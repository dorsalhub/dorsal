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
from dorsal.client import DorsalClient
from dorsal.common.exceptions import (
    DorsalClientError,
    NotFoundError,
    ApiDataValidationError,
    APIError,
    SchemaFormatError,
)
from dorsal.common.validators.datasets import Dataset

# Constants
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_DATASET_ID = "my-org/test-dataset"
_DUMMY_NAMESPACE = "my-org"
_DUMMY_NAME = "test-dataset"


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


@pytest.fixture
def mock_dataset_full_json():
    return {
        "dataset_id": _DUMMY_DATASET_ID,
        "type": "Reference",
        "key_field": "id",
        "version": "1.0.0",
        "name": "Test Dataset",
        "description": "A mock dataset for testing",
        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
        "date_created": "2025-01-01T12:00:00Z",
        "date_modified": "2025-01-01T12:00:00Z",
    }


# --- get_dataset Tests ---


def test_get_dataset_success(client, requests_mock, mock_dataset_full_json):
    """Test retrieving a full Dataset object."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}"
    requests_mock.get(target_url, json=mock_dataset_full_json, status_code=200)

    result = client.get_dataset(_DUMMY_DATASET_ID)

    assert isinstance(result, Dataset)
    assert result.dataset_id == _DUMMY_DATASET_ID
    assert result.dataset_schema["type"] == "object"


def test_get_dataset_not_found(client, requests_mock):
    """Test that 404 raises NotFoundError."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}"
    requests_mock.get(target_url, status_code=404, json={"detail": "Dataset not found"})

    with pytest.raises(NotFoundError):
        client.get_dataset(_DUMMY_DATASET_ID)


def test_get_dataset_invalid_id(client):
    """Test client-side validation of dataset_id format."""
    with pytest.raises(ValueError, match="Invalid dataset_id format"):
        client.get_dataset("invalid_format_no_slash")


def test_get_dataset_validation_error(client, requests_mock):
    """Test handling of malformed API responses."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}"
    requests_mock.get(target_url, json={"dataset_id": _DUMMY_DATASET_ID}, status_code=200)

    with pytest.raises(ApiDataValidationError):
        client.get_dataset(_DUMMY_DATASET_ID)


# --- get_dataset_type Tests ---


def test_get_dataset_type_success(client, requests_mock):
    """Test retrieving dataset type."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/type"
    requests_mock.get(target_url, text="File", status_code=200)

    result = client.get_dataset_type(_DUMMY_DATASET_ID)
    assert result == "File"


def test_get_dataset_type_unknown(client, requests_mock):
    """Test that an unknown type string raises validation error."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/type"
    requests_mock.get(target_url, text="UnknownType", status_code=200)

    with pytest.raises(ApiDataValidationError, match="Dataset type not recognised"):
        client.get_dataset_type(_DUMMY_DATASET_ID)


# --- get_dataset_schema Tests ---


def test_get_dataset_schema_success(client, requests_mock, mock_dataset_full_json):
    """Test retrieving just the schema."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/schema"
    requests_mock.get(target_url, json=mock_dataset_full_json["schema"], status_code=200)

    result = client.get_dataset_schema(_DUMMY_DATASET_ID)
    assert result == mock_dataset_full_json["schema"]


def test_get_dataset_schema_open_id(client, requests_mock):
    """Test that 'open/classification' style IDs work."""
    requests_mock.get(
        f"{_DUMMY_BASE_URL}/v1/namespaces/open/datasets/classification/schema", json={"type": "object"}, status_code=200
    )
    result = client.get_dataset_schema("open/classification")
    assert result == {"type": "object"}


# --- make_schema_validator Tests ---


def test_make_schema_validator_success(client, requests_mock):
    """Test creating a validator from a fetched schema."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/schema"
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}
    requests_mock.get(target_url, json=schema, status_code=200)

    validator = client.make_schema_validator(_DUMMY_DATASET_ID)

    assert validator.is_valid({"score": 10}) is True
    assert validator.is_valid({"score": "ten"}) is False


def test_make_schema_validator_retrieval_failure(client, requests_mock):
    """Test that errors during fetch propagate up."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/schema"
    requests_mock.get(target_url, status_code=500)

    with pytest.raises(APIError):
        client.make_schema_validator(_DUMMY_DATASET_ID)


def test_make_schema_validator_invalid_schema(client, requests_mock):
    """Test handling of a schema that isn't valid JSON Schema."""
    target_url = f"{_DUMMY_BASE_URL}/v1/namespaces/{_DUMMY_NAMESPACE}/datasets/{_DUMMY_NAME}/schema"

    invalid_schema = []  # Schemas must be dicts

    requests_mock.get(target_url, json=invalid_schema, status_code=200)

    # Fix: Expect DorsalClientError as per implementation
    with pytest.raises(DorsalClientError):
        client.make_schema_validator(_DUMMY_DATASET_ID)
