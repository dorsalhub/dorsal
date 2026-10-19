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

import pytest
from dorsal.common.validators.json_schema import (
    get_json_schema_validator,
    json_schema_validate_records,
    JsonSchemaValidator,
)
from dorsal.common.exceptions import SchemaFormatError, DorsalError


@pytest.fixture
def simple_schema():
    return {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }


def test_get_validator_success(simple_schema):
    v = get_json_schema_validator(simple_schema)
    assert v is not None

    v.validate({"name": "Bob"})


def test_get_validator_invalid_input_type():
    with pytest.raises(TypeError):
        get_json_schema_validator("not a dict")  # type: ignore


def test_get_validator_empty_schema():
    with pytest.raises(ValueError):
        get_json_schema_validator({})


def test_get_validator_strict_check():

    inert = {"foo": "bar"}
    with pytest.raises(ValueError) as exc:
        get_json_schema_validator(inert, strict=True)
    assert "is inert" in str(exc.value)


def test_get_validator_bad_schema_structure():
    bad = {"type": 123}
    with pytest.raises(SchemaFormatError):
        get_json_schema_validator(bad)


def test_validate_records_success(simple_schema):
    validator = get_json_schema_validator(simple_schema)
    records = [{"name": "Alice", "age": 30}, {"name": "Bob"}]

    summary = json_schema_validate_records(records, validator)
    assert summary["total_records"] == 2
    assert summary["valid_records"] == 2
    assert summary["invalid_records"] == 0
    assert summary["error_details"] == []


def test_validate_records_mixed_results(simple_schema):
    validator = get_json_schema_validator(simple_schema)
    records = [
        {"name": "Valid"},
        {"age": 20},
        {"name": 123},
    ]

    summary = json_schema_validate_records(records, validator)
    assert summary["valid_records"] == 1
    assert summary["invalid_records"] == 2
    assert len(summary["error_details"]) == 2
    assert summary["error_details"][0]["record_index"] == 1


def test_validate_records_invalid_input_type(simple_schema):
    v = get_json_schema_validator(simple_schema)
    with pytest.raises(ValueError):
        json_schema_validate_records("not a list", v)  # type: ignore


def test_validate_records_non_dict_item(simple_schema):
    v = get_json_schema_validator(simple_schema)

    records = [{"name": "ok"}, "string"]
    summary = json_schema_validate_records(records, v)

    assert summary["valid_records"] == 1
    assert summary["invalid_records"] == 1
    assert len(summary["error_details"]) == 1

    error = summary["error_details"][0]
    assert "Invalid record type: str" in error["error_message"]
    assert error["record_index"] == 1


BIG = 5_000_000
ERROR_TEXT_LIMIT = 2_000


@pytest.fixture
def bounded_schema():
    return {
        "type": "object",
        "properties": {
            "label": {"enum": ["cat", "dog"]},
            "text": {"type": "string", "maxLength": 10},
        },
        "additionalProperties": {"type": "string", "maxLength": 2},
    }


def _assert_bounded_error(err: BaseException) -> None:
    import traceback

    assert len(str(err)) < ERROR_TEXT_LIMIT
    assert len(repr(err)) < ERROR_TEXT_LIMIT
    assert len("".join(traceback.format_exception(err))) < ERROR_TEXT_LIMIT * 2
    assert len(getattr(err, "message", "")) < ERROR_TEXT_LIMIT


@pytest.mark.parametrize(
    "record",
    [
        {"label": "x" * BIG},
        {"text": "x" * BIG},
        {"k" * BIG: "too long"},
    ],
    ids=["enum", "maxLength", "huge-key"],
)
def test_validate_errors_are_bounded(bounded_schema, record):
    import jsonschema_rs

    validator = get_json_schema_validator(bounded_schema)

    with pytest.raises(jsonschema_rs.ValidationError) as exc_info:
        validator.validate(record)

    _assert_bounded_error(exc_info.value)


@pytest.mark.parametrize(
    "record",
    [{"label": "x" * BIG}, {"text": "x" * BIG}, {"k" * BIG: "too long"}],
    ids=["enum", "maxLength", "huge-key"],
)
def test_validate_records_errors_are_bounded(bounded_schema, record, caplog):
    import logging

    validator = get_json_schema_validator(bounded_schema)

    with caplog.at_level(logging.DEBUG):
        summary = json_schema_validate_records([record], validator)

    assert summary["invalid_records"] == 1
    detail = summary["error_details"][0]
    assert len(detail["error_message"]) < ERROR_TEXT_LIMIT
    assert len(detail["record_preview"]) <= 150
    assert sum(len(rec.getMessage()) for rec in caplog.records) < ERROR_TEXT_LIMIT * 5


def test_validate_records_reports_keyword(simple_schema):
    validator = get_json_schema_validator(simple_schema)

    summary = json_schema_validate_records([{"age": 1}, {"name": 5}], validator)

    messages = [detail["error_message"] for detail in summary["error_details"]]
    assert "(required)" in messages[0]
    assert "(type)" in messages[1]
    assert "limit of" not in " ".join(messages)


@pytest.mark.parametrize(
    "record",
    [{"description": "x" * BIG}, {"data": {"k": "x" * BIG}, "producer": 7}, {"k" * BIG: 1}],
    ids=["maxLength", "type", "huge-key"],
)
def test_open_schema_errors_are_bounded(record, caplog):
    import logging

    import jsonschema_rs

    from dorsal.file.validators.open_schema import get_open_schema_validator

    validator = get_open_schema_validator("generic")

    assert not validator.is_valid(record)

    with pytest.raises(jsonschema_rs.ValidationError) as exc_info:
        validator.validate(record)
    _assert_bounded_error(exc_info.value)

    with caplog.at_level(logging.DEBUG):
        summary = json_schema_validate_records([record], validator)

    detail = summary["error_details"][0]
    assert len(detail["error_message"]) < ERROR_TEXT_LIMIT
    assert len(detail["record_preview"]) <= 150
    assert sum(len(rec.getMessage()) for rec in caplog.records) < ERROR_TEXT_LIMIT * 5
