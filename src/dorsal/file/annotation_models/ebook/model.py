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

from dorsal.file.annotation_models.ebook.config import EBOOK_FORMAT_MAPPING
import dorsal.file.annotation_models.ebook.utils as ebook_utils

logger = logging.getLogger(__name__)


class EbookAnnotationModel(AnnotationModel):
    """Extracts metadata from common ebook formats (e.g., EPUB, MOBI)."""

    id: str = "dorsal/ebook"
    version: str = "1.0.0"
    variant: str = "dispatcher"

    def main(self) -> dict[str, Any] | None:
        """
        Extracts metadata by dispatching to the correct format-specific parser.

        Returns:
          * Dictionary of ebook metadata if successful.
          * None if the format is unsupported or parsing fails.
        """
        logger.debug(
            "EbookAnnotationModel: Starting metadata extraction for '%s'",
            self.file_path,
        )

        try:
            _, ext = os.path.splitext(self.file_path)
            parser_type = EBOOK_FORMAT_MAPPING.get(ext.lower())

            metadata: dict[str, Any] | None = None

            if parser_type == "epub":
                self.variant = "epub_stdlib"
                metadata = ebook_utils.extract_epub_metadata(self.file_path)

            else:
                self.error = f"Unsupported ebook format: '{ext}' for file: {self.file_path}"
                logger.info(self.error)
                return None

            if metadata is None:
                self.error = f"Failed to parse ebook metadata for file: {self.file_path} (parser: {self.variant})"
                logger.warning(self.error)
                return None

            logger.debug(
                "EbookAnnotationModel: Successfully processed '%s' with parser '%s'",
                self.file_path,
                self.variant,
            )
            return metadata

        except ImportError as e:
            self.error = f"Missing dependency for parser '{self.variant}': {e}. Cannot process file."
            logger.error(self.error, exc_info=True)
            return None

        except (FileNotFoundError, IOError, OSError) as e:
            self.error = f"File system error during ebook processing: {type(e).__name__}: {e}"
            logger.error(
                "EbookAnnotationModel: CRITICAL OS/IO Error for '%s'. Error: %s",
                self.file_path,
                self.error,
                exc_info=True,
            )
            raise

        except Exception as e:
            self.error = f"Unexpected error during EbookAnnotationModel processing: {type(e).__name__}: {e}"
            logger.error(
                "EbookAnnotationModel: UNEXPECTED Error for '%s'. Error: %s",
                self.file_path,
                self.error,
                exc_info=True,
            )
            raise
