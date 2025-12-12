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
from unittest.mock import call, patch, MagicMock

from dorsal.api import collection as collection_api
from dorsal.common.exceptions import DorsalError, DorsalClientError
from dorsal.client.validators import AddFilesResponse, RemoveFilesResponse


class MockApiResponse:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        return {"data": "mocked_dict"}

    def model_dump_json(self, **kwargs):
        return '{"data": "mocked_json"}'


class MockModel:
    """Helper to simulate Pydantic models with dump methods and attributes."""

    def __init__(self, data, **kwargs):
        self.data = data
        for k, v in kwargs.items():
            setattr(self, k, v)

    def model_dump(self, **kwargs):
        return self.data

    def model_dump_json(self, **kwargs):
        import json

        return json.dumps(self.data)


@pytest.fixture
def mock_shared_client():
    """Mocks the get_shared_dorsal_client function within the collection API module."""
    with patch("dorsal.session.get_shared_dorsal_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        yield mock_client


_DUMMY_CLIENT = MagicMock()
_DUMMY_SHA256 = "a" * 64


def test_list_collections_success(mock_shared_client):
    """Test a successful call to list_collections using the shared client."""
    mock_pagination = MagicMock()
    mock_pagination.current_page = 1
    mock_pagination.page_count = 1
    mock_response = MockApiResponse(records=[1, 2], pagination=mock_pagination)
    mock_shared_client.list_collections.return_value = mock_response

    result = collection_api.list_collections(page=1, per_page=50)

    mock_shared_client.list_collections.assert_called_once_with(page=1, per_page=50)
    assert result == mock_response


@patch("dorsal.client.DorsalClient")
def test_list_collections_with_api_key(mock_client_class, mock_shared_client):
    """Test that list_collections uses a temporary client when an api_key is provided."""
    mock_temp_client = MagicMock()
    mock_client_class.return_value = mock_temp_client

    collection_api.list_collections(api_key="temp_key_123")

    mock_shared_client.list_collections.assert_not_called()
    mock_client_class.assert_called_once_with(api_key="temp_key_123")
    mock_temp_client.list_collections.assert_called_once()


def test_get_collection_success(mock_shared_client):
    """Test a successful call to get a single collection."""
    mock_response = MockApiResponse(collection_id="col_123")
    mock_shared_client.get_collection.return_value = mock_response

    result = collection_api.get_collection("col_123", hydrate=True, mode="pydantic")

    mock_shared_client.get_collection.assert_called_once_with(
        collection_id="col_123", hydrate=True, page=1, per_page=30
    )
    assert result.collection_id == "col_123"


@pytest.mark.parametrize("mode, expected_type", [("dict", dict), ("json", str)])
def test_get_collection_modes(mock_shared_client, mode, expected_type):
    """Test the 'mode' parameter returns the correct data type for get_collection."""
    mock_shared_client.get_collection.return_value = MockApiResponse()

    result = collection_api.get_collection("col_123", mode=mode)

    assert isinstance(result, expected_type)


def test_update_collection_success(mock_shared_client):
    """Test a successful call to update a collection."""
    mock_response = MockApiResponse(name="new-name")
    mock_shared_client.update_collection.return_value = mock_response

    result = collection_api.update_collection(collection_id="col_123", name="new-name", description="new-desc")

    mock_shared_client.update_collection.assert_called_once_with(
        collection_id="col_123", name="new-name", description="new-desc"
    )
    assert result.name == "new-name"


def test_update_collection_no_fields_raises_error(mock_shared_client):
    """Test that update_collection raises a ValueError if no update fields are provided."""
    with pytest.raises(ValueError, match="At least one field .* must be provided"):
        collection_api.update_collection("col_123")

    mock_shared_client.update_collection.assert_not_called()


@patch("dorsal.api.collection.API_MAX_BATCH_SIZE", 2)
def test_add_files_to_collection_with_batching(mock_shared_client):
    """Test that add_files_to_collection correctly batches hashes and aggregates results."""
    collection_id = "col_123"
    hashes = [_DUMMY_SHA256] * 3

    mock_shared_client.add_files_to_collection.side_effect = [
        AddFilesResponse(added_count=2, duplicate_count=0, invalid_count=0),
        AddFilesResponse(added_count=1, duplicate_count=0, invalid_count=0),
    ]

    result = collection_api.add_files_to_collection(collection_id, hashes)

    # Assert that the client method was called twice
    assert mock_shared_client.add_files_to_collection.call_count == 2

    # Assert the aggregated result is correct
    assert isinstance(result, AddFilesResponse)
    assert result.added_count == 3
    assert result.duplicate_count == 0


def test_add_files_to_collection_empty_list_error():
    """Test that add_files_to_collection raises a ValueError for an empty hash list."""
    with pytest.raises(ValueError, match="The 'hashes' list cannot be empty"):
        collection_api.add_files_to_collection("col_123", [])


@patch("dorsal.api.collection.API_MAX_BATCH_SIZE", 2)
def test_remove_files_from_collection_with_batching(mock_shared_client):
    """Test that remove_files_from_collection correctly batches hashes and aggregates results."""
    collection_id = "col_123"
    hashes = ["a" * 64, "b" * 64, "c" * 64]  # 3 hashes to force two batches

    mock_shared_client.remove_files_from_collection.side_effect = [
        RemoveFilesResponse(removed_count=2, not_found_count=0),
        RemoveFilesResponse(removed_count=0, not_found_count=1),
    ]

    result = collection_api.remove_files_from_collection(collection_id, hashes)

    # Assert that the client method was called twice with the correct batches
    expected_calls = [
        call(collection_id=collection_id, hashes=["a" * 64, "b" * 64]),
        call(collection_id=collection_id, hashes=["c" * 64]),
    ]
    mock_shared_client.remove_files_from_collection.assert_has_calls(expected_calls)
    assert mock_shared_client.remove_files_from_collection.call_count == 2

    # Assert the aggregated result is correct
    assert isinstance(result, RemoveFilesResponse)
    assert result.removed_count == 2
    assert result.not_found_count == 1


@patch("dorsal.session.get_shared_dorsal_client")
def test_export_collection_success(mock_get_client):
    """Test that export_collection correctly calls the underlying client method."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    collection_id = "col_to_export"
    output_path = "/tmp/export.json.gz"

    collection_api.export_collection(
        collection_id=collection_id,
        output_path=output_path,
        poll_interval=10,
        timeout=60,
    )

    # Assert that the client's orchestrator method was called with all arguments passed through
    mock_client.export_collection.assert_called_once_with(
        collection_id=collection_id,
        output_path=output_path,
        poll_interval=10,
        timeout=60,
        console=None,
        palette=None,
    )


def test_delete_collection_success(mock_shared_client):
    """Test a successful call to delete a single collection."""
    collection_id = "col_to_delete"

    # The client method returns None on success
    mock_shared_client.delete_collections.return_value = None

    collection_api.delete_collection(collection_id)

    # Assert that the high-level function correctly wraps the single ID in a list
    # for the client's bulk-delete method.
    mock_shared_client.delete_collections.assert_called_once_with(collection_ids=[collection_id])


def test_delete_collection_empty_id_error(mock_shared_client):
    """Test that delete_collection raises a ValueError if the collection_id is empty."""
    with pytest.raises(ValueError, match="collection_id cannot be empty"):
        collection_api.delete_collection("")

    mock_shared_client.delete_collections.assert_not_called()


def test_list_collections_modes(mock_shared_client):
    """Test list_collections returns correct types for dict/json modes."""
    # Setup mock response with necessary attributes for logging
    mock_pagination = MagicMock()
    mock_pagination.current_page = 1
    mock_pagination.page_count = 1

    mock_response = MockModel({"records": []}, pagination=mock_pagination, records=[])
    mock_shared_client.list_collections.return_value = mock_response

    # Test 'dict' mode
    res_dict = collection_api.list_collections(mode="dict")
    assert isinstance(res_dict, dict)
    assert res_dict == {"records": []}

    # Test 'json' mode
    res_json = collection_api.list_collections(mode="json")
    assert isinstance(res_json, str)
    assert "records" in res_json

    # Test Invalid mode
    # Must catch DorsalError because the wrapper catches ValueError
    with pytest.raises(DorsalError, match="Invalid mode"):
        collection_api.list_collections(mode="invalid")  # type: ignore


def test_update_collection_modes(mock_shared_client):
    """Test update_collection returns correct types for dict/json modes."""
    mock_response = MockModel({"id": "123", "name": "Updated"})
    mock_shared_client.update_collection.return_value = mock_response

    # Test 'dict' mode
    res_dict = collection_api.update_collection("123", name="n", mode="dict")
    assert isinstance(res_dict, dict)

    # Test 'json' mode
    res_json = collection_api.update_collection("123", name="n", mode="json")
    assert isinstance(res_json, str)

    # Test Invalid mode
    with pytest.raises(DorsalError, match="Invalid mode"):
        collection_api.update_collection("123", name="n", mode="invalid")  # type: ignore


# --- 2. Error Handling Tests ---


@pytest.mark.parametrize(
    "function, args",
    [
        (collection_api.list_collections, {}),
        (collection_api.get_collection, {"collection_id": "123"}),
        (collection_api.update_collection, {"collection_id": "123", "name": "new"}),
        (collection_api.add_files_to_collection, {"collection_id": "123", "hashes": ["a" * 64]}),
        (collection_api.remove_files_from_collection, {"collection_id": "123", "hashes": ["a" * 64]}),
        (collection_api.make_collection_public, {"collection_id": "123"}),
        (collection_api.make_collection_private, {"collection_id": "123"}),
        (collection_api.export_collection, {"collection_id": "123", "output_path": "out.gz"}),
        (collection_api.delete_collection, {"collection_id": "123"}),
    ],
)
def test_api_wrappers_handle_unexpected_exceptions(mock_shared_client, function, args):
    """
    Verifies that unexpected exceptions (e.g. ValueError, TypeError from inside the client)
    are caught, logged, and re-raised as DorsalError.
    This covers the `except Exception` blocks.
    """
    # Configure the relevant method on the mock client to raise a generic error
    method_name = function.__name__

    # Map api function names to client method names where they differ
    if method_name == "delete_collection":
        method_name = "delete_collections"

    if hasattr(mock_shared_client, method_name):
        getattr(mock_shared_client, method_name).side_effect = ValueError("Unexpected Boom")

    with pytest.raises(DorsalError) as exc:
        function(**args)

    # Ensure it wrapped the original error, not just passed it through
    assert "Unexpected Boom" in str(exc.value)
    assert isinstance(exc.value, DorsalError)


@pytest.mark.parametrize(
    "function, args",
    [
        (collection_api.list_collections, {}),
        (collection_api.get_collection, {"collection_id": "123"}),
        (collection_api.update_collection, {"collection_id": "123", "name": "new"}),
        (collection_api.add_files_to_collection, {"collection_id": "123", "hashes": ["a" * 64]}),
        (collection_api.remove_files_from_collection, {"collection_id": "123", "hashes": ["a" * 64]}),
        (collection_api.make_collection_public, {"collection_id": "123"}),
        (collection_api.make_collection_private, {"collection_id": "123"}),
        (collection_api.export_collection, {"collection_id": "123", "output_path": "out.gz"}),
        (collection_api.delete_collection, {"collection_id": "123"}),
    ],
)
def test_api_wrappers_passthrough_dorsal_errors(mock_shared_client, function, args):
    """
    Verifies that known DorsalErrors (e.g. NotFoundError) are passed through directly.
    This covers the `except DorsalError` blocks.
    """
    method_name = function.__name__
    if method_name == "delete_collection":
        method_name = "delete_collections"

    if hasattr(mock_shared_client, method_name):
        getattr(mock_shared_client, method_name).side_effect = DorsalClientError("Known Error")

    with pytest.raises(DorsalClientError, match="Known Error"):
        function(**args)


def test_add_files_batching_loop_exception(mock_shared_client):
    """Test exception handling specifically inside the batching loop."""
    mock_shared_client.add_files_to_collection.side_effect = [
        MagicMock(added_count=1, duplicate_count=0, invalid_count=0),
        ValueError("Loop Boom"),
    ]

    with patch("dorsal.api.collection.API_MAX_BATCH_SIZE", 1):
        with pytest.raises(DorsalError, match="Loop Boom"):
            collection_api.add_files_to_collection("123", ["a" * 64, "b" * 64])


def test_get_collection_mode_exception(mock_shared_client):
    """Test get_collection invalid mode exception."""
    mock_shared_client.get_collection.return_value = MockModel({})
    with pytest.raises(DorsalError, match="Invalid mode"):
        collection_api.get_collection("123", mode="invalid")  # type: ignore
