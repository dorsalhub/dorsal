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

import os
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError as PydanticValidationError

from dorsal.common.validators import strings, datasets, json_schema
from dorsal.common.validators import (
    get_truthy_envvar,
    check_local_file_exists,
    import_callable,
    CallableImportPath,
    ValidationError,
)
from dorsal.common.exceptions import DorsalConfigError, SchemaFormatError


def test_truncate_string():
    """Test the core string truncation and validation logic."""
    assert strings.truncate_string("abc", 1, 5) == "abc"
    assert strings.truncate_string("abcdefgh", 1, 5) == "abcde"
    with pytest.raises(ValueError, match="String must be non-empty"):
        strings.truncate_string("", 1, 5)


class TruncationTestModel(BaseModel):
    """A model to test the TString annotated types."""

    val: strings.TString64


def test_tstring_validator():
    """Test that the TString64 annotated type truncates correctly."""
    long_string = "a" * 100
    obj = TruncationTestModel(val=long_string)
    assert len(obj.val) == 64
    assert obj.val == "a" * 64

    with pytest.raises(PydanticValidationError):
        TruncationTestModel(val="")


@pytest.mark.parametrize(
    "input_str, expected",
    [
        ("my-org/my-dataset", "my-org/my-dataset"),
        ("https://dorsalhub.com/d/dorsal/iso-language", "dorsal/iso-language"),
        ("dorsal/iso-language", "dorsal/iso-language"),
    ],
)
def test_get_dataset_id_success(input_str, expected):
    """Test successful extraction of a dataset ID."""
    assert datasets.get_dataset_id(input_str) == expected


@pytest.mark.parametrize("invalid_input", ["nodashes", "too--many--hyphens", "org/a"])
def test_get_dataset_id_failure(invalid_input):
    """Test that get_dataset_id fails for invalid formats."""
    with pytest.raises(ValueError):
        datasets.get_dataset_id(invalid_input)


def test_check_no_double_hyphens():
    """Test the double-hyphen validator."""
    assert datasets.check_no_double_hyphens("valid-id") == "valid-id"
    with pytest.raises(ValueError, match="must not contain double hyphens"):
        datasets.check_no_double_hyphens("invalid--id")


class DatasetIdTestModel(BaseModel):
    id: datasets.DatasetID


def test_dataset_id_validator():
    """Test the full DatasetID annotated type via a model."""
    obj = DatasetIdTestModel(id="my-org/my-dataset")
    assert obj.id == "my-org/my-dataset"

    with pytest.raises(PydanticValidationError):
        DatasetIdTestModel(id="invalid--namespace/my-dataset")


@pytest.fixture
def sample_schema() -> dict:
    """A basic, valid JSON schema for testing."""
    return {"type": "object", "properties": {"name": {"type": "string"}}}


def test_get_json_schema_validator_success(sample_schema):
    """Test that a valid schema produces a validator instance."""
    validator = json_schema.get_json_schema_validator(sample_schema)
    assert isinstance(validator, json_schema.JsonSchemaValidator)


def test_get_json_schema_validator_bad_schema():
    """Test that a structurally invalid schema raises the correct error."""
    bad_schema = {}
    with pytest.raises(ValueError, match="The 'schema' dictionary cannot be empty."):
        json_schema.get_json_schema_validator(bad_schema)


def test_json_schema_validate_records(sample_schema):
    """Test the record validation summary function."""
    json_schema.get_json_schema_validator(sample_schema)
    records = [
        {"name": "valid"},
        {"name": 123},  # Invalid type
        {},  # Missing required field
    ]

    sample_schema["required"] = ["name"]
    validator_with_required = json_schema.get_json_schema_validator(sample_schema)

    summary = json_schema.json_schema_validate_records(records, validator_with_required)

    assert summary["total_records"] == 3
    assert summary["valid_records"] == 1
    assert summary["invalid_records"] == 2


@pytest.mark.parametrize(
    "value, strict, expected",
    [
        ("1", True, True),
        ("true", True, True),
        ("y", True, True),
        ("0", True, False),
        ("false", True, False),
        ("no", True, False),
        ("anything-else", True, False),
        ("1", False, True),
        ("false", False, False),
        ("no", False, False),
        ("anything-else", False, True),
        (None, False, False),
    ],
)
def test_get_truthy_envvar(value, strict, expected):
    """Test the environment variable boolean logic."""
    env_vars = {"TEST_VAR": value} if value is not None else {}
    with patch("os.environ", env_vars):
        assert get_truthy_envvar("TEST_VAR", strict=strict) == expected


def test_check_local_file_exists(fs):
    """Test the file existence checker using a fake filesystem."""
    existing_file = "/tmp/exists.txt"
    fs.create_file(existing_file)

    check_local_file_exists(existing_file)

    with pytest.raises(ValidationError, match="does not exist or cannot be accessed"):
        check_local_file_exists("/tmp/does_not_exist.txt")


def test_import_callable():
    """Test the dynamic callable import function."""
    import_path = CallableImportPath(module="os.path", name="join")
    join_func = import_callable(import_path)
    assert callable(join_func)
    assert join_func("a", "b") == os.path.join("a", "b")
