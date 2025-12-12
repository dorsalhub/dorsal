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
from typing import Any

from jsonschema.exceptions import SchemaError as JSONSchemaSchemaError  # noqa: F401
from jsonschema.exceptions import (
    ValidationError as JSONSchemaValidationError,
)  # noqa: F401
from pydantic import ValidationError as PydanticValidationError  # noqa: F401

from dorsal.common import constants
from dorsal.common.constants import BASE_URL


class DorsalError(Exception):
    """Base class for all custom exceptions raised by the Dorsal library."""

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message)
        self.request_url = request_url
        self.original_exception = original_exception

    def __str__(self):
        base_message = super().__str__()
        return f"{base_message}"


class DorsalConfigError(DorsalError):
    """Config (dorsal.toml) error."""


class DorsalOfflineError(DorsalError):
    def __init__(self, message: str = "Operation blocked: Offline Mode is active."):
        super().__init__(message)


# == Validation Errors ==


class NotPopulatedError(DorsalError):
    """Indicates data is incomplete."""


class ValidationError(DorsalError):
    """Base validation error class."""


class UnsupportedHashError(ValidationError):
    """Unsupported file hash."""


class BatchSizeError(ValidationError):
    """The size of the request is too large."""


class SchemaFormatError(ValidationError):
    """Indicates that a JSON schema document is structurally invalid or unprocessable."""

    def __init__(
        self,
        message: str,
        schema_error_detail: str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message)
        self.schema_error_detail = schema_error_detail
        self.original_exception = original_exception

    def __str__(self):
        msg = self.args[0]
        if self.schema_error_detail:
            msg += f"\nSchema Detail: {self.schema_error_detail}"
        return msg


class RecordValidationError(ValidationError):
    """Indicates records failed client-side validation against the dataset's schema."""

    def __init__(self, message: str, dataset_id: str, validation_summary: dict | None = None):
        super().__init__(message)
        self.dataset_id = dataset_id
        self.validation_summary = validation_summary

    def __str__(self):
        msg = super().__str__()
        if self.validation_summary:
            msg += (
                f"\nDataset ID: {self.dataset_id}. "
                f"Client-side validation summary: "
                f"Total: {self.validation_summary.get('total_records', 'N/A')}, "
                f"Valid: {self.validation_summary.get('valid_records', 'N/A')}, "
                f"Invalid: {self.validation_summary.get('invalid_records', 'N/A')}."
            )
        return msg


class TaggingError(ValidationError):
    """Error tagging a file."""

    info_url = constants.DOCS_URL_DORSAL_FILE_TAGS
    extra_info_template = f"\nDorsal File Tags Documentation: {info_url}"

    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self):
        return f"{self.args[0]}\n\n{self.extra_info_template}"


class DuplicateTagError(TaggingError):
    """A duplicate tag exists."""


class InvalidTagError(TaggingError):
    """Tag is invalid."""


class AttributeConflictError(DorsalError):
    """
    Raised when an attribute or key cannot be set because it already
    exists and overwriting is not permitted by the operation.
    """

    def __init__(self, message: str):
        super().__init__(message=message)


class TemplateNotFoundError(DorsalError):
    """Raised when a report template or its essential files cannot be found."""

    pass


# == dorsal.api ==
class DatasetTypeError(DorsalError):
    """Raised when the type of a dataset prevents some action."""


# == /client ==
class DorsalClientError(DorsalError):
    """Dorsal Python client error."""

    info_url = constants.DOCS_URL_API_TROUBLESHOOTING
    extra_info = f"For help troubleshooting client errors, visit: {info_url}"

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.request_url = request_url
        self.original_exception = original_exception

    def __str__(self):
        message = f"{self.args[0]}"
        if self.request_url:
            message += f"\nRequest URL: {self.request_url}"

        message += f"\n\n{self.extra_info}"
        return message


class AuthError(DorsalClientError):
    """Error for client-side authentication or API key configuration issues."""

    info_url = constants.DOCS_URL_API_AUTH
    extra_info_template = f"\nFor more information about authentication, visit: {info_url}"

    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self):
        return f"{self.args[0]}\n\n{self.extra_info_template}"


class NetworkError(DorsalClientError):
    """Network error e.g. timeout or other connectivity issues."""

    info_url = constants.DOCS_URL_API_ERRORS_NETWORK
    extra_info = (
        f"Could not reach the API. Please check your network connection \nFor more information, visit: {info_url}"
    )

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message)
        self.request_url = request_url
        self.original_exception = original_exception

    def __str__(self):
        message = f"{self.args[0]}"
        if self.request_url:
            message += f"\nRequest URL: {self.request_url}"
        if self.original_exception:
            message += f"\nDetails: {type(self.original_exception).__name__}: {str(self.original_exception)}"

        message += f"\n\n{self.extra_info}"
        return message


