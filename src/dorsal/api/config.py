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
import re
from typing import Literal, Type, Any, cast

from packaging.utils import canonicalize_name

from dorsal.common.auth import (
    get_api_key_details,
    get_email_from_config,
    get_theme_from_config,
    APIKeySource,
)
from dorsal.common import constants
from dorsal.common.config import load_config, get_global_config_path, resolve_setting, set_config_value
from dorsal.common.model import AnnotationModel
from dorsal.common.validators import JsonSchemaValidator
from dorsal.file.configs.model_runner import ModelRunnerDependencyConfig
from dorsal.file.pipeline_config import PipelineConfig
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep

logger = logging.getLogger(__name__)


def get_config_summary() -> dict[str, Any]:
    """
    Retrieves a summary of the current system configuration (Auth, UI, Paths).
    """
    from dorsal.file.index.config import get_index_compression, get_index_compression_mode, get_index_compression_level
    details = get_api_key_details()

    key_source_map = {
        APIKeySource.ENV: "environment variable",
        APIKeySource.PROJECT: f"project config: {details['path']}",
        APIKeySource.GLOBAL: f"global config: {details['path']}",
        APIKeySource.NONE: "N/A",
    }

    config_file_path = str(details["path"]) or str(load_config()[1])

    return {
        "current_theme": os.getenv("DORSAL_THEME") or get_theme_from_config() or "default",
        "logged_in_user": get_email_from_config(),
        "api_key_set": details["source"] != APIKeySource.NONE,
        "api_key_source": key_source_map[details["source"]],
        "api_url": constants.BASE_URL,
        "reports_path": str(constants.LOCAL_DORSAL_DIR),
        "active_config_path": config_file_path,
        "global_config_path": str(get_global_config_path()),
        "index_compression_enabled": get_index_compression(),
        "index_compression_mode": get_index_compression_mode(),
        "index_compression_level": get_index_compression_level(),
    }


def get_model_pipeline(scope: Literal["effective", "project", "global"] = "effective") -> list[ModelRunnerPipelineStep]:
    """
    Returns the current list of annotation model objects in the pipeline.
    Useful for programmatic inspection of options and configuration.
    """
    return PipelineConfig.get_steps(scope=scope)


def show_model_pipeline(scope: Literal["effective", "project", "global"] = "effective") -> list[dict[str, Any]]:
    """
    Returns a simplified, human-readable summary of the pipeline.
    """
    steps = PipelineConfig.get_steps(scope=scope)
    summary = []
    for i, step in enumerate(steps):
        deps_str = "None"
        if step.dependencies:
            deps = [d.type for d in step.dependencies]
            deps_str = ", ".join(deps)

        status = "Active"
        if step.deactivated:
            status = "Deactivated"
        if i == 0:
            status = "Base (Locked)"

        summary.append(
            {
                "index": i,
                "status": status,
                "name": step.annotation_model.name,
                "module": step.annotation_model.module,
                "schema_id": step.schema_id,
                "schema_version": step.schema_version,
                "dependencies": deps_str,
            }
        )
    return summary


def remove_model_by_index(index: int, scope: Literal["project", "global"] = "project") -> None:
    """Removes a model from the pipeline by its index."""
    PipelineConfig.remove_step_by_index(index=index, scope=scope)


def remove_model_by_name(name: str, scope: Literal["project", "global"] = "project") -> None:
    """
    Removes a model from the pipeline by its name (e.g., "PDFAnnotationModel").
    Raises an error if the name is ambiguous (duplicates exist).
    """
    PipelineConfig.remove_step_by_name(name=name, scope=scope)


def activate_model_by_index(index: int, scope: Literal["project", "global"] = "project") -> None:
    """Activates (enables) a model in the pipeline by index."""
    PipelineConfig.set_step_status_by_index(index=index, active=True, scope=scope)


def activate_model_by_name(name: str, scope: Literal["project", "global"] = "project") -> None:
    """Activates (enables) a model in the pipeline by name."""
    PipelineConfig.set_step_status_by_name(name=name, active=True, scope=scope)


def deactivate_model_by_index(index: int, scope: Literal["project", "global"] = "project") -> None:
    """Deactivates (disables) a model in the pipeline by index."""
    PipelineConfig.set_step_status_by_index(index=index, active=False, scope=scope)


def deactivate_model_by_name(name: str, scope: Literal["project", "global"] = "project") -> None:
    """Deactivates (disables) a model in the pipeline by name."""
    PipelineConfig.set_step_status_by_name(name=name, active=False, scope=scope)


