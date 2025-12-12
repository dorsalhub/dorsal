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
from types import SimpleNamespace
from pydantic import BaseModel, ValidationError as PydanticValidationError
from dorsal.file.file_annotator import FileAnnotator
from dorsal.common.exceptions import (
    AnnotationConfigurationError,
    AnnotationExecutionError,
    AnnotationImportError,
    AnnotationValidationError,
    ModelRunnerError,
)
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep
from dorsal.file.validators.file_record import GenericFileAnnotation, Annotation
from dorsal.common.model import AnnotationModel, AnnotationModelSource, AnnotationManualSource
from dorsal.common.validators import CallableImportPath


class MockAnnotationModel(AnnotationModel):
    id = "mock_model"

    def main(self):
        pass


class MockPydanticModel(BaseModel):
    field: str


class BadModelNoId:
    pass


@pytest.fixture
def annotator():
    return FileAnnotator()


@pytest.fixture
def mock_runner(mocker):
    runner = mocker.MagicMock()
    # Valid hash is 64 chars (sha256)
    valid_hash = "a" * 64

    # Return a "dumb" object that mimics RunModelResult structure
    # to bypass strict Pydantic validation of Source types during testing.
    # We use a Model source here as that is what the Runner typically returns.
    source_obj = AnnotationModelSource(id="mock_model", version="1.0")

    result = SimpleNamespace(
        name="mock_model",
        schema_id="test/schema",
        record={"file_hash": valid_hash, "data": {"foo": "bar"}},
        source=source_obj,
        error=None,
    )
    runner.run_single_model.return_value = result
    return runner


# --- Tests: _execute ---


def test_execute_success(annotator, mock_runner):
    res = annotator._execute(
        model_runner=mock_runner,
        annotation_model=MockAnnotationModel,
        validation_model=None,
        file_path="test.file",
        schema_id="test/schema",
        options={"opt": 1},
    )
    assert res.record["file_hash"] == "a" * 64
    mock_runner.run_single_model.assert_called_once()


def test_execute_runner_raises_exception(annotator, mock_runner):
    mock_runner.run_single_model.side_effect = ModelRunnerError("Simulated Crash")
    with pytest.raises(AnnotationExecutionError) as exc:
        annotator._execute(mock_runner, MockAnnotationModel, None, "path", "id", {})
    assert "Execution failed for model" in str(exc.value)


def test_execute_runner_returns_error_string(annotator, mock_runner):
    mock_runner.run_single_model.return_value = SimpleNamespace(
        name="mock_model",
        schema_id="test/schema",
        record=None,
        source=AnnotationManualSource(id="error"),
        error="Logic Error inside Model",
    )
    with pytest.raises(AnnotationExecutionError) as exc:
        annotator._execute(mock_runner, MockAnnotationModel, None, "path", "id", {})
    assert "returned an error: Logic Error inside Model" in str(exc.value)


def test_execute_runner_returns_nothing(annotator, mock_runner):
    mock_runner.run_single_model.return_value = SimpleNamespace(
        name="mock_model",
        schema_id="test/schema",
        record=None,
        source=AnnotationManualSource(id="empty"),
        error=None,
    )
    with pytest.raises(AnnotationExecutionError) as exc:
        annotator._execute(mock_runner, MockAnnotationModel, None, "path", "id", {})
    assert "returned no record and no error" in str(exc.value)


# --- Tests: annotate_file_using_model_and_validator ---


def test_annotate_direct_success(annotator, mock_runner, mocker):
    mocker.patch("dorsal.file.file_annotator.is_valid_dataset_id_or_schema_id", return_value=True)

    result = annotator.annotate_file_using_model_and_validator(
        file_path="test.file",
        model_runner=mock_runner,
        annotation_model_cls=MockAnnotationModel,
        schema_id="test/direct",
        private=False,
    )
    assert isinstance(result, Annotation)
    assert result.record.file_hash == "a" * 64


def test_annotate_direct_missing_schema(annotator, mock_runner):
    with pytest.raises(AnnotationConfigurationError):
        annotator.annotate_file_using_model_and_validator(
            file_path="f",
            model_runner=mock_runner,
            annotation_model_cls=MockAnnotationModel,
            schema_id=None,
            private=False,  # type: ignore
        )


def test_annotate_direct_bad_model_class(annotator, mock_runner):
    with pytest.raises(AnnotationConfigurationError) as exc:
        annotator.annotate_file_using_model_and_validator(
            file_path="f",
            model_runner=mock_runner,
            annotation_model_cls=BadModelNoId,  # type: ignore
            schema_id="test/schema",
            private=False,
        )
    assert "missing a required, non-empty 'id'" in str(exc.value)


# --- Tests: annotate_file_using_pipeline_step ---


