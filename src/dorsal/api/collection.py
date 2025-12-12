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

import logging
import pathlib
from typing import Any, Literal, TYPE_CHECKING, overload

from dorsal.common.exceptions import DorsalClientError, DorsalError
from dorsal.common.constants import API_MAX_BATCH_SIZE

if TYPE_CHECKING:
    from rich.console import Console
    from dorsal.client.validators import (
        AddFilesResponse,
        CollectionsResponse,
        CollectionWebLocationResponse,
        RemoveFilesResponse,
    )
    from dorsal.file.validators.collection import (
        FileCollection,
        SingleCollectionResponse,
        HydratedSingleCollectionResponse,
    )

logger = logging.getLogger(__name__)


@overload
def list_collections(
    page: int = 1,
    per_page: int = 25,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic"],
) -> "CollectionsResponse": ...


@overload
def list_collections(
    page: int = 1,
    per_page: int = 25,
    api_key: str | None = None,
    *,
    mode: Literal["dict"],
) -> dict[str, Any]: ...


@overload
def list_collections(
    page: int = 1,
    per_page: int = 25,
    api_key: str | None = None,
    *,
    mode: Literal["json"],
) -> str: ...


def list_collections(
    page: int = 1,
    per_page: int = 25,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
) -> "CollectionsResponse | dict[str, Any] | str":
    """
    Retrieves a paginated list of collections from DorsalHub.

    This is a high-level wrapper around the DorsalClient's list_collections
    method, providing a simple way to access collection information.

    Example:
        ```python
        from dorsal.api.collection import list_dorsal_collections

        # Get the first page of collections as Pydantic objects
        response = list_dorsal_collections()
        print(f"Found {response.pagination.record_count} total collections.")
        for collection in response.results:
            print(f"- {collection.name} (ID: {collection.id})")

        # Get the second page as a JSON string
        response_json = list_dorsal_collections(page=2, mode="json")
        print(response_json)
        ```

    Args:
        page (int): The page number for pagination. Defaults to 1.
        per_page (int): The number of collections per page. Defaults to 25.
        api_key (str, optional): An API key for this request, overriding the
            client's default. Defaults to None.
        mode (Literal["pydantic", "dict", "json"]): The desired return format.
            Defaults to "pydantic".

    Returns:
        Union[CollectionsResponse, dict, str]: The search results, formatted
            according to the specified `mode`.

    Raises:
        DorsalClientError: For client-side validation errors or API errors
            like authentication or rate limiting.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = ""
    if api_key:
        log_message_context = "using temporary client with provided API key"
        logger.debug("API key override provided for list_collections. Creating temporary DorsalClient.")
        effective_client = DorsalClient(api_key=api_key)
    else:
        log_message_context = "using shared client"
        logger.debug("No API key override for list_collections. Using shared client instance.")
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching list_collections to client (%s) with params: page=%d, per_page=%d",
        log_message_context,
        page,
        per_page,
    )

    try:
        response = effective_client.list_collections(
            page=page,
            per_page=per_page,
        )

        logger.debug(
            "Collection list successful. Returned page %d of %d, with %d records.",
            response.pagination.current_page,
            response.pagination.page_count,
            len(response.records),
        )

        if mode == "pydantic":
            return response
        if mode == "dict":
            return response.model_dump(mode="json", by_alias=True, exclude_none=True)
        if mode == "json":
            return response.model_dump_json(indent=2, by_alias=True, exclude_none=True)

        raise ValueError(f"Invalid mode: '{mode}'. Must be one of 'pydantic', 'dict', or 'json'.")

    except DorsalError as err:
        logger.warning(
            "A client error occurred during list_dorsal_collections (%s): %s - %s",
            log_message_context,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during list_dorsal_collections (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred while listing collections: {err}") from err


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[True],
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic"],
) -> "HydratedSingleCollectionResponse": ...


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[True],
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["dict"],
) -> dict[str, Any]: ...


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[True],
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["json"],
) -> str: ...


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[False],
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic"],
) -> "SingleCollectionResponse": ...


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[False],
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["dict"],
) -> dict[str, Any]: ...


@overload
def get_collection(
    collection_id: str,
    hydrate: Literal[False] = False,
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["json"],
) -> str: ...


def get_collection(
    collection_id: str,
    hydrate: bool = False,
    page: int = 1,
    per_page: int = 30,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
) -> "SingleCollectionResponse | HydratedSingleCollectionResponse | dict[str, Any] | str":
    """
    Retrieves a specific collection and its contents from DorsalHub.

    Args:
        collection_id (str): The unique ID of the collection to fetch.
        hydrate (bool): If True, returns fully detailed file records. Defaults to False.
        page (int): The page number for file contents. Defaults to 1.
        per_page (int): The number of file records per page. Defaults to 30.
        api_key (str, optional): An API key for this request.
        mode (Literal["pydantic", "dict", "json"]): The desired return format.

    Returns:
        The collection data, formatted according to the specified `mode`.

    Raises:
        DorsalClientError: For API errors like not found or authentication issues.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching get_collection to client (%s) for ID: '%s', hydrate=%s",
        log_message_context,
        collection_id,
        hydrate,
    )
    response: SingleCollectionResponse | HydratedSingleCollectionResponse
    try:
        if hydrate:
            response = effective_client.get_collection(
                collection_id=collection_id,
                hydrate=True,
                page=page,
                per_page=per_page,
            )
        else:
            response = effective_client.get_collection(
                collection_id=collection_id,
                hydrate=False,
                page=page,
                per_page=per_page,
            )

        if mode == "pydantic":
            return response
        if mode == "dict":
            return response.model_dump(mode="json", by_alias=True, exclude_none=True)
        if mode == "json":
            return response.model_dump_json(indent=2, by_alias=True, exclude_none=True)

        raise ValueError(f"Invalid mode: '{mode}'.")

    except DorsalError as err:
        logger.warning(
            "A client error occurred during get_dorsal_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during get_dorsal_collection (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred while getting collection '{collection_id}': {err}") from err


