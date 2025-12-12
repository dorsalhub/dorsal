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
from typing import Any, Literal, cast

from pydantic import BaseModel

from dorsal.client import DorsalClient
from dorsal.common.auth import is_offline_mode
from dorsal.common.constants import API_MAX_BATCH_SIZE
from dorsal.common.exceptions import (
    ApiDataValidationError,
    DorsalError,
    DorsalClientError,
    JSONSchemaSchemaError,
    DorsalOfflineError,
)
from dorsal.common.validators.datasets import Dataset
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    get_json_schema_validator,
    json_schema_validate_records,
)
from dorsal.file.validators.open_schema import get_open_schema_validator
from dorsal.session import get_shared_dorsal_client

logger = logging.getLogger(__name__)


class DatasetApiResponse(BaseModel):
    pass


def get_dataset(dataset_id: str, api_key: str | None = None, client: DorsalClient | None = None) -> Dataset:
    """Retrieves the full definition of an existing dataset from DorsalHub.

    Fetches a dataset's metadata, including its name, description, schema,
    and other properties.

    Example:
        ```python
        from dorsal.api import get_dataset

        try:
            # Fetch a public dataset from the 'dorsal' namespace
            dataset = get_dataset("dorsal/arxiv-cs-papers")
            print(f"Dataset Name: {dataset.name}")
            print(f"Description: {dataset.description}")
        except Exception as e:
            print(f"Could not retrieve dataset: {e}")
        ```

    Args:
        dataset_id (str): The unique identifier for the dataset, in the
            format "namespace/dataset-name".
        api_key (str, optional): An API key to use for this request, especially
            for private datasets. Defaults to None.

    Returns:
        Dataset: A Pydantic model instance representing the full dataset definition.

    Raises:
        NotFoundError: If no dataset with the specified ID is found.
        DorsalClientError: If the API call fails for any other reason.
    """
    logger.debug(
        "get_dataset called with id: '%s', api_key provided: %s",
        dataset_id,
        "Yes" if api_key else "No",
    )

    if client is None:
        try:
            client = get_shared_dorsal_client(api_key=api_key)
        except Exception as err:
            logger.exception("Failed to obtain shared DorsalClient instance.")
            raise DorsalClientError("Could not initialize or retrieve the API client.") from err

    try:
        dataset_response = client.get_dataset(dataset_id=dataset_id, api_key=api_key)
        logger.debug(
            "Successfully retrieved dataset ID: '%s'",
            dataset_id,
        )
        return dataset_response
    except (
        ValueError,
        DorsalClientError,
    ) as err:
        logger.warning(
            "API call to retrieve dataset (ID: '%s') failed: %s - %s",
            dataset_id,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error during client.get_dataset (ID: '%s').",
            dataset_id,
        )
        raise DorsalClientError(
            f"An unexpected issue occurred while fetching dataset '{dataset_id}' via the client."
        ) from err


def get_dataset_schema(dataset_id: str, api_key: str | None = None, client: DorsalClient | None = None) -> dict:
    """Fetches the JSON schema for a given dataset.

    Example:
        ```python
        from dorsal.api import get_dataset_schema

        try:
            schema = get_dataset_schema("dorsal/arxiv-cs-papers")
            print("Schema properties:")
            for prop in schema.get("properties", {}):
                print(f"- {prop}")
        except Exception as e:
            print(f"Could not retrieve schema: {e}")
        ```

    Args:
        dataset_id (str): Identifier for a dataset (e.g., "dorsal/arxiv").
        api_key (str, optional): An API key for this request.

    Returns:
        dict[str, Any]: The JSON schema of the dataset.

    Raises:
        ValueError: If `dataset_id` is invalid (propagated from `get_dataset`).
        DorsalClientError: Base client error or for unexpected issues (propagated
                           from `get_dataset`).
        AuthError: Authentication failure (propagated from `get_dataset`).
        NotFoundError: If the dataset is not found (propagated from `get_dataset`).
        ForbiddenError: Access to the dataset is denied (propagated from `get_dataset`).
        RateLimitError: If the request is rate-limited by the API (propagated from
                        `get_dataset`).
        NetworkError: If a network issue occurs (propagated from `get_dataset`).
        APIError: For other HTTP errors from the API (propagated from `get_dataset`).
        ApiDataValidationError: If the API response for the dataset is malformed and
                                cannot be parsed into a valid `Dataset` object
                                (propagated from `get_dataset`).
    """
    logger.debug(
        "Attempting to fetch schema for dataset_id: '%s'. API key used: %s",
        dataset_id,
        "Yes (user-provided)" if api_key else "No (client default)",
    )
    if client is None:
        try:
            client = get_shared_dorsal_client()
        except Exception as err:
            logger.exception("Failed to obtain shared DorsalClient instance.")
            raise DorsalClientError("Could not initialize or retrieve the API client.") from err

    try:
        schema = client.get_dataset_schema(dataset_id=dataset_id)
        logger.debug("Successfully retrieved schema via client for dataset_id: '%s'", dataset_id)
        return schema
    except (ValueError, DorsalClientError) as err:
        logger.warning(
            "Client call to retrieve schema for dataset_id '%s' failed: %s - %s",
            dataset_id,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error during client.get_dataset_schema call for dataset_id: '%s'.",
            dataset_id,
        )
        raise DorsalClientError(
            message=f"An unexpected issue occurred while fetching schema for dataset '{dataset_id}' via the client."
        ) from err


