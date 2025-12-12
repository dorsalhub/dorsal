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

import copy
import pytest
import sys
from unittest.mock import patch, mock_open, MagicMock
from dorsal.client import DorsalClient
from dorsal.common.exceptions import (
    DorsalClientError,
    NotFoundError,
    ForbiddenError,
    ConflictError,
    ApiDataValidationError,
    APIError,
)
from dorsal.file.validators.collection import FileCollection, SingleCollectionResponse, HydratedSingleCollectionResponse
from dorsal.client.validators import (
    AddFilesResponse,
    RemoveFilesResponse,
    CollectionsResponse,
    CollectionWebLocationResponse,
    ExportJobStatus,
    CollectionSyncResponse,
)

# Constants
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64
_COLLECTION_ID = "col_123"


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


@pytest.fixture
def mock_pagination_json():
    return {
        "page": 1,
        "per_page": 50,
        "total_items": 1,
        "total_pages": 1,
        "current_page": 1,
        "record_count": 1,
        "page_count": 1,
        "has_next": False,
        "has_prev": False,
        "start_index": 0,
        "end_index": 0,
    }


@pytest.fixture
def mock_collection_response_json(mock_pagination_json):
    """Provides a valid JSON response for a single, non-hydrated collection."""
    return {
        "collection": {
            "collection_id": _COLLECTION_ID,
            "user_no": 1,
            "is_private": True,
            "name": "Test Collection",
            "description": "A test collection.",
            "icon": None,
            "total_files": 1,
            "total_size_bytes": 1024,
            "source": {"caller": "script"},
            "private_url": f"{_DUMMY_BASE_URL}/c/{_COLLECTION_ID}",
            "public_url": None,
            "date_created": "2025-08-07T14:30:00Z",
            "date_modified": "2025-08-07T14:30:00Z",
        },
        "files": [
            {
                "hash": _DUMMY_SHA256,
                "name": "file1.txt",
                "extension": ".txt",
                "size": 1024,
                "media_type": "text/plain",
                "date_created": "2025-08-07T14:30:00Z",
                "date_modified": "2025-08-07T14:30:00Z",
            }
        ],
        "pagination": mock_pagination_json,
    }


# --- CRUD Operations ---


def test_create_collection_success(client, requests_mock):
    """Test successful creation of a new collection."""
    mock_response = {
        "collection_id": _COLLECTION_ID,
        "user_no": 1,
        "is_private": True,
        "name": "My New Collection",
        "description": "A test collection.",
        "icon": None,
        "total_files": 0,
        "total_size_bytes": 0,
        "source": {"caller": "unit_test", "local_directory": "/tmp/test"},
        "private_url": f"{_DUMMY_BASE_URL}/c/{_COLLECTION_ID}",
        "public_url": None,
        "date_created": "2025-08-07T14:30:00Z",
        "date_modified": "2025-08-07T14:30:00Z",
    }
    requests_mock.post(f"{_DUMMY_BASE_URL}/v1/collections", json=mock_response, status_code=201)

    result = client.create_collection(
        name="My New Collection",
        is_private=True,
        source={"type": "script", "name": "unit_test"},
        description="A test collection.",
    )

    assert isinstance(result, FileCollection)
    assert result.collection_id == _COLLECTION_ID
    assert result.file_count == 0


def test_get_collection_success(client, requests_mock, mock_collection_response_json):
    """Test successfully fetching a non-hydrated collection."""
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}",
        json=mock_collection_response_json,
    )

    result = client.get_collection(_COLLECTION_ID, hydrate=False)

    assert isinstance(result, SingleCollectionResponse)
    assert result.collection.collection_id == _COLLECTION_ID
    assert len(result.files) == 1
    assert result.files[0].name == "file1.txt"


def test_get_collection_hydrated(client, requests_mock, mock_collection_response_json):
    """Test successfully fetching a hydrated collection."""
    # We reuse the same mock JSON, but the client will parse it into a different model
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}?page=1&per_page=100&hydrate=True",
        json=mock_collection_response_json,
    )

    result = client.get_collection(_COLLECTION_ID, hydrate=True)

    assert isinstance(result, HydratedSingleCollectionResponse)
    assert result.collection.collection_id == _COLLECTION_ID


