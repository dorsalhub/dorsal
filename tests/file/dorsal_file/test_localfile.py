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

import json
import os
import pathlib
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
    PartialIndexingError,
)
from dorsal.client.validators import FileIndexResponse


@pytest.fixture
def mock_metadata_reader():
    """Mocks the MetadataReader class used by LocalFile."""
    with patch("dorsal.file.metadata_reader.MetadataReader") as mock_reader_class:
        mock_reader_instance = MagicMock()
        mock_reader_class.return_value = mock_reader_instance
        yield mock_reader_instance


@pytest.fixture
def mock_file_record_strict() -> FileRecordStrict:
    """Provides a valid, complete FileRecordStrict object."""
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


def test_local_file_init_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test successful initialization of a LocalFile."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    expected_path = os.path.abspath(file_path)

    mock_metadata_reader._get_or_create_record.assert_called_once_with(
        file_path=expected_path, skip_cache=False, overwrite_cache=False, follow_symlinks=True
    )
    assert lf.name == "local_test.txt"
    assert lf.hash == "a" * 64
    assert lf.validation_hash == "b" * 64
    assert lf._source == "disk"
    assert isinstance(lf.date_created, datetime.datetime)


def test_local_file_init_file_not_found():
    """Test that initializing with a non-existent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        LocalFile("/path/that/does/not/exist.xyz")


def test_local_file_properties_are_correct(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that properties like 'tags', 'to_json', and 'to_dict' work correctly."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    assert lf.tags == []

    as_dict = lf.to_dict()
    assert isinstance(as_dict, dict)
    assert as_dict["hash"] == "a" * 64

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

    lf.add_private_tag(name="status", value="draft")

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
        lf.add_public_tag(name="invalid_tag", value="valid_local_length", auto_validate=True)


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

    result = lf.push(public=False)

    mock_client.index_private_file_records.assert_called_once_with(file_records=[lf.model], api_key=None)
    assert result.success == 1


def test_add_tag_raises_error_if_no_validation_hash(mock_metadata_reader, mock_file_record_strict, fs):
    """Test ValueError is raised when adding a tag to a file without a validation_hash."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    mock_file_record_strict.validation_hash = None
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

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

    lf.add_private_tag(name="status", value="draft")

    with pytest.raises(DuplicateTagError, match="Tag has already been added: status='draft'"):
        lf.add_private_tag(name="status", value="draft")


