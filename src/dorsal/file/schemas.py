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

import json
import logging
import os
import sys
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, OPEN_VALIDATION_SCHEMAS_VER

logger = logging.getLogger(__name__)

OPEN_SCHEMA_PREFIX = "open/"
OATS_SCHEMA_PREFIX = "oats/"

SCHEMA_ALIASES: dict[str, str] = {
    "arxiv": "dorsal/arxiv",
}

OPEN_SCHEMA_NAME_MAP = {
    "entity-extraction": "entity-extraction.json",
    "generic": "generic.json",
    "llm-output": "llm-output.json",
    "classification": "classification.json",
    "document-extraction": "document-extraction.json",
    "object-detection": "object-detection.json",
    "embedding": "embedding.json",
    "audio-transcription": "audio-transcription.json",
    "geolocation": "geolocation.json",
    "regression": "regression.json",
    "ranking": "ranking.json",
    "temporal-segmentation": "temporal-segmentation.json",
}

OpenSchemaName = Literal[
    "audio-transcription",
    "classification",
    "document-extraction",
    "embedding",
    "entity-extraction",
    "generic",
    "geolocation",
    "llm-output",
    "object-detection",
    "ranking",
    "regression",
    "temporal-segmentation",
]


def schema_version_of(schema: dict) -> str | None:
    """Return the version a schema declares: `x-version` (OATS 0.8.0 on) or `version` (earlier releases)."""
    version = schema.get("x-version", schema.get("version"))
    return version if isinstance(version, str) else None


@lru_cache(maxsize=128)
def _load_schema_from_package(filename: str, version: str) -> dict:
    """
    Load an open schema from the override directory, if one is set, or from the `oatschema` package.

    When `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` is set, `<dir>/<filename>` is loaded instead of the `oatschema`
    copy for every version, and a version mismatch is only logged. Otherwise the schema must declare the
    requested version.
    """
    override_dir = os.getenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR)

    if override_dir:
        schema_path = Path(override_dir) / filename
        source_desc = str(schema_path)
        try:
            schema_text = schema_path.read_text(encoding="utf-8")
            logger.info(f"Dorsal override active: Loading schema '{filename}' from local directory {override_dir}")
        except FileNotFoundError as err:
            raise FileNotFoundError(f"Override schema not found at {schema_path}") from err
    else:
        import oatschema

        name = filename.removesuffix(".json")
        source_desc = f"oatschema {oatschema.__version__}, schema version {version}"
        try:
            schema_text = oatschema.get_schema(cast("oatschema.SchemaName", name), version, mode="json")
        except LookupError as err:
            raise FileNotFoundError(f"Could not load schema '{name}' for version '{version}': {err}") from err
        except ValueError as err:
            raise ValueError(f"Unknown schema name: '{name}'. {err}") from err

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse JSON for schema '{filename}' from {source_desc}: {err}") from err

    if not isinstance(schema, dict):
        raise RuntimeError(f"Schema '{filename}' from {source_desc} is not a JSON object.")

    file_version = schema_version_of(schema)
    if file_version != version:
        if override_dir:
            logger.warning(
                f"Schema version mismatch for '{filename}'. Library requested '{version}', "
                f"but loaded '{file_version}' (from {source_desc}). Assuming intentional override."
            )
        else:
            raise RuntimeError(
                f"Critical Package Integrity Error: Schema '{filename}' claims to be version "
                f"('{file_version}') but does not match the requested version ('{version}'), "
                f"loaded from {source_desc}. This indicates a corrupted installation."
            )

    return schema


def get_open_schema(name: OpenSchemaName, version: str = OPEN_VALIDATION_SCHEMAS_VER) -> dict:
    """
    Retrieves the raw JSON dictionary for a built-in Dorsal 'open/' validation schema.

    This function provides a guaranteed, strictly-typed way to access Dorsal's
    standardized schemas (like 'classification' or 'entity-extraction') for local
    validation or data generation tasks.

    Schemas come from the `oatschema` package. When `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` is set,
    `<dir>/<name>.json` is loaded instead, for every version.

    Args:
        name: The short name of the open schema (e.g., "generic", "llm-output").
              Provides autocomplete support in modern IDEs.
        version: The exact schema version to load (e.g. "0.4.0"), from the versions the installed
                 `oatschema` package provides. Defaults to OPEN_VALIDATION_SCHEMAS_VER, the version
                 this release of the Dorsal library validates against.

    Returns:
        dict: The fully resolved JSON schema.

    Raises:
        ValueError: If the provided `name` is not a recognized Open Validation Schema.
        FileNotFoundError: If the requested `version` is not available, or does not contain `name`.
        RuntimeError: If the schema file is corrupted or fails its version integrity check.
    """
    name = cast(OpenSchemaName, open_schema_name(resolve_schema_id(name)) or name)
    schema_filename = OPEN_SCHEMA_NAME_MAP.get(name)

    if schema_filename is None:
        raise ValueError(f"Unknown schema name: '{name}'. Valid schemas are: {', '.join(OPEN_SCHEMA_NAME_MAP.keys())}")

    return _load_schema_from_package(schema_filename, version)


