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
import json
import pathlib
import re
from typing import Any, Literal, Self, Sequence, TYPE_CHECKING, Type, cast
import uuid


from pydantic import BaseModel, ConfigDict, Field

from dorsal.client import DorsalClient
from dorsal.client.validators import FileAnnotationResponse, FileDeleteResponse, FileIndexResponse
from dorsal.common.auth import is_offline_mode
from dorsal.common.constants import BASE_URL
from dorsal.common.exceptions import (
    APIError as DorsalClientAPIError,
    AttributeConflictError,
    AuthError as DorsalClientAuthError,
    BadRequestError as DorsalClientBadRequestError,
    ConflictError as DorsalClientConflictError,
    DorsalError,
    DorsalClientError,
    DuplicateTagError,
    FileAnnotatorError,
    ForbiddenError as DorsalClientForbiddenError,
    InvalidTagError,
    NetworkError as DorsalClientNetworkError,
    NotFoundError as DorsalClientNotFoundError,
    PydanticValidationError,
    RateLimitError as DorsalClientRateLimitError,
    TaggingError,
    UnsupportedHashError,
)
from dorsal.common.validators import (
    JsonSchemaValidator,
    import_callable,
    is_valid_dataset_id_or_schema_id,
)
from dorsal.common.model import AnnotationModel, scrub_pii_from_model

from dorsal.file.model_runner import ModelRunner
from dorsal.file.utils.hashes import hash_string_validator
from dorsal.file.utils.size import human_filesize
from dorsal.file.validators.open_schema import get_open_schema_validator
from dorsal.file.validators.file_record import CORE_MODEL_ANNOTATION_WRAPPERS

from dorsal.session import get_shared_dorsal_client

if TYPE_CHECKING:
    from dorsal.file.helpers import ClassificationLabel
    from dorsal.file.configs.model_runner import ModelRunnerPipelineStep
    from dorsal.file import MetadataReader
    from dorsal.file.validators.file_record import (
        Annotation,
        AnnotationXL,
        AnnotationGroup,
        AnnotationStub,
        Annotations,
        AnnotationSource,
        DeletionScope,
        FileRecord,
        FileRecordDateTime,
        FileRecordLite,
        FileRecordSuperLite,
        FileRecordStrict,
        FileTag,
        NewFileTag,
    )
    from dorsal.file.validators.base import FileCoreValidationModelHash
    from dorsal.file.validators.mediainfo import MediaInfoValidationModel
    from dorsal.file.validators.pdf import PDFValidationModel
    from dorsal.file.validators.ebook import EbookValidationModel
    from dorsal.file.validators.office_document import OfficeDocumentValidationModel


logger = logging.getLogger(__name__)


class FileAnnotationStub:
    """
    Interactive AnnotationStub.

    Download the full annotation with `download` method.
    """

    def __init__(self, stub: AnnotationStub, parent_file: "DorsalFile"):
        self._parent = parent_file
        self._stub = stub

        self.id: uuid.UUID = self._stub.id
        self.parent_hash = self._stub.hash
        self.source: AnnotationSource = self._stub.source
        self.user_id: int = self._stub.user_id
        self.date_modified: datetime.datetime = self._stub.date_modified
        self.url: str = self._make_url()

    def _make_url(self) -> str:
        return f"{BASE_URL}/file/{self.parent_hash}/annotations/{self.id}"

    @property
    def info(self) -> dict:
        return self.summary()

    def summary(self) -> dict:
        return {
            "id": self.id,
            "source": self.source.model_dump(by_alias=True, exclude_none=True),
            "user_id": self.user_id,
            "date_modified": self.date_modified,
            "url": self.url,
        }

    def download(self) -> FileAnnotationResponse:
        """
        Fetches full annotation record from DorsalHub.

        Returns:
            FileAnnotationResponse: A Pydantic model of the full annotation record.

        Raises:
            DorsalError: If the `DorsalFile` parent is not fully instantiated (no hash).
            DorsalClientError: If the API call fails for any reason.

        """
        client = self._parent._client or get_shared_dorsal_client()
        if self._parent.hash is None:
            raise DorsalError(f"Invalid `DorsalFile` instance: {str(self._parent)}")
        return client.get_file_annotation(file_hash=self._parent.hash, annotation_id=str(self.id))

    def __repr__(self) -> str:
        return f"<FileAnnotationStub id='{self.id}'>"


class _DorsalFile:
    """
    Represents a file record.
    """

    _source: Literal["dorsalhub", "cache", "disk"]
    FILE_NAME_MAX_LEN = 64

    def __init__(self, *, file_record: FileRecord):
        """
        Args:
            file_record: File annotation record
        """

        from dorsal.file.validators.file_record import (
            FileRecordDateTime,
            FileRecordStrict,
        )

        if not isinstance(file_record, (FileRecordDateTime, FileRecordStrict)):
            raise TypeError(
                f"file_record must be an instance of FileRecord or FileRecordStrict, got {type(file_record).__name__}"
            )
        self.model: FileRecord = file_record

        self.date_created: datetime.datetime
        self.date_modified: datetime.datetime
        self._client: DorsalClient | None
        self.hash: str | None = None
        self.validation_hash: str | None = None
        self.name: str | None = None
        self.extension: str | None = None
        self.size: int = 0
        self.media_type: str | None = None
        self.annotations: Annotations | None = None
        self.all_hashes: list[FileCoreValidationModelHash] | None = None

        self._metadata_reader: MetadataReader | None = None
        self.mediainfo: MediaInfoValidationModel | None = None
        self.mediainfo_source: AnnotationSource | None = None
        self.pdf: PDFValidationModel | None = None
        self.pdf_source: AnnotationSource | None = None
        self.ebook: EbookValidationModel | None = None
        self.ebook_source: AnnotationSource | None = None
        self.office: OfficeDocumentValidationModel | None = None
        self.office_source: AnnotationSource | None = None

        self._set_pydantic_method_aliases()
        self._populate()
        self._instance_datetime = datetime.datetime.now().astimezone()

    def __repr__(self):
        name_repr = self.name

        if name_repr is None and hasattr(self, "_file_path"):
            name_repr = pathlib.Path(self._file_path).name

        if name_repr is None:
            name_repr = self.hash

        deleted_str = ""
        if getattr(self, "_is_deleted", False):
            deleted_str = " (deleted)"

        if name_repr is None:
            return f"{self.__class__.__name__}[ Unidentified ]"

        if len(name_repr) > self.FILE_NAME_MAX_LEN:
            chars_for_name_segment = self.FILE_NAME_MAX_LEN - 2
            if chars_for_name_segment <= 0:
                return f"{self.__class__.__name__}[ ..{deleted_str} ]"
            name_segment = name_repr[-chars_for_name_segment:]
            return f"{self.__class__.__name__}[ ..{name_segment}{deleted_str} ]"

        return f"{self.__class__.__name__}[ {name_repr}{deleted_str} ]"

    @property
    def tags(self) -> list[FileTag]:
        """Provides direct access to the list of tags on the underlying model.
        Ensures that a list is always returned, and modifications update the model.
        """
        return self.model.tags

    @tags.setter
    def tags(self, value: list[FileTag]):
        """Allows setting the tags list, ensuring it's a list of FileTag."""
        if not isinstance(value, list):
            raise TypeError("Tags must be a list of FileTag objects.")
        from dorsal.file.validators.file_record import FileTag

        for item in value:
            if not isinstance(item, FileTag):
                raise TypeError(
                    f"All items in tags list must be FileTag objects or compatible dicts, got {type(item).__name__}."
                )
        self.model.tags = value

    @property
    def size_text(self) -> str:
        return human_filesize(self.size)

    def _populate(self) -> None:
        """Parse out `FileRecord` and set attributes on the instance."""
        file_record = self.model
        self.hash = file_record.hash
        self.quick_hash = getattr(file_record, "quick_hash", None)
        self.validation_hash = getattr(file_record, "validation_hash", None)
        self.annotations = file_record.annotations
        self.name = None
        self.extension = None
        self.size = 0
        self.media_type = None
        self.all_hashes = None
        self.mediainfo = None
        self.mediainfo_source = None
        self.pdf = None
        self.pdf_source = None
        self.ebook = None
        self.ebook_source = None
        self.office = None
        self.office_source = None

        if file_record.annotations is None:
            return None

        file_base_annotation = getattr(file_record.annotations, "file_base", None)
        if file_base_annotation and hasattr(file_base_annotation, "record") and file_base_annotation.record is not None:
            base_record = getattr(file_base_annotation, "record", None)
            if base_record:
                self.all_hashes = getattr(base_record, "all_hashes", None)
                self.name = getattr(base_record, "name", None)
                self.extension = getattr(base_record, "extension", None)
                self.size = getattr(base_record, "size", 0)
                self.media_type = getattr(base_record, "media_type", None)

        file_mediainfo_annotation = getattr(file_record.annotations, "file_mediainfo", None)
        if file_mediainfo_annotation:
            self.mediainfo = getattr(file_mediainfo_annotation, "record", None)
            self.mediainfo_source = getattr(file_mediainfo_annotation, "source", None)

        file_pdf_annotation = getattr(file_record.annotations, "file_pdf", None)
        if file_pdf_annotation:
            self.pdf = getattr(file_pdf_annotation, "record", None)
            self.pdf_source = getattr(file_pdf_annotation, "source", None)

        file_ebook_annotation = getattr(file_record.annotations, "file_ebook", None)
        if file_ebook_annotation:
            self.ebook = getattr(file_ebook_annotation, "record", None)
            self.ebook_source = getattr(file_ebook_annotation, "source", None)

        file_office_annotation = getattr(file_record.annotations, "file_office", None)
        if file_office_annotation:
            self.office = getattr(file_office_annotation, "record", None)
            self.office_source = getattr(file_office_annotation, "source", None)

    def _set_pydantic_method_aliases(self) -> None:
        """Set class aliases for FileRecord pydantic model methods."""
        self.model_dump = self.model.model_dump
        self.model_dump_json = self.model.model_dump_json
        self.model_copy = self.model.model_copy

    def to_json(
        self,
        indent: int | None = 2,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
    ) -> str:
        """Convenience wrapper for `model.model_dump_json` with appropriate defaults:
        - by_alias=True is necessary to get the correct dataset_id format (e.g. 'dorsal/arxiv')
        """
        return self.model.model_dump_json(
            indent=indent,
            by_alias=by_alias,
            exclude_none=exclude_none,
            exclude=exclude,
        )

    def to_dict(
        self,
        by_alias=True,
        exclude_none=True,
        mode: Literal["python", "json"] = "python",
        exclude: dict | set | None = None,
    ) -> dict:
        """Convenience wrapper for `model.model_dump` with appropriate defaults:
        - by_alias=True is necessary to get the correct dataset_id format (e.g. 'dorsal/arxiv')
        """
        return self.model.model_dump(
            by_alias=by_alias,
            exclude_none=exclude_none,
            mode=mode,
            exclude=exclude,
        )


