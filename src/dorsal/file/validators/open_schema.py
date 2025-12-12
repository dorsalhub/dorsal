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

import logging
from functools import lru_cache
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    get_json_schema_validator,
)
from dorsal.file.schemas import OpenSchemaName, get_open_schema, OPEN_SCHEMA_NAME_MAP

logger = logging.getLogger(__name__)

_VALIDATOR_NAMES = {f"{name}_validator": name for name in OPEN_SCHEMA_NAME_MAP}


@lru_cache(maxsize=None)
def _build_and_cache_validator(schema_name: OpenSchemaName) -> JsonSchemaValidator:
    """Internal helper to build and cache the validator on demand."""
    logger.debug("Building and caching validator for open schema: '%s'", schema_name)
    try:
        schema_dict = get_open_schema(schema_name)
        return get_json_schema_validator(schema_dict)
    except Exception as e:
        logger.error("Failed to build lazy-loaded validator for '%s': %s", schema_name, e)
        raise RuntimeError(f"Failed to build validator for '{schema_name}'") from e


def get_open_schema_validator(name: OpenSchemaName) -> JsonSchemaValidator:
    """
    Gets the pre-built, cached JsonSchemaValidator instance for a
    Dorsal 'open/' schema by its short name.
    """
    if name not in OPEN_SCHEMA_NAME_MAP:
        raise ValueError(f"Unknown schema name: '{name}'.")
    return _build_and_cache_validator(name)


def __getattr__(name: str) -> JsonSchemaValidator:
    """
    Called by Python when a module attribute is not found.
    This allows for lazy-loading of the open schema validators
    when they are imported by name (e.g., by the ModelRunner).
    """
    schema_name = _VALIDATOR_NAMES.get(name)

    if schema_name:
        return _build_and_cache_validator(schema_name)

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "get_open_schema_validator",
] + list(_VALIDATOR_NAMES.keys())
