# Copyright 2026 Dorsal Hub LTD
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

import re
from typing import Any

from dorsal.adapters.arxiv.helpers import extract_date_from_id
from dorsal.adapters.arxiv.validation import is_enabled, validate_record


def to_ris(
    record: dict[str, Any],
    *,
    validate: bool = False,
    **kwargs: Any,
) -> str:
    """Converts a 'dorsal/arxiv' record into an RIS citation."""
    if is_enabled(validate):
        validate_record(record, schema_id="dorsal/arxiv")

    lines = [
        "TY  - PREP",
    ]

    if "title" in record:
        lines.append(f"T1  - {record['title']}")

    for author in record.get("authors", []):
        lines.append(f"AU  - {author}")

    if "abstract" in record:
        lines.append(f"AB  - {record['abstract']}")

    date_info = extract_date_from_id(record.get("arxiv_id", ""))
    if date_info:
        year, month = date_info
        lines.append(f"PY  - {year}/{month.zfill(2)}/")

    for category in record.get("categories", []):
        lines.append(f"KW  - {category}")

    if "doi" in record:
        lines.append(f"DO  - {record['doi']}")

    if "url" in record:
        lines.append(f"UR  - {record['url']}")

    if "arxiv_id" in record:
        lines.append(f"M3  - {record['arxiv_id']}")

    lines.append("ER  - ")

    return "\n".join(lines)
