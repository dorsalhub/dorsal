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

from __future__ import annotations
from functools import wraps
import importlib
import inspect
import json
import logging
import os
import time
from typing import Any, NamedTuple, Type, TYPE_CHECKING, TypeVar, cast, Callable

from pydantic import BaseModel, Field, ConfigDict, ValidationInfo, field_validator

from dorsal.common import constants
from dorsal.common.exceptions import (
    BaseModelProcessingError,
    DataQualityError,
    DependencyCheckError,
    DependencyNotMetError,
    ModelExecutionError,
    ModelImportError,
    ModelOutputValidationError,
    ModelRunnerError,
    ModelRunnerConfigError,
    MissingHashError,
    ReadError,
    PipelineIntegrityError,
    PydanticValidationError,
    ValidationError,
)
from dorsal.common.model import AnnotationModel, AnnotationModelSource
from dorsal.common.validators import (
    CallableImportPath,
    JsonSchemaValidator,
    JsonSchemaValidatorType,
    StringNotEmpty,
    String4096,
    import_callable,
    json_schema_validate_records,
)
from dorsal.file.linters import apply_linter
from dorsal.file.utils.hashes import HashFunction

T = TypeVar("T", bound=BaseModel)

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import FileRecordStrict
    from dorsal.file.configs.model_runner import (
        DependencyConfig,
        ModelRunnerPipelineStep,
        RunModelResult,
    )

logger = logging.getLogger(__name__)


def model_debug_timer(method):
    """Decorates method - provides execution time.
    - Stores execution time of each model in `time_taken` instance mapping
    - Requires: `self.debug = True` on ModelRunner instance

    """

    @wraps(method)
    def _impl(instance, annotation_model: AnnotationModel, *method_args, **method_kwargs):
        if instance.debug:
            model_name = getattr(annotation_model, "__name__", "unknown")
            start_time = time.perf_counter()
            result: RunModelResult = method(instance, annotation_model, *method_args, **method_kwargs)
            end_time = time.perf_counter()
            instance.time_taken[model_name] = end_time - start_time
            result.time_taken = instance.time_taken.get(model_name)
            return result
        return method(instance, annotation_model, *method_args, **method_kwargs)

    return _impl