def open_schema_versions(name: OpenSchemaName) -> list[str]:
    """Return the schema versions, oldest first, in which the installed `oatschema` package provides `name`."""
    import oatschema

    name = cast(OpenSchemaName, open_schema_name(resolve_schema_id(name)) or name)

    versions = []
    for version in oatschema.available_versions():
        try:
            oatschema.get_schema(cast("oatschema.SchemaName", name), version, mode="json")
        except (LookupError, ValueError):
            continue
        versions.append(version)
    return versions


def normalize_schema_id(schema_id: str | None) -> str | None:
    """
    Return the dataset id for `schema_id`.

    An OATS schema name, bare (`generic`) or with the `oats/` prefix (`oats/generic`), becomes its dataset id
    (`open/generic`). An official alias in SCHEMA_ALIASES (`arxiv`) becomes the id it names (`dorsal/arxiv`).
    Other ids are returned unchanged.
    """
    if not schema_id or not isinstance(schema_id, str):
        return schema_id

    name = open_schema_name(schema_id)
    if name is not None:
        return f"{OPEN_SCHEMA_PREFIX}{name}"

    return SCHEMA_ALIASES.get(schema_id, schema_id)


def open_schema_name(schema_id: str | None) -> OpenSchemaName | None:
    """Return the OATS schema name for `schema_id` (`generic`, `oats/generic` or `open/generic`), or None."""
    if not isinstance(schema_id, str):
        return None
    for prefix in (OATS_SCHEMA_PREFIX, OPEN_SCHEMA_PREFIX):
        if schema_id.startswith(prefix):
            schema_id = schema_id.removeprefix(prefix)
            break
    return cast(OpenSchemaName, schema_id) if schema_id in OPEN_SCHEMA_NAME_MAP else None


def hub_record_schema_version(schema_id: str | None, schema_version: str | None) -> str | None:
    """Return the schema version of a record from DorsalHub, reading an unversioned OATS record as 0.5.0."""
    from dorsal.common.constants import UNVERSIONED_HUB_RECORD_SCHEMA_VER

    if schema_version is None and open_schema_name(schema_id) is not None:
        return UNVERSIONED_HUB_RECORD_SCHEMA_VER
    return schema_version


def is_deprecated_schema_id(schema_id: object) -> bool:
    """Return True if `schema_id` names an OATS schema with the deprecated `open/` prefix."""
    return (
        isinstance(schema_id, str)
        and schema_id.startswith(OPEN_SCHEMA_PREFIX)
        and schema_id.removeprefix(OPEN_SCHEMA_PREFIX) in OPEN_SCHEMA_NAME_MAP
    )


def deprecated_schema_id_message(schema_id: str) -> str:
    """Return the warning shown when `schema_id` uses the deprecated `open/` prefix."""
    name = schema_id.removeprefix(OPEN_SCHEMA_PREFIX)
    return (
        f"The schema id '{schema_id}' is deprecated and will stop working in a future release of Dorsal: use '{name}'."
    )


def _called_from_dorsal(depth: int) -> bool:
    try:
        frame = sys._getframe(depth + 1)
    except ValueError:
        return False
    module = frame.f_globals.get("__name__", "")
    return isinstance(module, str) and (module == "dorsal" or module.startswith("dorsal."))


def resolve_schema_id(schema_id: str, *, depth: int = 1) -> str:
    """
    Return the dataset id for a schema id given to a public function, warning if it uses the `open/` prefix.

    `generic`, `oats/generic` and the deprecated `open/generic` all resolve to `open/generic`, and an official
    alias such as `arxiv` resolves to `dorsal/arxiv`, as `normalize_schema_id` does. The `DeprecationWarning` is
    emitted only when the public function was called from outside Dorsal. `depth` is how many frames the public
    function is above this call.
    """
    if is_deprecated_schema_id(schema_id) and not _called_from_dorsal(depth + 1):
        warnings.warn(deprecated_schema_id_message(schema_id), DeprecationWarning, stacklevel=depth + 2)
    return normalize_schema_id(schema_id) or schema_id


__all__ = [
    "get_open_schema",
    "OpenSchemaName",
    "OATS_SCHEMA_PREFIX",
    "OPEN_SCHEMA_PREFIX",
    "SCHEMA_ALIASES",
    "deprecated_schema_id_message",
    "hub_record_schema_version",
    "is_deprecated_schema_id",
    "normalize_schema_id",
    "open_schema_name",
    "resolve_schema_id",
    "schema_version_of",
]
