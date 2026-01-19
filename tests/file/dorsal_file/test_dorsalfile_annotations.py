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

import datetime
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

    mock_annotation.source.id = "pipeline_source"
    mock_annotation.source.version = "1.0"
    mock_annotation.source.variant = None

    mock_annotator.annotate_file_using_pipeline_step.return_value = mock_annotation

    mock_local_file._annotate_using_pipeline_step(pipeline_step_config=step_config, private=True)

    assert getattr(mock_local_file.model.annotations, "test/schema") == [mock_annotation]


def test_annotate_using_pipeline_step_invalid_schema(mock_local_file):
    """Tests error with invalid schema ID."""

    with pytest.raises(ValidationError):
        mock_local_file._annotate_using_pipeline_step(
            pipeline_step_config={"schema_id": "bad_id", "annotation_model": ("a", "b")}, private=True
        )


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


def test_remove_annotation_missing(mock_local_file):
    """Tests removing an annotation that doesn't exist (safe no-op)."""
    mock_local_file.remove_annotation("non/existent")
    mock_local_file._populate.assert_not_called()


def test_remove_annotation_success(mock_local_file):
    """Tests successful removal."""

    mock_ann = MagicMock()
    mock_ann.source.id = "delete_me"

    setattr(mock_local_file.model.annotations, "test/remove", [mock_ann])

    mock_local_file.remove_annotation("test/remove")

    assert not hasattr(mock_local_file.model.annotations, "test/remove")
    mock_local_file._populate.assert_called_once()


def test_set_annotation_conflict(mock_local_file):
    """Tests that overwriting without overwrite=True raises error."""
    schema_id = "test/conflict"

    existing_mock = MagicMock()
    existing_mock.source.id = "conflict_id"
    existing_mock.source.version = "1.0"
    existing_mock.source.variant = None

    setattr(mock_local_file.model.annotations, schema_id, [existing_mock])

    new_mock = MagicMock()
    new_mock.source.id = "conflict_id"
    new_mock.source.version = "1.0"
    new_mock.source.variant = None

    with pytest.raises(AttributeConflictError):
        mock_local_file._set_annotation_attribute(schema_id=schema_id, annotation=new_mock, overwrite=False)


def test_get_annotations_returns_list(mock_local_file):
    """Test the standard list retrieval behavior."""

    schema_id = "test/multi"
    ann1 = MagicMock()
    ann1.source.id = "source_1"
    ann2 = MagicMock()
    ann2.source.id = "source_2"

    setattr(mock_local_file.model.annotations, schema_id, [ann1, ann2])

    all_anns = mock_local_file.get_annotations(schema_id)
    assert isinstance(all_anns, list)
    assert len(all_anns) == 2

    filtered = mock_local_file.get_annotations(schema_id, source_id="source_1")
    assert len(filtered) == 1
    assert filtered[0].source.id == "source_1"

    empty = mock_local_file.get_annotations("test/missing")
    assert isinstance(empty, list)
    assert len(empty) == 0


def test_get_latest_annotation_success(mock_local_file):
    """Test retrieving the latest annotation by date_modified."""
    schema_id = "test/dates"
    now = datetime.datetime.now(datetime.UTC)

    ann_old = MagicMock()
    ann_old.date_modified = now - datetime.timedelta(days=1)
    ann_old.record.data = "old"

    ann_new = MagicMock()
    ann_new.date_modified = now
    ann_new.record.data = "new"

    ann_mid = MagicMock()
    ann_mid.date_modified = now - datetime.timedelta(hours=1)
    ann_mid.record.data = "mid"

    setattr(mock_local_file.model.annotations, schema_id, [ann_old, ann_new, ann_mid])

    latest = mock_local_file.get_latest_annotation(schema_id)

    assert latest is not None
    assert latest.record.data == "new"


def test_get_latest_annotation_with_source_filter(mock_local_file):
    """Test retrieving latest annotation filtered by source ID first."""
    schema_id = "test/dates_source"
    now = datetime.datetime.now(datetime.UTC)

    ann_wrong_source = MagicMock()
    ann_wrong_source.date_modified = now + datetime.timedelta(hours=1)
    ann_wrong_source.source.id = "src_B"

    ann_src_a_new = MagicMock()
    ann_src_a_new.date_modified = now
    ann_src_a_new.source.id = "src_A"

    ann_src_a_old = MagicMock()
    ann_src_a_old.date_modified = now - datetime.timedelta(days=1)
    ann_src_a_old.source.id = "src_A"

    setattr(mock_local_file.model.annotations, schema_id, [ann_wrong_source, ann_src_a_new, ann_src_a_old])

    latest = mock_local_file.get_latest_annotation(schema_id, source_id="src_A")

    assert latest is not None
    assert latest.source.id == "src_A"
    assert latest == ann_src_a_new


def test_get_latest_annotation_empty(mock_local_file):
    """Test returns None when no annotations exist."""
    assert mock_local_file.get_latest_annotation("test/empty") is None


def test_get_latest_annotation_fallback_no_dates(mock_local_file):
    """Test fallback behavior when date_modified is missing (e.g. freshly created local objects)."""
    schema_id = "test/nodates"

    ann1 = MagicMock()
    del ann1.date_modified
    ann1.record.id = 1

    ann2 = MagicMock()
    del ann2.date_modified
    ann2.record.id = 2

    setattr(mock_local_file.model.annotations, schema_id, [ann1, ann2])

    result = mock_local_file.get_latest_annotation(schema_id)
    assert result is not None

    assert result in [ann1, ann2]
