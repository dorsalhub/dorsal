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

import pytest
from unittest.mock import MagicMock
from dorsal.client import DorsalClient
from dorsal.common.exceptions import DorsalClientError, NotFoundError, BatchSizeError, ApiDataValidationError, APIError
from dorsal.file.validators.file_record import (
    FileRecordStrict,
    FileRecordDateTime,
    FileSearchResponse,
    NewFileTag,
    ValidateTagsResult,
)
from dorsal.client.validators import FileIndexResponse, FileTagResponse, FileDeleteResponse

# Constants
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


@pytest.fixture
def mock_file_record_strict():
    # Fix: Populated annotations to satisfy FileRecordStrict validation
    return FileRecordStrict(
        hash=_DUMMY_SHA256,
        validation_hash="b" * 64,
        source="disk",
        annotations={
            "file/base": {
                "record": {
                    "hash": _DUMMY_SHA256,
                    "name": "test.txt",
                    "size": 100,
                    "media_type": "text/plain",
                    "all_hashes": [{"id": "SHA-256", "value": _DUMMY_SHA256}, {"id": "BLAKE3", "value": "b" * 64}],
                },
                "source": {"type": "Model", "id": "dorsal/file-core", "version": "1.0"},
            }
        },
    )


@pytest.fixture
def mock_file_response_json():
    """Standard JSON response for a downloaded file record."""
    return {
        "hash": _DUMMY_SHA256,
        "validation_hash": "b" * 64,
        "date_created": "2025-01-01T12:00:00Z",
        "date_modified": "2025-01-01T12:00:00Z",
        "annotations": {
            "file/base": {
                "record": {"hash": _DUMMY_SHA256, "name": "test.txt", "size": 100, "media_type": "text/plain"},
                "source": {"type": "Model", "id": "base", "version": "1.0"},
            }
        },
    }


# --- Indexing Tests ---


def test_index_public_file_records_success(client, requests_mock, mock_file_record_strict):
    """Test successful indexing of public records."""
    mock_response = {"total": 1, "success": 1, "error": 0, "unauthorized": 0, "results": []}
    requests_mock.post(f"{_DUMMY_BASE_URL}/v1/files/public", json=mock_response, status_code=201)

    result = client.index_public_file_records([mock_file_record_strict])

    assert isinstance(result, FileIndexResponse)
    assert result.success == 1


def test_index_private_file_records_success(client, requests_mock, mock_file_record_strict):
    """Test successful indexing of private records."""
    mock_response = {"total": 1, "success": 1, "error": 0, "unauthorized": 0, "results": []}
    requests_mock.post(f"{_DUMMY_BASE_URL}/v1/files/private", json=mock_response, status_code=201)

    result = client.index_private_file_records([mock_file_record_strict])

    assert isinstance(result, FileIndexResponse)
    assert result.success == 1


def test_index_file_records_batch_size_error(client, mock_file_record_strict):
    """Test that exceeding batch size raises BatchSizeError."""
    client._file_records_batch_insert_size = 1
    records = [mock_file_record_strict, mock_file_record_strict]

    with pytest.raises(BatchSizeError):
        client.index_public_file_records(records)


# --- Search Tests ---


def test_search_files_success(client, requests_mock):
    """Test successful file search."""
    mock_response = {
        "api_version": "1.0",
        "pagination": {
            "record_count": 1,
            "page_count": 1,
            "page": 1,
            "per_page": 25,
            "total_items": 1,
            "total_pages": 1,
            "current_page": 1,
            "has_next": False,
            "has_prev": False,
            "start_index": 0,
            "end_index": 0,
        },
        "results": [],  # Empty results for simplicity
        "errors": [],
    }
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/files/search", json=mock_response, status_code=200)

    result = client.search_files(q="name:test", match_any=False)
    assert isinstance(result, FileSearchResponse)
    assert result.pagination.record_count == 1


