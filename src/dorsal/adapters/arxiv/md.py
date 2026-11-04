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


def to_md(
    record: dict[str, Any],
    *,
    validate: bool = False,
    **kwargs: Any,
) -> str:
    """Converts a 'dorsal/arxiv' record into a RAG-optimized Markdown document."""
    if is_enabled(validate):
        validate_record(record, schema_id="dorsal/arxiv")

    lines = ["---"]
    arxiv_id = record.get("arxiv_id", "unknown")
    lines.append(f"arxiv_id: {arxiv_id}")

    date_info = extract_date_from_id(arxiv_id)
    if date_info:
        year, month = date_info
        lines.append(f"year: {year}")
        lines.append(f"month: {month}")

    if record.get("categories"):
        lines.append(f"categories: [{', '.join(record['categories'])}]")

    if record.get("doi"):
        lines.append(f"doi: {record['doi']}")

    lines.append("---")
    lines.append("")

    if "title" in record:
        lines.append(f"# {record['title']}")
        lines.append("")

    if "authors" in record:
        lines.append(f"**Authors:** {', '.join(record['authors'])}")
        lines.append("")

    if "abstract" in record:
        lines.append("## Abstract")
        lines.append(record["abstract"])

    return "\n".join(lines)


def from_md(content: str, *, validate: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Parses a Markdown string back into a 'dorsal/arxiv' record."""
    if not content.strip():
        raise ValueError("Provided Markdown content is empty.")

    record: dict[str, Any] = {"categories": [], "authors": []}

    frontmatter_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
    if frontmatter_match:
        fm_text = frontmatter_match.group(1)
        for line in fm_text.splitlines():
            if line.startswith("arxiv_id:"):
                record["arxiv_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("doi:"):
                record["doi"] = line.split(":", 1)[1].strip()
            elif line.startswith("categories:"):
                cats = line.split(":", 1)[1].strip().strip("[]")
                record["categories"] = [c.strip() for c in cats.split(",") if c.strip()]

    title_match = re.search(r"^#\s+(.*?)$", content, re.MULTILINE)
    if title_match:
        record["title"] = title_match.group(1).strip()

    authors_match = re.search(r"^\*\*Authors:\*\*\s+(.*?)$", content, re.MULTILINE)
    if authors_match:
        record["authors"] = [a.strip() for a in authors_match.group(1).split(",")]

    abstract_match = re.search(r"^## Abstract\n(.*?)(?=^#|\Z)", content, re.MULTILINE | re.DOTALL)
    if abstract_match:
        record["abstract"] = abstract_match.group(1).strip()

    if is_enabled(validate):
        validate_record(record, schema_id="dorsal/arxiv")

    return record
