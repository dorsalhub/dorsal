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

import json
import os
import pytest
from unittest.mock import patch, MagicMock
import datetime

from pydantic import BaseModel

import dorsal.file.file_annotator
from dorsal.common.model import AnnotationManualSource
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.validators.file_record import (
    FileRecordStrict,
    NewFileTag,
    ValidateTagsResult,
    Annotation,
    AnnotationSource,
    GenericFileAnnotation,
)
from dorsal.common.exceptions import (
    AuthError,
    DorsalError,
    DuplicateTagError,
    InvalidTagError,
    TaggingError,
    AuthError,
    DorsalClientError,
    AttributeConflictError,
)
from dorsal.client.validators import FileIndexResponse


@pytest.fixture
def mock_metadata_reader():
    """Mocks the MetadataReader class used by LocalFile."""
    with patch("dorsal.file.metadata_reader.MetadataReader") as mock_reader_class:
        # Configure the instance that will be created by LocalFile
        mock_reader_instance = MagicMock()
        mock_reader_class.return_value = mock_reader_instance
        yield mock_reader_instance


@pytest.fixture
def mock_file_record_strict() -> FileRecordStrict:
    """Provides a valid, complete FileRecordStrict object."""
    # This needs to be a real Pydantic object now, not a mock,
    # because LocalFile's internal logic depends on its structure.
    return FileRecordStrict(
        hash="a" * 64,
        validation_hash="b" * 64,
        source="disk",
        annotations={
            "file_base": {
                "record": {
                    "hash": "a" * 64,
                    "name": "local_test.txt",
                    "extension": ".txt",
                    "size": 123,
                    "media_type": "text/plain",
                    "all_hashes": [
                        {"id": "SHA-256", "value": "a" * 64},
                        {"id": "BLAKE3", "value": "b" * 64},
                    ],
                },
                "source": {"type": "Model", "id": "file/base", "version": "0.1.0"},
            }
        },
    )


# --- Tests Start Here ---


def test_local_file_init_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test successful initialization of a LocalFile."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    # Arrange: The metadata reader will return our complete mock record
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # Act
    lf = LocalFile(file_path)

    # Assert
    mock_metadata_reader._get_or_create_record.assert_called_once_with(
        file_path=file_path, skip_cache=False, overwrite_cache=False
    )
    assert lf.name == "local_test.txt"
    assert lf.hash == "a" * 64
    assert lf.validation_hash == "b" * 64
    assert lf._source == "disk"
    assert isinstance(lf.date_created, datetime.datetime)


def test_local_file_init_file_not_found():
    """Test that initializing with a non-existent path raises FileNotFoundError."""
    # Note: We don't use the fake filesystem (fs) here to ensure the path doesn't exist
    with pytest.raises(FileNotFoundError):
        LocalFile("/path/that/does/not/exist.xyz")


