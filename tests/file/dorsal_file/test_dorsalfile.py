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
from unittest.mock import patch, MagicMock
import datetime

from dorsal.client.validators import FileDeleteResponse
from dorsal.file.dorsal_file import DorsalFile
from dorsal.file.validators.file_record import (
    FileRecordDateTime,
    FileRecordStrict,
    NewFileTag,
    FileTag,
)
from dorsal.common.exceptions import (
    DorsalClientError,
    DorsalError,
    TaggingError,
    AuthError,
    RateLimitError,
    BadRequestError,
    ForbiddenError,
    NetworkError,
    UnsupportedHashError,
)


_DUMMY_CLIENT = MagicMock()


@pytest.fixture
def mock_file_record_dt_json() -> dict:
    """Provides a valid dictionary for a FileRecordDateTime API response."""
    return {
        "hash": "a" * 64,
        "date_created": "2025-01-01T12:00:00Z",
        "date_modified": "2025-01-01T12:00:00Z",
        "annotations": {
            "file_base": {
                "record": {
                    "hash": "a" * 64,
                    "name": "initial_name.txt",
                    "extension": ".txt",
                    "size": 1234,
                    "media_type": "text/plain",
                },
                "source": {"type": "Model", "id": "file/base", "version": "0.1.0"},
            }
        },
    }


@pytest.fixture
def mock_dorsal_client() -> MagicMock:
    """Provides a mock DorsalClient instance."""
    return MagicMock()


def test_dorsal_file_init_success(mock_dorsal_client, mock_file_record_dt_json):
    """Test successful initialization of a DorsalFile by fetching a record."""
    # Arrange: Configure the mock client to return a valid record
    mock_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = mock_record

    # Act: Initialize the DorsalFile, which will trigger the mocked download
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Assert
    mock_dorsal_client.download_file_record.assert_called_once_with(hash_string="a" * 64, private=None)
    assert df.hash == "a" * 64
    assert df.name == "initial_name.txt"
    assert isinstance(df.date_created, datetime.datetime)


def test_dorsal_file_init_from_record(mock_dorsal_client, mock_file_record_dt_json):
    """Test successful initialization using the from_record classmethod."""
    # Arrange: Create the Pydantic model instance directly
    record = FileRecordDateTime(**mock_file_record_dt_json)

    # Act: Initialize the DorsalFile from the existing record
    df = DorsalFile.from_record(record, client=mock_dorsal_client)

    # Assert: No network call was made
    mock_dorsal_client.download_file_record.assert_not_called()
    assert df.hash == record.hash
    assert df.name == "initial_name.txt"


def test_dorsal_file_refresh_success(mock_dorsal_client, mock_file_record_dt_json):
    """Test that the refresh method updates the object's data."""
    # Arrange: Setup initial and updated records
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)

    updated_record_json = mock_file_record_dt_json.copy()
    updated_record_json["annotations"]["file_base"]["record"]["name"] = "updated_name.txt"
    updated_record = FileRecordDateTime(**updated_record_json)

    # The client's download method will first return the initial record, then the updated one
    mock_dorsal_client.download_file_record.side_effect = [
        initial_record,
        updated_record,
    ]

    # Act 1: Initialize the object
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)
    assert df.name == "initial_name.txt"

    # Act 2: Refresh the object
    df.refresh()

    # Assert
    assert mock_dorsal_client.download_file_record.call_count == 2
    assert df.name == "updated_name.txt"  # The name should now be updated


def test_dorsal_file_add_public_tag(mock_dorsal_client, mock_file_record_dt_json):
    """Test adding a public tag to a DorsalFile instance."""
    # Arrange: Set up the initial record and a successful response from the client
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record

    # Mock the add_tags_to_file client method
    mock_add_response = MagicMock(success=True)
    mock_dorsal_client.add_tags_to_file.return_value = mock_add_response

    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Act: Add the tag
    df.add_public_tag(name="release_candidate", value=True)

    # Assert: Check that the client method was called with a correctly formed NewFileTag
    mock_dorsal_client.add_tags_to_file.assert_called_once()
    call_args, call_kwargs = mock_dorsal_client.add_tags_to_file.call_args
    sent_tags = call_kwargs["tags"]
    assert len(sent_tags) == 1
    assert isinstance(sent_tags[0], NewFileTag)
    assert sent_tags[0].name == "release_candidate"
    assert sent_tags[0].private is False


def test_dorsal_file_add_tag_failure(mock_dorsal_client, mock_file_record_dt_json):
    """Test that a failed tag operation on the client raises a TaggingError."""
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record

    # Mock a failed response from the client
    mock_add_response = MagicMock(success=False, detail="Server-side validation failed.")
    mock_dorsal_client.add_tags_to_file.return_value = mock_add_response

    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    with pytest.raises(TaggingError, match="Server-side validation failed."):
        df.add_private_tag(name="some_tag", value="some_value")