class APIError(DorsalClientError):
    """HTTP Error (4xx/5xx)."""

    info_url = constants.DOCS_URL_API_ERRORS
    extra_info = (
        "The API returned an error. Check the status code and details for more information."
        f"\nFor more information on API error codes, visit: {info_url}"
    )

    def __init__(
        self,
        status_code: int,
        detail: str | dict,
        request_url: str | None = None,
        response_text: str | None = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.request_url = request_url
        self.response_text = response_text

        if isinstance(detail, dict) and "detail" in detail:
            error_summary = detail["detail"]
        elif isinstance(detail, str):
            error_summary = detail
        else:
            error_summary = "No detail provided."

        base_message = f"API Error {status_code}: {error_summary}"
        super().__init__(base_message)

    def __str__(self):
        message = f"{self.args[0]}"
        if self.request_url:
            message += f"\nRequest URL: {self.request_url}"

        if isinstance(self.detail, dict) and self.detail.get("detail") != self.args[0].split(": ", 1)[-1]:
            full_detail_str = json.dumps(self.detail, indent=2)
            message += f"\nFull API Response Detail:\n{full_detail_str}"
        elif isinstance(self.detail, str) and self.detail != self.args[0].split(": ", 1)[-1]:
            message += f"\nAPI Response Detail: {self.detail}"

        message += f"\n\n{self.extra_info}"
        return message


class BadRequestError(DorsalClientError):
    """400 Bad Request error."""

    def __init__(self, message: str, request_url: str, response_text: str | None = None):
        self.request_url = request_url
        self.response_text = response_text
        super().__init__(f"{message}")


class NotFoundError(DorsalClientError):
    """404 Not Found error."""

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        response_text: str | None = None,
    ):
        self.request_url = request_url
        self.response_text = response_text
        super().__init__(f"{message}")


class ForbiddenError(DorsalClientError):
    """403 Forbidden error."""

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        response_text: str | None = None,
    ):
        self.request_url = request_url
        self.response_text = response_text
        full_message = f"{message}" if request_url else message
        super().__init__(full_message)


class ConflictError(DorsalClientError):
    """409 Conflict error."""

    def __init__(
        self,
        message: str,
        request_url: str | None = None,
        response_text: str | None = None,
    ):
        self.request_url = request_url
        self.response_text = response_text
        full_message = f"{message}" if request_url else message
        super().__init__(full_message)


class RateLimitError(DorsalClientError):
    """429 Too Many Requests error."""

    def __init__(
        self,
        message: str,
        request_url: str,
        retry_after: str | int | None = None,
        response_text: str | None = None,
    ):
        self.request_url = request_url
        self.retry_after = retry_after
        self.response_text = response_text
        super_message = f"{message} for {request_url}"
        if retry_after:
            super_message += f". Try again after {retry_after} seconds."
        super().__init__(super_message)


class ApiDataValidationError(DorsalClientError):
    """API response parsing/validation error."""

    info_url = constants.DOCS_URL_API_ERRORS_VALIDATION
    extra_info_template = (
        f"An error occurred when parsing or validating the API response. \nFor more information, visit: {info_url}"
    )

    def __init__(
        self,
        message: str,
        *,
        request_url: str | None = None,
        validation_errors: list | dict | str | None = None,
        response_text_snippet: str | None = None,
        original_exception: Exception | None = None,
    ):
        """
        Args:
            message: A concise description of the validation/decoding error.
            request_url: The URL that was being accessed.
            validation_errors: Specific validation errors (e.g., from Pydantic).
            response_text_snippet: A snippet of the problematic response text.
            original_exception: The underlying exception (e.g., JSONDecodeError, pydantic.ValidationError).
        """
        super().__init__(message)
        self.request_url = request_url
        self.validation_errors = validation_errors
        self.response_text_snippet = response_text_snippet
        self.original_exception = original_exception

    def __str__(self):
        message = f"{self.args[0]}"
        if self.request_url:
            message += f"\nRequest URL: {self.request_url}"
        if self.validation_errors:
            try:
                errors_str = json.dumps(self.validation_errors, indent=2)
            except TypeError:
                errors_str = str(self.validation_errors)
            message += f"\nValidation Issues:\n{errors_str}"
        if self.response_text_snippet:
            message += f"\nProblematic Response Snippet: {self.response_text_snippet}"
        if self.original_exception and not self.validation_errors:
            message += f"\nUnderlying Error: {type(self.original_exception).__name__}: {str(self.original_exception)}"

        message += f"\n\n{self.extra_info_template}"
        return message


# == ModelRunner ==
class ModelRunnerError(DorsalError):
    """Base class for errors specific to the ModelRunner."""

    def __init__(self, message: str, original_exception: Exception | None = None):
        super().__init__(message)
        self.original_exception = original_exception


class ModelRunnerConfigError(ModelRunnerError):
    """Errors related to loading or validating the ModelRunner pipeline configuration."""


class ModelImportError(ModelRunnerError):
    """Errors that occur when trying to import a model or its validator."""

    def __init__(self, callable_path_str: str, original_exception: Exception):
        message = f"Failed to import '{callable_path_str}'"
        super().__init__(message, original_exception)
        self.callable_path_str = callable_path_str