def test_local_file_properties_are_correct(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that properties like 'tags', 'to_json', and 'to_dict' work correctly."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Test tags property (should be an empty list initially)
    assert lf.tags == []

    # Test to_dict()
    as_dict = lf.to_dict()
    assert isinstance(as_dict, dict)
    assert as_dict["hash"] == "a" * 64

    # Test to_json()
    as_json = lf.to_json()
    assert isinstance(as_json, str)
    assert '"hash": "aaaaaaaa' in as_json


def test_local_file_add_tag_success_no_validation(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """Test adding a tag locally without remote validation."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    mock_response = mocker.Mock()
    mock_response.valid = True
    mocker.patch("dorsal.client.dorsal_client.DorsalClient.validate_tag", return_value=mock_response)

    # Act
    lf.add_private_tag(name="status", value="draft")

    # Assert
    assert len(lf.tags) == 1
    tag = lf.tags[0]
    assert isinstance(tag, NewFileTag)
    assert tag.name == "status"
    assert tag.value == "draft"
    assert tag.private is True


@patch("dorsal.file.dorsal_file.get_shared_dorsal_client")
def test_local_file_add_tag_with_successful_validation(
    mock_get_client, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test adding a tag with successful remote validation."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # Mock the client that will be used for validation
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)

    lf = LocalFile(file_path, client=mock_client)
    lf.add_public_tag(name="reviewed", value=True, auto_validate=True)

    mock_client.validate_tag.assert_called_once()
    assert len(lf.tags) == 1
    assert lf.tags[0].name == "reviewed"


@patch("dorsal.file.dorsal_file.get_shared_dorsal_client")
def test_local_file_add_tag_with_failed_validation(mock_get_client, mock_metadata_reader, mock_file_record_strict, fs):
    """Test that adding a tag with failed validation raises an InvalidTagError."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=False, message="Value too long.")

    lf = LocalFile(file_path, client=mock_client)

    with pytest.raises(InvalidTagError, match="Value too long."):
        lf.add_public_tag(name="invalid_tag", value="x" * 1000, auto_validate=True)

    assert len(lf.tags) == 0  # Ensure the invalid tag was not added


def test_local_file_push_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test pushing a local file record to the DorsalHub API."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_client.index_private_file_records.return_value = FileIndexResponse(
        total=1, success=1, error=0, unauthorized=0, results=[]
    )

    lf = LocalFile(file_path, client=mock_client)

    # Act: Push the record as private
    result = lf.push(private=True)

    # Assert
    mock_client.index_private_file_records.assert_called_once_with(file_records=[lf.model], api_key=None)
    assert result.success == 1


def test_add_tag_raises_error_if_no_validation_hash(mock_metadata_reader, mock_file_record_strict, fs):
    """Test ValueError is raised when adding a tag to a file without a validation_hash."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    # Arrange: Modify the record to have no validation hash
    mock_file_record_strict.validation_hash = None
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Act & Assert
    with pytest.raises(ValueError, match="Cannot add tag: File is missing a 'validation_hash'"):
        lf.add_public_tag(name="wont_work", value=True)


def test_add_tag_raises_duplicate_error(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """Test that adding the same tag twice raises DuplicateTagError."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    mock_response = mocker.Mock()
    mock_response.valid = True
    mocker.patch("dorsal.client.dorsal_client.DorsalClient.validate_tag", return_value=mock_response)

    # Act 1: Add the tag successfully
    lf.add_private_tag(name="status", value="draft")

    # Act 2 & Assert: Adding it again raises an error
    with pytest.raises(DuplicateTagError, match="Tag has already been added: status='draft'"):
        lf.add_private_tag(name="status", value="draft")


@pytest.mark.parametrize(
    "name, value, private",
    [
        (123, "draft", True),  # Invalid name type
        ("status", {"a": 1}, True),  # Invalid value type
        ("status", "draft", "True"),  # Invalid private type
    ],
)
def test_add_tag_raises_type_error_for_invalid_inputs(
    mock_metadata_reader, mock_file_record_strict, fs, name, value, private
):
    """Test that _add_local_tag raises TypeError for invalid argument types."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    with pytest.raises(TypeError):
        # Use the internal method directly to bypass the public helpers' specific signatures
        lf._add_local_tag(name=name, value=value, private=private)


# --- Tests for Push Operation ---


def test_local_file_push_public_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test pushing a local file record publicly."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_client.index_public_file_records.return_value = FileIndexResponse(
        total=1, success=1, error=0, unauthorized=0, results=[]
    )

    lf = LocalFile(file_path, client=mock_client)

    # Act: Push the record as public
    result = lf.push(private=False)

    # Assert
    mock_client.index_public_file_records.assert_called_once_with(file_records=[lf.model], api_key=None)
    mock_client.index_private_file_records.assert_not_called()
    assert result.success == 1


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_success(mock_annotator, mock_metadata_reader, mock_file_record_strict, fs):
    """Test successfully adding a new annotation."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # Arrange: Mock the annotator to return a valid Annotation object
    mock_annotation = Annotation(
        record=GenericFileAnnotation(file_hash="a" * 64, custom_field="test_value"),
        private=True,
        source=AnnotationManualSource(id="user_provided"),
    )
    mock_annotator.make_manual_annotation.return_value = mock_annotation

    mock_client = MagicMock()

    lf = LocalFile(file_path, client=mock_client)

    # Act
    lf._add_annotation(
        schema_id="dorsal/test-dataset",
        private=True,
        annotation_record={"custom_field": "test_value"},
    )

    # Assert
    assert hasattr(lf.model.annotations, "dorsal/test-dataset")
    added_annotations_list = getattr(lf.model.annotations, "dorsal/test-dataset")
    assert isinstance(added_annotations_list, list)
    assert len(added_annotations_list) == 1

    added_annotation = added_annotations_list[0]
    assert isinstance(added_annotation, Annotation)
    assert added_annotation.record.custom_field == "test_value"
    assert added_annotation.private is True


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_raises_conflict_error(mock_annotator, mock_metadata_reader, mock_file_record_strict, fs):
    """Test that adding an existing annotation without overwrite=True raises an error."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotation = Annotation(
        record=GenericFileAnnotation(), private=True, source=AnnotationManualSource(id="conflict_test_id")
    )
    mock_annotator.make_manual_annotation.return_value = mock_annotation

    mock_client = MagicMock()

    lf = LocalFile(file_path, client=mock_client)

    lf._add_annotation(schema_id="dorsal/test-dataset", private=True, annotation_record={})

    with pytest.raises(
        AttributeConflictError,
        match="already exists.*Set overwrite=True to update",
    ):
        lf._add_annotation(
            schema_id="dorsal/test-dataset",
            private=True,
            annotation_record={},
            overwrite=False,
        )


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_succeeds_with_overwrite(mock_annotator, mock_metadata_reader, mock_file_record_strict, fs):
    """Test that adding an existing annotation with overwrite=True succeeds."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict
    mock_annotation_1 = Annotation(
        record={"version": 1}, private=True, source=AnnotationManualSource(id="overwrite_test_id")
    )
    mock_annotation_2 = Annotation(
        record={"version": 2}, private=True, source=AnnotationManualSource(id="overwrite_test_id")
    )
    mock_annotator.make_manual_annotation.side_effect = [
        mock_annotation_1,
        mock_annotation_2,
    ]

    mock_client = MagicMock()

    lf = LocalFile(file_path, client=mock_client)
    lf._add_annotation(schema_id="dorsal/test-dataset", private=True, annotation_record={})

    # Check list index 0
    assert getattr(lf.model.annotations, "dorsal/test-dataset")[0].record.version == 1

    # Act: Add again with overwrite=True
    lf._add_annotation(
        schema_id="dorsal/test-dataset",
        private=True,
        annotation_record={},
        overwrite=True,
    )

    # Assert
    assert mock_annotator.make_manual_annotation.call_count == 2
    # Check list index 0 (it should have been updated in place)
    assert getattr(lf.model.annotations, "dorsal/test-dataset")[0].record.version == 2


def test_save_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that .save() writes a valid JSON file to disk."""
    file_path = "/fake/local.txt"
    output_path = "/fake/output_record.json"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Act
    lf.save(output_path)

    # Assert
    assert os.path.exists(output_path)

    with open(output_path, "r") as f:
        data = json.load(f)

    # Verify core stricture matches
    assert data["hash"] == mock_file_record_strict.hash
    assert data["validation_hash"] == mock_file_record_strict.validation_hash
    # Verify local_attributes were injected
    assert "local_attributes" in data
    assert data["local_attributes"]["file_path"] == file_path


def test_save_creates_nested_directories(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that .save() automatically creates missing parent directories."""
    file_path = "/fake/local.txt"
    # A path where 'exports' and '2025' do not exist yet
    output_path = "/fake/exports/2025/record.json"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Act
    lf.save(output_path)

    # Assert
    assert os.path.exists(output_path)


def test_from_json_success(mock_file_record_strict, fs):
    """Test rehydrating a LocalFile from a JSON file."""
    json_path = "/fake/record.json"
    original_file_path = "/fake/original_file.txt"

    # Create the original file so check_file_exists=True (optional) wouldn't fail
    fs.create_file(original_file_path)

    # Prepare valid JSON content
    # We add local_attributes to simulate a real saved file
    record_data = mock_file_record_strict.model_dump(by_alias=True, mode="json")
    record_data["local_attributes"] = {"file_path": original_file_path}

    fs.create_file(json_path, contents=json.dumps(record_data))

    # Act
    lf = LocalFile.from_json(json_path)

    # Assert
    assert isinstance(lf, LocalFile)
    assert lf.hash == mock_file_record_strict.hash
    # Ensure it didn't trigger a new metadata read (source should remain what was in JSON)
    assert lf.model.source == mock_file_record_strict.source
    # Ensure the internal file path was restored from local_attributes
    assert lf._file_path == original_file_path


def test_from_json_round_trip(mock_metadata_reader, mock_file_record_strict, fs):
    """
    Gold Standard Test: Save an object, load it back,
    and ensure the rehydrated object matches the original.
    """
    file_path = "/fake/data.txt"
    json_path = "/fake/checkpoint.json"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # 1. Create original
    original_lf = LocalFile(file_path)
    # Add a tag to make it interesting
    # (Mock validation for tag addition)
    with patch("dorsal.file.dorsal_file.get_shared_dorsal_client"):
        # Bypassing validation logic for simplicity in this IO test
        original_lf.model.tags.append(NewFileTag(name="trip", value="round", private=True))

    # 2. Save
    original_lf.save(json_path)

    # 3. Load
    loaded_lf = LocalFile.from_json(json_path)

    # 4. Compare
    assert loaded_lf.hash == original_lf.hash
    assert loaded_lf._file_path == original_lf._file_path
    assert len(loaded_lf.tags) == len(original_lf.tags)
    assert loaded_lf.tags[0].name == "trip"


def test_from_json_file_not_found(fs):
    """Test that from_json raises FileNotFoundError if the JSON path doesn't exist."""
    with pytest.raises(FileNotFoundError, match="JSON record not found"):
        LocalFile.from_json("/non/existent/path.json")


def test_from_json_invalid_json_syntax(fs):
    """Test that from_json raises ValueError on corrupt JSON."""
    json_path = "/fake/corrupt.json"
    fs.create_file(json_path, contents="{ invalid_json: ...")

    with pytest.raises(ValueError, match="Invalid JSON"):
        LocalFile.from_json(json_path)


def test_from_json_invalid_schema(fs):
    """Test that from_json raises ValueError if JSON doesn't match FileRecordStrict."""
    json_path = "/fake/bad_schema.json"
    # Missing required field 'hash'
    fs.create_file(json_path, contents='{"source": "disk"}')

    with pytest.raises(ValueError, match="JSON data is not a valid FileRecordStrict"):
        LocalFile.from_json(json_path)


def test_from_json_check_file_exists_fail(mock_file_record_strict, fs):
    """
    Test check_file_exists=True raises FileNotFoundError
    if the *original* file (pointed to by JSON) is missing.
    """
    json_path = "/fake/record.json"
    ghost_path = "/fake/ghost.txt"  # This file is NOT created in fs

    record_data = mock_file_record_strict.model_dump(by_alias=True, mode="json")
    record_data["local_attributes"] = {"file_path": ghost_path}

    fs.create_file(json_path, contents=json.dumps(record_data))

    with pytest.raises(FileNotFoundError, match="Serialized record points to"):
        LocalFile.from_json(json_path, check_file_exists=True)


def test_add_label(mock_metadata_reader, mock_file_record_strict, fs):
    """Test the add_label convenience method."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Act
    lf.add_label("important_doc")

    # Assert
    assert len(lf.tags) == 1
    tag = lf.tags[0]
    assert tag.name == "label"
    assert tag.value == "important_doc"
    assert tag.private is True  # Should always be private


@patch("dorsal.file.dorsal_file.get_shared_dorsal_client")
def test_add_tag_raises_auth_error_when_client_missing_and_auto_validate_true(
    mock_get_client, mock_metadata_reader, mock_file_record_strict, fs
):
    """
    CRITICAL: Test that setting auto_validate=True raises an error if
    no client is available (fixing the silent failure issue).
    """
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # Simulate get_shared_dorsal_client failing to find an API key
    mock_get_client.side_effect = AuthError("No API key")

    lf = LocalFile(file_path, client=None)  # No client injected

    # Act & Assert
    with pytest.raises(AuthError, match="Cannot perform auto-validation"):
        lf.add_public_tag("test", "val", auto_validate=True)

    # Ensure tag was NOT added
    assert len(lf.tags) == 0


def test_validate_tags_explicit_success(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """Test explicit validate_tags method success."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    # Mock client
    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)

    lf = LocalFile(file_path, client=mock_client)

    # Add a tag lazily (no network)
    lf.add_public_tag("status", "pending", auto_validate=False)

    # Act: Explicitly validate
    result = lf.validate_tags()

    # Assert
    assert result.valid is True
    mock_client.validate_tag.assert_called_once()