def test_dorsal_file_delete_tag(mock_dorsal_client, mock_file_record_dt_json):
    """Test deleting a tag from a DorsalFile instance."""
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    # The refresh call will need a record to return, we can just use the same one
    mock_dorsal_client.download_file_record.side_effect = [
        initial_record,
        initial_record,
    ]

    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Act: Delete the tag
    tag_id_to_delete = "615f7f3b3e3f1a3a3a3a3a3a"  # Example 24-char hex
    df.delete_tag(tag_id=tag_id_to_delete)

    # Assert: Check that the client's delete method was called correctly
    mock_dorsal_client.delete_tag.assert_called_once_with(file_hash=df.hash, tag_id=tag_id_to_delete, api_key=None)
    # Assert that the object was refreshed (download_file_record was called a second time)
    assert mock_dorsal_client.download_file_record.call_count == 2


def test_set_validation_hash_upgrades_model(mock_dorsal_client, mock_file_record_dt_json):
    """Test that setting a validation_hash upgrades the model to FileRecordStrict if annotations exist."""
    # Arrange
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    assert isinstance(df.model, FileRecordDateTime)

    # Act
    blake3_hash = "b" * 64
    df.set_validation_hash(blake3_hash)

    # Assert
    assert isinstance(df.model, FileRecordStrict)
    assert df.validation_hash == blake3_hash
    assert df.model.validation_hash == blake3_hash


def test_set_validation_hash_invalid_format(mock_dorsal_client, mock_file_record_dt_json):
    """Test that an invalid hash format raises a ValueError."""
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    with pytest.raises(ValueError, match="is not a valid BLAKE3 hash format"):
        df.set_validation_hash("not-a-valid-hash")


def test_delete_success(mock_dorsal_client, mock_file_record_dt_json):
    """Test a successful call to delete a file record."""
    # Arrange
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(initial_record, client=mock_dorsal_client)

    mock_response = FileDeleteResponse(file_deleted=1, tags_deleted=5)
    mock_dorsal_client.delete_file.return_value = mock_response

    assert df._is_deleted is False

    # Act
    result = df.delete()

    # Assert
    mock_dorsal_client.delete_file.assert_called_once_with(
        file_hash=df.hash, record="all", tags="all", annotations="all", api_key=None
    )
    assert df._is_deleted is True
    assert isinstance(result, FileDeleteResponse)
    assert result.file_deleted == 1


def test_delete_already_deleted_error(mock_dorsal_client, mock_file_record_dt_json):
    """Test that calling delete on an already-deleted object raises an error."""
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(initial_record, client=mock_dorsal_client)

    # Manually set the internal state to 'deleted'
    df._is_deleted = True

    with pytest.raises(DorsalError, match="This object has already been deleted"):
        df.delete()


def test_dorsal_file_repr_standard(mock_dorsal_client, mock_file_record_dt_json):
    """Test the standard __repr__ output."""
    record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(record, client=mock_dorsal_client)
    assert repr(df) == "DorsalFile[ initial_name.txt ]"


def test_dorsal_file_repr_long_filename(mock_dorsal_client, mock_file_record_dt_json):
    """Test the __repr__ output for a very long filename."""
    mock_file_record_dt_json["annotations"]["file_base"]["record"]["name"] = "a" * 100
    record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(record, client=mock_dorsal_client)

    # Expects truncation: "..aaaaaaaa..." with 62 'a's
    expected_repr = f"DorsalFile[ ..{'a' * 62} ]"
    assert repr(df) == expected_repr


def test_dorsal_file_repr_deleted(mock_dorsal_client, mock_file_record_dt_json):
    """Test the __repr__ output for a file marked as deleted."""
    record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(record, client=mock_dorsal_client)
    df._is_deleted = True  # Manually set the internal flag
    assert repr(df) == "DorsalFile[ initial_name.txt (deleted) ]"


def test_tags_setter_validation(mock_dorsal_client, mock_file_record_dt_json):
    """Test that the tags property setter enforces type constraints."""
    record = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile.from_record(record, client=mock_dorsal_client)

    # Valid tag
    valid_tag = FileTag(
        id="615f7f3b3e3f1a3a3a3a3a3a",
        name="test",
        value=True,
        private=False,
        hidden=False,
        upvotes=0,
        downvotes=0,
        origin="DorsalHub",
    )

    # Should succeed
    df.tags = [valid_tag]
    assert len(df.tags) == 1

    # Should fail with TypeError for wrong list content
    with pytest.raises(TypeError, match="All items in tags list must be FileTag objects"):
        df.tags = [valid_tag, "not_a_tag_object"]

    # Should fail with TypeError for wrong main type
    with pytest.raises(TypeError, match="Tags must be a list of FileTag objects."):
        df.tags = "this is not a list"


# --- Tests for DorsalFile Initialization and Download ---