@overload
def update_collection(
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic"],
) -> "FileCollection": ...


@overload
def update_collection(
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    api_key: str | None = None,
    *,
    mode: Literal["dict"],
) -> dict[str, Any]: ...


@overload
def update_collection(
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    api_key: str | None = None,
    *,
    mode: Literal["json"],
) -> str: ...


def update_collection(
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    api_key: str | None = None,
    *,
    mode: Literal["pydantic", "dict", "json"] = "pydantic",
) -> "FileCollection | dict[str, Any] | str":
    """
    Updates the metadata of a remote collection on DorsalHub.

    Args:
        collection_id (str): The unique ID of the collection to update.
        name (str, optional): The new name for the collection.
        description (str, optional): The new description for the collection.
        api_key (str, optional): An API key for this request.
        mode (Literal["pydantic", "dict", "json"]): The desired return format.

    Returns:
        The updated collection data, formatted according to the specified `mode`.

    Raises:
        DorsalClientError: For API errors.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    if not any([name, description]):
        raise ValueError("At least one field (name or description) must be provided to update.")

    effective_client: DorsalClient

    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        log_message_context = "using shared client"
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching update_collection to client (%s) for ID: '%s'",
        log_message_context,
        collection_id,
    )

    try:
        response = effective_client.update_collection(collection_id=collection_id, name=name, description=description)

        if mode == "pydantic":
            return response
        if mode == "dict":
            return response.model_dump(mode="json", by_alias=True, exclude_none=True)
        if mode == "json":
            return response.model_dump_json(indent=2, by_alias=True, exclude_none=True)

        raise ValueError(f"Invalid mode: '{mode}'.")

    except DorsalError as err:
        logger.warning(
            "A client error occurred during update_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during update_collection (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred while updating collection '{collection_id}': {err}") from err


def add_files_to_collection(
    collection_id: str,
    hashes: list[str],
    api_key: str | None = None,
) -> "AddFilesResponse":
    """
    Adds a list of files to a remote collection by their hash.

    This function automatically handles batching for large lists of hashes
    to comply with the API limit (10,000 per request).

    Args:
        collection_id (str): The unique ID of the collection to modify.
        hashes (list[str]): A list of SHA-256 file hashes to add.
        api_key (str, optional): An API key for this request.

    Returns:
        AddFilesResponse: A consolidated response summarizing the results of all batches.

    Raises:
        DorsalClientError: For API errors.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient
    from dorsal.client.validators import AddFilesResponse

    if not hashes:
        raise ValueError("The 'hashes' list cannot be empty.")

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching add_files_to_collection to client (%s) for ID: '%s' with %d hashes.",
        log_message_context,
        collection_id,
        len(hashes),
    )

    total_added = 0
    total_duplicates = 0
    total_invalid = 0
    batches = [hashes[i : i + API_MAX_BATCH_SIZE] for i in range(0, len(hashes), API_MAX_BATCH_SIZE)]

    try:
        for i, batch in enumerate(batches):
            logger.debug(f"Processing batch {i + 1}/{len(batches)}...")
            response = effective_client.add_files_to_collection(collection_id=collection_id, hashes=batch)
            total_added += response.added_count
            total_duplicates += response.duplicate_count
            total_invalid += response.invalid_count

        aggregate_response = AddFilesResponse(
            added_count=total_added,
            duplicate_count=total_duplicates,
            invalid_count=total_invalid,
        )
        logger.info(
            "Successfully finished adding files to collection '%s'. Added: %d, Duplicates: %d, Invalid: %s",
            collection_id,
            aggregate_response.added_count,
            aggregate_response.duplicate_count,
            aggregate_response.invalid_count,
        )
        return aggregate_response

    except DorsalError as err:
        logger.warning(
            "A client error occurred during add_files_to_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during add_files_to_collection (%s).",
            log_message_context,
        )
        raise DorsalError(
            f"An unexpected error occurred while adding files to collection '{collection_id}': {err}"
        ) from err