def test_annotate_pipeline_step_dict_success(annotator, mock_runner, mocker):
    mocker.patch("dorsal.file.file_annotator.is_valid_dataset_id_or_schema_id", return_value=True)
    mocker.patch("dorsal.file.file_annotator.import_callable", return_value=MockAnnotationModel)

    step_config = {
        "annotation_model": {"module": "some.module", "name": "ModelClass"},
        "schema_id": "test/pipeline",
        "options": {"foo": "bar"},
    }

    result = annotator.annotate_file_using_pipeline_step(
        file_path="f", model_runner=mock_runner, pipeline_step=step_config, private=True
    )

    assert result.record.file_hash == "a" * 64
    assert result.private is True


def test_annotate_pipeline_import_error(annotator, mock_runner, mocker):
    mocker.patch("dorsal.file.file_annotator.import_callable", side_effect=ImportError("No module named foo"))

    cip = CallableImportPath(module="foo", name="Bar")
    step = ModelRunnerPipelineStep(annotation_model=cip, schema_id="test/schema")

    with pytest.raises(AnnotationImportError) as exc:
        annotator.annotate_file_using_pipeline_step(
            file_path="f", model_runner=mock_runner, pipeline_step=step, private=False
        )
    assert "Failed to import model/validator" in str(exc.value)


def test_annotate_pipeline_type_error(annotator, mock_runner, mocker):
    mocker.patch("dorsal.file.file_annotator.import_callable", return_value=BadModelNoId)

    # Use CallableImportPath object
    cip = CallableImportPath(module="foo", name="Bad")
    step = ModelRunnerPipelineStep(annotation_model=cip, schema_id="test/schema")

    with pytest.raises(AnnotationImportError) as exc:
        annotator.annotate_file_using_pipeline_step(
            file_path="f", model_runner=mock_runner, pipeline_step=step, private=False
        )

    assert "Failed to import model/validator" in str(exc.value)


# --- Tests: validate_manual_annotation ---


def test_validate_manual_pydantic_success(annotator):
    data = {"field": "valid_value"}
    res = annotator.validate_manual_annotation(data, validator=MockPydanticModel)
    assert res["field"] == "valid_value"


def test_validate_manual_pydantic_failure(annotator):
    data = {"field": 123}
    with pytest.raises(AnnotationValidationError):
        annotator.validate_manual_annotation(data, validator=MockPydanticModel)


def test_validate_manual_no_validator(annotator):
    data = {"any": "thing"}
    res = annotator.validate_manual_annotation(data, validator=None)
    assert res == data


def test_validate_manual_unsupported_validator(annotator):
    with pytest.raises(AnnotationConfigurationError):
        annotator.validate_manual_annotation({}, validator=str)  # type: ignore


# --- Tests: make_manual_annotation ---


def test_make_manual_annotation_success(annotator, mocker):
    mocker.patch("dorsal.file.file_annotator.is_valid_dataset_id_or_schema_id", return_value=True)
    mocker.patch("dorsal.file.file_annotator.apply_linter")

    valid_hash = "a" * 64
    data = {"file_hash": valid_hash, "data": {}}

    res = annotator.make_manual_annotation(
        annotation=data, schema_id="manual/test", source_id="user input", private=False
    )

    assert res.record.file_hash == valid_hash
    assert res.source.id == "user input"


def test_make_manual_annotation_force(annotator, mocker):
    spy_val = mocker.spy(annotator, "validate_manual_annotation")

    valid_hash = "a" * 64
    valid_data = {"file_hash": valid_hash, "data": {}}

    annotator.make_manual_annotation(
        annotation=valid_data, schema_id="forced/schema", source_id=None, private=False, force=True
    )

    spy_val.assert_not_called()


def test_make_annotation_invalid_schema_id(annotator, mocker):
    mocker.patch("dorsal.file.file_annotator.is_valid_dataset_id_or_schema_id", return_value=False)

    with pytest.raises(AnnotationConfigurationError):
        annotator._make_annotation(
            validated_annotation={}, schema_id="invalid/id", schema_version=None, source={}, private=False
        )


def test_make_annotation_wrapper_lookup(annotator, mocker):
    mocker.patch("dorsal.file.file_annotator.is_valid_dataset_id_or_schema_id", return_value=True)

    class SpecialAnnotation(Annotation):
        pass

    mocker.patch.dict("dorsal.file.file_annotator.CORE_MODEL_ANNOTATION_WRAPPERS", {"special/id": SpecialAnnotation})

    valid_hash = "b" * 64
    valid_data = {"file_hash": valid_hash, "data": {}}

    # Use 'Manual' source to satisfy union in _make_annotation
    source_dict = {"type": "Manual", "id": "test"}

    res = annotator._make_annotation(
        validated_annotation=valid_data, schema_id="special/id", schema_version=None, source=source_dict, private=False
    )

    assert isinstance(res, SpecialAnnotation)
