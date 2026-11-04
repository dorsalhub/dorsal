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
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, IO

from dorsal.common.exceptions import DorsalError
from dorsal.file.schemas import open_schema_name, resolve_schema_id
from pydantic import BaseModel

if TYPE_CHECKING:
    from oatschema_adapters import Adapter

logger = logging.getLogger(__name__)

_registration_lock = threading.Lock()
_arxiv_adapters_registered = False


def _register_arxiv_adapters() -> None:
    global _arxiv_adapters_registered
    if _arxiv_adapters_registered:
        return
    with _registration_lock:
        if not _arxiv_adapters_registered:
            from dorsal.adapters.arxiv import register_arxiv_adapters

            register_arxiv_adapters()
            _arxiv_adapters_registered = True


def _adapter_schema(schema_id: str) -> str:
    return open_schema_name(schema_id) or schema_id


def _get_adapter(schema_id: str, target_format: str) -> "Adapter":
    from oatschema_adapters import get_adapter

    _register_arxiv_adapters()
    return get_adapter(_adapter_schema(schema_id), target_format)


def _with_schema_version(schema_id: str, schema_version: str | None, options: dict[str, Any]) -> dict[str, Any]:
    if open_schema_name(schema_id) is None:
        return options if schema_version is None else {**options, "schema_version": schema_version}
    from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER

    return {**options, "schema_version": schema_version or OPEN_VALIDATION_SCHEMAS_VER}


def get_format_extension(schema_id: str, target_format: str) -> str:
    """Return the file extension, without a leading dot, for exporting `schema_id` records to `target_format`."""
    schema_id = resolve_schema_id(schema_id)
    try:
        return _get_adapter(schema_id, target_format).extension
    except Exception as err:
        logger.warning(
            "Adapter not found for schema %s, format %s. Defaulting to %s. Full error: %s",
            schema_id,
            target_format,
            target_format,
            err,
        )
        return target_format


def export_record(
    record: dict[str, Any] | BaseModel,
    schema_id: str,
    target_format: str,
    *,
    schema_version: str | None = None,
    **options: Any,
) -> str:
    """
    Export a record to a format such as `"html"`, `"md"` or `"srt"`.

    `schema_id` is an OATS schema name such as `"document-extraction"`, or another schema with adapters, such as
    `"dorsal/arxiv"`. OATS records are validated at `schema_version` (default: OPEN_VALIDATION_SCHEMAS_VER) unless
    `validate=False` is passed. Other keyword arguments are the format's options; an unknown option raises.

    Raises:
        DorsalError: The format is not supported, an option is invalid, or the record fails validation.
    """
    schema_id = resolve_schema_id(schema_id)
    if isinstance(record, BaseModel):
        record_dict = record.model_dump(mode="json", by_alias=True)
    else:
        record_dict = record

    logger.debug(f"Attempting to export '{schema_id}' to '{target_format}'.")

    try:
        adapter = _get_adapter(schema_id, target_format)
        return adapter.export(record_dict, **_with_schema_version(schema_id, schema_version, options))
    except DorsalError:
        raise
    except Exception as e:
        logger.error(f"Adapter export failed: {e}")
        raise DorsalError(f"Failed to export record to {target_format}: {e}") from e


def export_record_to_file(
    record: dict[str, Any] | BaseModel,
    output_path: Path | str,
    schema_id: str,
    target_format: str | None = None,
    *,
    schema_version: str | None = None,
    **options: Any,
) -> str:
    """Export a record as `export_record` does, write it to `output_path`, and return the exported text.

    The format is inferred from the file extension when `target_format` is not given.
    """
    schema_id = resolve_schema_id(schema_id)
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

    exported_text = export_record(
        record, schema_id=schema_id, target_format=resolved_format, schema_version=schema_version, **options
    )

    try:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as fp:
            fp.write(exported_text)
    except Exception as e:
        logger.error(f"Failed to write exported text to file {path_obj}: {e}")
        raise DorsalError(f"Failed to write exported text to file {path_obj}: {e}") from e

    return exported_text


def parse_file(
    content: str | bytes | IO[Any],
    schema_id: str,
    source_format: str,
    *,
    schema_version: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """
    Parse content in `source_format` into a `schema_id` record.

    OATS records are validated at `schema_version` (default: OPEN_VALIDATION_SCHEMAS_VER) unless `validate=False`
    is passed. Other keyword arguments are the format's options; an unknown option raises.

    Raises:
        DorsalError: The format is not supported, an option is invalid, or parsing or validation fails.
    """
    schema_id = resolve_schema_id(schema_id)
    logger.debug(f"Attempting to parse '{source_format}' into '{schema_id}'.")

    try:
        adapter = _get_adapter(schema_id, source_format)
        parse_options = _with_schema_version(schema_id, schema_version, options)
        if isinstance(content, (str, bytes)):
            return adapter.parse(content, **parse_options)
        return adapter.parse_file(content, **parse_options)
    except DorsalError:
        raise
    except Exception as e:
        logger.error(f"Adapter parse failed: {e}")
        raise DorsalError(f"Failed to parse record from {source_format}: {e}") from e


def parse_file_from_path(
    file_path: Path | str,
    schema_id: str,
    source_format: str | None = None,
    *,
    schema_version: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """
    Read a file and parse it into a `schema_id` record, as `parse_file` does.

    The format is inferred from the file extension when `source_format` is not given.
    """
    schema_id = resolve_schema_id(schema_id)
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
            return parse_file(
                content=fp,
                schema_id=schema_id,
                source_format=resolved_format,
                schema_version=schema_version,
                **options,
            )
    except DorsalError:
        raise
    except Exception as e:
        logger.error(f"Failed to read or parse file {path_obj}: {e}")
        raise DorsalError(f"Failed to read or parse file {path_obj}: {e}") from e


def get_supported_formats(schema_id: str) -> list[tuple[str, str]]:
    """Returns a list of (format_name, description) for all supported formats of a given schema."""
    from oatschema_adapters import list_formats

    schema_id = resolve_schema_id(schema_id)
    _register_arxiv_adapters()
    return list_formats(_adapter_schema(schema_id))


def get_adapter_help(target: str, ui_context: dict) -> Any | None:
    pass
