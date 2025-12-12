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
from typing import Any

from dorsal.common.model import AnnotationModel
from dorsal.file.annotation_models.pdf.config import PDFIUM_METADATA_FIELD_MAPPING
from dorsal.file.annotation_models.pdf.utils import pdfium_extract_pdf_metadata
from dorsal.file.utils.dates import PDF_DATETIME


logger = logging.getLogger(__name__)


class PDFAnnotationModel(AnnotationModel):
    """Extract metadata from PDF files using pypdfium2."""

    id: str = "dorsal/pdf"
    version: str = "1.0.0"
    variant: str = "pypdfium2"

    def _normalize_pdf_metadata(self, raw_metadata: dict[str, Any]) -> dict[str, Any]:
        """Normalize raw metadata extracted from pypdfium2.

        - Map known fields to standardized names using PDFIUM_METADATA_FIELD_MAPPING.
        - Convert date strings to datetime objects.
        - Ensure all mapped fields are present in the output, with None if no value.
        - Ignore unmapped fields from raw_metadata with a debug log.

        Args:
          * raw_metadata: Dictionary of metadata directly from pypdfium2.

        Returns:
          * Normalized metadata dictionary.
        """
        normalized_metadata: dict[str, Any] = {}

        for pdfium_key, target_key in PDFIUM_METADATA_FIELD_MAPPING.items():
            raw_value = raw_metadata.get(pdfium_key)
            if raw_value is not None and raw_value != "":
                normalized_metadata[target_key] = raw_value
            else:
                normalized_metadata[target_key] = None
                logger.debug(
                    "Raw PDF metadata field '%s' (maps to '%s') is missing or empty. Setting to None.",
                    pdfium_key,
                    target_key,
                )

        for raw_key_from_pdfium in raw_metadata:
            if raw_key_from_pdfium not in PDFIUM_METADATA_FIELD_MAPPING:
                logger.debug(
                    "Ignoring unmapped PDF metadata field from pypdfium2: '%s' (value: '%s')",
                    raw_key_from_pdfium,
                    str(raw_metadata[raw_key_from_pdfium])[:100],
                )

        date_fields_to_parse = ("creation_date", "modified_date")
        for date_field_key in date_fields_to_parse:
            if date_field_key in normalized_metadata and isinstance(normalized_metadata[date_field_key], str):
                date_str_value = normalized_metadata[date_field_key]
                parsed_date = PDF_DATETIME.parse(date_str_value)
                if parsed_date is None and date_str_value:
                    logger.debug(
                        "Failed to parse date string '%s' for field '%s'. Field will be None.",
                        date_str_value,
                        date_field_key,
                    )
                normalized_metadata[date_field_key] = parsed_date
            elif date_field_key in normalized_metadata and normalized_metadata[date_field_key] is not None:
                logger.warning(
                    "Expected string for date field '%s', but got type '%s'. Leaving as None.",
                    date_field_key,
                    type(normalized_metadata[date_field_key]).__name__,
                )
                normalized_metadata[date_field_key] = None
        return normalized_metadata

    def main(self, password: str | None = None) -> dict[str, Any] | None:
        """Extract, normalize, and return metadata from the PDF file.

        Args:
            password: Optional password from pipeline config.

        Returns:
            Dictionary of normalized PDF metadata if successful.
            None if the PDF cannot be read or essential metadata extraction fails, with `self.error` set to an appropriate message.

        Raises:
            ImportError: If `pypdfium2` is not installed (propagated from utils).
            Other exceptions from `pypdfium2` for critical, unrecoverable errors not handled by `pdfium_extract_pdf_metadata`.

        """
        logger.debug("PDFAnnotationModel: Starting metadata extraction for '%s'", self.file_path)

        try:
            raw_metadata = pdfium_extract_pdf_metadata(file_path=self.file_path, password=password)
        except ImportError:
            self.error = "pypdfium2 library not found. Cannot process PDF."
            logger.error(self.error)
            raise
        except Exception as err:
            self.error = f"Unexpected error during raw PDF metadata extraction: {err}"
            logger.exception(
                "PDFAnnotationModel: Unexpected error from pdfium_extract_pdf_metadata for '%s'.",
                self.file_path,
            )
            return None

        if raw_metadata is None:
            self.error = "PDF metadata could not be extracted by pypdfium2 (e.g., encrypted, corrupted, or unreadable)."
            logger.debug(
                "PDFAnnotationModel: Raw metadata extraction failed for '%s'. Error message to be set: %s",
                self.file_path,
                self.error,
            )
            return None

        logger.debug(
            "PDFAnnotationModel: Raw metadata extracted for '%s', proceeding with normalization.",
            self.file_path,
        )

        try:
            normalized_metadata = self._normalize_pdf_metadata(raw_metadata=raw_metadata)
        except Exception as err:
            self.error = f"Failed to normalize extracted PDF metadata: {err}"
            logger.exception(
                "PDFAnnotationModel: Error during _normalize_pdf_metadata for '%s'.",
                self.file_path,
            )
            return None

        logger.debug(
            "PDFAnnotationModel: Metadata normalization complete for '%s'.",
            self.file_path,
        )
        return normalized_metadata
