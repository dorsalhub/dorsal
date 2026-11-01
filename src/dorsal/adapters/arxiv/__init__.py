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

from dorsal.adapters.arxiv.validation import ARXIV_SCHEMA_ID

_MODULE = "dorsal.adapters.arxiv"

ARXIV_FORMATS: tuple[tuple[str, str, str, str, str | None, tuple[str, ...]], ...] = (
    ("bibtex", "BibTeX (.bib) - A bibliographic reference format.", "bib", "bibtex:to_bibtex", None, ("bib",)),
    ("md", "Markdown (.md) - A RAG-optimized markdown document.", "md", "md:to_md", "md:from_md", ("markdown",)),
    ("ris", "RIS (.ris) - A standard reference manager format.", "ris", "ris:to_ris", None, ()),
    (
        "csl-json",
        "CSL-JSON (.json) - Citation Style Language JSON format.",
        "csl.json",
        "csl_json:to_csl_json",
        None,
        ("csl",),
    ),
)


def register_arxiv_adapters() -> None:
    """Register the `dorsal/arxiv` exporters with `oatschema_adapters`, skipping formats already registered."""
    from oatschema_adapters import list_formats, register_adapter

    registered = {name for name, _ in list_formats(ARXIV_SCHEMA_ID)}
    for name, description, extension, export, parse, aliases in ARXIV_FORMATS:
        if name in registered:
            continue
        register_adapter(
            ARXIV_SCHEMA_ID,
            name,
            description=description,
            extension=extension,
            export=f"{_MODULE}.{export}",
            parse=f"{_MODULE}.{parse}" if parse else None,
            aliases=aliases,
        )


__all__ = ["ARXIV_SCHEMA_ID", "register_arxiv_adapters"]
