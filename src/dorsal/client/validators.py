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
from typing import Any, Literal
import requests
from pydantic import BaseModel, Field, NonNegativeInt, computed_field
from dorsal.file.validators.file_record import AnnotationGroup, FileRecordDateTime
from dorsal.file.validators.collection import (
    FileCollection,
    SingleCollectionResponse,
    HydratedSingleCollectionResponse,
)
from dorsal.common.validators import Pagination


class TagResult(BaseModel):
    name: str
    namespace: str
    value: Any
    value_code: Any | None = None
    private: bool
    status: str
    detail: str | None = None


class IndexResultAnnotation(BaseModel):
    name: str
    status: str
    detail: str | None = None


class IndexResult(BaseModel):
    file_path: str | None = None
    name: str | None = None
    hash: str
    url: str
    annotations: list[IndexResultAnnotation]
    tags: list[TagResult] | None = None


class FileIndexResponse(BaseModel):
    total: int
    success: int
    error: int
    unauthorized: int
    tag_status: str | None = None
    results: list[IndexResult]
    response: requests.Response | None = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}


class NewDatasetResponse(BaseModel):
    created: str
    version: str
    url: str


class FileTagResponse(BaseModel):
    hash: str
    success: bool
    detail: str | None = None
    tags: list[TagResult] | None = None


class RecordIndexResultItem(BaseModel):
    key: str
    status: str
    url: str | None
    detail: str | None


class RecordIndexResult(BaseModel):
    total: int
    success: int
    error: int
    warnings: list[str] | None
    dataset_id: str
    results: list[RecordIndexResultItem]


class FileDeleteResponse(BaseModel):
    file_exists: NonNegativeInt | None = None
    file_deleted: NonNegativeInt = 0
    file_modified: NonNegativeInt = 0
    tags_exist: NonNegativeInt | None = None
    tags_deleted: NonNegativeInt = 0
    private_tags_deleted: int = 0
    annotations_exist: NonNegativeInt | None = None
    annotations_modified: NonNegativeInt = 0
    annotations_deleted: NonNegativeInt = 0
    private_annotations_deleted: int = 0
    user_file_exist: NonNegativeInt | None = None
    user_files_deleted: NonNegativeInt = 0


class CollectionCreateRequest(BaseModel):
    """For creating a new file collection."""

    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(None, max_length=1024)
    is_private: bool = True
    source: dict[str, Any]


class AddFilesRequest(BaseModel):
    """For adding files to a collection."""

    hashes: list[str] = Field(
        description="A list of file SHA-256 hashes to add to the collection.",
        max_length=10_000,
    )


class AddFilesResponse(BaseModel):
    added_count: int
    duplicate_count: int
    invalid_count: int


class CollectionsResponse(BaseModel):
    """For a paginated list of file collections."""

    records: list[FileCollection]
    pagination: Pagination


class CollectionUpdateRequest(BaseModel):
    """For updating a collection's properties."""

    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = Field(None, max_length=1024)


class CollectionsDeleteRequest(BaseModel):
    """For deleting one or more collections."""

    collection_ids: list[str] = Field(..., min_length=1)


class CollectionWebLocationResponse(BaseModel):
    location_url: str


class ExportJobStatus(BaseModel):
    job_id: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN"]
    message: str | None = None
    progress: float = Field(default=0.0)
    download_url: str | None = None
    expires_at: datetime.datetime | None = None


class ExportJobRequest(BaseModel):
    format: Literal["json.gz"] = "json.gz"


class RemoveFilesRequest(BaseModel):
    hashes: list[str] = Field(
        description="A list of file SHA-256 hashes to remove from the collection.",
        max_length=10_000,
    )


class RemoveFilesResponse(BaseModel):
    removed_count: int = Field(description="The number of files successfully removed from the collection.")
    not_found_count: int = Field(description="The number of provided hashes that were not found in the collection.")


class CollectionSyncRequest(BaseModel):
    hashes: list[str] = Field(
        description="The complete list of file SHA-256 hashes the collection should contain.",
        max_length=1_000_000,
    )


class CollectionSyncResponse(BaseModel):
    added_count: int = Field(description="The number of new files added to the collection.")
    removed_count: int = Field(description="The number of files removed from the collection.")
    unchanged_count: int = Field(
        description="The number of files that were already in the collection and were not changed."
    )


class CollectionSyncJob(BaseModel):
    job_id: str = Field(description="The unique ID for the synchronization job.")
    status: str = Field(description="The initial status of the job (e.g., PENDING).")


class CollectionSyncJobStatus(CollectionSyncJob):
    result: CollectionSyncResponse | None = Field(
        default=None,
        description="The final result of the sync, available when the job is complete.",
    )
    error: str | None = Field(default=None, description="An error message if the job failed.")


class AnnotationIndexResultItem(BaseModel):
    key: str
    annotation_id: str | None
    private: bool
    status: Literal["created", "updated", "skipped", "error"]
    detail: str | None = None


class AnnotationIndexResult(BaseModel):
    """For adding or updating file annotations."""

    total: int
    success: int
    error: int
    dataset_id: str
    results: list[AnnotationIndexResultItem]


class FileAnnotationResponse(BaseModel):
    annotation_id: str
    file_hash: str
    schema_id: str
    schema_version: str | None = None
    source: dict[str, Any]
    record: dict[str, Any]
    user_id: int
    date_created: datetime.datetime
    date_modified: datetime.datetime
    private: bool


class FileAnnotationGroupResponse(BaseModel):
    annotation_id: str
    file_hash: str
    schema_id: str
    schema_version: str | None = None
    source: dict[str, Any]
    group: AnnotationGroup
    user_id: int
    date_created: datetime.datetime
    date_modified: datetime.datetime
    private: bool
