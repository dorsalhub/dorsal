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
import json
from pathlib import Path
from typing import Any, IO

from dorsal.common.exceptions import DorsalError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    from dorsal_adapters.registry import get_adapter, list_formats

    _ADAPTERS_AVAILABLE = True
except ImportError:
    _ADAPTERS_AVAILABLE = False


def _require_adapters() -> None:
    if not _ADAPTERS_AVAILABLE:
        raise DorsalError("Please pip install dorsalhub-adapters to enable exports.")


def get_format_extension(schema_id: str, target_format: str) -> str:
    """Retrieves the correct file extension for a specific format adapter."""
    _require_adapters()
    try:
        from dorsal_adapters.registry import get_adapter

        adapter = get_adapter(schema_id, target_format)
        return adapter.extension
    except Exception as err:
        logger.warning(
            "Adapter not found for schema %s, format %s. Defaulting to %s. Full error: %s",
            schema_id,
            target_format,
            target_format,
            err,
        )
        return target_format


def export_record(record: dict[str, Any] | BaseModel, schema_id: str, target_format: str, **kwargs: Any) -> str:
    """Exports a validated JSON record to a standard format using Dorsal Adapters."""
    _require_adapters()

    if isinstance(record, BaseModel):
        record_dict = record.model_dump(mode="json", by_alias=True)
    else:
        record_dict = record

    logger.debug(f"Attempting to export '{schema_id}' to '{target_format}'.")

    try:
        # Fetch the adapter and export
        adapter = get_adapter(schema_id, target_format)
        return adapter.export(record_dict, **kwargs)
    except Exception as e:
        logger.error(f"Adapter export failed: {e}")
        raise DorsalError(f"Failed to export record to {target_format}: {e}") from e


def export_record_to_file(
    record: dict[str, Any] | BaseModel,
    output_path: Path | str,
    schema_id: str,
    target_format: str | None = None,
    **kwargs: Any,
) -> str:
    """Exports a validated JSON record and saves it directly to a file path."""
    _require_adapters()

    path_obj = Path(output_path)

    resolved_format = target_format
    if not resolved_format:
        suffix = path_obj.suffix.lstrip(".")
        if not suffix:
            raise DorsalError(
                f"Could not infer target format from file extension for '{path_obj.name}'. "
                "Please provide 'target_format' explicitly."
            )
        resolved_format = suffix

    logger.debug(f"Attempting to export '{schema_id}' to file '{path_obj.name}' as '{resolved_format}'.")

    exported_text = export_record(record, schema_id=schema_id, target_format=resolved_format, **kwargs)

    try:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as fp:
            fp.write(exported_text)
    except Exception as e:
        logger.error(f"Failed to write exported text to file {path_obj}: {e}")
        raise DorsalError(f"Failed to write exported text to file {path_obj}: {e}") from e

    return exported_text


def parse_file(content: str | bytes | IO[Any], schema_id: str, source_format: str, **kwargs: Any) -> dict[str, Any]:
    """Parses a file-like object or string into a validated JSON record using Dorsal Adapters."""
    _require_adapters()

    logger.debug(f"Attempting to parse '{source_format}' into '{schema_id}'.")

    try:
        adapter = get_adapter(schema_id, source_format)
        if isinstance(content, (str, bytes)):
            return adapter.parse(content, **kwargs)
        return adapter.parse_file(content, **kwargs)

    except Exception as e:
        logger.error(f"Adapter parse failed: {e}")
        raise DorsalError(f"Failed to parse record from {source_format}: {e}") from e


def parse_file_from_path(
    file_path: Path | str,
    schema_id: str,
    source_format: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Reads a file from a path and parses it into a validated JSON record.
    Automatically infers the format from the file extension if `source_format` is not provided.
    """
    _require_adapters()

    path_obj = Path(file_path)
    if not path_obj.is_file():
        raise DorsalError(f"Provided path is not a valid file or does not exist: {path_obj}")

    resolved_format = source_format
    if not resolved_format:
        suffix = path_obj.suffix.lstrip(".")
        if not suffix:
            raise DorsalError(
                f"Could not infer source format from file extension for '{path_obj.name}'. "
                "Please provide 'source_format' explicitly."
            )
        resolved_format = suffix

    logger.debug(f"Attempting to parse file '{path_obj.name}' as '{resolved_format}' into '{schema_id}'.")

    try:
        with open(path_obj, "r", encoding="utf-8") as fp:
            return parse_file(content=fp, schema_id=schema_id, source_format=resolved_format, **kwargs)
    except DorsalError:
        raise
    except Exception as e:
        logger.error(f"Failed to read or parse file {path_obj}: {e}")
        raise DorsalError(f"Failed to read or parse file {path_obj}: {e}") from e


def get_supported_formats(schema_id: str) -> list[tuple[str, str]]:
    """Returns a list of (format_name, description) for all supported formats of a given schema."""
    _require_adapters()

    try:
        from dorsal_adapters.registry import ALIAS_MAPPING, list_formats

        resolved_schema_id = ALIAS_MAPPING.get(schema_id, schema_id)
        return list_formats(resolved_schema_id)
    except ImportError:
        return list_formats(schema_id)