def remove_files_from_collection(
    collection_id: str,
    hashes: list[str],
    api_key: str | None = None,
) -> "RemoveFilesResponse":
    """
    Removes a list of files from a remote collection by their hash.

    This function automatically handles batching for large lists of hashes
    to comply with the API limit (10,000 per request).

    Args:
        collection_id (str): The unique ID of the collection to modify.
        hashes (list[str]): A list of SHA-256 file hashes to remove.
        api_key (str, optional): An API key for this request.

    Returns:
        RemoveFilesResponse: A consolidated response summarizing the results.

    Raises:
        DorsalClientError: For API errors.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient
    from dorsal.client.validators import RemoveFilesResponse

    if not hashes:
        raise ValueError("The 'hashes' list cannot be empty.")

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching remove_files_from_collection to client (%s) for ID: '%s' with %d hashes.",
        log_message_context,
        collection_id,
        len(hashes),
    )

    total_removed = 0
    total_not_found = 0
    batches = [hashes[i : i + API_MAX_BATCH_SIZE] for i in range(0, len(hashes), API_MAX_BATCH_SIZE)]

    try:
        for i, batch in enumerate(batches):
            logger.debug(f"Processing batch {i + 1}/{len(batches)}...")
            response = effective_client.remove_files_from_collection(collection_id=collection_id, hashes=batch)
            total_removed += response.removed_count
            total_not_found += response.not_found_count

        aggregate_response = RemoveFilesResponse(removed_count=total_removed, not_found_count=total_not_found)
        logger.info(
            "Successfully finished removing files from collection '%s'. Removed: %d",
            collection_id,
            aggregate_response.removed_count,
        )
        return aggregate_response

    except DorsalError as err:
        logger.warning(
            "A client error occurred during remove_files_from_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during remove_files_from_collection (%s).",
            log_message_context,
        )
        raise DorsalError(
            f"An unexpected error occurred while removing files from collection '{collection_id}': {err}"
        ) from err


def make_collection_public(
    collection_id: str,
    api_key: str | None = None,
) -> "CollectionWebLocationResponse":
    """
    Makes a private collection public.

    This is a high-level wrapper that handles client instantiation and error logging.

    Args:
        collection_id (str): The unique ID of the collection to make public.
        api_key (str, optional): An API key for this request.

    Returns:
        CollectionWebLocationResponse: An object containing the new public web URL.

    Raises:
        DorsalClientError: For API errors (e.g., ConflictError if already public).
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching make_collection_public to client (%s) for ID: '%s'",
        log_message_context,
        collection_id,
    )

    try:
        response = effective_client.make_collection_public(collection_id=collection_id)
        logger.info("Successfully made collection '%s' public.", collection_id)
        return response

    except DorsalError as err:
        logger.warning(
            "A client error occurred during make_collection_public (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during make_collection_public (%s).",
            log_message_context,
        )
        raise DorsalError(
            f"An unexpected error occurred while making collection '{collection_id}' public: {err}"
        ) from err


