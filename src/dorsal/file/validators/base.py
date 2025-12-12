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
import re
from typing import Annotated, Any, Self
import uuid

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from dorsal.common.validators import TString255
from dorsal.file.validators.common import QuickHash, SHA256Hash, TLSHash
from dorsal.file.utils.hashes import hash_string_validator, HashFunctionId

logger = logging.getLogger(__name__)

FILESIZE_UPPER_LIMIT = 2**50  # 1 Petabyte

RX_FILE_EXTENSION = re.compile(r"^\.[a-zA-Z0-9_!-]{1,16}$")

MediaTypeString = Annotated[str, Field(pattern=r"^\w+\/[-+.\w]+$", min_length=3, max_length=256)]
MediaTypePartString = Annotated[
    str, Field(pattern=r"^(?:\w+\/[-+.\w]+|\w+)$", min_length=3, max_length=256)
]  # `video/png` or just `video`


def validate_file_extension_or_null(value: Any) -> str | None:
    """Convert input to a lowercase string if it matches RX_FILE_EXTENSION.

    Return `None` for empty or unmatchings strings, or `None`

    """
    if value is None:
        return None

    try:
        str_value = str(value)

        if not str_value:
            return None

        if RX_FILE_EXTENSION.match(str_value):
            return str_value.lower()
        else:
            logger.debug(
                "File extension '%s' (original: '%s') does not match regex. Returning None.",
                str_value,
                value,
            )
            return None

    except (TypeError, AttributeError) as e:
        logger.debug(
            "Failed to process value for file extension validation (value: '%s', type: %s). Error: %s. Returning None.",
            value,
            type(value).__name__,
            e,
        )
        return None


FileExtension = Annotated[str | None, BeforeValidator(validate_file_extension_or_null)]


class FileCoreValidationModelHash(BaseModel):
    """
    Represents a single hash record with its type identifier and value.
    Validates the hash value against its specified type.
    """

    id: HashFunctionId
    value: str

    @field_validator("value")
    @classmethod
    def validate_hash_value_format_and_normalize_case(cls, value: str, info: ValidationInfo) -> str:
        """
        Validates the hash string's format based on the 'id' (hash function).
        Normalizes the case of the hash string (e.g., TLSH to uppercase, others to lowercase).
        Raises ValueError if the hash function is unsupported or the hash value is invalid.
        """
        hash_function_id = info.data.get("id")
        if not hash_function_id:
            raise ValueError("Hash function 'id' is missing, cannot validate hash value.")  # pragma: no cover

        if not hash_string_validator.is_supported_hash_function(hash_function_id):
            raise ValueError(f"Hash function '{hash_function_id}' is not currently supported.")

        normalized_hash = hash_string_validator.get_valid_hash(candidate_string=value, hash_function=hash_function_id)
        if normalized_hash is None:
            raise ValueError(f"Value '{value}' is not a valid hash for function '{hash_function_id}'.")
        return normalized_hash


class FileCoreValidationModel(BaseModel):
    """
    Base Pydantic model for validating the core metadata extracted by `FileCoreAnnotationModel`.
    This record forms the foundational data about a file.
    """

    hash: SHA256Hash
    quick_hash: QuickHash | None = None
    similarity_hash: TLSHash | None = None
    name: TString255
    extension: FileExtension | None = None
    size: int = Field(ge=0, lt=FILESIZE_UPPER_LIMIT)
    media_type: MediaTypeString

    all_hashes: list[FileCoreValidationModelHash] | None = Field(default=None, min_length=2)

    all_hash_ids: dict[HashFunctionId, str] | None = Field(default=None)

    @computed_field  # type: ignore
    @property
    def media_type_prefix(self) -> str:
        return self.media_type.split("/")[0]

    @model_validator(mode="after")
    def populate_and_validate_all_hash_ids(self) -> Self:
        """
        Populates `all_hash_ids`, overwrites top-level hashes, and performs validation checks:
        - Populates `all_hash_ids` from `all_hashes`.
        - Overwrites `quick_hash` and `similarity_hash` from `all_hashes`.
        - Ensures SHA256 and BLAKE3 hashes are present.
        - Verifies no duplicate hash IDs.
        - Confirms the primary `self.hash` matches the SHA256 value in `all_hashes`.
        """
        if self.all_hashes is not None:
            temp_all_hash_ids: dict[HashFunctionId, str] = {}
            for hash_record in self.all_hashes:
                if hash_record.id in temp_all_hash_ids:
                    raise ValueError(f"Duplicate hash ID '{hash_record.id}' found in record.all_hashes.")
                temp_all_hash_ids[hash_record.id] = hash_record.value
            self.all_hash_ids = temp_all_hash_ids

            if "QUICK" in self.all_hash_ids:
                self.quick_hash = self.all_hash_ids["QUICK"]

            if "TLSH" in self.all_hash_ids:
                self.similarity_hash = self.all_hash_ids["TLSH"]

            if len(set(self.all_hash_ids.values())) < len(self.all_hash_ids):
                logger.warning(
                    "Potential issue: Identical hash values found for different hash IDs in all_hashes. Record hash: %s",
                    self.hash,
                )

            if "SHA-256" not in self.all_hash_ids:
                raise ValueError("SHA-256 file hash missing from record.all_hashes.")
            if "BLAKE3" not in self.all_hash_ids:
                raise ValueError("BLAKE3 file hash missing from record.all_hashes.")
            if self.hash != self.all_hash_ids["SHA-256"]:
                raise ValueError("Record 'hash' (primary SHA256) does not match SHA-256 value in record.all_hashes.")
        return self


class FileCoreValidationModelLite(FileCoreValidationModel):
    """Pydantic model for validating the stripped-down output of `FileCoreValidationModel`.

    This record contains only an insecure QUICK hash, and is not suitable for indexing.
    """

    quick_hash: QuickHash
    hash: None = Field(default=None, exclude=True)  # type: ignore[assignment]
    similarity_hash: None = Field(default=None, exclude=True)


class FileCoreValidationModelSuperLite(FileCoreValidationModel):
    """Pydantic model for validating the stripped-down output of `FileCoreValidationModel`.

    This record contains only an insecure QUICK hash, and is not suitable for indexing.
    """

    quick_hash: None = Field(default=None, exclude=True)
    hash: str = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[assignment]
    similarity_hash: None = Field(default=None, exclude=True)


class FileCoreValidationModelStrict(FileCoreValidationModel):
    """
    A validated `FileCoreValidationModel` - i.e. contains 'BLAKE3' validation hash within `all_hashes`.
    """

    all_hashes: list[FileCoreValidationModelHash] = Field(min_length=2)
