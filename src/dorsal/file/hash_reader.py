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

import logging
import os

from dorsal.common.exceptions import (
    QuickHashConfigurationError,
    QuickHashFileInstabilityError,
    QuickHashFileSizeError,
)
from dorsal.file.utils import FILE_HASHER, QUICK_HASHER
from dorsal.file.cache.dorsal_cache import DorsalCache
from dorsal.file.utils.hashes import HashFunctionId
from dorsal.session import get_shared_cache

logger = logging.getLogger(__name__)


class HashReader:
    """Retrieves one or more hashes for a given file."""

    @property
    def _cache(self) -> DorsalCache:
        """Dynamically fetches the current valid shared cache."""
        return get_shared_cache()

    def get(
        self,
        file_path: str,
        hashes: list[HashFunctionId],
        skip_cache: bool = False,
    ) -> dict[str, str | None]:
        """
        Retrieves one or more hashes for a given file.

        It first attempts to fetch the hash from the shared cache. If a hash
        is not found in the cache or if caching is skipped, it will be
        calculated on-demand. Hashes are written back to cache.

        Args:
            file_path: The absolute path to the file.
            hashes: A list of hash algorithm identifiers to retrieve.
            skip_cache: If True, the cache check is bypassed and all
                        hashes are calculated directly. Defaults to False.

        Returns:
            A dictionary mapping the hash algorithm identifier to its
            hexadecimal string value. If a hash cannot be generated (e.g., TLSH
            on a small file), its value will be None.
        """
        results: dict[str, str | None] = {}
        hashes_to_process: set[HashFunctionId] = set(hashes)

        if not skip_cache:
            found_in_cache = set()
            for hash_func in hashes_to_process:
                cached_hash = self._cache.get_hash(path=file_path, hash_function=hash_func)
                if cached_hash is not None:
                    results[hash_func] = cached_hash
                    found_in_cache.add(hash_func)
            hashes_to_process -= found_in_cache

        if not hashes_to_process:
            return results

        try:
            modified_time = os.path.getmtime(file_path)
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.error(f"Could not access file details for {file_path}: {e}")
            for hash_func in hashes_to_process:
                results[hash_func] = None
            return results

        file_hasher_algos = hashes_to_process & {"SHA-256", "BLAKE3", "TLSH"}

        if file_hasher_algos:
            try:
                calculated_hashes = FILE_HASHER.hash(
                    file_path=file_path,
                    file_size=file_size,
                    calculate_sha256="SHA-256" in file_hasher_algos,
                    calculate_blake3="BLAKE3" in file_hasher_algos,
                    calculate_tlsh="TLSH" in file_hasher_algos,
                )
                for hash_function, hash_val in calculated_hashes.items():
                    results[hash_function] = hash_val
                    if not skip_cache:
                        self._cache.upsert_hash(
                            path=file_path,
                            modified_time=modified_time,
                            hash_function=hash_function,
                            hash_value=hash_val,
                        )
                    hashes_to_process.remove(hash_function)

            except OSError as e:
                logger.error(f"Error during hashing file {file_path}: {e}")
                for hash_function in file_hasher_algos:
                    results[hash_function] = None
                    hashes_to_process.remove(hash_function)

        if "QUICK" in hashes_to_process:
            quick_hash = None
            try:
                quick_hash = QUICK_HASHER.hash(file_path=file_path, file_size=file_size)
            except (
                QuickHashFileInstabilityError,
                QuickHashFileSizeError,
                QuickHashConfigurationError,
                OSError,
            ) as e:
                logger.warning(f"Could not generate QUICK hash for {file_path}: {e}")

            results["QUICK"] = quick_hash
            if not skip_cache and quick_hash is not None:
                self._cache.upsert_hash(
                    path=file_path,
                    modified_time=modified_time,
                    hash_function="QUICK",
                    hash_value=quick_hash,
                )
            hashes_to_process.remove("QUICK")

        for hash_func in hashes_to_process:
            results[hash_func] = None

        return results


HASH_READER = HashReader()
