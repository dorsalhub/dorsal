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
from collections import defaultdict
import datetime
import html
import json
import logging
import os
import pathlib
import stat
from string import Template
import sys
import time
from typing import (
    Any,
    Iterable,
    Literal,
    Sequence,
    TypedDict,
    Type,
    TYPE_CHECKING,
    cast,
    overload,
)

from pydantic import BaseModel
import tomlkit

from dorsal.common import constants
from dorsal.common.environment import is_jupyter_environment
from dorsal.common.exceptions import (
    ConflictError,
    DorsalClientError,
    DorsalConfigError,
    DorsalError,
    NotFoundError,
)
from dorsal.file.dependencies import (
    make_file_extension_dependency,
    make_media_type_dependency,
    make_file_name_dependency,
    make_file_size_dependency,
)
from dorsal.file.utils.cache import get_cached_hash
from dorsal.file.utils.hashes import hash_string_validator
from dorsal.file.utils import QuickHasher, get_quick_hash, get_sha256_hash
from dorsal.file.utils.infer_mediatype import get_media_type
from dorsal.file.utils.reports import resolve_template_path
from dorsal.file.utils.size import get_filesize, human_filesize, parse_filesize
from dorsal.session import get_shared_cache, get_metadata_reader

if TYPE_CHECKING:
    from rich.console import Console
    from rich.progress import Progress
    from dorsal.client import DorsalClient
    from dorsal.client.validators import (
        FileDeleteResponse,
        FileIndexResponse,
        FileTagResponse,
    )
    from dorsal.common.model import AnnotationModel
    from dorsal.common.validators import JsonSchemaValidator
    from dorsal.file.configs.model_runner import ModelRunnerDependencyConfig
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.dorsal_file import DorsalFile, LocalFile
    from dorsal.file.metadata_reader import MetadataReader
    from dorsal.file.validators.file_record import (
        DeletionScope,
        FileRecord,
        FileRecordStrict,
        FileSearchResponse,
        UserFileSearchQuery,
    )

__all__ = [
    "identify_file",
    "get_dorsal_file_record",
    "index_file",
    "index_directory",
    "scan_file",
    "scan_directory",
    "delete_private_dorsal_file_record",
    "delete_public_dorsal_file_record",
    "add_tag_to_file",
    "remove_tag_from_file",
    "search_user_files",
    "search_global_files",
    "find_duplicates",
    "get_directory_info",
    "generate_html_file_report",
    "generate_html_directory_report",
    "make_file_extension_dependency",
    "make_media_type_dependency",
    "make_file_size_dependency",
    "make_file_name_dependency",
]

logger = logging.getLogger(__name__)


@overload
def identify_file(
    file_path: str,
    quick: bool = True,
    file_size: int | None = None,
    *,
    mode: Literal["pydantic"],
    api_key: str | None = None,
    use_cache: bool = True,
) -> "FileRecord": ...


@overload
def identify_file(
    file_path: str,
    quick: bool = True,
    file_size: int | None = None,
    *,
    mode: Literal["dict"],
    api_key: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]: ...


@overload
def identify_file(
    file_path: str,
    quick: bool = True,
    file_size: int | None = None,
    *,
    mode: Literal["json"],
    api_key: str | None = None,
    use_cache: bool = True,
) -> str: ...