def make_schema_validator(
    dataset_id: str, api_key: str | None = None, client: DorsalClient | None = None
) -> JsonSchemaValidator:
    """Fetches a dataset's schema and returns a callable validator function.

    This is useful for validating records client-side before attempting to
    insert them, which can save API calls.

    Example:
        ```python
        from dorsal.api import make_schema_validator

        validator = make_schema_validator("my-org/my-book-collection")

        good_record = {"author": "J.R.R. Tolkien", "title": "The Hobbit"}
        bad_record = {"author": "J.R.R. Tolkien"} # Missing title

        try:
            validator(good_record)
            print("Good record is valid.")
            validator(bad_record)
        except Exception as e:
            print(f"Bad record is invalid: {e}")

        ```

    Args:
        dataset_id (str): Identifier for the dataset whose schema will be used.
        api_key (str, optional): An API key for this request.

    Returns:
        JsonSchemaValidator: A callable instance that validates a dictionary
            record against the fetched schema.

    Raises:
        ValueError: If `dataset_id` is invalid (propagated from `get_dataset`).
        DorsalClientError: Base client error or for unexpected issues (propagated
                           from `get_dataset`).
        AuthError: Authentication failure (propagated from `get_dataset`).
        NotFoundError: If the dataset is not found (propagated from `get_dataset`).
        ForbiddenError: Access to the dataset is denied (propagated from `get_dataset`).
        RateLimitError: If the request is rate-limited by the API (propagated from
                        `get_dataset`).
        NetworkError: If a network issue occurs (propagated from `get_dataset`).
        APIError: For other HTTP errors from the API (propagated from `get_dataset`).
        ApiDataValidationError: If the API response for the dataset is malformed and
                                cannot be parsed into a valid `Dataset` object
                                (propagated from `get_dataset`).
        JSONSchemaSchemaError: If the schema is invalid.

    """
    if dataset_id.startswith("open/"):
        schema_name = dataset_id.removeprefix("open/")
        try:
            return get_open_schema_validator(cast(Any, schema_name))
        except (ValueError, TypeError):
            pass

    if is_offline_mode():
        raise DorsalOfflineError(
            f"Cannot fetch validator for '{dataset_id}': System is in OFFLINE mode and this schema is locally available."
        )
    schema = get_dataset_schema(dataset_id=dataset_id, api_key=api_key, client=client)

    return get_json_schema_validator(schema=schema)


