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


from __future__ import annotations

import logging
import os
from typing import Any, TYPE_CHECKING

from dorsal.common.model import AnnotationModel
from dorsal.file.annotation_models.office_document.config import OFFICE_FORMAT_MAPPING

from dorsal.file.annotation_models.office_document.utils_docx import extract_docx_metadata
from dorsal.file.annotation_models.office_document.utils_xlsx import extract_xlsx_metadata
from dorsal.file.annotation_models.office_document.utils_pptx import extract_pptx_metadata

if TYPE_CHECKING:
    from dorsal.file.configs.model_runner import RunModelResult

logger = logging.getLogger(__name__)

OFFICE_MEDIA_TYPE_MAPPING = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        extract_docx_metadata,
        "docx_stdlib_xml",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (extract_xlsx_metadata, "xlsx_stdlib_xml"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        extract_pptx_metadata,
        "pptx_stdlib_xml",
    ),
    None: None,
}


class OfficeDocumentAnnotationModel(AnnotationModel):
    """
    Extracts metadata from Microsoft Office formats (OOXML: .docx, .xlsx, .pptx).
    This model acts as a dispatcher, calling the correct stdlib-based parser.
    """

    id: str = "dorsal/office"
    version: str = "1.0.0"
    variant: str = "dispatcher"

    def main(self) -> dict[str, Any] | None:
        """
        Dispatches to the correct format-specific parser based on media_type.
        """
        logger.debug(
            "OfficeAnnotationModel: Starting metadata extraction for '%s'",
            self.file_path,
        )

        media_type = self.media_type
        parser_info = OFFICE_MEDIA_TYPE_MAPPING.get(media_type)
        metadata: dict[str, Any] | None = None

        if parser_info:
            parser_func, variant_name = parser_info
            self.variant = variant_name
            metadata = parser_func(self.file_path)
        else:
            logger.debug("OfficeAnnotationModel: Skipping. Media type '%s' is not an OOXML office file.", media_type)
            return None

        if metadata is None:
            if self.error is None:
                self.error = f"Failed to parse metadata for file: {self.file_path} (parser: {self.variant})"
            logger.warning(self.error)
            return None

        logger.debug(
            "OfficeAnnotationModel: Successfully processed '%s' with parser '%s'",
            self.file_path,
            self.variant,
        )
        return metadata