def test_get_collection_not_found(client, requests_mock):
    """Test that a 404 on get_collection raises NotFoundError."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/collections/col_404", status_code=404)

    with pytest.raises(NotFoundError):
        client.get_collection("col_404")


def test_list_collections_success(client, requests_mock, mock_collection_response_json, mock_pagination_json):
    """Test successfully listing collections."""
    mock_response = {
        "records": [mock_collection_response_json["collection"]],
        "pagination": mock_pagination_json,
    }
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/collections", json=mock_response)

    result = client.list_collections()

    assert isinstance(result, CollectionsResponse)
    assert len(result.records) == 1
    assert isinstance(result.records[0], FileCollection)
    assert result.records[0].name == "Test Collection"


def test_update_collection_success(client, requests_mock, mock_collection_response_json):
    """Test successfully updating a collection's name."""
    updated_name = "An Updated Name"
    mock_response = copy.deepcopy(mock_collection_response_json["collection"])
    mock_response["name"] = updated_name

    requests_mock.patch(f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}", json=mock_response)

    result = client.update_collection(collection_id=_COLLECTION_ID, name=updated_name)

    assert isinstance(result, FileCollection)
    assert result.name == updated_name


def test_update_collection_no_fields_error(client):
    """Test that calling update without any fields raises a client error."""
    with pytest.raises(DorsalClientError, match="at least one field"):
        client.update_collection(collection_id=_COLLECTION_ID)


def test_delete_collections_success(client, requests_mock):
    """Test successful deletion of multiple collections."""
    collection_ids = ["col_123", "col_456"]
    requests_mock.delete(f"{_DUMMY_BASE_URL}/v1/collections", status_code=204)

    result = client.delete_collections(collection_ids=collection_ids)
    assert result is None


def test_delete_collections_api_error(client, requests_mock):
    """Test that a 403 Forbidden error is handled during deletion."""
    requests_mock.delete(f"{_DUMMY_BASE_URL}/v1/collections", status_code=403)

    with pytest.raises(ForbiddenError):
        client.delete_collections(collection_ids=[_COLLECTION_ID])


# --- File Management in Collections ---


def test_add_files_to_collection_success(client, requests_mock):
    """Test successfully adding files to a collection."""
    mock_response = {"added_count": 1, "duplicate_count": 0, "invalid_count": 0}
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/files",
        json=mock_response,
    )

    result = client.add_files_to_collection(_COLLECTION_ID, [_DUMMY_SHA256])

    assert isinstance(result, AddFilesResponse)
    assert result.added_count == 1


def test_remove_files_from_collection_success(client, requests_mock):
    """Test successfully removing files from a collection."""
    mock_response = {"removed_count": 1, "not_found_count": 0}
    requests_mock.delete(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/files",
        json=mock_response,
    )

    result = client.remove_files_from_collection(_COLLECTION_ID, [_DUMMY_SHA256])

    assert isinstance(result, RemoveFilesResponse)
    assert result.removed_count == 1


# --- Visibility Actions ---


def test_make_collection_public_success(client, requests_mock, mock_collection_response_json):
    """Test successfully making a private collection public."""
    # Ensure initial state is private
    mock_collection_response_json["collection"]["is_private"] = True

    # 1. Mock pre-flight check
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}",
        json=mock_collection_response_json,
    )

    # 2. Mock action POST
    mock_action_response = {"location_url": f"{_DUMMY_BASE_URL}/collections/public/{_COLLECTION_ID}"}
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/actions/make-public",
        json=mock_action_response,
        status_code=201,
    )

    result = client.make_collection_public(_COLLECTION_ID)
    assert isinstance(result, CollectionWebLocationResponse)
    assert result.location_url == mock_action_response["location_url"]


def test_make_collection_public_conflict(client, requests_mock, mock_collection_response_json):
    """Test that trying to make an already public collection public raises ConflictError."""
    mock_collection_response_json["collection"]["is_private"] = False
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}",
        json=mock_collection_response_json,
    )

    with pytest.raises(ConflictError, match="is already public"):
        client.make_collection_public(_COLLECTION_ID)


def test_make_collection_private_success(client, requests_mock, mock_collection_response_json):
    """Test successfully making a public collection private."""
    mock_collection_response_json["collection"]["is_private"] = False

    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}",
        json=mock_collection_response_json,
    )

    mock_action_response = {"location_url": f"{_DUMMY_BASE_URL}/c/{_COLLECTION_ID}"}
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/actions/make-private",
        json=mock_action_response,
        status_code=201,
    )

    result = client.make_collection_private(_COLLECTION_ID)
    assert isinstance(result, CollectionWebLocationResponse)


