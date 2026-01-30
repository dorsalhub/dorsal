# dorsal/registry/installer.py

import sys
import subprocess
import importlib.metadata
import importlib.resources
import logging
import pathlib
import tomllib
from typing import Literal, Any

import tomlkit

from dorsal.api.config import register_model
from dorsal.common.exceptions import DorsalError, DorsalConfigError
from dorsal.registry.validators import ModelSpec, is_registry_id
from dorsal.session import get_shared_dorsal_client

logger = logging.getLogger(__name__)


def _get_installed_distribution_names() -> set[str]:
    """Helper to get a set of all currently installed package names (normalized)."""
    return {dist.metadata["Name"].lower().replace("_", "-") for dist in importlib.metadata.distributions()}


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
    Loads 'model_config.toml' from the installed package resources.
    """
    try:
        # traverse the package resources safely (zip-safe)
        resource_path = importlib.resources.files(module_name) / "model_config.toml"

        if not resource_path.is_file():
            return {}

        content = resource_path.read_text(encoding="utf-8")
        return tomllib.loads(content)

    except (ImportError, FileNotFoundError):
        return {}
    except tomllib.TOMLDecodeError as e:
        raise DorsalConfigError(f"Syntax error in '{module_name}/model_config.toml': {e}") from e
    except Exception as e:
        logger.warning(f"Unexpected error loading config from {module_name}: {e}")
        return {}


def _run_pip_install_streaming(cmd: list[str], target_desc: str) -> None:
    """
    Runs pip install while streaming output to stdout, but capturing it for
    error analysis if the process fails.
    """
    logger.info(f"Installing {target_desc}...")

    # Merge stderr into stdout so we capture everything in one stream
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",  # Prevent crashing on non-utf8 install logs
        bufsize=1,  # Line buffered
    )

    captured_lines = []

    # Real-time streaming
    if process.stdout:
        for line in process.stdout:
            # Print to user immediately
            sys.stdout.write(line)
            # Capture for analysis
            captured_lines.append(line)

    return_code = process.wait()

    if return_code != 0:
        full_log = "".join(captured_lines)

        # --- Error Analysis Logic ---

        # Case 1: Git Repository Not Found
        if "Repository not found" in full_log or "fatal: repository" in full_log:
            raise DorsalError(
                f"The git repository for '{target_desc}' could not be found.\n"
                "It may have been deleted, made private, or you may lack the necessary SSH keys."
            )

        # Case 2: Git Authentication Failed (Private Repo)
        if "Authentication failed" in full_log or "could not read Username" in full_log:
            raise DorsalError(
                f"Authentication failed while accessing '{target_desc}'.\n"
                "Please ensure you have access to this private repository."
            )

        # Case 3: Invalid PyPI package
        if "No matching distribution found" in full_log:
            raise DorsalError(
                f"Could not find a package for '{target_desc}' on PyPI.\n"
                "Check the spelling or ensuring you have the correct python version."
            )

        # Fallback: Generic Pip Error
        raise DorsalError(f"Installation failed for '{target_desc}'. See log output above.")


def install_model_target(
    target: str,
    scope: Literal["project", "global"] = "project",
    force_reinstall: bool = False,
) -> str:
    """
    Installs a model from a pip-compatible target (PyPI name, git URL, or local path)
    and registers it to the dorsal configuration.
    """
    logger.info(f"Processing target: {target}")

    actual_target = target

    # 1. Resolve Registry ID
    if is_registry_id(target):
        try:
            client = get_shared_dorsal_client()
            registry_data = client.get_registry_model(target)
            actual_target = registry_data.install_url

            logger.info(f"Resolved registry ID '{target}' to install target: {actual_target}")
        except Exception as e:
            logger.warning(f"Registry lookup failed. Treating '{target}' as direct pip target. Error: {e}")
            actual_target = target

    # 2. Snapshot environment
    pre_install_packages = _get_installed_distribution_names()

    # 3. Run pip install (using the streaming helper)
    cmd = [sys.executable, "-m", "pip", "install", actual_target]
    if force_reinstall:
        cmd.append("--force-reinstall")

    _run_pip_install_streaming(cmd, target)

    # 4. Detect the package
    importlib.invalidate_caches()
    post_install_packages = _get_installed_distribution_names()

    new_packages = post_install_packages - pre_install_packages

    package_name = None

    if len(new_packages) == 1:
        package_name = list(new_packages)[0]
    elif len(new_packages) > 1:
        for pkg in new_packages:
            try:
                eps = importlib.metadata.entry_points(group="dorsal.models")
                if any(ep.dist and ep.dist.name.lower().replace("_", "-") == pkg for ep in eps):
                    package_name = pkg
                    break
            except Exception:
                continue

    # Fallback 1: Check local pyproject.toml
    if not package_name:
        try:
            path_target = pathlib.Path(actual_target).resolve()
            candidate_name = _get_local_pyproject_name(path_target)

            if candidate_name:
                norm_name = candidate_name.lower().replace("_", "-")
                if norm_name in post_install_packages:
                    package_name = norm_name
                    logger.debug(f"Detected existing local package: {package_name}")
        except Exception as e:
            logger.debug(f"Failed to inspect local path '{actual_target}': {e}")

    # Fallback 2: Heuristic
    if not package_name:
        if "git+" not in actual_target and "/" not in actual_target and "\\" not in actual_target:
            package_name = actual_target

    if not package_name:
        raise DorsalError(
            f"Package from '{target}' appears to be installed, but we could not determine its name to register it.\n"
            "Tip: Try running with [bold white]--force[/] to trigger a clean reinstall."
        )

    # 5. Register using the detected name
    install_model_from_package(package_name, scope=scope)

    return package_name


def install_model_from_package(
    package_name: str,
    entry_point_group: str = "dorsal.models",
    scope: Literal["project", "global"] = "project",
) -> None:
    """
    Registers a model from an installed package.
    Strictly requires 'model_config.toml' with an explicit 'model_class' definition.
    """
    logger.info(f"Registering model from package '{package_name}'...")

    # 1. Resolve Entry Point
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
            f"Package '{package_name}' is installed but does not expose a '{entry_point_group}' entry point."
        )

    try:
        # 2. Load the Module (Code)
        module = target_ep.load()
        module_name = target_ep.module

        # 3. Load the Metadata (Config)
        toml_config = _load_packaged_model_config(module_name)

        if not toml_config:
            raise DorsalError(
                f"Missing 'model_config.toml' in package '{package_name}'.\n"
                "Modern Dorsal models must include this file via 'force-include' in pyproject.toml."
            )

        # 4. Resolve Model Class (Explicit Definition Required)
        if "model_class" not in toml_config:
            raise DorsalError(f"Invalid 'model_config.toml' in '{package_name}': Missing required key 'model_class'.")

        class_name = toml_config["model_class"]
        try:
            model_class = getattr(module, class_name)
        except AttributeError as err:
            raise DorsalError(
                f"Config defines model_class='{class_name}', but it was not exported by module '{module_name}' - {err}"
            ) from err

        # 5. Merge Config
        merged_config = {
            "model_class": model_class,
            "schema_id": toml_config.get("schema_id", "open/generic"),
            "dependencies": toml_config.get("dependencies"),
            "options": toml_config.get("options", {}),
        }

        spec = ModelSpec(**merged_config)

    except Exception as e:
        raise DorsalError(f"Failed to inspect model package '{package_name}': {e}") from e

    # 6. Register
    try:
        register_model(
            annotation_model=spec.model_class,
            schema_id=spec.schema_id,
            validation_model=spec.validation_model,
            dependencies=spec.dependencies,
            options=spec.options,
            overwrite=True,
            scope=scope,
        )
        logger.info(f"Successfully registered model: {spec.model_class.__name__} ({spec.schema_id})")

    except Exception as e:
        raise DorsalConfigError(f"Failed to update {scope} config: {e}") from e