class ModelRunner:
    exclude_none: bool = True

    def __init__(
        self, pipeline_config: str | list[dict[str, Any]] | None = "default", debug: bool = False, testing: bool = False
    ):
        """
        Initializes the ModelRunner.

        Args:
            pipeline_config: Configuration for models to run after the base model.
                - str: "default", uses the default built-in pipeline.
                - str: Any string other than "default" is a file path to a JSON file containing the pipeline configuration list.
                - list: A direct list of configuration dictionaries. An empty list [] means
                        only the base model will be run with its effective options.
                - None: No pipeline will be set up. Useful for when you only need
            debug: If True, enables timing of model executions.
            testing: If True, supresses warning about the pipeline_config being set to None
        """
        from dorsal.common.config import load_config

        self.pipeline: "list[ModelRunnerPipelineStep]" = []
        self.pipeline_config_source: str
        if pipeline_config is None:
            self.pipeline_config_source = "No pipeline"
        elif pipeline_config == "default":
            _, config_path = load_config()
            self.pipeline_config_source = f"dorsal.toml {config_path}"
        elif isinstance(pipeline_config, str):
            self.pipeline_config_source = f"JSON Path: {pipeline_config}"
        elif isinstance(pipeline_config, list):
            self.pipeline_config_source = f"Custom {len(pipeline_config)} step pipeline"
        else:
            raise ModelRunnerConfigError(f"Invalid pipeline_config type: {type(pipeline_config).__name__}")

        self.debug = debug
        self.time_taken: dict[str, float] = {}

        self.pre_model = self._load_pre_pipeline_model_step()

        if pipeline_config is None:
            if not testing:
                logger.warning(
                    "Pipeline is being executed with pipeline_config set to `None` - this means any config will be ignored."
                )
        else:
            self.pipeline = self._load_raw_pipeline_config_steps(config=pipeline_config)

        self._log_warnings_for_duplicate_models(self.pipeline)

        self.pre_model_options: dict[str, Any] | None = self.pre_model.options

        if self.pipeline and self._is_matching_model_step(
            self.pipeline[0],
            self.pre_model.annotation_model.module,
            self.pre_model.annotation_model.name,
        ):
            logger.debug(
                "First step of the loaded pipeline matches the base model definition. "
                "Using options from this step for the base model execution."
            )
            self.pre_model_options = self.pipeline[0].options
            self.pipeline = self.pipeline[1:]
            logger.debug(
                "Base model options have been updated. The effective pipeline to run will start "
                "from the second step of the loaded configuration."
            )
        else:
            logger.debug(
                "Using default options for base model execution. The effective pipeline to run will "
                "consist of all loaded steps (if any)."
            )

        logger.debug(
            "ModelRunner initialized. Debug mode: %s. Pipeline models to run: %d. Config source: '%s'",
            "ON" if self.debug else "OFF",
            len(self.pipeline),
            self.pipeline_config_source,
        )

    def _load_pre_pipeline_model_step(self) -> ModelRunnerPipelineStep:
        from dorsal.file.configs.model_runner import (
            BASE_ANNOTATION_MODEL,
            ModelRunnerPipelineStep,
        )

        try:
            pre_model = ModelRunnerPipelineStep(**BASE_ANNOTATION_MODEL)
        except PydanticValidationError as err:
            logger.critical(
                "Failed to validate internal BASE_ANNOTATION_MODEL structure: %s. This is a critical setup error.",
                err.errors(),
                exc_info=True,
            )
            raise ModelRunnerConfigError("Internal BASE_ANNOTATION_MODEL is invalid.", original_exception=err) from err
        return pre_model

    def _load_raw_pipeline_config_steps(self, config: str | list[dict[str, Any]]) -> list[ModelRunnerPipelineStep]:
        """
        Loads and validates the raw pipeline configuration steps from the provided source.
        These steps run *after* the initial base model.

        - If config is None, loads default pipeline from config toml.
        - If config is an empty list [], returns an empty list (only base model runs).
        - If config is a path or a non-empty list, loads and validates those steps.
        """
        from dorsal.common.config import load_config
        from dorsal.file.configs.model_runner import ModelRunnerPipelineStep

        pipeline: list[dict[str, Any]]
        if config == "default":
            logger.debug("Resolving 'default' pipeline configuration from dorsal.toml hierarchy.")
            full_config, _ = load_config()
            pipeline = full_config.get("model_pipeline", [])
        elif isinstance(config, list):
            if not config:
                logger.info("pipeline_config is an empty list. Only the base annotation model will run.")
            else:
                logger.info(f"User-defined {len(config)}-step pipeline.")
            pipeline = config
        elif isinstance(config, str):
            logger.info("Loading pipeline configuration from file: %s", config)
            try:
                with open(config, "r") as fp:
                    loaded_json = json.load(fp)
                if not isinstance(loaded_json, list):
                    raise ModelRunnerConfigError(
                        f"Pipeline config file '{config}' content must be a JSON list, got {type(loaded_json).__name__}."
                    )
                pipeline = loaded_json
                if not pipeline:
                    logger.info("Pipeline config file '%s' contained an empty list.", config)
            except FileNotFoundError as err:
                logger.error("Pipeline config file not found: %s", config, exc_info=True)
                raise ModelRunnerConfigError(
                    f"Pipeline config file not found: {config}", original_exception=err
                ) from err
            except json.JSONDecodeError as err:
                logger.error(
                    "Failed to parse pipeline config file %s as JSON: %s",
                    config,
                    err.msg,
                    exc_info=True,
                )
                raise ModelRunnerConfigError(
                    f"Cannot parse pipeline config file {config} as JSON: {err.msg}",
                    original_exception=err,
                ) from err
            except Exception as err:
                logger.error(
                    "Unexpected error reading or parsing pipeline config file %s: %s",
                    config,
                    err,
                    exc_info=True,
                )
                raise ModelRunnerConfigError(f"Cannot read/parse config file {config}", original_exception=err) from err
        else:
            raise ModelRunnerConfigError(f"Invalid pipeline_config type during raw load: {type(config).__name__}")

        if not pipeline:
            logger.info(
                "Pipeline configuration (from source: '%s') is empty. "
                "Only the base model will be executed (with its default options).",
                self.pipeline_config_source,
            )
            return []

        validated_pipeline: list[ModelRunnerPipelineStep] = []
        for i, step_config_dict in enumerate(pipeline):
            try:
                validated_step = ModelRunnerPipelineStep.model_validate(step_config_dict)
                validated_pipeline.append(validated_step)
            except PydanticValidationError as err:
                error_details = err.errors()
                logger.error(
                    "Invalid configuration for pipeline step at index %d (source: '%s'): %s. Step data: %s",
                    i,
                    self.pipeline_config_source,
                    error_details,
                    str(step_config_dict)[:500],
                )
                raise ModelRunnerConfigError(
                    f"Invalid config for pipeline step {i} (source: '{self.pipeline_config_source}'). Details: {error_details}",
                    original_exception=err,
                ) from err

        logger.debug(
            "Pipeline successfully loaded and validated with %d step(s) from source: '%s'.",
            len(validated_pipeline),
            self.pipeline_config_source,
        )
        return validated_pipeline

    def _log_warnings_for_duplicate_models(self, pipeline_steps: list[ModelRunnerPipelineStep]) -> None:
        """Checks for and logs warnings if duplicate annotation models are found in the pipeline config."""
        seen_model_identifiers: set[tuple[str, str]] = set()
        if not pipeline_steps:
            return

        for i, step in enumerate(pipeline_steps):
            model_identifier = (
                step.annotation_model.module,
                step.annotation_model.name,
            )
            model_path_str = f"{step.annotation_model.module}.{step.annotation_model.name}"

            if model_identifier in seen_model_identifiers:
                logger.warning(
                    f"Configuration Warning: Duplicate model '{model_path_str}' found in pipeline configuration at "
                    f"step index {i} (0-indexed, relative to loaded config). This model identifier was already defined "
                    f"earlier in the pipeline. While allowed, ensure this is intentional, as it may lead to "
                    f"redundant processing or overwriting of results during the merge phase if model IDs are identical."
                )
            else:
                seen_model_identifiers.add(model_identifier)

    def _is_matching_model_step(
        self, step_config: ModelRunnerPipelineStep, target_module: str, target_name: str
    ) -> bool:
        """Checks if a pipeline step matches a target model module and name."""
        return step_config.annotation_model.module == target_module and step_config.annotation_model.name == target_name

    def _load_model_and_validator_classes(
        self, config_step: ModelRunnerPipelineStep
    ) -> tuple[Type[AnnotationModel], BaseModel | JsonSchemaValidator | None]:
        try:
            annotator_callable = import_callable(config_step.annotation_model)
            if not (inspect.isclass(annotator_callable) and issubclass(annotator_callable, AnnotationModel)):
                raise TypeError(
                    f"Imported annotator '{config_step.annotation_model.name}' is not a valid AnnotationModel."
                )
            annotator_class = cast(Type[AnnotationModel], annotator_callable)
            logger.debug("Imported annotation model: %s", config_step.annotation_model.name)
        except (ImportError, AttributeError, TypeError) as err:
            raise ModelImportError(
                f"Failed to import model from config: {config_step.annotation_model.module}.{config_step.annotation_model.name}",
                original_exception=err,
            ) from err

        validator: BaseModel | JsonSchemaValidator | None = None
        if config_step.validation_model is not None:
            if isinstance(config_step.validation_model, dict):
                try:
                    from dorsal.common.validators.json_schema import (
                        get_json_schema_validator,
                    )

                    validator = get_json_schema_validator(schema=config_step.validation_model)
                    logger.debug("Created JsonSchemaValidator instance from dictionary schema.")
                except Exception as err:
                    raise ModelImportError(
                        "Failed to create JsonSchemaValidator from the provided schema dictionary.",
                        original_exception=err,
                    ) from err
            else:
                try:
                    validator_callable = import_callable(config_step.validation_model)
                    is_pydantic_class = inspect.isclass(validator_callable) and issubclass(
                        validator_callable, BaseModel
                    )
                    if not (is_pydantic_class or isinstance(validator_callable, JsonSchemaValidator)):
                        raise TypeError(
                            f"Imported validator '{config_step.validation_model.name}' is not a Pydantic model or JsonSchemaValidator instance."
                        )
                    validator = validator_callable
                    logger.debug(
                        "Imported validation model: %s",
                        config_step.validation_model.name,
                    )
                except (ImportError, AttributeError, TypeError) as err:
                    raise ModelImportError(
                        f"Failed to import validator from config: {config_step.validation_model.module}.{config_step.validation_model.name}",
                        original_exception=err,
                    ) from err

        return annotator_class, validator

    def _pydantic_validate_raw_annotation_model_output(
        self,
        raw_model_output: dict[str, Any],
        pydantic_class: Type[BaseModel],
        annotator_model_name: str,
        file_path: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
        """Validate raw output using a Pydantic BaseModel class.

        Args:
            raw_model_output: Raw dictionary output from the annotation model.
            pydantic_class: Pydantic class to validate against.
            annotator_model_name: Name of the annotation model.
            file_path: Path of the file being processed.

        Returns:
            tuple[dict[str, Any] | None, list[dict[str, Any]] | None]: A tuple containing:
                - Validated data as dict (after model_dump) if successful, else None.
                - List of Pydantic error dicts if validation fails, else None.
        """
        logger.debug(
            "Validating output of annotator '%s' for file '%s' using Pydantic model '%s'.",
            annotator_model_name,
            file_path,
            pydantic_class.__name__,
        )
        try:
            validated_model_instance = pydantic_class.model_validate(raw_model_output)
            logger.debug(
                "Pydantic validation successful for annotator '%s', file '%s'.",
                annotator_model_name,
                file_path,
            )
            return (
                validated_model_instance.model_dump(mode="json", exclude_none=self.exclude_none),
                None,
            )
        except PydanticValidationError as err:
            logger.warning(
                "Pydantic validation failed for annotator '%s' output on file '%s' with validator '%s'. Errors: %s. Raw output snippet: %s",
                annotator_model_name,
                file_path,
                pydantic_class.__name__,
                err.errors(),
                str(raw_model_output)[:200],
            )
            return None, cast(list[dict[str, Any]], err.errors())

    def _json_schema_validate_raw_annotation_model_output(
        self,
        raw_model_output: dict[str, Any],
        schema_validator_instance: JsonSchemaValidatorType,
        annotator_model_name: str,
        file_path: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
        """Validate raw output using a JsonSchemaValidator instance.

        Args:
            raw_model_output: Raw dictionary output from the annotation model.
            schema_validator_instance: Pre-configured JsonSchemaValidator instance.
            annotator_model_name: Name of the annotation model.
            file_path: Path of the file being processed.

        Returns:
            tuple[dict[str, Any] | None, list[dict[str, Any]] | None]: A tuple containing:
                - Raw model output if validation successful, else None.
                - List of JSON Schema error detail dicts if validation fails, else None.
        """
        validator_type_name = type(schema_validator_instance).__name__
        logger.debug(
            "Validating output of annotator '%s' for file '%s' using JsonSchemaValidator instance of type '%s'.",
            annotator_model_name,
            file_path,
            validator_type_name,
        )
        summary = json_schema_validate_records(records=[raw_model_output], validator=schema_validator_instance)

        if summary.get("valid_records") == 1:
            logger.debug(
                "JSON Schema validation successful for annotator '%s', file '%s'.",
                annotator_model_name,
                file_path,
            )
            return raw_model_output, None
        else:
            error_details: list[dict[str, Any]] = summary.get("error_details", [])
            if error_details:
                for err_detail in error_details:
                    logger.warning(
                        "JSON Schema validation failed for annotator '%s' on file '%s'. Record Index: %s, Path: %s, Validator: '%s', Message: %s. Raw output snippet: %s",
                        annotator_model_name,
                        file_path,
                        err_detail.get("record_index"),
                        err_detail.get("path"),
                        err_detail.get("validator"),
                        err_detail.get("error_message"),
                        str(raw_model_output)[:200],
                    )
            else:
                logger.warning(
                    "JSON Schema validation failed for annotator '%s' on file '%s' (no specific error details in summary). Summary: %s. Raw output snippet: %s",
                    annotator_model_name,
                    file_path,
                    summary,
                    str(raw_model_output)[:200],
                )
            return None, error_details

    @model_debug_timer
    def run_single_model(
        self,
        annotation_model: Type[AnnotationModel],
        validation_model: Type[BaseModel] | JsonSchemaValidator | None,
        file_path: str,
        base_model_result: "RunModelResult" | None = None,
        schema_id: str | None = None,
        options: dict[str, Any] | None = None,
        ignore_linter_errors: bool = False,
    ) -> "RunModelResult":
        """
        Runs a single annotation model and validates its output.

        This is the core execution unit for all models in the pipeline,
        including the base model.

        - **Populates Model:** Injects base file info (size, media type, etc.)
          into the model instance before running.
        - **Runs Model:** Calls the model's `.main()` method.
        - **Validates Output:** (Optional) Validates the output
          against the provided Pydantic or JSON Schema validator.

        Args:
            annotation_model: The AnnotationModel class to execute.
            validation_model: The Pydantic model or JsonSchemaValidator to
                              validate the output against.
            file_path: The absolute path to the file being processed.
            base_model_result: The result from the initial FileCoreAnnotationModel.
                               This is `None` only when running the base model itself.
            schema_id: The target schema ID for this annotation.
            options: A dictionary of options to pass to the model's `.main()` method.

        Returns:
            A RunModelResult object containing the model's output or an error.
        """
        from dorsal.file.configs.model_runner import RunModelResult

        model_name = annotation_model.__name__
        result_data: dict[str, Any] = {
            "name": model_name,
            "source": {
                "type": "Model",
                "id": annotation_model.id,
                "variant": None,
                "version": annotation_model.version,
            },
            "record": None,
            "schema_id": schema_id,
            "schema_version": None,
            "error": None,
        }
        raw_model_output: dict[str, Any] | None = None
        validated_data: dict[str, Any] | None = None
        validation_error_payload: list[dict[str, Any]] | str | None = None

        try:
            logger.debug("Instantiating model '%s' for file '%s'", model_name, file_path)
            annotation_model_instance = annotation_model(file_path=file_path)  # type: ignore[call-arg]

            if base_model_result and base_model_result.record:
                for key, value in base_model_result.record.items():
                    if key == "all_hashes":
                        continue
                    setattr(annotation_model_instance, key, value)

            logger.debug(
                "Running model '%s' main method with options: %s",
                model_name,
                options or "None",
            )

            raw_model_output = (
                annotation_model_instance.main(**options) if options else annotation_model_instance.main()
            )

            result_data["source"]["variant"] = annotation_model_instance.variant

            if raw_model_output is None:
                error_msg_from_instance = getattr(annotation_model_instance, "error", None)
                error_msg = (
                    error_msg_from_instance
                    if error_msg_from_instance
                    else f"Model '{model_name}' returned None without specific error."
                )
                logger.warning(
                    "Model '%s' returned None for file '%s'. Detail: %s",
                    model_name,
                    file_path,
                    error_msg,
                )
                result_data["error"] = error_msg
                return RunModelResult(**result_data)

            validator_display_name = "None"
            if validation_model is not None:
                if inspect.isclass(validation_model):
                    validator_display_name = validation_model.__name__
                else:
                    validator_display_name = type(validation_model).__name__

            logger.debug(
                "Attempting to validate output of model '%s' with validator '%s'...",
                model_name,
                validator_display_name,
            )

            if validation_model is None:
                logger.debug(
                    "No validator provided for model '%s', file '%s'. Skipping output validation.",
                    model_name,
                    file_path,
                )
                validated_data = raw_model_output
            elif isinstance(validation_model, JsonSchemaValidator):
                result_data["schema_version"] = validation_model.schema.get("version")
                validated_data, validation_error_payload = self._json_schema_validate_raw_annotation_model_output(
                    raw_model_output=raw_model_output,
                    schema_validator_instance=validation_model,
                    annotator_model_name=model_name,
                    file_path=file_path,
                )
            elif inspect.isclass(validation_model) and issubclass(validation_model, BaseModel):
                validated_data, validation_error_payload = self._pydantic_validate_raw_annotation_model_output(
                    raw_model_output=raw_model_output,
                    pydantic_class=validation_model,
                    annotator_model_name=model_name,
                    file_path=file_path,
                )
            else:
                config_err_msg = (
                    f"Unsupported validator type '{type(validation_model).__name__}' provided for model '{model_name}'."
                )
                logger.error(config_err_msg + " This indicates a misconfiguration in the pipeline step.")
                raise ModelRunnerConfigError(config_err_msg)

            if validation_error_payload is not None:
                val_error = ModelOutputValidationError(
                    model_name=model_name,
                    validator_name=validator_display_name,
                    errors=cast(list[Any], validation_error_payload),
                    original_exception=None,
                )

                first_error_msg = ""
                if isinstance(validation_error_payload, list) and validation_error_payload:
                    first_error = validation_error_payload[0]
                    if isinstance(first_error, dict):
                        if "error_message" in first_error:
                            first_error_msg = first_error["error_message"]
                        elif "msg" in first_error:
                            first_error_msg = first_error["msg"]

                base_error_str = str(val_error)
                if first_error_msg:
                    result_data["error"] = f"{base_error_str}: {first_error_msg}"
                else:
                    result_data["error"] = base_error_str
            elif validated_data is None and validation_model is not None:
                internal_err_msg = (
                    f"Validation failed for model '{model_name}' with validator '{validator_display_name}', "
                    "but no specific error details were captured by helpers."
                )
                logger.error(internal_err_msg + " This may indicate an issue in the validation helper logic.")
                result_data["error"] = str(
                    ModelExecutionError(
                        model_name=model_name,
                        file_path=file_path,
                        original_exception=Exception(internal_err_msg),
                    )
                )
            else:
                if validated_data is not None:
                    try:
                        raise_on_linter_error = not ignore_linter_errors

                        apply_linter(schema_id=schema_id, record=validated_data, raise_on_error=raise_on_linter_error)

                    except DataQualityError as e:
                        logger.warning(
                            "Model '%s' output for file '%s' passed schema validation "
                            "but FAILED data quality linting. Error: %s",
                            model_name,
                            file_path,
                            e,
                        )
                        result_data["error"] = str(e)
                        return RunModelResult(**result_data)

                result_data["record"] = validated_data
                logger.debug(
                    "Model '%s' successfully executed for file '%s'. Output %s.",
                    model_name,
                    file_path,
                    ("validated" if validation_model is not None else "accepted (no validation)"),
                )

        except ModelRunnerConfigError as err:
            logger.debug("Propagating ModelRunnerConfigError from run_single_model: %s", err)
            raise
        except PydanticValidationError as err:
            error_payload = err.errors()
            logger.exception(
                "PydanticValidationError encountered, likely during RunModelResult creation for model '%s'.",
                model_name,
            )
            val_name_for_err = "RunModelResultInternal"
            if "validator_display_name" in locals() and validation_model:
                val_name_for_err = validator_display_name
            elif validation_model:
                val_name_for_err = type(validation_model).__name__

            val_error = ModelOutputValidationError(
                model_name=model_name,
                validator_name=val_name_for_err,
                errors=error_payload,
                original_exception=err,
            )
            result_data["error"] = str(val_error)

        except Exception as err:
            logger.exception(
                "Unexpected error during execution or instantiation of model '%s' for file '%s'.",
                model_name,
                file_path,
            )
            exec_error = ModelExecutionError(model_name=model_name, file_path=file_path, original_exception=err)
            result_data["error"] = str(exec_error)

        return RunModelResult(**result_data)

    def _check_single_dependency(
        self,
        dependency_config: DependencyConfig,
        prior_model_results: "list[RunModelResult]",
        current_model_name: str,
    ) -> bool:
        def _format_callable_path_str(cp: CallableImportPath) -> str:
            return f"{cp.module}.{cp.name}"

        checker_path_obj = dependency_config.checker
        checker_path_as_str = _format_callable_path_str(checker_path_obj)

        try:
            checker_callable = import_callable(checker_path_obj)
        except (ImportError, AttributeError) as err:
            logger.error(
                "Failed to import dependency checker: %s for model '%s'",
                checker_path_as_str,
                current_model_name,
                exc_info=True,
            )
            raise DependencyCheckError(checker_path_as_str, err) from err

        logger.debug(
            "Checking dependency type '%s' for model '%s' using checker '%s'",
            dependency_config.type,
            current_model_name,
            checker_path_as_str,
        )
        try:
            is_met = checker_callable(prior_model_results, dependency_config)
        except Exception as err:
            logger.error(
                "Dependency checker '%s' raised an exception for model '%s'",
                checker_path_as_str,
                current_model_name,
                exc_info=True,
            )
            raise DependencyCheckError(checker_path_as_str, err) from err

        if is_met:
            logger.debug(
                "Dependency type '%s' met for model '%s'.",
                dependency_config.type,
                current_model_name,
            )
            return True
        else:
            dep_error = DependencyNotMetError(current_model_name, dependency_config.type, dependency_config.silent)
            if not dependency_config.silent:
                logger.warning(
                    "Dependency NOT MET: %s. Raising error to halt pipeline for this file.",
                    dep_error,
                )
                raise dep_error
            else:
                logger.debug("Dependency NOT MET: %s. Model will be skipped.", dep_error)
                return False

    def run(self, file_path: str) -> "FileRecordStrict":
        from dorsal.file.configs.model_runner import RunModelResult

        logger.debug("Starting model execution pipeline for file: %s", file_path)
        all_model_results: "list[RunModelResult]" = []

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The specified file_path does not exist: {file_path}")
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"The specified file_path is not a file: {file_path}")

        logger.debug("Processing with base file model using effective options...")
        try:
            base_annotator, base_validator = self._load_model_and_validator_classes(self.pre_model)
        except ModelImportError as err:
            logger.critical(
                "Failed to import essential base model ('%s') or its validator. Cannot proceed.",
                err.callable_path_str,
                exc_info=True,
            )
            raise

        base_model_result: "RunModelResult" = self.run_single_model(
            annotation_model=base_annotator,
            validation_model=base_validator,
            file_path=file_path,
            schema_id=self.pre_model.schema_id,
            options=self.pre_model_options,
        )

        if base_model_result.error:
            logger.critical(
                "Base file model ('%s') processing failed for file '%s'. Error: %s. Pipeline cannot continue for this file.",
                base_annotator.__name__,
                file_path,
                base_model_result.error,
            )
            raise BaseModelProcessingError(f"Base model '{base_annotator.__name__}' failed: {base_model_result.error}")
        all_model_results.append(base_model_result)
        logger.debug("Base file model processed successfully.")

        if not self.pipeline:
            logger.debug("No models in the pipeline to run.")
        else:
            logger.debug("Processing with %d model(s) from pipeline...", len(self.pipeline))

        for step_config in self.pipeline:
            if step_config.deactivated:
                logger.debug(
                    "Skipping deactivated model: %s.%s",
                    step_config.annotation_model.module,
                    step_config.annotation_model.name,
                )
                continue
            annotator_path = f"{step_config.annotation_model.module}.{step_config.annotation_model.name}"
            logger.debug("Preparing to run pipeline step for model: %s", annotator_path)

            annotator_class: Type[AnnotationModel] | None = None
            annotator_model_id = "unknown/import-failed"
            annotator_model_variant = None
            annotator_model_version = None

            try:
                annotator_class, validator_class = self._load_model_and_validator_classes(step_config)
                annotator_model_version = annotator_class.version
                annotator_model_variant = annotator_class.variant
                annotator_model_id = annotator_class.id

                proceed_with_model = True
                if step_config.dependencies:
                    logger.debug(
                        "Checking %d dependenc(ies) for model '%s'",
                        len(step_config.dependencies),
                        annotator_class.__name__,
                    )
                    for dep_conf in step_config.dependencies:
                        if not self._check_single_dependency(dep_conf, all_model_results, annotator_class.__name__):
                            error_msg = f"Skipped due to unmet silent dependency (type: {dep_conf.type})"
                            error_result = RunModelResult(
                                name=annotator_class.__name__,
                                source={
                                    "type": "Model",
                                    "id": annotator_model_id,
                                    "variant": annotator_model_variant,
                                    "version": annotator_model_version,
                                },
                                schema_id=step_config.schema_id,
                                record=None,
                                error=error_msg,
                            )
                            all_model_results.append(error_result)
                            proceed_with_model = False
                            break

                if proceed_with_model:
                    logger.debug(
                        "Executing model: %s for file %s",
                        annotator_class.__name__,
                        file_path,
                    )
                    model_run_result = self.run_single_model(
                        annotation_model=annotator_class,
                        validation_model=validator_class,
                        file_path=file_path,
                        base_model_result=base_model_result,
                        schema_id=step_config.schema_id,
                        options=step_config.options,
                        ignore_linter_errors=step_config.ignore_linter_errors,
                    )
                    all_model_results.append(model_run_result)
                    if model_run_result.error:
                        logger.warning(
                            "Model '%s' completed with error: %s",
                            annotator_class.__name__,
                            model_run_result.error,
                        )
                    else:
                        logger.debug(
                            "Model '%s' completed successfully.",
                            annotator_class.__name__,
                        )

            except ModelImportError as err:
                logger.error(
                    "Failed to import model/validator for step '%s', skipping. Error: %s",
                    annotator_path,
                    err,
                    exc_info=True,
                )
                error_result = RunModelResult(
                    name=step_config.annotation_model.name,
                    source={
                        "type": "Model",
                        "id": annotator_model_id,
                        "variant": annotator_model_variant,
                        "version": annotator_model_version,
                    },
                    schema_id=step_config.schema_id,
                    record=None,
                    error=f"Import failed: {err.callable_path_str}: {err.original_exception}",
                )
                all_model_results.append(error_result)
                continue
            except DependencyNotMetError as err:
                logger.critical(
                    "HALTING PIPELINE for file '%s': Non-silent dependency not met for model '%s'. Error: %s",
                    file_path,
                    err.model_name,
                    err,
                )
                source_model_id = annotator_class.id if annotator_class else annotator_model_id
                source_model_version = annotator_class.version if annotator_class else annotator_model_version
                error_result = RunModelResult(
                    name=err.model_name,
                    source={
                        "type": "Model",
                        "id": source_model_id,
                        "variant": annotator_model_variant,
                        "version": source_model_version,
                    },
                    schema_id=step_config.schema_id,
                    record=None,
                    error=str(err),
                )
                all_model_results.append(error_result)
                raise
            except DependencyCheckError as err:
                logger.error(
                    "Skipping model '%s' due to failure in its dependency checker: %s",
                    annotator_class.__name__ if annotator_class else annotator_path,
                    err,
                    exc_info=True,
                )
                error_result = RunModelResult(
                    name=(annotator_class.__name__ if annotator_class else step_config.annotation_model.name),
                    source={
                        "type": "Model",
                        "id": annotator_model_id,
                        "variant": annotator_model_variant,
                        "version": annotator_model_version,
                    },
                    schema_id=step_config.schema_id,
                    record=None,
                    error=f"Dependency checker failed: {err.checker_path_str}: {err.original_exception}",
                )
                all_model_results.append(error_result)
                continue

        logger.debug(
            "Merging results from %d model execution(s) for file '%s'...",
            len(all_model_results),
            file_path,
        )
        final_file_record = self._merge_model_results(all_model_results, file_path)

        logger.debug(
            "Model execution pipeline completed successfully for file: '%s'. Final hash: %s",
            file_path,
            final_file_record.hash,
        )
        if self.debug:
            logger.debug("Model execution times for file '%s': %s", file_path, self.time_taken)
        return final_file_record

    def _merge_model_results(self, model_results: "list[RunModelResult]", file_path_for_log: str) -> "FileRecordStrict":
        from dorsal.file.validators.file_record import FileRecordStrict, CORE_MODEL_ANNOTATION_WRAPPERS
        from dorsal.file.validators.base import FileCoreValidationModelStrict

        if not model_results:
            logger.error(
                "Cannot merge: list of model results is empty for file '%s'.",
                file_path_for_log,
            )
            raise PipelineIntegrityError("No model results found to merge.")

        merged_data: dict[str, Any] = {"annotations": {}, "source": "disk"}
        base_model_output = model_results[0]

        if base_model_output.error or base_model_output.record is None:
            logger.error(
                "Base model result has an error or no record for file '%s' at merge stage. Error: %s",
                file_path_for_log,
                base_model_output.error,
            )
            raise PipelineIntegrityError(
                f"Base model result invalid (error: {base_model_output.error}) for '{file_path_for_log}' at merge."
            )

        try:
            base_file_data = FileCoreValidationModelStrict.model_validate(base_model_output.record)
        except PydanticValidationError as err:
            logger.error(
                "Failed to validate base model's record during merge for file '%s'. Errors: %s. Record: %s",
                file_path_for_log,
                err.errors(),
                base_model_output.record,
                exc_info=True,
            )
            raise PipelineIntegrityError(
                f"Base model record failed validation at merge for '{file_path_for_log}' - {err}",
                original_exception=err,
            ) from err

        merged_data["hash"] = base_file_data.hash

        if base_file_data.all_hash_ids and "BLAKE3" in base_file_data.all_hash_ids:
            merged_data["validation_hash"] = base_file_data.all_hash_ids["BLAKE3"]
        else:
            logger.error(
                "CRITICAL: BLAKE3 hash (required for validation_hash) not found in base model results for file '%s'. Available hashes: %s",
                file_path_for_log,
                base_file_data.all_hash_ids,
            )
            raise MissingHashError(
                f"BLAKE3 hash, required for 'validation_hash', was not produced by the base model for file '{file_path_for_log}'."
            )

        merged_data["quick_hash"] = base_file_data.all_hash_ids.get("QUICK")
        merged_data["similarity_hash"] = base_file_data.similarity_hash

        base_dataset_id = constants.FILE_BASE_ANNOTATION_SCHEMA
        merged_data["annotations"][base_dataset_id] = base_model_output.model_dump(
            mode="json", exclude_none=self.exclude_none
        )

        successful_merges = 0
        skipped_due_to_error = 0

        for result in model_results[1:]:
            schema_id = result.schema_id
            if schema_id is None:
                logger.error(
                    "Skipping result from model '%s' for file '%s': No target dataset id",
                    result.name,
                    file_path_for_log,
                )
                if not result.error:
                    result.error = "No target dataset id"
                skipped_due_to_error += 1
                continue
            if result.error or result.record is None:
                logger.debug(
                    "Skipping result from model '%s' for file '%s' (error or no record). Error: %s",
                    result.name,
                    file_path_for_log,
                    result.error,
                )
                skipped_due_to_error += 1
                continue

            result_dump = result.model_dump(mode="json", exclude_none=self.exclude_none)
            is_core_schema = schema_id in CORE_MODEL_ANNOTATION_WRAPPERS

            if is_core_schema:
                if schema_id in merged_data["annotations"]:
                    logger.warning(
                        "Duplicate CORE dataset ID '%s' in merge for file '%s'. Overwriting.",
                        schema_id,
                        file_path_for_log,
                    )
                merged_data["annotations"][schema_id] = result_dump
            else:
                if schema_id not in merged_data["annotations"]:
                    merged_data["annotations"][schema_id] = [result_dump]
                else:
                    current_val = merged_data["annotations"][schema_id]
                    if isinstance(current_val, list):
                        current_val.append(result_dump)
                    else:
                        merged_data["annotations"][schema_id] = [current_val, result_dump]

            successful_merges += 1

        logger.debug(
            "Merge complete for file '%s'. Base model processed. Annotations from pipeline successfully merged: %d. Annotations from pipeline skipped due to errors/dependencies: %d.",
            file_path_for_log,
            successful_merges,
            skipped_due_to_error,
        )

        try:
            file_record = FileRecordStrict(**merged_data)
        except PydanticValidationError as err:
            logger.exception(
                "Final merged data failed FileRecordStrict validation for file '%s'. Errors: %s. Data snippet: %s",
                file_path_for_log,
                err.errors(),
                str(merged_data)[:1000],
            )
            raise PipelineIntegrityError(
                f"Final merged record for file '{file_path_for_log}' is invalid.",
                original_exception=err,
            ) from err

        return file_record
