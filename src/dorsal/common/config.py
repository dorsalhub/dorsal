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
import logging
import pathlib
import tomllib
import tomlkit
import tomlkit.items
from functools import lru_cache
from typing import Any, Callable, MutableMapping, TypeVar

from dorsal.common import constants

logger = logging.getLogger(__name__)
T = TypeVar("T")
D = TypeVar("D", bound=MutableMapping)


_DEFAULT_CONFIG_STRING = f"""# This config defines default behavior of the dorsal library.
#
# A project-specific config (e.g., 'dorsal.toml' in your project root)
# can be used to override any of these settings.
#
# This file is TOML. See: https://toml.io/
# For help configuring th

# -----------------------------------------------------------------------------
#  Authenticating with DorsalHub.
# -----------------------------------------------------------------------------
[auth]
# Your API key, found in your DorsalHub account settings.
api_key = ""

# The email address associated with your DorsalHub account.
email = ""


# -----------------------------------------------------------------------------
#  Control how the CLI looks
# -----------------------------------------------------------------------------
[ui]
# Choose the visual theme. (e.g., "default", "dark", "light")
theme = "default"


# -----------------------------------------------------------------------------
#  HTML report options
# -----------------------------------------------------------------------------
[report.collection.panels]
# Choose which panels are enabled in reports.
summary_stats = true
collection_overview = true
dynamic_size_histogram = false
duplicates_report = true
file_explorer = true


# -----------------------------------------------------------------------------
#  Annotation Model Pipeline
# -----------------------------------------------------------------------------
# Defines the sequence of models to run on files.
# Each model step is defined as an array item using [[model_pipeline]].
# You can add, remove, or reorder these steps as needed.
#
# A step can have 'dependencies': conditions which determine when it runs.
# -----------------------------------------------------------------------------

# --- Model 1: Core File Annotation (Runs on ALL files) ---
[[model_pipeline]]
annotation_model = ["dorsal.file.annotation_models", "FileCoreAnnotationModel"]
validation_model = ["dorsal.file.validators.base", "FileCoreValidationModelStrict"]
schema_id = "{constants.FILE_BASE_ANNOTATION_SCHEMA}"

# Model-specific options
options = {{ calculate_similarity_hash = true }} # TLSH hash generation

# --- Model 2: MediaInfo Annotation (Runs on media files) ---
[[model_pipeline]]
annotation_model = ["dorsal.file.annotation_models", "MediaInfoAnnotationModel"]
schema_id = "{constants.CORE_MEDIAINFO_ANNOTATION_SCHEMA}"
validation_model = ["dorsal.file.validators.mediainfo", "MediaInfoValidationModel"]

# Dependencies: This model only runs if the file media type matches.
dependencies = [
    {{ type = "media_type", include = ["audio", "image", "video", "application/vnd.rn-realmedia", "application/x-shockwave-flash"], exclude = ["image/svg"] }},
]


# --- Model 3: PDF Annotation (Runs on PDF files) ---
[[model_pipeline]]
annotation_model = ["dorsal.file.annotation_models", "PDFAnnotationModel"]
schema_id = "{constants.CORE_PDF_ANNOTATION_SCHEMA}"
validation_model = ["dorsal.file.validators.pdf", "PDFValidationModel"]

# Dependencies: This model only runs on PDF files.
dependencies = [
    {{ type = "media_type", include = ["application/pdf"] }},
]

# --- Model 5: Ebook Annotation (Runs on Ebook files) ---
[[model_pipeline]]
annotation_model = ["dorsal.file.annotation_models", "EbookAnnotationModel"]
schema_id = "{constants.CORE_EBOOK_ANNOTATION_SCHEMA}"
validation_model = ["dorsal.file.validators.ebook", "EbookValidationModel"]

# Dependencies: This model only runs on EPUB files.
dependencies = [
    {{ type = "media_type", include = ["application/epub+zip"] }},
]

# --- Model 6: Office Document Annotation (Runs on office documents) ---
[[model_pipeline]]
annotation_model = ["dorsal.file.annotation_models", "OfficeDocumentAnnotationModel"]
schema_id = "{constants.CORE_OFFICE_DOCUMENT_ANNOTATION_SCHEMA}"
validation_model = ["dorsal.file.validators.office_document", "OfficeDocumentValidationModel"]

# Dependencies: This model only runs on certain OOXML files.
dependencies = [
    {{ type = "media_type", include = ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.openxmlformats-officedocument.presentationml.presentation" ] }},
]
"""

