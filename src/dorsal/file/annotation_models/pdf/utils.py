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

logger = logging.getLogger(__name__)

PDFIUM_VERSION_MAP = {
    11: "1.1",
    12: "1.2",
    13: "1.3",
    14: "1.4",
    15: "1.5",
    16: "1.6",
    17: "1.7",  # 1.8 and 1.9 do not exist
    20: "2.0",
}


def pdfium_extract_pdf_metadata(file_path: str, password: str | None = None) -> dict[str, Any] | None:
    """
    Extract common PDF metadata fields using pypdfium2.

    Args:
      * file_path: Absolute path to the PDF file.
      * password: Optional password for encrypted PDFs.

    Returns:
      * Dictionary of extracted metadata if successful.
      * None if PDF cannot be opened/read or pypdfium2 fails.

    Raises:
      * ImportError: If the 'pypdfium2' library is not installed.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ImportError:
        logger.exception("Unable to extract PDF Metadata: Missing 'pypdfium2' library. Please install it.")
        raise

    document: pdfium.PdfDocument | None = None
    try:
        logger.debug("Attempting to open PDF document: '%s'", file_path)
        document = pdfium.PdfDocument(file_path, password=password)

        document_metadata = document.get_metadata_dict()

        try:
            pdf_version_int = document.get_version()
            document_metadata["version"] = PDFIUM_VERSION_MAP.get(pdf_version_int)
            if document_metadata["version"] is None:
                logger.debug(
                    "Unknown PDF version integer from pypdfium2: %d for file '%s'. Version will be None.",
                    pdf_version_int,
                    file_path,
                )
        except Exception as err:
            logger.debug(
                "Could not determine PDF version for '%s': %s. Setting version to None.",
                file_path,
                err,
            )
            document_metadata["version"] = None

        try:
            document_metadata["page_count"] = len(document)
        except Exception as err:
            logger.debug(
                "Could not determine page count for '%s': %s. Setting page_count to None.",
                file_path,
                err,
            )
            document_metadata["page_count"] = None

        logger.debug("Successfully extracted pypdfium2 metadata for '%s'.", file_path)
        return document_metadata

    except pdfium.PdfiumError as err:
        logger.info(
            "Failed to open or process PDF document '%s' with pypdfium2: %s. "
            "This may be due to encryption, corruption, or wrong format.",
            file_path,
            err,
        )
        return None
    except Exception:
        logger.exception(
            "An unexpected error occurred with pypdfium2 while processing PDF '%s'.",
            file_path,
        )
        return None
    finally:
        if document:
            try:
                document.close()
                logger.debug("Closed PDF document: '%s'", file_path)
            except Exception:
                logger.exception("Error closing PDF document '%s' with pypdfium2.", file_path)
