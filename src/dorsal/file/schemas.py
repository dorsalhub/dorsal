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

import json
import logging
import importlib.resources
import os
from pathlib import Path
from functools import lru_cache
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


@lru_cache(maxsize=None)
def _load_schema_from_package(filename: str) -> dict:
    """
    Loads a schema JSON.

    Priority:
    1. Local Override: If DORSAL_OPEN_SCHEMAS_DIR is set, load from that path.
       If overriding schemas, this value should be a local directory containing the JSON files.
    2. Bundled schemas: Load the schema in `dorsal/schemas/open/{OVS_VERSION}`
    """
    override_dir = os.getenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR)

    schema_text: str
    source_desc: str

    if override_dir:
        schema_path = Path(override_dir) / filename
        source_desc = str(schema_path)
        logger.debug("Loading OVS schema '%s' from override: %s", filename, schema_path)
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_text = f.read()
        except FileNotFoundError as err:
            raise ValueError(f"OVS Schema '{filename}' not found in override dir: {override_dir}") from err
        except Exception as err:
            raise RuntimeError(f"Failed to load override schema '{filename}': {err}") from err
    else:
        try:
            resource_container = importlib.resources.files("dorsal.schemas.open")
            target_path = f"{OPEN_VALIDATION_SCHEMAS_VER}/{filename}"
            resource = resource_container.joinpath(target_path)

            source_desc = f"bundled:dorsal.schemas.open/{target_path}"

            if not resource.is_file():
                raise FileNotFoundError(f"Schema file missing in bundle at {OPEN_VALIDATION_SCHEMAS_VER}/{filename}")

            schema_text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError) as err:
            raise RuntimeError(
                f"Critical Package Integrity Error: Bundled schema '{filename}' for Open Validation Schemas version "
                f"('{OPEN_VALIDATION_SCHEMAS_VER}') is missing."
                "This indicates a corrupted installation or broken build artifact."
            ) from err
        except Exception as err:
            raise RuntimeError(f"Failed to load bundled schema '{filename}': {err}") from err

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as err:
        raise ValueError(f"Schema '{filename}' (from {source_desc}) contains invalid JSON.") from err

    file_version = schema.get("version")
    if file_version != OPEN_VALIDATION_SCHEMAS_VER:
        if override_dir:
            logger.debug(
                "Schema version mismatch for '%s'. Library expects %s, loaded %s (from %s). "
                "Assuming intentional override.",
                filename,
                OPEN_VALIDATION_SCHEMAS_VER,
                file_version,
                source_desc,
            )
        else:
            raise RuntimeError(
                f"Critical Package Integrity Error: Bundled schema '{filename}' for Open Validation Schemas version "
                f"('{file_version}') does not match library expectation ('{OPEN_VALIDATION_SCHEMAS_VER}')."
                "This indicates a corrupted installation or broken build artifact."
            )
    return schema


def get_open_schema(name: OpenSchemaName) -> dict:
    """
    Loads a built-in Dorsal 'open/' validation schema by its short name.

    Args:
        name: The short name of the open schema (e.g., "generic", "llm-output").
              Provides autocompletion in supported editors.

    Returns:
        The JSON schema as a Python dictionary.

    Raises:
        ValueError: If the name is not a valid, known schema.
    """
    schema_filename = OPEN_SCHEMA_NAME_MAP.get(name)

    if schema_filename is None:
        raise ValueError(f"Unknown schema name: '{name}'.")

    return _load_schema_from_package(schema_filename)


__all__ = [
    "get_open_schema",
    "OpenSchemaName",
]
