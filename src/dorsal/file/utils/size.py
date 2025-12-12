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
import os
import re
from typing import Any

from pydantic import BaseModel

from dorsal.common.literals import KB, MB, GB, TB, PB, KiB, MiB, GiB, TiB, PiB

logger = logging.getLogger(__name__)

FILESIZE_UNIT_DP_CONFIG = {"B": 0, "KiB": 0, "MiB": 0, "GiB": 2, "TiB": 2, "PiB": 2}

FILESIZE_ALIAS_MAPPING = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": KB,
    "k": KB,
    "kilobyte": KB,
    "kilobytes": KB,
    "mb": MB,
    "m": MB,
    "megabyte": MB,
    "megabytes": MB,
    "gb": GB,
    "g": GB,
    "gigabyte": GB,
    "gigabytes": GB,
    "t": TB,
    "tb": TB,
    "terabyte": TB,
    "terabytes": TB,
    "kib": KiB,
    "kibi": KiB,
    "kibibyte": KiB,
    "kibibytes": KiB,
    "mib": MiB,
    "mibi": MiB,
    "mebibyte": MiB,
    "mebibytes": MiB,
    "gib": GiB,
    "gibi": GiB,
    "gibibyte": GiB,
    "gibibytes": GiB,
    "tib": TiB,
    "tibi": TiB,
    "tibibyte": TiB,
    "tibibytes": TiB,
}


def get_filesize(file_path: str) -> int:
    try:
        return os.path.getsize(file_path)
    except (IOError, PermissionError) as err:
        logger.error("Could not access file at path '%s': %s", file_path, err)
        raise


def human_filesize(filesize: int | float) -> str:
    """Return a file size in a human readable form:

    - To the nearest MiB, GiB, TiB etc.

    In the default config, GiB and higher show 2 decimal places.

    E.g.
        - 22 -> '22 B'
        - 2_233 -> '2 KiB'
        - 223_344 -> '218 KiB'
        - 22_334_455 -> '21 MiB'
        - 2_233_445_566 -> '2.08 GiB'
        - 22_334_455_667_788 -> '20.31 TiB'
        - 2_233_445_566_778_899_001_122 -> '1983698.15 PiB'

    """
    for unit in FILESIZE_UNIT_DP_CONFIG:
        if filesize < 1024.0 or unit == "PiB":
            break
        filesize /= 1024.0
    dp = FILESIZE_UNIT_DP_CONFIG[unit]
    return f"{filesize:.{dp}f} {unit}"


RX_FILESIZE = re.compile(r"^\s*(\d*\.?\d+)\s*([a-zA-Z]+)\s*$")


def parse_filesize(size_str: str) -> int:
    """Parses a human-readable size string (e.g., "10MB", "2.5 GiB") into bytes."""
    size_str = size_str.strip()
    m = RX_FILESIZE.match(size_str)
    if not m:
        try:
            return int(size_str)
        except ValueError:
            logger.debug("Cannot cast %s to integer", size_str)
        logger.warning("Cannot parse file size: Invalid size format: %s", size_str)
        raise ValueError(f"Invalid size format: '{size_str}'")

    value_str, unit = m.groups()
    value = float(value_str)
    unit = unit.lower()

    if unit not in FILESIZE_ALIAS_MAPPING:
        raise ValueError(f"Unknown size unit: '{unit}' in '{size_str}'")

    return int(value * FILESIZE_ALIAS_MAPPING[unit])


def check_record_size(record: dict[str, Any] | BaseModel) -> int:
    """Returns the size of the record in UTF-8 bytes."""
    if isinstance(record, BaseModel):
        data = record.model_dump(mode="json")
    else:
        data = record

    return len(json.dumps(data, separators=(",", ":"), default=str).encode("utf-8"))
