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
from typing import get_args

import oatschema
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
from dorsal.common.validators.json_schema import JsonSchemaValidator
from dorsal.file.validators.open_schema import OpenSchemaValidator, get_open_schema_validator
import dorsal.file.validators.open_schema as open_schema_module
from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER, ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR
from dorsal.file.schemas import (
    OPEN_SCHEMA_NAME_MAP,
    OpenSchemaName,
    get_open_schema,
    _load_schema_from_package,
    OPEN_VALIDATION_SCHEMAS_VER,
    schema_version_of,
)


def test_build_classification_record():
    rec = build_classification_record(labels=["cat"], score_explanation="AI")
    assert rec["labels"][0]["label"] == "cat"
    assert rec["score_explanation"] == "AI"

    rec = build_classification_record(labels=[{"label": "dog", "score": 0.9}])
    assert rec["labels"][0]["score"] == 0.9

    with pytest.raises(TypeError):
        build_classification_record(labels="not a list")

    with pytest.raises(TypeError):
        build_classification_record(labels=[123])


def test_build_embedding_record():
    rec = build_embedding_record(vector=[0.1, 0.2], model="bert")
    assert rec["vector"] == [0.1, 0.2]
    assert rec["model"] == "bert"


def test_build_llm_output_record():
    rec = build_llm_output_record(model="gpt", response_data={"foo": "bar"})
    assert '{"foo": "bar"}' in rec["response_data"]

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
    rec = build_generic_record(description="desc", data={"key": 1, "valid": True})
    assert rec["data"]["key"] == 1

    with pytest.raises(TypeError):
        build_generic_record(description="d", data={"nested": {"a": 1}})


def test_get_open_schema():
    _load_schema_from_package.cache_clear()

    schema = get_open_schema("generic")
    assert schema_version_of(schema) == OPEN_VALIDATION_SCHEMAS_VER
    assert schema == oatschema.get_schema("generic", OPEN_VALIDATION_SCHEMAS_VER)

    with pytest.raises(ValueError):
        get_open_schema("invalid_name")

    with pytest.raises(FileNotFoundError):
        get_open_schema("generic", version="9.9.9")

    with pytest.raises(FileNotFoundError):
        get_open_schema("generic", version="0.5")

    with pytest.raises(FileNotFoundError):
        get_open_schema("ranking")


def test_get_open_schema_integrity_error():
    _load_schema_from_package.cache_clear()
    try:
        with patch("oatschema.get_schema", return_value=json.dumps({"type": "object", "version": "99.9.9"})):
            with pytest.raises(RuntimeError, match="Critical Package Integrity Error"):
                get_open_schema("generic")
    finally:
        _load_schema_from_package.cache_clear()


def test_schema_version_of():
    assert schema_version_of({"version": "0.7.0"}) == "0.7.0"
    assert schema_version_of({"x-version": "0.8.0"}) == "0.8.0"
    assert schema_version_of({"x-version": "0.8.0", "version": "0.7.0"}) == "0.8.0"
    assert schema_version_of({}) is None
    assert schema_version_of({"version": 1}) is None


def test_get_open_schema_validator():
    open_schema_module._build_and_cache_validator.cache_clear()

    val = get_open_schema_validator("generic")
    assert isinstance(val, OpenSchemaValidator)
    assert isinstance(val, JsonSchemaValidator)
    assert val.schema_version == OPEN_VALIDATION_SCHEMAS_VER
    assert val is get_open_schema_validator("generic")

    with pytest.raises(ValueError):
        get_open_schema_validator("bad_name")

    with pytest.raises(RuntimeError):
        get_open_schema_validator("generic", version="9.9.9")

    assert open_schema_module.__getattr__("generic_validator") is val
    assert open_schema_module.__getattr__("generic") is val

    with pytest.raises(AttributeError):
        open_schema_module.__getattr__("random_attribute")

    assert not hasattr(open_schema_module, "ranking_validator")


def test_open_schema_names_match_oatschema():
    assert set(OPEN_SCHEMA_NAME_MAP) == set(get_args(OpenSchemaName)) == set(get_args(oatschema.SchemaName))


@pytest.mark.parametrize("version", oatschema.available_versions())
def test_every_oatschema_version_loads(version):
    _load_schema_from_package.cache_clear()
    open_schema_module._build_and_cache_validator.cache_clear()

    for schema_name in OPEN_SCHEMA_NAME_MAP:
        try:
            oatschema.get_schema(schema_name, version)
        except LookupError:
            with pytest.raises(FileNotFoundError):
                get_open_schema(schema_name, version=version)
            continue

        schema = get_open_schema(schema_name, version=version)
        assert schema_version_of(schema) == version

        validator = get_open_schema_validator(schema_name, version=version)
        assert validator.schema_version == version
        assert validator.oats_validator is not None
        assert validator.oats_validator.schema_version == version


def test_get_open_schema_with_override(tmp_path):
    custom_schema = {
        "version": OPEN_VALIDATION_SCHEMAS_VER,
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
            with pytest.raises(FileNotFoundError, match="Override schema not found at"):
                get_open_schema("generic")
    finally:
        _load_schema_from_package.cache_clear()


def test_open_schema_validator_with_override(tmp_path):
    custom_schema = {
        "version": "0.4.0",
        "title": "Overridden Generic Schema",
        "type": "object",
        "properties": {"custom_field": {"type": "string", "maxLength": 3}},
        "required": ["custom_field"],
    }
    (tmp_path / "generic.json").write_text(json.dumps(custom_schema), encoding="utf-8")

    _load_schema_from_package.cache_clear()
    open_schema_module._build_and_cache_validator.cache_clear()
    try:
        with patch.dict(os.environ, {ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR: str(tmp_path)}):
            validator = get_open_schema_validator("generic")

        assert validator.oats_validator is None
        assert validator.schema_version == "0.4.0"
        assert validator.is_valid({"custom_field": "abc"})
        assert not validator.is_valid({"custom_field": "abcd"})
        error = validator.first_error({"custom_field": "x" * 1_000_000})
        assert error is not None
        assert len(error[0]) < 200
        assert error[1] == ["custom_field"]
        assert error[2] == "maxLength"
    finally:
        _load_schema_from_package.cache_clear()
        open_schema_module._build_and_cache_validator.cache_clear()
