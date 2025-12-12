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

from bisect import bisect_left
import hashlib
import logging

import os
from typing import Callable, TYPE_CHECKING

from dorsal.common.literals import GiB, MiB, PiB
from dorsal.common.exceptions import (
    QuickHashConfigurationError,
    QuickHasherError,
    QuickHashFileInstabilityError,
    QuickHashFileSizeError,
)
from dorsal.file.configs.hasher import file_size_chunks
from dorsal.file.configs.sampling import PREDICTABLE_COUNT
from dorsal.file.utils.sampling import reservoir_sample_r

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hashlib import _Hash


class QuickHasher:
    """
    Generate a 'quick hash' for large files by sampling content chunks.

    - Designed for speed on large files.
    - Provides a deterministic hash for fast lookups.
    - Not cryptographically collision-resistant like full-file hashes.
    - Aims for strong probabilistic uniqueness.
    - Number of chunks sampled varies with file size.
    - Sampling is deterministic, seeded by file size (using modulo operation),
      ensuring the same file (by size and content at sampled locations)
      will always produce the same QuickHash.
    """

    hasher_constructor: Callable[[], "_Hash"] = hashlib.sha256
    min_chunks: int = 8
    max_chunks: int = 1024
    chunk_size: int = MiB
    upper_filesize_chunks: int = 128 * GiB
    lower_filesize_chunks: int = 128 * MiB
    min_permitted_filesize: int = 32 * MiB
    max_permitted_filesize: int = 1 * PiB

    PREDICTABLE_SEQUENCE_LENGTH: int = PREDICTABLE_COUNT

    def _get_chunk_count(self, file_size: int) -> int:
        """Determine number of chunks to sample based on file size."""
        if file_size >= self.upper_filesize_chunks:
            return self.max_chunks
        if file_size <= self.lower_filesize_chunks:
            return self.min_chunks
        idx = bisect_left(a=file_size_chunks, x=file_size)
        return min(self.max_chunks, max(self.min_chunks, self.min_chunks + idx))

    def _get_total_chunks(self, file_size: int) -> int:
        """Calculate total number of fixed-size chunks in the file."""
        if self.chunk_size <= 0:
            msg = f"chunk_size must be positive, but got {self.chunk_size}."
            logger.error(msg + " Cannot calculate total chunks.")
            raise QuickHashConfigurationError(msg)
        return file_size // self.chunk_size

    def _make_seed(self, file_size: int) -> int:
        """
        Create a deterministic seed from file size using a modulo operation.
        Use for predictable number sequence offset.

        Args:
          * file_size: Size of the file in bytes.

        Returns:
          * Integer seed value (0 to PREDICTABLE_SEQUENCE_LENGTH - 1).

        Raises:
          * QuickHashConfigurationError: If PREDICTABLE_SEQUENCE_LENGTH is not positive.
        """
        if self.PREDICTABLE_SEQUENCE_LENGTH <= 0:
            msg = f"PREDICTABLE_SEQUENCE_LENGTH must be positive for seed generation, got {self.PREDICTABLE_SEQUENCE_LENGTH}."
            logger.error(msg)
            raise QuickHashConfigurationError(msg)

        seed = file_size % self.PREDICTABLE_SEQUENCE_LENGTH
        logger.debug(
            "Generated seed %d for file_size %d (sequence length %d) using modulo.",
            seed,
            file_size,
            self.PREDICTABLE_SEQUENCE_LENGTH,
        )
        return seed

    def _random_sample_chunk_indices(
        self, file_size: int, num_chunks_to_sample: int, total_chunks_in_file: int
    ) -> list[int]:
        """Generate a deterministic, sorted list of chunk indices to sample."""
        if total_chunks_in_file == 0:
            logger.debug(
                "Total chunks in file is 0 (file size %d, chunk_size %d). No chunks to sample.",
                file_size,
                self.chunk_size,
            )
            return []
        if num_chunks_to_sample <= 0:
            logger.debug(
                "Number of chunks to sample is %d. No chunks will be sampled.",
                num_chunks_to_sample,
            )
            return []

        actual_num_to_sample = min(num_chunks_to_sample, total_chunks_in_file)
        if actual_num_to_sample != num_chunks_to_sample:
            logger.debug(
                "Adjusted num chunks to sample from %d to %d (total available: %d) for file size %d.",
                num_chunks_to_sample,
                actual_num_to_sample,
                total_chunks_in_file,
                file_size,
            )
        if actual_num_to_sample == 0:
            return []

        seed = self._make_seed(file_size=file_size)

        sampled_indices = reservoir_sample_r(iterable=range(total_chunks_in_file), k=actual_num_to_sample, seed=seed)
        return sorted(sampled_indices)

    def _check_permitted_filesize(self, file_path: str, file_size: int, raise_on_error: bool) -> bool:
        """Check if file size is within permitted range for QuickHasher."""
        if not (self.min_permitted_filesize <= file_size <= self.max_permitted_filesize):
            msg = (
                f"File size {file_size} bytes is outside the permitted range "
                f"({self.min_permitted_filesize} - {self.max_permitted_filesize} bytes)."
            )
            if raise_on_error:
                logger.error("QuickHash error for file '%s': %s", file_path, msg)
                raise QuickHashFileSizeError(msg, file_path=file_path)
            logger.debug("QuickHash not generated for file '%s': %s", file_path, msg)
            return False
        return True

    def hash(self, file_path: str, file_size: int, raise_on_filesize_error: bool = False) -> str | None:
        """
        Generate a 'quick hash' by sampling file content.

        Args:
          * file_path: Absolute path to the file.
          * file_size: File size in bytes.
          * raise_on_filesize_error: If True, raise ValueError if file size
                                     is outside permitted range. Default False (returns None).

        Returns:
          * Hexadecimal string of QuickHash if successful and permitted.
          * None if size out of range and `raise_on_filesize_error` is False.

        Raises:
          * OSError: For file access errors (e.g., FileNotFoundError, PermissionError).
          * ValueError: If `raise_on_filesize_error` is True and file size is out of range,
                        or if internal configuration (e.g. chunk_size) is invalid.
                        (Specific subtypes like QuickHashFileSizeError or QuickHashConfigurationError may be raised).
          * QuickHashFileInstabilityError: If the file changes state during hashing.
        """
        logger.debug("Attempting to generate QuickHash for: %s", file_path)

        if not self._check_permitted_filesize(
            file_path=file_path,
            file_size=file_size,
            raise_on_error=raise_on_filesize_error,
        ):
            return None

        hasher_instance: "_Hash" = self.hasher_constructor()
        total_chunks_in_file = self._get_total_chunks(file_size)
        num_chunks_to_sample = self._get_chunk_count(file_size)

        logger.debug(
            "File '%s' (size %d bytes): Total %dMiB-chunks: %d, Chunks to sample: %d",
            file_path,
            file_size,
            self.chunk_size // MiB,
            total_chunks_in_file,
            num_chunks_to_sample,
        )

        chunk_indices_to_read = self._random_sample_chunk_indices(
            file_size=file_size,
            num_chunks_to_sample=num_chunks_to_sample,
            total_chunks_in_file=total_chunks_in_file,
        )

        if not chunk_indices_to_read:
            if file_size > 0 and file_size < self.chunk_size:
                logger.debug(
                    "File '%s' (size %d) is smaller than one chunk. Reading entire file for QuickHash.",
                    file_path,
                    file_size,
                )
                try:
                    with open(file_path, "rb") as fp:
                        hasher_instance.update(fp.read())
                except OSError:
                    logger.exception(
                        "Failed during full read for small file QuickHash on '%s'.",
                        file_path,
                    )
                    raise
                hex_digest = hasher_instance.hexdigest()
                logger.debug("Generated QuickHash for small file '%s': %s", file_path, hex_digest)
                return hex_digest
            else:
                logger.warning(
                    "QuickHash: No chunk indices selected for file '%s' (size %d). Returning None.",
                    file_path,
                    file_size,
                )
                return None

        logger.debug(
            "QuickHash: Selected chunk indices to read for '%s': %s",
            file_path,
            chunk_indices_to_read,
        )

        try:
            with open(file_path, "rb") as fp:
                for chunk_index in chunk_indices_to_read:
                    byte_offset = chunk_index * self.chunk_size
                    if byte_offset >= file_size:
                        msg = (
                            f"Calculated offset {byte_offset} exceeds current file size {file_size} "
                            f"for chunk index {chunk_index}. File may have changed during hashing."
                        )
                        logger.error(
                            "QuickHash Instability: %s",
                            msg,
                            extra={"file_path": file_path},
                        )
                        raise QuickHashFileInstabilityError(msg, file_path=file_path)

                    fp.seek(byte_offset)
                    chunk_data = fp.read(self.chunk_size)

                    if not chunk_data:
                        msg = (
                            f"Read empty chunk at offset {byte_offset} (index {chunk_index}) "
                            f"when data was expected (file size {file_size}). "
                            "File may have changed during hashing."
                        )
                        logger.error(
                            "QuickHash Instability: %s",
                            msg,
                            extra={"file_path": file_path},
                        )
                        raise QuickHashFileInstabilityError(msg, file_path=file_path)
                    hasher_instance.update(chunk_data)
        except OSError:
            logger.exception("Failed during chunked read for QuickHash on file '%s'.", file_path)
            raise

        hex_digest = hasher_instance.hexdigest()
        logger.debug("Generated QuickHash for '%s': %s", file_path, hex_digest)
        return hex_digest