class BaseModelProcessingError(ModelRunnerError):
    """Critical error during the processing of the essential base file model."""


class ModelExecutionError(ModelRunnerError):
    """Error during the execution of an individual annotation model's 'main' method."""

    def __init__(self, model_name: str, file_path: str, original_exception: Exception):
        message = f"Error executing model '{model_name}' for file '{file_path}'"
        super().__init__(message, original_exception)
        self.model_name = model_name
        self.file_path = file_path


class ModelOutputValidationError(ModelRunnerError):
    """Error when a model's output fails Pydantic validation."""

    def __init__(
        self,
        model_name: str,
        validator_name: str,
        errors: list[Any],
        original_exception: Exception | None,
    ):
        message = f"Output from model '{model_name}' failed validation against '{validator_name}'"
        super().__init__(message, original_exception)
        self.model_name = model_name
        self.validator_name = validator_name
        self.validation_errors = errors


class DependencyCheckError(ModelRunnerError):
    """Error occurred within a dependency checker function itself."""

    def __init__(self, checker_path_str: str, original_exception: Exception):
        message = f"Error in dependency checker '{checker_path_str}'"
        super().__init__(message, original_exception)
        self.checker_path_str = checker_path_str


class DependencyNotMetError(ModelRunnerError):
    """A required dependency for a model was not met.
    If this was a non-silent dependency, ModelRunner.run() will propagate this error.
    """

    def __init__(
        self,
        model_name: str,
        dependency_type: str,
        silent: bool,
        details: str | None = None,
    ):
        base_message = f"Dependency '{dependency_type}' not met for model '{model_name}'"
        if details:
            base_message += f": {details}"
        message = f"{base_message} (Silent: {silent})"
        super().__init__(message)
        self.model_name = model_name
        self.dependency_type = dependency_type
        self.silent = silent


class PipelineIntegrityError(ModelRunnerError):
    """Error indicating an unexpected state or structure in the pipeline results during merging."""


class MissingHashError(ModelRunnerError):
    """A required hash (e.g., validation hash) was not found after base model processing."""


# == Hashers ==


class QuickHasherError(DorsalError):
    """Base class for errors specific to QuickHasher operations."""

    def __init__(self, message: str, file_path: str | None = None):
        super().__init__(message)
        self.file_path = file_path
        self.message = message

    def __str__(self) -> str:
        msg = self.message
        if self.file_path:
            msg += f" (File: {self.file_path})"
        return msg


class QuickHashFileInstabilityError(QuickHasherError):
    """Error indicating the file changed or was inconsistent during hashing."""


class QuickHashConfigurationError(QuickHasherError, ValueError):
    """Error related to QuickHasher internal configuration."""


class QuickHashFileSizeError(QuickHasherError, ValueError):
    """Error for file size being outside permitted QuickHasher range when configured to raise."""


# == /file ===


class DuplicateFileError(DorsalError):
    """Duplicate file error."""

    info_url = f"{BASE_URL}/duplicate-files#howto"
    extra_info = (
        f"You cannot index identical files or records at the same time.\n  For more information, visit {info_url}"
    )

    def __init__(self, message, file_paths: list[str] | None = None):
        super().__init__(message)
        self.file_paths = file_paths

    def __str__(self):
        original_message = self.args[0]

        full_message = f"{original_message}"
        if self.file_paths:
            full_message += "\n\nDuplicates:"
            for file_path in self.file_paths:
                full_message += f"\n  {file_path}"
        full_message += f"\n\n{self.extra_info}"
        return full_message


class ReadError(DorsalError):
    """Read error."""


class UnexpectedResponseError(DorsalClientError):
    """The API returned an unexpected response."""


class DatasetExistsError(ConflictError):
    """Dataset exists."""


# == FileAnnotator ==


class FileAnnotatorError(DorsalError):
    """Base exception for all errors originating from the FileAnnotator."""


class AnnotationConfigurationError(FileAnnotatorError):
    """Raised when the configuration for an annotation task is invalid."""


class AnnotationImportError(FileAnnotatorError):
    """Raised when an annotation model or its validator fails to import."""


class AnnotationExecutionError(FileAnnotatorError):
    """Raised when an annotation model fails during execution or its output is invalid."""


class AnnotationValidationError(FileAnnotatorError):
    """Raised when a manually provided annotation fails validation against a schema."""

    def __init__(
        self,
        message: str,
        validation_errors: list | dict | str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message, original_exception=original_exception)
        self.validation_errors = validation_errors


# File Collections


class SyncConflictError(DorsalError):
    """
    Raised when a sync operation is blocked because the remote collection has changed since the last synchronization.
    """


# Data quality


class DataQualityError(DorsalError):
    """Raised when a data quality rule triggers it."""


# Preprocessing


class PDFProcessingError(DorsalError):
    """Raised when PDF processing fails (corruption, password protection, etc.)."""


class DependencyError(DorsalError):
    """Raised when optional dependencies are missing."""
