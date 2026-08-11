# Copyright 2026 Dorsal Hub LTD
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
import importlib.metadata
import importlib.resources
import tomllib
from typing import Any, Callable, cast

from packaging.utils import canonicalize_name

from dorsal.api.config import get_model_pipeline
from dorsal.common.exceptions import AuthError, DorsalError, DorsalConfigError
from dorsal.common.validators import CallableImportPath
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep, resolve_pipeline_step_models, RunModelResult
from dorsal.file.file_annotator import FILE_ANNOTATOR
from dorsal.file.model_runner import ModelRunner, run_model
from dorsal.file.validators.file_record import Annotation, AnnotationGroup
from dorsal.registry.installer import install_model_target
from dorsal.registry.resolution import resolve_target, is_package_installed

logger = logging.getLogger(__name__)

__all__ = ["run_or_install_model"]


def run_or_install_model(
    target: str,
    file_path: str,
    *,
    options: dict[str, Any] | None = None,
    ignore_linter_errors: bool = False,
    progress_callback: Callable[[float, float, str], None] | None = None,
) -> list[RunModelResult]:
    """
    Resolve a model, installs if necessary, and execute it on a local file.

    Args:
        target: A Registry ID ('dorsalhub/whisper'), Package Name ('dorsal-whisper'),
                or Class Name ('FasterWhisperTranscriber').
        file_path: Path to the file to process.
        api_key: Optional API key.
        options: Runtime options to override the model's defaults.
        ignore_linter_errors: If True, bypasses data quality checks.

    Returns:
        Annotation | AnnotationGroup: The final, validated annotation object(s).
    """
    logger.info(f"Requesting run for model target '{target}' on file '{file_path}'")

    strategy, package_name = resolve_target(target)

    if not is_package_installed(package_name):
        if strategy == "registry_id":
            logger.info(f"Model package '{package_name}' is not installed. Installing from '{target}'...")
            try:
                install_model_target(target)
                logger.info(f"Successfully installed '{package_name}'.")
            except Exception as e:
                raise DorsalError(f"Failed to auto-install model '{target}': {e}") from e
        else:
            message = f"The model '{target}' is not installed locally.\n"
            if target == ".":
                message += "For local development, install the model before running it."
            raise DorsalError(message)

    pipeline_step = _get_execution_step(package_name)

    if options or ignore_linter_errors:
        pipeline_step = pipeline_step.model_copy(deep=True)
        if options:
            pipeline_step.options = {**(pipeline_step.options or {}), **options}
        if ignore_linter_errors:
            pipeline_step.ignore_linter_errors = True

    annotator_class, validator = resolve_pipeline_step_models(pipeline_step)

    if pipeline_step.schema_id and pipeline_step.schema_id.startswith("open/"):
        effective_validator = None
    else:
        effective_validator = validator

    # 2. Delegate directly to run_model
    run_result = run_model(
        annotation_model=annotator_class,
        file_path=file_path,
        schema_id=pipeline_step.schema_id,
        schema_version=pipeline_step.schema_version,
        validation_model=effective_validator,
        dependencies=pipeline_step.dependencies,
        options=pipeline_step.options,
        ignore_linter_errors=pipeline_step.ignore_linter_errors,
        progress_callback=progress_callback,
    )

    return run_result


def _get_execution_step(package_name: str) -> ModelRunnerPipelineStep:
    """Retrieves ModelRunnerPipelineStep for the given package."""

    pipeline = get_model_pipeline(scope="effective")
    safe_pkg_name = canonicalize_name(package_name)

    for step in pipeline:
        if step.package_name and canonicalize_name(step.package_name) == safe_pkg_name:
            logger.debug(f"Found existing pipeline configuration for '{package_name}'.")
            return step

    logger.debug(f"No pipeline config found for '{package_name}'. Constructing ephemeral step from package.")
    return _construct_step_from_package(package_name)


def _construct_step_from_package(package_name: str) -> ModelRunnerPipelineStep:
    """Orchestrate construction of a pipeline step from an installed package."""
    module_name = _resolve_module_from_package(package_name)
    config_data = _load_package_config(module_name, package_name)
    return _build_pipeline_step(config_data, module_name, package_name)


