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

import copy
import inspect
import logging
import secrets
from typing import Any, Callable, Sequence, Type, cast
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
    get_json_schema_validator,
    import_callable,
    is_valid_dataset_id_or_schema_id,
    json_schema_validate_records,
)
from dorsal.file.model_runner import ModelRunner
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep, RunModelResult, resolve_pipeline_step_models
from dorsal.file.linters import apply_linter
from dorsal.file.sharding import build_annotation_or_annotationgroup, process_record_for_sharding
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
        progress_callback: Callable[[float, float, str], None] | None = None,
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
                progress_callback=progress_callback,
            )
            if run_model_result.error:
                raise AnnotationExecutionError(
                    f"Model '{annotation_model.id}' returned an error: {run_model_result.error}"
                )

            if run_model_result.records is None:
                raise AnnotationExecutionError(f"Model '{annotation_model.id}' returned no record and no error.")

            return run_model_result
        except ModelRunnerError as err:
            logger.exception("ModelRunner execution failed for model '%s'.", annotation_model.id)
            raise AnnotationExecutionError(f"Execution failed for model '{annotation_model.id}'.") from err

    def _make_annotation(
        self,
        *,
        validated_annotation: dict,
        schema_id: str,
        schema_version: str | None = None,
        source: dict,
        private: bool | None,
        force: bool = False,
    ) -> Annotation | AnnotationGroup:
        """
        Constructs a final, typed Annotation object (or AnnotationGroup) from a validated record.

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

        return build_annotation_or_annotationgroup(
            schema_id=schema_id,
            record_data=validated_annotation,
            source=source,
            schema_version=schema_version,
            private=private,
        )

    def annotate_file_using_pipeline_step(
        self,
        *,
        file_path: str,
        model_runner: ModelRunner,
        pipeline_step: ModelRunnerPipelineStep | dict[str, Any],
        schema_id: str | None = None,
        schema_version: str | None = None,
        private: bool | None,
        progress_callback: Callable[[float, float, str], None] | None = None,
    ) -> list[Annotation | AnnotationGroup]:
        """
        Runs an annotation model defined by a single pipeline step.

        Note: This ignores any dependency rules within the pipeline step.

        Args:
            file_path: Absolute or relative path to the local file.
            model_runner: An instance of the ModelRunner.
            pipeline_step: A `ModelRunnerPipelineStep` object or a dict defining the step.
            schema_id: Optional. Overrides the `schema_id` from the pipeline_step.

        Returns:
            A list of `Annotation` or `AnnotationGroup` objects containing the model's output.

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
        if effective_schema_id is None:
            raise AnnotationConfigurationError("schema_id could not be resolved.")

        logger.debug("Validation schema: %s", effective_schema_id)

        annotator_class, validator = resolve_pipeline_step_models(pipeline_step_obj)

        run_model_result = self._execute(
            model_runner=model_runner,
            annotation_model=annotator_class,
            validation_model=validator,
            file_path=file_path,
            schema_id=effective_schema_id,
            options=pipeline_step_obj.options,
            ignore_linter_errors=pipeline_step_obj.ignore_linter_errors,
            progress_callback=progress_callback,
        )

        final_version = schema_version
        if final_version is None and hasattr(run_model_result, "schema_version"):
            final_version = run_model_result.schema_version

        execution_id = str(uuid4())
        source_dict = run_model_result.source.model_dump(by_alias=True, exclude_none=True)
        source_dict["execution_id"] = execution_id

        results = []
        if run_model_result.records:
            for record_data in run_model_result.records:
                annotation_item = self._make_annotation(
                    validated_annotation=cast(dict, record_data),
                    schema_id=effective_schema_id,
                    schema_version=final_version,
                    private=private,
                    source=source_dict,
                )
                results.append(annotation_item)

        return results

    def annotate_file_using_model_and_validator(
        self,
        *,
        file_path: str,
        model_runner: ModelRunner,
        annotation_model_cls: Type[AnnotationModel],
        schema_id: str,
        schema_version: str | None = None,
        private: bool | None,
        options: dict | None = None,
        validation_model: Type[BaseModel] | JsonSchemaValidator | None = None,
        ignore_linter_errors: bool = False,
        progress_callback: Callable[[float, float, str], None] | None = None,
    ) -> list[Annotation | AnnotationGroup]:
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
            A list of `Annotation` or `AnnotationGroup` objects with the model's output.

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
            progress_callback=progress_callback,
        )

        execution_id = str(uuid4())
        source_dict = run_model_result.source.model_dump(by_alias=True, exclude_none=True)
        source_dict["execution_id"] = execution_id

        results = []
        if run_model_result.records:
            for record_data in run_model_result.records:
                annotation_item = self._make_annotation(
                    validated_annotation=cast(dict, record_data),
                    schema_id=schema_id,
                    schema_version=schema_version,
                    private=private,
                    source=source_dict,
                )
                results.append(annotation_item)

        return results

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
        annotation: BaseModel | dict[str, Any] | Sequence[BaseModel | dict[str, Any]],
        schema_id: str,
        schema_version: str | None = None,
        source_id: str | None,
        validator: Type[BaseModel] | JsonSchemaValidator | None = None,
        private: bool | None,
        ignore_linter_errors: bool = False,
        force: bool = False,
    ) -> list[Annotation | AnnotationGroup]:
        """
        Creates a fully-formed `Annotation` object from a manual payload.

        Args:
            annotation: The annotation data (dict or Pydantic model).
            schema_id: The validation schema for this annotation.
            schema_version: Specific version of the schema.
            source_id: A string identifying the source ID.
            validator: An optional validator for the payload.
            private: Visibility status of the annotation.
            ignore_linter_errors: If True, bypass data quality checks.
            force: If True, bypass all validation.

        Returns:
            A constructed and validated `Annotation` object.

        Raises:
            AnnotationConfigurationError: If config/types are invalid.
            AnnotationValidationError: If the payload fails validation.
            DataQualityError: If the payload fails post-validation data quality linting.
        """
        logger.debug("Creating manual annotation(s) for validation schema '%s'.", schema_id)

        if source_id is None:
            source_id = secrets.token_hex(12)

        execution_id = str(uuid4())
        source = AnnotationManualSource(id=source_id).model_dump()
        source["execution_id"] = execution_id

        annotations_to_process = annotation if isinstance(annotation, list) else [annotation]
        results = []

        for ann in annotations_to_process:
            if force:
                logger.debug("`force=True`: skipping all validation checks.")
                if is_pydantic_model_instance(ann):
                    validated_annotations = [ann.model_dump(by_alias=True, exclude_none=True)]
                else:
                    validated_annotations = [cast(dict[str, Any], ann)]
            else:
                try:
                    valid_ann = self.validate_manual_annotation(annotation=ann, validator=validator)
                    validated_annotations = [valid_ann]
                except (AnnotationValidationError, ValidationError, PydanticValidationError) as original_err:
                    from dorsal.file.chunking import chunk_record

                    raw_dict = (
                        ann.model_dump(by_alias=True, exclude_none=True)
                        if is_pydantic_model_instance(ann)
                        else cast(dict[str, Any], ann)
                    )

                    chunks = chunk_record(raw_dict, schema_id)

                    if len(chunks) > 1:
                        logger.info(
                            "Manual annotation validation failed. "
                            "Attempting to rescue by semantically chunking into %d records.",
                            len(chunks),
                        )
                        validated_annotations = []
                        try:
                            for chunk in chunks:
                                validated_annotations.append(
                                    self.validate_manual_annotation(annotation=chunk, validator=validator)
                                )
                            logger.info("Rescue successful. Manual annotation was safely chunked and validated.")
                        except (AnnotationValidationError, ValidationError, PydanticValidationError):
                            logger.warning("Rescue failed. The semantically chunked records still failed validation.")
                            raise original_err
                    else:
                        raise original_err

            for valid_rec in validated_annotations:
                if not force:
                    raise_on_error = not ignore_linter_errors
                    apply_linter(schema_id=schema_id, record=valid_rec, raise_on_error=raise_on_error)

                annotation_item = self._make_annotation(
                    validated_annotation=valid_rec,
                    schema_id=schema_id,
                    schema_version=schema_version,
                    private=private,
                    source=source,
                    force=force,
                )
                results.append(annotation_item)

        return results


FILE_ANNOTATOR = FileAnnotator()
