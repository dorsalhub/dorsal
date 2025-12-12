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

import io
import importlib.util
import logging
from typing import Any, Iterator, cast
import hashlib

import blake3

from dorsal.common.literals import MiB
from dorsal.file.utils.hashes import HashFunctionId

logger = logging.getLogger(__name__)


class FileHasher:
    """
    Calculate cryptographic hashes for a given file by reading it in chunks.

    Supports standard hashes like SHA-256 and BLAKE3, and can optionally
    calculate a TLSH (Trend Micro Locality Sensitive Hash) similarity hash if the
    `tlsh` library is available and the file meets minimum size requirements.
    """

    _default_hashers = {
        "SHA-256": hashlib.sha256,
        "BLAKE3": blake3.blake3,
    }
    chunk_size: int = MiB
    tlsh_min_size: int = 50

    def __init__(self) -> None:
        """Initializes the FileHasher."""
        self.hashers_constructors: dict[str, Any] = self._default_hashers.copy()
        self._tlsh_available: bool | None = None

    def _check_tlsh_availability(self) -> bool:
        """Checks if the TLSH library is available."""
        if self._tlsh_available is None:
            if importlib.util.find_spec("tlsh"):
                self._tlsh_available = True
                logger.debug("TLSH library is available")
            else:
                self._tlsh_available = False
                logger.debug(
                    "TLSH hashing library `py-tlsh` not found. TLSH similarity hashes will not be calculated. "
                    "To enable, please install the 'py-tlsh' Python package."
                )
        return self._tlsh_available

    def _yield_chunks(self, file_handler: io.BufferedReader) -> Iterator[bytes]:
        """
        Reads the file in chunks.

        Args:
            file_handler: An opened binary file handler.

        Yields:
            Bytes representing chunks of the file.
        """
        while True:
            chunk = file_handler.read(self.chunk_size)
            if not chunk:
                break
            yield chunk

    def hash(
        self,
        file_path: str,
        file_size: int,
        calculate_sha256: bool = True,
        calculate_blake3: bool = True,
        calculate_tlsh: bool = True,
    ) -> dict[HashFunctionId, str]:
        """
        Calculates multiple hashes for the specified file.

        Args:
            file_path: The absolute path to the file to be hashed.
            file_size: The size of the file in bytes. This must be provided by the caller.
            calculate_tlsh: If True, attempts to calculate the TLSH similarity hash.
                                       Requires `tlsh` library and the file size >= `tlsh_min_size`.

        Returns:
            A dictionary mapping hash algorithm names (e.g., "SHA-256", "BLAKE3", "TLSH")
            to their hexadecimal string representations. If a hash cannot be
            calculated (e.g., TLSH due to size or missing library), it will be
            omitted from the dictionary.

        Raises:
            FileNotFoundError: If `file_path` does not exist.
            PermissionError: If the file cannot be read due to permissions.
            IOError: For other I/O related errors during file reading.
        """
        functions_to_run = []
        if calculate_sha256:
            functions_to_run.append("SHA-256")
        if calculate_blake3:
            functions_to_run.append("BLAKE3")
        if calculate_tlsh:
            functions_to_run.append("TLSH")

        logger.debug(
            "Hashing file: '%s', size: %d bytes, functions: %s",
            file_path,
            file_size,
            functions_to_run,
        )

        constructors_to_use = {
            name: constructor for name, constructor in self.hashers_constructors.items() if name in functions_to_run
        }

        active_hashers: dict[str, Any] = {name: constructor() for name, constructor in constructors_to_use.items()}

        if calculate_tlsh and self._check_tlsh_availability():
            if file_size >= self.tlsh_min_size:
                import tlsh  # type: ignore[import-not-found]

                active_hashers["TLSH"] = tlsh.Tlsh()
                logger.debug("TLSH hasher added for file: '%s'", file_path)
            else:
                logger.debug(
                    "File '%s' is too small for TLSH. It will not be calculated.",
                    file_path,
                )

        try:
            with open(file_path, "rb") as fp:
                for chunk in self._yield_chunks(fp):
                    for hasher_instance in active_hashers.values():
                        hasher_instance.update(chunk)
        except (FileNotFoundError, PermissionError, IOError) as e:
            logger.exception("Failed to read file '%s' for hashing: %s", file_path, e)
            raise

        if "TLSH" in active_hashers:
            try:
                active_hashers["TLSH"].final()
                logger.debug("TLSH hash finalized for file: '%s'", file_path)
            except ValueError as err:
                logger.debug(
                    "TLSH finalization failed for file '%s': %s. TLSH will be omitted.",
                    file_path,
                    err,
                )
                active_hashers.pop("TLSH", None)

        calculated_hashes: dict[HashFunctionId, str] = {}
        for hash_name, hasher_instance in active_hashers.items():
            try:
                key = cast(HashFunctionId, hash_name)
                calculated_hashes[key] = hasher_instance.hexdigest()
            except ValueError as err:
                logger.debug(
                    "Failed to get hexdigest for '%s' on file '%s': %s.",
                    hash_name,
                    file_path,
                    err,
                )

        logger.debug(
            "Successfully calculated hashes for file: '%s'. Hashes obtained: %s",
            file_path,
            list(calculated_hashes.keys()),
        )
        return calculated_hashes

    def hash_sha256(self, file_path: str) -> str:
        """
        Calculates the SHA-256 hash for a single file.

        Args:
            file_path: The absolute path to the file to be hashed.

        Returns:
            The hexadecimal SHA-256 hash as a string.
        """
        logger.debug("SHA-256 hashing file: '%s'", file_path)
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError) as err:
            logger.error("Failed to read file '%s' for SHA-256 hashing: %s", file_path, err)
            raise

    def hash_blake3(self, file_path: str) -> str:
        """
        Calculates the BLAKE3 hash for a single file.

        Args:
            file_path: The absolute path to the file to be hashed.

        Returns:
            The hexadecimal BLAKE3 hash as a string.
        """
        logger.debug("BLAKE3 hashing file: '%s'", file_path)
        hasher = blake3.blake3()
        try:
            with open(file_path, "rb") as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError) as err:
            logger.error("Failed to read file '%s' for BLAKE3 hashing: %s", file_path, err)
            raise

    def hash_tlsh(self, file_path: str, file_size: int) -> str | None:
        """
        Calculates the TLSH similarity hash for a single file.

        Args:
            file_path: The absolute path to the file to be hashed.
            file_size: The size of the file in bytes.

        Returns:
            The TLSH hash as a string, or None if the tlsh library is not
            available, the file is too small, the file cannot be read, or the
            data has insufficient variance for TLSH.
        """
        logger.debug("TLSH hashing file: '%s'", file_path)
        if not self._check_tlsh_availability():
            logger.warning("Cannot calculate TLSH for '%s': tlsh library not available.", file_path)
            return None

        if file_size < self.tlsh_min_size:
            logger.debug(
                "Cannot calculate TLSH for '%s': File size %d is less than minimum %d bytes.",
                file_path,
                file_size,
                self.tlsh_min_size,
            )
            return None

        import tlsh  # type: ignore[import-not-found]

        hasher = tlsh.Tlsh()

        try:
            with open(file_path, "rb") as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)

            hasher.final()
            return hasher.hexdigest()
        except (IOError, PermissionError) as err:
            logger.error("Failed to read file '%s' for TLSH hashing: %s", file_path, err)
            raise
        except ValueError as e:
            logger.warning("Could not generate TLSH for '%s': %s", file_path, e)
            return None