@pytest.mark.parametrize(
    "name, value, private",
    [
        (123, "draft", True),
        ("status", {"a": 1}, True),
        ("status", "draft", "True"),
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
        lf._add_local_tag(name=name, value=value, private=private)


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

    result = lf.push(public=True)

    mock_client.index_public_file_records.assert_called_once_with(file_records=[lf.model], api_key=None)
    mock_client.index_private_file_records.assert_not_called()
    assert result.success == 1


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_success(mock_annotator, mock_metadata_reader, mock_file_record_strict, fs):
    """Test successfully adding a new annotation."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotation = Annotation(
        record=GenericFileAnnotation(file_hash="a" * 64, custom_field="test_value"),
        private=True,
        source=AnnotationManualSource(id="test"),
    )
    mock_annotator.make_manual_annotation.return_value = mock_annotation

    mock_client = MagicMock()

    lf = LocalFile(file_path, client=mock_client)

    lf._add_annotation(
        schema_id="dorsal/test-dataset",
        public=False,
        annotation_record={"custom_field": "test_value"},
    )

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

    lf._add_annotation(schema_id="dorsal/test-dataset", public=False, annotation_record={})

    with pytest.raises(
        AttributeConflictError,
        match="already exists.*Set overwrite=True to update",
    ):
        lf._add_annotation(
            schema_id="dorsal/test-dataset",
            public=False,
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
    lf._add_annotation(schema_id="dorsal/test-dataset", public=False, annotation_record={})

    assert getattr(lf.model.annotations, "dorsal/test-dataset")[0].record.version == 1

    lf._add_annotation(
        schema_id="dorsal/test-dataset",
        public=False,
        annotation_record={},
        overwrite=True,
    )

    assert mock_annotator.make_manual_annotation.call_count == 2

    assert getattr(lf.model.annotations, "dorsal/test-dataset")[0].record.version == 2


def test_save_success(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that .save() writes a valid JSON file to disk."""
    file_path = "/fake/local.txt"
    output_path = "/fake/output_record.json"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    lf.save(output_path)

    assert os.path.exists(output_path)

    with open(output_path, "r") as f:
        data = json.load(f)

    assert data["hash"] == mock_file_record_strict.hash
    assert data["validation_hash"] == mock_file_record_strict.validation_hash
    assert "local_attributes" in data
    assert data["local_attributes"]["file_path"] == file_path


def test_save_creates_nested_directories(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that .save() automatically creates missing parent directories."""
    file_path = "/fake/local.txt"
    output_path = "/fake/exports/2025/record.json"
    fs.create_file(file_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    lf.save(output_path)

    assert os.path.exists(output_path)


def test_from_json_success(mock_file_record_strict, fs):
    """Test rehydrating a LocalFile from a JSON file."""
    json_path = "/fake/record.json"
    original_file_path = "/fake/original_file.txt"

    fs.create_file(original_file_path)

    record_data = mock_file_record_strict.model_dump(by_alias=True, mode="json")
    record_data["local_attributes"] = {"file_path": original_file_path}

    fs.create_file(json_path, contents=json.dumps(record_data))

    lf = LocalFile.from_json(json_path)

    assert isinstance(lf, LocalFile)
    assert lf.hash == mock_file_record_strict.hash
    assert lf.model.source == mock_file_record_strict.source
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

    original_lf = LocalFile(file_path)

    with patch("dorsal.file.dorsal_file.get_shared_dorsal_client"):
        original_lf.model.tags.append(NewFileTag(name="trip", value="round", private=True))

    original_lf.save(json_path)

    loaded_lf = LocalFile.from_json(json_path)

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
    fs.create_file(json_path, contents='{"source": "disk"}')

    with pytest.raises(ValueError, match="JSON data is not a valid FileRecordStrict"):
        LocalFile.from_json(json_path)


def test_from_json_check_file_exists_fail(mock_file_record_strict, fs):
    """
    Test check_file_exists=True raises FileNotFoundError
    if the *original* file (pointed to by JSON) is missing.
    """
    json_path = "/fake/record.json"
    ghost_path = "/fake/ghost.txt"

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

    lf.add_label("important_doc")

    assert len(lf.tags) == 1
    tag = lf.tags[0]
    assert tag.name == "label"
    assert tag.value == "important_doc"
    assert tag.private is True


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

    mock_get_client.side_effect = AuthError("No API key")

    lf = LocalFile(file_path, client=None)

    with pytest.raises(AuthError, match="Cannot perform auto-validation"):
        lf.add_public_tag("test", "val", auto_validate=True)

    assert len(lf.tags) == 0


def test_validate_tags_explicit_success(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """Test explicit validate_tags method success."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)

    lf = LocalFile(file_path, client=mock_client)

    lf.add_public_tag("status", "pending", auto_validate=False)

    result = lf.validate_tags()

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

    with pytest.raises(InvalidTagError, match="Banned word"):
        lf.validate_tags()


def test_validate_tags_offline_error(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that calling validate_tags in offline mode raises DorsalError."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path, offline=True)

    with pytest.raises(DorsalError, match="LocalFile is in OFFLINE mode"):
        lf.validate_tags()


def test_validate_tags_empty_list(mock_metadata_reader, mock_file_record_strict, fs):
    """Test that validate_tags returns None early if there are no tags."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    lf = LocalFile(file_path, client=mock_client)

    result = lf.validate_tags()

    assert result is None
    mock_client.validate_tag.assert_not_called()


def test_local_file_get_annotations_integration(mock_metadata_reader, mock_file_record_strict, fs):
    file_path = "/fake/local.txt"
    fs.create_file(file_path)

    ann1 = Annotation(record=GenericFileAnnotation(data="one"), private=True, source=AnnotationManualSource(id="src1"))
    ann2 = Annotation(record=GenericFileAnnotation(data="two"), private=True, source=AnnotationManualSource(id="src2"))

    mock_file_record_strict.annotations.__pydantic_extra__ = {"test/data": [ann1, ann2]}
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    lf = LocalFile(file_path)

    results = lf.get_annotations("test/data")
    assert len(results) == 2

    filtered = lf.get_annotations("test/data", source_id="src1")
    assert len(filtered) == 1
    assert filtered[0].record.data == "one"


def test_push_strict_raises_on_partial_failure(mock_metadata_reader, mock_file_record_strict, fs):
    file_path = "/fake.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()

    mock_annotation_error = MagicMock()
    mock_annotation_error.name = "classification"
    mock_annotation_error.status = "error"
    mock_annotation_error.detail = "Schema mismatch"

    mock_result = MagicMock()
    mock_result.annotations = [mock_annotation_error]
    mock_result.tags = []

    mock_response = MagicMock(spec=FileIndexResponse)
    mock_response.total = 1
    mock_response.success = 0
    mock_response.error = 1
    mock_response.results = [mock_result]

    mock_client.index_private_file_records.return_value = mock_response

    lf = LocalFile(file_path, client=mock_client)

    with pytest.raises(PartialIndexingError) as exc_info:
        lf.push(strict=True)

    assert "Strict Mode enabled" in str(exc_info.value)
    assert "classification" in str(exc_info.value.summary)


def test_symlink_resolution_enabled_by_default(mock_metadata_reader, mock_file_record_strict, fs, mocker):
    """
    Verifies that by default, LocalFile resolves a symlink to its target
    for the MetadataReader (hashing), but preserves symlink info in local_attributes.
    """
    target_path = "/usr/bin/python3.14"
    link_path = "/usr/bin/python3"

    fs.create_file(target_path, contents="binary_content")
    fs.create_symlink(link_path, target_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    expected_target_abs = os.path.abspath(target_path)
    mocker.patch("pathlib.Path.resolve", return_value=pathlib.Path(expected_target_abs))

    lf = LocalFile(link_path)

    expected_target = os.path.abspath(target_path)

    args, kwargs = mock_metadata_reader._get_or_create_record.call_args
    assert kwargs["file_path"] == expected_target

    data = lf.to_dict()
    assert "local_attributes" in data
    assert data["local_attributes"]["is_symlink"] is True
    assert data["local_attributes"]["file_path"] == link_path


def test_symlink_resolution_not_enabled(mock_metadata_reader, mock_file_record_strict, fs):
    """
    Verifies that if we pass follow_symlinks=False, we treat the link as the file.
    """
    target_path = "/usr/bin/python3.14"
    link_path = "/usr/bin/python3"

    fs.create_file(target_path, contents="binary_content")
    fs.create_symlink(link_path, target_path)

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    LocalFile(link_path, follow_symlinks=False)

    args, kwargs = mock_metadata_reader._get_or_create_record.call_args
    assert kwargs["file_path"] == link_path


def test_broken_symlink_fallback(mock_metadata_reader, mock_file_record_strict, fs):
    """
    Verifies that if a symlink is broken, LocalFile handles the crash gracefully
    and defaults to processing the link path itself.
    """
    link_path = "/broken_link"

    fs.create_symlink(link_path, "/does/not/exist")

    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    LocalFile(link_path)

    args, kwargs = mock_metadata_reader._get_or_create_record.call_args
    assert kwargs["file_path"] == link_path


@patch("dorsal.file.dorsal_file.get_shared_dorsal_client")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_crud_lifecycle(
    mock_annotator, mock_get_client, mock_metadata_reader, mock_file_record_strict, fs
):
    """
    Tests the full lifecycle of adding (private/public), getting, and removing annotations.
    """
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.make_schema_validator.return_value = MagicMock()

    def mock_make_annotation(annotation, **kwargs):
        return Annotation(
            record=GenericFileAnnotation(**annotation),
            private=kwargs.get("private", True),
            source=AnnotationManualSource(id=kwargs.get("source_id", "default_src")),
        )

    mock_annotator.make_manual_annotation.side_effect = mock_make_annotation

    lf = LocalFile(file_path)

    lf.add_private_annotation(
        schema_id="test/private-schema", annotation_record={"key": "secret_value"}, source="src_A"
    )

    lf.add_public_annotation(schema_id="test/public-schema", annotation_record={"key": "public_value"}, source="src_B")

    private_anns = lf.get_annotations("test/private-schema")
    assert len(private_anns) == 1
    assert private_anns[0].record.key == "secret_value"
    assert private_anns[0].private is True
    assert private_anns[0].source.id == "src_A"

    public_anns = lf.get_annotations("test/public-schema")
    assert len(public_anns) == 1
    assert public_anns[0].record.key == "public_value"
    assert public_anns[0].private is False

    lf.remove_annotation("test/private-schema", source_id="src_A")
    assert len(lf.get_annotations("test/private-schema")) == 0

    lf.remove_annotation("test/public-schema")
    assert len(lf.get_annotations("test/public-schema")) == 0


@patch("dorsal.file.dorsal_file.get_shared_dorsal_client")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_annotation_wrappers_call_correct_helper(
    mock_annotator, mock_get_client, mock_metadata_reader, mock_file_record_strict, fs
):
    """Verifies _add_annotation is called correctly by public/private wrappers."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.make_schema_validator.return_value = MagicMock()

    mock_annotator.make_manual_annotation.return_value = Annotation(
        record=GenericFileAnnotation(x=1), private=True, source=AnnotationManualSource(id="s")
    )

    lf = LocalFile(file_path)

    lf.add_private_annotation(schema_id="foo/bar", annotation_record={"x": 1})
    assert mock_annotator.make_manual_annotation.call_args.kwargs["private"] is True

    lf.add_public_annotation(schema_id="foo/baz", annotation_record={"x": 1})
    assert mock_annotator.make_manual_annotation.call_args.kwargs["private"] is False


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_classification_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_classification using the real build_classification_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="cls"),
    )

    lf = LocalFile(file_path)

    lf.add_classification(labels=["cat", "dog"], score_explanation="Visual check")

    anns = lf.get_annotations("open/classification")
    assert len(anns) == 1
    record = anns[0].record

    assert record.labels == [{"label": "cat"}, {"label": "dog"}]
    assert record.score_explanation == "Visual check"


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_embedding_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_embedding using the real build_embedding_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="emb"),
    )

    lf = LocalFile(file_path)

    lf.add_embedding(vector=[0.1, 0.5, -0.9], model="clip-vit-b32")

    anns = lf.get_annotations("open/embedding")
    assert len(anns) == 1
    assert anns[0].record.vector == [0.1, 0.5, -0.9]
    assert anns[0].record.model == "clip-vit-b32"


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_llm_output_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_llm_output using the real build_llm_output_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="llm"),
    )

    lf = LocalFile(file_path)

    lf.add_llm_output(model="gpt-4", response_data={"summary": "It was good."})

    anns = lf.get_annotations("open/llm-output")
    assert len(anns) == 1
    assert anns[0].record.model == "gpt-4"
    assert anns[0].record.response_data == '{"summary": "It was good."}'


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_location_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_location using the real build_location_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="loc"),
    )

    lf = LocalFile(file_path)

    lf.add_location(longitude=12.5, latitude=55.2, camera_make="Canon")

    anns = lf.get_annotations("open/geolocation")
    assert len(anns) == 1
    record = anns[0].record

    assert record.type == "Feature"
    assert record.geometry == {"type": "Point", "coordinates": [12.5, 55.2]}
    assert record.properties["camera_make"] == "Canon"


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_transcription_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_transcription using the real build_transcription_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="trans"),
    )

    lf = LocalFile(file_path)

    lf.add_transcription(text="Hello world", language="eng")

    anns = lf.get_annotations("open/audio-transcription")
    assert len(anns) == 1
    assert anns[0].record.text == "Hello world"
    assert anns[0].record.language == "eng"


@patch("dorsal.file.dorsal_file.get_open_schema_validator")
@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_add_regression_integration(
    mock_annotator, mock_get_validator, mock_metadata_reader, mock_file_record_strict, fs
):
    """Test add_regression using the real build_single_point_regression_record helper."""
    file_path = "/fake/local.txt"
    fs.create_file(file_path)
    mock_metadata_reader._get_or_create_record.return_value = mock_file_record_strict

    mock_annotator.make_manual_annotation.side_effect = lambda annotation, **kwargs: Annotation(
        record=GenericFileAnnotation(**annotation),
        private=kwargs.get("private", True),
        source=AnnotationManualSource(id="reg"),
    )

    lf = LocalFile(file_path)

    lf.add_regression(value=42.0, target="age", statistic="mean", unit="years")

    anns = lf.get_annotations("open/regression")
    assert len(anns) == 1
    record = anns[0].record

    assert record.target == "age"
    assert record.unit == "years"
    assert len(record.points) == 1
    assert record.points[0]["value"] == 42.0
    assert record.points[0]["statistic"] == "mean"