def _resolve_module_from_package(package_name: str) -> str:
    """Resolve module name for a package by inspecting 'dorsal.models' entry points."""
    safe_pkg_name = canonicalize_name(package_name)
    eps = importlib.metadata.entry_points(group="dorsal.models")

    for ep in eps:
        if ep.dist and canonicalize_name(ep.dist.name) == safe_pkg_name:
            return ep.module

    raise DorsalError(
        f"Package '{package_name}' is installed but does not declare a 'dorsal.models' entry point.\n"
        "This package may be broken or is not a compatible Dorsal model."
    )


def _load_package_config(module_name: str, package_name: str) -> dict[str, Any]:
    """Load and parse 'model_config.toml' from the package's module resources."""
    try:
        resource_path = importlib.resources.files(module_name) / "model_config.toml"
        if not resource_path.is_file():
            raise DorsalConfigError(
                f"Package '{package_name}' is missing 'model_config.toml' in module '{module_name}'"
            )

        config_text = resource_path.read_text(encoding="utf-8")
        return tomllib.loads(config_text)

    except (ImportError, FileNotFoundError) as err:
        raise DorsalConfigError(f"Could not load config for '{package_name}': {err}") from err
    except tomllib.TOMLDecodeError as err:
        raise DorsalConfigError(f"Syntax error in 'model_config.toml' for '{package_name}': {err}") from err


def _build_pipeline_step(config_data: dict[str, Any], module_name: str, package_name: str) -> ModelRunnerPipelineStep:
    """Validate configuration data and constructs the ModelRunnerPipelineStep object.

    Supports both legacy (flat, string) and modern `model_config.toml` formats.
    """
    class_name = config_data.get("model_class")
    schema_id = config_data.get("schema_id")

    if not class_name:
        raise DorsalConfigError(f"Invalid config in '{package_name}': missing required field 'model_class'")

    if not schema_id:
        raise DorsalConfigError(f"Invalid config in '{package_name}': missing required field 'schema_id'")

    raw_options = config_data.get("options", {})
    parsed_options = {}

    for key, value in raw_options.items():
        if isinstance(value, dict) and ("default" in value or "help" in value):
            if "default" in value:
                parsed_options[key] = value["default"]
        else:
            parsed_options[key] = value

    try:
        return ModelRunnerPipelineStep(
            annotation_model=CallableImportPath(module=module_name, name=class_name),
            schema_id=schema_id,
            schema_version=config_data.get("schema_version"),
            dependencies=config_data.get("dependencies"),
            validation_model=None,
            options=config_data.get("options"),
            package_name=package_name,
        )
    except Exception as e:
        raise DorsalError(f"Failed to construct pipeline step for '{package_name}': {e}") from e


def get_model_help(target: str) -> dict[str, Any]:
    """
    Retrieve structured options and metadata for a specific model target.

    Returns a dictionary containing the model's status, package info,
    and normalized options (default values & help strings).
    """
    try:
        strategy, package_name = resolve_target(target)
    except (DorsalError, AuthError) as e:
        return {
            "status": "error",
            "target": target,
            "error": str(e),
        }

    if not is_package_installed(package_name):
        return {
            "status": "not_installed",
            "target": target,
            "package_name": package_name,
        }

    try:
        module_name = _resolve_module_from_package(package_name)
        config_data = _load_package_config(module_name, package_name)
    except Exception as e:
        return {
            "status": "config_error",
            "target": target,
            "package_name": package_name,
            "error": str(e),
        }

    raw_options = config_data.get("options", {})
    normalized_options: dict[str, dict[str, Any]] = {}

    for opt_key, opt_val in raw_options.items():
        if isinstance(opt_val, dict):
            normalized_options[opt_key] = {
                "default": opt_val.get("default", ""),
                "help": opt_val.get("help", "No description provided."),
            }
        else:
            normalized_options[opt_key] = {
                "default": opt_val,
                "help": "No description provided.",
            }

    return {
        "status": "success",
        "target": target,
        "package_name": package_name,
        "model_class": config_data.get("model_class", "UnknownClass"),
        "options": normalized_options,
    }
