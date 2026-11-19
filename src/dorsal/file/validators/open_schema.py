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
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.validators.json_schema import JsonSchemaValidator, bound_validation_error
from dorsal.file.validators.numbers import (
    ON_BAD_NUMBER_DEFAULT,
    CheckedRecords,
    ConvertedValue,
    DroppedValue,
    OnBadNumber,
    check_open_schema_numbers,
    number_rejection_reason,
)
from dorsal.file.schemas import (
    OPEN_SCHEMA_NAME_MAP,
    OpenSchemaName,
    get_open_schema,
    open_schema_name,
    resolve_schema_id,
    schema_version_of,
)

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
    ranking: "OpenSchemaValidator"
    regression: "OpenSchemaValidator"
    temporal_segmentation: "OpenSchemaValidator"

logger = logging.getLogger(__name__)

_VALIDATOR_LOOKUP = {schema_id.replace("-", "_"): schema_id for schema_id in OPEN_SCHEMA_NAME_MAP}
_VALIDATOR_LOOKUP.update({f"{k}_validator": v for k, v in _VALIDATOR_LOOKUP.items()})


class OpenSchemaValidator(JsonSchemaValidator):
    """
    A JsonSchemaValidator for one version of an open schema.

    `validate` raises `oatschema.ValidationError`. Errors come from `oatschema`, unless
    `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` overrides the schema.
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

    def validate(self, instance: Any) -> None:
        """Validate the instance, raising `oatschema.ValidationError` on failure."""
        if self.oats_validator is not None:
            self.oats_validator.validate(instance)
            return

        import jsonschema_rs
        import oatschema

        try:
            self.validator.validate(instance)
        except jsonschema_rs.ValidationError as err:
            bound_validation_error(err)
            raise oatschema.ValidationError(
                err.message,
                schema_name=self.schema_name,
                schema_version=self.schema_version,
                path=tuple(err.instance_path),
                schema_path=tuple(err.schema_path),
            ) from err

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

    @property
    def checks_numbers(self) -> bool:
        """True if `check_numbers` uses `oatschema`, False if `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` overrides the schema."""
        return self.oats_validator is not None

    def check_numbers(
        self, records: list[Any], *, on_bad_number: OnBadNumber = ON_BAD_NUMBER_DEFAULT
    ) -> CheckedRecords:
        """
        Return copies of `records` whose numbers are safe to store, validated at this schema version.

        Bad optional numbers (NaN, ±infinity, beyond ±9007199254740991, or outside the field's bounds) are dropped,
        or rejected with `on_bad_number="raise"`; lossless conversions, such as `-0.0` to `0.0`, are made. Both are
        listed on the result. Nothing is rounded. When `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` overrides the schema,
        records are only validated against it.

        Raises:
            oatschema.ValidationError: A record is rejected, or isn't valid.
            TypeError: A record is not JSON data.
        """
        if self.oats_validator is None:
            for record in records:
                self.validate(record)
            return CheckedRecords([*records], [], [])
        return check_open_schema_numbers(records, self.schema_name, self.schema_version, on_bad_number=on_bad_number)


def verified_open_schema_version(schema_id: str | None, schema_version: str | None, records: Any) -> str | None:
    """
    Return the version to stamp on records that no OATS validator has checked yet.

    For an OATS `schema_id`, returns `schema_version` only if every record validates against it, otherwise None.
    Any other `schema_id` keeps its `schema_version`.
    """
    schema_name = open_schema_name(schema_id)
    if schema_name is None or schema_version is None:
        return schema_version

    try:
        validator = get_open_schema_validator(schema_name, version=schema_version)
    except RuntimeError as err:
        logger.warning("Not recording schema version '%s' for '%s': %s", schema_version, schema_name, err)
        return None

    if validator.schema_version != schema_version:
        logger.warning(
            "Not recording schema version '%s' for '%s': the schema loaded declares '%s'.",
            schema_version,
            schema_name,
            validator.schema_version,
        )
        return None

    items = records if isinstance(records, list) else [records]
    if all(validator.is_valid(record) for record in items):
        return schema_version

    logger.warning(
        "Not recording schema version '%s' for '%s': the record does not validate against it.",
        schema_version,
        schema_name,
    )
    return None


def stamped_schema_version(
    schema_id: str | None, requested: str | None, validator: Any, validated_version: str | None, records: Any
) -> str | None:
    """
    Return the version records may carry after `validator` accepted them.

    A built-in OATS validator proves `validated_version`. For an OATS `schema_id`, anything else is checked against
    the real schema: the version a custom JSON Schema declares, or else `requested`. Other ids keep
    `validated_version` from a JSON Schema validator and `requested` from anything else.
    """
    if isinstance(validator, OpenSchemaValidator):
        return validated_version
    if isinstance(validator, JsonSchemaValidator):
        if open_schema_name(schema_id) is None:
            return validated_version
        return verified_open_schema_version(schema_id, validated_version or requested, records)
    return verified_open_schema_version(schema_id, requested, records)


class StampedRecords(NamedTuple):
    """The version records may carry, and the records to keep, with what checking their numbers changed."""

    version: str | None
    records: list[Any]
    dropped: list[DroppedValue]
    converted: list[ConvertedValue]
    rejection: str | None = None
    number_rejection: str | None = None


def stamp_checked_records(
    schema_id: str | None,
    requested: str | None,
    validator: Any,
    validated_version: str | None,
    records: list[Any],
    *,
    on_bad_number: OnBadNumber = ON_BAD_NUMBER_DEFAULT,
    already_checked: bool = False,
) -> StampedRecords:
    """
    Return the version records may carry after `validator` accepted them, and the records to keep.

    An OATS record is stamped only after `oatschema.check_numbers` accepts it at that version, and the record it
    returns is kept. Pass `already_checked=True` when a built-in OATS validator's `check_numbers` produced the
    records. Records that fail the check keep their content and get no version, and `rejection` says why.
    """
    if open_schema_name(schema_id) is None or (already_checked and isinstance(validator, OpenSchemaValidator)):
        return StampedRecords(
            stamped_schema_version(schema_id, requested, validator, validated_version, records), records, [], []
        )

    version = requested
    if isinstance(validator, OpenSchemaValidator):
        version = validated_version
    elif isinstance(validator, JsonSchemaValidator):
        version = validated_version or requested
    schema_name = open_schema_name(schema_id)
    if version is None or schema_name is None:
        return StampedRecords(None, records, [], [])

    try:
        checker = get_open_schema_validator(schema_name, version=version)
    except RuntimeError as err:
        logger.warning("Not recording schema version '%s' for '%s': %s", version, schema_name, err)
        return StampedRecords(None, records, [], [])
    if checker.schema_version != version:
        logger.warning(
            "Not recording schema version '%s' for '%s': the schema loaded declares '%s'.",
            version,
            schema_name,
            checker.schema_version,
        )
        return StampedRecords(None, records, [], [])

    import oatschema

    try:
        checked = checker.check_numbers(records, on_bad_number=on_bad_number)
    except (oatschema.ValidationError, TypeError) as err:
        logger.warning(
            "Not recording schema version '%s' for '%s': the record does not pass its checks: %s",
            version,
            schema_name,
            err,
        )
        return StampedRecords(None, records, [], [], str(err), number_rejection_reason(err))
    return StampedRecords(version, checked.records, checked.dropped, checked.converted)


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
    """Gets the cached validator for one version of an OATS schema, such as `get_open_schema_validator("generic")`."""
    schema_name = open_schema_name(resolve_schema_id(name)) if isinstance(name, str) else None
    if schema_name is None:
        raise ValueError(f"Unknown schema name: '{name}'.")
    return _build_and_cache_validator(schema_name, version)


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