def test_search_files_client_validation(client):
    """Test invalid search parameters."""
    with pytest.raises(DorsalClientError, match="'per_page' must be between"):
        client.search_files(q="test", per_page=1000, match_any=False)

    with pytest.raises(DorsalClientError, match="non-empty string"):
        client.search_files(q="", match_any=False)


# --- Existence Check ---


def test_check_files_indexed(client, requests_mock):
    """Test bulk existence check."""
    # Fix: URL matches constant in constants.py
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/users/files-indexed", json={_DUMMY_SHA256: True, "other_hash": False}, status_code=200
    )

    valid_other_hash = "b" * 64
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/users/files-indexed",
        json={_DUMMY_SHA256: True, valid_other_hash: False},
        status_code=200,
    )

    result = client.check_files_indexed([_DUMMY_SHA256, valid_other_hash])
    assert result[_DUMMY_SHA256] is True
    assert result[valid_other_hash] is False


# --- Tag Operations ---


def test_validate_tag_success(client, requests_mock):
    """Test tag validation."""
    tag = NewFileTag(name="status", value="ok", private=False)
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/files/tags/validate", json={"valid": True, "message": "OK"}, status_code=200
    )

    result = client.validate_tag([tag])
    assert isinstance(result, ValidateTagsResult)
    assert result.valid is True


def test_add_tags_to_file_success(client, requests_mock):
    """Test adding tags."""
    tag = NewFileTag(name="status", value="ok", private=False)
    requests_mock.post(
        f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/tags",
        json={"success": True, "hash": _DUMMY_SHA256, "tags": []},
        status_code=200,
    )

    result = client.add_tags_to_file(_DUMMY_SHA256, [tag])
    assert isinstance(result, FileTagResponse)


def test_delete_tag_success(client, requests_mock):
    """Test deleting a tag."""
    tag_id = "tag_1"
    requests_mock.delete(f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/tags/{tag_id}", status_code=204)

    result = client.delete_tag(file_hash=_DUMMY_SHA256, tag_id=tag_id)
    assert result is None


# --- Download Tests ---


def test_download_public_file_success(client, requests_mock, mock_file_response_json):
    """Test public download."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/files/public/{_DUMMY_SHA256}", json=mock_file_response_json)

    result = client.download_public_file_record(_DUMMY_SHA256)
    assert isinstance(result, FileRecordDateTime)
    assert result.hash == _DUMMY_SHA256


def test_download_private_file_success(client, requests_mock, mock_file_response_json):
    """Test private download."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/files/private/{_DUMMY_SHA256}", json=mock_file_response_json)

    result = client.download_private_file_record(_DUMMY_SHA256)
    assert isinstance(result, FileRecordDateTime)


def test_download_agnostic_fallback(client, requests_mock, mock_file_response_json):
    """Test that agnostic download tries private then public."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/files/private/{_DUMMY_SHA256}", status_code=404)
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/files/public/{_DUMMY_SHA256}", json=mock_file_response_json)

    result = client.download_file_record(_DUMMY_SHA256)
    assert result.hash == _DUMMY_SHA256
    assert requests_mock.call_count == 2


def test_download_invalid_response(client, requests_mock):
    """Test handling of malformed JSON from API."""
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/files/public/{_DUMMY_SHA256}", json={"incomplete": "data"}, status_code=200
    )

    with pytest.raises(ApiDataValidationError):
        client.download_public_file_record(_DUMMY_SHA256)


# --- Delete Tests ---


def test_delete_file_granular(client, requests_mock):
    """Test the granular delete endpoint."""
    requests_mock.delete(
        f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}",
        json={"file_deleted": 1, "tags_deleted": 0, "annotations_deleted": 0},
        status_code=200,
    )

    result = client.delete_file(file_hash=_DUMMY_SHA256, record="private")
    assert isinstance(result, FileDeleteResponse)
    assert result.file_deleted == 1
