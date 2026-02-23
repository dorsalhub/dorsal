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
from typing import Any, Union

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


def export_record(record: Union[dict[str, Any], BaseModel], schema_id: str, target_format: str) -> str:
    """Exports a validated JSON record to a standard format using Dorsal Adapters."""
    _require_adapters()

    # Normalize Pydantic models to dicts if necessary
    if isinstance(record, BaseModel):
        record_dict = record.model_dump(mode="json", by_alias=True)
    else:
        record_dict = record

    logger.debug(f"Attempting to export '{schema_id}' to '{target_format}'.")

    try:
        # Fetch the adapter and export
        adapter = get_adapter(schema_id, target_format)
        return adapter.export(record_dict)
    except Exception as e:
        logger.error(f"Adapter export failed: {e}")
        raise DorsalError(f"Failed to export record to {target_format}: {e}") from e


def get_supported_formats(schema_id: str) -> list[tuple[str, str]]:
    """Returns a list of (format_name, description) for all supported formats of a given schema."""
    _require_adapters()

    try:
        from dorsal_adapters.registry import ALIAS_MAPPING, list_formats

        resolved_schema_id = ALIAS_MAPPING.get(schema_id, schema_id)
        return list_formats(resolved_schema_id)
    except ImportError:
        return list_formats(schema_id)
