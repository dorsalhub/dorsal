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

logger.debug("JsonSchemaValidator configured using jsonschema-rs backend.")

if TYPE_CHECKING:
    from jsonschema_rs import Validator as RsValidator


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
            self.validator: RsValidator = jsonschema_rs.validator_for(schema, validate_formats=True)
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
        """
        self.validator.validate(instance)

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
                    "record_preview": str(record)[:100],
                    "error_message": f"Invalid record type: {type(record).__name__}",
                    "path": [],
                    "validator": "type_check",
                }
            )
            continue

        try:
            validator.validate(record)
            valid_records_count += 1
        except JsonSchemaValidationError as err:
            record_str = str(record)
            record_preview = record_str[:150] + "..." if len(record_str) > 150 else record_str

            path_list = [str(p) for p in err.instance_path]

            error_details_list.append(
                {
                    "record_index": index,
                    "record_preview": record_preview,
                    "error_message": err.message,
                    "path": path_list,
                    "validator": validator_name,
                }
            )
            logger.debug(
                "Record at index %d failed validation against %s: %s (Path: %s)",
                index,
                validator_name,
                err.message,
                path_list,
            )
        except Exception as err:
            record_str = str(record)
            record_preview = record_str[:150] + "..." if len(record_str) > 150 else record_str
            error_details_list.append(
                {
                    "record_index": index,
                    "record_preview": record_preview,
                    "error_message": f"An unexpected error occurred during this record's validation: {str(err)}",
                    "path": [],
                    "validator": "unknown_error",
                }
            )
            logger.exception("Unexpected error validating record at index %d.", index)

    invalid_records_count = len(records) - valid_records_count

    summary = {
        "total_records": len(records),
        "valid_records": valid_records_count,
        "invalid_records": invalid_records_count,
        "error_details": error_details_list,
    }

    if invalid_records_count > 0:
        logger.warning(
            "Validation completed: %d valid, %d invalid out of %d total records.",
            valid_records_count,
            invalid_records_count,
            len(records),
        )
    else:
        logger.debug("Validation completed: All %d records are valid.", len(records))

    return summary
