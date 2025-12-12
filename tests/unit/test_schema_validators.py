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
from unittest.mock import MagicMock, patch
from dorsal.file.helpers import (
    build_classification_record,
    build_embedding_record,
    build_llm_output_record,
    build_location_record,
    build_transcription_record,
    build_generic_record,
)
from dorsal.file.validators.open_schema import get_open_schema_validator
import dorsal.file.validators.open_schema as open_schema_module
from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER, ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR
from dorsal.file.schemas import OPEN_SCHEMA_NAME_MAP, get_open_schema, _load_schema_from_package


def test_build_classification_record():
    # Happy path
    rec = build_classification_record(labels=["cat"], score_explanation="AI")
    assert rec["labels"][0]["label"] == "cat"
    assert rec["score_explanation"] == "AI"

    # Mixed types
    rec = build_classification_record(labels=[{"label": "dog", "score": 0.9}])
    assert rec["labels"][0]["score"] == 0.9

    # Invalid type
    with pytest.raises(TypeError):
        build_classification_record(labels="not a list")  # type: ignore

    with pytest.raises(TypeError):
        build_classification_record(labels=[123])  # type: ignore


def test_build_embedding_record():
    rec = build_embedding_record(vector=[0.1, 0.2], model="bert")
    assert rec["vector"] == [0.1, 0.2]
    assert rec["model"] == "bert"


def test_build_llm_output_record():
    # Dictionary serialization
    rec = build_llm_output_record(model="gpt", response_data={"foo": "bar"})
    assert '{"foo": "bar"}' in rec["response_data"]

    # Failure to serialize
    with pytest.raises(TypeError):
        build_llm_output_record(model="g", response_data={"bad": object()})


def test_build_location_record():
    rec = build_location_record(longitude=10.0, latitude=20.0, timestamp="2023")
    assert rec["geometry"]["coordinates"] == [10.0, 20.0]
    assert rec["properties"]["timestamp"] == "2023"


def test_build_transcription_record():
    rec = build_transcription_record(language="eng", text="hello", track_id=1)
    assert rec["language"] == "eng"
    assert rec["track_id"] == 1


def test_build_generic_record():
    # Valid
    rec = build_generic_record(description="desc", data={"key": 1, "valid": True})
    assert rec["data"]["key"] == 1

    # Invalid nesting
    with pytest.raises(TypeError):
        build_generic_record(description="d", data={"nested": {"a": 1}})  # type: ignore


# --- 2. Schemas Tests ---


@patch("dorsal.file.schemas.importlib.resources.files")
def test_get_open_schema(mock_files):
    mock_file = MagicMock()
    mock_file.read_text.return_value = '{"type": "object", "version": "0.1.0"}'
    mock_files.return_value.joinpath.return_value = mock_file

    schema = get_open_schema("generic")
    assert schema == {"type": "object", "version": "0.1.0"}

    with pytest.raises(ValueError):
        get_open_schema("invalid_name")  # type: ignore

    mock_files.return_value.joinpath.side_effect = FileNotFoundError

    _load_schema_from_package.cache_clear()

    with pytest.raises(RuntimeError, match="Critical Package Integrity Error"):
        get_open_schema("generic")


# --- 3. Open Schema Validator Tests ---


@patch("dorsal.file.validators.open_schema.get_open_schema")
@patch("dorsal.file.validators.open_schema.get_json_schema_validator")
def test_get_open_schema_validator(mock_get_validator, mock_get_schema):
    # Setup
    open_schema_module._build_and_cache_validator.cache_clear()
    mock_get_schema.return_value = {"mock": "schema"}
    mock_get_validator.return_value = "MockValidatorInstance"

    # Test valid retrieval
    val = get_open_schema_validator("generic")
    assert val == "MockValidatorInstance"
    mock_get_schema.assert_called_with("generic")

    # Test unknown name
    with pytest.raises(ValueError):
        get_open_schema_validator("bad_name")  # type: ignore

    # Test module level getattr (lazy loading)
    # e.g. from dorsal.file.validators.open_schema import generic_validator
    val_lazy = open_schema_module.__getattr__("generic_validator")
    assert val_lazy == "MockValidatorInstance"

    # Test invalid module attr
    with pytest.raises(AttributeError):
        open_schema_module.__getattr__("random_attribute")


def test_bundled_schemas_integrity():
    _load_schema_from_package.cache_clear()

    for schema_name in OPEN_SCHEMA_NAME_MAP.keys():
        schema = get_open_schema(schema_name)

        assert schema.get("version") == OPEN_VALIDATION_SCHEMAS_VER, (
            f"Schema '{schema_name}' has version {schema.get('version')}, expected {OPEN_VALIDATION_SCHEMAS_VER}"
        )


def test_get_open_schema_with_override(tmp_path):
    custom_schema = {
        "version": "0.1.0",
        "title": "Overridden Generic Schema",
        "type": "object",
        "properties": {"custom_field": {"type": "string"}},
        "required": ["custom_field"],
    }

    target_file = tmp_path / "generic.json"
    target_file.write_text(json.dumps(custom_schema), encoding="utf-8")

    _load_schema_from_package.cache_clear()

    try:
        with patch.dict(os.environ, {ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR: str(tmp_path)}):
            loaded_schema = get_open_schema("generic")

        assert loaded_schema["title"] == "Overridden Generic Schema"
        assert "custom_field" in loaded_schema["properties"]

    finally:
        _load_schema_from_package.cache_clear()


def test_get_open_schema_override_missing_file(tmp_path):
    _load_schema_from_package.cache_clear()

    try:
        with patch.dict(os.environ, {ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR: str(tmp_path)}):
            with pytest.raises(ValueError, match="not found in override dir"):
                get_open_schema("generic")
    finally:
        _load_schema_from_package.cache_clear()
