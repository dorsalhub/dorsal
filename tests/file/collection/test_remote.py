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
from unittest.mock import MagicMock, patch
import datetime

from dorsal.file.collection.remote import DorsalFileCollection, PAGINATION_RECORD_LIMIT
from dorsal.common.exceptions import DorsalClientError

from dorsal.client.validators import CollectionsResponse, CollectionWebLocationResponse
from dorsal.file.validators.collection import (
    FileCollection,
    HydratedSingleCollectionResponse,
    Pagination,
    FileCollectionSource,
)
from dorsal.file.validators.file_record import Annotations, FileRecordDateTime, Annotation_Base
from dorsal.file.validators.base import FileCoreValidationModel


@pytest.fixture
def mock_dorsal_client():
    """Provides a mock DorsalClient instance."""
    with patch("dorsal.file.collection.remote.get_shared_dorsal_client") as mock_get_client:
        client_instance = MagicMock()
        mock_get_client.return_value = client_instance
        yield client_instance


@pytest.fixture
def mock_collection_response():
    """Provides a mock HydratedSingleCollectionResponse for a successful API call."""
    mock_core_model = MagicMock(spec=FileCoreValidationModel)
    mock_base_annotation = MagicMock(spec=Annotation_Base)
    mock_base_annotation.record = mock_core_model
    mock_base_annotation.record.hash = "a" * 64

    mock_base_annotation.record.quick_hash = None
    mock_base_annotation.record.similarity_hash = None
    mock_base_annotation.record.all_hash_ids = None
    mock_base_annotation.record.all_hashes = None

    mock_annotations = MagicMock(spec=Annotations)
    mock_annotations.file_base = mock_base_annotation

    mock_file_record = MagicMock(spec=FileRecordDateTime)
    mock_file_record.hash = "a" * 64
    mock_file_record.quick_hash = None
    mock_file_record.similarity_hash = None
    mock_file_record.validation_hash = None
    mock_file_record.date_created = datetime.datetime.now(tz=datetime.timezone.utc)
    mock_file_record.date_modified = datetime.datetime.now(tz=datetime.timezone.utc)
    mock_file_record.annotations = mock_annotations

    mock_collection_meta = FileCollection(
        collection_id="col_123",
        user_no=1,
        is_private=True,
        name="Test",
        total_files=1,
        total_size_bytes=100,
        source=FileCollectionSource(caller="test"),
    )
    mock_pagination = Pagination(
        current_page=1,
        record_count=1,
        page_count=1,
        per_page=50,
        has_next=False,
        has_prev=False,
        start_index=1,
        end_index=1,
    )
    return HydratedSingleCollectionResponse(
        collection=mock_collection_meta,
        files=[mock_file_record],
        pagination=mock_pagination,
    )


# --- Existing Tests ---


@patch("dorsal.file.dorsal_file.DorsalFile.from_record")
def test_dorsal_collection_init_success(mock_from_record, mock_dorsal_client, mock_collection_response):
    """Test successful initialization of a DorsalFileCollection."""
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    mock_file_instance = MagicMock()
    mock_from_record.return_value = mock_file_instance
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)
    mock_dorsal_client.get_collection.assert_called_once_with("col_123", hydrate=True)
    assert len(collection.files) == 1


def test_populate_with_pagination(mock_dorsal_client, mock_collection_response):
    """Test populating a collection using the standard pagination method."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    collection.metadata.file_count = 100
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection.populate()
    assert mock_dorsal_client.get_collection.call_count == 2
    assert collection._is_populated is True


def test_populate_with_export(mock_dorsal_client):
    """Test populating a large collection using the server-side export method."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    collection.metadata.file_count = PAGINATION_RECORD_LIMIT + 1
    with patch("json.load", return_value={"results": []}):
        collection.populate(use_export=True)
    mock_dorsal_client.export_collection.assert_called_once()
    assert collection._is_populated is True


def test_populate_large_collection_raises_error_without_export_flag(mock_dorsal_client):
    """Test that populating a large collection without use_export=True fails."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    collection.metadata.file_count = PAGINATION_RECORD_LIMIT + 1
    with pytest.raises(DorsalClientError, match="exceeds the pagination limit"):
        collection.populate(use_export=False)


def test_list_collections(mock_dorsal_client):
    """Test the list_collections classmethod."""
    # Arrange
    mock_meta1 = FileCollection(
        collection_id="col_1",
        user_no=1,
        is_private=True,
        name="C1",
        total_files=10,
        total_size_bytes=100,
        source=FileCollectionSource(caller="test"),
    )
    mock_pagination = Pagination(
        current_page=1,
        record_count=1,
        page_count=1,
        per_page=50,
        has_next=False,
        has_prev=False,
        start_index=1,
        end_index=1,
    )
    mock_response = CollectionsResponse(records=[mock_meta1], pagination=mock_pagination)
    mock_dorsal_client.list_collections.return_value = mock_response

    # Act
    collections = DorsalFileCollection.list_collections(client=mock_dorsal_client)

    # Assert
    mock_dorsal_client.list_collections.assert_called_once_with(page=1, per_page=50)
    assert len(collections) == 1
    assert collections[0].collection_id == "col_1"
    assert len(collections[0].files) == 0


@patch("dorsal.file.collection.remote.DorsalFileCollection.populate")
@patch("dorsal.file.collection.remote.DorsalFileCollection.__init__", return_value=None)
def test_from_remote(mock_init, mock_populate):
    """Test the from_remote classmethod convenience constructor."""
    DorsalFileCollection.from_remote("col_123")
    mock_init.assert_called_once()
    mock_populate.assert_called_once()


def test_fetch_page(mock_dorsal_client, mock_collection_response):
    """Test fetching a specific page of results."""
    initial_pagination = Pagination(
        current_page=1,
        record_count=10,
        page_count=5,
        per_page=0,
        has_next=True,
        has_prev=False,
        start_index=1,
        end_index=0,
    )
    initial_response = HydratedSingleCollectionResponse(
        collection=mock_collection_response.collection,
        files=[],
        pagination=initial_pagination,
    )
    mock_dorsal_client.get_collection.return_value = initial_response

    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)

    # Now, set up the mock response for the actual fetch_page call
    mock_dorsal_client.get_collection.return_value = mock_collection_response

    # Act
    collection.fetch_page(3)

    # Assert
    # The call now correctly uses per_page=0 from the pagination object set during initialization.
    mock_dorsal_client.get_collection.assert_called_with("col_123", page=3, per_page=0, hydrate=True)
    assert len(collection.files) == 1


def test_next_and_previous_page(mock_dorsal_client):
    """Test the next_page and previous_page helper methods."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    with patch.object(collection, "fetch_page") as mock_fetch:
        collection.pagination.has_next = True
        collection.pagination.current_page = 2
        collection.next_page()
        mock_fetch.assert_called_once_with(3)

        collection.pagination.has_prev = True
        collection.pagination.current_page = 2
        collection.previous_page()
        mock_fetch.assert_called_with(1)


