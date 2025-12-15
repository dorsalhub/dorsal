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
import json
import os
import time
import platform
from typing import Any, Literal, overload, NoReturn, Sequence, TYPE_CHECKING
from urllib.parse import urljoin

import logging

from jsonschema.exceptions import SchemaError as JSONSchemaSchemaError
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry


from dorsal.common import constants
from dorsal.common.auth import is_offline_mode, read_api_key
from dorsal.common.constants import BASE_URL, VALID_DATASET_TYPES
from dorsal.common.environment import is_jupyter_environment
from dorsal.common.exceptions import (
    APIError,
    ApiDataValidationError,
    AuthError,
    BadRequestError,
    BatchSizeError,
    ConflictError,
    DorsalError,
    DorsalClientError,
    ForbiddenError,
    NetworkError,
    NotFoundError,
    DorsalOfflineError,
    PydanticValidationError,
    RateLimitError,
    SchemaFormatError,
    UnsupportedHashError,
)
from dorsal.common.model import scrub_pii_from_model
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    get_json_schema_validator,
)
from dorsal.common.validators.datasets import (
    Dataset,
    is_valid_dataset_id_or_schema_id,
)
from dorsal.file.integrity import align_core_annotation_privacy
from dorsal.file.validators.common import validate_hex64
from dorsal.file.utils.hashes import HashFunction, parse_validate_hash
from dorsal.version import __version__

if TYPE_CHECKING:
    from rich.console import Console  # pragma: no cover
    from dorsal.file.validators.file_record import (
        Annotation,
        AnnotationGroup,
        DeletionScope,
        FileRecordDateTime,
        FileRecordStrict,
        FileSearchResponse,
        FileTag,
        NewFileTag,
        UserFileSearchQuery,
        ValidateTagsResult,
    )  # pragma: no cover
    from dorsal.file.validators.collection import (
        BulkDetailsRequest,
        SingleCollectionResponse,
        HydratedSingleCollectionResponse,
    )  # pragma: no cover

    from dorsal.client.validators import (
        AnnotationIndexResult,
        CollectionCreateRequest,
        CollectionsResponse,
        CollectionWebLocationResponse,
        CollectionSyncRequest,
        CollectionSyncResponse,
        ExportJobStatus,
        ExportJobRequest,
        FileAnnotationResponse,
        FileCollection,
        FileIndexResponse,
        NewDatasetResponse,
        RecordIndexResult,
        FileTagResponse,
        FileDeleteResponse,
        AddFilesResponse,
        AddFilesRequest,
        RemoveFilesRequest,
        RemoveFilesResponse,
    )  # pragma: no cover


logger = logging.getLogger(__name__)

SEARCH_PER_PAGE_DEFAULT = 25
SEARCH_PER_PAGE_MIN = 1
SEARCH_PER_PAGE_MAX = 50


class DorsalClientSession(requests.Session):
    """requests.Session which Intercepts all HTTP requests for `DORSAL_OFFLINE` check."""

    def send(self, request, *args, **kwargs):
        if is_offline_mode():
            url = getattr(request, "url", "unknown")
            logger.warning("Blocked network request due to Offline Mode: %s", url)
            raise DorsalOfflineError(
                "Calls to DorsalHub API are blocked: DORSAL_OFFLINE environment variable is active."
            )

        return super().send(request, *args, **kwargs)


