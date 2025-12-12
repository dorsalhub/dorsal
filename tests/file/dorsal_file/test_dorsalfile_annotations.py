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
from dorsal.file.dorsal_file import LocalFile
from dorsal.common.exceptions import AttributeConflictError, FileAnnotatorError
from pydantic import ValidationError
from types import SimpleNamespace


@pytest.fixture
def mock_local_file():
    """Creates a LocalFile with a mocked internal model."""
    with patch("dorsal.file.dorsal_file.LocalFile.__init__", return_value=None):
        lf = LocalFile("dummy.txt")

        lf._file_path = "dummy.txt"
        lf.hash = "a" * 64
        lf.validation_hash = "b" * 64
        lf._model_runner = MagicMock()

        lf.model = MagicMock()
        lf.model.annotations = SimpleNamespace()

        lf.model.annotations.__pydantic_extra__ = {}
        lf.model.annotations.model_fields_set = set()

        # Initialize core properties to None for tests
        lf.pdf = None
        lf.mediainfo = None
        lf.ebook = None
        lf.office = None

        lf._populate = MagicMock()

        return lf


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_annotate_using_pipeline_step_success(mock_annotator, mock_local_file):
    """Tests successful annotation via pipeline step config."""
    step_config = {"annotation_model": ("mod", "cls"), "schema_id": "test/schema"}
    mock_annotation = MagicMock()
    # Setup source ID for the mock to pass collision checks
    mock_annotation.source.id = "pipeline_source"
    mock_annotation.source.version = "1.0"
    mock_annotation.source.variant = None

    mock_annotator.annotate_file_using_pipeline_step.return_value = mock_annotation

    # Execute
    mock_local_file._annotate_using_pipeline_step(pipeline_step_config=step_config, private=True)

    # Verify attribute was set as a LIST
    assert getattr(mock_local_file.model.annotations, "test/schema") == [mock_annotation]


def test_annotate_using_pipeline_step_invalid_schema(mock_local_file):
    """Tests error with invalid schema ID."""
    # Pydantic validation happens first
    with pytest.raises(ValidationError):
        mock_local_file._annotate_using_pipeline_step(
            pipeline_step_config={"schema_id": "bad_id", "annotation_model": ("a", "b")}, private=True
        )


# --- Tests for _annotate_using_model_and_validator ---


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_annotate_model_validator_success(mock_annotator, mock_local_file):
    """Tests successful annotation via explicit model/validator."""
    mock_annotation = MagicMock()
    mock_annotation.source.id = "manual_source"
    mock_annotation.source.version = "1.0"
    mock_annotation.source.variant = None

    mock_annotator.annotate_file_using_model_and_validator.return_value = mock_annotation

    dummy_model_cls = MagicMock()
    dummy_model_cls.__name__ = "DummyModel"
    dummy_model_cls.__str__ = lambda x: "DummyModel"

    dummy_validator = MagicMock()
    dummy_validator.__name__ = "DummyValidator"
    dummy_validator.__str__ = lambda x: "DummyValidator"

    mock_local_file._annotate_using_model_and_validator(
        schema_id="test/manual",
        private=False,
        annotation_model=dummy_model_cls,
        validation_model=dummy_validator,
        overwrite=True,
    )

    mock_annotator.annotate_file_using_model_and_validator.assert_called_once()
    # Verify attribute was set as a LIST
    assert getattr(mock_local_file.model.annotations, "test/manual") == [mock_annotation]


@patch("dorsal.file.file_annotator.FILE_ANNOTATOR")
def test_annotate_model_validator_failure(mock_annotator, mock_local_file):
    """Tests that FileAnnotatorError is re-raised."""
    mock_annotator.annotate_file_using_model_and_validator.side_effect = FileAnnotatorError("Boom")

    dummy_model = MagicMock()
    dummy_model.__name__ = "DummyModel"

    with pytest.raises(FileAnnotatorError):
        mock_local_file._annotate_using_model_and_validator(
            schema_id="test/fail", private=True, annotation_model=dummy_model
        )


# --- Tests for remove_annotation ---


def test_remove_annotation_missing(mock_local_file):
    """Tests removing an annotation that doesn't exist (safe no-op)."""
    mock_local_file.remove_annotation("non/existent")
    mock_local_file._populate.assert_not_called()


def test_remove_annotation_success(mock_local_file):
    """Tests successful removal."""
    # Mock an annotation with source.id to satisfy remove_annotation logic
    mock_ann = MagicMock()
    mock_ann.source.id = "delete_me"

    setattr(mock_local_file.model.annotations, "test/remove", [mock_ann])

    mock_local_file.remove_annotation("test/remove")

    assert not hasattr(mock_local_file.model.annotations, "test/remove")
    mock_local_file._populate.assert_called_once()


# --- Helper Test: _set_annotation_attribute ---


def test_set_annotation_conflict(mock_local_file):
    """Tests that overwriting without overwrite=True raises error."""
    schema_id = "test/conflict"

    # Mock an existing annotation object with a specific source ID
    existing_mock = MagicMock()
    existing_mock.source.id = "conflict_id"
    existing_mock.source.version = "1.0"
    existing_mock.source.variant = None

    # Set it as a list on the model
    setattr(mock_local_file.model.annotations, schema_id, [existing_mock])

    # Create a new annotation mock with the SAME source ID
    new_mock = MagicMock()
    new_mock.source.id = "conflict_id"
    new_mock.source.version = "1.0"
    new_mock.source.variant = None

    with pytest.raises(AttributeConflictError):
        mock_local_file._set_annotation_attribute(schema_id=schema_id, annotation=new_mock, overwrite=False)


# --- Tests for Retrieval Methods (get_annotations) ---


def test_get_annotations_returns_list(mock_local_file):
    """Test the standard list retrieval behavior."""
    # 1. Setup data
    schema_id = "test/multi"
    ann1 = MagicMock()
    ann1.source.id = "source_1"
    ann2 = MagicMock()
    ann2.source.id = "source_2"

    setattr(mock_local_file.model.annotations, schema_id, [ann1, ann2])

    # 2. Test getting all
    all_anns = mock_local_file.get_annotations(schema_id)
    assert isinstance(all_anns, list)
    assert len(all_anns) == 2

    # 3. Test filtering
    filtered = mock_local_file.get_annotations(schema_id, source_id="source_1")
    assert len(filtered) == 1
    assert filtered[0].source.id == "source_1"

    # 4. Test missing
    empty = mock_local_file.get_annotations("test/missing")
    assert isinstance(empty, list)
    assert len(empty) == 0