def test_validate_tags_explicit_failure(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """Test explicit validate_tags method failure raises InvalidTagError."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=False, message="Banned word")

    lf = LocalFile(file_path, client=mock_client)
    lf.add_public_tag("status", "bad_word")

    # Act & Assert
    with pytest.raises(InvalidTagError, match="Banned word"):
        lf.validate_tags()


def test_validate_tags_offline_error(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that calling validate_tags in offline mode raises DorsalError."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path, offline=True)

    # Act & Assert
    with pytest.raises(DorsalError, match="LocalFile is in OFFLINE mode"):
        lf.validate_tags()


def test_validate_tags_empty_list(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that validate_tags returns None early if there are no tags."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    lf = LocalFile(file_path, client=mock_client)

    # Act
    result = lf.validate_tags()

    # Assert
    assert result is None
    mock_client.validate_tag.assert_not_called()


def test_local_file_get_annotations_integration(mock_metadata_reader, mock_file_record_strict, fs):
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    # Inject two annotations into the record fixture
    ann1 = Annotation(record=GenericFileAnnotation(data="one"), private=True, source=AnnotationManualSource(id="src1"))
    ann2 = Annotation(record=GenericFileAnnotation(data="two"), private=True, source=AnnotationManualSource(id="src2"))

    mock_file_record_strict.annotations.__pydantic_extra__ = {"test/data": [ann1, ann2]}
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    # Test: Get All
    results = lf.get_annotations("test/data")
    assert len(results) == 2

    # Test: Filter
    filtered = lf.get_annotations("test/data", source_id="src1")
    assert len(filtered) == 1
    assert filtered[0].record.data == "one"