# --- Export Operations ---


def test_start_collection_export_success(client, requests_mock):
    """Test successfully starting a collection export job."""
    mock_response = {
        "job_id": "job_xyz",
        "status": "PENDING",
        "message": "Job has been queued.",
    }
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/export/collection/{_COLLECTION_ID}",
        json=mock_response,
        status_code=202,
    )

    result = client.start_collection_export(_COLLECTION_ID)
    assert isinstance(result, ExportJobStatus)
    assert result.job_id == "job_xyz"


def test_get_export_job_status_success(client, requests_mock):
    """Test successfully polling for an export job's status."""
    job_id = "job_xyz"
    mock_response = {
        "job_id": job_id,
        "status": "COMPLETED",
        "progress": 100.0,
        "download_url": f"{_DUMMY_BASE_URL}/downloads/export.json.gz",
    }
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/export/jobs/{job_id}", json=mock_response)

    result = client.get_export_job_status(job_id)
    assert result.status == "COMPLETED"


@patch("os.makedirs")
@patch("builtins.open", new_callable=mock_open)
def test_download_completed_export_success(mock_open_file, mock_makedirs, client, requests_mock):
    """Test downloading the file from a completed job status object."""
    download_url = f"{_DUMMY_BASE_URL}/downloads/export.json.gz"
    job_status = ExportJobStatus(job_id="job_xyz", status="COMPLETED", download_url=download_url)
    output_path = "/tmp/my_export.json.gz"

    requests_mock.get(download_url, content=b"file-content")

    client.download_completed_export(job_status, output_path)

    mock_makedirs.assert_called_once()
    mock_open_file.assert_called_once_with(output_path, "wb")
    mock_open_file().write.assert_called_once_with(b"file-content")


def test_download_completed_export_job_not_complete(client):
    """Test that trying to download from a non-completed job raises an error."""
    job_status = ExportJobStatus(job_id="job_xyz", status="RUNNING")
    with pytest.raises(DorsalClientError, match="Job is not complete"):
        client.download_completed_export(job_status, "/tmp/file.gz")


@patch("os.makedirs")
@patch("builtins.open", new_callable=mock_open)
def test_export_collection_orchestrator_success(mock_open_file, mock_makedirs, client, requests_mock):
    """Test the full export_collection method (HEADLESS MODE)."""
    job_id = "job_xyz"
    download_url = f"{_DUMMY_BASE_URL}/downloads/export.json.gz"
    output_path = "/tmp/final_export.json.gz"

    # 1. Start
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/export/collection/{_COLLECTION_ID}",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )

    # 2. Poll (RUNNING -> COMPLETED)
    status_url = f"{_DUMMY_BASE_URL}/v1/export/jobs/{job_id}"
    requests_mock.get(
        status_url,
        [
            {"json": {"job_id": job_id, "status": "RUNNING", "progress": 50.0}, "status_code": 200},
            {
                "json": {"job_id": job_id, "status": "COMPLETED", "progress": 100.0, "download_url": download_url},
                "status_code": 200,
            },
        ],
    )

    # 3. Download
    requests_mock.get(download_url, content=b"data")

    client.export_collection(_COLLECTION_ID, output_path, poll_interval=0.01)

    mock_open_file.assert_called_once_with(output_path, "wb")


@patch("os.makedirs")
@patch("builtins.open", new_callable=mock_open)
def test_export_collection_with_console(mock_open_file, mock_makedirs, client, requests_mock):
    """Test the export_collection method with a Rich Console (UI MODE)."""
    job_id = "job_console"
    download_url = f"{_DUMMY_BASE_URL}/downloads/export.json.gz"
    output_path = "/tmp/console_export.json.gz"

    # Mock API flows
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/export/collection/{_COLLECTION_ID}",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/export/jobs/{job_id}",
        json={"job_id": job_id, "status": "COMPLETED", "progress": 100.0, "download_url": download_url},
        status_code=200,
    )
    requests_mock.get(download_url, content=b"data")

    # Mock the console object
    mock_console = MagicMock()

    # We must patch 'rich.live.Live' and 'rich.progress.Progress' as they are imported
    # inside the function in dorsal_client.py.
    with (
        patch("rich.live.Live") as mock_live,
        patch("rich.progress.Progress") as mock_progress,
        patch("dorsal.cli.themes.palettes.DEFAULT_PALETTE", {}),
    ):
        client.export_collection(_COLLECTION_ID, output_path, console=mock_console, poll_interval=0.01)

        # Verify Rich components were initialized
        assert mock_live.called
        assert mock_progress.called
        mock_open_file.assert_called_once_with(output_path, "wb")