def identify_file(
    file_path: str,
    quick: bool = True,
    file_size: int | None = None,
    *,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
    api_key: str | None = None,
    use_cache: bool = True,
) -> FileRecord | dict[str, Any] | str:
    """Gets metadata for a local file from DorsalHub using its content hash.

    This function identifies a file by first calculating its hash locally and then
    querying the remote API for a matching record. It provides an efficient
    "quick hash" option for large files and falls back to a secure SHA-256 hash.
    Uses local cache to avoid re-calculating hashes on subsequent calls to same file path.

    Example:
        ```python
        from dorsal.api import identify_file

        try:
            # Identify a file, using the fast "quick hash" if possible
            record = identify_file("path/to/my_video.mp4", mode="dict")
            print(f"Successfully identified '{record['name']}'")
            print(f"Dorsal URL: {record['url']}")

        except FileNotFoundError:
            print("Error: The file could not be found at that path.")
        except DorsalClientError as e:
            # Catches errors like record not found on the server
            print(f"API Error: {e.message}")
        ```

    Args:
        file_path (str): The path to the local file to identify.
        quick (bool, optional): If True, attempts to use the faster "quick hash"
            for files >= 32MiB. Defaults to True.
        file_size (int, optional): An optional pre-calculated file size in bytes.
            If not provided, it will be calculated. Defaults to None.
        mode (Literal["pydantic", "dict", "json"], optional): The desired return
            format. Defaults to "pydantic".
        api_key (str, optional): An API key for this request, overriding the
            client's default. Defaults to None.

    Returns:
        Union[FileRecord, dict, str]: The file record from DorsalHub, formatted
            according to the specified `mode`.

    Raises:
        FileNotFoundError: If the file does not exist at the specified path.
        DorsalClientError: For API-level errors, such as `NotFoundError` if
            no record matches the hash.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    log_message_context = "using default client"
    effective_client: DorsalClient = get_shared_dorsal_client()
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)

    logger.debug(
        "Identifying file record for path: '%s' (quick=%s, %s)",
        file_path,
        quick,
        log_message_context,
    )

    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at path: {file_path}")

        file_record = None
        secure_hash_key = ""
        cache = get_shared_cache() if use_cache else None

        if quick:
            if file_size is None:
                file_size = get_filesize(file_path=file_path)

            if file_size >= QuickHasher.min_permitted_filesize:
                quick_hash_val = None
                if cache:
                    quick_hash_val = get_cached_hash(
                        file_path=file_path,
                        cache=cache,
                        hash_callable=lambda p: get_quick_hash(p, fallback_to_sha256=False, file_size=file_size),
                        hash_function="QUICK",
                    )
                else:
                    quick_hash_val = get_quick_hash(
                        file_path=file_path,
                        fallback_to_sha256=False,
                        file_size=file_size,
                    )

                if quick_hash_val:
                    quick_hash_key = f"QUICK:{quick_hash_val}"
                    logger.debug(
                        "Attempting to identify file with Quick Hash: %s",
                        quick_hash_key,
                    )
                    try:
                        file_record = effective_client.download_file_record(hash_string=quick_hash_key)
                    except ConflictError:
                        logger.warning(
                            "Quick Hash collision for '%s'. Falling back to SHA-256.",
                            quick_hash_key,
                        )
                    except NotFoundError:
                        logger.debug("Quick Hash record not found. Falling back to SHA-256.")
            else:
                logger.debug("File size is less than 32MiB. Skipping Quick Hash.")

        if file_record is None:
            secure_hash_val = None
            if cache:
                secure_hash_val = get_cached_hash(
                    file_path=file_path,
                    cache=cache,
                    hash_callable=get_sha256_hash,
                    hash_function="SHA-256",
                )
            else:
                secure_hash_val = get_sha256_hash(file_path=file_path)

            if not secure_hash_val:
                raise DorsalError(f"Could not generate SHA-256 hash for file: {file_path}")

            secure_hash_key = f"SHA-256:{secure_hash_val}"
            logger.debug("Attempting to identify file with Secure Hash: %s", secure_hash_key)
            file_record = effective_client.download_file_record(hash_string=secure_hash_key)

        if mode == "dict":
            return file_record.model_dump(mode="json", by_alias=True, exclude_none=True)
        if mode == "json":
            return file_record.model_dump_json(indent=2, by_alias=True, exclude_none=True)
        if mode != "pydantic":
            logger.debug("Invalid mode '%s' specified. Returning default model.", mode)  # type: ignore[unreachable]
        return file_record

    except DorsalClientError as err:
        if isinstance(err.original_exception, NotFoundError):
            hash_key = secure_hash_key or "the file's hash"
            err.message = f"No file record was found on DorsalHub matching {hash_key}."
        logger.debug("A client error occurred during identify_file for '%s': %s", file_path, err)
        raise
    except (FileNotFoundError, ValueError) as err:
        logger.error(
            "An input or file system error occurred during identify_file for '%s': %s",
            file_path,
            err,
        )
        raise
    except Exception as err:
        logger.exception("An unexpected error occurred during identify_file for '%s'.", file_path)
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(f"An unexpected error occurred while identifying file '{file_path}'.") from err


@overload
def get_dorsal_file_record(
    hash_string: str,
    mode: Literal["pydantic"],
    private: bool | None = None,
    api_key: str | None = None,
) -> "FileRecord": ...


@overload
def get_dorsal_file_record(
    hash_string: str,
    mode: Literal["dict"],
    private: bool | None = None,
    api_key: str | None = None,
) -> dict[str, Any]: ...


@overload
def get_dorsal_file_record(
    hash_string: str,
    mode: Literal["json"],
    private: bool | None = None,
    api_key: str | None = None,
) -> str: ...


def get_dorsal_file_record(
    hash_string: str,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
    private: bool | None = None,
    api_key: str | None = None,
) -> "FileRecord | dict[str, Any] | str":
    """
    Gets metadata for a file record from DorsalHub

    - `private=None` (Default): check for a public record first, and if not found, check for a private one.
    - `private=True`: get public record
    - `private=False`: get private record

    Example:
        ```python
        from dorsal.api import get_file_metadata

        # Agnostic search (recommended)
        agnostic_file = get_file_metadata("some_hash")

        # Public-only search
        public_file = get_file_metadata("some_hash", private=False)

        # Private-only search as a dictionary
        private_file_dict = get_file_metadata("some_hash", private=True, mode="dict")
        ```

    Args:
        hash_string (str): The hash of the file to fetch (e.g., "sha256:...").
        mode (Literal["pydantic", "dict", "json"], optional): The desired return
            format. Defaults to "pydantic", returning a `DorsalFile` object.
        private (Optional[bool], optional): Controls the search visibility.
            Defaults to None (agnostic search).
        api_key (str, optional): An API key to use for this request, overriding
            any globally configured key. Defaults to None.

    """
    from dorsal.session import get_shared_dorsal_client

    search_strategy = (
        "Agnostic (Private, then Public)" if private is None else ("Private-only" if private else "Public-only")
    )
    log_message_context = "using default client"

    effective_client = get_shared_dorsal_client()
    if api_key:
        from dorsal.client import DorsalClient

        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)

    logger.debug(
        "Getting file metadata for hash: '%s'. Mode: %s, Search: %s, %s",
        hash_string,
        mode,
        search_strategy,
        log_message_context,
    )

    try:
        cleaned_hash_string = hash_string.strip() if isinstance(hash_string, str) else ""
        if not cleaned_hash_string:
            raise ValueError("hash_string must be a non-empty string.")

        file_record = effective_client.download_file_record(
            hash_string=cleaned_hash_string,
            private=private,
        )

        if mode == "pydantic":
            return file_record
        if mode == "dict":
            return file_record.model_dump(mode="json", by_alias=True, exclude_none=True)
        if mode == "json":
            return file_record.model_dump_json(indent=2, by_alias=True, exclude_none=True)

        raise ValueError(f"Invalid mode: '{mode}'.")

    except (TypeError, ValueError) as err:
        logger.warning(
            "Input validation error in get_dorsal_file_record (hash: '%s', search: %s, %s): %s",
            hash_string,
            search_strategy,
            log_message_context,
            err,
        )
        raise
    except DorsalClientError as err:
        if isinstance(err.original_exception, NotFoundError):
            err.message = f"File not found in '{search_strategy}' scope for hash '{cleaned_hash_string}'."

        logger.warning(
            "DorsalClientError during get_dorsal_file_record (hash: '%s', search: %s, %s): %s",
            hash_string,
            search_strategy,
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error in get_dorsal_file_record for hash '%s' (%s).",
            hash_string,
            log_message_context,
        )
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(f"An unexpected error occurred while getting metadata for hash '{hash_string}'.") from err


def _delete_dorsal_file_record(
    file_hash: str,
    *,
    record: DeletionScope | None = "all",
    tags: DeletionScope | None = "all",
    annotations: DeletionScope | None = "all",
    api_key: str | None = None,
) -> "FileDeleteResponse":
    """
    Deletes a file record and/or its associated data from DorsalHub.

    This function provides a high-level interface to the unified delete endpoint.
    The default behavior ("all") attempts to delete all records (public/private)
    and associated user-owned metadata. Setting a scope to "none" prevents
    deletion for that category.

    Example:
        ```python
        from dorsal.api import _delete_dorsal_file_record

        file_hash = "123..." # A valid SHA-256 hash

        # Use case 1: Full clean (default behavior)
        _delete_dorsal_file_record(file_hash)

        # Use case 2: Quota management
        # Deletes only the private file record, keeping all metadata.
        _delete_dorsal_file_record(
            file_hash,
            record="private",
            tags=None,
            annotations=None,
        )

        # Use case 3: Equivalent to Use Case 2 using None
        _delete_dorsal_file_record(
            file_hash,
            record="private",
            tags=None,
            annotations=None
        )
        ```

    Args:
        file_hash (str): The SHA-256 hash of the file record to delete.
        record (DeletionScope | None): Specifies which core file record(s) to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "all".
        tags (DeletionScope | None): Specifies which of the user's tags to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "all".
        annotations (DeletionScope | None): Specifies which of the user's annotations
            to delete. Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "all".
        api_key (str, optional): An API key to use for this request.

    Returns:
        FileDeleteResponse: An object summarizing the result of the delete operation.

    Raises:
        ValueError: If the provided `file_hash` is not a valid SHA-256 hash.
        DorsalClientError: For API errors (e.g., not found, permission denied).
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    if not hash_string_validator.is_valid(candidate_string=file_hash, hash_function="SHA-256"):
        raise ValueError("file_hash must be a valid SHA-256 hash")
    file_hash = file_hash.lower()

    effective_client: "DorsalClient"
    if api_key:
        logger.debug("API key override provided for delete. Creating temporary DorsalClient.")
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    record_scope: DeletionScope = record if record is not None else "none"
    tags_scope: DeletionScope = tags if tags is not None else "none"
    annotations_scope: DeletionScope = annotations if annotations is not None else "none"

    try:
        delete_response = effective_client.delete_file(
            file_hash=file_hash,
            record=record_scope,
            tags=tags_scope,
            annotations=annotations_scope,
        )
        return delete_response

    except DorsalClientError:
        raise
    except Exception as err:
        logger.exception("Unexpected error in _delete_dorsal_file_record for hash '%s'.", file_hash)
        raise DorsalError(f"An unexpected error occurred while deleting record for hash '{file_hash}'.") from err


def delete_private_dorsal_file_record(
    file_hash: str,
    *,
    tags: DeletionScope | None = "none",
    annotations: DeletionScope | None = "none",
    api_key: str | None = None,
) -> "FileDeleteResponse":
    """
    Delete the private file record for the given hash.

    Args:
        file_hash (str): The SHA-256 hash of the file record to delete.
        tags (DeletionScope | None): Specifies which tags to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "none".
        annotations (DeletionScope | None): Specifies which annotations to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "none".
        api_key (str, optional): An API key to use for this request.

    Returns:
        FileDeleteResponse: An object summarizing the result of the delete operation.

    Raises:
        ValueError: If the provided `file_hash` is not valid.
        DorsalClientError: For API errors (e.g., not found, permission denied).
        DorsalError: For other unexpected library errors.
    """
    logger.info(
        "Requesting deletion of PRIVATE record for hash %s (tags=%s, annotations=%s)",
        file_hash,
        tags or "none",
        annotations or "none",
    )

    return _delete_dorsal_file_record(
        file_hash=file_hash,
        record="private",
        tags=tags if tags is not None else "none",
        annotations=annotations if annotations is not None else "none",
        api_key=api_key,
    )


def delete_public_dorsal_file_record(
    file_hash: str,
    *,
    tags: DeletionScope | None = "none",
    annotations: DeletionScope | None = "none",
    api_key: str | None = None,
) -> "FileDeleteResponse":
    """
    Delete the public file record for the given hash.

    Args:
        file_hash (str): The SHA-256 hash of the file record to delete.
        tags (DeletionScope | None): Specifies which tags to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "none".
        annotations (DeletionScope | None): Specifies which annotations to delete.
            Options: "all", "public", "private", "none", or None (treated as "none").
            Defaults to "none".
        api_key (str, optional): An API key to use for this request.

    Returns:
        FileDeleteResponse: An object summarizing the result of the delete operation.

    Raises:
        ValueError: If the provided `file_hash` is not valid.
        DorsalClientError: For API errors (e.g., not found, permission denied).
        DorsalError: For other unexpected library errors.
    """
    logger.info(
        "Requesting deletion of PUBLIC record for hash %s (tags=%s, annotations=%s)",
        file_hash,
        tags or "none",
        annotations or "none",
    )

    return _delete_dorsal_file_record(
        file_hash=file_hash,
        record="public",
        tags=tags if tags is not None else "none",
        annotations=annotations if annotations is not None else "none",
        api_key=api_key,
    )


