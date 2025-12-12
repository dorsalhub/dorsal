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
from functools import cached_property
import logging
import os
from typing import Any, Iterable, Literal, Sequence, Type, TYPE_CHECKING, overload

import requests
from tqdm import tqdm
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
)
from rich.console import Console


from dorsal.version import __version__
from dorsal.client import DorsalClient
from dorsal.client.validators import FileIndexResponse
from dorsal.common import constants
from dorsal.common.auth import is_offline_mode
from dorsal.common.environment import is_jupyter_environment
from dorsal.common.exceptions import (
    BatchSizeError,
    DorsalError,
    DorsalClientError,
    DuplicateFileError,
)
from dorsal.file.cache import DorsalCache
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.model_runner import ModelRunner
from dorsal.file.utils.files import get_file_paths
from dorsal.session import get_shared_dorsal_client, get_shared_cache


if TYPE_CHECKING:
    from dorsal.file.validators.file_record import FileRecordStrict

logger = logging.getLogger(__name__)


def make_dorsalhub_file_url(file_hash: str) -> str:
    """Constructs a URL to a file record on DorsalHub."""
    base = constants.BASE_URL.rstrip("/")
    f_hash = file_hash.strip("/")
    return f"{base}/file/{f_hash}"


class MetadataReader:
    """A high-level utility for processing local files and indexing metadata.

    This class provides a convenient interface to the `ModelRunner` engine.
    It is designed to simplify the process of scanning local files, extracting
    rich metadata based on a configurable pipeline, and optionally pushing
    the results directly to a DorsalHub instance.

    Example:
        ```python
        from dorsal.file import MetadataReader

        # Initialize the reader
        reader = MetadataReader()

        # Use the reader to process a directory and get LocalFile objects
        local_files = reader.scan_directory("path/to/my_data")
        print(f"Processed {len(local_files)} files.")

        # Or, use the reader to process and immediately index a directory
        summary = reader.index_directory("path/to/my_data")
        print(f"Indexed {summary['total_records_accepted_by_api']} files to DorsalHub.")
        ```

    Args:
        client (DorsalClient, optional): An existing `DorsalClient` instance
            to use for API operations. If not provided, a shared instance
            will be used. Defaults to None.
        model_config (str | list, optional): A path to a custom JSON
            pipeline configuration file or a dictionary defining the pipeline
            for the ModelRunner. If None, the default pipeline is used.
            Defaults to None.
    """

    identity = f"dorsal.file.MetadataReader-{__version__}"

    def __init__(
        self,
        api_key: str | None = None,
        client: DorsalClient | None = None,
        model_config: str | list[dict[str, Any]] | None = "default",
        ignore_duplicates: bool = False,
        base_url: str = constants.BASE_URL,
        file_class: Type[LocalFile] = LocalFile,
        offline: bool = False,
    ):
        """
        Args:
            api_key: Optional API key for DorsalHub. If not provided, DorsalClient
                     will attempt to read it from environment variables.
            model_config: Optional configuration for the ModelRunner instance used for
                          local file processing.
            ignore_duplicates: If True, duplicate files (based on content hash)
                               encountered during directory indexing will be skipped.
                               If False (default), a DuplicateFileError will be raised.
            base_url: The base URL for the Dorsal API. Defaults to the common BASE_URL.
            file_class: Currently only `LocalFile` supported.
        """
        self.offline = offline or is_offline_mode()
        self._ignore_duplicates = ignore_duplicates
        self._model_runner = ModelRunner(pipeline_config=model_config)

        if self.offline:
            if client is not None:
                logger.warning("MetadataReader initialized in OFFLINE mode. The provided 'client' will be ignored.")
            self._client_instance = None
        else:
            self._client_instance = client

        self._api_key = api_key
        self._base_url = base_url
        self._file_class = file_class
        logger.debug("MetadataReader initialized.")

    @property
    def _cache(self) -> DorsalCache:
        """Dynamically retrieve the current valid shared cache."""
        return get_shared_cache()

    @property
    def _client(self) -> DorsalClient:
        """Lazily initializes/returns the DorsalClient instance.

        Priority:
        1. Use `self._client_instance` if already set (e.g., passed via __init__).
        2. If `self._api_key` is set, create a new, dedicated client and store it.
        3. If neither is set, fall back to the global shared client.

        Note: when 'passing on' the client, use `_client_instance` instead, as invoking this
              necessarily creates a DorsalClient or raises an error.
        """
        if self.offline:
            raise DorsalError("MetadataReader is in OFFLINE mode. Network operations are blocked.")
        if self._client_instance is None:
            if self._api_key is not None:
                logger.debug("Creating DorsalClient instance using provided api_key.")
                self._client_instance = DorsalClient(api_key=self._api_key)
            else:
                logger.debug("DorsalClient not present, getting shared instance...")
                self._client_instance = get_shared_dorsal_client(api_key=None)

        return self._client_instance

    def _run_models(self, file_path: str) -> FileRecordStrict:
        """
        Internal helper to run local file models on a given file path.

        Args:
            file_path: Path to the file to process.

        Returns:
            A FileRecordStrict object with generated metadata.

        Raises:
            FileNotFoundError: If the file_path does not exist.
            IOError: If the file cannot be read.
            DorsalClientError: For other errors during model execution, wrapped for consistency.
        """
        try:
            return self._model_runner.run(file_path=file_path)
        except FileNotFoundError:
            logger.error("File not found by ModelRunner: %s", file_path)
            raise
        except IOError as e:
            logger.error("IOError processing file %s: %s", file_path, e)
            raise
        except Exception as e:
            logger.error("Error running models on file %s: %s", file_path, e)
            raise DorsalClientError(
                message=f"Failed to process metadata for file: {file_path}.",
                original_exception=e,
            ) from e

    def _get_or_create_record(
        self, file_path: str, *, skip_cache: bool, overwrite_cache: bool = False
    ) -> FileRecordStrict:
        """
        Gets a file record from cache or creates it by running the ModelRunner.

        Args:
            file_path: Path to the file to process.
            skip_cache: If True, the cache check is bypassed and the ModelRunner is forced to run.

        Returns:
            FileRecordStrict object with generated metadata.

        Raises:
            FileNotFoundError: If the file_path does not exist.
            IOError: If the file cannot be read.
            DorsalClientError: For other errors during model execution.
        """
        from dorsal.file.validators.file_record import FileRecordStrict

        if not skip_cache and not overwrite_cache:
            abspath = os.path.abspath(file_path)
            try:
                modified_time = os.path.getmtime(abspath)
                cached_record = self._cache.get_record(path=abspath)

                if cached_record and cached_record.modified_time == modified_time:
                    logger.debug("Cache hit for file: %s", abspath)
                    record = FileRecordStrict.model_validate_json(cached_record.record_json)
                    record.source = "cache"
                    return record

            except FileNotFoundError:
                logger.error("File not found during cache check: %s", file_path)
                raise
            except Exception:
                logger.exception(
                    "Unexpected error during cache retrieval for '%s'. Proceeding to run models.",
                    file_path,
                )

        logger.debug("Cache miss or skipped for file: %s. Running models.", file_path)
        try:
            file_record = self._model_runner.run(file_path=file_path)

            if not skip_cache or overwrite_cache:
                abspath = os.path.abspath(file_path)
                modified_time = os.path.getmtime(abspath)
                self._cache.upsert_record(path=abspath, modified_time=modified_time, record=file_record)

            return file_record

        except FileNotFoundError:
            logger.error("File not found by ModelRunner: %s", file_path)
            raise
        except IOError as err:
            logger.error("IOError processing file %s: %s", file_path, err)
            raise
        except Exception as err:
            logger.error("Error running models on file %s: %s", file_path, err, exc_info=True)
            raise DorsalClientError(
                message=f"Failed to process metadata for file: {file_path}.",
                original_exception=err,
            ) from err

    def generate_processed_records_from_directory(
        self,
        dir_path: str,
        *,
        recursive: bool = False,
        limit: int | None = None,
        console: Console | None = None,
        palette: dict | None = None,
        skip_cache: bool = False,
        overwrite_cache: bool = False,
    ) -> tuple[list[FileRecordStrict], dict[str, str]]:
        """
        Scan directory, and sends each file through the ModelRunner pipeline.

        NOTE: When duplicates are ignored, this returned map intentionally contains only the path of the *first* file
              encountered for each hash

        Args:
            dir_path: Path to the directory to scan.
            recursive: If True, scans subdirectories recursively. Defaults to False.
            limit: Optional. top processing files once this many unique records have been generated.

        Returns:
            tuple[list[FileRecordStrict], dict[str, str]]:
                - list of unique `FileRecordStrict` objects.
                - mapping file content hashes to original file paths.

        Raises:
            FileNotFoundError: If `dir_path` does not exist.
            DuplicateFileError: If `self._ignore_duplicates` is False and duplicates found.
            DorsalClientError: For errors scanning directory or during local processing.
        """
        logger.debug(
            "Generating processed records from directory: '%s' (Recursive: %s, Ignore Duplicates: %s, Max: %s)",
            dir_path,
            recursive,
            self._ignore_duplicates,
            limit,
        )
        try:
            file_paths = get_file_paths(dir_path=dir_path, recursive=recursive)
        except FileNotFoundError:
            logger.error("Directory not found for generating records: %s", dir_path)
            raise
        except Exception as e:
            logger.error("Error scanning directory '%s' for record generation: %s", dir_path, e)
            raise DorsalClientError(
                message=f"An error occurred while scanning directory: {dir_path}.",
                original_exception=e,
            ) from e

        if not file_paths:
            logger.debug("No files found to process in directory: %s", dir_path)
            return [], {}
        if limit and len(file_paths) > limit:
            error_message = f"Number of records in the directory exceeds the limit: {len(file_paths)} > {limit}"
            raise DorsalError(error_message)

        file_hash_to_path_map: dict[str, str] = {}
        records_to_index_list: list[FileRecordStrict] = []
        processed_files_summary_local: dict[str, str] = {}

        logger.debug(
            "Generating metadata for up to %s file(s) from directory '%s' (Max: %s).",
            len(file_paths),
            dir_path,
            limit if limit is not None else "All",
        )

        rich_progress = None
        iterator: Iterable[str]
        if is_jupyter_environment():
            iterator = tqdm(file_paths, desc="Generating Metadata (Local)")
        elif console is not None:
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_columns = (
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette["progress_description"],
                ),
                BarColumn(bar_width=None, style=active_palette["progress_bar"]),
                TaskProgressColumn(style=active_palette["progress_percentage"]),
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
            task_id = rich_progress.add_task("Generating Metadata", total=len(file_paths))
            iterator = file_paths
        else:
            iterator = file_paths

        with rich_progress if rich_progress else open(os.devnull, "w"):
            for file_path in iterator:
                if limit is not None and len(records_to_index_list) >= limit:
                    logger.debug(
                        "Reached generation limit of %d records. Stopping further local processing for '%s'.",
                        limit,
                        dir_path,
                    )
                    break
                try:
                    file_record = self._get_or_create_record(
                        file_path=file_path, skip_cache=skip_cache, overwrite_cache=overwrite_cache
                    )
                    if not hasattr(file_record, "hash") or not file_record.hash:
                        logger.error(
                            "Skipping file %s: processed record is missing a hash.",
                            file_path,
                        )
                        processed_files_summary_local[file_path] = "error_missing_hash"
                        continue
                    if file_record.hash in file_hash_to_path_map:
                        original_file = file_hash_to_path_map[file_record.hash]
                        if self._ignore_duplicates:
                            logger.debug(
                                "Skipping duplicate: '%s' (original: '%s', hash: %s)",
                                file_path,
                                original_file,
                                file_record.hash,
                            )
                            processed_files_summary_local[file_path] = "skipped_duplicate_content"
                            continue
                        else:
                            logger.error(
                                "Duplicate file content: '%s' and '%s' (hash: %s). Not ignoring.",
                                file_path,
                                original_file,
                                file_record.hash,
                            )
                            raise DuplicateFileError(
                                message="Duplicate file content detected during local processing.",
                                file_paths=[file_path, original_file],
                            )
                    file_hash_to_path_map[file_record.hash] = file_path
                    records_to_index_list.append(file_record)
                    processed_files_summary_local[file_path] = "processed_for_indexing"
                except DuplicateFileError:
                    raise
                except (FileNotFoundError, IOError) as err:
                    logger.error("Skipping '%s': local access error: %s", file_path, err)
                    processed_files_summary_local[file_path] = f"error_local_access: {type(err).__name__}"
                except DorsalClientError as err:
                    logger.error("Skipping '%s': model execution error: %s", file_path, err)
                    processed_files_summary_local[file_path] = (
                        f"error_model_execution: {type(err.original_exception or err).__name__}"
                    )
                except Exception as err:
                    logger.exception(
                        "Unexpected error processing file '%s'. Skipping this file.",
                        file_path,
                    )
                    processed_files_summary_local[file_path] = f"error_unexpected: {type(err).__name__}"

                if rich_progress:
                    rich_progress.update(task_id, advance=1)

        logger.debug(
            "Completed local generation for '%s'. %d unique records generated.",
            dir_path,
            len(records_to_index_list),
        )
        return records_to_index_list, file_hash_to_path_map

    def index_directory(
        self,
        dir_path: str,
        *,
        recursive: bool = False,
        private: bool = True,
        skip_cache: bool = False,
    ) -> FileIndexResponse:
        """Scans, processes, and indexes all files in a directory to DorsalHub.

        This is an online method that performs a complete workflow:
        1. Scans the directory for files, handling recursion as specified.
        2. Runs the metadata extraction pipeline on each unique file.
        3. Indexes all resulting records to DorsalHub in a single batch API call.

        It handles duplicate file content within the directory based on the
        `ignore_duplicates` setting provided during the reader's initialization.

        Note:
            This method is designed for convenience and sends all discovered
            records in a single API request. It will raise a `BatchSizeError`
            if the number of unique files in the directory exceeds the API's
            batch limit. For very large directories, it is recommended to use
            the `dorsal.api.file.index_directory()` wrapper, which handles
            splitting the upload into multiple batches automatically.

        Example:
            ```python
            from dorsal.file import MetadataReader

            # Initialize a reader that will raise an error on duplicates.
            reader = MetadataReader(ignore_duplicates=False)

            try:
                response = reader.index_directory("path/to/project/assets", private=True)
                print(f"Indexing complete. {response.success} of {response.total} records indexed.")
            except Exception as e:
                print(f"An error occurred during indexing: {e}")
            ```

        Args:
            dir_path (str): The path to the directory to scan and index.
            recursive (bool, optional): If True, scans all subdirectories
                recursively. Defaults to False.
            private (bool, optional): If True, all file records will be created
                as private on DorsalHub. Defaults to True.

        Returns:
            FileIndexResponse: A response object from the API detailing the outcome
                of the batch indexing operation. The `file_path` attribute of
                each result item will be populated with its original local path.

        Raises:
            FileNotFoundError: If the `dir_path` does not exist.
            DuplicateFileError: If duplicate file content is detected and the
                reader was initialized with `ignore_duplicates=False`.
            BatchSizeError: If the number of unique files found exceeds the
                API's single-request batch limit.
            DorsalClientError: For any other error occurring during metadata
                extraction or the subsequent API call.
        """
        logger.debug(
            "MetadataReader.index_directory called: dir='%s', rec=%s, priv=%s",
            dir_path,
            recursive,
            private,
        )
        if self.offline:
            raise DorsalError("Cannot index directory: MetadataReader is in OFFLINE mode.")
        try:
            records_to_index_list, file_hash_to_path_map = self.generate_processed_records_from_directory(
                dir_path=dir_path,
                recursive=recursive,
                limit=constants.API_MAX_BATCH_SIZE + 1,
                skip_cache=skip_cache,
            )
        except (FileNotFoundError, ValueError, DuplicateFileError, DorsalClientError):
            raise

        if not records_to_index_list:
            logger.debug(
                "No unique files from '%s' to index via MetadataReader.index_directory.",
                dir_path,
            )
            return FileIndexResponse(total=0, success=0, error=0, unauthorized=0, results=[], created=False)

        if len(records_to_index_list) > constants.API_MAX_BATCH_SIZE:
            error_msg = (
                f"MetadataReader.index_directory: Directory '{dir_path}' yielded {len(records_to_index_list)} records "
                f"(processed up to {constants.API_MAX_BATCH_SIZE + 1}), exceeding the single API call limit of "
                f"{constants.API_MAX_BATCH_SIZE}. Use 'dorsal.api.file.index_directory' to automate batching."
            )
            logger.error(error_msg)
            raise BatchSizeError(error_msg)

        logger.debug(
            "Attempting to index %d unique file records from '%s' (Private: %s) in a single batch...",
            len(records_to_index_list),
            dir_path,
            private,
        )
        api_response: FileIndexResponse
        try:
            if private:
                api_response = self._client.index_private_file_records(file_records=records_to_index_list)
            else:
                api_response = self._client.index_public_file_records(file_records=records_to_index_list)
            logger.debug(
                "MetadataReader.index_directory: Indexing complete for '%s'. API: Total=%d, Success=%d, Error=%d, Unauthorized=%d",
                dir_path,
                api_response.total,
                api_response.success,
                api_response.error,
                api_response.unauthorized,
            )
        except DorsalClientError as err:
            logger.error(
                "MetadataReader.index_directory: API call failed for '%s'. Error: %s",
                dir_path,
                err,
            )
            raise
        except Exception as err:
            logger.exception(
                "MetadataReader.index_directory: Unexpected error during API call for '%s'.",
                dir_path,
            )
            raise DorsalClientError(
                message=f"Unexpected error during API indexing for directory '{dir_path}'.",
                original_exception=err,
            ) from err

        if file_hash_to_path_map and hasattr(api_response, "results") and api_response.results:
            for result_item in api_response.results:
                item_hash = getattr(result_item, "hash", None)
                if item_hash:
                    path = file_hash_to_path_map.get(item_hash)
                    if path and hasattr(result_item, "file_path"):
                        try:
                            result_item.file_path = path
                        except Exception as err_setattr:
                            logger.warning(
                                "Could not set file_path on result item for hash %s: %s",
                                item_hash,
                                err_setattr,
                            )
        return api_response

    def index_file(
        self, file_path: str, *, private: bool = True, skip_cache: bool = False, overwrite_cache: bool = False
    ) -> FileIndexResponse:
        """Processes a single file and immediately indexes it to DorsalHub.

        This method provides a complete "read and push" workflow for a single
        file. It runs the metadata extraction pipeline and then uploads the
        resulting record to DorsalHub.

        Example:
            ```python
            from dorsal.file import MetadataReader

            reader = MetadataReader()

            try:
                result = reader.index_file("path/to/important_document.docx")
                if result.success:
                    print("Document indexed successfully!")
            except Exception as e:
                print(f"Failed to index document: {e}")
            ```

        Args:
            file_path (str): The path to the local file to process and index.
            private (bool, optional): If True, the file record will be created
                as private on DorsalHub. Defaults to True.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default key. Defaults to None.

        Returns:
            FileIndexResponse: A response object from the API detailing the
                result of the indexing operation.

        Raises:
            DorsalClientError: If there's an error processing the file locally or an API error
                               during indexing.
            FileNotFoundError: If the file_path does not exist.
            IOError: If the file cannot be read by ModelRunner.
        """
        if self.offline:
            raise DorsalError("Cannot index file: MetadataReader is in OFFLINE mode.")
        logger.debug("Starting file indexing for: %s (Private: %s)", file_path, private)
        file_record = self._get_or_create_record(
            file_path=file_path, skip_cache=skip_cache, overwrite_cache=overwrite_cache
        )

        logger.debug("Indexing file '%s' (hash: %s) to DorsalHub...", file_path, file_record.hash)

        api_response: FileIndexResponse
        if private:
            api_response = self._client.index_private_file_records(file_records=[file_record])
        else:
            api_response = self._client.index_public_file_records(file_records=[file_record])

        log_status_msg = "processed by API"
        if api_response.results:
            result_item = api_response.results[0]
            result_item.file_path = file_path

            was_created = False
            if api_response.response and api_response.response.status_code == 201:
                was_created = True
            if was_created:
                log_status_msg = "newly indexed"
            elif api_response.success > 0:
                log_status_msg = "updated/existing"
            elif api_response.unauthorized > 0:
                log_status_msg = "unauthorized"
            elif api_response.error > 0:
                log_status_msg = "error during indexing attempt"

            logger.debug(
                "File '%s' %s on DorsalHub. URL: %s",
                file_path,
                log_status_msg,
                getattr(result_item, "url", "N/A"),
            )
        elif api_response.error > 0:
            logger.error("Failed to index file %s.", file_path)
        else:
            raw_resp_text = api_response.response.text[:200] if api_response.response else "N/A"
            logger.warning(
                "Unexpected response from server for file %s (no results or errors in structured response, "
                "but success/error counts are Total:%d, Success:%d, Error:%d, Unauthorized:%d). "
                "Raw response snippet: %s",
                file_path,
                api_response.total,
                api_response.success,
                api_response.error,
                api_response.unauthorized,
                raw_resp_text,
            )
        return api_response

    @overload
    def scan_directory(
        self,
        dir_path: str,
        *,
        recursive: bool = False,
        return_errors: Literal[False] = False,
        console: Console | None = None,
        palette: dict | None = None,
        skip_cache: bool = False,
        overwrite_cache: bool = False,
    ) -> list[LocalFile]: ...

    @overload
    def scan_directory(
        self,
        dir_path: str,
        *,
        recursive: bool = False,
        return_errors: Literal[True],
        console: Console | None = None,
        palette: dict | None = None,
        skip_cache: bool = False,
        overwrite_cache: bool = False,
    ) -> tuple[list[LocalFile], list[str]]: ...

    def scan_directory(
        self,
        dir_path: str,
        *,
        recursive: bool = False,
        return_errors: bool = False,
        console: Console | None = None,
        palette: dict | None = None,
        skip_cache: bool = False,
        overwrite_cache: bool = False,
    ) -> list[LocalFile] | tuple[list[LocalFile], list[str]]:
        """Scans a directory and runs the pipeline on all found files.

        This method discovers all files within a given directory (and optionally
        its subdirectories), runs the metadata extraction pipeline on each one,
        and returns a list of the resulting `LocalFile` objects. This is an
        offline operation.

        Example:
            ```python
            from dorsal.file import MetadataReader

            reader = MetadataReader()
            files_to_process = reader.scan_directory("path/to/images", recursive=True)

            print(f"Found and processed {len(files_to_process)} image files.")
            ```

        Args:
            dir_path (str): The path to the directory to scan.
            recursive (bool, optional): If True, scans all subdirectories
                recursively. Defaults to False.

        Returns:
            list[LocalFile]: initialized `LocalFile` instances.
            Or
            tuple:
            - list[LocalFile]: initialized `LocalFile` instances.
            - list[str]: errors (for cli output).
        """
        logger.debug("Starting directory read for: %s (Recursive: %s)", dir_path, recursive)
        try:
            file_paths = get_file_paths(dir_path=dir_path, recursive=recursive)
        except FileNotFoundError:
            logger.error("Directory not found: %s", dir_path)
            raise
        except Exception as e:
            logger.error("Error scanning directory %s: %s", dir_path, e)
            raise DorsalError(
                message=f"An error occurred while scanning directory: {dir_path}.",
                original_exception=e,
            ) from e

        if not file_paths:
            logger.debug("No files found to read in directory: %s", dir_path)
            return ([], []) if return_errors else []

        local_files: list[LocalFile] = []
        warnings: list[str] = []
        logger.debug("Found %d file(s). Processing with local models...", len(file_paths))

        rich_progress = None
        iterator: Iterable[str]
        if is_jupyter_environment():
            iterator = tqdm(file_paths, desc="Processing Files")
        elif console is not None:
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_columns = (
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette["progress_description"],
                ),
                BarColumn(bar_width=None, style=active_palette["progress_bar"]),
                TaskProgressColumn(style=active_palette["progress_percentage"]),
                MofNCompleteColumn(),
                TextColumn("•", style="dim"),
                TimeElapsedColumn(),
                TextColumn("•", style="dim"),
                TimeRemainingColumn(),
            )
            rich_progress = Progress(
                *progress_columns,
                console=console,
                transient=True,
                redirect_stdout=True,
                redirect_stderr=True,
            )
            task_id = rich_progress.add_task("Processing files", total=len(file_paths))
            iterator = file_paths
        else:
            iterator = file_paths

        with rich_progress if rich_progress else open(os.devnull, "w"):
            for file_path in iterator:
                try:
                    local_file_obj = self._file_class(
                        file_path=file_path,
                        client=self._client_instance,
                        use_cache=not skip_cache,
                        offline=self.offline,
                        overwrite_cache=overwrite_cache,
                    )
                    local_files.append(local_file_obj)
                except Exception as e:
                    msg = f"Skipping '{os.path.basename(file_path)}' due to processing error: {e}"
                    logger.error(msg)
                    warnings.append(msg)

                if rich_progress:
                    rich_progress.update(task_id, advance=1)

        logger.debug(
            "Successfully processed %d files into %s objects from directory %s.",
            len(local_files),
            self._file_class.__name__,
            dir_path,
        )

        if return_errors:
            return local_files, warnings
        return local_files

    def scan_file(self, file_path: str, *, skip_cache: bool, overwrite_cache: bool = False) -> LocalFile:
        """Runs the metadata extraction pipeline on a single file.

        This method processes a single local file through the configured
        `ModelRunner` pipeline, generating all its metadata. This is an
        offline operation that does not contact the DorsalHub API.

        Example:
            ```python
            from dorsal.file import MetadataReader

            reader = MetadataReader()
            try:
                local_file = reader.scan_file("path/to/document.pdf")
                print(f"Successfully processed: {local_file.name}")
                if local_file.pdf:
                    print(f"Page Count: {local_file.pdf.page_count}")
            except FileNotFoundError:
                print("The specified file does not exist.")
            ```

        Args:
            file_path (str): The path to the local file to process.

        Returns:
            LocalFile: An initialized `LocalFile` instance containing the rich
                metadata extracted by the pipeline.

        Raises:
            FileNotFoundError: If the file_path does not exist or is not a file.
            IOError: If there are issues reading the file.
            DorsalError: For other errors during model execution

        """
        logger.debug("Starting file read for: %s", file_path)
        try:
            local_file_obj = self._file_class(
                file_path=file_path,
                client=self._client_instance,
                use_cache=not skip_cache,
                overwrite_cache=overwrite_cache,
                offline=self.offline,
            )
        except FileNotFoundError:
            logger.error("File not found for reading: %s", file_path)
            raise
        except IOError as e:
            logger.error("IOError reading file %s: %s", file_path, e)
            raise
        except Exception as e:
            logger.error("Failed to read/process file %s: %s", file_path, e)
            raise DorsalError(
                message=f"Failed to process local file: {file_path}.",
                original_exception=e,
            ) from e

        logger.debug(
            "Successfully processed file '%s' into a %s object (hash: %s).",
            file_path,
            self._file_class.__name__,
            local_file_obj.hash,
        )
        return local_file_obj
