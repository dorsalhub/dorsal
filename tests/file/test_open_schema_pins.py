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

from typing import Any

import pytest

from dorsal.common.validators import import_callable

from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.exceptions import AnnotationImportError, ModelImportError
from dorsal.common.model import AnnotationModel
from dorsal.file.configs.model_runner import (
    ModelRunnerPipelineStep,
    resolve_open_schema_step_validator,
    resolve_pipeline_step_models,
)
from dorsal.file.model_runner import ModelRunner
from dorsal.file.validators.open_schema import OpenSchemaValidator


class TranscriptionModel(AnnotationModel):
    id = "test/transcriber"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        return {"text": "hello world", "language": "eng"}


class RankingModel(AnnotationModel):
    id = "test/ranker"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        return {"not_a_ranking_field": True}


def _step(schema_id: str, schema_version: str | None, model: type[AnnotationModel]) -> ModelRunnerPipelineStep:
    clean_name = schema_id.removeprefix("open/").replace("-", "_")
    return ModelRunnerPipelineStep(
        annotation_model={"module": __name__, "name": model.__name__},
        validation_model={"module": "dorsal.file.validators.open_schema", "name": f"{clean_name}_validator"},
        schema_id=schema_id,
        schema_version=schema_version,
    )


def _import_test_models(path):
    return globals()[path.name] if path.module == __name__ else import_callable(path)


@pytest.fixture
def runner(mocker):
    mocker.patch("dorsal.file.model_runner.import_callable", side_effect=_import_test_models)
    return ModelRunner(pipeline_config=[])


@pytest.mark.parametrize(
    ("schema_version", "expected"),
    [("0.4.0", "0.4.0"), (None, OPEN_VALIDATION_SCHEMAS_VER), ("0.8.0", "0.8.0")],
)
def test_pinned_version_selects_validator(schema_version, expected):
    validator = resolve_open_schema_step_validator(
        _step("open/audio-transcription", schema_version, TranscriptionModel)
    )

    assert isinstance(validator, OpenSchemaValidator)
    assert validator.schema_version == expected
    assert validator.schema_name == "audio-transcription"


def test_validators_are_cached_per_version():
    v4 = resolve_open_schema_step_validator(_step("open/generic", "0.4.0", TranscriptionModel))
    v5 = resolve_open_schema_step_validator(_step("open/generic", "0.5.0", TranscriptionModel))
    v4_again = resolve_open_schema_step_validator(_step("open/generic", "0.4.0", TranscriptionModel))

    assert v4 is v4_again
    assert v4 is not v5
    assert v4.schema_version == "0.4.0"
    assert v5.schema_version == "0.5.0"


def test_non_open_steps_are_not_resolved():
    step = ModelRunnerPipelineStep(
        annotation_model={"module": __name__, "name": "TranscriptionModel"},
        validation_model={"module": "my.module", "name": "my_validator"},
        schema_id="open/generic",
        schema_version="0.4.0",
    )
    assert resolve_open_schema_step_validator(step) is None


@pytest.mark.parametrize("schema_version", ["0.4.0", None, "0.8.0"])
def test_record_stamped_with_validated_version(runner, tmp_path, schema_version):
    file_path = tmp_path / "audio.txt"
    file_path.write_text("x")
    step = _step("open/audio-transcription", schema_version, TranscriptionModel)

    annotator, validator = runner._load_model_and_validator_classes(step)
    results = runner.run_single_model(
        annotation_model=annotator,
        validation_model=validator,
        file_path=str(file_path),
        schema_id=step.schema_id,
        schema_version=step.schema_version,
    )

    assert len(results) == 1
    assert results[0].error is None
    assert results[0].schema_version == (schema_version or OPEN_VALIDATION_SCHEMAS_VER)


def test_schema_newer_than_default_version(runner, tmp_path):
    file_path = tmp_path / "items.txt"
    file_path.write_text("x")
    step = _step("open/ranking", "0.8.0", RankingModel)

    annotator, validator = runner._load_model_and_validator_classes(step)
    results = runner.run_single_model(
        annotation_model=annotator,
        validation_model=validator,
        file_path=str(file_path),
        schema_id=step.schema_id,
        schema_version=step.schema_version,
    )

    assert isinstance(validator, OpenSchemaValidator)
    assert validator.schema_version == "0.8.0"
    assert results[0].records is None
    assert results[0].error is not None
    assert results[0].schema_version == "0.8.0"


@pytest.mark.parametrize(
    ("schema_id", "schema_version"),
    [("open/audio-transcription", "9.9.9"), ("open/audio-transcription", "0.5"), ("open/ranking", "0.5.0")],
)
def test_unavailable_pin_is_an_import_error(runner, schema_id, schema_version):
    step = _step(schema_id, schema_version, TranscriptionModel)

    with pytest.raises(ModelImportError):
        runner._load_model_and_validator_classes(step)

    with pytest.raises(AnnotationImportError):
        resolve_pipeline_step_models(step)


def test_unavailable_pin_gives_error_result(mocker, tmp_path, caplog):
    file_path = tmp_path / "audio.txt"
    file_path.write_text("x")
    step = _step("open/audio-transcription", "9.9.9", TranscriptionModel)
    mocker.patch("dorsal.file.model_runner.import_callable", side_effect=_import_test_models)
    runner = ModelRunner(pipeline_config=[step.model_dump()])

    record = runner.run(file_path=str(file_path))

    assert record.annotations is not None
    assert getattr(record.annotations, "__pydantic_extra__", None) in (None, {})
    assert any(
        "Failed to import model/validator" in rec.getMessage() and "9.9.9" in rec.getMessage() for rec in caplog.records
    )