def index_file(
    file_path: str,
    *,
    private: bool = True,
    api_key: str | None = None,
    use_cache: bool = True,
) -> FileIndexResponse:
    """Processes a single local file and uploads its metadata to DorsalHub.

    This function provides a simple, one-shot way to get a local file's
    metadata indexed on the remote server.

    Example:
        ```python
        from dorsal.api import index_file

        try:
            response = index_file("path/to/my_image.jpg", private=True)
            if response.success > 0:
                print("File indexed successfully!")
                print(f"View at: {response.results[0].url}")
        except Exception as e:
            print(f"Failed to index file: {e}")
        ```

    Args:
        file_path (str): The path to the local file to process and index.
        private (bool, optional): If True, the record will be created as private.
            Defaults to True.
        api_key (str, optional): An API key to use for this specific request.
            Defaults to None.

    Returns:
        FileIndexResponse: A response object from the API detailing the
            result of the indexing operation.
    """
    from dorsal.file.metadata_reader import MetadataReader

    metadata_reader: MetadataReader
    log_message_context = ""

    if api_key is not None:
        log_message_context = (
            "using provided API key with temporary MetadataReader (default model/ignore_duplicates settings)"
        )
        logger.debug(
            "API key override provided for index_file (file: '%s'). Creating temporary MetadataReader instance.",
            file_path,
        )
        metadata_reader = MetadataReader(api_key=api_key)

    else:
        log_message_context = "using shared METADATA_READER instance"
        logger.debug(
            "No API key override for index_file (file: '%s'). Using shared METADATA_READER instance.",
            file_path,
        )
        metadata_reader = get_metadata_reader()

    logger.debug(
        "High-level index_file calling effective MetadataReader for file_path='%s' (%s), private=%s.",
        file_path,
        log_message_context,
        private,
    )

    try:
        response = metadata_reader.index_file(file_path=file_path, private=private, skip_cache=not use_cache)
        logger.debug(
            "Effective MetadataReader.index_file completed for file_path='%s'. Response success: %s",
            file_path,
            response.success if hasattr(response, "success") else "N/A",
        )
        return response
    except (FileNotFoundError, IOError, DorsalError) as err:
        logger.warning(
            "Call to effective MetadataReader.index_file for file_path='%s' (%s) failed: %s - %s",
            file_path,
            log_message_context,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error in high-level index_file for file_path='%s' (%s).",
            file_path,
            log_message_context,
        )
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(
            f"An unexpected error occurred while indexing file '{file_path}' ({log_message_context})."
        ) from err


def index_directory(
    dir_path: str,
    recursive: bool = False,
    *,
    private: bool = True,
    api_key: str | None = None,
    use_cache: bool = True,
) -> dict:
    """Scans a directory and indexes all files to DorsalHub.

    This is a powerful, one-shot function that performs a complete workflow:
    1. Scans the specified directory for files.
    2. Generates rich metadata for each file locally.
    3. Uploads all generated metadata records to DorsalHub in managed batches.

    Example:
        ```python
        from dorsal.api import index_directory

        # Scan a directory and index all files to your private records
        summary = index_directory("path/to/project_assets", recursive=True, private=True)

        print("--- Indexing Complete ---")
        print(f"Files processed locally: {summary['total_records_processed_locally']}")
        print(f"Successfully indexed to API: {summary['total_records_accepted_by_api']}")
        ```

    Args:
        dir_path (str): The path to the directory you want to scan and index.
        recursive (bool, optional): If True, scans all subdirectories
            recursively. Defaults to False.
        private (bool, optional): If True, all file records will be created
            as private on DorsalHub. Defaults to True.
        api_key (str | None, optional): An API key to use for this operation,
            overriding the client's default. Defaults to None.

    Returns:
        dict: A summary dictionary detailing the results of the entire batch
            operation, including local processing and API indexing counts.
    """
    from dorsal.file.metadata_reader import MetadataReader

    effective_reader: MetadataReader
    log_message_context = ""

    if api_key is not None:
        log_message_context = "using provided API key with temporary MetadataReader"
        logger.debug(
            "API key override for index_directory (dir: '%s'). Creating temporary MetadataReader.",
            dir_path,
        )
        effective_reader = MetadataReader(api_key=api_key)
    else:
        log_message_context = "using shared METADATA_READER instance"
        logger.debug(
            "No API key override for index_directory (dir: '%s'). Using shared METADATA_READER.",
            dir_path,
        )
        effective_reader = get_metadata_reader()

    logger.debug(
        "High-level index_directory: dir_path='%s' (%s), recursive=%s, private=%s.",
        dir_path,
        log_message_context,
        recursive,
        private,
    )

    all_records_to_index: list[FileRecordStrict]
    file_hash_to_path_map: dict[str, str]

    try:
        logger.debug(
            "Step 1: Generating file records from directory '%s' via MetadataReader.",
            dir_path,
        )
        all_records_to_index, file_hash_to_path_map = effective_reader.generate_processed_records_from_directory(
            dir_path=dir_path, recursive=recursive, skip_cache=not use_cache
        )
        total_records_processed_locally = len(all_records_to_index)
        logger.debug(
            "MetadataReader generated %d unique file records from directory '%s'.",
            total_records_processed_locally,
            dir_path,
        )
    except DorsalError as err:
        logger.warning(
            "Failed to generate file records from directory '%s' (%s): %s - %s",
            dir_path,
            log_message_context,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error generating file records from directory '%s' (%s).",
            dir_path,
            log_message_context,
        )
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(f"Unexpected error processing directory '{dir_path}': {err}") from err

    if not all_records_to_index:
        logger.debug("No unique file records generated from directory '%s' to index.", dir_path)
        return {
            "total_records_processed_locally": 0,
            "total_batches_created": 0,
            "successful_api_batches": 0,
            "failed_api_batches": 0,
            "total_records_accepted_by_api": 0,
            "batch_processing_details": [],
        }

    batches = [
        all_records_to_index[i : i + constants.API_MAX_BATCH_SIZE]
        for i in range(0, total_records_processed_locally, constants.API_MAX_BATCH_SIZE)
    ]
    total_batches_created = len(batches)

    logger.debug(
        "Submitting %d records in %d batches of up to %d each to DorsalHub (private=%s, context: %s).",
        total_records_processed_locally,
        total_batches_created,
        constants.API_MAX_BATCH_SIZE,
        private,
        log_message_context,
    )

    successful_api_batches_count = 0
    failed_api_batches_count = 0
    total_records_accepted_by_api = 0
    batch_processing_details_list = []

    for i, current_batch_records in enumerate(batches):
        batch_number = i + 1
        records_in_this_batch = len(current_batch_records)
        batch_detail_entry: dict = {
            "batch_number": batch_number,
            "records_in_batch": records_in_this_batch,
            "status": "failure",
            "api_response": None,
            "error_message": None,
            "error_type": None,
        }

        logger.debug(
            "Submitting API batch %d of %d (%d records) for directory '%s'.",
            batch_number,
            total_batches_created,
            records_in_this_batch,
            dir_path,
        )
        try:
            batch_api_response: FileIndexResponse
            if private:
                batch_api_response = effective_reader._client.index_private_file_records(
                    file_records=current_batch_records
                )
            else:
                batch_api_response = effective_reader._client.index_public_file_records(
                    file_records=current_batch_records
                )

            if file_hash_to_path_map and batch_api_response.results:
                for result_item in batch_api_response.results:
                    if hasattr(result_item, "hash") and hasattr(result_item, "file_path"):
                        path = file_hash_to_path_map.get(result_item.hash)
                        if path:
                            result_item.file_path = path

            batch_detail_entry["status"] = "success"
            batch_detail_entry["api_response"] = batch_api_response
            successful_api_batches_count += 1
            total_records_accepted_by_api += batch_api_response.success

            logger.debug(
                "API Batch %d of %d for directory '%s' submitted successfully. API Response: Total=%d, Success=%d.",
                batch_number,
                total_batches_created,
                dir_path,
                batch_api_response.total,
                batch_api_response.success,
            )
        except DorsalError as err:
            logger.warning(
                "API Batch %d of %d for directory '%s' failed: %s - %s",
                batch_number,
                total_batches_created,
                dir_path,
                type(err).__name__,
                err,
            )
            batch_detail_entry["error_message"] = str(err)
            batch_detail_entry["error_type"] = type(err).__name__
            failed_api_batches_count += 1
        except Exception as err:
            logger.exception(
                "Unexpected error submitting API batch %d of %d for directory '%s'.",
                batch_number,
                total_batches_created,
                dir_path,
            )
            batch_detail_entry["error_message"] = f"Unexpected error: {str(err)}"
            batch_detail_entry["error_type"] = type(err).__name__
            failed_api_batches_count += 1

        batch_processing_details_list.append(batch_detail_entry)

    overall_summary = {
        "total_records_processed_locally": total_records_processed_locally,
        "total_batches_created": total_batches_created,
        "successful_api_batches": successful_api_batches_count,
        "failed_api_batches": failed_api_batches_count,
        "total_records_accepted_by_api": total_records_accepted_by_api,
        "batch_processing_details": batch_processing_details_list,
    }

    if failed_api_batches_count > 0:
        logger.warning(
            "Batch indexing for directory '%s' (%s) completed with %d successful and %d failed API batches (out of %d). "
            "Total records accepted by API in successful batches: %d.",
            dir_path,
            log_message_context,
            successful_api_batches_count,
            failed_api_batches_count,
            total_batches_created,
            total_records_accepted_by_api,
        )
    else:
        logger.debug(
            "Batch indexing for directory '%s' (%s) completed successfully. All %d API batches processed. "
            "Total records accepted by API: %d.",
            dir_path,
            log_message_context,
            total_batches_created,
            total_records_accepted_by_api,
        )
    return overall_summary


