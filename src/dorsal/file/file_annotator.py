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

import copy
import inspect
import logging
import secrets
from typing import Any, Callable, Type, cast
from uuid import uuid4

from pydantic import BaseModel

from dorsal.common.exceptions import (
    AnnotationConfigurationError,
    AnnotationExecutionError,
    AnnotationImportError,
    AnnotationValidationError,
    ModelExecutionError,
    ModelImportError,
    ModelRunnerError,
    PydanticValidationError,
    ValidationError,
)
from dorsal.common.model import (
    AnnotationModel,
    AnnotationManualSource,
    is_pydantic_model_class,
    is_pydantic_model_instance,
)
from dorsal.common.validators import (
    JsonSchemaValidator,
    JsonSchemaValidatorType,
    get_json_schema_validator,
    import_callable,
    is_valid_dataset_id_or_schema_id,
    json_schema_validate_records,
)
from dorsal.file.model_runner import ModelRunner
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep, RunModelResult
from dorsal.file.linters import apply_linter
from dorsal.file.sharding import process_record_for_sharding
from dorsal.file.validators.file_record import (
    Annotation,
    AnnotationGroup,
    Annotation_Base,
    Annotation_MediaInfo,
    Annotation_PDF,
    AnnotationData,
    AnnotationSource,
    AnnotationGroupInfo,
    CORE_MODEL_ANNOTATION_WRAPPERS,
    GenericFileAnnotation,
)


logger = logging.getLogger(__name__)


