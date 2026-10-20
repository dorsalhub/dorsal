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
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, OPEN_VALIDATION_SCHEMAS_VER

logger = logging.getLogger(__name__)

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
    "entity-extraction",
    "generic",
    "llm-output",
    "classification",
    "document-extraction",
    "object-detection",
    "embedding",
    "audio-transcription",
    "geolocation",
    "regression",
    "ranking",
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
    schema_filename = OPEN_SCHEMA_NAME_MAP.get(name)

    if schema_filename is None:
        raise ValueError(f"Unknown schema name: '{name}'. Valid schemas are: {', '.join(OPEN_SCHEMA_NAME_MAP.keys())}")

    return _load_schema_from_package(schema_filename, version)


def open_schema_versions(name: OpenSchemaName) -> list[str]:
    """Return the schema versions, oldest first, in which the installed `oatschema` package provides `name`."""
    import oatschema

    versions = []
    for version in oatschema.available_versions():
        try:
            oatschema.get_schema(cast("oatschema.SchemaName", name), version, mode="json")
        except (LookupError, ValueError):
            continue
        versions.append(version)
    return versions


def normalize_schema_id(schema_id: str | None) -> str | None:
    if not schema_id:
        return schema_id

    if schema_id in OPEN_SCHEMA_NAME_MAP:
        return f"open/{schema_id}"

    return schema_id


__all__ = [
    "get_open_schema",
    "OpenSchemaName",
    "normalize_schema_id",
    "schema_version_of",
]
