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
from pydantic import BaseModel, Field
from dorsal.common.validators import TString4096


class PDFValidationModel(BaseModel):
    """Validation model for core PDF metadata."""

    author: TString4096 | None = Field(
        default=None,
        description="The primary author of the document, from the 'Author' metadata field.",
        json_schema_extra={"pii_risk": True},
    )
    title: TString4096 | None = Field(
        default=None, description="The title of the document, from the 'Title' metadata field."
    )
    creator: TString4096 | None = Field(
        default=None,
        description="The software tool used to create the original document (e.g., 'Word'), from the 'Creator' field.",
        json_schema_extra={"pii_risk": True},
    )
    producer: TString4096 | None = Field(
        default=None,
        description="The software tool used to convert or produce the final PDF (e.g., 'Acrobat PDF Library'), from the 'Producer' field.",
    )
    subject: TString4096 | None = Field(
        default=None, description="The subject or topic of the document, from the 'Subject' field."
    )
    keywords: TString4096 | None = Field(
        default=None, description="A string of keywords associated with the document, from the 'Keywords' field."
    )
    version: str | None = Field(
        default=None,
        pattern=r"^[1,2]\.\d$",
        description="The PDF version (e.g., '1.7', '2.0') as reported by the parser.",
    )
    page_count: int | None = Field(default=None, ge=0, description="The total number of pages in the document.")
    creation_date: datetime.datetime | None = Field(
        default=None, description="The date and time the document was created, from the 'CreationDate' field."
    )
    modified_date: datetime.datetime | None = Field(
        default=None, description="The date and time the document was last modified, from the 'ModDate' field."
    )