class FileAnnotator:
    """Orchestrates on-demand annotation of local files.

    Acts as a bridge between high-level callers (like LocalFile) and the
    ModelRunner, handling single annotation tasks, validating manual data,
    and wrapping results into a standardized format.

    """

    def _execute(
        self,
        model_runner: ModelRunner,
        annotation_model: Type[AnnotationModel],
        validation_model: Type[BaseModel] | JsonSchemaValidator | None,  # type: ignore
        file_path: str,
        schema_id: str,
        options: dict | None,
        ignore_linter_errors: bool = False,
    ) -> RunModelResult:
        """
        Executes a single model via the ModelRunner.

        Args:
            model_runner: The ModelRunner instance.
            annotation_model: The annotation model class to run.
            validation_model: The validator for the model's output.
            file_path: Path to the target file.
            schema_id: The target dataset ID for the annotation.
            options: Options for the model's main() method.

        Returns:
            The result of the model execution.

        Raises:
            AnnotationExecutionError: If the model run fails.
        """
        model_id_for_log = getattr(annotation_model, "id", "[unknown_id]")
        logger.debug(
            "Executing annotation model '%s' for schema_id '%s' on file '%s'.",
            model_id_for_log,
            schema_id,
            file_path,
        )
        try:
            run_model_result: RunModelResult = model_runner.run_single_model(
                annotation_model=annotation_model,
                validation_model=validation_model,
                file_path=file_path,
                schema_id=schema_id,
                options=options,
                ignore_linter_errors=ignore_linter_errors,
            )
            if run_model_result.error:
                raise AnnotationExecutionError(
                    f"Model '{annotation_model.id}' returned an error: {run_model_result.error}"
                )

            if run_model_result.record is None:
                raise AnnotationExecutionError(f"Model '{annotation_model.id}' returned no record and no error.")

            return run_model_result
        except ModelRunnerError as err:
            logger.exception("ModelRunner execution failed for model '%s'.", annotation_model.id)
            raise AnnotationExecutionError(f"Execution failed for model '{annotation_model.id}'.") from err

    def _create_wrapped_annotation(
        self,
        *,
        record_data: dict[str, Any],
        wrapper_class: Type[Annotation],
        schema_id: str,
        source: dict,
        private: bool,
        schema_version: str | None = None,
        group_info: AnnotationGroupInfo | None = None,
    ) -> Annotation:
        """
        Helper method to instantiate a single Annotation object (or subclass).

        This encapsulates the conversion of raw dict data into a GenericFileAnnotation
        and then into the specific wrapper class (e.g. Annotation_PDF).
        """
        try:
            annotation_record = GenericFileAnnotation(**record_data)
        except PydanticValidationError as err:
            group_info_str = f" (Chunk {group_info.index}/{group_info.total})" if group_info else ""
            logger.exception(
                "Failed to wrap validated model output into GenericFileAnnotation for dataset '%s'%s.",
                schema_id,
                group_info_str,
            )
            raise AnnotationExecutionError(
                f"Output for dataset '{schema_id}'{group_info_str} is incompatible with the base annotation structure."
            ) from err

        try:
            return wrapper_class(
                record=annotation_record,
                private=private,
                source=source,
                schema_version=schema_version,
                group=group_info,
            )
        except PydanticValidationError as err:
            logger.exception("Failed to instantiate wrapper class '%s'.", wrapper_class.__name__)
            raise AnnotationExecutionError(
                f"Failed to create annotation wrapper for '{schema_id}': {str(err)}"
            ) from err

    def _make_annotation(
        self,
        *,
        validated_annotation: dict,
        schema_id: str,
        schema_version: str | None = None,
        source: dict,
        private: bool,
        force: bool = False,
    ) -> Annotation | AnnotationGroup:
        """
        Constructs a final, typed Annotation object (or AnnotationGroup) from a validated record.

        This method acts as the 'Sharding Controller'. It determines if the payload needs
        splitting based on the schema and size constraints defined in `dorsal.file.sharding`.

        Args:
            validated_annotation: The actual annotation data.
            schema_id: The validation schema ID.
            source: The dictionary describing the annotation's source.
            private: Visibility status.
            force: If True, bypasses schema ID validation (but not size/sharding checks).

        Returns:
            Annotation: If the record fits in one chunk.
            AnnotationGroup: If the record was sharded.

        Raises:
            AnnotationConfigurationError: If the schema_id ID is invalid.
            AnnotationExecutionError: If data parsing or sharding fails.
        """
        if not force:
            if not is_valid_dataset_id_or_schema_id(schema_id):
                raise AnnotationConfigurationError(f"Target dataset '{schema_id}' is not a valid dataset ID.")

        try:
            chunks = process_record_for_sharding(schema_id, validated_annotation)
        except ValueError as e:
            raise AnnotationExecutionError(f"Annotation processing failed for '{schema_id}': {e}") from e

        annotation_wrapper_class: Type[Annotation] = CORE_MODEL_ANNOTATION_WRAPPERS.get(schema_id, Annotation)

        if len(chunks) == 1:
            logger.debug(
                "Creating atomic annotation wrapper '%s' for dataset '%s'.",
                annotation_wrapper_class.__name__,
                schema_id,
            )
            return self._create_wrapped_annotation(
                record_data=chunks[0],
                wrapper_class=annotation_wrapper_class,
                schema_id=schema_id,
                source=source,
                private=private,
                schema_version=schema_version,
                group_info=None,
            )

        group_uid = uuid4()
        total_chunks = len(chunks)
        group_items: list[Annotation] = []

        logger.info(
            "Payload for '%s' exceeds 1MiB. Splitting into %d chunks (Group ID: %s).",
            schema_id,
            total_chunks,
            group_uid,
        )

        for index, chunk_data in enumerate(chunks):
            chunk_meta = AnnotationGroupInfo(id=group_uid, index=index, total=total_chunks)

            annotation = self._create_wrapped_annotation(
                record_data=chunk_data,
                wrapper_class=annotation_wrapper_class,
                schema_id=schema_id,
                source=source,
                private=private,
                schema_version=schema_version,
                group_info=chunk_meta,
            )
            group_items.append(annotation)

        return AnnotationGroup(annotations=group_items)

    def annotate_file_using_pipeline_step(
        self,
        *,
        file_path: str,
        model_runner: ModelRunner,
        pipeline_step: ModelRunnerPipelineStep | dict[str, Any],
        schema_id: str | None = None,
        schema_version: str | None = None,
        private: bool,
    ) -> Annotation | AnnotationGroup:
        """
        Runs an annotation model defined by a single pipeline step.

        Note: This ignores any dependency rules within the pipeline step.

        Args:
            file_path: Absolute or relative path to the local file.
            model_runner: An instance of the ModelRunner.
            pipeline_step: A `ModelRunnerPipelineStep` object or a dict defining the step.
            schema_id: Optional. Overrides the `schema_id` from the pipeline_step.

        Returns:
            An `Annotation` object containing the model's output.

        Raises:
            AnnotationConfigurationError: If the pipeline_step config is invalid.
            AnnotationImportError: If the specified model or validator cannot be imported.
            AnnotationExecutionError: If the model fails to run or its output is invalid.
        """
        logger.debug("Annotating file '%s' using pipeline step.", file_path)
        if isinstance(pipeline_step, dict):
            try:
                pipeline_step_obj = ModelRunnerPipelineStep(**pipeline_step)
            except PydanticValidationError as err:
                raise AnnotationConfigurationError(f"Invalid `pipeline_step` dictionary provided: {err}") from err
        elif isinstance(pipeline_step, ModelRunnerPipelineStep):
            pipeline_step_obj = pipeline_step
        else:
            raise AnnotationConfigurationError(
                f"pipeline_step must be a dict or ModelRunnerPipelineStep, not {type(pipeline_step).__name__}."
            )

        effective_schema_id = schema_id if schema_id is not None else pipeline_step_obj.schema_id

        try:
            annotator_callable = import_callable(import_path=pipeline_step_obj.annotation_model)
            if not (inspect.isclass(annotator_callable) and issubclass(annotator_callable, AnnotationModel)):
                raise TypeError(
                    f"Imported callable '{annotator_callable.__name__}' is not a subclass of AnnotationModel."
                )
            annotator_class = cast(Type[AnnotationModel], annotator_callable)

            validator: Callable | JsonSchemaValidatorType | None = None
            if pipeline_step_obj.validation_model:
                if isinstance(pipeline_step_obj.validation_model, dict):
                    validator = get_json_schema_validator(schema=pipeline_step_obj.validation_model, strict=True)
                else:
                    validator_callable = import_callable(import_path=pipeline_step_obj.validation_model)
                    if not (
                        is_pydantic_model_class(validator_callable)
                        or isinstance(validator_callable, JsonSchemaValidator)
                    ):
                        raise TypeError(
                            f"Imported validator '{pipeline_step_obj.validation_model.name}' is not a supported type."
                        )
                    validator = validator_callable
        except (ImportError, AttributeError, TypeError) as err:
            msg = (
                "Failed to import model/validator from config: "
                f"{pipeline_step_obj.annotation_model.module}.{pipeline_step_obj.annotation_model.name}"
            )
            logger.exception("AnnotationImportError: %s.", msg)
            raise AnnotationImportError(msg) from err

        run_model_result = self._execute(
            model_runner=model_runner,
            annotation_model=annotator_class,
            validation_model=validator,
            file_path=file_path,
            schema_id=effective_schema_id,
            options=pipeline_step_obj.options,
            ignore_linter_errors=pipeline_step_obj.ignore_linter_errors,
        )

        final_version = schema_version
        if final_version is None and hasattr(run_model_result, "schema_version"):
            final_version = run_model_result.schema_version

        return self._make_annotation(
            validated_annotation=cast(dict, run_model_result.record),
            schema_id=effective_schema_id,
            schema_version=final_version,
            private=private,
            source=run_model_result.source.model_dump(),
        )

    def annotate_file_using_model_and_validator(
        self,
        *,
        file_path: str,
        model_runner: ModelRunner,
        annotation_model_cls: Type[AnnotationModel],
        schema_id: str,
        schema_version: str | None = None,
        private: bool,
        options: dict | None = None,
        validation_model: Type[BaseModel] | JsonSchemaValidator | None = None,
        ignore_linter_errors: bool = False,
    ) -> Annotation | AnnotationGroup:
        """
        Runs a given annotation model class directly.

        Args:
            file_path: Path to the local file.
            model_runner: An instance of the ModelRunner.
            annotation_model_cls: The annotation model class to execute.
            schema_id: The dataset ID for the resulting annotation.
            options: Optional keyword arguments for the model's main() method.
            validation_model: Optional validator for the model's output.

        Returns:
            An `Annotation` object with the model's output.

        Raises:
            AnnotationConfigurationError: If `schema_id` is not provided.
            AnnotationExecutionError: If the model fails to run.
        """
        logger.debug(
            "Annotating file '%s' with model '%s' for dataset '%s'.",
            file_path,
            annotation_model_cls.__name__,
            schema_id,
        )
        if schema_id is None:
            raise AnnotationConfigurationError("`schema_id` must be provided.")

        if not (
            hasattr(annotation_model_cls, "id") and isinstance(annotation_model_cls.id, str) and annotation_model_cls.id
        ):
            raise AnnotationConfigurationError(
                f"The provided AnnotationModel class '{annotation_model_cls.__name__}' "
                "is missing a required, non-empty 'id' string attribute."
            )

        run_model_result = self._execute(
            model_runner=model_runner,
            annotation_model=annotation_model_cls,
            validation_model=validation_model,
            file_path=file_path,
            schema_id=schema_id,
            options=options,
            ignore_linter_errors=ignore_linter_errors,
        )

        return self._make_annotation(
            validated_annotation=cast(dict, run_model_result.record),
            schema_id=schema_id,
            schema_version=schema_version,
            private=private,
            source=run_model_result.source.model_dump(),
        )

    def _jsonschema_validate(self, annotation: dict[str, Any], validator: JsonSchemaValidator) -> None:
        status = json_schema_validate_records(records=[annotation], validator=validator)
        if status.get("valid_records") != 1:
            raise ValidationError(f"Schema validation failed - Invalid record: {status['error_details']}")
        return None

    def validate_manual_annotation(
        self,
        annotation: BaseModel | dict[str, Any],
        validator: Type[BaseModel] | JsonSchemaValidator | None,
    ) -> dict[str, Any]:
        """
        Validates a user-provided annotation payload against an optional validator.

        Args:
            annotation: The annotation data payload (dict or Pydantic model).
            validator: The validator to use (Pydantic class or JsonSchemaValidator instance).
            file_hash: (Deprecated) The primary hash of the file being annotated.
                       No longer injected into the record.

        Returns:
            The validated annotation as a dictionary.

        Raises:
            AnnotationConfigurationError: If the annotation or validator type is unsupported.
            AnnotationValidationError: If the annotation fails validation.
        """
        validator_type_name = type(validator).__name__ if validator else "None"
        logger.debug(
            "Validating manual annotation. Input type: %s, Validator type: %s.",
            type(annotation).__name__,
            validator_type_name,
        )

        if validator is None:
            if isinstance(annotation, BaseModel):
                return annotation.model_dump(by_alias=True, exclude_none=True)
            elif isinstance(annotation, dict):
                return annotation.copy()
            else:
                raise AnnotationConfigurationError(
                    f"Unsupported annotation type for manual validation: {type(annotation).__name__}"
                )

        if not (is_pydantic_model_class(validator) or isinstance(validator, JsonSchemaValidator)):
            raise AnnotationConfigurationError(f"Unsupported validator type: {type(validator).__name__}")

        try:
            if isinstance(annotation, BaseModel):
                annotation_dict = annotation.model_dump(by_alias=True, exclude_none=True)
                if is_pydantic_model_class(validator) and validator.__name__ != annotation.__class__.__name__:
                    logger.debug("Re-validating Pydantic model against different validator model.")
                    validator.model_validate(annotation_dict)
                elif isinstance(validator, JsonSchemaValidator):
                    logger.debug("Validating Pydantic model against JSON schema.")
                    summary = json_schema_validate_records(records=[annotation_dict], validator=validator)
                    if summary.get("valid_records") != 1:
                        raise AnnotationValidationError(
                            f"Schema validation failed: {summary.get('error_details')}",
                            validation_errors=summary.get("error_details"),
                        )
                return annotation_dict

            elif isinstance(annotation, dict):
                annotation_dict = annotation.copy()

                if is_pydantic_model_class(validator):
                    logger.debug("Validating dict against Pydantic model.")
                    validator.model_validate(annotation_dict)
                elif isinstance(validator, JsonSchemaValidator):
                    logger.debug("Validating dict against JSON schema.")
                    summary = json_schema_validate_records(records=[annotation_dict], validator=validator)
                    if summary.get("valid_records") != 1:
                        raise AnnotationValidationError(
                            f"Schema validation failed: {summary.get('error_details')}",
                            validation_errors=summary.get("error_details"),
                        )
                return annotation_dict

            else:
                raise AnnotationConfigurationError(
                    f"Unsupported annotation type for manual validation: {type(annotation).__name__}"
                )

        except PydanticValidationError as err:
            logger.debug("Pydantic validation failed for manual annotation.")
            raise AnnotationValidationError(
                "Manual annotation failed Pydantic validation.",
                validation_errors=err.errors(),
            ) from err
        except ValidationError as err:
            logger.debug("Schema validation failed for manual annotation.")
            raise err

    def make_manual_annotation(
        self,
        *,
        annotation: BaseModel | dict[str, Any],
        schema_id: str,
        schema_version: str | None = None,
        source_id: str | None,
        validator: Type[BaseModel] | JsonSchemaValidator | None = None,
        private: bool,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> Annotation | AnnotationGroup:
        """
        Creates a fully-formed `Annotation` object from a manual payload.

        Args:
            annotation: The annotation data (dict or Pydantic model).
            schema_id: The validation schema for this annotation.
            detail: A string describing the source of the manual annotation.
            validator: An optional validator for the payload.

        Returns:
            A constructed and validated `Annotation` object.

        Raises:
            AnnotationConfigurationError: If config/types are invalid.
            AnnotationValidationError: If the payload fails validation.
            DataQualityError: If the payload fails post-validation data quality linting.
        """
        logger.debug("Creating manual annotation for validation schema '%s'.", schema_id)

        if force:
            logger.debug("`force=True: skipping all validation checks.")
            if is_pydantic_model_instance(annotation):
                validated_annotation = annotation.model_dump(by_alias=True, exclude_none=True)
            else:
                validated_annotation = cast(dict[str, Any], annotation)
        else:
            validated_annotation = self.validate_manual_annotation(annotation=annotation, validator=validator)

            raise_on_error = not ignore_linter_errors
            apply_linter(schema_id=schema_id, record=validated_annotation, raise_on_error=raise_on_error)

        if source_id is None:
            source_id = secrets.token_hex(12)

        source = AnnotationManualSource(id=source_id).model_dump()

        return self._make_annotation(
            validated_annotation=validated_annotation,
            schema_id=schema_id,
            schema_version=schema_version,
            private=private,
            source=source,
            force=force,
        )


FILE_ANNOTATOR = FileAnnotator()