class DorsalClient:
    """The low-level client for interacting with the DorsalHub API.

    This class handles all direct communication with the DorsalHub API endpoints.
    It manages the HTTP session, authentication headers, request serialization,
    response parsing, and error handling.

    For most common workflows, it's recommended to use the higher-level
    interfaces like `LocalFile`, `DorsalFile`, `MetadataReader` or the functions in `dorsal.api`.
    However, this client is available for users who need more fine-grained
    control over API requests.

    Example:
        ```python
        from dorsal.client import DorsalClient

        # Initialize with an explicit API key
        client = DorsalClient(api_key="your_dorsal_api_key_here")

        # Alternatively, the client can read the key from the
        # DORSAL_API_KEY environment variable if the `api_key`
        # argument is omitted.
        # client = DorsalClient()
        ```

    Args:
        api_key (str, optional): The API key for authentication. If not
            provided, the client will attempt to read it from the
            `DORSAL_API_KEY` environment variable. Defaults to None.
        base_url (str, optional): The base URL for the Dorsal API. Defaults
            to the official DorsalHub production URL.
        identity (str, optional): An identifier for the client instance, which
            is used in the User-Agent header for requests. Defaults to
            "dorsal.DorsalClient".
        timeout (float, optional): The default timeout for HTTP requests
            in seconds. Defaults to 10.0.
    """

    _file_records_batch_insert_size = 10_000
    _dataset_records_batch_insert_size = 10_000

    _default_timeout = 10.0
    _dorsal_base_url = BASE_URL
    _default_identity = "dorsal.DorsalClient"

    _collections_endpoint = constants.API_ENDPOINT_COLLECTIONS
    _export_endpoint = constants.API_ENDPOINT_EXPORT
    _files_endpoint = constants.API_ENDPOINT_FILES
    _file_search_endpoint = constants.API_ENDPOINT_FILE_SEARCH
    _file_tag_validation_endpoint = constants.API_ENDPOINT_FILE_TAG_VALIDATION
    _namespaces_endpoint = constants.API_ENDPOINT_NAMESPACES
    _user_check_files_indexed_endpoint = constants.API_ENDPOINT_USER_CHECK_FILES_INDEXED

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _dorsal_base_url,
        identity: str = _default_identity,
        timeout: float = _default_timeout,
    ):
        """
        Initialize the DorsalClient.

        Args:
            api_key: API key for authentication. Reads from env var if None.
            base_url: Base URL for the Dorsal API.
            identity: Identifier for the client instance (used in User-Agent).
            timeout: Default timeout for HTTP requests in seconds.
        """
        if is_offline_mode():
            raise DorsalOfflineError("Cannot initialize DorsalClient: DORSAL_OFFLINE environment variable is set.")
        self.api_key = read_api_key(api_key=api_key)
        self.base_url = base_url.rstrip("/")
        self.identity = identity
        self.session = self._build_requests_session()
        self.timeout = timeout
        self.last_response: requests.Response | None = None
        self.last_request: requests.Request | None = None
        logger.debug(
            "DorsalClient initialized successfully. Base URL: '%s', Identity: '%s'. API key configured: %s (DEBUG ONLY: %s)",
            self.base_url,
            self.identity,
            ("Yes" if self.api_key else "No (will use session headers if previously set, or fail if auth needed)"),
            self.api_key,
        )

    def _make_user_agent(self) -> dict:
        dorsal_user_agent = {
            "caller": self.identity,
            "client_version": f"dorsal-python-{__version__}",
            "platform": platform.platform(),
        }

        return dorsal_user_agent

    def _make_request_headers(self, api_key: str | None = None) -> dict:
        dorsal_user_agent = self._make_user_agent()
        dorsal_user_agent_string = json.dumps(dorsal_user_agent)
        user_agent_string = f"Dorsal/{__version__} Python Client"
        api_key = api_key if api_key is not None else self.api_key
        if not api_key:
            raise AuthError("API Key is missing.")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": user_agent_string,
            "X-Dorsal-User-Agent": dorsal_user_agent_string,
            "Authorization": f"Bearer {api_key}",
        }

        return headers

    def _build_requests_session(self):
        session = DorsalClientSession()
        session.headers.update(self._make_request_headers())

        retry_strategy = Retry(
            total=3,
            status_forcelist=[
                429,
                500,
                502,
                503,
                504,
            ],  # 429 uses Retry-After header by default
            allowed_methods=["HEAD", "GET", "OPTIONS", "PUT", "DELETE"],
            backoff_factor=1,  # after retry no. 2, delay = {backoff factor} * (2 ** ({number of total retries} - 1)))
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _handle_api_error(self, response: requests.Response, suppress_warning_log: bool = False) -> NoReturn:
        status_code = response.status_code
        try:
            error_data: dict = response.json()
            detail = error_data.get("detail", response.text)
        except json.JSONDecodeError:
            detail = response.text

        if not suppress_warning_log:
            logger.warning(
                "API request to %s failed with status %s. Detail: %s",
                response.url,
                status_code,
                detail,
            )

        if status_code == 400:
            err_message = f"Bad Request: {detail}"
            raise BadRequestError(err_message, request_url=response.url, response_text=response.text)
        elif status_code == 401:
            auth_message = f"Authentication failed: {detail}"
            raise AuthError(auth_message)
        elif status_code == 402:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message=f"API quota exceeded: {detail}",
                request_url=response.url,
                retry_after=retry_after,
                response_text=response.text,
            )
        elif status_code == 403:
            raise ForbiddenError(
                message=f"Forbidden: {detail}",
                request_url=response.url,
                response_text=response.text,
            )
        elif status_code == 404:
            raise NotFoundError(
                message=f"Resource not found: {detail}",
                request_url=response.url,
                response_text=response.text,
            )
        elif status_code == 409:
            raise ConflictError(
                message=f"Conflict occurred: {detail}",
                request_url=response.url,
                response_text=response.text,
            )
        elif status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message=f"Rate limit exceeded: {detail}",
                request_url=response.url,
                retry_after=retry_after,
                response_text=response.text,
            )
        elif 400 <= status_code < 500:
            raise APIError(
                status_code=status_code,
                detail=f"Client error ({status_code}): {detail}",
                request_url=response.url,
                response_text=response.text,
            )
        elif 500 <= status_code < 600:
            raise APIError(
                status_code=status_code,
                detail=f"Server error ({status_code}): {detail}",
                request_url=response.url,
                response_text=response.text,
            )
        else:
            raise APIError(
                status_code=status_code,
                detail=f"Unexpected HTTP status {status_code}: {detail}",
                request_url=response.url,
                response_text=response.text,
            )

    def _parse_validate_file_hash(self, hash_string: str) -> tuple[str, str]:
        logger.debug("Client: Validating hash string: '%s'", hash_string)

        file_hash, hash_function = parse_validate_hash(hash_string=hash_string)

        if file_hash is None or hash_function is None:
            error_msg = f"Invalid or unsupported hash string format: '{hash_string}'. "
            logger.warning(error_msg)
            raise ValueError(error_msg)

        if hash_function == "TLSH":
            error_msg = "Lookup via TLSH is currently unsupported."
            logger.warning(error_msg)
            raise UnsupportedHashError(error_msg)

        logger.debug(
            "Client: Validation successful. Type: %s, Hash: %s",
            hash_function,
            file_hash,
        )
        return file_hash, hash_function

    def _split_dataset_or_schema_id(self, value: str) -> tuple[str, str]:
        if not is_valid_dataset_id_or_schema_id(value=value):
            raise DorsalClientError("Schema ID parsing failure: %s", value)
        try:
            namespace, name = value.split("/")
            return namespace, name
        except Exception as err:  # pragma: no cover
            raise DorsalClientError("Schema ID parsing failure: %s", value) from err  # pragma: no cover

    def _make_file_key(self, file_hash: str, hash_function: str):
        if hash_function == HashFunction.SHA256.value:
            return file_hash
        return f"{hash_function}:{file_hash}"

    def _make_get_public_file_record_url(self, file_key: str):
        return f"{self.base_url}/{self._files_endpoint}/public/{file_key.strip('/')}"

    def _make_get_private_file_record_url(self, file_key: str):
        return f"{self.base_url}/{self._files_endpoint}/private/{file_key.strip('/')}"

    def _make_get_dataset_url(self, namespace: str, name: str) -> str:
        return f"{self.base_url}/{self._namespaces_endpoint}/{namespace.strip('/')}/datasets/{name.strip('/')}"

    def _make_get_dataset_schema_url(self, namespace: str, name: str) -> str:
        return f"{self.base_url}/{self._namespaces_endpoint}/{namespace.strip('/')}/datasets/{name.strip('/')}/schema"

    def _make_get_dataset_type_url(self, namespace: str, name: str) -> str:
        return f"{self.base_url}/{self._namespaces_endpoint}/{namespace.strip('/')}/datasets/{name.strip('/')}/type"

    def _make_check_files_indexed_url(self) -> str:
        return f"{self.base_url}/{self._user_check_files_indexed_endpoint.strip('/')}"

    def _make_add_tags_to_file_url(self, file_hash: str) -> str:
        return f"{self.base_url}/{self._files_endpoint}/{file_hash.strip('/')}/tags"

    def _make_delete_tag_url(self, file_hash: str, tag_id: str) -> str:
        return f"{self.base_url}/{self._files_endpoint}/{file_hash.strip('/')}/tags/{tag_id.strip('/')}"

    def _make_collections_url(self) -> str:
        """Constructs the URL for the collections API endpoint."""
        return f"{self.base_url}/{self._collections_endpoint.strip('/')}"

    def _make_collection_url(self, collection_id: str) -> str:
        """Constructs the URL for a specific collection."""
        return f"{self.base_url}/{self._collections_endpoint.strip('/')}/{collection_id.strip('/')}"

    def _make_collection_files_url(self, collection_id: str) -> str:
        """Constructs the URL for adding files to a specific collection."""
        return f"{self.base_url}/{self._collections_endpoint.strip('/')}/{collection_id.strip('/')}/files"

    def _make_collection_action_url(self, collection_id: str, action: str) -> str:
        """Constructs the URL for performing an action on a collection."""
        return f"{self.base_url}/{self._collections_endpoint.strip('/')}/{collection_id.strip('/')}/actions/{action}"

    def _make_collection_sync_job_url(self, job_id: str) -> str:
        """Constructs the URL for polling a sync job's status."""
        return f"{self.base_url}/{self._collections_endpoint.strip('/')}/sync-jobs/{job_id.strip('/')}"

    def _make_get_export_job_status_url(self, job_id: str) -> str:
        """Constructs the URL for getting an export job's status."""
        return f"{self.base_url}/{self._export_endpoint.strip('/')}/jobs/{job_id.strip('/')}"

    def _make_start_collection_export_url(self, collection_id: str) -> str:
        """Constructs the URL for starting a collection export."""
        return f"{self.base_url}/{self._export_endpoint.strip('/')}/collection/{collection_id.strip('/')}"

    def _make_add_file_annotation_url(self, file_hash: str, namespace: str, name: str) -> str:
        """Constructs the URL for adding an annotation to a file."""
        return f"{self.base_url}/{self._files_endpoint}/{file_hash.strip('/')}/annotations/{namespace.strip('/')}/{name.strip('/')}"

    def _make_get_file_annotation_url(self, file_hash: str, annotation_id: str) -> str:
        """Constructs the URL for retrieving a specific file annotation."""
        return f"{self.base_url}/{self._files_endpoint}/{file_hash.strip('/')}/annotations/{annotation_id.strip('/')}"

    def _make_delete_file_annotation_url(self, file_hash: str, annotation_id: str) -> str:
        """Constructs the URL for deleting a specific file annotation."""
        return f"{self.base_url}/{self._files_endpoint.strip('/')}/{file_hash.strip('/')}/annotations/{annotation_id.strip('/')}"

    def _validate_sha256_hashes(self, file_hashes: list[str]) -> list[str]:
        if not isinstance(file_hashes, list) or not file_hashes:
            raise DorsalClientError("Input must be a non-empty list of hash strings.")

        validated_hashes = []
        for i, file_hash in enumerate(file_hashes):
            try:
                validated_hash = validate_hex64(file_hash)
                validated_hashes.append(validated_hash)
            except ValueError as err:
                raise DorsalClientError(f"Invalid SHA-256 hash at index {i}: {file_hash}") from err

        return validated_hashes

    def validate_tag(self, file_tags: "Sequence[FileTag]", api_key: str | None = None) -> "ValidateTagsResult":
        """Validates a list of file tags against server-side rules.

        This method is used to check if one or more proposed `FileTag` objects
        are valid according to the platform's rules before they are permanently
        attached to a file record.

        Example:
            ```python
            from dorsal.client import DorsalClient
            from dorsal.file.validators.file_record import FileTag

            client = DorsalClient()

            # Create a tag to validate
            tag_to_check = FileTag(name="review-status", value="approved")

            try:
                result = client.validate_tag([tag_to_check])
                if result.valid:
                    print("Tag is valid!")
                else:
                    print(f"Tag is invalid: {result.message}")
            except Exception as e:
                print(f"Error validating tag: {e}")
            ```

        Args:
            file_tags (list[FileTag]): A list of `FileTag` Pydantic model
                instances to validate.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            ValidateTagsResult: A Pydantic model instance containing the overall
                validation result and a message from the server.

        Raises:
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.file.validators.file_record import (
            ValidateTagsResult,
            NewFileTag,
        )

        logger.debug("Client: validate_tag called with %d tags.", len(file_tags))

        if not file_tags or not isinstance(file_tags, list):
            raise DorsalClientError("Input 'file_tags' must be a non-empty list of FileTag objects.")

        request_body = []
        for i, tag in enumerate(file_tags):
            try:
                if not isinstance(tag, NewFileTag):
                    if isinstance(tag, dict):
                        tag = NewFileTag(**tag)
                    else:
                        raise TypeError(f"Item at index {i} is not a FileTag instance or a dict.")
                request_body.append(tag.model_dump(mode="json"))
            except PydanticValidationError as err:
                logger.error("Validation error for FileTag at index %s: %s", i, err.errors())
                raise DorsalClientError(f"Invalid data for FileTag at index {i}: {err}") from err
            except TypeError as err:
                logger.error("Type error for FileTag at index %s: %s", i, err)
                raise DorsalClientError(str(err)) from err

        target_url = f"{self.base_url}/{self._file_tag_validation_endpoint}"
        logger.debug("Attempting to validate %d tags at: %s", len(request_body), target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out during tag validation for %s: %s", target_url, err)
            raise NetworkError(
                "Request timed out while trying to reach API for tag validation.",
                target_url,
                err,
            ) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error during tag validation for %s: %s", target_url, err)
            raise NetworkError(
                "Could not establish connection to server for tag validation.",
                target_url,
                err,
            ) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed during tag validation for %s: %s", target_url, err)
            raise NetworkError(
                "An unexpected error occurred during the HTTP request for tag validation.",
                target_url,
                err,
            ) from err

        if response.status_code != 200:
            logger.warning(
                "API responded with non-200 status %s during tag validation for %s.",
                response.status_code,
                target_url,
            )
            self._handle_api_error(response=response)
            raise APIError(
                response.status_code,
                "Unhandled API error during tag validation",
                target_url,
                response.text,
            )  # pragma: no cover

        try:
            json_response = response.json()
            validation_result = ValidateTagsResult(**json_response)
            logger.debug(
                "Successfully validated tags. Overall valid: %s, Message: '%s'",
                validation_result.valid,
                validation_result.message,
            )
            return validation_result
        except json.JSONDecodeError as err:
            snippet = response.text[:200]
            logger.error(
                "Failed to decode JSON from successful tag validation response (status %s) for %s. Snippet: %s",
                response.status_code,
                target_url,
                snippet,
            )
            raise ApiDataValidationError(
                message="API returned an invalid JSON response for tag validation despite success status.",
                request_url=target_url,
                response_text_snippet=snippet,
                original_exception=err,
            ) from err
        except PydanticValidationError as err:
            logger.error(
                "Successful tag validation response (status %s) for %s failed Pydantic validation against ValidateTagsResult. Errors: %s",
                response.status_code,
                target_url,
                err.errors(),
            )
            raise ApiDataValidationError(
                message="API response on tag validation success failed data validation against ValidateTagsResult.",
                request_url=target_url,
                validation_errors=err.errors(),
                response_text_snippet=(
                    json.dumps(json_response)[:200] if "json_response" in locals() else response.text[:200]
                ),
                original_exception=err,
            ) from err

    def add_tags_to_file(
        self, file_hash: str, tags: "list[NewFileTag]", api_key: str | None = None
    ) -> "FileTagResponse":
        """Adds one or more tags to a single file identified by its SHA-256 hash.

        This method sends a list of `NewFileTag` objects to the server to be
        applied to a specific file. The server will process each tag, adding it
        if it's new, upvoting it if it's an existing public tag, or taking no
        action if it's a duplicate private tag.

        Example:
            ```python
            from dorsal.client import DorsalClient
            from dorsal.file.validators.file_record import NewFileTag

            client = DorsalClient()
            file_hash = "123..." # A valid SHA-256 hash of a file on the platform

            tags_to_add = [
                NewFileTag(name="review_status", value="approved", private=False),
                NewFileTag(name="internal_id", value=9001, private=True),
            ]

            try:
                result = client.add_tags_to_file(file_hash, tags_to_add)
                if result.success:
                    print(f"Successfully processed tags for file {result.hash}")
                    for tag_result in result.tags:
                        print(f"- Tag '{tag_result.name}': {tag_result.status}")
            except Exception as e:
                print(f"An error occurred: {e}")
            ```

        Args:
            file_hash (str): The 64-character SHA-256 hash of the file to tag.
            tags (list[NewFileTag]): A list of `NewFileTag` Pydantic models
                representing the tags to apply.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            FileTagResponse: A Pydantic model instance containing the detailed
                outcome of the tagging operation for each tag.

        Raises:
            DorsalClientError: For client-side validation issues, like an
                invalid hash format or an empty list of tags.
            NotFoundError: If the file with the specified hash is not found.
            ForbiddenError: If you try to add a public tag to a file you
                haven't indexed.
            AuthError: If authentication fails.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
            ApiDataValidationError: If the API response cannot be parsed or
                validated against the expected model.
        """
        from dorsal.client.validators import FileTagResponse

        logger.debug(
            "Client: add_tags_to_file called for hash '%s' with %d tags.",
            file_hash,
            len(tags),
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        if not tags or not isinstance(tags, list):
            raise DorsalClientError("Input 'tags' must be a non-empty list.")

        target_url = self._make_add_tags_to_file_url(file_hash=validated_hash)
        try:
            request_body = [tag.model_dump(mode="json") for tag in tags]
        except AttributeError as err:
            raise DorsalClientError(
                "Each item in the 'tags' list must be a Pydantic model with a .model_dump() method."
            ) from err

        logger.debug("Attempting to add %d tags to file at: %s", len(request_body), target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to add tags for hash %s. API responded with status %s.",
                validated_hash,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

        try:
            json_response = response.json()
            tag_response = FileTagResponse(**json_response)
            logger.debug(
                "Successfully processed tags for hash %s. Success: %s.",
                validated_hash,
                tag_response.success,
            )
            return tag_response
        except json.JSONDecodeError as err:
            snippet = response.text[:200]
            logger.error(
                "Failed to decode JSON from successful tag operation (status %s) for %s.",
                response.status_code,
                target_url,
            )
            raise ApiDataValidationError(
                message="API returned an invalid JSON response despite success status.",
                request_url=target_url,
                response_text_snippet=snippet,
                original_exception=err,
            ) from err
        except PydanticValidationError as err:
            logger.error(
                "Successful tag operation response (status %s) for %s failed Pydantic validation. Errors: %s",
                response.status_code,
                target_url,
                err.errors(),
            )
            raise ApiDataValidationError(
                message="API response on success failed data validation against FileTagResponse.",
                request_url=target_url,
                validation_errors=err.errors(),
                response_text_snippet=(
                    json.dumps(json_response)[:200] if "json_response" in locals() else response.text[:200]
                ),
                original_exception=err,
            ) from err

    def delete_tag(self, *, file_hash: str, tag_id: str, api_key: str | None = None) -> None:
        """Deletes a single tag from a file using its unique tag ID.

        Args:
            file_hash (str): The 64-character SHA-256 hash of the file.
            tag_id (str): The unique identifier of the tag to delete.
            api_key (str | None): Optional API key to override the client's default.

        Returns:
            None: A successful deletion returns no content.

        Raises:
            DorsalClientError: For client-side validation issues.
            NotFoundError: If the file or tag is not found, or you do not have
                permission to delete it.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other unhandled API error.
        """
        logger.debug(
            "Client: delete_tag called for hash '%s' with tag_id '%s'.",
            file_hash,
            tag_id,
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        if not tag_id or not isinstance(tag_id, str):
            raise DorsalClientError("Input 'tag_id' must be a non-empty string.")

        target_url = self._make_delete_tag_url(file_hash=validated_hash, tag_id=tag_id)
        logger.debug("Attempting to delete tag at: %s", target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.delete(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.exception("HTTP DELETE request failed for %s", target_url)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 204:
            logger.warning(
                "Failed to delete tag %s for hash %s. API responded with status %s.",
                tag_id,
                validated_hash,
                response.status_code,
            )
            self._handle_api_error(response=response)

        logger.debug("Successfully deleted tag %s from file %s.", tag_id, validated_hash)
        return None

    def index_private_file_records(
        self,
        file_records: "Sequence[FileRecordStrict | dict]",
        api_key: str | None = None,
    ) -> FileIndexResponse:
        """Indexes a batch of file records as private to the authenticated user.

        This method sends a list of `FileRecordStrict` objects to the private
        indexing endpoint. Private records are only visible and accessible to the
        user who owns the provided API key.

        Example:
            ```python
            from dorsal.client import DorsalClient
            from dorsal.api import scan_file

            # Assumes client is an initialized DorsalClient
            client = DorsalClient()
            local_file = scan_file("path/to/private_document.pdf")

            if local_file.model.validation_hash:
                try:
                    response = client.index_private_file_records([local_file.model])
                    if response.success > 0:
                        print("Successfully indexed private file.")
                except Exception as e:
                    print(f"Error indexing file: {e}")
            ```

        Args:
            file_records (list[FileRecordStrict | dict]): A list of file records
                to be indexed. Items can be `FileRecordStrict` Pydantic models
                or dictionaries that conform to the model's structure.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            FileIndexResponse: A response object from the API detailing the
                result of the indexing operation.

        Raises:
            BatchSizeError: If the number of records exceeds the API limit.
            AuthError: If authentication fails (e.g., missing or invalid API Key).
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
            DorsalClientError: For client-side data validation issues.
        """
        return self._index_file_records(file_records=file_records, private=True, api_key=api_key)

    def index_public_file_records(
        self,
        file_records: "Sequence[FileRecordStrict | dict]",
        api_key: str | None = None,
    ) -> FileIndexResponse:
        """Indexes a batch of file records, making them publicly accessible.

        This method sends a list of `FileRecordStrict` objects to the public
        indexing endpoint. Public records can be viewed and accessed by anyone.

        Example:
            ```python
            from dorsal.client import DorsalClient
            from dorsal.api import scan_file

            # Assumes client is an initialized DorsalClient
            client = DorsalClient()

            # First, create a local file object to get its metadata
            local_file = scan_file("path/to/public_asset.png")

            # The client requires the 'strict' version of the model for upload
            if local_file.model.validation_hash:
                try:
                    response = client.index_public_file_records([local_file.model])
                    if response.success > 0:
                        print("Successfully indexed public file.")
                except Exception as e:
                    print(f"Error indexing file: {e}")
            ```

        Args:
            file_records (list[FileRecordStrict | dict]): A list of file records
                to be indexed. Items can be `FileRecordStrict` Pydantic models
                or dictionaries that conform to the model's structure.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            FileIndexResponse: A response object from the API detailing the
                result of the indexing operation.

        Raises:
            BatchSizeError: If the number of records exceeds the API limit.
            AuthError: If authentication fails (e.g., missing or invalid API Key).
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
            DorsalClientError: For client-side data validation issues.
        """
        return self._index_file_records(file_records=file_records, private=False, api_key=api_key)

    def _index_file_records(
        self,
        file_records: "Sequence[FileRecordStrict | dict]",
        private: bool,
        api_key: str | None = None,
    ) -> FileIndexResponse:
        from dorsal.file.validators.file_record import FileRecordStrict
        from dorsal.client.validators import FileIndexResponse

        """Helper method for indexing file records."""
        if not file_records:
            raise ValueError("file_records list cannot be empty for indexing.")

        if len(file_records) > self._file_records_batch_insert_size:
            raise BatchSizeError(
                f"Too many records for a single request: {len(file_records)} (limit: {self._file_records_batch_insert_size})"
            )

        validated_records: "list[FileRecordStrict]" = []
        for i, file_record_item in enumerate(file_records):
            try:
                if isinstance(file_record_item, dict):
                    file_record_item = FileRecordStrict(**file_record_item)
                elif not isinstance(file_record_item, FileRecordStrict):
                    raise TypeError(f"Item at index {i} is not a FileRecordStrict instance or a dict.")
                validated_records.append(file_record_item)
            except PydanticValidationError as err:
                logger.error("Validation error for record at index %s: %s", i, err.errors())
                raise DorsalClientError(f"Invalid data for record at index {i}: {err}") from err
            except TypeError as err:
                logger.error("Type error for record at index %s: %s", i, err)
                raise DorsalClientError(str(err)) from err

        records_to_send: list[FileRecordStrict] = []

        for i, rec in enumerate(validated_records):
            try:
                payload = rec.model_copy(deep=True)

                payload = align_core_annotation_privacy(record=payload, is_private=private)

                if not private:
                    payload = scrub_pii_from_model(payload)

                records_to_send.append(payload)

            except Exception as e:
                logger.exception(
                    "CRITICAL: Failed to apply integrity checks (privacy/scrubbing) to record at index %d (hash: %s).",
                    i,
                    getattr(rec, "hash", "unknown"),
                )
                raise DorsalClientError(
                    f"Internal error preparing record at index {i} for upload. Halting operation."
                ) from e

        request_body = [record.model_dump(exclude_none=True, mode="json", by_alias=True) for record in records_to_send]

        if private:
            target_url = f"{self.base_url}/{self._files_endpoint}/private"
            file_type = "private"
        else:
            target_url = f"{self.base_url}/{self._files_endpoint}/public"
            file_type = "public"

        logger.debug(
            "Attempting to index %s %s file records to: %s.",
            len(request_body),
            file_type,
            target_url,
        )

        try:
            if api_key is not None:
                headers = self._make_request_headers(api_key=api_key)
                response = self.session.post(
                    url=target_url,
                    json=request_body,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
            else:
                response = self.session.post(
                    url=target_url,
                    json=request_body,
                    allow_redirects=False,
                    timeout=self.timeout,
                )
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out: %s", target_url)
            raise NetworkError("Request timed out while trying to reach API.", target_url, err) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error for %s: %s", target_url, err)
            raise NetworkError("Could not establish connection to server.", target_url, err) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code not in (200, 201):
            logger.warning(
                "Failed to index records to %s. API responded with status %s.",
                target_url,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

        try:
            json_response = response.json()
            index_result = FileIndexResponse(**json_response)
            index_result.response = response
            logger.debug(
                "Successfully indexed %s %s file records. Response Status: %s. Total: %s, Success: %s, Error: %s",
                len(request_body),
                file_type,
                response.status_code,
                index_result.total,
                index_result.success,
                index_result.error,
            )
            return index_result
        except json.JSONDecodeError as err:
            snippet = response.text[:200]
            logger.error(
                "Failed to decode JSON from successful API response (status %s) for %s.",
                response.status_code,
                target_url,
            )
            raise ApiDataValidationError(
                message="API returned an invalid JSON response despite success status.",
                request_url=target_url,
                response_text_snippet=snippet,
                original_exception=err,
            ) from err
        except PydanticValidationError as err:
            logger.error(
                "Successful API response (status %s) for %s failed Pydantic validation for FileIndexResponse. Errors: %s",
                response.status_code,
                target_url,
                err.errors(),
            )
            raise ApiDataValidationError(
                message="API response on success failed data validation against FileIndexResponse.",
                request_url=target_url,
                validation_errors=err.errors(),
                response_text_snippet=(
                    json.dumps(json_response)[:200] if "json_response" in locals() else response.text[:200]
                ),
                original_exception=err,
            ) from err

    def _make_search_files_url(self) -> str:
        """Constructs the URL for the file search API endpoint."""
        return f"{self.base_url}/{self._file_search_endpoint.strip('/')}"

    def search_files(
        self,
        q: str,
        *,
        scope: Literal["user", "global"] = "user",
        deduplicate: bool = True,
        page: int = 1,
        per_page: int = SEARCH_PER_PAGE_DEFAULT,
        sort_by: Literal["date_modified", "date_created", "size", "name"] = "date_modified",
        sort_order: Literal["asc", "desc"] = "desc",
        match_any: bool,
        api_key: str | None = None,
    ) -> "FileSearchResponse":
        """
        Searches for file records across DorsalHub.

        This method performs a text-based search. The search can be limited to
        files indexed by the authenticated user (`scope='user'`) or expanded to
        all public files on the platform (`scope='global'`). Note that global
        search requires a premium account.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()

            # Search for PDF files indexed by the user
            try:
                response = client.search_files(q="extension:pdf", scope="user")
                print(f"Found {response.pagination.total_items} matching files.")
                for record in response.results:
                    print(f"- {record.name} (modified: {record.date_modified})")
            except Exception as e:
                print(f"An error occurred: {e}")
            ```

        Args:
            q (str): The search query string. Supports operators like
                `tag:`, `name:`, `extension:`.
            scope (Literal["user", "global"]): The scope of the search.
                Defaults to "user".
            deduplicate (bool): If True, returns only unique file records.
                Defaults to True.
            page (int): The page number for pagination. Defaults to 1.
            per_page (int): The number of results per page. Must be between
                1 and 50. Defaults to 25.
            sort_by (Literal): The field to sort results by.
            sort_order (Literal): The sort order ('asc' or 'desc').
            api_key (str, optional): An API key for this request, overriding
                the client's default. Defaults to None.

        Returns:
            FileSearchResponse: An object containing the search results,
                pagination info, and any errors.

        Raises:
            DorsalClientError: For client-side validation errors, like an
                invalid `per_page` value.
            ForbiddenError: If `scope='global'` is used without the required
                account permissions.
            AuthError: If the API key is invalid or missing.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
            ApiDataValidationError: If the API response cannot be parsed.
        """
        from dorsal.file.validators.file_record import FileSearchResponse

        if not (SEARCH_PER_PAGE_MIN <= per_page <= SEARCH_PER_PAGE_MAX):
            raise DorsalClientError(f"'per_page' must be between {SEARCH_PER_PAGE_MIN} and {SEARCH_PER_PAGE_MAX}.")

        if not q or not isinstance(q, str):
            raise DorsalClientError("'q' must be a non-empty string.")

        target_url = self._make_search_files_url()
        params = {
            "q": q,
            "scope": scope,
            "deduplicate": deduplicate,
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "match_any": match_any,
        }
        logger.debug("Attempting to search files at: %s with params: %s", target_url, params)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.get(
                url=target_url,
                params=params,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to search files. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

        try:
            json_response = response.json()
            search_response = FileSearchResponse(**json_response)
            logger.debug("Search API version: %s", search_response.api_version)
            logger.debug(
                "Successfully performed file search. Found %s total records.",
                search_response.pagination.record_count,
            )
            return search_response
        except json.JSONDecodeError as err:
            snippet = response.text[:200]
            logger.error("Failed to decode JSON from successful file search: %s", snippet)
            raise ApiDataValidationError(
                message="API returned an invalid JSON response despite success status.",
                request_url=target_url,
                response_text_snippet=snippet,
                original_exception=err,
            ) from err
        except PydanticValidationError as err:
            logger.error("File search response failed Pydantic validation: %s", err.errors())
            raise ApiDataValidationError(
                message="API response on success failed data validation against FileSearchResponse.",
                request_url=target_url,
                validation_errors=err.errors(),
                original_exception=err,
            ) from err

    def check_files_indexed(self, file_hashes: list[str], api_key: str | None = None) -> dict[str, bool]:
        """Checks which files from a list have been indexed by the user.

        This method sends a list of SHA-256 hashes to the API and returns a
        dictionary mapping each hash to a boolean indicating whether a file with
        that hash has been indexed by the authenticated user.

        Example:
            ```python
            from dorsal.client import DorsalClient

            # This client must be initialized with a valid API key
            client = DorsalClient()

            hashes_to_check = [
                "1a7a1c752a7a11eda328901b0e7371c4252a7a11eda328901b0e7371c425aa", # Exists
                "0c752a7a11eda328901b0e7371c4252a7a11eda328901b0e7371c425bb2a7a", # Does not exist
            ]

            try:
                results = client.check_files_indexed(hashes_to_check)
                for file_hash, exists in results.items():
                    print(f"Hash {file_hash[:10]}... exists: {exists}")
                # Expected output:
                # Hash 1a7a1c752a... exists: True
                # Hash 0c752a7a11... exists: False
            except Exception as e:
                print(f"An error occurred: {e}")
            ```

        Args:
            file_hashes (list[str]): A list of 64-character SHA-256 hash
                strings to check.
            api_key (str, optional): An API key for this request, overriding
                the client's default. Defaults to None.

        Returns:
            dict[str, bool]: A dictionary mapping each submitted hash to a
                boolean value (True if indexed, False otherwise).

        Raises:
            AuthError: If the API key is invalid or missing.
            DorsalClientError: If the input `file_hashes` list is invalid.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
            ApiDataValidationError: If the API response cannot be parsed.
        """
        validated_hashes = self._validate_sha256_hashes(file_hashes)

        target_url = self._make_check_files_indexed_url()
        request_body = {"hash_list": validated_hashes}
        logger.debug(
            "Attempting to check existence for %d hashes at: %s",
            len(validated_hashes),
            target_url,
        )

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError(
                "An unexpected error occurred during the HTTP request.",
                target_url,
                err,
            ) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to check file existence. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response)

        try:
            return response.json()
        except json.JSONDecodeError as err:
            snippet = response.text[:200]
            logger.error("Failed to decode JSON from successful API response for %s.", target_url)
            raise ApiDataValidationError(
                message="API returned an invalid JSON response despite success status.",
                request_url=target_url,
                response_text_snippet=snippet,
                original_exception=err,
            ) from err

    def _download_file_record(
        self,
        hash_string: str,
        private: bool = False,
        api_key: str | None = None,
        suppress_warning_log: bool = False,
    ) -> "FileRecordDateTime":
        """File download helper method."""
        from dorsal.file.validators.file_record import FileRecordDateTime

        try:
            file_hash, hash_function = self._parse_validate_file_hash(hash_string)
        except UnsupportedHashError as err:
            logger.warning("Unsupported hash type provided for '%s'. Details: %s", hash_string, err)
            raise DorsalClientError(
                message=f"The hash type for '{hash_string}' is not supported by the API.",
                original_exception=err,
            ) from err
        except ValueError as err:
            logger.warning("Invalid hash string format for '%s'. Details: %s", hash_string, err)
            raise DorsalClientError(
                message=f"The provided hash string '{hash_string}' is invalid or in an unrecognized format.",
                original_exception=err,
            ) from err

        api_file_key = self._make_file_key(file_hash=file_hash, hash_function=hash_function)
        if private:
            download_url = self._make_get_private_file_record_url(file_key=api_file_key)
            file_type = "private"
        else:
            download_url = self._make_get_public_file_record_url(file_key=api_file_key)
            file_type = "public"

        logger.debug("Attempting to download %s file record from: %s", file_type, download_url)

        try:
            if api_key is not None:
                headers = self._make_request_headers(api_key=api_key)
                response = self.session.get(
                    url=download_url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
            else:
                response = self.session.get(url=download_url, allow_redirects=False, timeout=self.timeout)
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out: %s", download_url)
            raise NetworkError(
                message="Request timed out while trying to reach API.",
                request_url=download_url,
                original_exception=err,
            ) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error for %s: %s", download_url, err)
            raise NetworkError(
                message="Could not establish connection to server.",
                request_url=download_url,
                original_exception=err,
            ) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", download_url, err)
            raise NetworkError(
                message="An unexpected error occurred during the HTTP request.",
                request_url=download_url,
                original_exception=err,
            ) from err

        if response.status_code != 200:
            self._handle_api_error(response, suppress_warning_log=suppress_warning_log)

        try:
            json_response = response.json()
        except json.JSONDecodeError as err:
            logger.error("Failed to decode JSON from API (status 200) for %s.", download_url)
            raise ApiDataValidationError(
                message="API returned an invalid JSON response.",
                request_url=download_url,
                response_text_snippet=response.text[:200],
                original_exception=err,
            ) from err

        try:
            file_record = FileRecordDateTime(**json_response)
            file_record.date_modified = file_record.date_modified.astimezone(tz=datetime.UTC)
            file_record.date_created = file_record.date_created.astimezone(tz=datetime.UTC)

        except PydanticValidationError as err:
            logger.error("API response validation failed for %s.", download_url)
            raise ApiDataValidationError(
                message="API response failed data validation.",
                request_url=download_url,
                validation_errors=err.errors(),
                response_text_snippet=json.dumps(json_response)[:200],
                original_exception=err,
            ) from err

        logger.debug(
            "Successfully downloaded and parsed %s file record from: %s",
            file_type,
            download_url,
        )
        return file_record

    def download_public_file_record(self, hash_string: str, api_key: str | None = None) -> "FileRecordDateTime":
        """Downloads metadata for a public file record by its hash.

        Retrieves the metadata for a single, publicly accessible file record
        from DorsalHub.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()
            public_hash = "known_public_sha256_hash"

            try:
                file_record = client.download_public_file_record(public_hash)
                print(f"Found file: {file_record.name}")
                print(f"Media type: {file_record.annotations.file_base.record.media_type}")
            except Exception as e:
                print(f"Could not download file record: {e}")
            ```

        Args:
            hash_string (str): A file hash string, optionally prefixed with an
                algorithm (e.g., "sha256:..."). Defaults to SHA-256 if no
                prefix is provided.

        Returns:
            FileRecord: A Pydantic model instance containing the file's metadata.

        Raises:
            NotFoundError: If no public file with the specified hash is found.
            UnsupportedHashError: If a valid but unsupported hash type (like TLSH)
                is used for lookup.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        return self._download_file_record(hash_string=hash_string, private=False, api_key=api_key)

    def download_private_file_record(
        self,
        hash_string: str,
        api_key: str | None = None,
        suppress_warning_log: bool = False,
    ) -> "FileRecordDateTime":
        """Downloads metadata for a private file record by its hash.

        Retrieves the metadata for a single, private file record from DorsalHub.
        This operation requires a valid API key with permissions to access the
        record.

        Example:
            ```python
            from dorsal.client import DorsalClient

            # This client must be initialized with a valid API key
            client = DorsalClient()
            private_hash = "known_private_sha256_hash"

            try:
                file_record = client.download_private_file_record(private_hash)
                print(f"Found private file: {file_record.name}")
            except Exception as e:
                print(f"Could not download file record: {e}")
            ```

        Args:
            hash_string (str): A file hash string, optionally prefixed with an
                algorithm (e.g., "sha256:..."). Defaults to SHA-256 if no
                prefix is provided.

        Returns:
            FileRecord: A Pydantic model instance containing the file's metadata.

        Raises:
            NotFoundError: If no private file with the specified hash is found
                for the authenticated user.
            AuthError: If the provided API key is invalid or missing.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        return self._download_file_record(
            hash_string=hash_string,
            private=True,
            api_key=api_key,
            suppress_warning_log=suppress_warning_log,
        )

    def download_file_record(
        self, hash_string: str, private: bool | None = None, api_key: str | None = None
    ) -> "FileRecordDateTime":
        """
        Downloads metadata for a file record, with agnostic search as the default.

        If `private` is None, it attempts to find a private record first. If that
        results in a 404 Not Found error, it seamlessly falls back to searching
        for a public record. Warnings for the initial 404 are suppressed to
        provide a clean experience for this expected fallback.

        Args:
            hash_string (str): The hash of the file to fetch.
            private (Optional[bool], optional): The visibility scope to search.
                Defaults to None (agnostic: private then public).
            api_key (str, optional): An API key to use for this specific request.

        Returns:
            FileRecordDateTime: A Pydantic model of the found file record.
        """
        from dorsal.common.exceptions import NotFoundError

        if private is not None:
            return self._download_file_record(hash_string=hash_string, private=private, api_key=api_key)

        try:
            logger.debug("Agnostic get: Attempting private record for hash '%s'...", hash_string)

            return self.download_private_file_record(
                hash_string=hash_string, api_key=api_key, suppress_warning_log=True
            )

        except NotFoundError:
            logger.debug("Agnostic get: Private record not found. Falling back to public.")
            return self.download_public_file_record(hash_string=hash_string, api_key=api_key)

    def delete_file(
        self,
        *,
        file_hash: str,
        record: DeletionScope = "all",
        tags: DeletionScope = "all",
        annotations: DeletionScope = "all",
        api_key: str | None = None,
    ) -> "FileDeleteResponse":
        """
        Deletes a file record and/or its associated data with granular control.

        This method sends a DELETE request to the unified file endpoint. The
        behavior of the deletion is controlled by the `record`, `tags`, and
        `annotations` parameters, which are sent in the request body.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()
            file_hash = "123..." # A valid SHA-256 hash

            # Use case 1: Full clean (default behavior)
            # Deletes all records, tags, and annotations for the user.
            client.delete_file(file_hash=file_hash)

            # Use case 2: Quota management
            # Deletes only the private file record, keeping all metadata.
            client.delete_file(file_hash=file_hash, record="private", tags="none", annotations="none")

            # Use case 3: Granular public cleanup
            # Deletes the public record and the user's public tags.
            client.delete_file(file_hash=file_hash, record="public", tags="public", annotations="none")
            ```

        Args:
            file_hash (str): The 64-character SHA-256 hash of the file.
            record (Scope): Specifies which core file record(s) to delete.
                Defaults to "all".
            tags (Scope): Specifies which of the user's tags to delete.
                Defaults to "all".
            annotations (Scope): Specifies which of the user's annotations to
                delete. Defaults to "all".
            api_key (str | None): Optional API key to override the client's default.

        Returns:
            FileDeleteResponse: A detailed report of the deletion operation.

        Raises:
            DorsalClientError: For client-side validation issues.
            NotFoundError: If no file record matching the deletion criteria is found.
            AuthError: If authentication fails.
            ForbiddenError: If the user does not have permission to delete the
                specified public record.
            ConflictError: If the server could not complete the deletion due to
                a conflict (e.g., the record is frozen).
            APIError: For any other unhandled API error.
        """
        from dorsal.client.validators import FileDeleteResponse

        logger.debug(
            "Client: delete_file called for hash '%s' with options: record=%s, tags=%s, annotations=%s.",
            file_hash,
            record,
            tags,
            annotations,
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        target_url = f"{self.base_url}/{self._files_endpoint}/{validated_hash}"

        request_body = {
            "record": record,
            "tags": tags,
            "annotations": annotations,
        }

        logger.debug("Attempting to delete file record at: %s with body: %s", target_url, request_body)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.delete(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.exception("HTTP DELETE request failed for %s", target_url)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to delete file %s. API responded with status %s.",
                validated_hash,
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            return FileDeleteResponse(**json_response)
        except json.JSONDecodeError as err:
            logger.exception("Failed to decode JSON from successful file deletion.")
            raise ApiDataValidationError(
                message="API returned an invalid JSON response despite success status.",
                request_url=target_url,
                response_text_snippet=response.text[:200],
                original_exception=err,
            ) from err
        except PydanticValidationError as err:
            logger.exception("File deletion response failed Pydantic validation.")
            raise ApiDataValidationError(
                message="API response on success failed data validation against FileDeleteResponse.",
                request_url=target_url,
                validation_errors=err.errors(),
                original_exception=err,
            ) from err

    def get_dataset(self, dataset_id: str, api_key: str | None = None) -> Dataset:
        """Retrieves a specific dataset by its ID.

        Fetches the full definition of a dataset, including its schema, name,
        description, and other metadata.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()

            try:
                dataset = client.get_dataset("dorsal/iso-language-codes")
                print(f"Dataset: {dataset.name}")
                print(f"Description: {dataset.description}")
                # The schema is available as a dictionary
                print(f"Schema keys: {list(dataset.dataset_schema.keys())}")
            except Exception as e:
                print(f"Error getting dataset: {e}")
            ```

        Args:
            dataset_id (str): The unique identifier of the dataset, in the
                format "namespace/dataset-name".
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            Dataset: A Pydantic model instance representing the full dataset.

        Raises:
            NotFoundError: If no dataset with the specified ID is found.
            AuthError: If authentication fails (required for private datasets).
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        if not dataset_id or not isinstance(dataset_id, str):
            raise ValueError("dataset_id must be a non-empty string.")

        dataset_id = dataset_id.lower()
        if not is_valid_dataset_id_or_schema_id(value=dataset_id):
            logger.error("Invalid dataset_id format for get_dataset: '%s'", dataset_id)
            raise ValueError(f"Invalid dataset_id format: {dataset_id}")

        dataset_namespace, dataset_name = self._split_dataset_or_schema_id(value=dataset_id)
        target_url = self._make_get_dataset_url(namespace=dataset_namespace, name=dataset_name)
        logger.debug("Attempting to retrieve dataset from: %s", target_url)

        try:
            if api_key is not None:
                headers = self._make_request_headers(api_key=api_key)
                response = self.session.get(
                    url=target_url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
            else:
                response = self.session.get(url=target_url, allow_redirects=False, timeout=self.timeout)
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out: %s", target_url)
            raise NetworkError("Request timed out while trying to reach API.", target_url, err) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error for %s: %s", target_url, err)
            raise NetworkError("Could not establish connection to server.", target_url, err) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code == 200:
            try:
                json_response = response.json()
                dataset_record = Dataset(**json_response)
                logger.debug("Successfully retrieved dataset: %s", dataset_id)
                return dataset_record
            except json.JSONDecodeError as err:
                snippet = response.text[:200]
                logger.error(
                    "Failed to decode successful GET dataset response (status 200) for %s.",
                    target_url,
                )
                raise ApiDataValidationError(
                    message="API returned an invalid response.",
                    request_url=target_url,
                    response_text_snippet=snippet,
                    original_exception=err,
                ) from err
            except PydanticValidationError as err:
                logger.error(
                    "Successful GET dataset response (status 200) for %s failed Pydantic validation. Errors: %s",
                    target_url,
                    err.errors(),
                )
                raise ApiDataValidationError(
                    message="API response on GET dataset success failed data validation.",
                    request_url=target_url,
                    validation_errors=err.errors(),
                    response_text_snippet=(
                        json.dumps(json_response)[:200] if "json_response" in locals() else response.text[:200]
                    ),
                    original_exception=err,
                ) from err
        else:
            logger.warning(
                "Failed to retrieve dataset %s. API responded with status %s.",
                dataset_id,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

    def get_dataset_type(self, dataset_id: str, api_key: str | None = None) -> Literal["File", "Reference"]:
        """Retrieves the type of a specific dataset by its ID.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()
            dataset_id = "dorsal/arxiv-cs-papers" # This is a 'File' dataset

            try:
                dataset_type = client.get_dataset_type(dataset_id)
                if dataset_type == "File":
                    print(f"'{dataset_id}' is a collection of files.")
                else:
                    print(f"'{dataset_id}' is a collection of reference data.")
            except Exception as e:
                print(f"Error getting dataset type: {e}")
            ```

        Args:
            dataset_id (str): The unique identifier of the dataset, in the
                format "namespace/dataset-name".
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            Literal["File", "Reference"]: The type of the dataset.

        Raises:
            NotFoundError: If no dataset with the specified ID is found.
            ApiDataValidationError: If the API returns an unexpected value for
                the dataset type.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        if not dataset_id or not isinstance(dataset_id, str):
            raise ValueError("dataset_id must be a non-empty string.")

        dataset_id = dataset_id.lower()
        if not is_valid_dataset_id_or_schema_id(value=dataset_id):
            logger.error("Invalid dataset_id format for get_dataset_type: '%s'", dataset_id)
            raise ValueError(f"Invalid dataset_id format: {dataset_id}")

        dataset_namespace, dataset_name = self._split_dataset_or_schema_id(value=dataset_id)
        target_url = self._make_get_dataset_type_url(namespace=dataset_namespace, name=dataset_name)
        logger.debug("Attempting to retrieve dataset type from: %s", target_url)

        try:
            if api_key is not None:
                headers = self._make_request_headers(api_key=api_key)
                response = self.session.get(
                    url=target_url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
            else:
                response = self.session.get(url=target_url, allow_redirects=False, timeout=self.timeout)
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out: %s", target_url)
            raise NetworkError("Request timed out while trying to reach API.", target_url, err) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error for %s: %s", target_url, err)
            raise NetworkError("Could not establish connection to server.", target_url, err) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code == 200:
            if response.text not in VALID_DATASET_TYPES:
                raise ApiDataValidationError(
                    message=f"Dataset type not recognised: {response.text[:200]}, {repr(response.text)}, valid: {VALID_DATASET_TYPES}",
                    request_url=target_url,
                    validation_errors=None,
                    response_text_snippet=(response.text[:200]),
                    original_exception=None,
                )
            return response.text
        else:
            logger.warning(
                "Failed to retrieve dataset %s. API responded with status %s.",
                dataset_id,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

    def get_dataset_schema(self, dataset_id: str, api_key: str | None = None) -> dict[str, Any]:
        """Fetches the JSON schema for a given dataset.

        This method retrieves just the schema of a dataset, which can be more
        efficient than fetching the entire dataset definition if the schema is
        all that is required.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()
            dataset_id = "my-org/application-users"

            try:
                schema = client.get_dataset_schema(dataset_id)
                print(f"Schema for '{dataset_id}':")
                for field, properties in schema.get("properties", {}).items():
                    print(f"- {field} (type: {properties.get('type')})")
            except Exception as e:
                print(f"Error getting dataset schema: {e}")
            ```

        Args:
            dataset_id (str): The unique identifier of the dataset, in the
                format "namespace/dataset-name" (e.g., "open/classification").
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            dict[str, Any]: A dictionary representing the JSON schema of the dataset.

        Raises:
            NotFoundError: If no dataset with the specified ID is found.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        logger.debug(
            "get_dataset_schema called for dataset_id: '%s'. API key provided: %s",
            dataset_id,
            "Yes" if api_key else "No",
        )

        if not dataset_id or not isinstance(dataset_id, str):
            raise ValueError("dataset_id must be a non-empty string.")

        dataset_id = dataset_id.lower()
        if not is_valid_dataset_id_or_schema_id(value=dataset_id):
            logger.error("Invalid dataset_id format for get_dataset_schema: '%s'", dataset_id)
            raise ValueError(f"Invalid dataset_id format: {dataset_id}")

        dataset_namespace, dataset_name = self._split_dataset_or_schema_id(value=dataset_id)
        target_url = self._make_get_dataset_schema_url(namespace=dataset_namespace, name=dataset_name)
        logger.debug("Attempting to retrieve dataset schema from: %s", target_url)

        try:
            if api_key is not None:
                headers = self._make_request_headers(api_key=api_key)
                response = self.session.get(
                    url=target_url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
            else:
                response = self.session.get(url=target_url, allow_redirects=False, timeout=self.timeout)
            self.last_response = response
        except requests.exceptions.Timeout as err:
            logger.error("Request timed out: %s", target_url)
            raise NetworkError("Request timed out while trying to reach API.", target_url, err) from err
        except requests.exceptions.ConnectionError as err:
            logger.error("Connection error for %s: %s", target_url, err)
            raise NetworkError("Could not establish connection to server.", target_url, err) from err
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code == 200:
            try:
                json_response = response.json()
                logger.debug("Successfully retrieved schema for: %s", dataset_id)
                return json_response
            except json.JSONDecodeError as err:
                snippet = response.text[:200]
                logger.error(
                    "Failed to decode successful GET schema response (status 200) for %s.",
                    target_url,
                )
                raise ApiDataValidationError(
                    message="API returned an invalid response.",
                    request_url=target_url,
                    response_text_snippet=snippet,
                    original_exception=err,
                ) from err
        else:
            logger.warning(
                "Failed to retrieve schema for %s. API responded with status %s.",
                dataset_id,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(response.status_code, "Unhandled error", target_url, response.text)  # pragma: no cover

    def make_schema_validator(self, dataset_id: str, api_key: str | None = None) -> JsonSchemaValidator:
        """Fetches a dataset's schema and returns a callable validator function.

        This powerful utility method fetches a dataset's schema and compiles it
        into a validator function on the fly. This allows for client-side
        validation of records before they are sent to the API, preventing
        unnecessary API calls with invalid data.

        Example:
            ```python
            from dorsal.client import DorsalClient
            from jsonschema.exceptions import ValidationError

            client = DorsalClient()
            dataset_id = "my-org/application-users"

            try:
                validator = client.make_schema_validator(dataset_id)

                # This record is valid and will not raise an exception
                valid_record = {"user_id": 101, "username": "alice"}
                validator(valid_record)
                print("Valid record passed validation.")

                # This record is missing a required field and will raise an error
                invalid_record = {"user_id": 102}
                validator(invalid_record)

            except ValidationError as e:
                print(f"Invalid record failed validation: {e.message}")
            except Exception as e:
                print(f"An error occurred: {e}")
            ```

        Args:
            dataset_id (str): The identifier for the dataset whose schema will be
                used to create the validator.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default. Defaults to None.

        Returns:
            JsonSchemaValidator: A callable instance that validates a dictionary
                record against the fetched schema.

        Raises:
            ApiDataValidationError: If the fetched schema is invalid or unsuitable
                for creating a validator.
            NotFoundError: If no dataset with the specified ID is found.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        logger.debug(
            "make_schema_validator called for dataset_id: '%s'. API key provided: %s",
            dataset_id,
            "Yes" if api_key else "No",
        )
        try:
            schema_dict: dict[str, Any] = self.get_dataset_schema(dataset_id=dataset_id, api_key=api_key)
        except Exception as err:
            logger.warning(
                "make_schema_validator failed for dataset_id '%s' because schema retrieval via self.get_schget_dataset_schemaema failed: %s - %s",
                dataset_id,
                type(err).__name__,
                err,
            )
            raise

        try:
            validator = get_json_schema_validator(schema=schema_dict)
            logger.debug(
                "Successfully created JsonSchemaValidator for dataset_id: '%s'",
                dataset_id,
            )
            return validator
        except ValueError as err:
            logger.exception(
                "Invalid schema structure passed to get_json_schema_validator for dataset_id '%s'.",
                dataset_id,
            )
            raise ApiDataValidationError(
                message=f"The schema fetched for dataset '{dataset_id}' is unsuitable for validator creation: {err!s}",
                original_exception=err,
                request_url=(
                    self.last_response.url
                    if self.last_response and self.last_response.url.endswith(dataset_id.strip("/"))
                    else None
                ),
            ) from err
        except SchemaFormatError as err:
            logger.exception(
                "The schema for dataset '%s' is invalid and cannot be used by get_json_schema_validator.",
                dataset_id,
            )
            error_message = str(err)

            validation_detail = (
                [{"msg": err.schema_error_detail, "loc": ("schema",)}]
                if hasattr(err, "schema_error_detail") and err.schema_error_detail
                else [{"msg": error_message}]
            )
            raise ApiDataValidationError(
                message=f"The schema for dataset '{dataset_id}' is invalid: {error_message}",
                original_exception=err,
                validation_errors=validation_detail,
                request_url=(
                    self.last_response.url
                    if self.last_response and self.last_response.url.endswith(dataset_id.strip("/"))
                    else None
                ),
            ) from err
        except DorsalError as err:
            logger.exception(
                "An unexpected occurred in get_json_schema_validator for dataset_id '%s'.",
                dataset_id,
            )
            raise DorsalClientError(
                message=f"Could not create schema validator for dataset '{dataset_id}' due to an internal error: {err!s}",
                original_exception=err,
            ) from err
        except Exception as err:
            logger.exception(
                "Unexpected error in get_json_schema_validator for dataset_id '%s'.",
                dataset_id,
            )
            raise DorsalClientError(
                message=f"An unexpected error occurred while creating schema validator for dataset '{dataset_id}': {err!s}"
            ) from err

    def verify_credentials(self) -> dict:
        """
        Verifies the API key by making a lightweight, authenticated request.

        Returns:
            A dictionary containing user information if successful.

        Raises:
            AuthError: If the API key is invalid or missing.
            NetworkError: If there's a connectivity issue.
            APIError: For other unexpected API errors.
        """
        verify_url = urljoin(self.base_url, "/v1/users/me")
        logger.debug("Verifying credentials via: %s", verify_url)

        try:
            response = self.session.get(url=verify_url, allow_redirects=False, timeout=self.timeout)
            self.last_response = response

            if response.status_code != 200:
                self._handle_api_error(response)

            return response.json()

        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed during credential verification: %s", err)
            raise NetworkError(
                "An unexpected network error occurred while verifying credentials.",
                request_url=verify_url,
                original_exception=err,
            ) from err

    def create_collection(
        self,
        name: str,
        is_private: bool,
        source: dict,
        description: str | None = None,
        api_key: str | None = None,
    ) -> "FileCollection":
        """
        Creates a new, empty file collection on DorsalHub.

        This is the low-level method for creating a file collection. It's
        typically called by `LocalFileCollection.create_remote_collection()`.

        Args:
            name (str): The name for the new collection.
            is_private (bool): The visibility of the new collection.
            source (dict): A dictionary describing the source of the collection.
            description (str, optional): An optional description. Defaults to None.
            api_key (str, optional): An API key for this request. Defaults to None.

        Returns:
            FileCollection: A Pydantic model of the newly created collection.

        Raises:
            ConflictError: If a collection with the same name already exists.
            AuthError: If authentication fails.
            NetworkError: If a network or connectivity issue occurs.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.file.validators.collection import FileCollection
        from dorsal.client.validators import CollectionCreateRequest

        target_url = self._make_collections_url()
        logger.debug("Attempting to create collection '%s' at: %s", name, target_url)

        try:
            request_model = CollectionCreateRequest(
                name=name,
                description=description,
                is_private=is_private,
                source=source,
            )
            request_body = request_model.model_dump(mode="json")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for collection creation: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 201:
            logger.warning(
                "Failed to create collection. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            return FileCollection(**json_response)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            logger.error(
                "Failed to parse successful create_collection response from %s.",
                target_url,
            )
            raise ApiDataValidationError(
                message="API response on collection creation success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    @overload
    def get_collection(
        self,
        collection_id: str,
        hydrate: Literal[True],
        page: int = 1,
        per_page: int = 100,
        api_key: str | None = None,
    ) -> "HydratedSingleCollectionResponse": ...

    @overload
    def get_collection(
        self,
        collection_id: str,
        hydrate: Literal[False] = False,
        page: int = 1,
        per_page: int = 100,
        api_key: str | None = None,
    ) -> "SingleCollectionResponse": ...

    def get_collection(
        self,
        collection_id: str,
        hydrate: bool = False,
        page: int = 1,
        per_page: int = 100,
        api_key: str | None = None,
    ) -> "SingleCollectionResponse | HydratedSingleCollectionResponse":
        """
        Retrieves a specific collection and its file contents from DorsalHub.

        Args:
            collection_id (str): The unique ID of the collection to fetch.
            hydrate (bool): If True, returns fully detailed file records.
                Defaults to False.
            page (int): The page number for file contents. Defaults to 1.
            per_page (int): The number of file records per page. Defaults to 100.
            api_key (str | None): An API key for this request. Defaults to None.

        Returns:
            SingleCollectionResponse | HydratedSingleCollectionResponse: An object
            containing the collection metadata and a paginated list of its files.
            The specific type depends on the `hydrate` flag.

        Raises:
            NotFoundError: If the collection is not found.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.file.validators.collection import SingleCollectionResponse
        from dorsal.client.validators import HydratedSingleCollectionResponse

        if not collection_id or not isinstance(collection_id, str):
            raise DorsalClientError("collection_id must be a non-empty string.")

        target_url = self._make_collection_url(collection_id)
        params = {"page": page, "per_page": per_page, "hydrate": hydrate}
        logger.debug("Attempting to get collection '%s' from: %s", collection_id, target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.get(
                url=target_url,
                params=params,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to get collection. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            if hydrate:
                return HydratedSingleCollectionResponse(**json_response)
            else:
                return SingleCollectionResponse(**json_response)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            logger.error(
                "Failed to parse successful get_collection response from %s.",
                target_url,
            )
            raise ApiDataValidationError(
                message="API response on get_collection success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def add_files_to_collection(
        self, collection_id: str, hashes: list[str], api_key: str | None = None
    ) -> "AddFilesResponse":
        """
        Adds a list of files to a specified collection using their SHA-256 hashes.

        The server validates that each file exists and is accessible to the user
        before adding it. This operation is idempotent.

        Args:
            collection_id (str): The unique ID of the collection.
            hashes (list[str]): A list of SHA-256 hash strings for the files to add.
            api_key (str | None): An API key for this request. Defaults to None.

        Returns:
            AddFilesResponse: A summary of the operation from the API.

        Raises:
            NotFoundError: If the collection is not found.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.client.validators import AddFilesRequest, AddFilesResponse

        if not collection_id or not isinstance(collection_id, str):
            raise DorsalClientError("collection_id must be a non-empty string.")

        validated_hashes = self._validate_sha256_hashes(hashes)
        target_url = self._make_collection_files_url(collection_id)
        logger.debug(
            "Attempting to add %d files to collection '%s' at: %s",
            len(hashes),
            collection_id,
            target_url,
        )

        try:
            request_model = AddFilesRequest(hashes=validated_hashes)
            request_body = request_model.model_dump(mode="json")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for add_files_to_collection: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to add files to collection. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            return AddFilesResponse(**json_response)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            logger.error(
                "Failed to parse successful add_files_to_collection response from %s.",
                target_url,
            )
            raise ApiDataValidationError(
                message="API response on add_files_to_collection success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def remove_files_from_collection(
        self, collection_id: str, hashes: list[str], api_key: str | None = None
    ) -> "RemoveFilesResponse":
        """
        Removes a list of files from a specified collection using their SHA-256 hashes.

        The server validates that the user owns the collection before removing the
        files. This operation is idempotent.

        Args:
            collection_id (str): The unique ID of the collection.
            hashes (list[str]): A list of SHA-256 hash strings for the files to remove.
            api_key (str | None): An API key for this request. Defaults to None.

        Returns:
            RemoveFilesResponse: A summary of the operation from the API.

        Raises:
            NotFoundError: If the collection is not found.
            ForbiddenError: If the user does not have permission to modify the collection.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
            DorsalClientError: For client-side validation errors, like providing too many hashes.
        """
        from dorsal.client.validators import RemoveFilesRequest, RemoveFilesResponse

        if not collection_id or not isinstance(collection_id, str):
            raise DorsalClientError("collection_id must be a non-empty string.")

        validated_hashes = self._validate_sha256_hashes(hashes)
        target_url = self._make_collection_files_url(collection_id)
        logger.debug(
            "Attempting to remove %d files from collection '%s' at: %s",
            len(hashes),
            collection_id,
            target_url,
        )

        try:
            request_model = RemoveFilesRequest(hashes=validated_hashes)
            request_body = request_model.model_dump(mode="json")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for remove_files_from_collection: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.delete(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to remove files from collection. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            return RemoveFilesResponse(**json_response)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            logger.error(
                "Failed to parse successful remove_files_from_collection response from %s.",
                target_url,
            )
            raise ApiDataValidationError(
                message="API response on remove_files_from_collection success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def list_collections(self, page: int = 1, per_page: int = 50, api_key: str | None = None) -> "CollectionsResponse":
        """
        Retrieves a paginated list of the authenticated user's collections.

        Args:
            page (int): The page number, 1-indexed. Defaults to 1.
            per_page (int): Number of records per page. Defaults to 50.
            api_key (str | None): An API key for this request. Defaults to None.

        Returns:
            PaginatedCollectionsResponse: An object containing the list of
            collections and pagination details.

        Raises:
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.client.validators import CollectionsResponse

        target_url = self._make_collections_url()
        params = {"page": page, "per_page": per_page}
        logger.debug(
            "Attempting to list collections from: %s with params: %s",
            target_url,
            params,
        )

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.get(
                url=target_url,
                params=params,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.error("HTTP request failed for %s: %s", target_url, err)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            logger.warning(
                "Failed to list collections. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response=response)

        try:
            json_response = response.json()
            return CollectionsResponse(**json_response)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            logger.error(
                "Failed to parse successful list_collections response from %s.",
                target_url,
            )
            raise ApiDataValidationError(
                message="API response on list_collections success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def update_collection(
        self,
        *,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
        api_key: str | None = None,
    ) -> "FileCollection":
        """
        Updates the properties (name, description) of a collection.

        Args:
            collection_id (str): The ID of the collection to update.
            name (str, optional): The new name for the collection.
            description (str, optional): The new description.
            api_key (str, optional): An API key for this request.

        Returns:
            FileCollection: A model of the collection with its updated properties.
        """
        from dorsal.file.validators.collection import FileCollection
        from dorsal.client.validators import CollectionUpdateRequest

        target_url = self._make_collection_url(collection_id)
        logger.debug("Attempting to update collection '%s' at: %s", collection_id, target_url)

        try:
            request_model = CollectionUpdateRequest(name=name, description=description)
            request_body = request_model.model_dump(mode="json", exclude_none=True)
            if not request_body:
                raise DorsalClientError("Update failed: at least one field (name or description) must be provided.")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for collection update: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.patch(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            self._handle_api_error(response)

        try:
            return FileCollection(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on collection update success failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def delete_collections(self, *, collection_ids: list[str], api_key: str | None = None) -> None:
        """
        Deletes one or more collections.

        Args:
            collection_ids (list[str]): A list of collection IDs to delete.
            api_key (str | None): An API key for this request.

        Returns:
            None: A 204 No Content response indicates success.
        """
        from dorsal.client.validators import CollectionsDeleteRequest

        if not collection_ids:
            raise DorsalClientError("collection_ids list cannot be empty.")

        target_url = self._make_collections_url()
        logger.debug(
            "Attempting to delete %d collections at: %s",
            len(collection_ids),
            target_url,
        )

        try:
            request_model = CollectionsDeleteRequest(collection_ids=collection_ids)
            request_body = request_model.model_dump(mode="json")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for collections delete: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.delete(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 204:
            self._handle_api_error(response)

        return None

    def make_collection_public(self, collection_id: str, api_key: str | None = None) -> "CollectionWebLocationResponse":
        """
        Converts a private collection to public after performing a pre-flight check.

        Args:
            collection_id (str): The ID of the collection to make public.
            api_key (str, optional): An API key for this request.

        Returns:
            CollectionWebLocationResponse: An object containing the new public web URL.

        Raises:
            ConflictError: If the collection is already public.
        """
        from dorsal.client.validators import CollectionWebLocationResponse

        logger.debug("Attempting to make collection '%s' public...", collection_id)

        current_collection = self.get_collection(collection_id, api_key=api_key)
        if not current_collection.collection.is_private:
            raise ConflictError(f"Collection '{collection_id}' is already public.")

        target_url = self._make_collection_action_url(collection_id, "make-public")
        logger.debug("Pre-flight check passed. Posting to: %s", target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 201:
            self._handle_api_error(response)

        try:
            return CollectionWebLocationResponse(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on make_collection_public failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def make_collection_private(
        self, collection_id: str, api_key: str | None = None
    ) -> "CollectionWebLocationResponse":
        """
        Converts a public collection to private after performing a pre-flight check.

        Args:
            collection_id (str): The ID of the collection to make private.
            api_key (str, optional): An API key for this request.

        Returns:
            CollectionWebLocationResponse: An object containing the new private web URL.

        Raises:
            ConflictError: If the collection is already private.
        """
        from dorsal.client.validators import CollectionWebLocationResponse

        logger.debug("Attempting to make collection '%s' private...", collection_id)

        current_collection = self.get_collection(collection_id, api_key=api_key)
        if current_collection.collection.is_private:
            raise ConflictError(f"Collection '{collection_id}' is already private.")

        target_url = self._make_collection_action_url(collection_id, "make-private")
        logger.debug("Pre-flight check passed. Posting to: %s", target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 201:
            self._handle_api_error(response)

        try:
            return CollectionWebLocationResponse(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on make_collection_private failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def start_collection_export(self, collection_id: str, api_key: str | None = None) -> "ExportJobStatus":
        """
        Kicks off a server-side export job for a given collection.

        Args:
            collection_id (str): The unique ID of the collection to export.
            api_key (str, optional): An API key for this request. Defaults to None.

        Returns:
            ExportJobStatus: An object containing the initial job status and ID.

        Raises:
            NotFoundError: If the collection ID is not found.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.client.validators import ExportJobRequest, ExportJobStatus

        if not collection_id:
            raise DorsalClientError("collection_id cannot be empty.")

        target_url = self._make_start_collection_export_url(collection_id)
        logger.debug(
            "Requesting to start export for collection '%s' at: %s",
            collection_id,
            target_url,
        )

        request_body = ExportJobRequest().model_dump()

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 202:
            self._handle_api_error(response)

        try:
            return ExportJobStatus(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on start_collection_export failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def get_export_job_status(self, job_id: str, api_key: str | None = None) -> "ExportJobStatus":
        """
        Polls the server for the status of a previously started export job.

        Args:
            job_id (str): The unique ID of the export job.
            api_key (str, optional): An API key for this request. Defaults to None.

        Returns:
            ExportJobStatus: An object detailing the current status of the job.

        Raises:
            NotFoundError: If the job ID is not found.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.client.validators import ExportJobStatus

        if not job_id:
            raise DorsalClientError("job_id cannot be empty.")

        target_url = self._make_get_export_job_status_url(job_id)
        logger.debug("Polling for job status at: %s", target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.get(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            self._handle_api_error(response)

        try:
            return ExportJobStatus(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on get_export_job_status failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def _download_export_file(self, download_url: str, output_path: str) -> None:
        logger.info("Downloading file from %s", download_url)
        try:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            with requests.get(url=download_url, stream=True) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            logger.info("File successfully saved to: %s", output_path)
        except requests.exceptions.RequestException as err:
            logger.exception("Download failed from URL: %s", download_url)
            raise NetworkError(f"Download failed from {download_url}", download_url, err) from err

    def download_completed_export(self, job_status: "ExportJobStatus", output_path: str) -> None:
        """Downloads the result of a completed export job."""
        if job_status.status != "COMPLETED":
            raise DorsalClientError(f"Job is not complete. Status: {job_status.status}")

        if not job_status.download_url:
            raise DorsalClientError("Export job completed but returned no download URL.")

        self._download_export_file(job_status.download_url, output_path)

    def export_collection(
        self,
        collection_id: str,
        output_path: str,
        poll_interval: int = 2,
        timeout: int | None = 3600,
        api_key: str | None = None,
        console: "Console | None" = None,
        palette: dict | None = None,
    ) -> None:
        """
        Starts a collection export, waits for completion, and downloads the result.

        Example:
            ```python
            from dorsal.client import DorsalClient

            client = DorsalClient()
            collection_id = "your_collection_id_here"
            output_file = "./my_export.json.gz"

            try:
                print(f"Starting export for {collection_id}...")
                client.export_collection(collection_id, output_file)
                print(f"✅ Export successful. File saved to {output_file}")
            except Exception as e:
                print(f"❌ Export failed: {e}")
            ```

        Args:
            collection_id (str): The unique ID of the collection to export.
            output_path (str): The local file path to save the exported data.
            poll_interval (int): The number of seconds to wait between status
                checks. Defaults to 5.
            api_key (str | None): An API key for this request. Defaults to None.

        Raises:
            DorsalError: If the job fails or an API error occurs.
        """
        start_status = self.start_collection_export(collection_id, api_key=api_key)
        job_id = start_status.job_id
        logger.info("Successfully started export job: %s", job_id)

        start_time = time.time()

        if is_jupyter_environment():
            with tqdm(total=100, desc="Exporting collection") as pbar:
                while True:
                    if timeout is not None and time.time() - start_time > timeout:
                        raise DorsalClientError(f"Export job did not complete within the {timeout} second timeout.")

                    job_status = self.get_export_job_status(job_id, api_key=api_key)
                    pbar.n = int(job_status.progress)
                    pbar.refresh()

                    if job_status.status == "COMPLETED":
                        pbar.n = 100
                        pbar.refresh()
                        self.download_completed_export(job_status, output_path)
                        return None
                    elif job_status.status == "FAILED":
                        raise APIError(status_code=500, detail=f"Export failed: {job_status.message}")
                    time.sleep(poll_interval)

        if console:
            from rich.live import Live
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE
            from rich.progress import (
                Progress,
                BarColumn,
                TaskProgressColumn,
                TextColumn,
                TimeElapsedColumn,
            )

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_bar = Progress(
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette.get("progress_description", "default"),
                ),
                BarColumn(bar_width=None, style=active_palette.get("progress_bar", "default")),
                TaskProgressColumn(style=active_palette.get("progress_percentage", "default")),
                TextColumn("•", style="dim"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            )
            task_id = progress_bar.add_task("Exporting...", total=100)

            with Live(progress_bar, console=console, refresh_per_second=4) as live:
                while True:
                    if timeout is not None and time.time() - start_time > timeout:
                        raise DorsalClientError(f"Export job did not complete within the {timeout} second timeout.")

                    status = self.get_export_job_status(job_id, api_key=api_key)
                    progress_bar.update(task_id, completed=status.progress)

                    if status.status == "COMPLETED":
                        progress_bar.update(
                            task_id,
                            completed=100,
                            description="[green]Downloading...[/]",
                        )
                        self.download_completed_export(status, output_path)
                        break
                    elif status.status == "FAILED":
                        live.stop()
                        raise APIError(status_code=500, detail=f"Export failed: {status.message}")

                    time.sleep(poll_interval)
            return

        while True:
            if timeout is not None and time.time() - start_time > timeout:
                raise DorsalClientError(f"Export job did not complete within the {timeout} second timeout.")

            status = self.get_export_job_status(job_id, api_key=api_key)

            if status.status == "COMPLETED":
                logger.info("Job %s completed successfully", job_id)
                self.download_completed_export(status, output_path)
                return
            elif status.status == "FAILED":
                raise APIError(status_code=500, detail=f"Export failed: {status.message}")
            else:
                logger.debug(
                    "Polling job %s: Status=%s, Progress=%.2f%%",
                    job_id,
                    status.status,
                    status.progress,
                )
                time.sleep(poll_interval)

    def sync_collection_by_hash(
        self,
        collection_id: str,
        hashes: list[str],
        poll_interval: int = 5,
        timeout: int | None = 300,
        api_key: str | None = None,
    ) -> "CollectionSyncResponse":
        """
        Synchronizes a collection to exactly match a provided list of hashes.

        The server calculates the difference between the current and target states
        and performs the necessary additions and removals atomically.

        Args:
            collection_id (str): The unique ID of the collection to synchronize.
            hashes (list[str]): The complete list of SHA-256 hashes the collection
                should contain after the operation.
            api_key (str | None): An API key for this request. Defaults to None.

        Returns:
            CollectionSyncResponse: A summary of the additions, removals, and
            unchanged files.

        Raises:
            ForbiddenError: If attempting to add a non-public file to a public
                collection.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other 4xx or 5xx API error.
        """
        from dorsal.client.validators import (
            CollectionSyncRequest,
            CollectionSyncResponse,
            CollectionSyncJob,
            CollectionSyncJobStatus,
        )

        if not collection_id or not isinstance(collection_id, str):
            raise DorsalClientError("collection_id must be a non-empty string.")

        validated_hashes = self._validate_sha256_hashes(hashes)
        start_url = f"{self._make_collection_url(collection_id)}/sync"
        logger.debug(
            "Requesting to start sync for collection '%s' at: %s",
            collection_id,
            start_url,
        )

        try:
            request_model = CollectionSyncRequest(hashes=validated_hashes)
            request_body = request_model.model_dump(mode="json")
        except PydanticValidationError as err:
            raise DorsalClientError(f"Invalid data for collection sync: {err}") from err

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=start_url,
                json=request_body,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError(
                "An unexpected error occurred while starting the sync job.",
                start_url,
                err,
            ) from err

        if response.status_code != 202:
            logger.warning(
                "Failed to start sync job. API responded with status %s.",
                response.status_code,
            )
            self._handle_api_error(response)

        try:
            job_info = CollectionSyncJob(**response.json())
            job_id = job_info.job_id
            logger.info("Successfully started sync job: %s", job_id)
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on starting sync job failed data validation.",
                request_url=start_url,
                original_exception=err,
            ) from err

        status_url = self._make_collection_sync_job_url(job_id)
        start_time = time.time()

        while True:
            if timeout is not None and time.time() - start_time > timeout:
                raise DorsalClientError(f"Sync job did not complete within the {timeout} second timeout.")

            logger.debug("Polling job status at: %s", status_url)
            try:
                headers = self._make_request_headers(api_key=api_key)
                status_response = self.session.get(
                    url=status_url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers=headers,
                )
                self.last_response = status_response
            except requests.exceptions.RequestException as err:
                raise NetworkError(f"Polling request failed for job {job_id}.", status_url, err) from err

            if status_response.status_code != 200:
                self._handle_api_error(status_response)

            try:
                status_data = CollectionSyncJobStatus(**status_response.json())
            except (json.JSONDecodeError, PydanticValidationError) as err:
                raise ApiDataValidationError(
                    message=f"Polling response for job {job_id} failed data validation.",
                    request_url=status_url,
                    original_exception=err,
                ) from err

            if status_data.status == "SUCCESS":
                logger.info("Job %s completed successfully.", job_id)
                if status_data.result:
                    return status_data.result
                else:
                    raise DorsalClientError("Sync job completed successfully but returned no result data.")
            elif status_data.status == "FAILURE":
                error_message = status_data.error or "Sync job failed with an unspecified error."
                logger.error("Job %s failed: %s", job_id, error_message)
                raise DorsalClientError(f"Sync failed: {error_message}")
            else:
                logger.info("Polling job %s: Status=%s", job_id, status_data.status)
                time.sleep(poll_interval)

    def add_file_annotation(
        self,
        *,
        file_hash: str,
        schema_id: str,
        annotation: "Annotation | AnnotationGroup",
        overwrite: bool = False,
        api_key: str | None = None,
    ) -> "AnnotationIndexResult":
        """
        Adds or updates a single source-aware annotation for a specific file.

        Args:
            file_hash (str): The SHA-256 hash of the file to annotate.
            dataset_id (str): The target dataset ID (e.g., "namespace/name").
            annotation (Annotation): The `dorsal.file.validators.file_record.Annotation`
                object to add.
            overwrite (bool): If True, replaces an existing annotation from the
                same source. If False (default), fails if one already exists.
            api_key (str | None): An API key for this request, overriding the
                client's default.

        Returns:
            AnnotationIndexResult: A detailed result of the indexing operation.

        Raises:
            DorsalClientError: For client-side validation errors.
            NotFoundError: If the file or dataset is not found.
            ConflictError: If `overwrite` is False and an annotation from this
                source already exists.
            ForbiddenError: If you do not have permission to annotate the file.
            APIError: For any other unhandled API error.
        """
        from dorsal.client.validators import AnnotationIndexResult
        from dorsal.file.validators.file_record import Annotation, AnnotationGroup

        logger.debug(
            "Client: add_file_annotation called for hash '%s', dataset '%s'.",
            file_hash,
            schema_id,
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        if not isinstance(annotation, (Annotation, AnnotationGroup)):
            raise DorsalClientError("The 'annotation' argument must be a valid Annotation or AnnotationGroup.")

        namespace, name = self._split_dataset_or_schema_id(schema_id)
        target_url = self._make_add_file_annotation_url(validated_hash, namespace, name)
        params = {"overwrite": overwrite}
        request_body = annotation.model_dump(mode="json")

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.post(
                url=target_url,
                json=request_body,
                params=params,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code not in [200, 201, 409]:
            self._handle_api_error(response=response)

        try:
            return AnnotationIndexResult(**response.json())
        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on add_file_annotation failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def get_file_annotation(
        self, *, file_hash: str, annotation_id: str, api_key: str | None = None
    ) -> "FileAnnotationResponse":
        """
        Retrieves a single annotation by its ID.

        **Automatic Reassembly:**
        If the requested annotation was "sharded" (split into multiple chunks due to
        size limits) during upload, this method automatically fetches the group container,
        reassembles the chunks in the correct order, and returns the fully merged record.

        This process is transparent: the returned object is indistinguishable from
        a standard atomic annotation.

        Args:
            file_hash (str): The SHA-256 hash of the file the annotation belongs to.
            annotation_id (str): The unique ID of the annotation to retrieve.
            api_key (str | None): An API key for this request, overriding the
                client's default.

        Returns:
            FileAnnotationResponse: The full, detailed annotation record.

        Raises:
            DorsalClientError: For client-side validation errors.
            NotFoundError: If the file or annotation is not found, or if you
                lack permission to view it.
            ApiDataValidationError: If the response cannot be validated or reassembled.
            APIError: For any other unhandled API error.
        """
        from dorsal.client.validators import FileAnnotationResponse
        from dorsal.file.validators.file_record import AnnotationGroup

        logger.debug(
            "Client: get_file_annotation called for hash '%s', annotation_id '%s'.",
            file_hash,
            annotation_id,
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        if not annotation_id or not isinstance(annotation_id, str):
            raise DorsalClientError("annotation_id must be a non-empty string.")

        target_url = self._make_get_file_annotation_url(validated_hash, annotation_id)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.get(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 200:
            self._handle_api_error(response)

        try:
            json_response = response.json()

            if json_response.get("group"):
                try:
                    from dorsal.file.sharding import reassemble_record
                    from dorsal.client.validators import FileAnnotationGroupResponse

                    group_response_obj = FileAnnotationGroupResponse(**json_response)

                    schema_id, unified_record = reassemble_record(group_response_obj.group)

                    logger.debug(
                        "Transparently reassembled %d chunks for annotation %s (Schema: %s).",
                        len(group_response_obj.group.annotations),
                        annotation_id,
                        schema_id,
                    )

                    return FileAnnotationResponse(
                        annotation_id=group_response_obj.annotation_id,
                        file_hash=group_response_obj.file_hash,
                        schema_id=schema_id,
                        schema_version=group_response_obj.schema_version,
                        source=group_response_obj.source,
                        record=unified_record,
                        user_id=group_response_obj.user_id,
                        date_created=group_response_obj.date_created,
                        date_modified=group_response_obj.date_modified,
                        private=group_response_obj.private,
                    )

                except PydanticValidationError as err:
                    raise ApiDataValidationError(
                        message="API returned a malformed Sharded Group response.",
                        request_url=target_url,
                        original_exception=err,
                    ) from err
                except Exception as err:
                    logger.exception("Failed to reassemble sharded annotation group.")
                    raise ApiDataValidationError(
                        message="Failed to reassemble sharded annotation record.",
                        request_url=target_url,
                        original_exception=err,
                    ) from err

            return FileAnnotationResponse(**json_response)

        except (json.JSONDecodeError, PydanticValidationError) as err:
            raise ApiDataValidationError(
                message="API response on get_file_annotation failed data validation.",
                request_url=target_url,
                original_exception=err,
            ) from err

    def delete_file_annotation(self, *, file_hash: str, annotation_id: str, api_key: str | None = None) -> None:
        """
        Deletes a single, specific annotation by its ID.

        Note: This typically applies to non-core annotations created via the API
        or client libraries. Core annotations (like file/base, file/pdf) managed
        by the system might not be deletable this way.

        Example:
            ```python
            from dorsal.client import DorsalClient

            # Assumes client is initialized with a valid API key
            client = DorsalClient()
            file_hash_to_modify = "..."
            annotation_id_to_delete = "..." # ID obtained previously

            try:
                client.delete_file_annotation(
                    file_hash=file_hash_to_modify,
                    annotation_id=annotation_id_to_delete
                )
                print(f"Successfully deleted annotation {annotation_id_to_delete}")
            except Exception as e:
                print(f"Error deleting annotation: {e}")
            ```

        Args:
            file_hash (str): The 64-character SHA-256 hash of the file the
                annotation belongs to.
            annotation_id (str): The unique identifier of the annotation to delete.
            api_key (str | None): Optional API key to override the client's default.

        Returns:
            None: A successful deletion returns no content (HTTP 204).

        Raises:
            DorsalClientError: For client-side validation issues (invalid hash, empty ID).
            NotFoundError: If the file or annotation ID is not found, or the annotation
                ID does not belong to the specified file hash.
            ForbiddenError: If the user does not have permission to delete the
                specified annotation.
            AuthError: If authentication fails.
            NetworkError: For network connectivity issues.
            APIError: For any other unhandled API error (4xx, 5xx).
        """
        logger.debug(
            "Client: delete_file_annotation called for hash '%s', annotation_id '%s'.",
            file_hash,
            annotation_id,
        )
        try:
            validated_hash = validate_hex64(file_hash)
        except ValueError as err:
            raise DorsalClientError(f"Invalid SHA-256 hash provided: '{file_hash}'") from err

        if not annotation_id or not isinstance(annotation_id, str):
            raise DorsalClientError("annotation_id must be a non-empty string.")

        target_url = self._make_delete_file_annotation_url(validated_hash, annotation_id)
        logger.debug("Attempting to delete annotation at: %s", target_url)

        try:
            headers = self._make_request_headers(api_key=api_key)
            response = self.session.delete(
                url=target_url,
                allow_redirects=False,
                timeout=self.timeout,
                headers=headers,
            )
            self.last_response = response
        except requests.exceptions.RequestException as err:
            logger.exception("HTTP DELETE request failed for %s", target_url)
            raise NetworkError("An unexpected error occurred during the HTTP request.", target_url, err) from err

        if response.status_code != 204:
            logger.warning(
                "Failed to delete annotation %s for hash %s. API responded with status %s.",
                annotation_id,
                validated_hash,
                response.status_code,
            )
            self._handle_api_error(response=response)
            raise APIError(
                response.status_code, "Unhandled error during annotation deletion", target_url, response.text
            )  # pragma: no cover

        logger.debug("Successfully deleted annotation %s from file %s.", annotation_id, validated_hash)
        return None