def find_package_name_by_class(class_name: str, scope: Literal["project", "global"] = "project") -> str | None:
    """
    Resolves a Model Class Name (e.g. 'FasterWhisperTranscriber') to its  package name (e.g. 'dorsal-whisper')
    """
    steps = PipelineConfig.get_steps(scope=scope)

    for step in steps:
        if step.annotation_model.name == class_name:
            if step.package_name:
                return step.package_name

            return None

    return None

def set_compression(
    mode: Literal["zlib", "zstd"] | None = None,
    level: int | None = None,
    scope: Literal["project", "global"] = "project"
) -> None:
    """
    Updates the index compression settings in the dorsal configuration file.
    
    Args:
        mode: The compression mode to use ("zlib" or "zstd").
        level: The compression level (zlib: 0-9, zstd: 1-22).
        scope: The config scope to modify ("project" or "global").
    """
    if mode is not None:
        if mode not in ("zlib", "zstd"):
            raise ValueError(f"Unsupported compression mode '{mode}'. Must be 'zlib' or 'zstd'.")
        set_config_value(constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_MODE, mode, scope=scope)

    if level is not None:
        if not isinstance(level, int) or level < 0 or level > 22:
            raise ValueError("Compression level must be an integer between 0 and 22.")
        set_config_value(constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_LEVEL, level, scope=scope)

def register_model(
    annotation_model: Type[AnnotationModel],
    schema_id: str | None = None,
    schema_version: str | None = None,
    validation_model: dict | Type[Any] | JsonSchemaValidator | None = None,
    dependencies: list[ModelRunnerDependencyConfig] | ModelRunnerDependencyConfig | None = None,
    options: dict | None = None,
    package_name: str | None = None,
    overwrite: bool = False,
    *,
    scope: Literal["project", "global"] = "project",
) -> None:
    """
    Programmatically registers a new annotation model in the dorsal config.
    """
    from dorsal.common.model import is_pydantic_model_class, is_pydantic_model_instance
    from dorsal.common.validators.json_schema import (
        JsonSchemaValidator,
        JSON_SCHEMA_CONSTRAINT_KEYWORDS,
    )
    from dorsal.common.exceptions import DorsalConfigError, PydanticValidationError
    from dorsal.file.schemas import normalize_schema_id
    from dorsal.common.validators.schemas import is_valid_dataset_id_or_schema_id

    if scope not in ["project", "global"]:
        raise ValueError("Invalid scope. Must be one of 'project' or 'global'.")

    effective_dependencies_dicts = []
    if dependencies:
        dep_list = dependencies
        if not isinstance(dep_list, list):
            dep_list = [dep_list]
        for i, dep in enumerate(dep_list):
            d_any = cast(Any, dep)
            if is_pydantic_model_instance(d_any):
                effective_dependencies_dicts.append(d_any.model_dump())
            elif isinstance(d_any, dict):
                raise TypeError(
                    f"Item {i} in 'dependencies' is a dict. "
                    "Dependencies must be passed as instances of a "
                    "'ModelRunnerDependencyConfig' subclass (e.g., MediaTypeDependencyConfig)."
                )
            else:
                raise TypeError(
                    f"Item {i} in 'dependencies' is an invalid type ({type(d_any)}). "
                    "Must be an instance of 'ModelRunnerDependencyConfig'."
                )

    model_module, model_name = annotation_model.__module__, annotation_model.__name__
    if model_module == "__main__":
        raise TypeError(f"Model '{model_name}' must be defined in an importable module, not the main script.")
    model_path = (model_module, model_name)

    if schema_id is None:
        if validation_model is not None and is_pydantic_model_class(validation_model):
            class_name = validation_model.__name__
            norm_name = re.sub(r"(?<!^)(?=[A-Z])", "-", class_name).lower()
            schema_id = f"pydantic/{norm_name}"
        else:
            raise ValueError(
                "A 'schema_id' must be provided explicitly unless a Pydantic class "
                "is passed as the 'validation_model' (in which case it can be inferred)."
            )

    schema_id = normalize_schema_id(schema_id)

    if not is_valid_dataset_id_or_schema_id(schema_id):
        raise ValueError(
            f"The schema ID '{schema_id}' is invalid. "
            "It must consist of a namespace and a name separated by a forward slash (e.g., 'namespace/dataset-name'). "
            "Both parts must be 3 to 32 characters long and contain only lowercase letters, numbers, and hyphens."
        )

    is_open_schema = False
    if schema_id is not None:
        is_open_schema = schema_id.startswith("open/")
    validation_model_config: tuple[str, str] | dict[str, Any] | None = None

    if validation_model is not None:
        if isinstance(validation_model, dict):
            if not any(key in validation_model for key in JSON_SCHEMA_CONSTRAINT_KEYWORDS):
                raise ValueError("The provided 'validation_model' JSON Schema is inert (won't validate anything)")
            validation_model_config = validation_model
        elif is_pydantic_model_class(validation_model):
            validator_module, validator_name = (
                validation_model.__module__,
                validation_model.__name__,
            )
            if validator_module == "__main__":
                raise TypeError(f"Validator class '{validator_name}' must be defined in an importable module.")
            validation_model_config = (validator_module, validator_name)
        elif isinstance(validation_model, JsonSchemaValidator):
            validator_module, validator_name = (
                validation_model.__module__,
                validation_model.__name__,
            )
            if validator_module == "__main__":
                raise TypeError(f"Validator instance '{validator_name}' must be defined in an importable module.")
            validation_model_config = (validator_module, validator_name)
        else:
            raise TypeError(f"Invalid 'validation_model' type ({type(validation_model)}).")

    elif is_open_schema and schema_id is not None:
        schema_name = schema_id.removeprefix("open/")
        clean_name = schema_name.replace("-", "_")
        validation_model_config = (
            "dorsal.file.validators.open_schema",
            f"{clean_name}_validator",
        )

    new_step_data = {
        k: v
        for k, v in {
            "annotation_model": model_path,
            "schema_id": schema_id,
            "schema_version": schema_version,
            "dependencies": effective_dependencies_dicts if effective_dependencies_dicts else None,
            "validation_model": validation_model_config,
            "options": options,
            "package_name": package_name,
        }.items()
        if v is not None
    }

    try:
        validated_step_model = ModelRunnerPipelineStep.model_validate(new_step_data)
        toml_safe_step_data = validated_step_model.model_dump(mode="json", exclude_none=True)
    except PydanticValidationError as e:
        raise DorsalConfigError(f"The provided model configuration is invalid: {e}") from e

    try:
        PipelineConfig.upsert_step(step_data=toml_safe_step_data, overwrite=overwrite, scope=scope)
    except Exception as e:
        raise DorsalConfigError(f"Failed to register model in {scope} config: {e}") from e


