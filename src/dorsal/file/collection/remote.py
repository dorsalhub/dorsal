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

import json
import logging
import os
import tempfile
from typing import Self, Iterable

from rich.console import Console
from tqdm import tqdm

from dorsal.file.collection.base import _BaseFileCollection
from dorsal.client import DorsalClient
from dorsal.file.dorsal_file import DorsalFile
from dorsal.session import get_shared_dorsal_client
from dorsal.common.exceptions import DorsalClientError
from dorsal.common.environment import is_jupyter_environment
from dorsal.common.validators import Pagination
from dorsal.file.validators.file_record import FileRecordDateTime
from dorsal.file.validators.collection import (
    FileCollection,
    HydratedSingleCollectionResponse,
    SingleCollectionResponse,
)

logger = logging.getLogger(__name__)

RECORDS_PER_CHUNK_FILE = 10_000
PAGINATION_RECORD_LIMIT = 10_000


class DorsalFileCollection(_BaseFileCollection):
    """
    Represents and interacts with a remote File Collection on DorsalHub.
    """

    def __init__(
        self,
        collection_id: str,
        *,
        client: DorsalClient | None = None,
        _metadata: FileCollection | None = None,
        _files: list[DorsalFile] | None = None,
        _pagination: Pagination | None = None,
    ):
        """
        Initializes a remote file collection.

        Args:
            collection_id: The unique ID of the collection to fetch.
            client: An optional DorsalClient instance.
        """
        self._client: DorsalClient = client or get_shared_dorsal_client()
        self.collection_id: str = collection_id

        if _metadata and _files is not None and _pagination:
            self.metadata = _metadata
            self.files = _files
            self.pagination = _pagination
        else:
            response = self._client.get_collection(self.collection_id, hydrate=True)
            self._update_from_response(response)

        super().__init__(
            files=self.files,
            source_info={"type": "remote", "collection_id": self.collection_id},
        )
        self._is_populated = False
        logger.info(
            f"Initialized collection '{self.metadata.name}' ({self.collection_id}) with {len(self.files)} files."
        )

    @classmethod
    def from_id(cls, collection_id: str, client: DorsalClient | None = None) -> Self:
        """Explicitly create a DorsalFileCollection from a collection ID."""
        return cls(collection_id, client=client)

    @classmethod
    def from_id_metadata_only(cls, collection_id: str, client: DorsalClient | None = None) -> Self:
        """Create collection with no files. Useful for management operations via the CLI."""
        client_instance = client or get_shared_dorsal_client()

        response = client_instance.get_collection(collection_id, hydrate=False, per_page=0)

        instance = cls(
            collection_id=collection_id,
            client=client_instance,
            _metadata=response.collection,
            _files=[],
            _pagination=response.pagination,
        )
        return instance

    @classmethod
    def list_collections(cls, client: DorsalClient | None = None, page: int = 1, per_page: int = 50) -> list[Self]:
        """
        List available remote collections for the user and return them as (unpopulated) DorsalFileCollection instances.
        """
        client_instance = client or get_shared_dorsal_client()
        response = client_instance.list_collections(page=page, per_page=per_page)

        collections = []
        for collection_metadata in response.records:
            initial_pagination = Pagination(
                current_page=0,
                record_count=collection_metadata.file_count,
                page_count=0,
                per_page=0,
                has_next=collection_metadata.file_count > 0,
                has_prev=False,
                start_index=0,
                end_index=0,
            )

            instance = cls(
                collection_id=collection_metadata.collection_id,
                client=client_instance,
                _metadata=collection_metadata,
                _files=[],
                _pagination=initial_pagination,
            )
            collections.append(instance)

        return collections

    @classmethod
    def from_remote(
        cls,
        collection_id: str,
        client: DorsalClient | None = None,
        use_export: bool = False,
        poll_interval: int = 5,
        timeout: int | None = 3600,
        console: "Console | None" = None,
        palette: dict | None = None,
    ) -> Self:
        """
        Creates and returns a new, fully populated DorsalFileCollection.

        This is a convenience method that initializes the collection and
        immediately calls .populate().
        """
        instance = cls(collection_id, client=client)
        instance.populate(
            use_export=use_export,
            poll_interval=poll_interval,
            timeout=timeout,
            console=console,
            palette=palette,
        )
        return instance

    def populate(
        self,
        use_export: bool = False,
        poll_interval: int = 5,
        timeout: int | None = 3600,
        console: "Console | None" = None,
        palette: dict | None = None,
    ) -> Self:
        """
        Populates the collection with all of its file records from the remote server.
        """
        logger.info(f"Requesting to fully populate collection '{self.collection_id}'...")

        collection_metadata = self.metadata
        total_files = collection_metadata.file_count
        dorsal_files: list[DorsalFile] = []

        if total_files > PAGINATION_RECORD_LIMIT and not use_export:
            raise DorsalClientError(
                f"Collection has {total_files} files, which exceeds the pagination limit of {PAGINATION_RECORD_LIMIT}. "
                f"To populate a large collection, you must use the server-side export feature. "
                f"Please re-run with `.populate(use_export=True)`."
            )

        if total_files > PAGINATION_RECORD_LIMIT and use_export:
            logger.info(f"Collection is large ({total_files} files). Using efficient server-side export...")
            with tempfile.NamedTemporaryFile(mode="w+", delete=True, suffix=".json") as tmp:
                self._client.export_collection(
                    collection_id=self.collection_id,
                    output_path=tmp.name,
                    poll_interval=poll_interval,
                    timeout=timeout,
                    console=console,
                    palette=palette,
                )
                tmp.seek(0)
                export_data = json.load(tmp)
            files_data = export_data.get("results", [])
            dorsal_files = [DorsalFile.from_record(FileRecordDateTime(**data), self._client) for data in files_data]
        else:
            logger.info(f"Collection has {total_files} files. Using paginated download...")
            per_page = 500
            total_pages = (total_files + per_page - 1) // per_page
            page_iterator = range(1, total_pages + 1)
            rich_progress = None

            iterator: Iterable[int]
            if is_jupyter_environment():
                iterator = tqdm(page_iterator, desc="Fetching pages", total=total_pages)
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
                    BarColumn(
                        bar_width=None,
                        style=active_palette.get("progress_bar", "default"),
                    ),
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
                    redirect_stderr=True,
                )
                task_id = rich_progress.add_task("Fetching pages...", total=total_pages)
                iterator = page_iterator
            else:
                iterator = page_iterator

            with rich_progress if rich_progress else open(os.devnull, "w"):
                for page_num in iterator:
                    response = self._client.get_collection(
                        collection_id=self.collection_id,
                        page=page_num,
                        per_page=per_page,
                        hydrate=True,
                    )
                    if not response.files:
                        break
                    dorsal_files.extend([DorsalFile.from_record(rec, self._client) for rec in response.files])
                    if rich_progress:
                        rich_progress.update(task_id, advance=1)

        self.files = dorsal_files
        self.pagination = Pagination(
            current_page=1,
            record_count=total_files,
            page_count=1,
            per_page=total_files,
            has_next=False,
            has_prev=False,
            start_index=1 if total_files > 0 else 0,
            end_index=total_files,
        )

        self._is_populated = True

        logger.info(f"Successfully populated collection with {len(self.files)} file records.")
        return self

    def _check_if_populated(self, force: bool):
        """
        Helper to check population status.
        ...
        """
        is_incomplete = len(self.files) < self.metadata.file_count

        if not self._is_populated and is_incomplete and not force:
            raise DorsalClientError(
                f"This collection is not fully populated. The currently loaded page ({len(self.files)} files) "
                f"does not contain the entire collection ({self.metadata.file_count} files). "
                "Calling this method would produce an incomplete export. "
                "To export the complete collection, first call the .populate() method. "
                "To proceed with exporting only the currently loaded files, re-run with force=True."
            )

        if not self._is_populated and is_incomplete and force:
            logger.warning(
                "Exporting an incomplete DorsalFileCollection. The output will only contain "
                "the %d of %d total files that are currently loaded.",
                len(self.files),
                self.metadata.file_count,
            )

    def to_dict(
        self,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
        force: bool = False,
    ) -> dict:
        """
        Serializes the collection to a dictionary.

        Raises an error if the collection is not fully populated, unless `force=True`.
        """
        self._check_if_populated(force)
        return super().to_dict(by_alias=by_alias, exclude_none=exclude_none, exclude=exclude)

    def to_json(
        self,
        filepath: str | None = None,
        indent: int | None = 2,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
        force: bool = False,
    ) -> str | None:
        """
        Saves the collection data to a JSON file or returns it as a string.

        Raises an error if the collection is not fully populated, unless `force=True`.
        """
        self._check_if_populated(force)
        return super().to_json(
            filepath=filepath,
            indent=indent,
            by_alias=by_alias,
            exclude_none=exclude_none,
            exclude=exclude,
        )

    def to_csv(self, file_path: str, force: bool = False) -> None:
        """
        Exports the collection's metadata to a CSV file.

        Raises an error if the collection is not fully populated, unless `force=True`.
        """
        self._check_if_populated(force)
        super().to_csv(file_path=file_path)

    def to_dataframe(self, force: bool = False):  # pragma: no cover
        """
        Exports the collection's metadata to a pandas DataFrame.

        Raises an error if the collection is not fully populated, unless `force=True`.
        """
        self._check_if_populated(force)
        return super().to_dataframe()

    def to_sqlite(self, db_path: str, table_name: str = "files", force: bool = False) -> None:
        """
        Exports the collection's data to a table in an SQLite database.

        Raises an error if the collection is not fully populated, unless `force=True`.
        """
        self._check_if_populated(force)
        super().to_sqlite(db_path=db_path, table_name=table_name)

    def _update_from_response(self, response: SingleCollectionResponse | HydratedSingleCollectionResponse):
        """Helper to update the collection's state from an API response."""
        self.metadata = response.collection
        self.pagination = response.pagination
        if isinstance(response, HydratedSingleCollectionResponse):
            self.files = [DorsalFile.from_record(rec, self._client) for rec in response.files]
        else:
            if response.files:
                logger.warning("Received a non-hydrated response with file stubs; they will be ignored.")
            self.files = []

    def fetch_page(self, page: int) -> Self:
        """
        Fetches a specific page of file records, updating the collection in-place.
        ...
        """
        if not self.pagination or page < 1 or page > self.pagination.page_count:
            raise ValueError(f"Page number must be between 1 and {getattr(self.pagination, 'page_count', 1)}")

        response = self._client.get_collection(
            self.collection_id,
            page=page,
            per_page=self.pagination.per_page,
            hydrate=True,
        )
        self._update_from_response(response)
        logger.info(
            f"Fetched page {page}. Displaying items {self.pagination.start_index} to {self.pagination.end_index}."
        )
        return self

    def next_page(self) -> Self:
        if not self.pagination or not self.pagination.has_next:
            logger.warning("Already on the last page.")
            return self
        return self.fetch_page(self.pagination.current_page + 1)

    def previous_page(self) -> Self:
        if not self.pagination or not self.pagination.has_prev:
            logger.warning("Already on the first page.")
            return self
        return self.fetch_page(self.pagination.current_page - 1)

    def add_files(self, hashes: list[str]) -> dict:
        """Adds a list of files to this remote collection by their hash."""
        response = self._client.add_files_to_collection(self.collection_id, hashes)
        self.refresh()
        return response.model_dump()

    def remove_files(self, hashes: list[str]) -> dict:
        """
        Removes a list of files from this remote collection by their hash.
        This does not delete the file records themselves from DorsalHub.
        """
        response = self._client.remove_files_from_collection(self.collection_id, hashes)
        self.refresh()
        return response.model_dump()

    def update(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> Self:
        """Updates the metadata of the remote collection."""
        updated_metadata = self._client.update_collection(
            collection_id=self.collection_id, name=name, description=description
        )
        self.metadata = updated_metadata
        return self

    def make_public(self) -> str:
        """Makes the remote collection public."""
        response = self._client.make_collection_public(self.collection_id)
        self.refresh()
        return response.location_url

    def make_private(self) -> str:
        """Makes the remote collection private."""
        response = self._client.make_collection_private(self.collection_id)
        self.refresh()
        return response.location_url

    def delete(self) -> None:
        """Deletes the entire remote collection."""
        self._client.delete_collections(collection_ids=[self.collection_id])
        logger.info(f"Collection '{self.metadata.name}' ({self.collection_id}) has been deleted.")

    def refresh(self) -> Self:
        """Refreshes the collection's metadata and re-fetches the current page."""
        current_page = self.pagination.current_page if self.pagination else 1
        return self.fetch_page(current_page)