def test_refresh(mock_dorsal_client):
    """Test that refresh re-fetches the current page of the collection."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    collection.pagination.current_page = 4
    with patch.object(collection, "fetch_page") as mock_fetch:
        collection.refresh()
        mock_fetch.assert_called_once_with(4)


def test_fetch_page_invalid_page_raises_error(mock_dorsal_client):
    """Test that calling fetch_page with an out-of-bounds page number raises a ValueError."""
    collection = DorsalFileCollection.from_id_metadata_only("col_123", client=mock_dorsal_client)
    collection.pagination.page_count = 3
    with pytest.raises(ValueError):
        collection.fetch_page(4)


# --- New Tests ---


def test_add_files(mock_dorsal_client, mock_collection_response):
    """Test adding files to a remote collection."""
    # Arrange
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)
    hashes_to_add = ["hash1", "hash2"]

    # Act
    collection.add_files(hashes_to_add)

    # Assert
    mock_dorsal_client.add_files_to_collection.assert_called_once_with("col_123", hashes_to_add)
    # The initial __init__ call and the refresh() call
    assert mock_dorsal_client.get_collection.call_count == 2


def test_remove_files(mock_dorsal_client, mock_collection_response):
    """Test removing files from a remote collection."""
    # Arrange
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)
    hashes_to_remove = ["hash1", "hash2"]

    # Act
    collection.remove_files(hashes_to_remove)

    # Assert
    mock_dorsal_client.remove_files_from_collection.assert_called_once_with("col_123", hashes_to_remove)
    assert mock_dorsal_client.get_collection.call_count == 2


def test_update(mock_dorsal_client, mock_collection_response):
    """Test updating a remote collection's metadata."""
    # Arrange
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)

    # The client's update_collection method should return the new metadata
    updated_meta = mock_collection_response.collection.model_copy()
    updated_meta.name = "New Name"
    mock_dorsal_client.update_collection.return_value = updated_meta

    result = collection.update(name="New Name", description="New Desc")

    mock_dorsal_client.update_collection.assert_called_once_with(
        collection_id="col_123", name="New Name", description="New Desc"
    )
    assert collection.metadata.name == "New Name"
    assert result is collection


def test_make_public(mock_dorsal_client, mock_collection_response):
    """Test making a collection public."""
    # Arrange
    # The initial state is a private collection
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)

    # Mock the response from the make_collection_public client method
    mock_location_response = CollectionWebLocationResponse(location_url="http://example.com/public/col_123")
    mock_dorsal_client.make_collection_public.return_value = mock_location_response

    # Act
    result_url = collection.make_public()

    # Assert
    mock_dorsal_client.make_collection_public.assert_called_once_with("col_123")
    # The method should call refresh(), which calls get_collection() again
    assert mock_dorsal_client.get_collection.call_count == 2
    assert result_url == "http://example.com/public/col_123"


def test_make_private(mock_dorsal_client, mock_collection_response):
    """Test making a collection private."""
    # Arrange
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)

    # Mock the response from the make_collection_private client method
    mock_location_response = CollectionWebLocationResponse(location_url="http://example.com/private/col_123")
    mock_dorsal_client.make_collection_private.return_value = mock_location_response

    # Act
    result_url = collection.make_private()

    # Assert
    mock_dorsal_client.make_collection_private.assert_called_once_with("col_123")
    # The method should call refresh()
    assert mock_dorsal_client.get_collection.call_count == 2
    assert result_url == "http://example.com/private/col_123"


def test_delete(mock_dorsal_client, mock_collection_response):
    """Test deleting a remote collection."""
    # Arrange
    mock_dorsal_client.get_collection.return_value = mock_collection_response
    collection = DorsalFileCollection(collection_id="col_123", client=mock_dorsal_client)

    # Act
    collection.delete()

    # Assert
    mock_dorsal_client.delete_collections.assert_called_once_with(collection_ids=["col_123"])
