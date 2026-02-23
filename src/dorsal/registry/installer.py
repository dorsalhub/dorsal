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

import sys
import subprocess
import importlib.metadata
import importlib.resources
import logging
from packaging.utils import canonicalize_name
import pathlib
import tomllib
import shutil
from typing import Literal, Any

import tomlkit

from dorsal.api.config import register_model
from dorsal.common.exceptions import AuthError, DorsalError, DorsalConfigError
from dorsal.registry.validators import ModelSpec, is_registry_id, is_valid_local_path, validate_install_url
from dorsal.session import get_shared_dorsal_client

logger = logging.getLogger(__name__)


def _get_local_pyproject_name(target_path: pathlib.Path) -> str | None:
    """Safely extracts the package name from a local pyproject.toml file."""
    pyproject = target_path / "pyproject.toml"
    if not pyproject.is_file():
        return None

    try:
        with open(pyproject, "r", encoding="utf-8") as f:
            data = tomlkit.load(f)
        name = data.get("project", {}).get("name")
        return str(name) if name else None
    except Exception as e:
        logger.debug(f"Failed to parse pyproject.toml at {target_path}: {e}")
        return None


def _load_packaged_model_config(module_name: str) -> dict[str, Any]:
    """
    Loads 'model_config.toml' from the installed package resources or local project root.
    """
    try:
        resource_path = importlib.resources.files(module_name) / "model_config.toml"

        if resource_path.is_file():
            content = resource_path.read_text(encoding="utf-8")
            return tomllib.loads(content)

    except (ImportError, FileNotFoundError):
        pass
    except tomllib.TOMLDecodeError as e:
        raise DorsalConfigError(f"Syntax error in '{module_name}/model_config.toml': {e}") from e

    try:
        mod = importlib.import_module(module_name)
        mod_file = getattr(mod, "__file__", None)
        if mod_file:
            local_config = pathlib.Path(mod_file).parent.parent / "model_config.toml"
            if local_config.is_file():
                content = local_config.read_text(encoding="utf-8")
                return tomllib.loads(content)
    except Exception as e:
        logger.warning(f"Unexpected error loading fallback config from {module_name}: {e}")

    return {}


def _ensure_git_installed() -> None:
    """
    Verifies that 'git' is installed and available in the system PATH.
    """
    if shutil.which("git") is None:
        raise DorsalError(  # pragma: no cover
            "Git is not installed or not found in your system PATH.\n"
            "Installing models from the Dorsal Registry requires Git to clone the repositories.\n\n"
            "Please install Git and try again."
        )


def _run_pip_install_streaming(cmd: list[str], target_desc: str) -> None:
    """
    Runs pip install.
    - Default: Captures output silently, only printing it if an error occurs.
    - Verbose (-v): Streams output to stdout in real-time.
    """
    logger.info(f"Installing {target_desc}...")

    is_verbose = logger.isEnabledFor(logging.INFO)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    captured_lines = []

    if process.stdout:
        for line in process.stdout:
            if is_verbose:  # pragma: no cover
                sys.stdout.write(line)
            captured_lines.append(line)

    return_code = process.wait()

    if return_code != 0:
        full_log = "".join(captured_lines)

        if not is_verbose:
            sys.stderr.write(f"\n[!] Pip Installation Log for '{target_desc}':\n")
            sys.stderr.write(full_log)
            sys.stderr.write("\n")

        if "Repository not found" in full_log or "fatal: repository" in full_log:  # pragma: no cover
            raise DorsalError(
                f"The git repository for '{target_desc}' could not be found.\n"
                "It may have been deleted, made private, or you may lack the necessary SSH keys."
            )

        if "Authentication failed" in full_log or "could not read Username" in full_log:  # pragma: no cover
            raise DorsalError(
                f"Authentication failed while accessing '{target_desc}'.\n"
                "Please ensure you have access to this private repository."
            )

        if "No matching distribution found" in full_log:  # pragma: no cover
            raise DorsalError(
                f"Could not find a package for '{target_desc}' on PyPI.\n"
                "Check the spelling or ensuring you have the correct python version."
            )

        raise DorsalError(f"Installation failed for '{target_desc}'. See log output above.")


