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
import datetime
from typing import Any, cast

import jsonschema
from jsonschema.validators import (
    Draft202012Validator,
    extend as extend_jsonschema_validator,
)
from jsonschema.exceptions import SchemaError as JSONSchemaSchemaError
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError
from jsonschema.protocols import Validator as jsonschema_Validator

from dorsal.common.exceptions import (
    ApiDataValidationError,
    DorsalError,
    SchemaFormatError,
)


logger = logging.getLogger(__name__)

# See: https://json-schema.org/draft/2020-12/json-schema-validation
JSON_SCHEMA_LIVENESS_KEYWORDS = {
    "$schema",
    "$ref",
    "$defs",
    "definitions",
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
    "title",
    "description",
    "default",
    "deprecated",
    "readOnly",
    "writeOnly",
    "examples",
}


def is_datetime_instance(checker, instance) -> bool:
    """Checks if an instance is a Python datetime.datetime object."""
    return isinstance(instance, datetime.datetime)


_extended_type_checker = Draft202012Validator.TYPE_CHECKER.redefine("datetime", is_datetime_instance)

JsonSchemaValidator = extend_jsonschema_validator(Draft202012Validator, type_checker=_extended_type_checker)

JsonSchemaValidatorType = jsonschema_Validator


logger.debug("JsonSchemaValidator class configured with 'datetime' type support.")


def get_json_schema_validator(schema: dict, strict: bool = False) -> JsonSchemaValidatorType:
    """
    Prepares a configured jsonschema validator instance for a given schema.

    This function first performs structural validation (metaschema check) to ensure
    the input schema adheres to the rules of the JSON Schema specification (Draft 2020-12).

    Args:
        schema: The JSON Schema (as a dictionary) to validate against.
        strict: If True, performs an **added "liveness" check** to ensure the schema
                contains actual validation keywords (e.g., 'type', 'properties').
                Defaults to False.

    Returns:
        JsonSchemaValidatorType: A callable jsonschema validator instance.

    Raises:
        TypeError: If the input schema is not a dictionary.
        ValueError: If the input schema is empty, or if `strict=True` and the schema
                    is found to be inert (lacks validation keywords).
        SchemaFormatError: If the input schema is structurally invalid (fails
                           the metaschema check, e.g., 'type' is not a string/array).
        DorsalError: For unexpected errors during initialization.
    """

    logger.debug("Preparing custom validator for the provided JSON schema.")

    if not isinstance(cast(Any, schema), dict):
        logger.error("Schema must be a dictionary. Got type: %s", type(schema).__name__)
        raise TypeError(
            f"The 'schema' argument must be a dictionary, got {type(schema).__name__}."
            " Tip: If your schema is a JSON string, use 'json.loads(your_string)' first."
        )

    if not schema:
        logger.error("Schema dictionary cannot be empty.")
        raise ValueError("The 'schema' dictionary cannot be empty.")

    if strict:
        if not any(key in schema for key in JSON_SCHEMA_LIVENESS_KEYWORDS):
            logger.warning("Schema appears to be inert (no validation keywords found).")
            raise ValueError(
                "The provided schema appears to be inert: it contains no known JSON Schema "
                "validation keywords (like 'type', 'properties', etc.) "
                "and would silently pass all validation."
            )

    try:
        Draft202012Validator.check_schema(schema)

        validator_instance = JsonSchemaValidator(schema=schema, format_checker=jsonschema.FormatChecker())
        logger.debug("Custom validator instance prepared successfully for the schema.")
        return validator_instance

    except JSONSchemaSchemaError as err:
        logger.exception(
            "The provided schema is structurally invalid and cannot be used to create a validator: %s",
            err.message,
        )
        raise SchemaFormatError(
            message="The provided schema is invalid and cannot be used to prepare a validator.",
            schema_error_detail=err.message,
        ) from err
    except Exception as err:
        logger.exception("Unexpected error initializing custom validator with the provided schema.")
        raise DorsalError(
            "Could not initialize validator with the provided schema due to an unexpected error."
        ) from err


def json_schema_validate_records(records: list[dict] | Any, validator: JsonSchemaValidatorType) -> dict:
    """Validates records using a pre-configured jsonschema validator."""
    logger.debug(
        "Validating %s records with provided validator instance (type: %s).",
        len(records) if isinstance(records, list) else "an unknown number of",
        type(validator).__name__,
    )

    if not isinstance(records, list):
        logger.warning("Input 'records' must be a list. Got: %s", type(records).__name__)
        raise ValueError(f"Input 'records' must be a list, got {type(records).__name__}.")

    if not records:
        logger.debug("Records list is empty. No validation performed.")
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "error_details": [],
        }

    for i, record_item in enumerate(records):
        if not isinstance(record_item, dict):
            logger.warning(
                "All items in 'records' list must be dictionaries. Item at index %d is type %s.",
                i,
                type(record_item).__name__,
            )
            raise ValueError(
                f"All items in 'records' list must be dictionaries. Item at index {i} is type {type(record_item).__name__}."
            )

    valid_records_count = 0
    error_details_list = []

    for index, record in enumerate(records):
        try:
            validator.validate(instance=record)
            valid_records_count += 1
        except JSONSchemaValidationError as err:
            record_str = str(record)
            record_preview = record_str[:150] + "..." if len(record_str) > 150 else record_str
            error_details_list.append(
                {
                    "record_index": index,
                    "record_preview": record_preview,
                    "error_message": err.message,
                    "path": [str(p) for p in err.path],
                    "validator": err.validator,
                }
            )
            logger.debug(
                "Record at index %d failed validation: %s (Path: %s, Validator: %s)",
                index,
                err.message,
                list(err.path),
                err.validator,
            )
        except JSONSchemaSchemaError as err:
            logger.exception(
                "Invalid schema detected by validator instance during validation of record at index %d. Error: %s",
                index,
                err.message,
            )
            raise SchemaFormatError(
                message=f"Problematic schema encountered by validator during validation of record at index {index}.",
                schema_error_detail=err.message,
            ) from err
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