def unregister_model(package_name: str, scope: Literal["project", "global"] = "project") -> None:
    """
    Removes a model configuration from the pipeline.

    Args:
        package_name: The package name of the model (e.g., 'dorsal-whisper').
        scope: The config scope to modify ('project' or 'global').

    Raises:
        KeyError: If the model is not found in the specified scope.
        DorsalConfigError: If writing to the config file fails.
    """
    from dorsal.common.exceptions import DorsalConfigError

    if scope not in ["project", "global"]:
        raise ValueError("Invalid scope. Must be one of 'project' or 'global'.")

    clean_name = package_name.lower().replace("-", "_")

    logger.info(f"Attempting to unregister package '{package_name}' (looking for module '{clean_name}')")

    steps = PipelineConfig.get_steps(scope=scope)

    if not steps:
        logger.warning(f"No pipeline steps found in {scope} scope. Config might be empty.")

    found_index = -1

    for i, step in enumerate(steps):
        try:
            module_path = step.annotation_model.module.lower()

            logger.debug(f"Checking step {i}: {module_path} vs {clean_name}")

            if clean_name == module_path or clean_name in module_path.split("."):
                found_index = i
                logger.info(f"Found match at index {i}: {module_path}")
                break

        except AttributeError:
            logger.debug(f"Skipping step {i} (invalid structure)")
            continue

    if found_index == -1:
        step_modules = [s.annotation_model.module for s in steps]
        raise KeyError(
            f"Could not find model for '{package_name}' in {scope} config.\n"
            f"Looked for module matching: '{clean_name}'\n"
            f"Available modules: {step_modules}"
        )

    try:
        PipelineConfig.remove_step_by_index(index=found_index, scope=scope)
        logger.info(f"Removed step {found_index} from {scope} config.")
    except Exception as e:
        raise DorsalConfigError(f"Failed to unregister model '{package_name}' from {scope} config: {e}") from e