def install_model_target(
    target: str,
    scope: Literal["project", "global"] = "project",
    force_reinstall: bool = False,
) -> str:
    """
    Installs a model from a pip-compatible target and registers it.

    Identifies the package name from the Source of Truth (Registry Model or Local Config)
    BEFORE installation, ensuring robust handling of updates and reinstallations.
    """
    logger.info(f"Processing target: {target}")
    actual_target = None
    target_package_name = None

    if is_registry_id(target):
        if pathlib.Path(target).exists():
            raise DorsalError(
                f"Ambiguous Target: You requested Registry Model '{target}', but a directory with this name exists locally.\n"
                "To install the local model, use an explicit path: './{target}'\n"
                "To install the remote model, please rename or move the local directory."
            )

        logger.info(f"Resolved '{target}' to Registry ID.")
        client = get_shared_dorsal_client()
        try:
            reg_data = client.get_registry_model(target)
            actual_target = validate_install_url(reg_data.install_url)

            target_package_name = reg_data.package_name

            if actual_target.startswith("git+"):
                _ensure_git_installed()

            logger.info(f"Registry lookup successful. Package: {target_package_name}")

        except AuthError as e:
            raise e
        except Exception as e:
            raise DorsalError(f"Failed to resolve model '{target}' in registry: {e}") from e

    elif is_valid_local_path(target):
        logger.info(f"Resolved '{target}' to local path.")
        local_path = pathlib.Path(target).resolve()
        actual_target = str(local_path)

        target_package_name = _get_local_pyproject_name(local_path)

        if not target_package_name:
            raise DorsalError(
                f"Could not determine package name from '{target}'.\n"
                "Ensure the directory contains a valid 'pyproject.toml'."
            )

    else:
        raise DorsalError(
            f"Invalid install target '{target}'.\n\n"
            "Dorsal only supports installing from:\n"
            "1. A Registry ID (e.g. 'dorsalhub/whisper')\n"
            "2. A local directory path (e.g. './my-model')\n\n"
            "Generic PyPI packages must be installed via standard 'pip install'."
        )

    cmd = [sys.executable, "-m", "pip", "install", actual_target]
    if force_reinstall:
        cmd.append("--force-reinstall")

    _run_pip_install_streaming(cmd, target)

    importlib.invalidate_caches()

    safe_package_name = canonicalize_name(target_package_name)
    install_model_from_package(safe_package_name, scope=scope)

    return safe_package_name


def install_model_from_package(
    package_name: str,
    entry_point_group: str = "dorsal.models",
    scope: Literal["project", "global"] = "project",
) -> None:
    """
    Registers a model from an already installed package.
    Strictly requires 'model_config.toml' with an explicit 'model_class' definition.
    """
    logger.info(f"Registering model from package '{package_name}'...")

    eps = importlib.metadata.entry_points(group=entry_point_group)
    target_ep = None
    normalized_pkg_name = package_name.lower().replace("_", "-")

    for ep in eps:
        if ep.dist and ep.dist.name.lower().replace("_", "-") == normalized_pkg_name:
            target_ep = ep
            break
        if ep.name == package_name:
            target_ep = ep
            break

    if not target_ep:
        raise DorsalError(
            f"Package '{package_name}' is installed but does not expose a '{entry_point_group}' entry point.\n"
            "Try running with --force-reinstall if you believe this is an error."
        )

    try:
        module = target_ep.load()
        module_name = target_ep.module

        toml_config = _load_packaged_model_config(module_name)

        if not toml_config:
            raise DorsalError(
                f"Missing 'model_config.toml' in package '{package_name}'.\n"
                "Modern Dorsal models must include this file via 'force-include' in pyproject.toml."
            )

        if "model_class" not in toml_config:
            raise DorsalError(f"Invalid 'model_config.toml' in '{package_name}': Missing required key 'model_class'.")

        class_name = toml_config["model_class"]
        try:
            model_class = getattr(module, class_name)
        except AttributeError as err:
            raise DorsalError(
                f"Config defines model_class='{class_name}', but it was not exported by module '{module_name}' - {err}"
            ) from err

        merged_config = {
            "model_class": model_class,
            "schema_id": toml_config.get("schema_id", "open/generic"),
            "schema_version": toml_config.get("schema_version"),
            "dependencies": toml_config.get("dependencies"),
            "options": toml_config.get("options", {}),
        }

        spec = ModelSpec(**merged_config)

    except Exception as e:
        raise DorsalError(f"Failed to inspect model package '{package_name}': {e}") from e

    try:
        register_model(
            annotation_model=spec.model_class,
            schema_id=spec.schema_id,
            schema_version=spec.schema_version,
            validation_model=spec.validation_model,
            dependencies=spec.dependencies,
            options=spec.options,
            package_name=package_name,
            overwrite=True,
            scope=scope,
        )
        logger.info(f"Successfully registered model: {spec.model_class.__name__} ({spec.schema_id})")

    except Exception as e:
        raise DorsalConfigError(f"Failed to update config: {e}") from e
