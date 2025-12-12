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
import itertools
import logging
import uuid
from typing import Annotated, Any, Callable, Literal, Self, Type, Union

from pydantic import (
    AwareDatetime,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from dorsal.common.constants import ANNOTATION_MAX_SIZE_BYTES
from dorsal.common.exceptions import PydanticValidationError
from dorsal.common.model import (
    AnnotationSource,
)
from dorsal.file.utils.size import check_record_size
from dorsal.common.validators import DatasetID, Pagination, String256, TString255
from dorsal.file.validators.base import (
    FileCoreValidationModel,
    FileExtension,
    FILESIZE_UPPER_LIMIT,
    MediaTypeString,
)
from dorsal.file.validators.common import Blake3Hash, QuickHash, SHA256Hash, TLSHash
from dorsal.file.validators.mediainfo import MediaInfoValidationModel
from dorsal.file.validators.pdf import PDFValidationModel
from dorsal.file.validators.ebook import EbookValidationModel
from dorsal.file.validators.office_document import OfficeDocumentValidationModel


logger = logging.getLogger(__name__)


class GenericFileAnnotation(BaseModel):
    """A container for arbitrary annotation record data, allowing any fields.

    Used in `LocalFile._add_annotation` when the annotation being added is a dictionary.

    """

    model_config = ConfigDict(extra="allow")


class AnnotationGroupInfo(BaseModel):
    id: uuid.UUID = Field(description="ID linking all chunks of a split annotation.")
    index: int = Field(ge=0)
    total: int = Field(gt=1, description="Total number of chunks in the entire annotation.")


class Annotation(BaseModel):
    """Container for a single annotation record (e.g. `file/pdf`)

    Attributes:
    - `record` - e.g. `PDFValidationModel` - a single file annotation record
    - `source` - has attributes (e.g. `version`) relevant to production of `record`
    """

    record: GenericFileAnnotation | None
    private: bool = True
    source: AnnotationSource
    schema_version: str | None = None
    group: AnnotationGroupInfo | None = None

    @field_validator("record", mode="after")
    @classmethod
    def _validate_record_size(cls, record: GenericFileAnnotation | None) -> GenericFileAnnotation | None:
        """Enforces global annotation size limit."""
        if record is None:
            return None

        payload_size = check_record_size(record)

        if payload_size > ANNOTATION_MAX_SIZE_BYTES:
            raise ValueError(
                f"Annotation record size ({payload_size} bytes) exceeds the limit of "
                f"{ANNOTATION_MAX_SIZE_BYTES} bytes. Please ensure sharding is applied."
            )

        return record


class AnnotationXL(Annotation):
    """An Annotation variant that bypasses the size limit check.

    Used by `LocalFile.get_annotations`
    """

    @field_validator("record", mode="after")
    @classmethod
    def _validate_record_size(cls, record: GenericFileAnnotation | None) -> GenericFileAnnotation | None:
        return record


class ShardedAnnotation(Annotation):
    """A strict subset of Annotation that guarantees 'record' and 'group' are present."""

    record: GenericFileAnnotation
    group: AnnotationGroupInfo


class AnnotationGroup(BaseModel):
    """Container for multiple linked annotations. The order in the array is meaningful."""

    annotations: list[Annotation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _similarity_check(self) -> Self:
        private = self.annotations[0].private
        source = self.annotations[0].source
        schema_version = self.annotations[0].schema_version
        for ann in self.annotations[1:]:
            if ann.private != private:
                raise ValueError("Field `private` must be identical across all Annotation records")
            if ann.source != source:
                raise ValueError("Field `source` must be identical across all Annotation records")
            if ann.schema_version != schema_version:
                raise ValueError("Field `schema_version` must be identical across all Annotation records")

        return self

    @property
    def private(self) -> bool:
        return self.annotations[0].private

    @property
    def source(self) -> AnnotationSource:
        return self.annotations[0].source

    @property
    def schema_version(self) -> str | None:
        return self.annotations[0].schema_version


class Annotation_Base(Annotation):
    record: FileCoreValidationModel  # type: ignore[assignment]
    private: None = Field(default=None, exclude=True)  # type: ignore[assignment]


class Annotation_OfficeDocument(Annotation):
    record: OfficeDocumentValidationModel | None = None  # type: ignore[assignment]
    private: bool = True


class Annotation_MediaInfo(Annotation):
    record: MediaInfoValidationModel | None = None  # type: ignore[assignment]
    private: bool = True


class Annotation_PDF(Annotation):
    record: PDFValidationModel | None = None  # type: ignore[assignment]
    private: bool = True


class Annotation_Ebook(Annotation):
    record: EbookValidationModel | None = None  # type: ignore[assignment]
    private: bool = True


CORE_MODEL_ANNOTATION_WRAPPERS: dict[str, Type[Annotation]] = {
    "file/base": Annotation_Base,
    "file/ebook": Annotation_Ebook,
    "file/office": Annotation_OfficeDocument,
    "file/mediainfo": Annotation_MediaInfo,
    "file/pdf": Annotation_PDF,
}


class AnnotationStub(BaseModel):
    """
    Represents a lightweight, summary view of an annotation, typically
    returned in a fully hydrated FileRecord.
    """

    model_config = ConfigDict(populate_by_name=True)

    hash: SHA256Hash
    id: uuid.UUID
    source: AnnotationSource
    user_id: int = Field(validation_alias=AliasChoices("user_no", "user_id"))
    date_modified: AwareDatetime
    group: AnnotationGroupInfo | None = None


class Annotations(BaseModel):
    """
    File annotation container.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )

    file_base: Annotation_Base = Field(alias="file/base")
    file_ebook: Annotation_Ebook | None = Field(default=None, alias="file/ebook")
    file_mediainfo: Annotation_MediaInfo | None = Field(default=None, alias="file/mediainfo")
    file_office: Annotation_OfficeDocument | None = Field(default=None, alias="file/office")
    file_pdf: Annotation_PDF | None = Field(default=None, alias="file/pdf")

    @model_validator(mode="wrap")
    @classmethod
    def _validate_and_type_extras(cls, value: Any, handler: Callable[[Any], Self], info: ValidationInfo) -> Self:
        validated_instance = handler(value)
        current_extras = validated_instance.__pydantic_extra__

        if current_extras:
            for key in list(current_extras.keys()):
                extra_value = current_extras[key]
                parsed_value: Any = None

                try:
                    if isinstance(extra_value, dict):
                        if "annotations" in extra_value and isinstance(extra_value["annotations"], list):
                            parsed_value = AnnotationGroup.model_validate(extra_value)
                        elif "record" in extra_value:
                            parsed_value = Annotation.model_validate(extra_value)
                        else:
                            parsed_value = AnnotationStub.model_validate(extra_value)

                    elif isinstance(extra_value, list) and extra_value:
                        new_list: list[Annotation | AnnotationGroup | AnnotationStub] = []
                        for item in extra_value:
                            if isinstance(item, dict):
                                if "annotations" in item:
                                    new_list.append(AnnotationGroup.model_validate(item))

                                elif "record" in item:
                                    new_list.append(Annotation.model_validate(item))

                                else:
                                    new_list.append(AnnotationStub.model_validate(item))

                            elif isinstance(item, (Annotation, AnnotationGroup, AnnotationStub)):
                                new_list.append(item)
                            else:
                                raise ValueError(f"List item is not a valid Annotation type: {type(item)}")

                        parsed_value = new_list

                    else:
                        parsed_value = extra_value

                    setattr(validated_instance, key, parsed_value)
                    validated_instance.model_fields_set.add(key)

                except PydanticValidationError as err:
                    error_details = err.errors(include_url=False)
                    raise ValueError(
                        f"Annotation key '{key}' contains invalid data. "
                        f"Could not validate as Annotation, Group, or Stub. "
                        f"Details: {error_details}"
                    ) from err
                except Exception as err:
                    raise ValueError(
                        f"An unexpected error occurred while validating annotation key '{key}': {str(err)}"
                    ) from err
        return validated_instance


class FileTag(BaseModel):
    id: str | None = Field(pattern=r"^[0-9a-f]{24}$", default=None)  # bson.ObjectId string
    name: str = Field(pattern=r"^[a-zA-Z0-9\_]{3,64}$")
    value: str | bool | datetime.datetime | int | float
    value_code: str | None = None
    private: bool
    hidden: bool
    upvotes: NonNegativeInt
    downvotes: NonNegativeInt
    origin: Literal["dorsal.LocalFile", "DorsalHub"] = "DorsalHub"


class NewFileTag(FileTag):
    hidden: Literal[False] = False
    upvotes: Literal[0] = 0
    downvotes: Literal[0] = 0
    origin: Literal["dorsal.LocalFile"] = "dorsal.LocalFile"


class ValidTag(BaseModel):
    name: str
    value: Any


class ValidateTagsResult(BaseModel):
    valid: bool
    message: str | None = None
    tags: list[ValidTag] = Field(default_factory=list)


class TagResult(BaseModel):
    name: str
    namespace: str
    value: Any
    value_code: Any | None = None
    private: bool
    status: Literal["added", "no-action", "upvoted"]
    detail: str | None = None


DeletionScope = Literal["all", "public", "private", "none"]


class FileRecord(BaseModel):
    """File annotation record.

    Optionally includes validation hash.

    """

    hash: SHA256Hash
    validation_hash: Blake3Hash | None = None
    quick_hash: QuickHash | None = None
    similarity_hash: TLSHash | None = None
    annotations: Annotations | None = None
    tags: list[FileTag] = Field(default_factory=list)

    def _validate_or_populate_hash_field(
        self, *, field_name: str, source_value: str | None, source_name_for_error: str
    ):
        if source_value is None:
            return

        current_value = getattr(self, field_name)
        if current_value is None:
            setattr(self, field_name, source_value)
        elif current_value != source_value:
            raise ValueError(
                f"Data integrity error: Top-level '{field_name}' ('{current_value}') "
                f"does not match the source '{source_name_for_error}' value "
                f"('{source_value}') from 'file/base'."
            )

    @model_validator(mode="after")
    def _populate_and_validate_hashes_from_base(self) -> Self:
        """
        - Populates the top-level `quick_hash`, `similarity_hash` and `validation_hash` fields, when available in `file/base`.
        - Validates and enforces hash consistency between the top-level hash fields and 'file/base'.
        """
        if not self.annotations or not self.annotations.file_base:
            return self

        core_validation_model = self.annotations.file_base.record

        if self.hash != core_validation_model.hash:
            raise ValueError(
                "Data integrity error: Top-level 'hash' does not match the 'hash' "
                f"in the 'file/base' annotation record ('{self.hash}' vs '{core_validation_model.hash}')."
            )

        self._validate_or_populate_hash_field(
            field_name="quick_hash",
            source_value=core_validation_model.quick_hash,
            source_name_for_error="QUICK",
        )
        self._validate_or_populate_hash_field(
            field_name="similarity_hash",
            source_value=core_validation_model.similarity_hash,
            source_name_for_error="TLSH",
        )
        self._validate_or_populate_hash_field(
            field_name="validation_hash",
            source_value=(
                core_validation_model.all_hash_ids.get("BLAKE3") if core_validation_model.all_hash_ids else None
            ),
            source_name_for_error="BLAKE3",
        )
        return self

    @model_validator(mode="after")
    def _identical_hash_check(self) -> Self:
        """
        Ensures no two identical hashes are populated.
        """
        hash_fields = [
            self.hash,
            self.validation_hash,
            self.quick_hash,
            self.similarity_hash,
        ]
        hashes = [h for h in hash_fields if h is not None]

        if len(set(hashes)) == len(hashes):
            return self

        field_names = ["hash", "validation_hash", "quick_hash", "similarity_hash"]
        for field1, field2 in itertools.combinations(field_names, 2):
            hash1 = getattr(self, field1, None)
            hash2 = getattr(self, field2, None)

            if hash1 is not None and hash1 == hash2:
                raise ValueError(
                    f"Inconsistent hash values: '{field1}' and '{field2}' are "
                    f"unexpectedly identical (value: '{hash1}')."
                )

        raise ValueError("Inconsistent hash values: A duplicate was detected but could not be located.")


class FileRecordStrict(FileRecord):
    """File annotation record, including validation hash.

    - Used for indexing new files and their metadata (including structured records and/or tags)
    - This format is generated locally by a ModelRunner instance, it is not provided by the DorsalHub API.

    Used in:

    - `POST /file/public|private`
    """

    validation_hash: Blake3Hash
    annotations: Annotations
    source: Literal["disk", "cache", "dorsalhub"]


class FileRecordDateTime(FileRecord):
    """A `FileRecord` with dates in the root level.

    - This format is returned by the DorsalHub API

    """

    all_hashes: None = Field(default=None, exclude=True)
    all_hash_ids: None = Field(default=None, exclude=True)
    date_created: AwareDatetime
    date_modified: AwareDatetime


class FileRecordLite(BaseModel):
    """Flat file record, with no secure hashes."""

    quick_hash: SHA256Hash
    name: TString255
    extension: FileExtension | None = None
    size: int = Field(ge=0, lt=FILESIZE_UPPER_LIMIT)
    media_type: MediaTypeString

    annotations: Annotations | None = None
    tags: list[FileTag] = Field(default_factory=list)


class FileRecordSuperLite(BaseModel):
    """Flat file record, with no hashes.

    Used in cli/stats

    Note: for compatability with the rest of the pipeline, uuid4 is generated on the fly
    """

    hash: str
    name: TString255
    extension: FileExtension | None = None
    size: int = Field(ge=0, lt=FILESIZE_UPPER_LIMIT)
    media_type: MediaTypeString

    annotations: Annotations | None = None
    tags: list[FileTag] = Field(default_factory=list)


class AnnotationData(BaseModel):
    schema_id: DatasetID
    annotation: Annotation | None
    error: str | None = None


class UserFileSearchQuery(BaseModel):
    """
    Query object for searching user files.
    This model is designed to be used with FastAPI for request body validation.
    """

    text: str | None = None
    field: dict[str, list[str]] | None = Field(
        default=None,
        description="Key-value pairs for field-based filtering. e.g. {'extension': ['.pdf', '.docx']}",
    )
    not_filters: dict[str, list[str]] | None = Field(
        default=None,
        alias="not",
        description="Key-value pairs to exclude from results.",
    )
    from_date: datetime.datetime | None = None
    to_date: datetime.datetime | None = None
    date_field: str = Field(
        default="date_modified",
        description="The date field to use for range filtering.",
    )


class UserFileRead(BaseModel):
    """User file record, for API response."""

    hash_: str = Field(alias="hash")
    user_id: int
    name: str
    extension: str | None
    size: int
    media_type: str
    private: bool
    first_indexed: datetime.datetime
    last_indexed: datetime.datetime


class FileSearchResponse(BaseModel):
    results: list[FileRecordDateTime]
    errors: list[str]
    pagination: Pagination
    api_version: str
