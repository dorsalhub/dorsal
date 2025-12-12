# Copyright 2025 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations
import datetime
import logging
import os
import time
from typing import (
    Iterator,
    Type,
    TYPE_CHECKING,
    cast,
    Iterable,
    Sequence,
    Any,
)

from rich.console import Console
from tqdm import tqdm

from dorsal.file.collection.base import _BaseFileCollection
from dorsal.client import DorsalClient
from dorsal.common.auth import is_offline_mode
from dorsal.common.environment import is_jupyter_environment
from dorsal.common.exceptions import (
    DorsalError,
    DorsalClientError,
    InvalidTagError,
    SyncConflictError,
)
from dorsal.common.constants import API_MAX_BATCH_SIZE
from dorsal.file.dorsal_file import LocalFile, _DorsalFile
from dorsal.file.metadata_reader import MetadataReader
from dorsal.session import get_shared_dorsal_client
from dorsal.file.validators.file_record import FileRecordStrict

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dorsal.file.collection.remote import DorsalFileCollection
    from dorsal.file.validators.file_record import NewFileTag, FileRecord


def _get_source_paths(source_info: dict) -> list[str]:
    """Recursively extracts all source directory paths from a source_info dictionary."""
    paths = []
    if source_info.get("type") == "local" and source_info.get("path"):
        paths.append(source_info["path"])
    elif source_info.get("type") == "merged":
        for source in source_info.get("sources", []):
            paths.extend(_get_source_paths(source))
    return list(dict.fromkeys(paths))


