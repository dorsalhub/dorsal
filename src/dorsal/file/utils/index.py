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

from __future__ import annotations
import os
import pathlib
import logging
from typing import Callable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.file.index import DorsalIndex

logger = logging.getLogger(__name__)


def get_cached_hash(
    *,
    file_path: str,
    index: "DorsalIndex",
    hash_callable: Callable[[str], str | None],
    hash_function: str,
) -> str | None:
    """Gets a hash from the index or calculates and caches it on a miss.

    Orchestrates the caching logic for individual hashes.
    First attempts a fast, read-only check of the index using the `DorsalIndex.get_hash` method,
    which includes a staleness check against the file's modification time.

    If that check fails (either because the file is new or has been modified),
    it invokes the provided callable to generate a new hash and then saves
    the result back to the index using `DorsalIndex.upsert_hash` for future use.

    Args:
        file_path: The absolute path to the file to be hashed.
        index: An active instance of the DorsalIndex class.
        hash_callable: The function to call to generate the hash. It must accept
                       a file path string and return a hash string or None.
        hash_function: The string identifier for the hash function (e.g., "SHA-256")
              to be used as the key when storing the hash in the index.

    Returns:
        The hash string if successfully retrieved or generated, otherwise None.
    """
    logger.debug(
        "Attempting to get cached hash for '%s' (hash_function: %s)",
        file_path,
        hash_function,
    )

    cached_hash = index.get_hash(path=file_path, hash_function=hash_function)
    if cached_hash:
        logger.debug("Cache hit for '%s' (hash_function: %s)", file_path, hash_function)
        return cached_hash

    logger.debug(
        "Cache miss for '%s' (hash_function: %s). Calculating new hash.",
        file_path,
        hash_function,
    )
    try:
        new_hash = hash_callable(file_path)
        if not new_hash:
            return None

        modified_time = os.path.getmtime(file_path)
        index.upsert_hash(
            path=file_path,
            modified_time=modified_time,
            hash_function=hash_function,
            hash_value=new_hash,
        )
        return new_hash

    except (FileNotFoundError, PermissionError) as e:
        logger.error("Could not generate hash for '%s' due to filesystem error: %s", file_path, e)
        return None
    except Exception:
        logger.exception("An unexpected error occurred during hash generation for '%s'.", file_path)
        return None