DEFAULT_CONFIG: dict[str, Any] = tomllib.loads(_DEFAULT_CONFIG_STRING)


def _recursive_merge(base: D, new: MutableMapping) -> D:
    """
    Recursively merges the 'new' dictionary into the 'base' dictionary.

    Note: This function replaces lists, it does not append to them.
    """
    for key, value in new.items():
        if isinstance(value, MutableMapping) and key in base and isinstance(base[key], MutableMapping):
            base[key] = _recursive_merge(base[key], value)
        else:
            base[key] = value
    return base


def find_project_config_path() -> pathlib.Path | None:
    """
    Finds the highest-precedence project-level config file
    """
    global_config_path = get_global_config_path().resolve()
    current_dir = pathlib.Path.cwd()
    root = pathlib.Path(current_dir.root)

    while True:
        for filename in constants.PROJECT_CONFIG_FILENAMES:
            config_file = current_dir / filename
            if config_file.is_file():
                if config_file.resolve() != global_config_path:
                    logger.debug("Found project config at: %s", config_file)
                    return config_file

        subdir_config_file = current_dir / constants.PROJECT_CONFIG_SUBDIR / constants.GLOBAL_CONFIG_FILENAME
        if subdir_config_file.is_file():
            if subdir_config_file.resolve() != global_config_path:
                logger.debug("Found project config at: %s", subdir_config_file)
                return subdir_config_file

        if current_dir == root or current_dir == current_dir.parent:
            break
        current_dir = current_dir.parent

    return None


def get_global_config_path() -> pathlib.Path:
    return pathlib.Path(constants.LOCAL_DORSAL_DIR) / constants.GLOBAL_CONFIG_FILENAME


def _create_default_global_config_if_not_exists() -> None:
    """
    Creates the default global config file from the template string if it doesn't exist.
    """
    global_config_path = get_global_config_path()
    if global_config_path.exists():
        return

    logger.info("No global config found. Creating default at %s", global_config_path)
    try:
        global_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(global_config_path, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_CONFIG_STRING)
    except Exception as e:
        logger.error("Failed to write default global config: %s", e, exc_info=True)


def _load_config_file(path: pathlib.Path) -> dict[str, Any]:
    """
    Safely loads a TOML config file.
    Returns an empty dict if the file doesn't exist or is invalid.
    """
    if not path or not path.is_file():
        return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error("Failed to load config at %s: %s", path, e)
        return {}


def get_project_level_config() -> tuple[dict[str, Any], pathlib.Path | None]:
    """
    Finds and loads the highest-precedence project-level config file.

    It searches from the current directory upwards for a valid config file.

    Returns:
        A tuple containing:
        - A dictionary with the loaded config, or an empty dict if not found/invalid.
        - The Path object of the found config file, or None if not found.
    """
    config_path = find_project_config_path()
    if not config_path:
        return {}, None

    config_data = _load_config_file(config_path)
    return config_data, config_path


@lru_cache(maxsize=1)
def load_config() -> tuple[dict[str, Any], pathlib.Path]:
    """
    Loads configuration by merging project-specific settings over global settings,
    which are all merged over the in-memory defaults.

    Precedence: Project > Global > Defaults

    Returns:
        A tuple containing:
        - The dictionary of the final merged configuration.
        - The path of the highest-precedence configuration file that was loaded
          (project path if it exists, otherwise global path).
    """
    _create_default_global_config_if_not_exists()

    effective_config = copy.deepcopy(DEFAULT_CONFIG)

    global_config_path = get_global_config_path()
    global_config_data = _load_config_file(global_config_path)
    effective_config = _recursive_merge(effective_config, global_config_data)

    effective_path = global_config_path

    project_config_data, project_config_path = get_project_level_config()

    if project_config_path:
        logger.debug("Loading project-specific config from: %s", project_config_path)
        effective_config = _recursive_merge(effective_config, project_config_data)
        effective_path = project_config_path

    return effective_config, effective_path


