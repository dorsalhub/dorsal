# dorsal/file/validators/office_document.py
#
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

import datetime
from typing import Any
from pydantic import BaseModel, Field
from dorsal.common.validators import TString4096


class WordProperties(BaseModel):
    """Validation model for Word-specific properties (.docx)."""

    page_count: int | None = Field(default=None, description="Number of pages in the document.")
    word_count: int | None = Field(default=None, description="Number of words in the document.")
    char_count: int | None = Field(default=None, description="Number of characters in the document.")
    paragraph_count: int | None = Field(default=None, description="Number of paragraphs in the document.")
    hyperlinks: list[TString4096] = Field(
        default_factory=list, description="A list of external hyperlinks found in the document.", max_length=256
    )
    embedded_images: list[TString4096] = Field(
        default_factory=list, description="A list of paths to embedded images within the OOXML package.", max_length=256
    )
    has_track_changes: bool | None = Field(default=None, description="Indicates if 'Track Changes' is or was enabled.")


class ExcelSheet(BaseModel):
    """Validation model for a single sheet within an Excel workbook."""

    name: TString4096 = Field(description="The display name of the worksheet.")
    is_hidden: bool = Field(default=False, description="True if the sheet is hidden.")
    row_count: int | None = Field(
        default=None, description="The number of rows with data, based on the <dimension> tag."
    )
    column_count: int | None = Field(
        default=None, description="The number of columns with data, based on the <dimension> tag."
    )
    column_names: list[TString4096] = Field(
        default_factory=list,
        description="A list of values found in the first row (Row '1') of the sheet.",
        max_length=256,
    )


class ExcelProperties(BaseModel):
    """Validation model for Excel-specific properties (.xlsx)."""

    active_sheet_name: TString4096 | None = Field(
        default=None, description="The name of the sheet that was active when saved."
    )
    sheet_names: list[TString4096] = Field(
        default_factory=list, description="An ordered list of all sheet names in the workbook.", max_length=256
    )
    has_macros: bool | None = Field(default=None, description="True if the workbook contains macros.")
    sheets: list[ExcelSheet] = Field(
        default_factory=list, description="A list of objects, one for each parsed sheet.", max_length=256
    )


class PowerPointProperties(BaseModel):
    """Validation model for PowerPoint-specific properties (.pptx)."""

    slide_count: int | None = Field(default=None, description="The total number of slides in the presentation.")
    slide_master_names: list[TString4096] = Field(
        default_factory=list, description="A list of names of the slide masters.", max_length=256
    )


class OfficeDocumentValidationModel(BaseModel):
    """
    Main validation model for the OfficeDocumentAnnotationModel.
    This structure combines all common and format-specific metadata.
    """

    # --- Core Properties (from core.xml) ---
    author: TString4096 | None = Field(
        default=None, description="The document author.", json_schema_extra={"pii_risk": True}
    )
    last_modified_by: TString4096 | None = Field(
        default=None, description="The user who last saved the document.", json_schema_extra={"pii_risk": True}
    )
    title: TString4096 | None = Field(default=None, description="The document title.")
    subject: TString4096 | None = Field(default=None, description="The document subject.")
    keywords: list[TString4096] = Field(default_factory=list, description="A list of keywords.")
    revision: int | None = Field(default=None, description="The document revision number.")
    creation_date: datetime.datetime | None = Field(default=None, description="The document creation timestamp.")
    modified_date: datetime.datetime | None = Field(default=None, description="The document modification timestamp.")
    application_name: TString4096 | None = Field(
        default=None, description="The name of the application that created the file."
    )
    application_version: TString4096 | None = Field(
        default=None, description="The version of the application that created the file."
    )
    template: TString4096 | None = Field(
        default=None, description="The name of the template file (e.g., 'Normal.dotm')."
    )

    structural_parts: list[TString4096] = Field(
        default_factory=list, description="A list of all content types defined in the package.", max_length=256
    )
    has_comments: bool | None = Field(
        default=None, description="True if the document package contains a comments part."
    )

    custom_properties: dict[TString4096, Any] = Field(
        default_factory=dict,
        description="A key-value map of custom document properties.",
        json_schema_extra={"pii_risk": True},
    )

    language: TString4096 | None = Field(
        default=None, description="The normalized, human-readable language name (e.g., 'English')."
    )
    language_code: TString4096 | None = Field(
        max_length=3, default=None, description="The ISO 639-3 alpha-3 language code (e.g., 'eng')."
    )
    locale_code: TString4096 | None = Field(
        max_length=35, default=None, description="The language/locale code (e.g., 'en-US')."
    )
    default_font: TString4096 | None = Field(
        default=None, description="The default font defined in the document styles."
    )
    all_fonts: list[TString4096] = Field(
        default_factory=list, description="A list of all fonts declared in the font table.", max_length=256
    )

    is_password_protected: bool = Field(
        default=False, description="True if the file is zip-encrypted (password protected)."
    )

    word: WordProperties | None = Field(default=None, description="Contains metadata specific to Word documents.")
    excel: ExcelProperties | None = Field(default=None, description="Contains metadata specific to Excel workbooks.")
    powerpoint: PowerPointProperties | None = Field(
        default=None, description="Contains metadata specific to PowerPoint presentations."
    )
