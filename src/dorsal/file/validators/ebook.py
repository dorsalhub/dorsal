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
from pydantic import BaseModel, Field, ConfigDict
from dorsal.common.validators import LanguageName, TString4096


class EbookValidationModel(BaseModel):
    """Validation model for common ebook metadata."""

    title: TString4096 | None = Field(default=None, description="The primary title of the ebook.")
    authors: list[TString4096] = Field(
        default_factory=list, description="A list of the primary authors or creators of the work.", max_length=256
    )
    contributors: list[TString4096] = Field(
        default_factory=list, description="A list of other contributors (e.g., editors, illustrators).", max_length=256
    )
    publisher: TString4096 | None = Field(default=None, description="The publisher of the ebook.")
    subjects: list[TString4096] = Field(
        default_factory=list,
        description="A list of subjects, keywords, or tags associated with the ebook.",
        max_length=256,
    )
    description: TString4096 | None = Field(
        default=None, description="A synopsis or description of the ebook's content."
    )
    language: LanguageName | None = Field(default=None, description="The language of the ebook.")
    language_code: str | None = Field(
        max_length=3, default=None, description="The ISO 639-3 alpha-3 language code (e.g., 'eng')."
    )
    locale_code: str | None = Field(default=None, description="The locale of the ebook.")
    rights: TString4096 | None = Field(
        default=None, description="Copyright or rights information associated with the ebook."
    )
    isbn: str | None = Field(
        default=None,
        pattern=r"^([0-9]{9}[0-9X]|[0-9]{13})$",
        description="The ISBN (10 or 13) of the ebook, if available.",
    )
    other_identifiers: list[TString4096] = Field(
        default_factory=list,
        description="A list of other unique identifiers (e.g., UUIDs, ASINs, etc.).",
        max_length=256,
    )
    tools: list[TString4096] = Field(
        default_factory=list,
        description="A list of software tools or agents used to create or convert the ebook file.",
        max_length=256,
    )
    cover_path: TString4096 | None = Field(
        default=None, description="An internal path to the cover image within the ebook's archive, if one exists."
    )
    publication_date: datetime.datetime | None = Field(
        default=None, description="The primary publication date of the ebook."
    )
    creation_date: datetime.datetime | None = Field(
        default=None, description="The original creation date of the work, if specified."
    )
    modification_date: datetime.datetime | None = Field(
        default=None, description="The last modification date of the ebook file."
    )