def set_config_value(section: str, option: str, value: Any, scope: str = "project") -> None:
    """
    Sets a configuration value in the specified scope.

    Args:
        section: The section name (e.g., 'auth').
        option: The option name (e.g., 'api_key').
        value: The value to set.
        scope: The scope to write to ('project' or 'global'). Defaults to 'project'.
    """
    if scope == "global":
        config_path = get_global_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        project_config_path = find_project_config_path()
        if project_config_path:
            config_path = project_config_path
        else:
            config_path = pathlib.Path.cwd() / "dorsal.toml"

    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = tomlkit.load(f)
        except Exception as e:
            logger.error("Failed to parse config %s, creating new one: %s", config_path, e)
            config = tomlkit.document()
    else:
        config = tomlkit.document()

    section_table = config.get(section)

    if not isinstance(section_table, tomlkit.items.Table):
        section_table = tomlkit.table()
        config[section] = section_table

    section_table[option] = value

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(config, f)
        load_config.cache_clear()
    except Exception as e:
        raise OSError(f"Failed to write to config file at {config_path}: {e}") from e


def remove_config_value(section: str, option: str, scope: str = "project") -> bool:
    """
    Removes a configuration value from the specified scope.

    Args:
        section: The section name (e.g., 'auth').
        option: The option name (e.g., 'api_key').
        scope: The scope to modify ('project' or 'global'). Defaults to 'project'.

    Returns:
        True if the value was successfully removed, False otherwise.
    """
    if scope == "global":
        config_path = get_global_config_path()
    else:
        project_config_path = find_project_config_path()
        if not project_config_path:
            return False
        config_path = project_config_path

    if not config_path or not config_path.is_file():
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = tomlkit.load(f)
    except Exception as e:
        logger.error("Failed to read config %s for removal: %s", config_path, e)
        return False

    section_table = config.get(section)

    if not isinstance(section_table, tomlkit.items.Table):
        return False

    if option in section_table:
        del section_table[option]
        if not section_table:
            del config[section]

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                tomlkit.dump(config, f)
            load_config.cache_clear()
            return True
        except Exception as e:
            raise OSError(f"Failed to write to config file at {config_path}: {e}") from e

    return False


def resolve_setting(
    *,
    setting_name: str,
    explicit_value: T | None,
    env_getter: Callable[[], T | None],
    config_getter: Callable[[], T | None],
    default_value: T,
) -> T:
    """
    Resolves a setting's value by checking sources in a fixed order of precedence.

    Precedence Order:
    1. Explicit value (if not None)
    2. Environment variable (via env_getter)
    3. Configuration file (via config_getter)
    4. Default value
    """
    if explicit_value is not None:
        logger.debug("Using explicit argument for '%s': %s", setting_name, explicit_value)
        return explicit_value

    from_env = env_getter()
    if from_env is not None:
        logger.debug("Using environment variable for '%s': %s", setting_name, from_env)
        return from_env

    from_config = config_getter()
    if from_config is not None:
        logger.debug("Using config file for '%s': %s", setting_name, from_config)
        return from_config

    logger.debug(
        "No specific setting found for '%s'. Using default: %s",
        setting_name,
        default_value,
    )
    return default_value


def get_collection_report_panel_config() -> dict[str, bool]:
    """
    Loads the merged configuration and returns the specific panel settings for the collection report.

    The returned config is a result of merging defaults, global, and project
    settings.

    Returns:
        A dictionary where keys are panel names and values are booleans
        indicating if they should be enabled.
    """
    merged_config, _ = load_config()

    return merged_config.get("report", {}).get("collection", {}).get("panels", {})


def get_writable_toml_doc(scope: str) -> tuple[tomlkit.TOMLDocument, pathlib.Path]:
    """
    Retrieves a generic writable TOML document based on scope.
    """
    if scope == "project":
        target_path = find_project_config_path()
        if not target_path:
            target_path = pathlib.Path.cwd() / "dorsal.toml"
    elif scope == "global":
        target_path = get_global_config_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        raise ValueError("Invalid scope. Must be 'project' or 'global'.")

    if target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return tomlkit.load(f), target_path
        except Exception as err:
            logger.error(f"Failed to read config at {target_path}: {err}")
            return tomlkit.document(), target_path

    return tomlkit.document(), target_path


def save_toml_doc(doc: tomlkit.TOMLDocument, path: pathlib.Path) -> None:
    """
    Writes a TOML document to disk and clears the config cache.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        load_config.cache_clear()
    except Exception as err:
        raise OSError(f"Failed to write config to {path}: {err}") from err
