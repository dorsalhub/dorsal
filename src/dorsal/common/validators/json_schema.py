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
from typing import Any, cast, List, TypeAlias, Type, TYPE_CHECKING

import jsonschema_rs

from dorsal.common.exceptions import (
    ApiDataValidationError,
    DorsalError,
    JsonSchemaValidationError,
    SchemaFormatError,
)


logger = logging.getLogger(__name__)

# See: https://json-schema.org/draft/2020-12/json-schema-validation
JSON_SCHEMA_CONSTRAINT_KEYWORDS = {
    "$ref",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "dependentSchemas",
    "properties",
    "patternProperties",
    "additionalProperties",
    "items",
    "additionalItems",
    "contains",
    "propertyNames",
    "type",
    "enum",
    "const",
    "multipleOf",
    "maximum",
    "exclusiveMaximum",
    "minimum",
    "exclusiveMinimum",
    "maxLength",
    "minLength",
    "pattern",
    "maxItems",
    "minItems",
    "uniqueItems",
    "maxContains",
    "minContains",
    "maxProperties",
    "minProperties",
    "required",
    "dependentRequired",
    "format",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
}

if TYPE_CHECKING:
    from jsonschema_rs import Validator as JsonSchemaRustValidator

VALUE_MASK = "…"
ERROR_MESSAGE_LIMIT = 1000
RECORD_PREVIEW_LIMIT = 150
ERROR_INPUT_PREVIEW_LIMIT = 100
PYDANTIC_ERRORS_LIMIT = 20


def shorten_text(text: str, limit: int) -> str:
    """Return `text`, cut to at most `limit` characters with a trailing ellipsis."""
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def bound_validation_error(err: Any) -> None:
    """Cap the text a jsonschema-rs `ValidationError` carries in its message, `str()` and `repr()`."""
    message = shorten_text(str(getattr(err, "message", "")), ERROR_MESSAGE_LIMIT)
    for attr, value in (
        ("message", message),
        ("verbose_message", shorten_text(str(getattr(err, "verbose_message", message)), ERROR_MESSAGE_LIMIT)),
    ):
        try:
            setattr(err, attr, value)
        except AttributeError:  # pragma: no cover
            pass
    err.args = (message,)


def preview_record(record: Any, limit: int = RECORD_PREVIEW_LIMIT) -> str:
    """Return a short preview of a record without formatting the whole of it."""
    import reprlib

    shortener = reprlib.Repr()
    shortener.maxlevel = 3
    shortener.maxdict = 6
    shortener.maxlist = 6
    shortener.maxstring = 60
    shortener.maxother = 60
    return shorten_text(shortener.repr(record), limit)


def bound_pydantic_errors(err: Any, max_errors: int = PYDANTIC_ERRORS_LIMIT) -> list[dict[str, Any]]:
    """
    Return up to `max_errors` of a Pydantic `ValidationError`'s error dicts, with record values bounded.

    `loc`, `type` and `url` are kept, `msg` is capped, and `input` and `ctx` values are replaced by short previews.
    """
    bounded: list[dict[str, Any]] = []
    for error in err.errors()[:max_errors]:
        item: dict[str, Any] = {
            "type": error.get("type"),
            "loc": tuple(
                shorten_text(part, ERROR_INPUT_PREVIEW_LIMIT) if isinstance(part, str) else part
                for part in error.get("loc", ())
            ),
            "msg": shorten_text(str(error.get("msg", "")), ERROR_MESSAGE_LIMIT),
            "input": preview_record(error.get("input"), ERROR_INPUT_PREVIEW_LIMIT),
        }
        ctx = error.get("ctx")
        if ctx:
            item["ctx"] = {
                key: value
                if value is None or isinstance(value, (bool, int, float))
                else preview_record(value, ERROR_INPUT_PREVIEW_LIMIT)
                for key, value in ctx.items()
            }
        if "url" in error:
            item["url"] = error["url"]
        bounded.append(item)
    return bounded


def format_pydantic_errors(err: Any, limit: int = ERROR_MESSAGE_LIMIT) -> str:
    """Return a one-line summary of a Pydantic `ValidationError`, capped at `limit` characters."""
    count = err.error_count()
    parts = [
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']} "
        f"[type={error['type']}, input={error['input']}]"
        for error in bound_pydantic_errors(err, max_errors=5)
    ]
    noun = "error" if count == 1 else "errors"
    return shorten_text(f"{count} validation {noun}: " + "; ".join(parts), limit)


