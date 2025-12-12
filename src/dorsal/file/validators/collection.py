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

import datetime

from pydantic import BaseModel, Field, HttpUrl

from dorsal.common.validators import Pagination
from dorsal.file.validators.file_record import FileRecordDateTime
from dorsal.common.validators.strings import String1024, String256


class FileCollectionSource(BaseModel):
    caller: str
    local_directory: str | None = None
    comment: str | None = None


class FileCollection(BaseModel):
    """Represents the core metadata of a collection in the new architecture."""

    collection_id: str
    user_no: int
    is_private: bool
    name: String256
    description: str | None = Field(default=None, max_length=1024)
    icon: str | None = Field(default=None, max_length=1024)
    file_count: int = Field(alias="total_files")
    total_size: int = Field(alias="total_size_bytes")
    source: FileCollectionSource
    private_url: HttpUrl | None = None
    public_url: HttpUrl | None = None
    date_created: datetime.datetime | None = None
    date_modified: datetime.datetime | None = None


class FileRecordInCollection(BaseModel):
    hash: str = Field(description="The primary SHA-256 hash of the file.")
    name: str
    extension: str | None = None
    size: int
    media_type: str
    date_created: datetime.datetime
    date_modified: datetime.datetime


class SingleCollectionResponse(BaseModel):
    """
    A dedicated response model for a single collection request, ensuring
    pagination for the file list is explicit and consistent.
    """

    collection: FileCollection
    files: list[FileRecordInCollection]
    pagination: Pagination


class HydratedSingleCollectionResponse(BaseModel):
    collection: FileCollection
    files: list[FileRecordDateTime]
    pagination: Pagination


class BulkDetailsRequest(BaseModel):
    hash_strings: list[str] = Field(..., min_length=1)
    private: bool = Field(
        False,
        description="Specifies whether to look for the hashes in public (False) or private (True) file records.",
    )
