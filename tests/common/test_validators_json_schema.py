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
from jsonschema.exceptions import ValidationError as JValidationError
from dorsal.common.validators.json_schema import (
    get_json_schema_validator,
    json_schema_validate_records,
    JsonSchemaValidator,
)
from dorsal.common.exceptions import SchemaFormatError, DorsalError

# --- Fixtures ---


@pytest.fixture
def simple_schema():
    return {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }


# --- get_json_schema_validator Tests ---


def test_get_validator_success(simple_schema):
    v = get_json_schema_validator(simple_schema)
    assert v is not None
    # Should accept valid data
    v.validate({"name": "Bob"})


def test_get_validator_invalid_input_type():
    with pytest.raises(TypeError):
        get_json_schema_validator("not a dict")  # type: ignore


def test_get_validator_empty_schema():
    with pytest.raises(ValueError):
        get_json_schema_validator({})


def test_get_validator_strict_check():
    # Inert schema (no keywords)
    inert = {"foo": "bar"}
    with pytest.raises(ValueError) as exc:
        get_json_schema_validator(inert, strict=True)
    assert "appears to be inert" in str(exc.value)


def test_get_validator_bad_schema_structure():
    bad = {"type": 123}
    with pytest.raises(SchemaFormatError):
        get_json_schema_validator(bad)


# --- json_schema_validate_records Tests ---


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
        {"age": 20},  # Missing name
        {"name": 123},  # Wrong type
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
    with pytest.raises(ValueError):
        json_schema_validate_records([{"name": "ok"}, "string"], v)
