# Copyright 2025-2026 Dorsal Hub LTD
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
import os
import queue
import threading
from typing import Any, Iterator, cast, ContextManager
import hashlib

import blake3

from dorsal.common.literals import MiB
from dorsal.file.utils.hashes import HashFunctionId

logger = logging.getLogger(__name__)


class FileHasher:
    """
    Calculate cryptographic hashes for a given file by reading it in chunks.

    Supports standard hashes like SHA-256, BLAKE3, MD5, SHA-1, and can optionally calculate
    a TLSH (Trend Micro Locality Sensitive Hash) similarity  hash if the `tlsh` library is
    available and the file meets minimum size requirements.
    """

    _default_hashers = {
        "SHA-256": hashlib.sha256,
        "BLAKE3": blake3.blake3,
        "MD5": hashlib.md5,
        "SHA-1": hashlib.sha1,
        "DORSAL": lambda: blake3.blake3(derive_key_context="Dorsal Validation Hash Context"),
    }
    chunk_size: int = 4 * MiB
    tlsh_min_size: int = 50
    threaded_min_size: int = 4 * MiB

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

    def _stream_file_content(self, file_path: str, follow_symlinks: bool) -> ContextManager[Any]:
        """
        Returns a context manager yielding a binary stream.

        - Regular Files (or follow_symlinks=True): The actual file content on disk.
        - Symlinks (with follow_symlinks=False): The target path string encoded as bytes.
        """
        if not follow_symlinks and os.path.islink(file_path):
            target_path = os.readlink(file_path)
            return io.BytesIO(target_path.encode("utf-8"))

        return open(file_path, "rb")

    def _yield_chunks(self, file_handler: Any) -> Iterator[bytes]:
        """
        Reads the file in chunks synchronously.

        Args:
            file_handler: An opened binary file handler (or BytesIO).

        Yields:
            Bytes representing chunks of the file.
        """
        while True:
            chunk = file_handler.read(self.chunk_size)
            if not chunk:
                break
            yield chunk

    def _yield_chunks_async(self, file_handler: Any, prefetch_count: int = 2) -> Iterator[bytes]:
        """
        Reads the file in chunks using a background thread.
        This overlaps disk I/O with CPU execution for multi-hash operations.
        """
        chunk_queue: queue.Queue[Any] = queue.Queue(maxsize=prefetch_count)

        def reader_thread() -> None:
            try:
                while True:
                    chunk = file_handler.read(self.chunk_size)
                    if not chunk:
                        chunk_queue.put(None)
                        break
                    chunk_queue.put(chunk)
            except Exception as exc:
                chunk_queue.put(exc)

        t = threading.Thread(target=reader_thread, daemon=True)
        t.start()

        while True:
            item = chunk_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    def hash(
        self,
        file_path: str,
        file_size: int | None = None,
        calculate_sha256: bool = True,
        calculate_blake3: bool = True,
        calculate_md5: bool = True,
        calculate_sha1: bool = True,
        calculate_validation: bool = True,
        calculate_tlsh: bool = True,
        follow_symlinks: bool = True,
        threads: int | None = None,
    ) -> dict[HashFunctionId, str]:
        """
        Calculates multiple hashes for the specified file.

        Args:
            file_path: The absolute path to the file to be hashed.
            file_size: The size of the file in bytes.
            calculate_sha256: Whether to calculate SHA-256 (default True).
            calculate_blake3: Whether to calculate BLAKE3 (default True).
            calculate_md5: Whether to calculate MD5 (default True).
            calculate_sha1: Whether to calculate SHA-1 (default True).
            calculate_validation: Whether to calculate validation hash (default True).
            calculate_tlsh: If True, attempts to calculate the TLSH similarity hash.
            follow_symlinks: If True (default), follows symlinks to hash target content.
                              If False, hashes the symlink pointer string itself.
            threads: Max worker threads. None = auto-detect. 1 = force synchronous mode.

        Returns:
            A dictionary mapping hash algorithm names to their hexadecimal string representations.
            If a hash cannot be calculated (e.g., TLSH due to size), it is omitted.

        Raises:
            FileNotFoundError: If `file_path` does not exist.
            PermissionError: If the file cannot be read due to permissions.
            IOError: For other I/O related errors during file reading.
        """
        if file_size is None:
            try:
                if not follow_symlinks and os.path.islink(file_path):
                    file_size = os.lstat(file_path).st_size
                else:
                    file_size = os.path.getsize(file_path)
            except OSError as e:
                logger.exception("Failed to get file size for '%s': %s", file_path, e)
                raise

        functions_to_run = []
        if calculate_sha256:
            functions_to_run.append("SHA-256")
        if calculate_blake3:
            functions_to_run.append("BLAKE3")
        if calculate_md5:
            functions_to_run.append("MD5")
        if calculate_sha1:
            functions_to_run.append("SHA-1")
        if calculate_validation:
            functions_to_run.append("DORSAL")
        if calculate_tlsh:
            functions_to_run.append("TLSH")

        logger.debug(
            "Hashing file: '%s', size: %d bytes, functions: %s, requested threads: %s",
            file_path,
            file_size,
            functions_to_run,
            threads,
        )

        constructors_to_use = {
            name: constructor for name, constructor in self.hashers_constructors.items() if name in functions_to_run
        }

        active_hashers: dict[str, Any] = {name: constructor() for name, constructor in constructors_to_use.items()}

        if calculate_tlsh:
            if not follow_symlinks and os.path.islink(file_path):
                logger.debug("Skipping TLSH for symlink '%s' (Physical Mode).", file_path)
            elif self._check_tlsh_availability():
                if file_size >= self.tlsh_min_size:
                    import tlsh  # type: ignore[import-not-found]

                    active_hashers["TLSH"] = tlsh.Tlsh()
                    logger.debug("TLSH hasher added for file: '%s'", file_path)
                else:
                    logger.debug(
                        "File '%s' is too small for TLSH. It will not be calculated.",
                        file_path,
                    )

        hasher_instances = list(active_hashers.values())
        num_hashers = len(hasher_instances)

        if threads == 1 or num_hashers <= 1 or file_size < self.threaded_min_size:
            worker_count = 1
        elif threads is not None:
            worker_count = min(threads, num_hashers)
        else:
            cpu_count = os.cpu_count() or 1
            worker_count = min(cpu_count, 4, num_hashers)

        try:
            if worker_count > 1:
                try:
                    from concurrent.futures import ThreadPoolExecutor

                    with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                        with ThreadPoolExecutor(max_workers=worker_count) as executor:
                            for chunk in self._yield_chunks_async(fp):
                                futures = [executor.submit(h.update, chunk) for h in hasher_instances]
                                for f in futures:
                                    f.result()
                except (ImportError, RuntimeError) as e:
                    logger.debug("ThreadPoolExecutor unavailable or failed, falling back to sequential hash: %s", e)
                    worker_count = 1

            if worker_count == 1:
                with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                    for chunk in self._yield_chunks(fp):
                        for hasher_instance in hasher_instances:
                            hasher_instance.update(chunk)
        except (FileNotFoundError, PermissionError, IOError, OSError) as e:
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

    def hash_sha256(self, file_path: str, follow_symlinks: bool = True) -> str:
        """
        Calculates the SHA-256 hash for a single file.
        """
        logger.debug("SHA-256 hashing file: '%s'", file_path)
        hasher = hashlib.sha256()
        try:
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for SHA-256 hashing: %s", file_path, err)
            raise

    def hash_blake3(self, file_path: str, follow_symlinks: bool = True) -> str:
        """
        Calculates the BLAKE3 hash for a single file.
        """
        logger.debug("BLAKE3 hashing file: '%s'", file_path)
        hasher = blake3.blake3()
        try:
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for BLAKE3 hashing: %s", file_path, err)
            raise

    def hash_md5(self, file_path: str, follow_symlinks: bool = True) -> str:
        """
        Calculates the MD5 hash for a single file.
        """
        logger.debug("MD5 hashing file: '%s'", file_path)
        hasher = hashlib.md5()
        try:
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for MD5 hashing: %s", file_path, err)
            raise

    def hash_sha1(self, file_path: str, follow_symlinks: bool = True) -> str:
        """
        Calculates the SHA-1 hash for a single file.
        """
        logger.debug("SHA-1 hashing file: '%s'", file_path)
        hasher = hashlib.sha1()
        try:
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for SHA-1 hashing: %s", file_path, err)
            raise

    def hash_dorsal_validation(self, file_path: str, follow_symlinks: bool = True) -> str:
        """
        Calculates the personalized BLAKE3 hash for a single file.
        """
        logger.debug("DORSAL (validation) hashing file: '%s'", file_path)
        hasher = blake3.blake3(derive_key_context="Dorsal Validation Hash Context")
        try:
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for DORSAL (validation) hashing: %s", file_path, err)
            raise

    def hash_tlsh(self, file_path: str, file_size: int, follow_symlinks: bool = True) -> str | None:
        """
        Calculates the TLSH similarity hash for a single file.
        """
        logger.debug("TLSH hashing file: '%s'", file_path)

        if not follow_symlinks and os.path.islink(file_path):
            return None

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
            with self._stream_file_content(file_path, follow_symlinks=follow_symlinks) as fp:
                for chunk in self._yield_chunks(fp):
                    hasher.update(chunk)

            hasher.final()
            return hasher.hexdigest()
        except (IOError, PermissionError, OSError) as err:
            logger.error("Failed to read file '%s' for TLSH hashing: %s", file_path, err)
            raise
        except ValueError as e:
            logger.warning("Could not generate TLSH for '%s': %s", file_path, e)
            return None
