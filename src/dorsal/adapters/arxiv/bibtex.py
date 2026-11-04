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


def to_bibtex(
    record: dict[str, Any],
    **kwargs: Any,
) -> str:
    """Converts a 'dorsal/arxiv' record into a BibTeX citation."""

    arxiv_id = record.get("arxiv_id", "unknown")

    citation_key = arxiv_id.replace("/", "_").replace(".", "_")

    authors = record.get("authors", [])
    author_str = " and ".join(authors)

    lines = [f"@misc{{{citation_key},"]

    if "title" in record:
        lines.append(f"  title = {{{record['title']}}},")
    if author_str:
        lines.append(f"  author = {{{author_str}}},")

    lines.append(f"  eprint = {{{arxiv_id}}},")
    lines.append("  archivePrefix = {arXiv},")

    categories = record.get("categories", [])
    if categories:
        lines.append(f"  primaryClass = {{{categories[0]}}},")

    if record.get("doi"):
        lines.append(f"  doi = {{{record['doi']}}},")
    if record.get("url"):
        lines.append(f"  url = {{{record['url']}}},")

    date_info = extract_date_from_id(arxiv_id)
    if date_info:
        year, month = date_info
        lines.append(f"  year = {{{year}}},")
        lines.append(f"  month = {{{month}}},")

    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]

    lines.append("}")

    return "\n".join(lines)