def scan_directory(
    dir_path: str, recursive: bool = False, *, api_key: str | None = None, use_cache: bool = True, offline: bool = False
) -> list[LocalFile]:
    """Scans a directory and returns a list of LocalFile objects.

    This function is a high-level wrapper that processes all files in a
    given directory and generates their metadata offline using the local Annotation Model pipeline.

    It returns a list of `LocalFile` objects.

    Example:
        ```python
        from dorsal.api import scan_directory

        # Scan a directory non-recursively for all files
        processed_files = scan_directory("path/to/my_invoices")

        print(f"Found {len(processed_files)} files to process.")

        # You can now iterate over the list
        for f in processed_files:
            if f.size > 500000:
                print(f"{f.name} is a large file.")
        ```

    Args:
        dir_path (str): The path to the directory you want to scan.
        recursive (bool, optional): If True, scans all subdirectories
            recursively. Defaults to False.

    Returns:
        list[LocalFile]: A list of processed `LocalFile` objects from the directory.
    """
    from dorsal.file.metadata_reader import MetadataReader

    effective_reader: MetadataReader
    if api_key is not None or offline:
        if api_key:
            logger.debug(
                "API key override for scan_directory (path: '%s'). Attaching MetadataReader configured with this API Key",
                dir_path,
            )
        if offline:
            logger.debug(
                "Offline mode. Attached MetadataReader blocked from making network calls",
            )
        effective_reader = MetadataReader(api_key=api_key)
    else:
        logger.debug(
            "No API key override for scan_directory (file: '%s'). Using shared METADATA_READER.",
            dir_path,
        )
        effective_reader = get_metadata_reader()

    logger.debug(
        "High-level scan_directory calling effective MetadataReader for dir_path='%s', recursive=%s.",
        dir_path,
        recursive,
    )

    try:
        local_files = effective_reader.scan_directory(dir_path=dir_path, recursive=recursive, skip_cache=not use_cache)
        logger.debug(
            "Effective MetadataReader.scan_directory completed for dir_path='%s'. Found %d LocalFile objects.",
            dir_path,
            len(local_files),
        )
        return local_files
    except (FileNotFoundError, DorsalError) as err:
        logger.warning(
            "Call to effective MetadataReader.scan_directory for dir_path='%s' failed: %s - %s",
            dir_path,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error in high-level scan_directory for dir_path='%s'",
            dir_path,
        )
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(f"An unexpected error occurred while reading directory '{dir_path}'.") from err


def scan_file(
    file_path: str, *, api_key: str | None = None, use_cache: bool = True, offline: bool = False
) -> LocalFile:
    """Processes a single file and returns a LocalFile object.

    This is a direct wrapper for `dorsal.LocalFile`. It's a convenient
    entry point for processing a single file and accessing its metadata
    without needing to import the `LocalFile` class directly.

    Example:
        ```python
        from dorsal.api import scan_file

        local_file = scan_file("path/to/my_image.jpg")

        print(f"File: {local_file.name}")
        print(f"Media Type: {local_file.media_type}")
        ```

    Args:
        file_path (str): The path to the local file to process.

    Returns:
        LocalFile: An initialized `LocalFile` instance with extracted metadata."
    """
    from dorsal.file.metadata_reader import MetadataReader

    effective_reader: MetadataReader

    if api_key is not None or offline:
        if api_key:
            logger.debug(
                "API key override for scan_file (file: '%s'). Attaching MetadataReader configured with this API Key",
                file_path,
            )
        if offline:
            logger.debug(
                "Offline mode. Attached MetadataReader blocked from making network calls",
            )
        effective_reader = MetadataReader(api_key=api_key)
    else:
        logger.debug(
            "No API key override for scan_file (file: '%s'). Using shared METADATA_READER.",
            file_path,
        )
        effective_reader = get_metadata_reader()

    logger.debug("High-level scan_file calling effective MetadataReader for file_path='%s'.", file_path)

    try:
        local_file = effective_reader.scan_file(file_path=file_path, skip_cache=not use_cache)
        logger.debug(
            "Effective MetadataReader.scan_file completed for file_path='%s'. Hash: %s",
            file_path,
            local_file.hash if hasattr(local_file, "hash") else "N/A",
        )
        return local_file
    except (FileNotFoundError, IOError, DorsalError) as err:
        logger.warning(
            "Call to effective MetadataReader.scan_file for file_path='%s' failed: %s - %s",
            file_path,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error in high-level scan_file for file_path='%s'",
            file_path,
        )
        if isinstance(err, DorsalError):
            raise
        raise DorsalError(f"An unexpected error occurred while reading file '{file_path}'.") from err