def make_collection_private(
    collection_id: str,
    api_key: str | None = None,
) -> "CollectionWebLocationResponse":
    """
    Makes a public collection private.

    This is a high-level wrapper that handles client instantiation and error logging.

    Args:
        collection_id (str): The unique ID of the collection to make private.
        api_key (str, optional): An API key for this request.

    Returns:
        CollectionWebLocationResponse: An object containing the new private web URL.

    Raises:
        DorsalClientError: For API errors (e.g., ConflictError if already private).
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching make_collection_private to client (%s) for ID: '%s'",
        log_message_context,
        collection_id,
    )

    try:
        response = effective_client.make_collection_private(collection_id=collection_id)
        logger.info("Successfully made collection '%s' private.", collection_id)
        return response

    except DorsalError as err:
        logger.warning(
            "A client error occurred during make_collection_private (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during make_collection_private (%s).",
            log_message_context,
        )
        raise DorsalError(
            f"An unexpected error occurred while making collection '{collection_id}' private: {err}"
        ) from err


def export_collection(
    collection_id: str,
    output_path: str | pathlib.Path,
    poll_interval: int = 5,
    timeout: int | None = 3600,
    api_key: str | None = None,
    console: "Console | None" = None,
    palette: dict | None = None,
) -> None:
    """
    Exports a remote file collection from DorsalHub.

    Starts an export job, polls for its completion, and downloads to a local path.

    The exported file will be in .json.gz format.

    Args:
        collection_id (str): The ID of the collection to export.
        output_path (str | pathlib.Path): The local path to save the exported file.
        poll_interval (int): Seconds to wait between status checks.
        timeout (int | None): Total seconds to wait for the job to complete.
        api_key (str, optional): An API key for this request.
        console (Console, optional): A rich.console.Console for progress display.
        palette (dict, optional): Color palette for the progress bar.

    Raises:
        DorsalClientError: For API errors.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching export_collection to client (%s) for ID: '%s'",
        log_message_context,
        collection_id,
    )

    try:
        effective_client.export_collection(
            collection_id=collection_id,
            output_path=str(output_path),
            poll_interval=poll_interval,
            timeout=timeout,
            console=console,
            palette=palette,
        )
        logger.info("Successfully exported collection '%s' to '%s'", collection_id, output_path)

    except DorsalError as err:
        logger.warning(
            "A client error occurred during export_dorsal_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during export_dorsal_collection (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred while exporting collection '{collection_id}': {err}") from err


def delete_collection(
    collection_id: str,
    api_key: str | None = None,
) -> None:
    """
    Deletes a file collection from DorsalHub by its ID.

    Args:
        collection_id (str): The unique ID of the collection to delete.
        api_key (str, optional): An API key for this request.

    Raises:
        DorsalClientError: For API errors.
        DorsalError: For other unexpected library errors.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.client import DorsalClient

    if not collection_id:
        raise ValueError("collection_id cannot be empty.")

    effective_client: DorsalClient
    log_message_context = "using shared client"
    if api_key:
        log_message_context = "using temporary client with provided API key"
        effective_client = DorsalClient(api_key=api_key)
    else:
        effective_client = get_shared_dorsal_client()

    logger.debug(
        "Dispatching delete_collections to client (%s) for ID: '%s'",
        log_message_context,
        collection_id,
    )

    try:
        effective_client.delete_collections(collection_ids=[collection_id])
        logger.info("Successfully dispatched deletion for collection '%s'", collection_id)
        return

    except DorsalError as err:
        logger.warning(
            "A client error occurred during delete_dorsal_collection (%s): %s",
            log_message_context,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "An unexpected error occurred during delete_dorsal_collection (%s).",
            log_message_context,
        )
        raise DorsalError(f"An unexpected error occurred while deleting collection '{collection_id}': {err}") from err
