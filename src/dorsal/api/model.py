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
import pathlib
import importlib.metadata
import importlib.resources
import tomllib
from typing import Any, Callable, Literal, cast

from packaging.utils import canonicalize_name
from pydantic import BaseModel

from dorsal.api.config import get_model_pipeline
from dorsal.common.constants import WEB_URL
from dorsal.common.exceptions import AuthError, DorsalError, DorsalConfigError, NotFoundError
from dorsal.common.validators import CallableImportPath
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep, resolve_pipeline_step_models, RunModelResult
from dorsal.file.file_annotator import FILE_ANNOTATOR
from dorsal.file.model_runner import ModelRunner, run_model
from dorsal.file.validators.file_record import Annotation, AnnotationGroup
from dorsal.registry.installer import install_model_target
from dorsal.registry.resolution import resolve_target, is_package_installed
from dorsal.registry.validators import is_registry_id, is_valid_local_path
from dorsal.registry.uninstaller import uninstall_model_target
from dorsal.registry.initialize import create_new_annotation_model_project
from dorsal.session import get_shared_dorsal_client

logger = logging.getLogger(__name__)

__all__ = ["get_model_help", "run_or_install_model", "install_model", "uninstall_model", "init_model_project"]


class ModelMetadata(BaseModel):
    """Encapsulates display metadata for the CLI security prompts."""

    description: str | None = None
    url: str | None = None
    source_url: str | None = None
    is_verified: bool = False
    is_official: bool = False
    published_date: str | None = None


class ModelTargetResolution(BaseModel):
    """The structured intent payload instructing the CLI how to proceed."""

    target: str
    strategy: Literal["pipeline", "registry_id", "local_path", "package", "error"]
    package_name: str | None = None

    is_installed: bool = False

    metadata: ModelMetadata | None = None
    error_message: str | None = None


def prepare_model_target(target: str) -> ModelTargetResolution:
    """
    Evaluates a user string, fetches relevant metadata, and returns a
    structured resolution plan without executing or installing anything.
    """
    pipeline = get_model_pipeline(scope="effective")
    for step in pipeline:
        if step.annotation_model.name == target:
            return ModelTargetResolution(
                target=target,
                strategy="pipeline",
                package_name=step.package_name or "dorsal",
                is_installed=True,
            )

    if is_registry_id(target):
        try:
            _, package_name = resolve_target(target)
            is_installed = is_package_installed(package_name)
            client = get_shared_dorsal_client()
            reg_data = client.get_registry_model(target)

            source_url = None
            if reg_data.install_url:
                source_url = reg_data.install_url.replace("git+", "").split("@")[0]

            metadata = ModelMetadata(
                description=reg_data.description,
                url=f"{WEB_URL}/models/{reg_data.namespace}/{reg_data.name}",
                source_url=source_url,
                is_verified=reg_data.is_verified,
                is_official=reg_data.is_official,
                published_date=reg_data.created_at.date().isoformat() if reg_data.created_at else None,
            )

            return ModelTargetResolution(
                target=target,
                strategy="registry_id",
                package_name=package_name,
                is_installed=is_installed,
                metadata=metadata,
            )
        except (AuthError, NotFoundError) as e:
            return ModelTargetResolution(target=target, strategy="error", error_message=str(e))
        except Exception as e:
            logger.debug(f"Failed to fetch metadata for {target}: {e}")
            return ModelTargetResolution(
                target=target, strategy="error", error_message=f"Registry connection failed: {e}"
            )

    if target.startswith((".", "/", "~")) or is_valid_local_path(target):
        return ModelTargetResolution(
            target=target,
            strategy="local_path",
            is_installed=False,
        )

    safe_pkg_name = canonicalize_name(target)

    if is_package_installed(safe_pkg_name):
        return ModelTargetResolution(
            target=target,
            strategy="package",
            package_name=safe_pkg_name,
            is_installed=True,
        )

    return ModelTargetResolution(
        target=target,
        strategy="error",
        error_message=f"Model '{target}' is not installed.",
    )


def init_model_project(name: str, target_dir: pathlib.Path | None = None):
    """API wrapper to scaffold a new model directory."""
    return create_new_annotation_model_project(name=name, target_dir=target_dir)


def install_model(target: str, scope: Literal["project", "global"] = "project", force_reinstall: bool = False) -> str:
    """API wrapper to install and register a model."""
    res = prepare_model_target(target)

    if res.strategy == "error":
        raise DorsalError(res.error_message or f"Failed to resolve target '{target}'.")
    if res.strategy == "pipeline":
        raise DorsalError(f"Target '{target}' is a built-in core model and cannot be installed via pip.")

    return install_model_target(target=target, scope=scope, force_reinstall=force_reinstall)