@patch("os.makedirs")
@patch("builtins.open", new_callable=mock_open)
@patch("dorsal.client.dorsal_client.is_jupyter_environment", return_value=True)
@patch("dorsal.client.dorsal_client.tqdm")
def test_export_collection_jupyter(mock_tqdm, mock_is_jupyter, mock_open_file, mock_makedirs, client, requests_mock):
    """Test the export_collection method in a JUPYTER environment."""
    job_id = "job_jupyter"
    download_url = f"{_DUMMY_BASE_URL}/downloads/export.json.gz"
    output_path = "/tmp/jupyter_export.json.gz"

    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/export/collection/{_COLLECTION_ID}",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/export/jobs/{job_id}",
        json={"job_id": job_id, "status": "COMPLETED", "progress": 100.0, "download_url": download_url},
        status_code=200,
    )
    requests_mock.get(download_url, content=b"data")

    client.export_collection(_COLLECTION_ID, output_path, poll_interval=0.01)

    # Verify tqdm was used (context manager enter/exit)
    assert mock_tqdm.called
    mock_tqdm.return_value.__enter__.return_value.refresh.assert_called()


def test_export_collection_timeout(client, requests_mock):
    """Test that export_collection raises a timeout error if the job takes too long."""
    job_id = "job_timeout"
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/export/collection/{_COLLECTION_ID}",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )

    # Job stays RUNNING forever
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/export/jobs/{job_id}",
        json={"job_id": job_id, "status": "RUNNING", "progress": 10.0},
        status_code=200,
    )

    # Set a very short timeout
    with pytest.raises(DorsalClientError, match="did not complete within"):
        client.export_collection(_COLLECTION_ID, "/tmp/out.gz", poll_interval=0.1, timeout=0.05)


# --- Sync Operations ---


def test_sync_collection_by_hash_success(client, requests_mock):
    """Test the full sync_collection_by_hash method orchestrates calls correctly."""
    job_id = "sync_abc"
    hashes = [_DUMMY_SHA256]

    # 1. Start
    start_url = f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/sync"
    requests_mock.post(start_url, json={"job_id": job_id, "status": "PENDING"}, status_code=202)

    # 2. Poll
    status_url = f"{_DUMMY_BASE_URL}/v1/collections/sync-jobs/{job_id}"
    requests_mock.get(
        status_url,
        [
            {"json": {"job_id": job_id, "status": "RUNNING", "result": None, "error": None}, "status_code": 200},
            {
                "json": {
                    "job_id": job_id,
                    "status": "SUCCESS",
                    "result": {"added_count": 10, "removed_count": 5, "unchanged_count": 90},
                    "error": None,
                },
                "status_code": 200,
            },
        ],
    )

    result = client.sync_collection_by_hash(_COLLECTION_ID, hashes, poll_interval=0.01)

    assert isinstance(result, CollectionSyncResponse)
    assert result.added_count == 10


def test_sync_collection_by_hash_job_fails(client, requests_mock):
    """Test that a FAILED job status during polling raises a client error."""
    job_id = "sync_fail"

    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/sync",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )

    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/sync-jobs/{job_id}",
        json={"job_id": job_id, "status": "FAILURE", "result": None, "error": "Critical error"},
        status_code=200,
    )

    with pytest.raises(DorsalClientError, match="Sync failed: Critical error"):
        client.sync_collection_by_hash(_COLLECTION_ID, [_DUMMY_SHA256], poll_interval=0.01)


def test_sync_collection_empty_result_error(client, requests_mock):
    """Test that a SUCCESS job with no result data raises an error."""
    job_id = "sync_empty"

    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/collections/{_COLLECTION_ID}/sync",
        json={"job_id": job_id, "status": "PENDING"},
        status_code=202,
    )

    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/collections/sync-jobs/{job_id}",
        json={"job_id": job_id, "status": "SUCCESS", "result": None, "error": None},
        status_code=200,
    )

    with pytest.raises(DorsalClientError, match="returned no result data"):
        client.sync_collection_by_hash(_COLLECTION_ID, [_DUMMY_SHA256], poll_interval=0.01)
