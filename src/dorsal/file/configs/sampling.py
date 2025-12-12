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

import os
import struct
import hashlib
import logging

logger = logging.getLogger(__name__)


PREDICTABLE_BIN_FILENAME = "predictable.bin"
PREDICTABLE_BIN_SHA256 = "b1e601f5605b411e789a1d309216ef6b01331dbfb969616f05db9cbe4d641e73"
PREDICTABLE_COUNT = 100000


predictable_numbers: list[int] = []


def _calculate_sha256(file_path: str) -> str:
    """Calculates the SHA256 hash of a file."""
    try:
        with open(file_path, "rb") as fp:
            return hashlib.sha256(fp.read()).hexdigest()
    except OSError as err:
        logger.exception("Failed to read file '%s' for SHA256 calculation -  %s", file_path, err)
        raise


def _initialize_predictable_numbers(base_dir: str) -> list[int]:
    """
    Loads, validates, and returns the sequence of predictable numbers from a
    binary .bin file.
    """
    bin_file_path = os.path.join(base_dir, PREDICTABLE_BIN_FILENAME)
    logger.debug("Attempting to load predictable numbers from: %s", bin_file_path)

    if not os.path.exists(bin_file_path):
        raise FileNotFoundError(f"Required data file not found: {bin_file_path}")

    actual_sha256 = _calculate_sha256(bin_file_path)
    if actual_sha256.lower() != PREDICTABLE_BIN_SHA256.lower():
        raise ValueError(
            f"Data file integrity check failed for '{bin_file_path}'. "
            f"Expected SHA256: {PREDICTABLE_BIN_SHA256}, but got: {actual_sha256}"
        )
    logger.debug("Integrity check passed for '%s'.", bin_file_path)

    with open(bin_file_path, "rb") as f:
        packed_data = f.read()

    expected_size_bytes = PREDICTABLE_COUNT * 8
    if len(packed_data) != expected_size_bytes:
        raise ValueError(
            f"Data file has incorrect size. Expected {expected_size_bytes} bytes, but got {len(packed_data)}."
        )

    format_string = f"<{PREDICTABLE_COUNT}Q"  # Q for 64-bit unsigned int; < for little-endian byte order
    predictable_list = list(struct.unpack(format_string, packed_data))

    if len(predictable_list) != PREDICTABLE_COUNT:
        raise ValueError(f"Data file loaded with {len(predictable_list)} numbers, but expected {PREDICTABLE_COUNT}.")

    logger.debug("Successfully loaded %d predictable numbers.", len(predictable_list))
    return predictable_list


try:
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    predictable_numbers = _initialize_predictable_numbers(base_dir=current_script_dir)
except (FileNotFoundError, ValueError, TypeError) as err:
    logger.critical("Failed to initialize predictable numbers: %s", err)
    raise RuntimeError("Critical data for sampling is missing or corrupt.") from err
except Exception:
    logger.exception("An unexpected error occurred during predictable numbers initialization.")
    raise
