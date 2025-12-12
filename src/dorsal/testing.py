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
from typing import Any, Type, cast
from pydantic import BaseModel

from dorsal.common.model import AnnotationModel, AnnotationModelSource
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    get_json_schema_validator,
)
from dorsal.file.dependencies import make_file_extension_dependency, make_media_type_dependency
from dorsal.file.model_runner import ModelRunner
from dorsal.file.configs.model_runner import (
    RunModelResult,
    ModelRunnerDependencyConfig,
    check_extension_dependency,
    check_media_type_dependency,
    check_size_dependency,
    check_name_dependency,
    FileExtensionDependencyConfig,
    FilenameDependencyConfig,
    FileSizeDependencyConfig,
    MediaTypeDependencyConfig,
)
from dorsal.file.annotation_models.base import FileCoreAnnotationModel

from dorsal.file.schemas import get_open_schema, OpenSchemaName

from dorsal.file.validators.open_schema import get_open_schema_validator
from dorsal.file.validators.base import FileCoreValidationModelStrict

__all__ = [
    "get_json_schema_validator",
    "make_file_extension_dependency",
    "make_media_type_dependency",
    "get_open_schema",
    "get_open_schema_validator",
    "run_model",
    "RunModelResult",
]

logger = logging.getLogger(__name__)


def run_model(
    annotation_model: Type[AnnotationModel],
    file_path: str,
    *,
    schema_id: str | None = None,
    validation_model: Type[BaseModel] | JsonSchemaValidator | None = None,
    dependencies: list[ModelRunnerDependencyConfig] | ModelRunnerDependencyConfig | None = None,
    options: dict[str, Any] | None = None,
) -> RunModelResult:
    """
    Tests a single AnnotationModel in isolation.

    1.  `FileCoreAnnotationModel` retrieves base metadata.
    2.  (Optional) Checks your model's dependencies
    3.  Runs your model
    4.  Returns the result of your model's execution.

    Args:
        model_class: The custom AnnotationModel class you want to test (e.g., `ArchiveModel`).
        file_path: The absolute path to the file to test against.
        schema_id: (Optional) The target schema ID (e.g., "open/generic").
                   If this is an "open/" schema, the standard validator
                   will be used automatically.
        validation_model: (Optional) A *custom* Pydantic model or
                          JsonSchemaValidator. This overrides the
                          automatic validator from 'schema_id'.
        dependencies: (Optional) A list of dependency configs to check before running.
        options: (Optional) A dictionary of options to pass to the model's `.main()` method.

    Returns:
        A RunModelResult object containing your model's output or any errors.

    Raises:
        ValueError: If 'schema_id' is an "open/" schema and a
                    'validation_model' is also provided, as this
                    is an ambiguous configuration.
    """
    runner = ModelRunner(pipeline_config=None, debug=True, testing=True)

    logger.info(f"Running FileCoreAnnotationModel on {file_path}...")
    base_model_result = runner.run_single_model(
        annotation_model=FileCoreAnnotationModel,
        validation_model=FileCoreValidationModelStrict,
        file_path=file_path,
        options={"calculate_similarity_hash": True},
    )

    if base_model_result.error or base_model_result.record is None:
        logger.error(f"Base model failed, cannot proceed: {base_model_result.error}")
        return base_model_result

    deps_list = dependencies
    if deps_list and not isinstance(deps_list, list):
        deps_list = [deps_list]

    if deps_list:
        logger.info("Checking dependencies...")
        for dep_config in deps_list:
            is_met = False
            if isinstance(dep_config, MediaTypeDependencyConfig):
                is_met = check_media_type_dependency([base_model_result], dep_config)
            elif isinstance(dep_config, FileExtensionDependencyConfig):
                is_met = check_extension_dependency([base_model_result], dep_config)
            elif isinstance(dep_config, FilenameDependencyConfig):
                is_met = check_name_dependency([base_model_result], dep_config)
            elif isinstance(dep_config, FileSizeDependencyConfig):
                is_met = check_size_dependency([base_model_result], dep_config)
            if not is_met:
                dep_type = getattr(dep_config, "type", "Unknown")
                error_msg = f"Skipped: Dependency not met: {dep_type}"
                logger.warning(error_msg)
                return RunModelResult(
                    name=annotation_model.id or annotation_model.__name__,
                    source=AnnotationModelSource(
                        type="Model",
                        id=annotation_model.id or annotation_model.__name__,
                        version=annotation_model.version,
                        variant=annotation_model.variant,
                    ),
                    record=None,
                    schema_id=schema_id,
                    error=error_msg,
                )
        logger.info("All dependencies met.")

    if validation_model and schema_id and schema_id.startswith("open/"):
        raise ValueError(
            f"Ambiguous configuration: You cannot provide a custom 'validation_model' when using an 'open/' schema_id ('{schema_id}').\n"
            f"The 'open/' schemas use a standard, built-in validator.\n"
            f"  - To test with the standard validator: Remove the 'validation_model' argument.\n"
            f"  - To test with your custom validator: Use a custom 'schema_id' (e.g., 'my-org/my-custom-schema') or set schema_id=None."
        )

    effective_validator: Type[BaseModel] | JsonSchemaValidator | None = validation_model

    if effective_validator:
        logger.debug("Using explicitly provided 'validation_model'.")
    elif schema_id and schema_id.startswith("open/"):
        schema_name = schema_id.removeprefix("open/")
        try:
            effective_validator = get_open_schema_validator(cast(OpenSchemaName, schema_name))
            logger.debug("Resolved 'schema_id' (%s) to standard validator.", schema_id)
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning(
                "Could not find a standard validator for 'schema_id' (%s): %s. Proceeding without validation.",
                schema_id,
                e,
            )

    if annotation_model.__module__ == "__main__":
        logger.debug(
            "The 'annotation_model' (%s) is defined in your main script. "
            "Move it to an importable .py file before using 'register_model' or that function will complain.",
            annotation_model.__name__,
        )

    if effective_validator and effective_validator.__module__ == "__main__":
        validator_name = getattr(effective_validator, "__name__", str(effective_validator))
        logger.debug(
            "The 'validation_model' (%s) is defined in your main script. "
            "Move it to an importable .py file before using 'register_model' or that function will complain.",
            validator_name,
        )

    logger.info("Running %s on file: '%s'", annotation_model.__name__, file_path)
    my_model_result = runner.run_single_model(
        annotation_model=annotation_model,
        validation_model=effective_validator,
        file_path=file_path,
        base_model_result=base_model_result,
        schema_id=schema_id,
        options=options,
    )

    return my_model_result