class LocalFileCollection(_BaseFileCollection):
    """
    A high-level interface to create and manage a collection of local files.

    This class can be initialized from a directory path, which it will scan,
    or from a pre-existing list of LocalFile objects. It provides methods for
    pushing file metadata to DorsalHub, creating remote collections, and
    performing bulk operations like tagging.
    """

    def __init__(
        self,
        source: str | list[LocalFile] | None = None,
        *,
        files: Sequence[_DorsalFile] | None = None,
        recursive: bool = False,
        client: DorsalClient | None = None,
        model_runner_pipeline: str | list[dict[str, Any]] | None = "default",
        file_class: Type[LocalFile] = LocalFile,
        source_info: dict | None = None,
        palette: dict | None = None,
        console: Console | None = None,
        use_cache: bool = True,
        overwrite_cache: bool = False,
        offline: bool = False,
    ):
        """
        Initializes the LocalFileCollection.

        The constructor can either scan a directory to build a new collection of
        files or wrap an existing list of LocalFile objects.

        Args:
            source (Union[str, list[LocalFile]]): A directory path to scan or a
                pre-populated list of LocalFile objects.
            recursive (bool): If scanning a directory, whether to include
                subdirectories. Defaults to False.
            client (DorsalClient | None): An optional pre-initialized DorsalClient
                instance to use for API operations. Defaults to None.
            model_runner_pipeline (Union[dict, str, None]): An optional custom
                model runner pipeline configuration. Defaults to None.
            file_class (Type[LocalFile]): The class to use when instantiating
                files from disk. Defaults to LocalFile.
            source_info (dict | None): Optional metadata about the source. Used
                internally when merging collections. Defaults to None.
            palette (dict | None): A color palette for Rich progress bars.
            console (Console | None): A Rich Console for progress display.
            use_cache (bool): Whether to use the local cache for hashing and
                metadata. Defaults to True.
        """
        self.offline = offline or is_offline_mode()
        self._client = client
        self.warnings: list[str] = []
        self._file_class = file_class

        self.remote_collection_id: str | None = None
        self.remote_last_modified: datetime.datetime | None = None
        self.remote_file_count: int | None = None

        final_files: Sequence[_DorsalFile]
        final_source_info: dict | None = source_info

        if files is not None:
            final_files = files
        elif isinstance(source, str):
            path = source
            reader = MetadataReader(
                client=self._client, model_config=model_runner_pipeline, file_class=file_class, offline=self.offline
            )
            scan_files, self.warnings = reader.scan_directory(
                dir_path=source,
                recursive=recursive,
                return_errors=True,
                console=console,
                palette=palette,
                skip_cache=not use_cache,
                overwrite_cache=overwrite_cache,
            )
            final_files = scan_files
            if self.warnings:
                logger.warning(
                    f"Initialized collection from '{path}', but {len(self.warnings)} "
                    f"files could not be processed. Check the .warnings attribute for details."
                )
            if not final_source_info:
                final_source_info = {
                    "type": "local",
                    "path": path,
                    "recursive": recursive,
                    "scan_started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
        elif isinstance(source, list):
            final_files = source
        else:
            raise ValueError("Either 'source' or 'files' must be provided to LocalFileCollection.")

        super().__init__(files=final_files, source_info=final_source_info)
        self._is_populated = True

    def __add__(self, other: "_BaseFileCollection") -> "LocalFileCollection":
        """
        Combines two LocalFileCollection objects into a new one.
        """
        if not isinstance(other, LocalFileCollection):
            raise TypeError("Addition is only supported between two LocalFileCollection objects.")

        combined_files_map = {f.hash: f for f in self.files}
        combined_files_map.update({f.hash: f for f in other.files})

        new_source_info = {
            "type": "merged",
            "operation": "addition",
            "sources": [self.source_info, other.source_info],
        }
        return self.__class__(
            source=cast(list[LocalFile], list(combined_files_map.values())),
            source_info=new_source_info,
        )

    def __sub__(self, other: _BaseFileCollection) -> LocalFileCollection:
        """
        Creates a new LocalFileCollection by removing files present in the
        second collection from the first.
        """
        if not isinstance(cast(object, other), _BaseFileCollection):
            return NotImplemented

        other_hashes = {f.hash for f in other.files}
        resulting_files = [f for f in self.files if f.hash not in other_hashes]

        new_source_info = {
            "type": "merged",
            "operation": "subtraction",
            "sources": [self.source_info, other.source_info],
        }
        return self.__class__(source=cast(list[LocalFile], resulting_files), source_info=new_source_info)

    def add_tags(
        self,
        tags: list[dict | NewFileTag],
        api_key: str | None = None,
        console: Console | None = None,
        palette: dict | None = None,
    ) -> LocalFileCollection:
        """
        Adds one or more tags to every file in the collection.

        This method first validates all tags against the server in a single
        batch, then applies them locally to each file object. The local changes
        must be synchronized with DorsalHub by calling `.push()`.

        Args:
            tags (list[dict | NewFileTag]): A list of tags to add. Each tag can
                be a dictionary or a `NewFileTag` object.
            api_key (str | None): An optional API key for validation.
            console (Console | None): A Rich Console for progress display.
            palette (dict | None): A color palette for the progress bar.

        Returns:
            The `LocalFileCollection` instance for method chaining.
        """
        from dorsal.file.validators.file_record import NewFileTag

        if not self.files:
            logger.warning("Cannot add tags: the collection is empty.")
            return self

        if not tags:
            logger.warning("No tags provided to add.")
            return self

        if self._client is None:
            self._client = get_shared_dorsal_client(api_key=api_key)

        if self.offline:
            logger.info("Step 1/2: *SKIPPING* tag validation - Offline Mode")
        else:
            logger.info(f"Step 1/2: Validating {len(tags)} tags in a single batch...")
            try:
                tags_to_validate = [tag if isinstance(tag, NewFileTag) else NewFileTag(**tag) for tag in tags]
            except Exception as e:
                raise DorsalClientError(f"Failed to parse input tags: {e}") from e

            validation_result = self._client.validate_tag(file_tags=tags_to_validate, api_key=api_key)

            if not validation_result.valid:
                error_msg = validation_result.message or "Tag validation failed with no specific message."
                logger.error(f"Tag validation failed: {error_msg}")
                raise InvalidTagError(error_msg)

            logger.info("Tag validation successful.")

        logger.info(f"Step 2/2: Applying {len(tags_to_validate)} tags to {len(self.files)} files...")

        rich_progress = None
        iterator: Iterable[_DorsalFile]
        if is_jupyter_environment():
            iterator = tqdm(self.files, desc="Applying tags")
        elif console:
            from rich.progress import (
                Progress,
                BarColumn,
                TaskProgressColumn,
                MofNCompleteColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_columns = (
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette.get("progress_description", "default"),
                ),
                BarColumn(bar_width=None, style=active_palette.get("progress_bar", "default")),
                TaskProgressColumn(style=active_palette.get("progress_percentage", "default")),
                MofNCompleteColumn(),
                TextColumn("•", style="dim"),
                TimeElapsedColumn(),
                TextColumn("•", style="dim"),
                TimeRemainingColumn(),
            )
            rich_progress = Progress(
                *progress_columns,
                console=console,
                redirect_stdout=True,
                transient=True,
                redirect_stderr=True,
            )
            task_id = rich_progress.add_task("Applying tags...", total=len(self.files))
            iterator = self.files
        else:
            iterator = self.files

        with rich_progress if rich_progress else open(os.devnull, "w"):
            for file in iterator:
                if isinstance(file, LocalFile):
                    for tag in tags_to_validate:
                        try:
                            file._add_local_tag(
                                name=tag.name,
                                value=tag.value,
                                private=tag.private,
                            )
                        except Exception as e:
                            logger.warning(f"Could not apply tag '{tag.name}' to file '{file.name}': {e}")
                if rich_progress:
                    rich_progress.update(task_id, advance=1)

        logger.info("Batch tagging complete.")
        return self

    def push(
        self,
        private: bool = True,
        api_key: str | None = None,
        console: "Console | None" = None,
        palette: dict | None = None,
    ) -> dict:
        """Pushes all file records in the collection to DorsalHub for indexing."""
        if self._client is None:
            self._client = get_shared_dorsal_client(api_key=api_key)

        all_records = [f.model for f in self.files if isinstance(f.model, FileRecordStrict)]
        summary: dict[str, Any] = {
            "total_records_in_collection": len(self.files),
            "total_records_to_push": len(all_records),
            "successful_api_batches": 0,
            "failed_api_batches": 0,
            "total_records_accepted_by_api": 0,
            "batch_processing_details": [],
        }

        if not all_records:
            logger.info("No valid records in the collection to push.")
            return summary

        batches = [all_records[i : i + API_MAX_BATCH_SIZE] for i in range(0, len(all_records), API_MAX_BATCH_SIZE)]

        rich_progress = None
        iterator: Iterable[list[FileRecordStrict]]
        if is_jupyter_environment():
            iterator = tqdm(batches, desc="Pushing batches")
        elif console:
            from rich.progress import (
                Progress,
                BarColumn,
                TaskProgressColumn,
                MofNCompleteColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_columns = (
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette.get("progress_description", "default"),
                ),
                BarColumn(bar_width=None, style=active_palette.get("progress_bar", "default")),
                TaskProgressColumn(style=active_palette.get("progress_percentage", "default")),
                MofNCompleteColumn(),
                TextColumn("•", style="dim"),
                TimeElapsedColumn(),
                TextColumn("•", style="dim"),
                TimeRemainingColumn(),
            )
            rich_progress = Progress(
                *progress_columns,
                console=console,
                redirect_stdout=True,
                transient=True,
                redirect_stderr=True,
            )
            task_id = rich_progress.add_task("Pushing batches...", total=len(batches))
            iterator = batches
        else:
            logger.debug("Starting push of %d batches...", len(batches))
            iterator = batches

        start_time = time.perf_counter()
        with rich_progress if rich_progress else open(os.devnull, "w"):
            for i, batch in enumerate(iterator):
                detail: dict[str, Any] = {
                    "batch_number": i + 1,
                    "records_in_batch": len(batch),
                }
                try:
                    if private:
                        response = self._client.index_private_file_records(file_records=batch)
                    else:
                        response = self._client.index_public_file_records(file_records=batch)

                    summary["successful_api_batches"] = cast(int, summary["successful_api_batches"]) + 1
                    summary["total_records_accepted_by_api"] = (
                        cast(int, summary["total_records_accepted_by_api"]) + response.success
                    )
                    detail.update({"status": "success", "response": response.model_dump()})
                except DorsalClientError as e:
                    summary["failed_api_batches"] = cast(int, summary["failed_api_batches"]) + 1
                    detail.update(
                        {
                            "status": "failure",
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        }
                    )

                cast(list, summary["batch_processing_details"]).append(detail)
                if rich_progress:
                    rich_progress.update(task_id, advance=1)

        duration = time.perf_counter() - start_time
        if not console:
            logger.debug("Push finished in %.3fs.", duration)

        return summary

    def sync_with_remote(
        self,
        api_key: str | None = None,
        force: bool = False,
        poll_interval: int = 5,
        timeout: int | None = 300,
    ) -> dict:
        """
        Synchronizes the linked remote collection to exactly match this local collection.
        ...
        """
        if not self.remote_collection_id:
            raise DorsalError(
                "Synchronization requires a linked remote collection. Use `create_remote_collection()` to create and link one first."
            )

        if self._client is None:
            self._client = get_shared_dorsal_client(api_key=api_key)

        logger.debug(f"Starting synchronization for remote collection: {self.remote_collection_id}")

        logger.debug("Step 1/3: Performing pre-flight check...")
        remote_state = self._client.get_collection(self.remote_collection_id, api_key=api_key, hydrate=False)

        is_state_synced = (
            remote_state.collection.date_modified == self.remote_last_modified
            and remote_state.collection.file_count == self.remote_file_count
        )

        if not is_state_synced and not force:
            raise SyncConflictError(
                "Sync failed: The remote collection has been modified since the last synchronization. To proceed and overwrite the remote changes, run the command again with `force=True`."
            )
        elif not is_state_synced and force:
            logger.warning("`force=True` provided. Overwriting remote changes.")
        else:
            logger.debug("Pre-flight check passed. Remote collection is in expected state.")

        logger.info("Step 2/3: Pushing local file records to ensure they exist on the server...")
        is_remote_private = remote_state.collection.is_private
        push_summary = self.push(private=is_remote_private, api_key=api_key)

        num_to_push = cast(int, push_summary.get("total_records_to_push", 0))
        num_accepted = cast(int, push_summary.get("total_records_accepted_by_api", 0))
        if not is_remote_private and num_accepted != num_to_push:
            raise DorsalClientError(
                f"Sync aborted: Not all local files could be indexed publicly ({num_accepted}/{num_to_push}). Cannot sync with a public collection."
            )

        logger.info("Step 3/3: Sending complete hash list to the server for synchronization...")
        local_hashes = [f.hash for f in self.files if f.hash]

        sync_response = self._client.sync_collection_by_hash(
            collection_id=self.remote_collection_id,
            hashes=local_hashes,
            api_key=api_key,
            poll_interval=poll_interval,
            timeout=timeout,
        )

        final_remote_state = self._client.get_collection(self.remote_collection_id, api_key=api_key, hydrate=False)
        self.remote_last_modified = final_remote_state.collection.date_modified
        self.remote_file_count = final_remote_state.collection.file_count

        logger.info(
            f"Synchronization complete. Added: {sync_response.added_count}, Removed: {sync_response.removed_count}, Unchanged: {sync_response.unchanged_count}."
        )
        return sync_response.model_dump()

    def create_remote_collection(
        self,
        name: str,
        description: str | None = None,
        is_private: bool = True,
        api_key: str | None = None,
    ) -> "DorsalFileCollection":
        """
        Creates a new remote collection on DorsalHub, populates it with the
        files from this local collection, and links the two.

        Note: `is_private` here refers to the the local collection, and most importantly the *files* within the collection.
              The collection itself cannot be created as `public` - but it can be made public after.
        """
        from dorsal.file.collection.remote import DorsalFileCollection

        if self._client is None:
            self._client = get_shared_dorsal_client(api_key=api_key)

        logger.info("Step 1/3: Pushing file records to DorsalHub...")
        push_summary = self.push(private=is_private, api_key=api_key)
        if cast(int, push_summary["total_records_accepted_by_api"]) == 0:
            raise DorsalClientError("No files were successfully indexed. Cannot create collection.")
        logger.info("File records pushed successfully.")

        logger.info(f"Step 2/3: Creating remote collection '{name}'...")

        source_paths = _get_source_paths(self.source_info)
        collection_source = {
            "caller": "dorsal.LocalFileCollection",
            "local_directories": source_paths,
            "comment": "Created via the Dorsal Python library.",
        }

        remote_collection_meta = self._client.create_collection(
            name=name,
            description=description,
            is_private=is_private,
            source=collection_source,
        )
        collection_id = remote_collection_meta.collection_id

        logger.info("Step 3/3: Adding files to the new collection...")
        file_hashes = [file.hash for file in self.files if file.hash][:API_MAX_BATCH_SIZE]
        if len(file_hashes) > API_MAX_BATCH_SIZE:
            logger.warning(
                "This collection exceeds the max batch size."
                f"Only the first {API_MAX_BATCH_SIZE} records will be included initially."
                "You should run `sync_with_remote` after the collection is created to add the rest."
            )
        add_response = self._client.add_files_to_collection(collection_id=collection_id, hashes=file_hashes)
        logger.info(
            f"Successfully added {add_response.added_count} files to collection '{name}'. "
            f"({add_response.duplicate_count} duplicates ignored)."
        )

        collection_response = self._client.get_collection(collection_id=collection_id, per_page=0, hydrate=False)
        remote_collection = collection_response.collection

        self.remote_collection_id = collection_id
        self.remote_last_modified = remote_collection.date_modified
        self.remote_file_count = remote_collection.file_count
        logger.info("Remote collection created and linked. Local state updated.")

        return DorsalFileCollection(collection_id=collection_id, client=self._client)

    def to_dict(
        self,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
    ) -> dict:
        """
        Serializes the local collection to a dictionary, augmenting each file
        record with essential local filesystem attributes.
        """
        data = super().to_dict(by_alias=by_alias, exclude_none=exclude_none, exclude=exclude)

        for i, file_obj in enumerate(self.files):
            if i < len(data["results"]):
                if isinstance(file_obj, LocalFile):
                    data["results"][i]["local_attributes"] = {
                        "date_modified": file_obj.date_modified,
                        "date_created": file_obj.date_created,
                        "file_path": file_obj._file_path,
                    }
        return data
