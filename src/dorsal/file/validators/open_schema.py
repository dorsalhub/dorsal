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
from functools import lru_cache
from typing import TYPE_CHECKING

from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    get_json_schema_validator,
)
from dorsal.file.schemas import OpenSchemaName, get_open_schema, OPEN_SCHEMA_NAME_MAP

if TYPE_CHECKING:
    audio_transcription: JsonSchemaValidator
    classification: JsonSchemaValidator
    document_extraction: JsonSchemaValidator
    embedding: JsonSchemaValidator
    entity_extraction: JsonSchemaValidator
    generic: JsonSchemaValidator
    geolocation: JsonSchemaValidator
    llm_output: JsonSchemaValidator
    object_detection: JsonSchemaValidator
    regression: JsonSchemaValidator

logger = logging.getLogger(__name__)

_VALIDATOR_LOOKUP = {schema_id.replace("-", "_"): schema_id for schema_id in OPEN_SCHEMA_NAME_MAP}
_VALIDATOR_LOOKUP.update({f"{k}_validator": v for k, v in _VALIDATOR_LOOKUP.items()})


@lru_cache(maxsize=None)
def _build_and_cache_validator(schema_name: OpenSchemaName, version: str) -> JsonSchemaValidator:
    """Internal helper to build and cache the validator on demand."""
    logger.debug("Building and caching validator for open schema: '%s'", schema_name)
    try:
        schema_dict = get_open_schema(schema_name, version=version)
        return get_json_schema_validator(schema_dict)
    except Exception as e:
        logger.error("Failed to build validator for '%s' v%s: %s", schema_name, version, e)
        raise RuntimeError(f"Failed to build validator for '{schema_name}' v{version}") from e


def get_open_schema_validator(name: OpenSchemaName, version: str = OPEN_VALIDATION_SCHEMAS_VER) -> JsonSchemaValidator:
    """Gets the pre-built, cached JsonSchemaValidator instance for a specific version."""
    if name not in OPEN_SCHEMA_NAME_MAP:
        raise ValueError(f"Unknown schema name: '{name}'.")
    return _build_and_cache_validator(name, version)


def __getattr__(name: str) -> JsonSchemaValidator:
    """Provides access to validators using the default library version."""
    schema_id = _VALIDATOR_LOOKUP.get(name)

    if schema_id:
        return _build_and_cache_validator(schema_id, OPEN_VALIDATION_SCHEMAS_VER)

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    """
    Expose dynamic attributes to dir() calls (e.g. for autocomplete or introspection).
    """
    return list(globals().keys()) + list(_VALIDATOR_LOOKUP.keys())


__all__ = list(_VALIDATOR_LOOKUP.keys()) + ["get_open_schema_validator"]