def uninstall_model(target: str, scope: Literal["project", "global"] = "project") -> str:
    """API wrapper to unregister and uninstall a model."""
    res = prepare_model_target(target)

    if res.strategy == "error":
        raise DorsalError(res.error_message or f"Failed to resolve target '{target}'.")
    if res.strategy == "pipeline":
        raise DorsalError(
            f"Target '{target}' is a built-in core model. Use 'dorsal config pipeline remove' instead of uninstalling."
        )

    return uninstall_model_target(target=target, scope=scope)


def run_or_install_model(
    target: str,
    file_path: str,
    *,
    options: dict[str, Any] | None = None,
    ignore_linter_errors: bool = False,
    progress_callback: Callable[[float, float, str], None] | None = None,
) -> list[RunModelResult]:

    logger.info(f"Requesting run for model target '{target}' on file '{file_path}'")

    res = prepare_model_target(target)

    if res.strategy == "error":
        raise DorsalError(res.error_message or f"Failed to resolve target '{target}'.")

    if not res.is_installed:
        if res.strategy in ("registry_id", "local_path"):
            logger.info(f"Model '{target}' is not installed. Auto-installing...")
            res.package_name = install_model_target(target)
            res.is_installed = True
        else:
            raise DorsalError(f"Model '{target}' is not installed and cannot be auto-installed.")

    if res.strategy == "pipeline":
        pipeline = get_model_pipeline(scope="effective")
        pipeline_step = next(step for step in pipeline if step.annotation_model.name == target)
        logger.debug(f"Target '{target}' resolved directly to active pipeline step.")
    else:
        if not res.package_name:
            raise DorsalError(f"Could not determine package name for target '{target}'.")
        pipeline_step = _construct_step_from_package(res.package_name)

    if options or ignore_linter_errors:
        pipeline_step = pipeline_step.model_copy(deep=True)
        if options:
            pipeline_step.options = {**(pipeline_step.options or {}), **options}
        if ignore_linter_errors:
            pipeline_step.ignore_linter_errors = True

    annotator_class, validator = resolve_pipeline_step_models(pipeline_step)
    effective_validator = (
        None if (pipeline_step.schema_id and pipeline_step.schema_id.startswith("open/")) else validator
    )

    return run_model(
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


def _find_pipeline_step_by_target(target: str) -> ModelRunnerPipelineStep | None:
    """Finds a target model directly within the effective pipeline configuration."""
    pipeline = get_model_pipeline(scope="effective")
    safe_target = canonicalize_name(target)

    for step in pipeline:
        if step.annotation_model.name == target:
            return step

        if step.package_name and canonicalize_name(step.package_name) == safe_target:
            return step

    return None


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
        if isinstance(value, dict) and "default" in value:
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
            options=parsed_options,
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
    res = prepare_model_target(target)

    if res.strategy == "error":
        return {"status": "error", "target": target, "error": res.error_message or "Unknown error"}

    if not res.is_installed:
        return {"status": "not_installed", "target": target, "package_name": res.package_name}

    package_name: str
    if res.strategy == "pipeline":
        pipeline = get_model_pipeline(scope="effective")
        pipeline_step = next((step for step in pipeline if step.annotation_model.name == target), None)

        if pipeline_step:
            package_name = pipeline_step.package_name or "dorsal"
            module_name = pipeline_step.annotation_model.module
            model_class = pipeline_step.annotation_model.name

            try:
                config_data = _load_package_config(module_name, package_name)
            except DorsalConfigError:
                logger.debug(f"No model_config.toml found for {model_class}, using pipeline options.")
                config_data = {"model_class": model_class, "options": pipeline_step.options or {}}
        else:
            return {"status": "error", "target": target, "error": f"Failed to retrieve pipeline step for {target}"}
    else:
        if not res.package_name:
            return {"status": "error", "target": target, "error": f"No package name found for target '{target}'."}
        package_name = res.package_name
        try:
            module_name = _resolve_module_from_package(package_name)
            config_data = _load_package_config(module_name, package_name)
        except Exception as e:
            return {"status": "config_error", "target": target, "package_name": package_name, "error": str(e)}

    raw_options = config_data.get("options", {})
    normalized_options: dict[str, dict[str, Any]] = {}

    for opt_key, opt_val in raw_options.items():
        if isinstance(opt_val, dict):
            opt_type = opt_val.get("type")

            if not opt_type and "default" in opt_val:
                opt_type = type(opt_val["default"]).__name__

            elif not opt_type:
                opt_type = "str"

            normalized_options[opt_key] = {
                "default": opt_val.get("default", None),
                "type": opt_type,
                "help": opt_val.get("help", "No description provided."),
            }
        else:
            normalized_options[opt_key] = {
                "default": opt_val,
                "type": type(opt_val).__name__,
                "help": "No description provided.",
            }

    return {
        "status": "success",
        "target": target,
        "package_name": package_name,
        "model_class": config_data.get("model_class", "UnknownClass"),
        "options": normalized_options,
    }
