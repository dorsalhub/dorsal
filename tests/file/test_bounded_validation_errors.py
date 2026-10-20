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

import logging
import traceback

import pytest
from pydantic import BaseModel

from dorsal.common.exceptions import (
    AnnotationValidationError,
    ApiDataValidationError,
    DataQualityError,
    PydanticValidationError,
)
from dorsal.common.model import AnnotationModel
from dorsal.common.validators.json_schema import (
    ERROR_INPUT_PREVIEW_LIMIT,
    ERROR_MESSAGE_LIMIT,
    PYDANTIC_ERRORS_LIMIT,
    bound_pydantic_errors,
    format_pydantic_errors,
)
from dorsal.file.file_annotator import FileAnnotator
from dorsal.file.linters import apply_linter
from dorsal.file.model_runner import run_model
from dorsal.file.validators.file_record import FileRecordStrict

BIG = "x" * 5_000_000
MARKER = "SECRET-MARKER"
BIG_WITH_MARKER = MARKER + BIG + MARKER
SIZE_LIMIT = 20_000


class StrictOutput(BaseModel):
    count: int
    items: list[int] = []


class BigStringModel(AnnotationModel):
    id = "test/big-string"
    version = "1.0.0"

    def main(self):
        return {"count": BIG_WITH_MARKER}


class ManyErrorsModel(AnnotationModel):
    id = "test/many-errors"
    version = "1.0.0"

    def main(self):
        return {"count": BIG_WITH_MARKER, "items": [BIG] + ["x"] * 100_000}


def _make_error(data):
    try:
        StrictOutput.model_validate(data)
    except PydanticValidationError as err:
        return err
    raise AssertionError("validation unexpectedly passed")


def _formatted_log_sizes(caplog):
    return [len(caplog.handler.format(record)) for record in caplog.records]


def _traceback_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("hello")
    return str(path)


def test_bound_pydantic_errors_keeps_loc_and_type():
    err = _make_error({"count": BIG_WITH_MARKER})

    errors = bound_pydantic_errors(err)

    assert len(errors) == 1
    assert errors[0]["loc"] == ("count",)
    assert errors[0]["type"] == "int_parsing"
    assert len(errors[0]["input"]) <= ERROR_INPUT_PREVIEW_LIMIT
    assert len(repr(errors)) < 2_000


def test_bound_pydantic_errors_caps_the_number_of_errors():
    err = _make_error({"count": 1, "items": ["x"] * 100_000})

    assert err.error_count() == 100_000
    assert len(bound_pydantic_errors(err)) == PYDANTIC_ERRORS_LIMIT
    summary = format_pydantic_errors(err)
    assert summary.startswith("100000 validation errors")
    assert len(summary) <= ERROR_MESSAGE_LIMIT


@pytest.mark.parametrize("model", [BigStringModel, ManyErrorsModel])
def test_model_output_failing_pydantic_validation_is_bounded(model, text_file, caplog):
    caplog.set_level(logging.DEBUG)

    results = run_model(annotation_model=model, file_path=text_file, validation_model=StrictOutput)

    assert results[0].error is not None
    assert results[0].records is None
    assert len(results[0].error) < SIZE_LIMIT
    assert MARKER + "x" * 200 not in results[0].error
    assert caplog.records
    assert max(_formatted_log_sizes(caplog)) < SIZE_LIMIT
    assert any("Pydantic validation failed" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("model", [BigStringModel, ManyErrorsModel])
def test_model_output_failing_pydantic_validation_with_schema_id_is_bounded(model, text_file, caplog):
    caplog.set_level(logging.DEBUG)

    results = run_model(
        annotation_model=model, file_path=text_file, schema_id="test/custom", validation_model=StrictOutput
    )

    assert results[0].error is not None
    assert len(results[0].error) < SIZE_LIMIT
    assert max(_formatted_log_sizes(caplog)) < SIZE_LIMIT


@pytest.mark.parametrize(
    "record",
    [{"count": BIG_WITH_MARKER}, {"count": BIG_WITH_MARKER, "items": [BIG] + ["x"] * 100_000}],
)
def test_manual_annotation_failing_pydantic_validation_is_bounded(record, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(AnnotationValidationError) as exc_info:
        FileAnnotator().validate_manual_annotation(annotation=record, validator=StrictOutput)

    err = exc_info.value
    assert len(str(err)) <= ERROR_MESSAGE_LIMIT + 100
    assert len(repr(err)) <= ERROR_MESSAGE_LIMIT + 200
    assert len(_traceback_text(err)) < SIZE_LIMIT
    assert len(repr(err.validation_errors)) < SIZE_LIMIT
    assert isinstance(err.original_exception, PydanticValidationError)
    assert max(_formatted_log_sizes(caplog), default=0) < SIZE_LIMIT


def test_linter_error_is_bounded(caplog):
    record = {"labels": [{"label": BIG_WITH_MARKER}] * 2, "vocabulary": ["a"] * 50_000}

    with pytest.raises(DataQualityError) as exc_info:
        apply_linter(schema_id="open/classification", record=record, raise_on_error=True)

    assert len(str(exc_info.value)) < 2 * ERROR_MESSAGE_LIMIT
    assert len(_traceback_text(exc_info.value)) < SIZE_LIMIT

    caplog.set_level(logging.WARNING)
    apply_linter(schema_id="open/classification", record=record, raise_on_error=False)
    assert max(_formatted_log_sizes(caplog), default=0) < SIZE_LIMIT


def test_api_data_validation_error_with_pydantic_cause_is_bounded():
    err = _make_error({"count": BIG_WITH_MARKER, "items": ["x"] * 100_000})

    api_error = ApiDataValidationError("Bad response", original_exception=err)

    assert len(str(api_error)) < 2 * ERROR_MESSAGE_LIMIT


def test_invalid_annotation_in_file_record_is_bounded(mock_file_record_strict_dict):
    data = mock_file_record_strict_dict
    data["annotations"]["test/bad"] = {"record": BIG_WITH_MARKER, "source": {"type": "Manual", "id": "x"}}

    with pytest.raises(PydanticValidationError) as exc_info:
        FileRecordStrict.model_validate(data)

    assert len(str(exc_info.value)) < SIZE_LIMIT
    for error in exc_info.value.errors():
        assert len(str(error.get("msg", ""))) < SIZE_LIMIT


@pytest.fixture
def mock_file_record_strict_dict():
    return {
        "hash": "a" * 64,
        "validation_hash": "e" * 64,
        "source": "disk",
        "annotations": {
            "file/base": {
                "record": {
                    "hash": "a" * 64,
                    "name": "local_test.txt",
                    "extension": ".txt",
                    "size": 123,
                    "media_type": "text/plain",
                },
                "source": {"type": "Model", "id": "dorsal/base", "version": "1.0.0"},
            }
        },
    }