def add_tag_to_file(
    hash_string: str, name: str, value: Any, private: bool, api_key: str | None = None
) -> FileTagResponse:
    """
    Adds a single tag to a file record on DorsalHub.

    Args:
        hash_string (str): The hash of the file record to tag.
        name (str): The name of the tag.
        value (Any): The value of the tag.
        private (bool): The visibility of the tag itself.
        api_key (str, optional): An API key for this request.

    Returns:
        FileTagResponse: A response object from the API.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.file.validators.file_record import NewFileTag

    effective_client = get_shared_dorsal_client()
    if api_key:
        from dorsal.client import DorsalClient

        effective_client = DorsalClient(api_key=api_key)

    try:
        new_tag = NewFileTag(name=name, value=value, private=private)
        tag_result = effective_client.add_tags_to_file(file_hash=hash_string, tags=[new_tag])
        return tag_result
    except (DorsalClientError, ValueError):
        raise


def remove_tag_from_file(hash_string: str, tag_id: str, api_key: str | None = None) -> None:
    """
    Removes a specific tag from a file record.

    Args:
        hash_string (str): The hash of the file record.
        tag_id (str): The unique ID of the tag to remove.
        api_key (str, optional): An API key for this request.
    """
    from dorsal.session import get_shared_dorsal_client

    effective_client = get_shared_dorsal_client()
    if api_key:
        from dorsal.client import DorsalClient

        effective_client = DorsalClient(api_key=api_key)

    try:
        effective_client.delete_tag(file_hash=hash_string, tag_id=tag_id)
        return None
    except DorsalClientError:
        raise


def add_label_to_file(hash_string: str, label: str, api_key: str | None = None) -> "FileTagResponse":
    """
    Adds a simple Label to a file record.

    Labels are a specific type of private metadata tag where the key is always 'label'.
    They are useful for simple workflow statuses like 'urgent', 'todo', or 'complete'.

    This is a convenience wrapper around `add_tag_to_file`.

    Args:
        hash_string (str): The hash of the file record.
        label (str): The label text (e.g. "urgent").
        api_key (str, optional): An API key for this request.

    Returns:
        FileTagResponse: The API response.
    """
    return add_tag_to_file(hash_string=hash_string, name="label", value=label, private=True, api_key=api_key)


@overload
def search_user_files(
    query: str,
    deduplicate: bool = True,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    *,
    match_any: bool = False,
    api_key: str | None = None,
    mode: Literal["pydantic"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> "FileSearchResponse": ...


@overload
def search_user_files(
    query: str,
    deduplicate: bool = True,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    *,
    match_any: bool = False,
    api_key: str | None = None,
    mode: Literal["dict"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> dict[str, Any]: ...


@overload
def search_user_files(
    query: str,
    deduplicate: bool = True,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    *,
    match_any: bool = False,
    api_key: str | None = None,
    mode: Literal["json"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> str: ...


def search_user_files(
    query: str,
    deduplicate: bool = True,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    *,
    match_any: bool = False,
    api_key: str | None = None,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> "FileSearchResponse | dict | str":
    """Searches for file records indexed by the authenticated user.

    This function provides a simple and powerful interface to search for files
    you have indexed on DorsalHub. The query supports simple text matching as
    well as advanced operators.

    Example:
        ```python
        from dorsal.api import search_user_files

        # Find all PDF files you have indexed, sorted by name
        try:
            response = search_user_files(
                query="extension:pdf",
                sort_by="name",
                sort_order="asc",
                mode="dict"
            )

            print(f"Found {response['pagination']['record_count']} matching PDF files.")
            for record in response['results']:
                print(f"- {record['name']}")

        except Exception as e:
            print(f"An error occurred during search: {e}")
        ```

    Args:
        query (str): The search query string. Supports operators like
            `tag:`, `name:`, `extension:`, and `size:>1MB`.
        mode (Literal["pydantic", "dict", "json"]): The desired return format.
            Defaults to "pydantic".
        deduplicate (bool): If True, returns only unique file records based on
            their content hash. Defaults to True.
        page (int): The page number for pagination. Defaults to 1.
        per_page (int): The number of results per page. Must be between 1 and 50.
            Defaults to 25.
        sort_by (Literal): The field to sort results by. Defaults to 'date_modified'.
        sort_order (Literal): The sort order ('asc' or 'desc'). Defaults to 'desc'.
        api_key (str | None): An API key for this request, overriding the
            client's default. Defaults to None.

    Returns:
        Union[FileSearchResponse, dict, str]: The search results, formatted
            according to the specified `mode`.

    Raises:
        DorsalClientError: For client-side validation errors or API errors
            like authentication or rate limiting.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = ""
    if api_key:
        log_message_context = "using temporary client with provided API key"
        logger.debug("API key override provided for search. Creating temporary DorsalClient.")
        effective_client = DorsalClient(api_key=api_key)
    else:
        log_message_context = "using shared client via MetadataReader"
        logger.debug("No API key override for search. Using shared client instance.")
        effective_client = get_metadata_reader()._client

    logger.debug(
        "Dispatching user file search to client (%s) with query: '%s'",
        log_message_context,
        query,
    )

    try:
        response = effective_client.search_files(
            q=query,
            scope="user",
            deduplicate=deduplicate,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            match_any=match_any,
        )

        logger.debug(
            "User file search successful. Returned page %d of %d, with %d records.",
            response.pagination.current_page,
            response.pagination.page_count,
            len(response.results),
        )

        if mode == "pydantic":
            return response
        if mode == "dict":
            return response.model_dump(
                by_alias=model_dump_by_alias,
                exclude_none=model_dump_exclude_none,
                mode="json",
            )
        if mode == "json":
            return response.model_dump_json(
                by_alias=model_dump_by_alias,
                exclude_none=model_dump_exclude_none,
                indent=2,
            )

        raise ValueError(f"Invalid mode: '{mode}'. Must be one of 'pydantic', 'dict', or 'json'.")  # pragma: no cover

    except DorsalError as err:
        logger.warning(
            "A client error occurred during search_user_files (%s): %s - %s",
            log_message_context,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during search_user_files (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred during file search: {err}") from err


@overload
def search_global_files(
    query: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    api_key: str | None = None,
    *,
    match_any: bool = False,
    mode: Literal["pydantic"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> "FileSearchResponse": ...


@overload
def search_global_files(
    query: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    api_key: str | None = None,
    *,
    match_any: bool = False,
    mode: Literal["dict"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> dict[str, Any]: ...


@overload
def search_global_files(
    query: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    api_key: str | None = None,
    *,
    match_any: bool = False,
    mode: Literal["json"],
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> str: ...


def search_global_files(
    query: str,
    page: int = 1,
    per_page: int = 25,
    sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
    sort_order: Literal["asc", "desc"] = "desc",
    api_key: str | None = None,
    *,
    match_any: bool = False,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
    model_dump_exclude_none: bool = True,
    model_dump_by_alias: bool = True,
) -> "FileSearchResponse | dict | str":
    """Searches for public file records across the entire DorsalHub platform.

    This function provides a simple interface to search all public files.
    Note: This is a premium feature and requires an appropriate account status.

    Example:
        ```python
        from dorsal.api import search_global_files

        # Find all publicly indexed files tagged with 'research'
        try:
            response = search_global_files(
                query="tag:research",
                mode="dict"
            )

            print(f"Found {response['pagination']['record_count']} public files tagged 'research'.")
            for record in response['results']:
                print(f"- {record['name']} (hash: {record['hash']})")

        except Exception as e:
            print(f"An error occurred during search: {e}")
        ```

    Args:
        query (str): The search query string. Supports operators like
            `tag:`, `name:`, `extension:`, and `size:>1MB`.
        mode (Literal["pydantic", "dict", "json"]): The desired return format.
            Defaults to "pydantic".
        page (int): The page number for pagination. Defaults to 1.
        per_page (int): The number of results per page. Must be between 1 and 50.
            Defaults to 25.
        sort_by (Literal): The field to sort results by. Defaults to 'date_modified'.
        sort_order (Literal): The sort order ('asc' or 'desc'). Defaults to 'desc'.
        api_key (str | None): An API key for this request, overriding the
            client's default. Defaults to None.

    Returns:
        Union[FileSearchResponse, dict, str]: The search results, formatted
            according to the specified `mode`.

    Raises:
        DorsalClientError: For client-side validation errors or API errors like
            authentication, rate limiting, or insufficient permissions (e.g.
            using this feature on a non-premium account).
        DorsalError: For other unexpected library errors.
    """
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = ""
    if api_key:
        log_message_context = "using temporary client with provided API key"
        logger.debug("API key override provided for global search. Creating temporary DorsalClient.")
        effective_client = DorsalClient(api_key=api_key)
    else:
        log_message_context = "using shared client via MetadataReader"
        logger.debug("No API key override for global search. Using shared client instance.")
        effective_client = get_metadata_reader()._client

    logger.debug(
        "Dispatching global file search to client (%s) with query: '%s'",
        log_message_context,
        query,
    )

    try:
        response = effective_client.search_files(
            q=query,
            scope="global",
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            match_any=match_any,
        )

        logger.debug(
            "Global file search successful. Returned page %d of %d, with %d records.",
            response.pagination.current_page,
            response.pagination.page_count,
            len(response.results),
        )

        if mode == "pydantic":
            return response
        if mode == "dict":
            return response.model_dump(
                by_alias=model_dump_by_alias,
                exclude_none=model_dump_exclude_none,
                mode="json",
            )
        if mode == "json":
            return response.model_dump_json(
                by_alias=model_dump_by_alias,
                exclude_none=model_dump_exclude_none,
                indent=2,
            )
        raise ValueError(f"Invalid mode: '{mode}'. Must be one of 'pydantic', 'dict', or 'json'.")  # pragma: no cover

    except DorsalError as err:
        logger.warning(
            "A client error occurred during search_global_files (%s): %s - %s",
            log_message_context,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during search_global_files (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred during global file search: {err}") from err


def _filter_by_size(
    path: pathlib.Path,
    recursive: bool,
    min_size_bytes: int,
    max_size_bytes: int | None,
    progress_console: "Console" | None = None,
    palette: dict | None = None,
) -> tuple[list[pathlib.Path], int, int]:
    """
    Pass 1: Walk a directory, filter by size, and return potential duplicates
    along with scan statistics. Includes progress reporting during the walk.
    """
    size_map = defaultdict(list)
    rich_progress = None
    tqdm_bar = None
    processed_files = 0
    inaccessible_files = 0

    task_description = "Pass 1: Scanning for files..."

    if is_jupyter_environment():
        from tqdm import tqdm

        tqdm_bar = tqdm(desc=task_description, unit=" file")
    elif progress_console:
        rich_progress = _create_rich_progress(progress_console, palette)
        task_id = rich_progress.add_task(task_description, total=None)
    else:
        logger.debug("Starting file size scan...")

    with rich_progress if rich_progress else open(os.devnull, "w"):
        try:
            for root, _, files in os.walk(path):
                for name in files:
                    processed_files += 1
                    if rich_progress:
                        rich_progress.update(task_id, advance=1)
                    elif tqdm_bar:
                        tqdm_bar.update(1)

                    file_path = pathlib.Path(root) / name
                    try:
                        if file_path.is_file():
                            file_stat = file_path.stat()
                            if min_size_bytes <= file_stat.st_size and (
                                max_size_bytes is None or file_stat.st_size <= max_size_bytes
                            ):
                                size_map[file_stat.st_size].append(file_path)
                    except (FileNotFoundError, PermissionError) as e:
                        logger.warning("Could not access file '%s': %s", file_path, e)
                        inaccessible_files += 1

                if not recursive:
                    break
        finally:
            if tqdm_bar is not None:
                tqdm_bar.close()

    total_scanned = processed_files
    potential_duplicates = [file for size_group in size_map.values() if len(size_group) > 1 for file in size_group]

    logger.debug(
        "Pass 1 complete. Scanned %d files (%d inaccessible). Found %d potential duplicates in %d size groups.",
        total_scanned,
        inaccessible_files,
        len(potential_duplicates),
        sum(1 for g in size_map.values() if len(g) > 1),
    )
    return potential_duplicates, total_scanned, inaccessible_files


class _DuplicateSet(TypedDict):
    hash: str
    hash_type: str
    count: int
    file_size: str
    file_size_bytes: int
    paths: list[str]


def _format_duplicate_results(path: str, hash_map: dict[str, list[str]]) -> dict:
    """Formats the results of a duplicate search."""
    duplicate_sets_raw = [paths for paths in hash_map.values() if len(paths) > 1]
    if not duplicate_sets_raw:
        return {}

    duplicate_sets_formatted: list[_DuplicateSet] = []
    for paths in duplicate_sets_raw:
        try:
            size_each = pathlib.Path(paths[0]).stat().st_size
            count = len(paths)
            prefixed_hash = next(h for h, p_list in hash_map.items() if p_list == paths)
            hash_type, file_hash = prefixed_hash.split(":", 1)

            duplicate_sets_formatted.append(
                {
                    "hash": file_hash,
                    "hash_type": hash_type,
                    "count": count,
                    "file_size": human_filesize(size_each),
                    "file_size_bytes": size_each,
                    "paths": paths,
                }
            )
        except (FileNotFoundError, StopIteration):
            continue

    duplicate_sets_formatted.sort(key=lambda x: x["file_size_bytes"], reverse=True)

    return {
        "path": str(path),
        "total_sets": len(duplicate_sets_formatted),
        "duplicate_sets": duplicate_sets_formatted,
    }


def _create_rich_progress(progress_console: "Console", palette: dict[str, str] | None = None):
    """Helper to create a Rich Progress instance."""
    from rich.progress import (
        Progress,
        BarColumn,
        TextColumn,
        TaskProgressColumn,
        TimeRemainingColumn,
        TimeElapsedColumn,
        MofNCompleteColumn,
        SpinnerColumn,
    )

    palette = palette or {}
    return Progress(
        SpinnerColumn(),
        TextColumn(
            "[progress.description]{task.description}",
            style=palette.get("progress_description", "default"),
        ),
        BarColumn(bar_width=None, style=palette.get("progress_bar", "default")),
        TaskProgressColumn(style=palette.get("progress_percentage", "default")),
        MofNCompleteColumn(),
        TextColumn("•", style="dim"),
        TimeElapsedColumn(),
        TextColumn("•", style="dim"),
        TimeRemainingColumn(),
        console=progress_console,
        transient=True,
    )


def _find_duplicates_sha256(
    files_to_check: Sequence[pathlib.Path],
    use_cache: bool,
    progress_console: "Console" | None = None,
    palette: dict | None = None,
) -> tuple[dict[str, list[str]], int]:
    """Hashes a list of files with SHA-256 and returns a map of prefixed hashes."""
    hash_map = defaultdict(list)
    cache_hits = 0

    cache = get_shared_cache() if use_cache else None

    iterator: Iterable[pathlib.Path] = files_to_check
    rich_progress = None

    if is_jupyter_environment():
        from tqdm import tqdm

        iterator = tqdm(files_to_check, desc="Hashing (SHA-256)")
    elif progress_console:
        rich_progress = _create_rich_progress(progress_console, palette)
        task_id = rich_progress.add_task("Hashing (SHA-256)...", total=len(files_to_check))

    with rich_progress if rich_progress else open(os.devnull, "w"):
        for file_path in iterator:
            file_hash = None
            try:
                resolved_path = str(file_path.resolve())

                if cache:
                    cached_val = cache.get_hash(path=resolved_path, hash_function="SHA-256")
                    if cached_val:
                        file_hash = cached_val
                        cache_hits += 1

                if file_hash is None:
                    if cache:
                        file_hash = get_cached_hash(
                            file_path=resolved_path,
                            cache=cache,
                            hash_callable=get_sha256_hash,
                            hash_function="SHA-256",
                        )
                    else:
                        file_hash = get_sha256_hash(resolved_path)

                if file_hash:
                    hash_map[f"sha256:{file_hash}"].append(str(file_path))

            except Exception as e:
                logger.warning("Failed to hash file '%s': %s", file_path, e)
            if rich_progress:
                rich_progress.update(task_id, advance=1)

    return hash_map, cache_hits


def _find_duplicates_quick(
    files_to_check: Sequence[pathlib.Path],
    use_cache: bool,
    progress_console: "Console" | None = None,
    palette: dict | None = None,
) -> tuple[dict[str, list[str]], int]:
    """Hashes a list of files with QUICK hash and returns a map of prefixed hashes."""
    hash_map = defaultdict(list)
    cache_hits = 0

    cache = get_shared_cache() if use_cache else None

    iterator: Iterable[pathlib.Path] = files_to_check
    rich_progress = None
    if is_jupyter_environment():
        from tqdm import tqdm

        iterator = tqdm(files_to_check, desc="Hashing (QUICK)")
    elif progress_console:
        rich_progress = _create_rich_progress(progress_console, palette)
        task_id = rich_progress.add_task("Hashing (QUICK)...", total=len(files_to_check))

    with rich_progress if rich_progress else open(os.devnull, "w"):
        for file_path in iterator:
            hash_to_use = None
            hash_function = None
            try:
                resolved_path = str(file_path.resolve())

                if cache:
                    cached_val = cache.get_hash(path=resolved_path, hash_function="QUICK")
                    if cached_val:
                        hash_to_use, hash_function = cached_val, "quick"
                        cache_hits += 1

                if hash_to_use is None:
                    if cache:
                        quick_hash_val = get_cached_hash(
                            file_path=resolved_path,
                            cache=cache,
                            hash_callable=lambda p: get_quick_hash(p, fallback_to_sha256=False),
                            hash_function="QUICK",
                        )
                        if quick_hash_val:
                            hash_to_use, hash_function = quick_hash_val, "quick"
                    else:
                        quick_hash_val = get_quick_hash(resolved_path, fallback_to_sha256=False)
                        if quick_hash_val:
                            hash_to_use, hash_function = quick_hash_val, "quick"

                if hash_to_use is None:
                    if cache:
                        cached_val = cache.get_hash(path=resolved_path, hash_function="SHA-256")
                        if cached_val:
                            hash_to_use, hash_function = cached_val, "sha256"
                            cache_hits += 1

                    if hash_to_use is None:
                        if cache:
                            hash_to_use = get_cached_hash(
                                file_path=resolved_path,
                                cache=cache,
                                hash_callable=get_sha256_hash,
                                hash_function="SHA-256",
                            )
                        else:
                            hash_to_use = get_sha256_hash(resolved_path)
                        hash_function = "sha256"

                if hash_to_use:
                    hash_map[f"{hash_function}:{hash_to_use}"].append(str(file_path))

            except Exception as e:
                logger.warning("Failed to hash file '%s': %s", file_path, e)
            if rich_progress:
                rich_progress.update(task_id, advance=1)

    return hash_map, cache_hits


def find_duplicates(
    path: str | pathlib.Path,
    recursive: bool = False,
    min_size: str | int = 0,
    max_size: str | int | None = None,
    mode: Literal["hybrid", "quick", "sha256"] = "hybrid",
    use_cache: bool = True,
    progress_console: "Console" | None = None,
    palette: dict | None = None,
) -> dict:
    """
    Finds duplicate files in a directory using a multi-pass filtering strategy.
    """

    path = pathlib.Path(path)
    min_size_bytes = parse_filesize(min_size) if isinstance(min_size, str) else min_size
    max_size_bytes = parse_filesize(max_size) if isinstance(max_size, str) else max_size

    candidate_files, total_scanned, inaccessible_count = _filter_by_size(
        path, recursive, min_size_bytes, max_size_bytes, progress_console, palette
    )
    if not candidate_files:
        logger.debug("No potential duplicates found based on file size. Finished.")
        return {}

    results = {}
    total_cache_hits = 0

    if mode == "hybrid":
        logger.debug("Pass 2/3: Identifying potential duplicates with QUICK hash...")
        quick_hash_map, quick_cache_hits = _find_duplicates_quick(candidate_files, use_cache, progress_console, palette)
        total_cache_hits += quick_cache_hits

        potential_duplicates = [pathlib.Path(p) for s in quick_hash_map.values() if len(s) > 1 for p in s]

        if not potential_duplicates:
            logger.debug("No potential duplicates found after QUICK hash pass. Finished.")
            results = _format_duplicate_results(path=str(path), hash_map=quick_hash_map)
        else:
            logger.debug(
                "Pass 2 complete. Found %d potential duplicates to verify with SHA-256.",
                len(potential_duplicates),
            )
            logger.debug("Pass 3/3: Verifying duplicates with SHA-256 hash...")
            final_hash_map, sha_cache_hits = _find_duplicates_sha256(
                potential_duplicates, use_cache, progress_console, palette
            )
            total_cache_hits += sha_cache_hits
            results = _format_duplicate_results(path=str(path), hash_map=final_hash_map)

    elif mode == "quick":
        logger.warning("Using 'quick' mode. Results may include false positives.")
        logger.debug("Pass 2/2: Identifying potential duplicates with QUICK hash...")
        quick_hash_map, total_cache_hits = _find_duplicates_quick(candidate_files, use_cache, progress_console, palette)
        results = _format_duplicate_results(path=str(path), hash_map=quick_hash_map)

    elif mode == "sha256":
        logger.debug("Pass 2/2: Identifying duplicates with SHA-256 hash...")
        sha256_hash_map, total_cache_hits = _find_duplicates_sha256(
            candidate_files, use_cache, progress_console, palette
        )
        results = _format_duplicate_results(path=str(path), hash_map=sha256_hash_map)

    else:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of 'hybrid', 'quick', or 'sha256'.")

    results["hashes_from_cache"] = total_cache_hits

    if results and results.get("total_sets", 0) > 0:
        total_duplicate_files = sum(s["count"] for s in results.get("duplicate_sets", []))
        logger.debug(
            "Duplicate search complete. Scanned %d files (%d inaccessible, %d hashes from cache). "
            "Found %d sets of duplicates, comprising %d total files.",
            total_scanned,
            inaccessible_count,
            total_cache_hits,
            results["total_sets"],
            total_duplicate_files,
        )
    else:
        logger.debug("Duplicate search complete. No duplicate sets were found.")

    return results


class _FileInfo(TypedDict, total=False):
    size: int | float
    path: str | None
    date: datetime.datetime | None


class _MediaTypeStats(TypedDict):
    count: int
    total_size: int


class _DirectoryInfoResult(TypedDict):
    overall: dict[str, Any]
    by_type: list[dict[str, Any]]


class _FileReportInfo(TypedDict, total=False):
    size: int | float
    path: str | None
    date: str | None


class _DirectoryMetrics:
    """Collect metrics during a directory walk."""

    def __init__(self, media_type_enabled: bool):
        self.media_type_enabled = media_type_enabled
        self.time_in_mt = 0.0

        self.total_files: int = 0
        self.successfully_processed_files: int = 0
        self.total_size: int = 0
        self.total_dirs: int = 0
        self.hidden_files: int = 0

        self.largest_file: _FileInfo = {"size": -1, "path": None}
        self.smallest_file: _FileInfo = {"size": float("inf"), "path": None}
        self.newest_mod_file: _FileInfo | None = None
        self.oldest_mod_file: _FileInfo | None = None
        self.oldest_creation_file: _FileInfo | None = None

        self.type_stats: defaultdict[str, _MediaTypeStats] = defaultdict(lambda: {"count": 0, "total_size": 0})
        self.permissions: defaultdict[str, int] = defaultdict(int)

    def process_file(self, file_path: pathlib.Path) -> None:
        """
        Processes a single file path, gets its stats, and updates all relevant metrics.
        This method acts as a central dispatcher to more specific update methods.
        """
        try:
            stat_info = file_path.stat()
            self.successfully_processed_files += 1

            self._update_file_counts(file_path.name, stat_info)
            self._update_size_stats(stat_info.st_size, str(file_path), stat_info.st_mtime)
            self._update_date_stats(stat_info.st_mtime, stat_info.st_ctime, str(file_path))
            self._update_permission_stats(stat_info.st_mode)

            if self.media_type_enabled:
                self._update_media_type_stats(file_path, stat_info.st_size)

        except OSError as e:
            logger.warning("Could not process file '%s': %s", file_path, e)

    def _update_file_counts(self, file_name: str, stat_info: os.stat_result) -> None:
        is_hidden = file_name.startswith(".")
        if sys.platform == "win32" and hasattr(stat_info, "st_file_attributes"):
            if stat_info.st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN:
                is_hidden = True
        if is_hidden:
            self.hidden_files += 1

    def _update_size_stats(self, file_size: int, file_path_str: str, mtime: float) -> None:
        self.total_size += file_size
        if file_size > self.largest_file["size"]:
            mod_date = datetime.datetime.fromtimestamp(mtime).astimezone()
            self.largest_file = {"size": file_size, "path": file_path_str, "date": mod_date}
        if file_size < cast(float, self.smallest_file["size"]):
            mod_date = datetime.datetime.fromtimestamp(mtime).astimezone()
            self.smallest_file = {"size": file_size, "path": file_path_str, "date": mod_date}

    def _update_date_stats(self, mtime: float, ctime: float, file_path_str: str) -> None:
        mod_date = datetime.datetime.fromtimestamp(mtime).astimezone()
        creation_date = datetime.datetime.fromtimestamp(ctime).astimezone()

        if self.newest_mod_file is None or mod_date > cast(datetime.datetime, self.newest_mod_file["date"]):
            self.newest_mod_file = {"date": mod_date, "path": file_path_str}
        if self.oldest_mod_file is None or mod_date < cast(datetime.datetime, self.oldest_mod_file["date"]):
            self.oldest_mod_file = {"date": mod_date, "path": file_path_str}
        if self.oldest_creation_file is None or creation_date < cast(
            datetime.datetime, self.oldest_creation_file["date"]
        ):
            self.oldest_creation_file = {"date": creation_date, "path": file_path_str}

    def _update_permission_stats(self, mode: int) -> None:
        if not (mode & stat.S_IWUSR):
            self.permissions["read_only"] += 1
        if not (mode & stat.S_IRUSR):
            self.permissions["write_only"] += 1
        if mode & stat.S_IXUSR:
            self.permissions["executable"] += 1

    def _update_media_type_stats(self, file_path: pathlib.Path, file_size: int) -> None:
        file_extension = file_path.suffix.lower() or "No Extension"
        mt_time_start = time.perf_counter()
        media_type_result = get_media_type(str(file_path), file_extension)
        mt_time_end = time.perf_counter()
        self.time_in_mt += mt_time_end - mt_time_start

        self.type_stats[media_type_result]["count"] += 1
        self.type_stats[media_type_result]["total_size"] += file_size


def _to_report_info(file_info: _FileInfo | None) -> _FileReportInfo:
    if not file_info:
        return {"date": None, "path": None}

    date_val = file_info.get("date")
    iso_date: str | None = None
    if isinstance(date_val, datetime.datetime):
        iso_date = date_val.isoformat()

    report: _FileReportInfo = {"date": iso_date, "path": file_info.get("path")}
    if "size" in file_info:
        report["size"] = file_info["size"]
    return report


def _format_results(metrics: _DirectoryMetrics, duration: float) -> _DirectoryInfoResult:
    """Formats the collected metrics into the final API response dictionary."""
    avg_size = (
        (metrics.total_size / metrics.successfully_processed_files) if metrics.successfully_processed_files > 0 else 0
    )

    if metrics.total_files > 0 and metrics.successfully_processed_files == 0:
        largest_file = _to_report_info({"size": 0, "path": None})
        smallest_file = _to_report_info({"size": 0, "path": None})
        newest_mod = _to_report_info(None)
        oldest_mod = _to_report_info(None)
        oldest_creation = _to_report_info(None)
    else:
        largest_file = _to_report_info(metrics.largest_file)
        smallest_file = _to_report_info(metrics.smallest_file)
        newest_mod = _to_report_info(metrics.newest_mod_file)
        oldest_mod = _to_report_info(metrics.oldest_mod_file)
        oldest_creation = _to_report_info(metrics.oldest_creation_file)

    overall = {
        "total_files": metrics.total_files,
        "total_dirs": metrics.total_dirs,
        "hidden_files": metrics.hidden_files,
        "total_size": metrics.total_size,
        "avg_size": avg_size,
        "largest_file": largest_file,
        "smallest_file": smallest_file,
        "newest_mod_file": newest_mod,
        "oldest_mod_file": oldest_mod,
        "oldest_creation_file": oldest_creation,
        "permissions": dict(metrics.permissions),
        "time_taken_seconds": duration,
        "time_taken_mt": metrics.time_in_mt,
    }

    by_type = []
    if metrics.media_type_enabled and metrics.total_size > 0:
        by_type = sorted(
            [
                {
                    "media_type": k,
                    **v,
                    "percentage": (v["total_size"] / metrics.total_size) * 100,
                }
                for k, v in metrics.type_stats.items()
            ],
            key=lambda x: cast(int, x["total_size"]),
            reverse=True,
        )

    return {"overall": overall, "by_type": by_type}


def get_directory_info(
    dir_path: str,
    recursive: bool = False,
    media_type: bool = True,
    progress_console: "Console" | None = None,
    palette: dict[str, str] | None = None,
) -> _DirectoryInfoResult:
    """
    Calculates and returns a detailed summary of a directory using a single-pass method.
    """
    if not os.path.isdir(dir_path):
        raise NotADirectoryError(f"The specified path is not a directory: {dir_path}")

    metrics = _DirectoryMetrics(media_type_enabled=media_type)
    start_time = time.perf_counter()

    tqdm_bar = None
    rich_progress = None
    task_id = None

    if is_jupyter_environment():
        from tqdm import tqdm

        tqdm_bar = tqdm(desc="Analyzing directory", unit="file")
    elif progress_console:
        rich_progress = _create_rich_progress(progress_console, palette)
        task_id = rich_progress.add_task("Analyzing directory...", total=None)

    progress_manager = rich_progress if rich_progress else open(os.devnull, "w")
    with progress_manager:
        for root, dirs, files in os.walk(dir_path, topdown=True):
            metrics.total_dirs += len(dirs)

            for name in files:
                metrics.total_files += 1

                if rich_progress and task_id is not None:
                    rich_progress.update(task_id, advance=1)
                elif tqdm_bar:
                    tqdm_bar.update(1)

                metrics.process_file(pathlib.Path(root) / name)

            if not recursive:
                dirs.clear()

    if tqdm_bar:
        tqdm_bar.close()

    duration = time.perf_counter() - start_time
    logger.info("Directory analysis for '%s' completed in %.2f seconds.", dir_path, duration)

    return _format_results(metrics, duration)


def generate_html_file_report(
    file_path: str,
    *,
    local_file: LocalFile | None = None,
    output_path: str | None = None,
    template: str = "default",
    use_cache: bool = True,
    api_key: str | None = None,
) -> str | None:
    """
    Generates a self-contained HTML report for a single local file.

    This function serves as a high-level entry point to the reporting engine. It
    leverages `scan_file` to perform a full metadata extraction and then renders
    the result into a rich, interactive HTML document using a flexible,
    user-configurable Jinja2 template system. The final output is a single,
    portable HTML file with all CSS and JavaScript embedded.

    Example:
        ```python
        from dorsal.api import generate_html_file_report

        # Generate the report and save it to a file
        generate_html_file_report(
            "path/to/my_document.pdf",
            output_path="report.html"
        )

        # Generate a report using a custom template and get the HTML as a string
        html_content = generate_html_file_report(
            "path/to/archive.zip",
            template="compact"
        )
        ```

    Args:
        file_path (str): The path to the local file to report on.
        output_path (str, optional): If provided, the HTML report will be saved
            to this file path. Defaults to None.
        template (str, optional): The name of a built-in/user-defined template
            or an absolute path to a custom template .html file.
            Defaults to "default".
        use_cache (bool, optional): Whether to use the local cache during file
            processing. Defaults to True.
        api_key (str, optional): An API key for operations that may require it.
            Defaults to None.

    Returns:
        str: The generated HTML report as a string.

    Raises:
        DorsalError: If file processing or report generation fails.
        TemplateNotFoundError: If the specified template cannot be located.
        FileNotFoundError: If the specified `file_path` does not exist.
    """
    from jinja2 import Environment, FileSystemLoader
    from dorsal.templates.file.icons import get_media_type_icon
    from dorsal.version import __version__

    logger.debug(f"Generating HTML report for: '{file_path}' using template: '{template}'")
    try:
        if local_file is None:
            local_file = scan_file(file_path, use_cache=use_cache, api_key=api_key)

        template_file, template_base_dir = resolve_template_path(report_type="file", name_or_path=template)

        env = Environment(loader=FileSystemLoader(template_base_dir), autoescape=True)
        env.globals["human_filesize"] = human_filesize
        env.globals["get_media_type_icon"] = get_media_type_icon

        jinja_template = env.get_template(template_file.name)
        file_dict = local_file.to_dict(mode="json")

        base_info = file_dict.get("annotations", {}).get("file/base", {}).get("record", {})
        file_size_info = {
            "human": human_filesize(base_info.get("size", 0)),
            "raw": f"{base_info.get('size', 0)} bytes",
        }

        local_fs_info = {
            "full_path": local_file._file_path,
            "date_created": {
                "human": local_file.date_created.strftime("%Y-%m-%d %H:%M:%S"),
                "raw": local_file.date_created.isoformat(),
            },
            "date_modified": {
                "human": local_file.date_modified.strftime("%Y-%m-%d %H:%M:%S"),
                "raw": local_file.date_modified.isoformat(),
            },
        }

        context = {
            "report_title": f"Dorsal Report: {html.escape(base_info.get('name', 'Untitled File'))}",
            "generation_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "file": file_dict,
            "file_size": file_size_info,
            "raw_data_json": json.dumps(file_dict, indent=2, default=str),
            "local_filesystem_info": local_fs_info,
            "dorsal_version": __version__,
        }

        html_content = jinja_template.render(context)

        if output_path:
            output_file = pathlib.Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"HTML file report saved to: {output_path}")
            return None

        return html_content
    except Exception as e:
        logger.exception(f"Failed to generate HTML file report for '{file_path}'.")
        if isinstance(e, (DorsalError, FileNotFoundError)):
            raise
        raise DorsalError(f"Could not generate HTML report for {file_path}: {e}") from e


def generate_html_directory_report(
    dir_path: str,
    output_path: str | None = None,
    *,
    local_collection: LocalFileCollection | None = None,
    template: str = "default",
    use_cache: bool = True,
    recursive: bool = False,
) -> str | None:
    """
    Generates a self-contained HTML dashboard for a directory of files.

    This function orchestrates the creation of a rich, interactive HTML document.
    It processes a directory into a LocalFileCollection, generates data for various
    UI panel based on user configuration, and renders the result using a
    flexible Jinja2 template system.

    Args:
        dir_path (str): The path to the local directory to report on.
        local_collection (LocalFileCollection, optional): An existing, pre-processed
            collection can be passed to avoid re-scanning the directory.
        output_path (str, optional): If provided, the HTML dashboard will be saved
            to this file path.
        template (str, optional): The name of the template to use. Defaults to "default".
        use_cache (bool, optional): Whether to use the local cache during file processing.
        recursive (bool, optional): Whether to scan the directory recursively.

    Returns:
        str: The generated HTML dashboard as a string.

    Raises:
        DorsalError: If file processing or report generation fails.
        TemplateNotFoundError: If the specified template cannot be located.
        FileNotFoundError: If the specified `dir_path` does not exist.
    """
    from jinja2 import Environment, FileSystemLoader
    from dorsal.common.config import get_collection_report_panel_config
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.utils.reports import REPORT_DATA_GENERATORS, resolve_template_path
    from dorsal.templates.file.icons import get_media_type_icon
    from dorsal.version import __version__
    import datetime
    import html
    import json
    import pathlib

    logger.debug(f"Generating HTML dashboard for: '{dir_path}' using template: '{template}'")
    try:
        if local_collection is None:
            collection = LocalFileCollection(
                source=dir_path,
                recursive=recursive,
                use_cache=use_cache,
            )
        else:
            collection = local_collection

        panel_config = get_collection_report_panel_config()
        enabled_panels = [name for name, is_enabled in panel_config.items() if is_enabled]

        panels_to_render = []
        for panel_id in enabled_panels:
            generator_func = REPORT_DATA_GENERATORS.get(panel_id)
            if generator_func:
                logger.debug(f"Generating data for panel: {panel_id}")
                panel_data = generator_func(collection)
                panels_to_render.append(
                    {
                        "id": panel_id,
                        "title": panel_id.replace("_", " ").title(),
                        "data": panel_data,
                    }
                )
            else:
                logger.warning(f"No data generator found for configured panel: {panel_id}")

        template_file, template_base_dir = resolve_template_path(report_type="collection", name_or_path=template)

        env = Environment(loader=FileSystemLoader(template_base_dir), autoescape=True)
        env.globals["human_filesize"] = human_filesize
        env.globals["get_media_type_icon"] = get_media_type_icon

        jinja_template = env.get_template(template_file.name)

        collection_dict = collection.to_dict()
        collection_dict["panels"] = panels_to_render

        full_collection_data_json = json.dumps(collection_dict, default=str)

        context = {
            "report_title": f"Directory Report: {html.escape(pathlib.Path(dir_path).name)}",
            "collection_source_path": dir_path,
            "generation_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "dorsal_version": __version__,
            "panels": panels_to_render,
            "full_collection_data_json": full_collection_data_json,
        }

        html_content = jinja_template.render(context)

        if output_path:
            output_file = pathlib.Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"HTML dashboard saved to: {output_path}")
            return None

        return html_content
    except Exception as e:
        logger.exception(f"Failed to generate HTML dashboard for '{dir_path}'.")
        if isinstance(e, (DorsalError, FileNotFoundError)):
            raise
        raise DorsalError(f"Could not generate HTML dashboard for {dir_path}: {e}") from e
