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

import json
from typing import Any

from dorsal.adapters.arxiv.helpers import extract_date_from_id


def _parse_author_name(full_name: str) -> dict[str, str]:
    """Splits a full name string into CSL-JSON 'family' and 'given' parts.

    Note: the `family` and `given` dichotomy
    """
    parts = full_name.strip().split()
    if not parts:
        return {}
    if len(parts) == 1:
        return {"family": parts[0]}

    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def to_csl_json(
    record: dict[str, Any],
    **kwargs: Any,
) -> str:
    """Converts a 'dorsal/arxiv' record into a strictly validated CSL-JSON string."""

    arxiv_id = record.get("arxiv_id", "unknown")

    csl_item: dict[str, Any] = {
        "id": arxiv_id,
        "type": "article",
        "publisher": "arXiv",
    }

    if "title" in record:
        csl_item["title"] = record["title"]

    if "abstract" in record:
        csl_item["abstract"] = record["abstract"]

    if "authors" in record:
        csl_item["author"] = [_parse_author_name(a) for a in record["authors"]]

    date_info = extract_date_from_id(arxiv_id)
    if date_info:
        year, month = date_info
        csl_item["issued"] = {"date-parts": [[int(year), int(month)]]}

    if "url" in record:
        csl_item["URL"] = record["url"]
    elif arxiv_id != "unknown":
        csl_item["URL"] = f"https://arxiv.org/abs/{arxiv_id}"

    if "doi" in record:
        csl_item["DOI"] = record["doi"]

    if arxiv_id != "unknown":
        csl_item["number"] = arxiv_id

    return json.dumps([csl_item], indent=2)
