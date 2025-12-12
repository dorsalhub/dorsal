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
from typing import Any

from dorsal.common.model import AnnotationModel
from dorsal.file.utils import get_quick_hash, multi_hash
from dorsal.file.utils.infer_mediatype import get_media_type

logger = logging.getLogger(__name__)


class FileCoreAnnotationModel(AnnotationModel):
    """
    Annotation model for extracting core file metadata.

    - Calculate file hashes (SHA256, TLSH, BLAKE3 and QUICK).
    - Determine basic file attributes: name, extension, size and media type.
    - This model is designed for use in the `ModelRunner`
    - Its `main` method outputs a dictionary conforming to `FileCoreValidationModel`.

    """

    id: str = "dorsal/base"
    version: str = "1.0.0"

    def _get_file_hashes(self, calculate_similarity_hash: bool = False) -> dict[str, str]:
        """Calculates cryptographic hashes for the file.

        Args:
            calculate_similarity_hash: If True, includes the TLSH similarity hash.

        Returns:
            A dictionary where keys are hash algorithm names (e.g., "SHA-256", "TLSH")
            and values are their hexadecimal hash strings.

        Raises:
            FileNotFoundError, IOError: If the file cannot be read by `multi_hash`.

        """
        try:
            return multi_hash(file_path=self.file_path, similarity_hash=calculate_similarity_hash)
        except Exception as e:
            logger.error(
                "Error calculating hashes for '%s': %s",
                self.file_path,
                e,
                exc_info=True,
            )
            raise

    def _get_filesize(self) -> int:
        """Gets the size of the file in bytes.

        Returns:
            The file size in bytes.

        Raises:
            FileNotFoundError, OSError: If the file does not exist or is inaccessible.

        """
        try:
            if os.path.islink(self.file_path):
                return os.lstat(self.file_path).st_size
            return os.stat(self.file_path).st_size
        except OSError as e:
            logger.error("Error getting filesize for '%s': %s", self.file_path, e, exc_info=True)
            raise

    def _get_filename(self) -> str:
        """Extract the filename (basename) from the file path."""
        return os.path.basename(self.file_path)

    def _get_file_extension(self, file_name: str) -> str | None:
        """Extract the file extension from the filename.

        Considers an empty string or a single dot as "no extension".

        Args:
            file_name: The name of the file.

        Returns:
            The lowercase file extension (including the leading dot, e.g., ".txt"),
            or None if the file has no meaningful extension.

        """
        _, extension = os.path.splitext(file_name)
        if not extension or extension == ".":
            return None
        return extension.lower()

    def _get_media_type(self, file_extension: str | None) -> str:
        """
        Determines the 'best guess' media type for the file by calling the utility function.

        Args:
            file_extension: The file's extension (e.g., ".txt"), or None.

        Returns:
            The determined media type string.
        """
        return get_media_type(file_path=self.file_path, file_extension=file_extension)

    def main(self, calculate_similarity_hash: bool = False) -> dict[str, Any] | None:
        """
        Main execution method for the FileCoreAnnotationModel.

        Orchestrates the extraction of all fundamental file metadata.

        Args:
            calculate_similarity_hash: If True, the TLSH similarity hash will be
                                       calculated and included in the results.
                                       Defaults to False.

        Returns:
            A dictionary containing the extracted file metadata, conforming to
            the structure expected by `FileCoreValidationModelStrict`.
            Returns None if a recoverable error specific to this model's logic occurs
            and `self.error` is set (though current implementation tends to let
            critical OS/IO errors propagate).

        Raises:
            FileNotFoundError, IOError, OSError: If critical issues occur during
                file access (e.g., for hashing, size, media type determination).
                These are expected to be caught by the ModelRunner.
        """
        try:
            logger.debug(
                "FileCoreAnnotationModel main: Starting processing for '%s'",
                self.file_path,
            )

            hashes = self._get_file_hashes(calculate_similarity_hash=calculate_similarity_hash)
            primary_hash = hashes.get("SHA-256")
            if not primary_hash:
                self.error = "Core SHA-256 hash calculation failed."
                logger.error(self.error + " File: '%s'", self.file_path)
                return None

            tlsh_hash = hashes.get("TLSH")
            quick_hash = hashes.get("QUICK")

            all_hashes_list = [{"id": hash_name, "value": hash_value} for hash_name, hash_value in hashes.items()]

            file_name = self._get_filename()
            file_extension = self._get_file_extension(file_name=file_name)
            file_size = self._get_filesize()

            media_type = self._get_media_type(file_extension=file_extension)

            logger.debug(
                "FileCoreAnnotationModel main: Successfully processed '%s'",
                self.file_path,
            )
            return {
                "hash": primary_hash,
                "similarity_hash": tlsh_hash,
                "quick_hash": quick_hash,
                "all_hashes": all_hashes_list,
                "name": file_name,
                "extension": file_extension,
                "size": file_size,
                "media_type": media_type,
            }
        except (FileNotFoundError, IOError, OSError) as e:
            self.error = f"File system error during processing: {type(e).__name__}: {e}"
            logger.error(
                "FileCoreAnnotationModel main: CRITICAL OS/IO Error for '%s'. Error: %s",
                self.file_path,
                self.error,
                exc_info=True,
            )
            raise
        except Exception as e:
            self.error = f"Unexpected error during FileCoreAnnotationModel processing: {type(e).__name__}: {e}"
            logger.error(
                "FileCoreAnnotationModel main: UNEXPECTED Error for '%s'. Error: %s",
                self.file_path,
                self.error,
                exc_info=True,
            )
            raise