class DorsalFile(_DorsalFile):
    """
    Represents a file whose metadata is fetched from the DorsalHub platform.

    This constructor performs a network request to the DorsalHub API to download
    the file's record. The operation may take some time depending on network
    conditions and API responsiveness.

    This class provides an object-oriented interface to a file's record on DorsalHub,
    identified by its hash string.

    Attributes:
        hash (str): The primary SHA-256 hash of the file content.
        name (str): The base name of the file.
        size (int): The file size in bytes.
        media_type (str): The detected media type of the file.
        tags (list[FileTag]): A list of tags associated with the file.
        annotations (object): A container for detailed metadata records.

    Example:
        ```python
        from dorsal import DorsalFile

        # This fetches the record for the given hash from DorsalHub.
        file_hash = "known_file_hash_from_dorsalhub"
        dorsal_file = DorsalFile(file_hash)

        print(f"File: {dorsal_file.name}")
        ```

    Args:
        hash_string (str): The hash of the file to fetch. Can be prefixed
            with the algorithm (e.g., "blake3:...") but defaults to SHA-256.
        private (bool, optional): If True, searches for the file in your
            private records. If False, searches public records. Defaults to False.
        client (DorsalClient, optional): An existing `DorsalClient` instance
            to use for the API call. If not provided, a shared instance
            will be used. Defaults to None.

    Raises:
        DorsalClientError: If the API call fails.
        NotFoundError: If no file record with the specified hash is found.

    """

    def __init__(
        self,
        hash_string: str,
        private: bool | None = None,
        client: DorsalClient | None = None,
        _file_record: "FileRecordDateTime | None" = None,
    ):
        """
        Initializes a DorsalFile instance by fetching its metadata from DorsalHub.

        If `_file_record` is provided, it initializes from that data directly.

        Args:
            hash_string: The hash string (e.g., "sha256:value" or just "value" for SHA-256)
                         of the file to fetch.
            private (optional) : By default (None) will attempt to download the private file record, and fall
                                 back on the public, before raising an error if neither are found.
            client: An optional DorsalClient instance for API communication.
                    If None, a globally shared DorsalClient instance will be used.

        Raises:
            DorsalClientError: If an error occurs during instantiation.
            TypeError: If hash_string is not a string.
        """
        if not isinstance(hash_string, str):
            raise TypeError(f"hash_string must be a string, got {type(hash_string).__name__}")

        self._source: Literal["dorsalhub"] = "dorsalhub"
        self._hash_string: str = hash_string
        self._client: DorsalClient = client if client is not None else get_shared_dorsal_client()
        self._private: bool | None = private
        self._is_deleted: bool = False
        self.annotation_stubs: dict[str, list[FileAnnotationStub]] = {}

        file_record_model: "FileRecordDateTime"
        if _file_record:
            file_record_model = _file_record
        else:
            file_record_model = self._download()

        self.date_modified = file_record_model.date_modified.astimezone(tz=datetime.UTC)
        self.date_created = file_record_model.date_created.astimezone(tz=datetime.UTC)

        super().__init__(file_record=file_record_model)
        logger.debug("DorsalFile for hash '%s' initialized successfully.", self.hash)

    @classmethod
    def from_record(cls, record: "FileRecordDateTime", client: DorsalClient | None = None) -> "DorsalFile":
        """
        Alternative constructor to create a DorsalFile instance from an
        already-fetched FileRecordDateTime object.

        This avoids making an additional API call to download the record.

        Args:
            record: The FileRecordDateTime Pydantic model instance.
            client: An optional DorsalClient instance to attach to the object.

        Returns:
            An initialized DorsalFile instance.
        """
        return cls(hash_string=record.hash, client=client, _file_record=record)

    def _download(self) -> FileRecordDateTime:
        """
        Internal method to download the file record using the configured DorsalClient.
        This method handles common API errors and wraps them in a user-friendly
        DorsalClientError.

        Returns:
            The downloaded FileRecordDateTime.

        Raises:
            DorsalClientError: If an error occurs during communication with DorsalHub.
                               The message will be tailored for common issues.
                               The `original_exception` attribute will contain the
                               more detailed error from the underlying client.
        """
        try:
            logger.debug(
                "DorsalFile _download: Attempting to download %s record for hash '%s'.",
                "private" if self._private else "public",
                self._hash_string,
            )
            if self._private is None:
                record = self._client.download_file_record(hash_string=self._hash_string, private=None)
            elif self._private:
                record = self._client.download_private_file_record(hash_string=self._hash_string)
            else:
                record = self._client.download_public_file_record(hash_string=self._hash_string)
            return record
        except DorsalClientNotFoundError as err:
            msg = f"File record not found on DorsalHub for hash: {self._hash_string}."
            logger.warning(f"{msg} URL: {err.request_url}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientAuthError as err:
            msg = "Authentication failed when accessing DorsalHub. Please check your API key and permissions."
            logger.warning(f"{msg} URL: {getattr(err, 'request_url', None)}. Original error: {err}")
            raise DorsalClientError(
                message=msg,
                request_url=getattr(err, "request_url", None),
                original_exception=err,
            ) from err
        except DorsalClientRateLimitError as err:
            retry_after_msg = f" (Retry-After: {err.retry_after})" if err.retry_after else ""
            msg = f"Rate limit exceeded when accessing DorsalHub{retry_after_msg}. Please try again later."
            logger.warning(f"{msg} URL: {err.request_url}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientBadRequestError as err:
            msg = f"The request to DorsalHub for file hash '{self._hash_string}' was invalid or malformed."
            logger.warning(
                f"{msg} URL: {err.request_url}. Detail: {err.detail if hasattr(err, 'detail') else str(err)}. Original error: {err}"
            )
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientForbiddenError as err:
            msg = f"Access denied for file hash '{self._hash_string}' on DorsalHub. Ensure you have necessary permissions."
            logger.warning(f"{msg} URL: {err.request_url}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientConflictError as err:
            msg = f"A conflict occurred when accessing file hash '{self._hash_string}' on DorsalHub. This might be due to data inconsistencies or concurrent updates."
            logger.warning(f"{msg} URL: {err.request_url}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientNetworkError as err:
            msg = "A network error occurred while trying to contact DorsalHub."
            logger.warning(f"{msg} URL: {err.request_url}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except UnsupportedHashError as err:
            msg = f"The hash string format or type is unsupported: '{self._hash_string}'."
            logger.warning(f"{msg} Original error: {err}")
            raise DorsalClientError(message=msg, original_exception=err) from err
        except DorsalClientAPIError as err:
            msg = f"An API error (status: {err.status_code}) occurred while fetching data from DorsalHub for hash: {self._hash_string}."
            logger.warning(f"{msg} URL: {err.request_url}. Detail: {err.detail}. Original error: {err}")
            raise DorsalClientError(message=msg, request_url=err.request_url, original_exception=err) from err
        except DorsalClientError as err:
            msg = f"A client-side error occurred while processing request for hash: {self._hash_string}."
            logger.warning(f"{msg} Original error: {err}")
            raise DorsalClientError(
                message=msg,
                request_url=getattr(err, "request_url", None),
                original_exception=err,
            ) from err

    def _populate(self) -> None:
        """Populate all base attributes from the parent class."""
        from dorsal.file.validators.file_record import AnnotationStub

        super()._populate()

        if self.annotations:
            pydantic_extra = getattr(self.model.annotations, "__pydantic_extra__", None)
            if pydantic_extra:
                for key, value in pydantic_extra.items():
                    if isinstance(value, list):
                        valid_stubs = []
                        for item in value:
                            if isinstance(item, AnnotationStub):
                                valid_stubs.append(item)
                            elif isinstance(item, dict):
                                try:
                                    valid_stubs.append(AnnotationStub(**item))
                                except PydanticValidationError:
                                    pass

                        if valid_stubs:
                            self.annotation_stubs[key] = [
                                FileAnnotationStub(stub=stub, parent_file=self) for stub in valid_stubs
                            ]

    def get_annotations(
        self, schema_id: str, source_id: str | None = None
    ) -> Sequence[
        FileAnnotationStub
        | PDFValidationModel
        | MediaInfoValidationModel
        | EbookValidationModel
        | OfficeDocumentValidationModel
    ]:
        """
        Retrieves a list of annotations (or stubs) from the remote record, by schema_id.

        Args:
            schema_id: The unique identifier of the dataset/schema (e.g. 'open/classification').
            source_id: Optional. Filter annotations by their source ID.

        Returns:
            A list of FileAnnotationStub objects (for custom schemas) or Core Models.
        """
        if schema_id == "file/pdf":
            return [self.pdf] if self.pdf else []
        elif schema_id == "file/mediainfo":
            return [self.mediainfo] if self.mediainfo else []
        elif schema_id == "file/ebook":
            return [self.ebook] if self.ebook else []
        elif schema_id == "file/office":
            return [self.office] if self.office else []

        stubs = self.annotation_stubs.get(schema_id, [])

        if source_id is not None:
            return [stub for stub in stubs if stub.source.id == source_id]

        return stubs

    def set_validation_hash(self, validation_hash: str) -> None:
        """Sets the BLAKE3 validation hash, potentially upgrading the model.

        This method validates the format of the provided BLAKE3 hash string.
        If valid, it updates the instance's `validation_hash` and the
        underlying Pydantic model (`self.model`). The model is explicitly
        re-instantiated to ensure all Pydantic validations run.

        If the `DorsalFile` instance's model (initially `FileRecordDateTime`)
        has its `annotations` field populated, setting this `validation_hash`
        will upgrade `self.model` to `FileRecordStrict`. Otherwise, `self.model`
        will remain `FileRecordDateTime` but with its `validation_hash` field now set.

        This method is specific to `DorsalFile` and allows users to provide
        the BLAKE3 hash to "validate" possession of a file, as the server
        does not disclose this hash for `FileRecordDateTime` downloads.

        Args:
            validation_hash: The candidate string for the BLAKE3 validation hash.

        Raises:
            TypeError: If `blake3_hash_input` is not a string.
            ValueError: If `blake3_hash_input` is not a valid BLAKE3 hash format,
                        or if updating the model causes a Pydantic validation
                        error (e.g., hash collision with primary SHA256).
            RuntimeError: For unexpected errors during the process.
        """
        from dorsal.file.validators.file_record import FileRecordDateTime, FileRecordStrict

        if not isinstance(validation_hash, str):
            raise TypeError("Input 'blake3_hash_input' must be a string.")

        logger.debug(
            "DorsalFile: Attempting to set BLAKE3 hash: '%s' for file (current primary hash: %s)",
            validation_hash,
            self.hash,
        )

        normalized_blake3 = hash_string_validator.get_valid_hash(
            candidate_string=validation_hash, hash_function="BLAKE3"
        )

        if normalized_blake3 is None:
            logger.warning(
                "DorsalFile: Invalid BLAKE3 hash format provided: '%s' for file (primary hash: %s)",
                validation_hash,
                self.hash,
            )
            raise ValueError(f"The provided string '{validation_hash}' is not a valid BLAKE3 hash format.")

        current_model_data = self.model.model_dump()
        current_model_data["validation_hash"] = normalized_blake3

        target_model_class: type[FileRecordDateTime] | type[FileRecordStrict]
        if self.model.annotations is not None:
            logger.debug(
                "DorsalFile: Annotations found. Attempting to upgrade model to FileRecordStrict for file (primary hash: %s).",
                self.hash,
            )
            target_model_class = FileRecordStrict
            current_model_data["source"] = "dorsalhub"
        else:
            logger.debug(
                "DorsalFile: Annotations field is None. Model will be FileRecordDateTime with validation_hash for file (primary hash: %s).",
                self.hash,
            )
            target_model_class = FileRecordDateTime

        try:
            updated_model = target_model_class(**current_model_data)
            self.model = updated_model

            self.validation_hash = self.model.validation_hash

            logger.debug(
                "DorsalFile: Successfully set validation_hash to '%s' on model type '%s' for file (primary hash: %s)",
                self.validation_hash,
                self.model.__class__.__name__,
                self.hash,
            )
        except PydanticValidationError as err:
            logger.debug(
                "DorsalFile: Pydantic model validation failed during %s instantiation. Errors: %s",
                target_model_class.__name__,
                err.errors(),
            )
            logger.exception(
                "DorsalFile: Failed to set validation_hash '%s' for file (primary hash: %s) "
                "due to Pydantic model validation error when using target class '%s'.",
                normalized_blake3,
                self.hash,
                target_model_class.__name__,
            )
            raise ValueError(
                f"Failed to apply BLAKE3 hash '{normalized_blake3}'. "
                f"Model validation failed for {target_model_class.__name__}. "
                "Check logs for details."
            ) from err
        except Exception as err:
            logger.exception(
                "DorsalFile: Unexpected error setting validation_hash '%s' for file (primary hash: %s) "
                "with target class '%s'.",
                normalized_blake3,
                self.hash,
                target_model_class.__name__,
            )
            raise RuntimeError(f"Unexpected error setting validation_hash: {err!s}") from err

    def _add_tags_remote(
        self,
        *,
        tags: list[NewFileTag],
        api_key: str | None = None,
    ) -> None:
        """Adds one or more tags to the remote file record on DorsalHub.

        This method makes a direct API call to apply tags to the file.

        Args:
            tags (list[NewFileTag]): A list of `NewFileTag` objects to apply.
            api_key (str | None): An optional API key to use for this request.

        Raises:
            DorsalClientError: If the input `tags` list is invalid.
            TaggingError: If the server successfully receives the request but
                is unable to apply the tags for a logical reason.
            APIError: For other unhandled API errors.
        """
        if not self.hash:
            raise ValueError("Cannot add tags to a file with no hash.")
        if not tags or not isinstance(tags, list):
            raise DorsalClientError(message="Input 'tags' must be a non-empty list.")

        logger.debug(
            "Attempting to remotely add %d tags to file (hash: %s)",
            len(tags),
            self.hash,
        )

        try:
            client = self._client or get_shared_dorsal_client(api_key=api_key)
            response = client.add_tags_to_file(file_hash=self.hash, tags=tags, api_key=api_key)

            if not response.success:
                detail = response.detail or "Unknown server-side error."
                logger.warning(
                    "API call succeeded but tagging failed for file %s. Reason: %s",
                    self.hash,
                    detail,
                )
                raise TaggingError(message=detail)

        except DorsalClientError as err:
            logger.exception("An error occurred during the add_tags API call for file %s.", self.hash)
            raise err

        logger.debug(
            "Remote tags added successfully for file %s. Refreshing local state.",
            self.hash,
        )
        self.refresh()

        return None

    def add_public_tag(
        self,
        *,
        name: str,
        value: Any,
        api_key: str | None = None,
    ) -> DorsalFile:
        """Adds a single public tag to the remote file record on DorsalHub.

        This method makes a direct API call. On success, the local object is
        refreshed to reflect the new state on the server.

        Args:
            name: Name of the tag (typically 3-64 alphanumeric characters and
                  underscores).
            value: Value of the tag (str, bool, datetime, int, or float).
            auto_validate: If True, immediately validates the tag against the
                           DorsalHub API (requires internet connection).
                           Defaults to False (lazy validation).
            api_key: Optional API key to use if auto_validate is True.

        Returns:
            DorsalFile: The instance of the class, allowing for method chaining.

        Raises:
            ValueError: If the tag data fails Pydantic validation.
            TaggingError: If the server is unable to apply the tag.
            DorsalClientError: For underlying client, network, or API errors.

        Example:
            ```python
            from dorsal import DorsalFile

            dorsal_file = DorsalFile(hash_string="YOUR_FILE_HASH_HERE")
            dorsal_file.add_public_tag(name="release_candidate", value=True)
            ```
        """
        from dorsal.file.validators.file_record import NewFileTag

        try:
            new_tag = NewFileTag(
                name=name,
                value=value,
                private=False,
            )
        except PydanticValidationError as err:
            logger.exception("Failed to create NewFileTag(name='%s') from user input.", name)
            raise ValueError(f"Invalid tag data for name='{name}'.") from err

        self._add_tags_remote(tags=[new_tag], api_key=api_key)
        logger.info(
            "Public tag (%s=%s) added successfully to remote file record. Object refreshed to reflect changes.",
            name,
            value,
        )
        return self

    def add_private_tag(
        self,
        *,
        name: str,
        value: Any,
        api_key: str | None = None,
    ) -> DorsalFile:
        """Adds a single private tag to the remote file record on DorsalHub.

        This method makes a direct API call. On success, the local object is
        refreshed to reflect the new state on the server.

        Args:
            name (str): The name of the tag.
            value (Any): The value for the tag (str, bool, int, etc.).
            api_key (str | None): An optional API key for this specific request.

        Returns:
            DorsalFile: The instance of the class, allowing for method chaining.

        Raises:
            ValueError: If the tag data fails Pydantic validation.
            TaggingError: If the server is unable to apply the tag.
            DorsalClientError: For underlying client, network, or API errors.

        Example:
            ```python
            from dorsal import DorsalFile

            dorsal_file = DorsalFile(hash_string="YOUR_FILE_HASH_HERE")
            dorsal_file.add_private_tag(name="internal_id", value=12345)
            ```
        """
        from dorsal.file.validators.file_record import NewFileTag

        try:
            new_tag = NewFileTag(
                name=name,
                value=value,
                private=True,
            )
        except PydanticValidationError as err:
            logger.exception("Failed to create NewFileTag(name='%s') from user input.", name)
            raise ValueError(f"Invalid tag data for name='{name}'.") from err

        self._add_tags_remote(tags=[new_tag], api_key=api_key)
        logger.info(
            "Private tag (%s=%s) added successfully to file remote file record. Object refreshed to reflect changes.",
            name,
            value,
        )
        return self

    def add_tags(
        self,
        *,
        public: dict[str, Any] | None = None,
        private: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> DorsalFile:
        """
        Adds multiple tags to the remote file record in one call.

        Args:
            public: A dictionary of public tags to add {name: value}.
            private: A dictionary of private tags to add {name: value}.
            api_key: An optional API key for this specific request.

        Returns:
            DorsalFile: The instance of the class, refreshed with the new tags.

        Raises:
            ValueError: If tag names or values are invalid.
            DorsalClientError: If the API call fails.

        Example:
            ```python
            file.add_tags(
                public={"status": "processed", "project": "alpha"},
                private={"reviewer": "me", "priority": 1}
            )
            ```
        """
        from dorsal.file.validators.file_record import NewFileTag

        tags_to_add: list[NewFileTag] = []

        try:
            if public:
                for name, value in public.items():
                    tags_to_add.append(NewFileTag(name=name, value=value, private=False))

            if private:
                for name, value in private.items():
                    tags_to_add.append(NewFileTag(name=name, value=value, private=True))

        except PydanticValidationError as err:
            logger.exception("Failed to create tag objects from bulk input.")
            raise ValueError(f"Invalid tag data provided in bulk update: {err}") from err

        if not tags_to_add:
            logger.warning("add_tags called with no public or private tags provided.")
            return self

        self._add_tags_remote(tags=tags_to_add, api_key=api_key)

        logger.info("Bulk added %d tags to remote file record. Object refreshed.", len(tags_to_add))
        return self

    def delete_tag(self, *, tag_id: str, api_key: str | None = None) -> DorsalFile:
        """Deletes a specific tag from the remote file record using its unique ID.

        This method makes a direct API call to delete the tag. On success, the
        local object is automatically refreshed with the latest data from the server.

        Args:
            tag_id (str): The unique 24-character ID of the tag to delete.
            api_key (str | None): An optional API key for this specific request.

        Returns:
            DorsalFile: The instance of the class, allowing for method chaining.

        Raises:
            ValueError: If the provided tag_id is not a valid format.
            DorsalClientError: For underlying client, network, or API errors,
                including NotFoundError if the tag does not exist or the user
                does not have permission to delete it.

        Example:
            ```python
            from dorsal import DorsalFile

            # Assume dorsal_file is an initialized DorsalFile object with tags
            dorsal_file = DorsalFile(hash_string="YOUR_FILE_HASH_HERE")

            if dorsal_file.tags:
                # Get the ID of the first tag on the file
                id_to_delete = dorsal_file.tags[0].id

                print(f"Attempting to delete tag with ID: {id_to_delete}")
                dorsal_file.delete_tag(tag_id=id_to_delete)
                print("Tag deleted successfully.")
            else:
                print("File has no tags to delete.")
            ```
        """
        if not self.hash:
            raise ValueError("Cannot add delete tags from a file with no hash.")

        if not isinstance(tag_id, str) or not re.match(r"^[0-9a-f]{24}$", tag_id):
            raise ValueError(f"Invalid tag_id format: '{tag_id}'. Must be a 24-character lowercase hex string.")

        logger.debug(
            "Attempting to remotely delete tag (id: %s) from file (hash: %s)",
            tag_id,
            self.hash,
        )

        try:
            client = self._client or get_shared_dorsal_client(api_key=api_key)
            client.delete_tag(file_hash=self.hash, tag_id=tag_id, api_key=api_key)
        except DorsalClientError as err:
            logger.exception(
                "An error occurred during the delete_tag API call for tag id %s.",
                tag_id,
            )
            raise err

        logger.debug(
            "Remote tag id '%s' deleted successfully for file %s. Refreshing local state.",
            tag_id,
            self.hash,
        )
        self.refresh()

        return self

    def delete(
        self,
        *,
        record: DeletionScope | None = None,
        tags: DeletionScope | None = None,
        annotations: DeletionScope | None = None,
        api_key: str | None = None,
    ) -> "FileDeleteResponse":
        """
        Deletes this file's record and/or associated data from DorsalHub
        with granular control.

        This method is context-aware. If no scope options are provided, it
        derives a default behavior from how the object was initialized:
        - If initialized with `private=True`, it defaults to deleting only
          private data (`record="private"`, `tags="private"`, etc.).
        - If initialized with `private=False`, it defaults to deleting only
          public data.
        - If initialized with `private=None` (agnostic), it defaults to a
          "full clean" (`record="all"`, etc.).

        You can override this default behavior by providing explicit scope
        arguments.

        Args:
            record (Scope, optional): Specifies which record(s) to delete.
                If None, uses the context-aware default.
            tags (Scope, optional): Specifies which tags to delete.
                If None, uses the context-aware default.
            annotations (Scope, optional): Specifies which annotations to delete.
                If None, uses the context-aware default.
            api_key (str | None): An optional API key for this specific request.

        Returns:
            FileDeleteResponse: A detailed report of the deletion operation.

        Raises:
            DorsalClientError: If the remote deletion fails due to an API,
                network, or authentication error.
            DorsalError: If this method is called on an already deleted object.

        Example:
            ```python
            # Assumes 'file' is an initialized DorsalFile(..., private=True)

            # Intuitive default: deletes only the private record and metadata
            file.delete()

            # Powerful override: performs a "full clean" from the private file object
            file.delete(record="all", tags="all", annotations="all")
            ```
        """
        if not self.hash:
            raise ValueError("Cannot delete a file record with no hash.")

        if self._is_deleted:
            raise DorsalError(f"Cannot delete file {self.hash}: This object has already been deleted.")

        default_scope: DeletionScope
        if self._private is True:
            default_scope = "private"
        elif self._private is False:
            default_scope = "public"
        else:
            default_scope = "all"

        final_record_scope = record if record is not None else default_scope
        final_tags_scope = tags if tags is not None else default_scope
        final_annotations_scope = annotations if annotations is not None else default_scope

        logger.debug(
            "Attempting to remotely delete file (hash: %s) with effective options: record=%s, tags=%s, annotations=%s",
            self.hash,
            final_record_scope,
            final_tags_scope,
            final_annotations_scope,
        )

        try:
            client = self._client or get_shared_dorsal_client(api_key=api_key)
            response = client.delete_file(
                file_hash=self.hash,
                record=final_record_scope,
                tags=final_tags_scope,
                annotations=final_annotations_scope,
                api_key=api_key,
            )
        except DorsalClientError as err:
            logger.exception(
                "An error occurred during the file delete API call for hash %s.",
                self.hash,
            )
            raise err

        self._is_deleted = True
        logger.info(
            "File record for hash %s was successfully deleted from DorsalHub. This local object is now stale.",
            self.hash,
        )

        return response

    def refresh(self) -> None:
        """Reloads the file record's data from DorsalHub.

        This method re-fetches the record from the API, updating the object's
        attributes with the latest data from the server.

        Raises:
            DorsalClientError: If the API call fails.
            NotFoundError: If the file record can no longer be found on the server.
        """
        logger.debug("Refreshing DorsalFile for hash: %s", self._hash_string)

        new_file_record = self._download()

        super().__init__(file_record=new_file_record)
        logger.debug("DorsalFile for hash '%s' refreshed successfully.", self.hash)


class LocalFile(_DorsalFile):
    _client: DorsalClient | None
    _identity: Literal["dorsal.LocalFile"] = "dorsal.LocalFile"
    _model_runner: ModelRunner
    _file_path: str

    model: FileRecordStrict
    """Represents a file on the local filesystem.

    Triggers an offline metadata extraction pipeline that generates/infers metadata for this file.
    Includes methods for updating, managing and indexing (to DorsalHub) the file metadata.

    Attributes:
        hash (str): The primary SHA-256 hash of the file content.
        name (str): The base name of the file.
        size (int): The file size in bytes.
        media_type (str): The detected media type of the file.
        tags (list[FileTag]): A list of tags associated with the file.
        annotations (object): A container for detailed metadata records.
            Specific annotations like `pdf` or `mediainfo` can be accessed
            as attributes on this object (e.g., `local_file.pdf.page_count`).

    Example:
        ```python
        from dorsal import LocalFile

        # This line processes the file and populates its metadata.
        local_file = LocalFile("path/to/my/document.pdf")

        # Strict Offline usage (Blocks all network calls e.g. for validation or indexing)
        offline_file = LocalFile("path/to/doc.pdf", offline=True)

        print(f"Hashed {local_file.name} ({local_file.size} bytes)")

        if local_file.pdf:
            print(f"It has {local_file.pdf.page_count} pages.")
        ```

    """

    def __init__(
        self,
        file_path: str,
        client: DorsalClient | None = None,
        model_runner_pipeline: str | list[dict[str, Any]] | None = "default",
        use_cache: bool = True,
        overwrite_cache: bool = False,
        offline: bool = False,
        _file_record: FileRecordStrict | None = None,
    ):
        """
        Args:
            file_path: Absolute or relative path to the local file.
            client: An optional DorsalClient instance to use for `push()` operations.
                    If None, a globally shared DorsalClient instance will be used by `push()`.
                    Ignored if `offline` is True.
            model_runner_pipeline: Optional configuration for the ModelRunner instance.
            use_cache: Whether to use the local cache to speed up processing. Defaults to True.
            overwrite_cache: Whether to run the full pipeline *and* overwrite the cache result. Defaults to False
            offline: If True, puts the instance in Offline Mode. Blocks network calls from `LocalFile`.

        Raises:
            FileNotFoundError: If the file_path does not exist or is not a file.
            IOError: If there are issues reading the file.
            DorsalClientError: If model runner encounters an issue that it wraps.
            TypeError: If file_path is not a string.
        """
        from dorsal.file.metadata_reader import MetadataReader

        if not isinstance(file_path, str):
            raise TypeError(f"file_path must be a string, got {type(file_path).__name__}")

        self.offline = offline or is_offline_mode()

        if self.offline:
            self._client = None
            if client is not None:
                logger.warning("LocalFile initialized in OFFLINE mode. The provided 'client' will be ignored.")
        else:
            self._client = client

        self._file_path: str = file_path
        self._use_cache = use_cache
        self._overwrite_cache = overwrite_cache

        if _file_record is None:
            self._metadata_reader = MetadataReader(client=self._client, model_config=model_runner_pipeline)
            logger.debug("LocalFile init: Generating record for local file at '%s'.", file_path)
            file_record_model = self._generate_record()
        else:
            self._metadata_reader = None
            file_record_model = _file_record
            logger.debug("LocalFile init: Loaded from injected record for '%s'.", file_path)

        self._source = file_record_model.source

        stat = pathlib.Path(file_path).stat()
        self.date_modified = datetime.datetime.fromtimestamp(stat.st_mtime).astimezone()

        if hasattr(stat, "st_birthtime"):  # type: ignore[attr-defined]
            self.date_created = datetime.datetime.fromtimestamp(
                stat.st_birthtime  # type: ignore[attr-defined]
            ).astimezone()
        else:
            self.date_created = datetime.datetime.fromtimestamp(stat.st_ctime).astimezone()

        super().__init__(file_record=file_record_model)
        logger.debug(
            "LocalFile for path '%s' (hash: %s) initialized successfully.",
            file_path,
            self.hash,
        )

    def _generate_record(self) -> FileRecordStrict:
        """Use `_metadata_reader` instance to generate File metadata record (`FileRecordStrict`)"""
        if self._metadata_reader is None:
            raise RuntimeError("MetadataReader is not initialized.")
        return self._metadata_reader._get_or_create_record(
            file_path=self._file_path, skip_cache=not self._use_cache, overwrite_cache=self._overwrite_cache
        )

    @classmethod
    def from_json(cls, path: str | pathlib.Path, check_file_exists: bool = False) -> "LocalFile":
        """Factory method: Instantiates a LocalFile from a JSON File Record."""
        from dorsal.file.validators.file_record import FileRecordStrict

        input_path = pathlib.Path(path)
        if not input_path.exists():
            raise FileNotFoundError(f"JSON record not found: {input_path}")

        try:
            with open(input_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {input_path}: {e}") from e

        local_attrs = data.get("local_attributes", {})
        original_file_path = local_attrs.get("file_path", str(input_path))

        if check_file_exists:
            target = pathlib.Path(original_file_path)
            if not target.exists():
                raise FileNotFoundError(
                    f"Serialized record points to '{original_file_path}', which does not exist on this system."
                )

        try:
            record_model = FileRecordStrict.model_validate(data)
        except PydanticValidationError as e:
            raise ValueError(f"JSON data is not a valid FileRecordStrict: {e}") from e

        return cls(file_path=original_file_path, _file_record=record_model)

    def add_public_tag(
        self,
        name: str,
        value: str | bool | int | float | datetime.datetime,
        auto_validate: bool = False,
        api_key: str | None = None,
    ):
        """
        Adds a *public* file tag to the local file model.

        This method modifies `self.model.tags` locally.

        To synchronize these tags with DorsalHub, call `push` on the instance.

        When `auto_validate` is True, validates the tag against the API

        Args:
            name: Name of the tag (typically 3-64 alphanumeric characters and
                  underscores, subject to server-side validation if dorsal is online).
            value: Value of the tag (str, bool, datetime, int, or float).
            api_key: Optional API key to use for validation
        """
        return self._add_local_tag(
            name=name,
            value=value,
            private=False,
            auto_validate=auto_validate,
            api_key=api_key,
        )

    def add_private_tag(
        self,
        name: str,
        value: str | bool | int | float | datetime.datetime,
        auto_validate: bool = False,
        api_key: str | None = None,
    ):
        """
        Adds a *private* file tag to the local file model.

        This method modifies `self.model.tags` locally.

        To synchronize these tags with DorsalHub, call `push` on the instance.

        Args:
            name: Name of the tag (typically 3-64 alphanumeric characters and
                  underscores
            value: Value of the tag (str, bool, datetime, int, or float).
            api_key: Optional API key to use for validation
        """
        return self._add_local_tag(
            name=name,
            value=value,
            private=True,
            auto_validate=auto_validate,
            api_key=api_key,
        )

    def add_label(
        self,
        value: str | bool | int | float | datetime.datetime,
        auto_validate: bool = False,
        api_key: str | None = None,
    ):
        """
        Adds a private 'label' tag to the local file model.

        This method modifies `self.model.tags` locally.
        To synchronize these tags with DorsalHub, call `push` on the instance.

        Note: This is strictly a private tag because "label" is not a whitelisted
        public tag namespace on DorsalHub.

        Args:
            value: Value of the label (str, bool, datetime, int, or float).
            api_key: Optional API key to use for validation.
        """
        return self._add_local_tag(
            name="label",
            value=value,
            private=True,
            auto_validate=auto_validate,
            api_key=api_key,
        )

    def _add_local_tag(
        self,
        name: str,
        value: Any,
        private: bool | Any = True,
        auto_validate: bool = False,
        api_key: str | None = None,
    ) -> "_DorsalFile":
        """Adds a tag to the local file model.

        When `auto_validate` is True, validates the tag against the DorsalHub API.

        Raises:
            ValueError: If local validation fails (missing hash or invalid format).
            DuplicateTagError: If the tag already exists on the file.
            InvalidTagError: If online validation fails (tag rejected by server).
            TaggingError: If online validation is attempted but authentication fails.
        """
        from dorsal.file.validators.file_record import NewFileTag

        if not self.validation_hash:
            error_msg = "Cannot add tag: File is missing a 'validation_hash'. "
            logger.error(
                "Attempted to add tag '%s' to file (hash: %s) without a validation_hash.",
                name,
                self.hash,
            )
            raise ValueError(error_msg)

        if not isinstance(name, str):
            logger.warning("Tag name provided is not a string: %s", type(name).__name__)  # type: ignore[unreachable]
            raise TypeError("Tag name must be a string.")

        if not isinstance(value, (str, bool, datetime.datetime, int, float)):
            logger.warning("Tag value provided has an invalid type: %s", type(value).__name__)
            raise TypeError(
                f"Tag value must be a string, boolean, datetime, int, or float. Got {type(value).__name__}."
            )
        if not isinstance(private, bool):
            logger.warning("Tag 'private' flag must be a boolean. Got: %s", type(private).__name__)
            raise TypeError("Tag 'private' flag must be a boolean.")

        file_identifier = getattr(self, "_file_path", None) or self.hash
        logger.debug(
            "Locally adding tag to file '%s' (hash: %s, validation_hash: %s): name='%s', value_type=%s, private=%s",
            file_identifier,
            self.hash,
            self.validation_hash,
            name,
            type(value).__name__,
            private,
        )

        try:
            new_tag = NewFileTag(
                name=name,
                value=value,
                private=private,
            )
        except PydanticValidationError as err:
            logger.warning(
                "Failed to create FileTag(name='%s', value='%s') due to Pydantic validation error: %s",
                name,
                value,
                err.errors(),
            )
            raise ValueError(f"Invalid tag data for name='{name}'. Details: {err.errors()}") from err

        existing_tags = {(tag.name, tag.value) for tag in self.tags if tag.origin == "dorsal.LocalFile"}
        if (new_tag.name, new_tag.value) in existing_tags:
            raise DuplicateTagError(f"Tag has already been added: {new_tag.name}='{new_tag.value}'")

        if self.offline:
            logger.debug("OFFLINE MODE: Skipping remote validation for tag '%s'.", name)
        elif auto_validate:
            client: DorsalClient | None = getattr(self, "_client", None)

            if client is None:
                try:
                    client = get_shared_dorsal_client(api_key=api_key)
                except DorsalClientAuthError as err:
                    logger.error(
                        "Tag auto-validation requested for '%s' but no valid DorsalClient could be initialized.", name
                    )
                    raise DorsalClientAuthError(
                        "Cannot perform auto-validation: No valid DorsalClient or API key found."
                    ) from err

            if client:
                to_validate = [new_tag]
                validation_result = client.validate_tag(file_tags=to_validate, api_key=api_key)
                if not validation_result.valid:
                    logger.warning("Tag not added: %s - Invalid", new_tag)
                    raise InvalidTagError(validation_result.message or "Tag validation failed.")
        else:
            logger.debug("Skipping tag validation.")

        self.model.tags.append(new_tag)
        private_label = "Private" if private else "Public"
        logger.info(
            "%s tag (%s=%s) added to local record for '%s'. Call push() to sync record with DorsalHub.",
            private_label,
            name,
            value,
            file_identifier,
        )
        return self

    def validate_tags(self, *, api_key: str | None = None):
        """
        Validates all tags against DorsalHub's API.

        Args:
            api_key: Optional API key.

        Returns:
            The validation response object from the client.

        Raises:
            DorsalError: If the instance is in offline mode.
            InvalidTagError: If the tags are rejected by the API.
            DorsalClientError: If the API call fails.
        """
        if self.offline:
            raise DorsalError("Cannot validate tags: LocalFile is in OFFLINE mode.")

        if not self.tags:
            logger.debug("No tags to validate on file '%s'.", self._file_path)
            return None

        client = self._client or get_shared_dorsal_client(api_key=api_key)

        logger.debug(
            "Validating %d tags for file '%s' (hash: %s)",
            len(self.tags),
            self._file_path,
            self.hash,
        )

        validation_result = client.validate_tag(file_tags=self.tags, api_key=api_key)

        if not validation_result.valid:
            error_msg = validation_result.message or "Tag validation failed."
            logger.warning("Tag validation failed for file '%s': %s", self._file_path, error_msg)
            raise InvalidTagError(error_msg)

        logger.info(
            "Successfully validated %d tags for file '%s'.",
            len(self.tags),
            self._file_path,
        )
        return validation_result

    def push(self, private: bool = True, api_key: str | None = None) -> FileIndexResponse:
        """Indexes file's metadata (annotations and tags) to DorsalHub.

        If no record exists for this hash, a new record is created either privately or publicly.

        When `private` is `True`, if you indexed any annotations or tags for this file before, they are overwritten.
        When `private` is `False`, the record is updated in an aggregate manner.

        Note:

        Args:
            private (bool, optional): If True, the file record will be created
                as private and will only be accessible to the authenticated user.
                Defaults to True.
            api_key (str, optional): An API key to use for this specific request,
                overriding the client's default key. Defaults to None.

        Returns:
            FileIndexResponse: A response object from the API detailing the
                result of the indexing operation.

        Raises:
            DorsalClientError: If the push operation fails due to an API error,
                network issue, or authentication failure.
        """
        from dorsal.file.validators.file_record import FileRecordStrict

        if self.offline:
            raise DorsalError("Cannot push file record: LocalFile is in OFFLINE mode. ")

        if not isinstance(self.model, FileRecordStrict):
            logger.error("Cannot push LocalFile: internal model is not FileRecordStrict.")  # type: ignore[unreachable]
            raise DorsalClientError(
                message="Internal error: LocalFile model is not suitable for upload. Expected FileRecordStrict.",
            )

        if self._client is None:
            self._client = get_shared_dorsal_client(api_key=api_key)

        client = self._client

        logger.debug(
            "Pushing %s file record for local file '%s' (hash: %s) to DorsalHub.",
            "private" if private else "public",
            self._file_path,
            self.hash,
        )

        try:
            if private:
                response = client.index_private_file_records(file_records=[self.model], api_key=api_key)
            else:
                response = client.index_public_file_records(file_records=[self.model], api_key=api_key)

            logger.info(
                "Successfully pushed file record for '%s' to DorsalHub. Total: %s, Success: %s, Error: %s",
                self._file_path,
                response.total,
                response.success,
                response.error,
            )
            return response
        except DorsalClientError as err:
            logger.error(
                "Failed to push file record for '%s' to DorsalHub. Error: %s",
                self._file_path,
                err,
            )
            raise

    def _set_annotation_attribute(
        self, schema_id: str, annotation: Annotation | AnnotationGroup, overwrite: bool
    ) -> None:
        from dorsal.file.validators.file_record import CORE_MODEL_ANNOTATION_WRAPPERS

        logger.debug(
            "Attempting to set annotation for schema '%s' on file '%s'.",
            schema_id,
            self._file_path,
        )

        is_core_schema = schema_id in CORE_MODEL_ANNOTATION_WRAPPERS
        annotation_id = schema_id.replace("/", "_").replace("-", "_") if is_core_schema else schema_id

        if is_core_schema:
            if hasattr(self.model.annotations, annotation_id) and not overwrite:
                conflict_message = f"Core annotation '{schema_id}' already exists. Set overwrite=True to replace it."
                logger.warning("AttributeConflictError: %s", conflict_message)
                raise AttributeConflictError(message=conflict_message)

            setattr(self.model.annotations, annotation_id, annotation)
            self._populate()
            return

        current_list: list[Annotation | AnnotationGroup] | None = getattr(self.model.annotations, annotation_id, None)

        if current_list is None:
            setattr(self.model.annotations, annotation_id, [annotation])
            logger.debug("Initialized annotation list for key '%s'.", annotation_id)
        else:
            match_index = -1
            new_source = annotation.source

            new_source_id = new_source.id

            for i, existing_item in enumerate(current_list):
                existing_source = existing_item.source

                if (
                    existing_source.id == new_source_id
                    and existing_source.version == new_source.version
                    and existing_source.variant == new_source.variant
                ):
                    match_index = i
                    break

            if match_index != -1:
                if not overwrite:
                    conflict_message = (
                        f"An annotation for '{schema_id}' with source id '{new_source_id}' "
                        f"(v{new_source.version}) already exists. "
                        "Set overwrite=True to update this specific entry."
                    )
                    logger.warning("AttributeConflictError: %s", conflict_message)
                    raise AttributeConflictError(message=conflict_message)

                current_list[match_index] = annotation
                logger.debug(
                    "Overwrote existing annotation in list for key '%s' (Source ID: %s).", annotation_id, new_source_id
                )
            else:
                current_list.append(annotation)
                logger.debug("Appended annotation to list for key '%s' (Source ID: %s).", annotation_id, new_source_id)

        self._populate()
        return None

    def _annotate_using_pipeline_step(
        self,
        *,
        pipeline_step_config: "ModelRunnerPipelineStep" | dict[str, Any],
        schema_id: str | None = None,
        private: bool,
        overwrite: bool = False,
    ) -> "LocalFile":
        from dorsal.file.file_annotator import FILE_ANNOTATOR
        from dorsal.file.configs.model_runner import ModelRunnerPipelineStep

        logger.debug(
            "Attempting to annotate file '%s' using pipeline step %s, Overwrite: %s",
            self._file_path,
            pipeline_step_config,
            overwrite,
        )

        if not self.validation_hash:
            raise ValueError("Cannot annotate: File is missing 'validation_hash'.")

        pipeline_step_obj = (
            pipeline_step_config
            if isinstance(pipeline_step_config, ModelRunnerPipelineStep)
            else ModelRunnerPipelineStep(**pipeline_step_config)
        )

        if schema_id is None:
            schema_id = pipeline_step_obj.schema_id

        if not is_valid_dataset_id_or_schema_id(schema_id):
            raise ValueError(f"target dataset is not a valid dataset ID: {schema_id}")

        annotation = FILE_ANNOTATOR.annotate_file_using_pipeline_step(
            file_path=self._file_path,
            model_runner=self._model_runner,
            pipeline_step=pipeline_step_obj,
            schema_id=schema_id,
            private=private,
        )

        self._set_annotation_attribute(
            schema_id=schema_id,
            annotation=annotation,
            overwrite=overwrite,
        )

        logger.debug(
            "Annotation Finished for dataset '%s', file '%s'.",
            schema_id,
            self._file_path,
        )
        return self

    def _annotate_using_model_and_validator(
        self,
        *,
        schema_id: str,
        private: bool,
        annotation_model: Type[AnnotationModel],
        validation_model: Type[BaseModel] | JsonSchemaValidator | None = None,
        overwrite: bool = False,
        options: dict | None = None,
    ) -> "LocalFile":
        from dorsal.file.file_annotator import FILE_ANNOTATOR

        logger.debug(
            "Attempting to annotate file '%s' using AnnotationModel: %s, Validation model: %s Overwrite: %s",
            self._file_path,
            annotation_model.__name__,
            validation_model.__name__ if validation_model is not None else None,
            overwrite,
        )
        if not self.validation_hash:
            raise ValueError("Cannot annotate: File is missing 'validation_hash'.")

        if not is_valid_dataset_id_or_schema_id(schema_id):
            raise ValueError(f"target dataset is not a valid dataset ID: {schema_id}")
        try:
            annotation = FILE_ANNOTATOR.annotate_file_using_model_and_validator(
                file_path=self._file_path,
                model_runner=self._model_runner,
                annotation_model_cls=annotation_model,
                schema_id=schema_id,
                private=private,
                options=options,
                validation_model=validation_model,
            )

            self._set_annotation_attribute(
                schema_id=schema_id,
                annotation=annotation,
                overwrite=overwrite,
            )

            logger.debug(
                "Annotation Finished for dataset '%s', file '%s'.",
                schema_id,
                self._file_path,
            )
            return self
        except FileAnnotatorError as err:
            logger.exception("Failed to annotate file using model and validator.")
            raise err

    def _annotate_using_manual_annotation(
        self,
        *,
        annotation: BaseModel | dict[str, Any],
        schema_id: str,
        schema_version: str | None = None,
        private: bool,
        source_id: str | None = None,
        validator: BaseModel | JsonSchemaValidator | None = None,
        ignore_linter_errors: bool = False,
        overwrite: bool = False,
        force: bool = False,
    ) -> None:
        from dorsal.file.file_annotator import FILE_ANNOTATOR

        logger.debug(
            "Attempting to add manual annotation to file '%s', snippet: %s, Overwrite: %s",
            self._file_path,
            str(annotation)[:200],
            overwrite,
        )
        if not force:
            if not self.validation_hash:
                raise ValueError("Cannot annotate: File is missing 'validation_hash'.")
            if not is_valid_dataset_id_or_schema_id(schema_id):
                raise ValueError(f"Invalid Schema ID: {schema_id}")

        annotation = FILE_ANNOTATOR.make_manual_annotation(
            annotation=annotation,
            schema_id=schema_id,
            schema_version=schema_version,
            source_id=source_id,
            validator=validator,
            private=private,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

        self._set_annotation_attribute(schema_id=schema_id, annotation=annotation, overwrite=overwrite)
        return None

    def _add_annotation(
        self,
        *,
        schema_id: str,
        private: bool,
        annotation_record: BaseModel | dict[str, Any],
        validator: BaseModel | None = None,
        source_id: str | None = None,
        api_key: str | None = None,
        overwrite: bool = False,
        force: bool = False,
        ignore_linter_errors: bool = False,
    ) -> "LocalFile":
        """Add or update an annotation with manually provided data.

        This method employs a "Best Effort" validation strategy:
        1. If `schema_id` starts with 'open/' (e.g. 'open/classification'), it uses
           the library's bundled validators. This works offline.
        2. If `schema_id` is custom/remote AND the client is Online, it fetches
           the schema from DorsalHub.
        3. If `schema_id` is custom/remote AND the client is Offline, validation
           is skipped with a warning.

        Args:
            schema_id: The schema identifier (e.g., 'open/generic').
                       Note: Core schemas (e.g., 'file/pdf') cannot be added manually.
            private: Whether the annotation should be marked as private.
            annotation_record: The annotation data (a Pydantic model or dict).
            validator: An optional explicit validator. If provided, overrides
                       automatic resolution.
            detail: An optional string describing the source of the data.
            api_key: An optional API key for fetching remote schemas.
            overwrite: If True, overwrite an existing annotation for the same dataset.
            force: If True, skips ALL validation checks (unsafe).
            ignore_linter_errors: If True, bypasses data quality linter checks.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If `schema_id` is invalid or refers to a protected Core schema.
            DorsalClientError: If an API error occurs while fetching a remote schema.
            FileAnnotatorError: If validation or application fails.
        """
        if schema_id in CORE_MODEL_ANNOTATION_WRAPPERS:
            raise ValueError(f"The '{schema_id}' annotation cannot be added created/updated via _add_annotation. ")

        logger.debug(
            "Attempting to annotate file '%s', schema '%s'.",
            self._file_path,
            schema_id,
        )

        if not isinstance(schema_id, str) or not is_valid_dataset_id_or_schema_id(schema_id):
            raise ValueError(f"Schema ID is not valid: {schema_id}")

        if force:
            logger.warning("`force=True`: Skipping all validation checks.")
        elif validator is None:
            if schema_id.startswith("open/"):
                schema_name = schema_id.removeprefix("open/")
                try:
                    validator = get_open_schema_validator(cast(Any, schema_name))
                    logger.debug("Resolved '%s' to local bundled validator.", schema_id)
                except (ValueError, TypeError):
                    logger.warning("Could not resolve local validator for '%s'", schema_id)

            if validator is None:
                if not self.offline:
                    try:
                        client = self._client or get_shared_dorsal_client(api_key=api_key)
                        logger.debug("Fetching JSON schema validator for dataset '%s' from API.", schema_id)
                        validator = client.make_schema_validator(dataset_id=schema_id, api_key=api_key)
                    except DorsalClientError as err:
                        logger.exception("Failed to fetch schema for validation.")
                        raise err
                else:
                    logger.warning(
                        "OFFLINE MODE: Skipping validation for remote schema '%s'. "
                        "Data will be added without validation.",
                        schema_id,
                    )

        schema_version = None
        if isinstance(validator, JsonSchemaValidator):
            schema_version = validator.schema.get("version")

        try:
            self._annotate_using_manual_annotation(
                annotation=annotation_record,
                schema_id=schema_id,
                schema_version=schema_version,
                private=private,
                source_id=source_id,
                validator=validator,
                overwrite=overwrite,
                ignore_linter_errors=ignore_linter_errors,
                force=force,
            )
            logger.debug("Exiting _add_annotation, successful for dataset '%s'.", schema_id)
            return self
        except (ValueError, FileAnnotatorError) as err:
            logger.exception("Failed to add manual annotation.")
            raise err

    def get_annotations(
        self, schema_id: str, source_id: str | None = None
    ) -> Sequence[
        Annotation
        | AnnotationXL
        | PDFValidationModel
        | MediaInfoValidationModel
        | EbookValidationModel
        | OfficeDocumentValidationModel
    ]:
        """
        Retrieves a list of annotations from the local model by schema_id.

        Args:
            schema_id: The unique identifier of the dataset/schema.
            source_id: Optional. Filter custom annotations by their source ID.

        Returns:
            A list of annotation objects (Core models or generic Annotations).
        """
        from dorsal.file.validators.file_record import AnnotationXL, AnnotationGroup, GenericFileAnnotation

        if schema_id == "file/pdf":
            return [self.pdf] if self.pdf else []
        elif schema_id == "file/mediainfo":
            return [self.mediainfo] if self.mediainfo else []
        elif schema_id == "file/ebook":
            return [self.ebook] if self.ebook else []
        elif schema_id == "file/office":
            return [self.office] if self.office else []

        value = getattr(self.model.annotations, schema_id, None)

        if value is None:
            return []

        raw_list = value if isinstance(value, list) else [value]
        processed_list = []

        for item in raw_list:
            if isinstance(item, AnnotationGroup):
                from dorsal.file.sharding import reassemble_record

                _, record_content = reassemble_record(item)
                head_chunk = item.annotations[0]
                try:
                    reassembled_ann = AnnotationXL(
                        record=GenericFileAnnotation(**record_content),
                        private=head_chunk.private,
                        source=head_chunk.source,
                        schema_version=head_chunk.schema_version,
                        group=None,
                    )
                    processed_list.append(reassembled_ann)
                except Exception as err:
                    raise RuntimeError(f"Failed to reassemble group for {schema_id}: {err}") from err
            else:
                processed_list.append(item)

        if source_id is not None:
            return [ann for ann in processed_list if ann.source.id == source_id]

        return processed_list

    def remove_annotation(self, schema_id: str, source_id: str | None = None) -> "LocalFile":
        """
        Removes an annotation from the local file model.
        For custom schemas, providing `source_id` removes only that specific entry.
        """
        from dorsal.file.validators.file_record import CORE_MODEL_ANNOTATION_WRAPPERS

        annotation_id = schema_id
        is_core = schema_id in CORE_MODEL_ANNOTATION_WRAPPERS

        if is_core:
            annotation_id = schema_id.replace("/", "_").replace("-", "_")

        if source_id is None or is_core:
            if hasattr(self.model.annotations, annotation_id):
                try:
                    delattr(self.model.annotations, annotation_id)
                    if (
                        self.model.annotations.__pydantic_extra__
                        and annotation_id in self.model.annotations.__pydantic_extra__
                    ):
                        del self.model.annotations.__pydantic_extra__[annotation_id]
                    if annotation_id in self.model.annotations.model_fields_set:
                        self.model.annotations.model_fields_set.remove(annotation_id)

                    logger.info("Removed all local annotations for '%s' (key: '%s').", schema_id, annotation_id)
                    self._populate()
                except Exception as e:
                    logger.warning("Failed to remove annotation '%s': %s", schema_id, e)
            return self

        current_val = getattr(self.model.annotations, annotation_id, None)

        if isinstance(current_val, list):
            original_len = len(current_val)

            new_list = [ann for ann in current_val if ann.source.id != source_id]

            if len(new_list) < original_len:
                if not new_list:
                    return self.remove_annotation(schema_id)

                setattr(self.model.annotations, annotation_id, new_list)
                self._populate()
                logger.debug(
                    "Removed %d annotation(s) with source_id '%s' from '%s'.",
                    original_len - len(new_list),
                    source_id,
                    schema_id,
                )

        return self

    def add_private_annotation(
        self,
        *,
        schema_id: str,
        annotation_record: BaseModel | dict[str, Any],
        validator: BaseModel | None = None,
        source: str | None = None,
        api_key: str | None = None,
        overwrite: bool = False,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """Adds a private annotation to the local file model.

        This is a wrapper for the `_add_annotation` method,
        pre-setting `private=True`.

        The annotation is added locally and will be synchronized with DorsalHub upon calling `push()`.

        Args:
            schema_id: The schema used for validation (e.g., 'open/generic').
            annotation_record: The annotation data (a Pydantic model or dict).
            validator: An optional Pydantic model class or `JsonSchemaValidator` instance.
            source: An optional string describing the source of the manual data.
            api_key: An optional API key for fetching the schema.
            overwrite: If True, overwrite an existing annotation for the same dataset.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the `schema_id` is invalid or validation fails.
            FileAnnotatorError: If the annotation record cannot be processed.

        Example:
            ```python
            my_file = LocalFile("path/to/file.txt")
            private_data = {"internal_id": 12345, "status": "pending_review"}
            my_file.add_private_annotation(
                schema_id="dorsal/my-internal-schema",
                annotation_record=private_data
            )
            my_file.push(private=True)
            ```
        """
        logger.debug(
            "Adding private annotation for schema '%s' to file '%s'.",
            schema_id,
            self._file_path,
        )
        return self._add_annotation(
            schema_id=schema_id,
            private=True,
            annotation_record=annotation_record,
            validator=validator,
            source_id=source,
            api_key=api_key,
            overwrite=overwrite,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_public_annotation(
        self,
        *,
        schema_id: str,
        annotation_record: BaseModel | dict[str, Any],
        validator: BaseModel | None = None,
        source: str | None = None,
        api_key: str | None = None,
        overwrite: bool = False,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """Adds a public annotation to the local file model.

        This is a wrapper for the `_add_annotation` method,
        pre-setting `private=False`.

        The annotation is added locally and will be synchronized with DorsalHub upon calling `push()`.

        Args:
            schema_id: The schema used for validation (e.g., 'open/generic').
            annotation_record: The annotation data (a Pydantic model or dict).
            validator: An optional Pydantic model class or `JsonSchemaValidator` instance.
            source: An optional string describing the source of the manual data.
            api_key: An optional API key for fetching the schema.
            overwrite: If True, overwrite an existing annotation for the same dataset.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the `schema_id` is invalid or validation fails.
            FileAnnotatorError: If the annotation record cannot be processed.

        Example:
            ```python
            my_file = LocalFile("path/to/image.jpg")
            public_data = {"label": "cat", "confidence": 0.98}
            my_file.add_public_annotation(
                schema_id="open/classification",
                annotation_record=public_data
            )
            my_file.push(private=False)
            ```
        """
        logger.debug(
            "Adding public annotation for schema '%s' to file '%s'.",
            schema_id,
            self._file_path,
        )
        return self._add_annotation(
            schema_id=schema_id,
            private=False,
            annotation_record=annotation_record,
            validator=validator,
            source_id=source,
            api_key=api_key,
            overwrite=overwrite,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_classification(
        self,
        labels: list[str | ClassificationLabel],
        *,
        vocabulary: list[str] | None = None,
        source: str | None = None,
        score_explanation: str | None = None,
        vocabulary_url: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> LocalFile:
        """
        Adds an 'open/classification' annotation to the file.

        Args:
            - labels: can be simple strings (e.g., ["cat"]) or dictionaries

        example:
            >>> # Only labels
            >>> lf.add_classification(labels=["EXPIRED", "COMPLETED"])
            >>> # Labels with vocabulary
            >>> lf.add_classification(labels=["eng"], vocabulary=["eng", "fra", "deu"])
            >>> # Labels, vocabulary, attributes and source
            >>> lf.add_classification(
                    labels=[
                        {
                            "label": "SENSITIVE",
                            "score": 0.95,
                            "attributes": {
                                "page_number": 22,
                                "context": "This document contains sensitive information"
                            }
                        }
                    ],
                    vocabulary=["SENSITIVE", "INTERNAL", "PUBLIC"],
                    source="MySensitiveDocumentScannerV1.0"
                )
        """
        from dorsal.file.helpers import build_classification_record

        record_data = build_classification_record(
            labels=labels,
            score_explanation=score_explanation,
            vocabulary=vocabulary,
            vocabulary_url=vocabulary_url,
        )

        return self._add_annotation(
            schema_id="open/classification",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_embedding(
        self,
        vector: list[float],
        *,
        model: str | None = None,
        target: str | None = None,
        source: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """
        Adds an 'open/embedding' annotation to the file.

        This helper provides a convenience wrapper for adding a simple
        embedding (feature vector) to the file record.

        Args:
            vector (list[float]): The embedding vector.
            model (str, optional): Name of the algorithm or model
                that generated the embedding (e.g., 'CLIP', 'text-embedding-ada-002').
            target (str, optional): Name of target feature/variable
            source (str, optional): An optional string describing the source
                of the annotation (e.g., 'Local CLIP Model v1.2').
                This will be passed to the 'detail' field.
            private (bool): Whether the annotation should be private.
            overwrite (bool): Whether to overwrite an existing annotation.
            api_key (str, optional): API key for validation.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the file is missing a 'validation_hash'.
        """
        from dorsal.file.helpers import build_embedding_record

        logger.debug(
            "Adding embedding (Model: %s, Dimensions: %d) to file '%s'.",
            model,
            len(vector),
            self._file_path,
        )

        record_data = build_embedding_record(vector=vector, model=model, target=target)

        return self._add_annotation(
            schema_id="open/embedding",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_llm_output(
        self,
        model: str,
        response_data: str | dict[str, Any],
        *,
        prompt: str | None = None,
        language: str | None = None,
        score: float | None = None,
        score_explanation: str | None = None,
        generation_params: dict[str, Any] | None = None,
        generation_metadata: dict[str, Any] | None = None,
        source: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """
        Adds an 'open/llm-output' annotation to the file.

        This helper provides a convenience wrapper for storing the output
        of a Large Language Model (LLM) task related to this file.

        Args:
            model (str): The ID or name of the generative model used
                (e.g., 'gpt-4o').
            response_data (str | dict): The generative output from the model.
                Can be a string or a simple key-value dictionary.
            prompt (str, optional): The text-based task or prompt
                provided to the model.
            language (str, optional): The 3-letter ISO-639-3 language
                code of the response (e.g., 'eng').
            score (float, optional): An optional confidence or evaluation score
                for the generated output, from -1 to 1.
            generation_params (dict, optional): Optional parameters sent in the
                API request (e.g., {"temperature": 0.5, "max_tokens": 1000}).
            generation_metadata (dict, optional): Optional metadata returned
                by the API response (e.g., {"usage": {...}, "finish_reason": "stop"}).
            source (str, optional): An optional string describing the source
                of the annotation (e.g., 'OpenAI Summarizer v3').
                This will be passed to the 'detail' field.
            private (bool): Whether the annotation should be private.
            overwrite (bool): Whether to overwrite an existing annotation.
            api_key (str, optional): API key for validation.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the file is missing a 'validation_hash'.
        """
        from dorsal.file.helpers import build_llm_output_record

        logger.debug(
            "Adding 'open/llm-output' (Model: %s) to file '%s'.",
            model,
            self._file_path,
        )

        record_data = build_llm_output_record(
            model=model,
            response_data=response_data,
            prompt=prompt,
            language=language,
            score=score,
            score_explanation=score_explanation,
            generation_params=generation_params,
            generation_metadata=generation_metadata,
        )

        return self._add_annotation(
            schema_id="open/llm-output",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_location(
        self,
        longitude: float,
        latitude: float,
        *,
        timestamp: str | None = None,
        camera_make: str | None = None,
        camera_model: str | None = None,
        bbox: list[float] | None = None,
        source: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """
        Adds an 'open/geolocation' annotation for a simple Point.

        This helper provides a convenience wrapper for the common use case of
        tagging a file with a single GPS coordinate (longitude, latitude)
        and optional EXIF-like data.

        It automatically builds the required GeoJSON Feature object.

        Args:
            longitude (float): The longitude coordinate (e.g., -0.5895).
            latitude (float): The latitude coordinate (e.g., 51.3814).
            timestamp (str, optional): An ISO 8601 timestamp for when the
                geospatial data was captured (e.g., "2025-09-17T11:45:00Z").
            camera_make (str, optional): The make of the camera or sensor.
            camera_model (str, optional): The model of the camera or sensor.
            source (str, optional): An optional string describing the source
                of the annotation (e.g., 'EXIF Data Parser').
                This will be passed to the 'detail' field.
            private (bool): Whether the annotation should be private.
            overwrite (bool): Whether to overwrite an existing annotation.
            api_key (str, optional): API key for validation.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the file is missing a 'validation_hash'.
        """
        from dorsal.file.helpers import build_location_record

        logger.debug(
            "Adding 'open/geolocation' Point(%s, %s) to file '%s'.",
            longitude,
            latitude,
            self._file_path,
        )

        record_data = build_location_record(
            longitude=longitude,
            latitude=latitude,
            timestamp=timestamp,
            camera_make=camera_make,
            camera_model=camera_model,
            bbox=bbox,  # Passed through
        )

        return self._add_annotation(
            schema_id="open/geolocation",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_transcription(
        self,
        text: str,
        language: str,
        *,
        track_id: str | int | None = None,
        source: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """
        Adds a simple 'open/audio-transcription' annotation to the file.

        This helper provides a convenience wrapper for the common use case of
        storing the *full, flat text* transcription of an audio file.

        NOTE: This helper populates the top-level 'text' field. It does
        NOT handle 'segments'. For timed transcriptions, build the
        dictionary and use the generic 'add_private_annotation' method.

        Args:
            text (str): The full, concatenated transcribed text.
            language (str): The 3-letter ISO-639-3 language
                code of the transcription (e.g., 'eng').
            track_id (str | int, optional): Identifier for the specific
                audio track or channel in the source file.
            source (str, optional): An optional string describing the source
                of the annotation (e.g., 'Whisper v3 (simple)').
                This will be passed to the 'detail' field.
            private (bool): Whether the annotation should be private.
            overwrite (bool): Whether to overwrite an existing annotation.
            api_key (str, optional): API key for validation.

        Returns:
            The LocalFile instance, for method chaining.

        Raises:
            ValueError: If the file is missing a 'validation_hash'.
        """
        from dorsal.file.helpers import build_transcription_record

        logger.debug(
            "Adding 'open/audio-transcription' (Language: %s, Length: %d) to file '%s'.",
            language,
            len(text),
            self._file_path,
        )

        record_data = build_transcription_record(
            language=language,
            text=text,
            track_id=track_id,
        )

        return self._add_annotation(
            schema_id="open/audio-transcription",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def add_regression(
        self,
        value: float | None,
        *,
        target: str | None = None,
        unit: str | None = None,
        producer: str | None = None,
        score_explanation: str | None = None,
        statistic: str | None = None,
        quantile_level: float | None = None,
        interval_lower: float | None = None,
        interval_upper: float | None = None,
        score: float | None = None,  #
        timestamp: str | datetime.datetime | None = None,
        attributes: dict[str, Any] | None = None,
        source: str | None = None,
        private: bool = True,
        overwrite: bool = False,
        api_key: str | None = None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> "LocalFile":
        """
        Adds an 'open/regression' annotation for a single point estimate.

        This helper creates a record containing a single data point.

        Use for scalar predictions (e.g. a price).

        For multi-point data (e.g. time-series, distributions), use `add_private_annotation` / `add_public_annotation` and
        construct the record manually with a list of points using `dorsal.file.helpers.build_regression_point`

        Args:
            value (float | None): The predicted or sampled value.
            target (str, optional): The name of the variable being predicted
                (e.g., 'house_price', 'credit_score').
            unit (str, optional): The unit of measurement (e.g., 'USD', 'kg').
            statistic (str, optional): The statistical nature of this value
                (e.g., 'mean', 'median', 'max', 'quantile').
            quantile_level (float, optional): If statistic='quantile', this defines
                the level (e.g., 0.95).
            interval_lower (float, optional): The lower bound of the confidence interval.
            interval_upper (float, optional): The upper bound of the confidence interval.
            timestamp (str | datetime, optional): The specific time this prediction applies to.
            source (str, optional): An optional string describing the source
                of the annotation (e.g., 'PricePredictor v1.0').
            private (bool): Whether the annotation should be private.
            overwrite (bool): Whether to overwrite an existing annotation.
            api_key (str, optional): API key for validation.

        Returns:
            The LocalFile instance, for method chaining.

        Examples:
            Simple Point Estimate:
            >>> lf.add_regression(target="sentiment", value=0.85, statistic="mean")

            Prediction with Confidence Interval:
            >>> lf.add_regression(
            ...     target="temperature",
            ...     value=22.5,
            ...     unit="celsius",
            ...     interval_lower=21.0,
            ...     interval_upper=24.0
            ... )

            Quantile Prediction:
            >>> lf.add_regression(
            ...     target="latency",
            ...     value=150,
            ...     unit="ms",
            ...     statistic="quantile",
            ...     quantile_level=0.99
            ... )
        """
        from dorsal.file.helpers import build_single_point_regression_record

        logger.debug(
            "Adding 'open/regression' (Target: %s, Value: %s) to file '%s'.",
            target,
            value,
            self._file_path,
        )

        record_data = build_single_point_regression_record(
            value=value,
            target=target,
            unit=unit,
            producer=producer,
            score_explanation=score_explanation,
            statistic=statistic,
            quantile_level=quantile_level,
            interval_lower=interval_lower,
            interval_upper=interval_upper,
            score=score,
            timestamp=timestamp,
            attributes=attributes,
        )

        return self._add_annotation(
            schema_id="open/regression",
            private=private,
            annotation_record=record_data,
            source_id=source,
            overwrite=overwrite,
            api_key=api_key,
            ignore_linter_errors=ignore_linter_errors,
            force=force,
        )

    def _get_local_info_dict(self) -> dict:
        """
        Gathers system-agnostic, local-only attributes into a dictionary
        by using os.stat to provide a more complete overview of the file's
        local state.

        Note: datetime objects are not converted to strings here to maintain
        consistency with other date fields in the LocalFile object.
        """
        local_info: dict[str, str | datetime.datetime | int] = {}
        try:
            stat_result = pathlib.Path(self._file_path).stat()

            local_info["date_modified"] = datetime.datetime.fromtimestamp(stat_result.st_mtime).astimezone()
            local_info["date_accessed"] = datetime.datetime.fromtimestamp(stat_result.st_atime).astimezone()

            if hasattr(stat_result, "st_birthtime"):  # type: ignore[attr-defined]
                local_info["date_created"] = datetime.datetime.fromtimestamp(
                    stat_result.st_birthtime  # type: ignore[attr-defined]
                ).astimezone()
            else:
                local_info["date_created"] = datetime.datetime.fromtimestamp(stat_result.st_ctime).astimezone()

            local_info["file_path"] = self._file_path
            local_info["file_size_bytes"] = stat_result.st_size
            local_info["file_permissions_mode"] = stat_result.st_mode
            local_info["inode"] = stat_result.st_ino
            local_info["number_of_links"] = stat_result.st_nlink

        except (FileNotFoundError, OSError) as e:
            logger.warning(f"Could not retrieve local file stats for {self._file_path}: {e}")
            local_info["error"] = f"Failed to retrieve local file info: {e}"

        return local_info

    def to_dict(
        self,
        by_alias=True,
        exclude_none=True,
        mode: Literal["python", "json"] = "python",
        exclude: dict | set | None = None,
    ) -> dict:
        """
        Overrides the parent method to include local file information.
        """
        base_dict = super().to_dict(
            by_alias=by_alias,
            exclude_none=exclude_none,
            mode=mode,
            exclude=exclude,
        )
        local_info = self._get_local_info_dict()
        base_dict["local_attributes"] = local_info
        return base_dict

    def to_json(
        self,
        indent: int | None = 2,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
    ) -> str:
        """Export the File Record to a JSON string."""
        output_dict = self.to_dict(
            by_alias=by_alias,
            exclude_none=exclude_none,
            mode="json",
            exclude=exclude,
        )

        return json.dumps(output_dict, indent=indent, default=str)

    def save(
        self,
        path: str | pathlib.Path,
        indent: int | None = 2,
        by_alias: bool = True,
        exclude_none: bool = True,
    ) -> None:
        """
        Exports the File Record to a JSON file on disk.

        Args:
            path: The file path to write to.
            indent: JSON indentation level.
            by_alias: Whether to use field aliases (required for correct schema loading).
            exclude_none: Whether to exclude fields with None values.

        Raises:
            IOError: If the file cannot be written.
        """
        output_path = pathlib.Path(path)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for export: {e}")
            raise IOError(f"Could not create directory for '{output_path}'") from e

        json_content = self.to_json(indent=indent, by_alias=by_alias, exclude_none=exclude_none)

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_content)
            logger.debug(f"Successfully saved LocalFile state to {output_path}")
        except IOError as e:
            logger.error(f"Failed to write JSON to {output_path}: {e}")
            raise