@pytest.mark.parametrize(
    "private_flag, expected_method_called",
    [
        (True, "download_private_file_record"),
        (False, "download_public_file_record"),
    ],
)
def test_dorsal_file_init_private_flag(
    mock_dorsal_client, mock_file_record_dt_json, private_flag, expected_method_called
):
    """Test that the 'private' flag calls the correct client download method."""
    record = FileRecordDateTime(**mock_file_record_dt_json)
    getattr(mock_dorsal_client, expected_method_called).return_value = record

    df = DorsalFile(hash_string="a" * 64, private=private_flag, client=mock_dorsal_client)

    # Assert the correct method was called
    getattr(mock_dorsal_client, expected_method_called).assert_called_once_with(hash_string="a" * 64)

    # Assert the general-purpose method was NOT called
    mock_dorsal_client.download_file_record.assert_not_called()
    assert df.hash == "a" * 64


@pytest.mark.parametrize(
    "raised_exception, expected_message_part",
    [
        (AuthError(message="Auth failed."), "Authentication failed"),
        (
            RateLimitError(
                message="Too many requests",
                request_url="http://test.url",
                retry_after=60,
            ),
            "Rate limit exceeded",
        ),
        (
            BadRequestError(message="Bad request.", request_url="http://test.url"),
            "was invalid or malformed",
        ),
        (
            ForbiddenError(message="Forbidden.", request_url="http://test.url"),
            "Access denied for file hash",
        ),
        (NetworkError(message="Connection failed."), "A network error occurred"),
        (
            UnsupportedHashError(message="Bad hash type."),
            "hash string format or type is unsupported",
        ),
    ],
)
def test_dorsal_file_init_handles_specific_client_errors(mock_dorsal_client, raised_exception, expected_message_part):
    """Test that specific client errors during download are caught and wrapped."""
    mock_dorsal_client.download_file_record.side_effect = raised_exception

    with pytest.raises(DorsalClientError, match=expected_message_part):
        DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)


# --- Tests for DorsalFile Edge Cases ---


def test_set_validation_hash_no_annotations(mock_dorsal_client, mock_file_record_dt_json):
    """Test setting validation_hash on a record with no annotations does not upgrade the model."""
    # Arrange: Create a record with annotations set to None
    mock_file_record_dt_json["annotations"] = None
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record

    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    assert isinstance(df.model, FileRecordDateTime)
    assert df.model.annotations is None

    # Act
    blake3_hash = "b" * 64
    df.set_validation_hash(blake3_hash)

    # Assert: Model is still FileRecordDateTime, not upgraded to Strict
    assert isinstance(df.model, FileRecordDateTime)
    assert not isinstance(df.model, FileRecordStrict)
    assert df.validation_hash == blake3_hash
    assert df.model.validation_hash == blake3_hash


def test_dorsal_file_add_tags_bulk_success(mock_dorsal_client, mock_file_record_dt_json):
    """Test adding multiple tags (public and private) in a single batch."""
    # Arrange
    initial_record = FileRecordDateTime(**mock_file_record_dt_json)
    mock_dorsal_client.download_file_record.return_value = initial_record
    mock_dorsal_client.add_tags_to_file.return_value = MagicMock(success=True)

    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Act
    df.add_tags(public={"status": "done", "score": 10}, private={"reviewer": "alice", "internal_id": 99})

    # Assert
    mock_dorsal_client.add_tags_to_file.assert_called_once()
    _, call_kwargs = mock_dorsal_client.add_tags_to_file.call_args
    sent_tags = call_kwargs["tags"]

    assert len(sent_tags) == 4

    # helper to find tag by name in list
    def get_tag(name):
        return next((t for t in sent_tags if t.name == name), None)

    t1 = get_tag("status")
    assert t1.value == "done" and t1.private is False

    t2 = get_tag("score")
    assert t2.value == 10 and t2.private is False

    t3 = get_tag("reviewer")
    assert t3.value == "alice" and t3.private is True

    # Assert refresh was called (download called twice total: init + refresh)
    assert mock_dorsal_client.download_file_record.call_count == 2


def test_dorsal_file_add_tags_bulk_empty(mock_dorsal_client, mock_file_record_dt_json):
    """Test that calling add_tags with no arguments does nothing."""
    mock_dorsal_client.download_file_record.return_value = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Act
    df.add_tags(public={}, private=None)

    # Assert
    mock_dorsal_client.add_tags_to_file.assert_not_called()


def test_dorsal_file_add_tags_bulk_invalid_data(mock_dorsal_client, mock_file_record_dt_json):
    """Test that bulk tagging raises ValueError if Pydantic validation fails."""
    mock_dorsal_client.download_file_record.return_value = FileRecordDateTime(**mock_file_record_dt_json)
    df = DorsalFile(hash_string="a" * 64, client=mock_dorsal_client)

    # Act & Assert
    with pytest.raises(ValueError, match="Invalid tag data provided in bulk update"):
        df.add_tags(public={"bad_value": {"nested": "dict_not_allowed"}})
