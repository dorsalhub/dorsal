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
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.validators.json_schema import JsonSchemaValidator
from dorsal.file.schemas import OpenSchemaName, get_open_schema, OPEN_SCHEMA_NAME_MAP, schema_version_of

if TYPE_CHECKING:
    import oatschema

    audio_transcription: "OpenSchemaValidator"
    classification: "OpenSchemaValidator"
    document_extraction: "OpenSchemaValidator"
    embedding: "OpenSchemaValidator"
    entity_extraction: "OpenSchemaValidator"
    generic: "OpenSchemaValidator"
    geolocation: "OpenSchemaValidator"
    llm_output: "OpenSchemaValidator"
    object_detection: "OpenSchemaValidator"
    regression: "OpenSchemaValidator"

logger = logging.getLogger(__name__)

_VALIDATOR_LOOKUP = {schema_id.replace("-", "_"): schema_id for schema_id in OPEN_SCHEMA_NAME_MAP}
_VALIDATOR_LOOKUP.update({f"{k}_validator": v for k, v in _VALIDATOR_LOOKUP.items()})


class OpenSchemaValidator(JsonSchemaValidator):
    """
    A JsonSchemaValidator for one version of an open schema.

    `validate` raises `jsonschema_rs.ValidationError`, as for any JsonSchemaValidator. Error details reported
    by `first_error` come from `oatschema`, unless `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` overrides the schema.
    """

    __slots__ = ("schema_name", "schema_version", "oats_validator")

    def __init__(self, name: OpenSchemaName, version: str = OPEN_VALIDATION_SCHEMAS_VER):
        schema = get_open_schema(name, version=version)
        super().__init__(schema)
        self.schema_name = name
        self.schema_version: str = schema_version_of(schema) or version
        self.oats_validator: "oatschema.Validator | None" = None
        if not os.getenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR):
            import oatschema

            self.oats_validator = oatschema.get_validator(cast("oatschema.SchemaName", name), version)

    def is_valid(self, instance: Any) -> bool:
        """Return True if valid, False otherwise."""
        if self.oats_validator is None:
            return super().is_valid(instance)
        return self.oats_validator.is_valid(instance)

    def first_error(self, instance: Any) -> tuple[str, list[str | int], str] | None:
        """Return the message, instance path and keyword of an error in `instance`, or None if it is valid."""
        if self.oats_validator is None:
            return super().first_error(instance)

        import oatschema

        try:
            self.oats_validator.validate(instance)
        except oatschema.ValidationError as err:
            return err.message, list(err.path), err.keyword
        return None


@lru_cache(maxsize=None)
def _build_and_cache_validator(schema_name: OpenSchemaName, version: str) -> OpenSchemaValidator:
    """Internal helper to build and cache the validator on demand."""
    logger.debug("Building and caching validator for open schema: '%s' v%s", schema_name, version)
    try:
        return OpenSchemaValidator(schema_name, version)
    except Exception as e:
        logger.debug("Failed to build validator for '%s' v%s: %s", schema_name, version, e)
        raise RuntimeError(f"Failed to build validator for '{schema_name}' v{version}: {e}") from e


def get_open_schema_validator(name: OpenSchemaName, version: str = OPEN_VALIDATION_SCHEMAS_VER) -> OpenSchemaValidator:
    """Gets the cached validator for one version of an open schema."""
    if name not in OPEN_SCHEMA_NAME_MAP:
        raise ValueError(f"Unknown schema name: '{name}'.")
    return _build_and_cache_validator(name, version)


def __getattr__(name: str) -> OpenSchemaValidator:
    """Provides access to validators using the default library version."""
    schema_id = _VALIDATOR_LOOKUP.get(name)

    if schema_id:
        try:
            return _build_and_cache_validator(schema_id, OPEN_VALIDATION_SCHEMAS_VER)
        except RuntimeError as err:
            if isinstance(err.__cause__, FileNotFoundError):
                raise AttributeError(
                    f"Open schema '{schema_id}' is not in schema version {OPEN_VALIDATION_SCHEMAS_VER}. "
                    f"Use get_open_schema_validator('{schema_id}', version=...) instead."
                ) from err
            raise

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    """
    Expose dynamic attributes to dir() calls (e.g. for autocomplete or introspection).
    """
    return list(globals().keys()) + list(_VALIDATOR_LOOKUP.keys())


__all__ = list(_VALIDATOR_LOOKUP.keys()) + ["get_open_schema_validator", "OpenSchemaValidator"]
