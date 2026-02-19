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
import importlib.resources
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

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
]


@lru_cache(maxsize=128)
def _load_schema_from_package(filename: str, version: str) -> dict:
    """
    Internal loader that resolves the file path (or override) and validates integrity.

    This function handles two distinct loading paths:
    1. Local Override: If the ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR environment variable
       is set, it attempts to load the schema directly from that local directory.
    2. Bundled Package: Otherwise, it uses importlib.resources to safely extract the
       schema from the bundled `.whl` or package installation.

    It also performs a critical package integrity check to ensure the loaded JSON
    claims to be the exact version that was requested.
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
        try:
            ref = importlib.resources.files("dorsal.schemas") / "open" / version / filename
            schema_text = ref.read_text(encoding="utf-8")
            source_desc = f"bundled dorsal.schemas.open.{version}"
        except OSError as err:
            raise FileNotFoundError(
                f"Could not load bundled schema '{filename}' for version '{version}'. "
                f"Ensure version '{version}' is supported by this release of the Dorsal library."
            ) from err

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse JSON for schema '{filename}' from {source_desc}: {err}") from err

    file_version = schema.get("version")
    if file_version != version:
        if override_dir:
            logger.warning(
                f"Schema version mismatch for '{filename}'. Library requested '{version}', "
                f"but loaded '{file_version}' (from {source_desc}). Assuming intentional override."
            )
        else:
            raise RuntimeError(
                f"Critical Package Integrity Error: Bundled schema '{filename}' claims to be version "
                f"('{file_version}') but does not match the requested version directory ('{version}'). "
                "This indicates a corrupted installation or broken build artifact."
            )

    return schema


def get_open_schema(name: OpenSchemaName, version: str = OPEN_VALIDATION_SCHEMAS_VER) -> dict:
    """
    Retrieves the raw JSON dictionary for a built-in Dorsal 'open/' validation schema.

    This function provides a guaranteed, strictly-typed way to access Dorsal's
    standardized schemas (like 'classification' or 'entity-extraction') for local
    validation or data generation tasks.

    Args:
        name: The short name of the open schema (e.g., "generic", "llm-output").
              Provides autocomplete support in modern IDEs.
        version: The specific version of the schema to load. By default, this is
                 safely pinned to the version (OPEN_VALIDATION_SCHEMAS_VER) tested
                 and bundled with this specific release of the Dorsal library.

    Returns:
        dict: The fully resolved JSON schema.

    Raises:
        ValueError: If the provided `name` is not a recognized Open Validation Schema.
        FileNotFoundError: If the requested `version` is not bundled with the library.
        RuntimeError: If the schema file is corrupted or fails its version integrity check.
    """
    schema_filename = OPEN_SCHEMA_NAME_MAP.get(name)

    if schema_filename is None:
        raise ValueError(f"Unknown schema name: '{name}'. Valid schemas are: {', '.join(OPEN_SCHEMA_NAME_MAP.keys())}")

    return _load_schema_from_package(schema_filename, version)


__all__ = [
    "get_open_schema",
    "OpenSchemaName",
]
