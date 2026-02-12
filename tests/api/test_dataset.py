# Copyright 2025-2026 Dorsal Hub LTD
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
from unittest.mock import patch, MagicMock

from dorsal.api import dataset as dataset_api
from dorsal.common.exceptions import (
    ApiDataValidationError,
    ConflictError,
    DorsalClientError,
    RecordValidationError,
    DatasetTypeError,
    DorsalOfflineError,
)
from dorsal.common.validators.datasets import Dataset
from dorsal.common.validators.json_schema import JsonSchemaValidator
from dorsal.client.validators import NewDatasetResponse, RecordIndexResult


class MockDataset:
    """A mock to stand in for the real Dataset Pydantic model."""

    def __init__(self, dataset_id, schema):
        self.dataset_id = dataset_id
        self.dataset_schema = schema


@pytest.fixture
def mock_shared_client():
    """Mocks the get_shared_dorsal_client function within the dataset API module."""
    with patch("dorsal.api.dataset.get_shared_dorsal_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        yield mock_client


def test_get_dataset_success(mock_shared_client):
    """Test a successful call to get a dataset."""
    dataset_id = "my-org/my-dataset"
    mock_response = MockDataset(dataset_id=dataset_id, schema={})
    mock_shared_client.get_dataset.return_value = mock_response

    result = dataset_api.get_dataset(dataset_id)

    mock_shared_client.get_dataset.assert_called_once_with(dataset_id=dataset_id, api_key=None)
    assert result == mock_response


def test_get_dataset_schema_success(mock_shared_client):
    """Test a successful call to get a dataset's schema."""
    dataset_id = "my-org/my-dataset"
    expected_schema = {"type": "object"}
    mock_shared_client.get_dataset_schema.return_value = expected_schema

    result = dataset_api.get_dataset_schema(dataset_id)

    mock_shared_client.get_dataset_schema.assert_called_once_with(dataset_id=dataset_id)
    assert result == expected_schema


@patch("dorsal.api.dataset.get_dataset_schema")
@patch("dorsal.api.dataset.get_json_schema_validator")
def test_make_schema_validator_success(mock_get_validator, mock_get_schema):
    """Test that make_schema_validator orchestrates schema fetching and validator creation."""
    dataset_id = "my-org/my-dataset"
    schema = {"type": "object"}
    mock_validator = MagicMock(spec=JsonSchemaValidator)

    mock_get_schema.return_value = schema
    mock_get_validator.return_value = mock_validator

    result = dataset_api.make_schema_validator(dataset_id)

    mock_get_schema.assert_called_once_with(dataset_id=dataset_id, api_key=None, client=None)
    mock_get_validator.assert_called_once_with(schema=schema)
    assert result == mock_validator


@patch("dorsal.api.dataset.get_dataset_schema")
def test_make_schema_validator_bad_schema(mock_get_schema):
    """Test that a schema error from the underlying validator function propagates."""
    mock_get_schema.return_value = "this-is-not-a-schema"

    with pytest.raises(TypeError):
        dataset_api.make_schema_validator("my-org/my-dataset")


@patch("dorsal.api.dataset.get_dataset_schema")
@patch("dorsal.api.dataset.json_schema_validate_records")
def test_validate_dataset_records_with_schema_dict(mock_validate, mock_get_schema):
    """Test validation when the schema is provided directly."""
    records = [{"id": 1}]
    schema = {"type": "object"}
    mock_validate.return_value = {"total_records": 1, "invalid_records": 0}

    summary = dataset_api.validate_dataset_records("my-org/ds", records=records, schema_dict=schema)

    mock_get_schema.assert_not_called()
    mock_validate.assert_called_once()
    assert summary["invalid_records"] == 0


@patch("dorsal.api.dataset.get_open_schema_validator")
def test_make_schema_validator_open_dataset(mock_get_open):
    """Test that 'open/' prefix triggers the open schema validator."""
    dataset_id = "open/arxiv"
    mock_validator = MagicMock()
    mock_get_open.return_value = mock_validator

    result = dataset_api.make_schema_validator(dataset_id)

    mock_get_open.assert_called_once_with("arxiv")
    assert result == mock_validator


@patch("dorsal.api.dataset.is_offline_mode")
def test_make_schema_validator_offline_mode(mock_offline):
    """Test that offline mode raises the correct error if schema not found locally."""
    mock_offline.return_value = True

    with pytest.raises(DorsalOfflineError) as exc:
        dataset_api.make_schema_validator("my-org/remote-only")

    assert "System is in OFFLINE mode" in str(exc.value)


@patch("dorsal.api.dataset.get_dataset_schema")
@patch("dorsal.api.dataset.get_json_schema_validator")
@patch("dorsal.api.dataset.json_schema_validate_records")
def test_validate_records_fetches_schema_when_missing(mock_validate, mock_get_validator, mock_get_schema):
    """Test that validation fetches the schema if schema_dict is None."""
    dataset_id = "my-org/fetch-me"
    records = [{"item": 1}]
    fetched_schema = {"type": "fetched"}

    mock_get_schema.return_value = fetched_schema

    dataset_api.validate_dataset_records(dataset_id, records, schema_dict=None)

    mock_get_schema.assert_called_once_with(dataset_id=dataset_id, api_key=None, client=None)

    mock_get_validator.assert_called_once_with(schema=fetched_schema)


def test_validate_records_input_guards():
    """Test input validation for dataset_id and records."""

    with pytest.raises(ValueError, match="Dataset ID must be a non-empty string"):
        dataset_api.validate_dataset_records("", [{"a": 1}])

    with pytest.raises(ValueError, match="must be a list"):
        dataset_api.validate_dataset_records("id", {"not": "a list"})


def test_get_dataset_generic_exception(mock_shared_client):
    """Test that unexpected exceptions are wrapped in DorsalClientError."""
    mock_shared_client.get_dataset.side_effect = Exception("Boom")

    with pytest.raises(DorsalClientError, match="unexpected issue occurred"):
        dataset_api.get_dataset("my-org/fail")


def test_get_dataset_schema_generic_exception(mock_shared_client):
    """Test that unexpected exceptions in schema fetch are wrapped."""
    mock_shared_client.get_dataset_schema.side_effect = Exception("Crash")

    with pytest.raises(DorsalClientError, match="unexpected issue occurred"):
        dataset_api.get_dataset_schema("my-org/fail")


@patch("dorsal.api.dataset.get_dataset_schema")
@patch("dorsal.api.dataset.get_json_schema_validator")
def test_validate_records_validator_creation_error(mock_get_validator, mock_get_schema):
    """Test error handling when validator creation fails."""

    mock_get_schema.return_value = {"valid": "json"}
    mock_get_validator.side_effect = ValueError("Invalid schema structure")

    with pytest.raises(ValueError, match="Invalid schema structure"):
        dataset_api.validate_dataset_records("id", [{"a": 1}], schema_dict=None)


@patch("dorsal.api.dataset.get_open_schema_validator")
@patch("dorsal.api.dataset.get_dataset_schema")
@patch("dorsal.api.dataset.get_json_schema_validator")
def test_make_schema_validator_open_dataset_fallback(mock_get_validator, mock_get_schema, mock_get_open):
    """Test that if open schema lookup fails, it falls back to standard schema fetching."""
    dataset_id = "open/unknown-dataset"

    mock_get_open.side_effect = ValueError("Unknown open schema")

    mock_get_schema.return_value = {"type": "object"}
    mock_get_validator.return_value = MagicMock()

    dataset_api.make_schema_validator(dataset_id)

    mock_get_open.assert_called_once_with("unknown-dataset")

    mock_get_schema.assert_called_once_with(dataset_id=dataset_id, api_key=None, client=None)