class JsonSchemaValidator:
    """
    A wrapper around the jsonschema-rs validator.

    This class serves as a Carrier for the compiled Rust validator engine,
    while retaining access to the original schema dictionary (required by
    ModelRunner) and providing a concrete type for static analysis.
    """

    __slots__ = ("schema", "validator", "__name__")

    def __init__(self, schema: dict, strict: bool = True):
        self._validate_schema_structure(schema, strict)

        self.schema = schema

        title = schema.get("title", "Untitled")
        self.__name__ = f"JsonSchemaValidator[{title}]"

        try:
            self.validator: JsonSchemaRustValidator = jsonschema_rs.validator_for(
                schema, validate_formats=True, mask=VALUE_MASK
            )
        except Exception as err:
            logger.exception(
                "The provided schema is structurally invalid and cannot be used to create a validator: %s",
                err,
            )
            raise SchemaFormatError(
                message="The provided schema is invalid and cannot be used to prepare a validator.",
                schema_error_detail=str(err),
            ) from err

    def _validate_schema_structure(self, schema: Any, strict: bool) -> None:
        """Internal helper to validate input schema before compilation."""
        if not isinstance(schema, dict):
            logger.error("Schema must be a dictionary. Got type: %s", type(schema).__name__)
            raise TypeError(f"The 'schema' argument must be a dictionary, got {type(schema).__name__}.")

        if not schema:
            logger.error("Schema dictionary cannot be empty.")
            raise ValueError("The 'schema' dictionary cannot be empty.")

        if strict:
            if not any(key in schema for key in JSON_SCHEMA_CONSTRAINT_KEYWORDS):
                logger.warning("Schema appears to be inert (no constraint keywords found).")
                raise ValueError(
                    "The provided schema is inert: it contains no known JSON Schema "
                    "constraint keywords (like 'type', 'properties', '$ref', etc.) "
                    "and would silently pass all validation."
                )

    def validate(self, instance: Any) -> None:
        """
        Validate the instance, raising jsonschema_rs.ValidationError on failure.

        The error's message shows record values as `…` and is capped in length.
        """
        try:
            self.validator.validate(instance)
        except jsonschema_rs.ValidationError as err:
            bound_validation_error(err)
            raise

    def first_error(self, instance: Any) -> tuple[str, list[str | int], str] | None:
        """Return the message, instance path and keyword of an error in `instance`, or None if it is valid."""
        try:
            self.validator.validate(instance)
        except jsonschema_rs.ValidationError as err:
            bound_validation_error(err)
            keyword = next((str(part) for part in reversed(err.schema_path) if isinstance(part, str)), "")
            return err.message, list(err.instance_path), keyword
        return None

    def is_valid(self, instance: Any) -> bool:
        """Return True if valid, False otherwise."""
        return self.validator.is_valid(instance)

    def __call__(self, instance: Any) -> None:
        return self.validate(instance)


def get_json_schema_validator(schema: dict, strict: bool = True) -> JsonSchemaValidator:
    """Create a JsonSchemaValidator instance."""
    return JsonSchemaValidator(schema, strict=strict)


def json_schema_validate_records(records: list[dict] | Any, validator: JsonSchemaValidator) -> dict:
    """Validates records using a pre-configured jsonschema-rs validator."""
    validator_name = getattr(validator, "__name__", "JsonSchemaValidator")

    logger.debug(
        "Validating %s records with Rust validator '%s'.",
        len(records) if isinstance(records, list) else "an unknown number of",
        validator_name,
    )

    if not isinstance(records, list):
        logger.warning("Input 'records' must be a list. Got: %s", type(records).__name__)
        raise ValueError(f"Input 'records' must be a list, got {type(records).__name__}.")

    if not records:
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "error_details": [],
        }

    valid_records_count = 0
    error_details_list = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            error_details_list.append(
                {
                    "record_index": index,
                    "record_preview": preview_record(record, limit=100),
                    "error_message": f"Invalid record type: {type(record).__name__}",
                    "path": [],
                    "validator": "type_check",
                }
            )
            continue

        try:
            error = validator.first_error(record)
        except Exception as err:
            error_details_list.append(
                {
                    "record_index": index,
                    "record_preview": preview_record(record),
                    "error_message": "An unexpected error occurred during this record's validation: "
                    + shorten_text(str(err), ERROR_MESSAGE_LIMIT),
                    "path": [],
                    "validator": "unknown_error",
                }
            )
            logger.error("Unexpected %s validating record at index %d.", type(err).__name__, index)
            continue

        if error is None:
            valid_records_count += 1
            continue

        message, path, keyword = error
        path_str = " -> ".join(shorten_text(str(part), 100) for part in path) if path else "root"
        public_error = shorten_text(
            f"Validation failed at '{path_str}' ({keyword or 'schema'}): {message}", ERROR_MESSAGE_LIMIT
        )

        error_details_list.append(
            {
                "record_index": index,
                "record_preview": preview_record(record),
                "error_message": public_error,
                "path": path,
                "validator": validator_name,
            }
        )

        logger.debug("Record %d: %s", index, public_error)

    invalid_records_count = len(records) - valid_records_count

    summary = {
        "total_records": len(records),
        "valid_records": valid_records_count,
        "invalid_records": invalid_records_count,
        "error_details": error_details_list,
    }

    if invalid_records_count > 0:
        logger.debug(
            "Validation completed: %d valid, %d invalid out of %d total records.",
            valid_records_count,
            invalid_records_count,
            len(records),
        )
    else:
        logger.debug("Validation completed: All %d records are valid.", len(records))

    return summary