def validate_dataset_records(
    dataset_id: str,
    records: list[dict],
    schema_dict: dict | None = None,
    api_key: str | None = None,
    client: DorsalClient | None = None,
) -> dict:
    """Validates records against a dataset's JSON schema.

    Orchestrates schema retrieval (if a schema is not provided directly),  custom validator preparation,
        and record-by-record validation.
    Returns a summary of the validation results.

    Args:
        dataset_id: Identifier of the dataset. Used to fetch the schema if
                    `schema_dict` is None, and for logging/error context.
        records: A list of dictionaries, where each dictionary is a record
                 to be validated.
        schema_dict: Optional. A pre-fetched JSON schema dictionary. If provided,
                     `get_dataset_schema` will not be called.
        api_key: Optional API key, used by `get_dataset_schema` if `schema_dict` is not
                 provided. Uses the client's default if None.

    Returns:
        dict: A summary of validation results, including counts for total,
              valid, and invalid records, and detailed error information for
              each invalid record.

    Raises:
        ValueError: If `dataset_id` is invalid, `records` is not a list,
                    or if `schema_dict` is provided but is not a valid,
                    non-empty dictionary.
        ApiDataValidationError: If a schema (fetched or provided) is invalid or
                                cannot be used to prepare a validator (e.g., due
                                to `JSONSchemaSchemaError` during preparation).
        DorsalClientError: (And its subclasses like AuthError, NotFoundError,
                           NetworkError, APIError, etc.) Propagated if `get_dataset_schema`
                           is called and encounters an issue.
        JSONSchemaSchemaError: Propagated from `validate_records_with_validator`
                               if the validator's schema has issues found during
                               the record validation loop (should be rare if
                               `prepare_custom_validator` succeeds).
    """
    logger.debug(
        "Initiating record validation for dataset_id: '%s'. %s records. Schema provided: %s. API key: %s. Custom DorsalClient: %s",
        dataset_id,
        (len(records) if isinstance(records, list) else "Invalid 'records' input (not a list)"),
        "Yes" if schema_dict is not None else "No",
        "Yes (user-provided)" if api_key else "No (client default)",
        "Yes" if client else "No",
    )

    if not (isinstance(dataset_id, str) and dataset_id.strip()):
        logger.warning(
            "Dataset ID must be a non-empty string. Got: '%s' (type: %s)",
            dataset_id,
            type(dataset_id).__name__,
        )
        raise ValueError("Dataset ID must be a non-empty string.")

    if not isinstance(records, list):
        logger.warning("Input 'records' must be a list. Got: %s", type(records).__name__)  # type: ignore[unreachable]
        raise ValueError(f"Input 'records' must be a list, got {type(records).__name__}.")  # type: ignore[unreachable]

    actual_schema_to_use: dict
    if schema_dict is not None:
        logger.debug("Using user-provided schema for dataset_id: '%s'.", dataset_id)
        if not isinstance(schema_dict, dict) or not schema_dict:
            logger.warning(
                "Provided schema_dict for dataset_id '%s' must be a non-empty dictionary. Got type: %s",
                dataset_id,
                type(schema_dict).__name__,
            )
            raise ValueError("Provided schema_dict must be a non-empty dictionary.")
        actual_schema_to_use = schema_dict
    else:
        logger.debug("Schema not provided for dataset_id: '%s'; attempting to fetch.", dataset_id)
        try:
            actual_schema_to_use = get_dataset_schema(dataset_id=dataset_id.strip(), api_key=api_key, client=client)
            logger.debug("Successfully fetched schema for dataset_id: '%s'.", dataset_id)
        except Exception as err:
            logger.warning(
                "Failed to fetch schema for dataset_id '%s' (needed for validation): %s - %s",
                dataset_id,
                type(err).__name__,
                err,
            )
            raise

    try:
        validator = get_json_schema_validator(schema=actual_schema_to_use)
        logger.debug("Schema validator prepared successfully for dataset_id: '%s'.", dataset_id)
    except (ValueError, ApiDataValidationError) as err:
        logger.warning(
            "Failed to prepare schema validator for dataset_id '%s' using the schema. Error: %s - %s",
            dataset_id,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error preparing schema validator for dataset_id '%s'.",
            dataset_id,
        )
        raise ApiDataValidationError(
            f"Could not prepare validator for dataset_id '{dataset_id}' due to an unexpected error with the schema or validator setup."
        ) from err

    try:
        validation_summary = json_schema_validate_records(records=records, validator=validator)
        logger.debug(
            "Record validation process completed via helper for dataset_id: '%s'.",
            dataset_id,
        )
        return validation_summary
    except (ValueError, JSONSchemaSchemaError) as err:
        logger.warning(
            "Record validation failed for dataset_id '%s' due to issues within the validator or record structure: %s - %s",
            dataset_id,
            type(err).__name__,
            err,
        )
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error during the record validation stage for dataset_id '%s'.",
            dataset_id,
        )
        raise DorsalError(
            f"An unexpected error occurred while validating records for dataset_id '{dataset_id}'."
        ) from err
