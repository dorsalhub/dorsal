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

import hashlib
import logging
import os
from typing import cast

from dorsal.common.exceptions import (
    QuickHashConfigurationError,
    QuickHasherError,
    QuickHashFileInstabilityError,
    QuickHashFileSizeError,
)
from dorsal.file.configs.sampling import _calculate_sha256
from dorsal.file.utils.file_hasher import FileHasher
from dorsal.file.utils.quick_hasher import QuickHasher
from dorsal.file.utils.size import get_filesize, human_filesize as human_filesize

logger = logging.getLogger(__name__)

FILE_HASHER = FileHasher()
QUICK_HASHER = QuickHasher()


def get_quick_hash(file_path: str, fallback_to_sha256: bool = False, file_size: int | None = None) -> str | None:
    """Get the quick hash of a file.

    When `fallback_to_sha256` is True, when QuickHasher fails (e.g. the file is too small)
        a SHA-256 hash is calculated and returned in its place.
    """
    quick_hash: str | None = None
    try:
        if file_size is None:
            file_size = get_filesize(file_path)
        quick_hash = QUICK_HASHER.hash(file_path=file_path, file_size=file_size)
        if quick_hash is None and fallback_to_sha256:
            quick_hash = _calculate_sha256(file_path=file_path)
    except OSError as err:
        logger.exception("multi_hash: Failed to get file size for '%s' - %s", file_path, err)
        raise

    return quick_hash


def get_sha256_hash(file_path: str) -> str:
    try:
        return FILE_HASHER.hash_sha256(file_path=file_path)
    except (IOError, PermissionError):
        raise


def get_blake3_hash(file_path: str) -> str:
    try:
        return FILE_HASHER.hash_blake3(file_path=file_path)
    except (IOError, PermissionError):
        raise


def multi_hash(file_path: str, similarity_hash: bool = False) -> dict[str, str]:
    """Calculate several hashes for a given file.

    - SHA-256 (always)
    - BLAKE3 (always)
    - TLSH (optional, `similarity_hash` == True)
    - QUICK (when file size >= 8MiB)

    Args:
      * file_path: Absolute path to the file.
      * similarity_hash: If True, attempt to calculate TLSH via `FileHasher`.

    Returns:
      * A dictionary mapping hash function names (e.g., "SHA-256", "BLAKE3",
        "TLSH", "QUICK") to their hexadecimal string representations.
    """
    logger.debug("Starting multi-hash calculations for file: '%s'", file_path)

    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        logger.exception("multi_hash: Failed to get file size for '%s'.", file_path)
        raise

    try:
        hashes = FILE_HASHER.hash(
            file_path=file_path,
            file_size=file_size,
            calculate_sha256=True,
            calculate_blake3=True,
            calculate_tlsh=similarity_hash,
        )
    except OSError:
        logger.exception("multi_hash: FileHasher failed for '%s'.", file_path)
        raise
    except Exception:
        logger.exception("multi_hash: Unexpected error from FileHasher for '%s'.", file_path)
        raise

    quick_hash_value: str | None = None
    try:
        quick_hash_value = QUICK_HASHER.hash(file_path=file_path, file_size=file_size, raise_on_filesize_error=False)

        if quick_hash_value is not None:
            hashes["QUICK"] = quick_hash_value

    except QuickHashFileInstabilityError as err:
        logger.warning(
            "QuickHash generation for '%s' failed due to file instability: %s. QUICK hash will be omitted.",
            file_path,
            err,
        )
    except QuickHashFileSizeError as err:
        logger.warning(
            "QuickHash generation for '%s' skipped due to file size error: %s. QUICK hash will be omitted.",
            file_path,
            err,
        )
    except QuickHashConfigurationError as err:
        logger.error(
            "QuickHash generation for '%s' failed due to configuration error: %s. QUICK hash will be omitted.",
            file_path,
            err,
        )
    except OSError:
        logger.exception(
            "multi_hash: OSError during QuickHash attempt for '%s'. QUICK hash will be omitted.",
            file_path,
        )
    except Exception:
        logger.exception(
            "multi_hash: Unexpected error from QuickHasher for '%s'. QUICK hash will be omitted.",
            file_path,
        )

    logger.debug(
        "multi_hash completed for '%s'. Final hash keys: %s",
        file_path,
        list(hashes.keys()),
    )
    return cast(dict[str, str], hashes)
