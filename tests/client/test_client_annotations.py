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
import requests
import requests_mock
from unittest.mock import MagicMock
from dorsal.client import DorsalClient
from dorsal.common.exceptions import DorsalClientError, NotFoundError, NetworkError, ApiDataValidationError
from dorsal.file.validators.file_record import Annotation, GenericFileAnnotation
from dorsal.client.validators import AnnotationIndexResult, FileAnnotationResponse

# Constants for testing
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64
_DUMMY_ANNOTATION_ID = "anno_12345"
_DUMMY_SCHEMA_ID = "my-org/my-dataset"


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


@pytest.fixture
def mock_annotation():
    """Returns a valid Annotation object for testing."""
    return Annotation(
        record=GenericFileAnnotation(file_hash=_DUMMY_SHA256, score=0.95),
        source={"type": "Model", "id": "my-org/my-model", "version": "1.0"},
    )


def test_add_file_annotation_success(client, requests_mock, mock_annotation):
    """Test successfully adding an annotation."""
    mock_response = {
        "total": 1,
        "success": 1,
        "error": 0,
        "dataset_id": _DUMMY_SCHEMA_ID,
        "results": [
            {
                "key": "some_key",
                "annotation_id": _DUMMY_ANNOTATION_ID,
                "private": True,
                "status": "created",
                "reason": None,
            }
        ],
    }

    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/my-org/my-dataset"

    requests_mock.post(expected_url, json=mock_response, status_code=201)

    result = client.add_file_annotation(file_hash=_DUMMY_SHA256, schema_id=_DUMMY_SCHEMA_ID, annotation=mock_annotation)

    assert isinstance(result, AnnotationIndexResult)
    assert result.success == 1
    assert result.results[0].annotation_id == _DUMMY_ANNOTATION_ID
    assert result.results[0].status == "created"


def test_add_file_annotation_validation_errors(client, mock_annotation):
    """Test client-side validation for add_file_annotation."""
    with pytest.raises(DorsalClientError, match="Invalid SHA-256"):
        client.add_file_annotation(file_hash="bad-hash", schema_id=_DUMMY_SCHEMA_ID, annotation=mock_annotation)

    with pytest.raises(DorsalClientError, match="must be a valid Annotation"):
        client.add_file_annotation(
            file_hash=_DUMMY_SHA256,
            schema_id=_DUMMY_SCHEMA_ID,
            annotation={"not": "an object"},  # type: ignore
        )


def test_add_file_annotation_network_error(client, requests_mock, mock_annotation):
    """Test handling of network errors during add."""
    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/my-org/my-dataset"
    requests_mock.post(expected_url, exc=requests.exceptions.ConnectionError("Connection refused"))

    with pytest.raises(NetworkError):
        client.add_file_annotation(file_hash=_DUMMY_SHA256, schema_id=_DUMMY_SCHEMA_ID, annotation=mock_annotation)


def test_get_file_annotation_success(client, requests_mock):
    """Test successfully retrieving a specific annotation."""
    mock_response = {
        "annotation_id": _DUMMY_ANNOTATION_ID,
        "file_hash": _DUMMY_SHA256,
        "schema_id": _DUMMY_SCHEMA_ID,
        "schema_version": None,
        "source": {"type": "human", "id": "u1"},
        "record": {"file_hash": _DUMMY_SHA256, "score": 0.8},
        "user_id": 1,
        "date_created": "2025-01-01T12:00:00Z",
        "date_modified": "2025-01-01T12:00:00Z",
        "private": True,
    }

    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.get(expected_url, json=mock_response, status_code=200)

    result = client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)

    assert isinstance(result, FileAnnotationResponse)
    assert result.annotation_id == _DUMMY_ANNOTATION_ID
    assert result.schema_id == _DUMMY_SCHEMA_ID


def test_get_file_annotation_not_found(client, requests_mock):
    """Test retrieving a non-existent annotation."""
    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.get(expected_url, status_code=404, json={"detail": "Not found"})

    with pytest.raises(NotFoundError):
        client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)


def test_get_file_annotation_invalid_data(client, requests_mock):
    """Test handling of invalid API response data."""
    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    # Missing required fields
    requests_mock.get(expected_url, json={"id": "123"}, status_code=200)

    with pytest.raises(ApiDataValidationError):
        client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)


def test_delete_file_annotation_success(client, requests_mock):
    """Test successfully deleting an annotation."""
    expected_url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.delete(expected_url, status_code=204)

    result = client.delete_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)
    assert result is None


def test_delete_file_annotation_validation(client):
    """Test client validation for delete parameters."""
    with pytest.raises(DorsalClientError, match="annotation_id must be a non-empty string"):
        client.delete_file_annotation(file_hash=_DUMMY_SHA256, annotation_id="")

    with pytest.raises(DorsalClientError, match="Invalid SHA-256"):
        client.delete_file_annotation(file_hash="bad_hash", annotation_id=_DUMMY_ANNOTATION_ID)
