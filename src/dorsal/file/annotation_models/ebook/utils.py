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
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, List, Dict, Optional
from datetime import datetime

from dorsal.common.language import normalize_language_name, extract_locale_code, normalize_language_alpha3
from dorsal.file.utils.dates import PDF_DATETIME

logger = logging.getLogger(__name__)

NS_MAP = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

HTML_TAG_RX = re.compile(r"<[^>]+>")
ISBN_RX = re.compile(r"(?:ISBN[ \t]*:?|urn:isbn:)\s*([0-9]{9,12}[0-9X])")
CLEAN_ISBN_RX = re.compile(r"^([0-9]{9}[0-9X]|[0-9]{13})$")
PLACEHOLDER_DATE_RX = re.compile(r"^(0001|0101)-01-01")
TOOL_RX = re.compile(
    r"^(calibre|ibooks author|smashwords|adobe|kindle|pressbooks|libreoffice|easypress|innodata|pyscript)",
    re.IGNORECASE,
)


def _strip_html(text: str | None) -> str | None:
    """Removes HTML tags from a string. Returns None if result is empty."""
    if not text:
        return None
    cleaned_text = HTML_TAG_RX.sub("", text).strip()
    return cleaned_text if cleaned_text else None


def _parse_date(date_str: str | None) -> datetime | None:
    """Parses a date string, using the PDFDatetime parser."""
    if not date_str or not PDF_DATETIME:
        return None

    return PDF_DATETIME.parse(date_str)


def _extract_isbn(id_str: str | None) -> str | None:
    """Extracts a valid ISBN-10 or ISBN-13, stripping prefixes."""
    if not id_str:
        return None

    match = ISBN_RX.search(id_str)
    if match:
        return match.group(1).replace("-", "")

    clean_id = id_str.replace("-", "").strip()
    if CLEAN_ISBN_RX.match(clean_id):
        return clean_id

    return None


def _get_meta_text(metadata_el: ET.Element, tag: str) -> str | None:
    """Find a single metadata tag's text (namespace-agnostic)."""
    el = metadata_el.find(f"dc:{tag}", NS_MAP)
    if el is not None and el.text:
        return el.text.strip()
    el = metadata_el.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _get_meta_list(metadata_el: ET.Element, tag: str) -> List[str]:
    """Find all metadata tags (namespace-agnostic) and return text list."""
    elements = metadata_el.findall(f"dc:{tag}", NS_MAP)
    if not elements:
        elements = metadata_el.findall(tag)
    if not elements:
        return []
    return [el.text for el in elements if el.text]


def _get_all_epub_dates(metadata_el: ET.Element) -> dict[str, str | None]:
    """
    Parses all dc:date elements and sorts them by their opf:event.
    """
    event_key = f"{{{NS_MAP['opf']}}}event"
    date_els = metadata_el.findall("dc:date", NS_MAP)
    if not date_els:
        date_els = metadata_el.findall("date")

    dates: dict[str, str | None] = {
        "publication": None,
        "creation": None,
        "modification": None,
        "first_unspecified": None,
    }

    for el in date_els:
        date_str = el.text.strip() if el.text else None
        if not date_str:
            continue

        event = el.get(event_key)

        if event == "publication" and not dates["publication"]:
            dates["publication"] = date_str
        elif event == "modification" and not dates["modification"]:
            dates["modification"] = date_str
        elif event == "creation" and not dates["creation"]:
            dates["creation"] = date_str
        elif event is None and not dates["first_unspecified"]:
            dates["first_unspecified"] = date_str

    return dates


def _get_cover_path(opf_root: ET.Element) -> str | None:
    """
    Finds the cover image path from the <metadata> and <manifest>.
    """
    metadata_el = opf_root.find("opf:metadata", NS_MAP)
    if metadata_el is None:
        return None

    cover_id = None
    for meta_el in metadata_el.findall("opf:meta", NS_MAP) + metadata_el.findall("meta"):
        if meta_el.get("name") == "cover":
            cover_id = meta_el.get("content")
            break

    if not cover_id:
        logger.debug('Could not find <meta name="cover"> tag in metadata.')
        return None

    manifest_el = opf_root.find("opf:manifest", NS_MAP)
    if manifest_el is None:
        logger.debug("Could not find <manifest> element in .opf.")
        return None

    search_paths = [f"opf:item[@id='{cover_id}']", f"item[@id='{cover_id}']"]
    cover_item = None
    for path in search_paths:
        cover_item = manifest_el.find(path, NS_MAP)
        if cover_item is not None:
            break

    if cover_item is None:
        logger.debug("Found cover ID '%s' but no matching <item> in manifest.", cover_id)
        return None

    cover_href = cover_item.get("href")
    if not cover_href:
        logger.debug("Cover <item> '%s' has no 'href' attribute.", cover_id)
        return None

    return cover_href


def extract_epub_metadata(file_path: str) -> dict[str, Any] | None:
    """
    Extracts and normalizes metadata from an EPUB file.
    """
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            try:
                container_data = z.read("META-INF/container.xml")
            except KeyError:
                logger.debug("META-INF/container.xml not found in '%s'.", file_path)
                return None
            container_root = ET.fromstring(container_data)
            opf_path_el = container_root.find("c:rootfiles/c:rootfile", NS_MAP)
            if opf_path_el is None:
                logger.debug("Could not find .opf file path in container.xml for '%s'.", file_path)
                return None
            opf_path = opf_path_el.get("full-path")
            if not opf_path:
                logger.debug("Invalid container.xml in '%s' (no full-path).", file_path)
                return None

            opf_data = z.read(opf_path)
            opf_root = ET.fromstring(opf_data)

            metadata_el = opf_root.find("opf:metadata", NS_MAP)
            if metadata_el is None:
                logger.debug("Could not find <metadata> element in .opf for '%s'.", file_path)
                return None

            raw_identifiers = _get_meta_list(metadata_el, "identifier")
            isbn = None
            other_identifiers = []

            for id_str in raw_identifiers:
                if not id_str:
                    continue

                found_isbn = _extract_isbn(id_str)
                if found_isbn and not isbn:
                    isbn = found_isbn
                else:
                    other_identifiers.append(id_str.strip())

            tool_name_from_meta = None
            for meta_el in metadata_el.findall("opf:meta", NS_MAP) + metadata_el.findall("meta"):
                if meta_el.get("name") in ("generator", "producer"):
                    tool_name_from_meta = meta_el.get("content")
                    if tool_name_from_meta:
                        break

            raw_contributors = _get_meta_list(metadata_el, "contributor")
            final_contributors = []
            final_tools = []

            if tool_name_from_meta:
                final_tools.append(tool_name_from_meta.strip())

            for entry in raw_contributors:
                if not entry:
                    continue

                if TOOL_RX.search(entry):
                    final_tools.append(entry.strip())
                else:
                    final_contributors.append(entry.strip())

            all_dates = _get_all_epub_dates(metadata_el)
            pub_date_str = (
                all_dates.get("publication")
                or all_dates.get("creation")
                or all_dates.get("first_unspecified")
                or all_dates.get("modification")
            )

            raw_lang_str = _get_meta_text(metadata_el, "language")

            metadata = {
                "title": _get_meta_text(metadata_el, "title"),
                "authors": _get_meta_list(metadata_el, "creator"),
                "contributors": final_contributors,
                "publisher": _get_meta_text(metadata_el, "publisher"),
                "language": normalize_language_name(raw_lang_str),
                "language_code": normalize_language_alpha3(raw_lang_str),
                "locale_code": extract_locale_code(raw_lang_str),
                "subjects": _get_meta_list(metadata_el, "subject"),
                "description": _strip_html(_get_meta_text(metadata_el, "description")),
                "rights": _get_meta_text(metadata_el, "rights"),
                "isbn": isbn,
                "other_identifiers": other_identifiers,
                "cover_path": _get_cover_path(opf_root),
                "tools": list(set(final_tools)),
                "publication_date": _parse_date(pub_date_str),
                "creation_date": _parse_date(all_dates.get("creation")),
                "modification_date": _parse_date(all_dates.get("modification")),
            }

            return metadata

    except zipfile.BadZipFile:
        logger.warning("File is not a valid ZIP archive (may be corrupt or DRM-protected): '%s'", file_path)
        return None
    except ET.ParseError:
        logger.warning("Failed to parse XML from ebook: '%s'", file_path)
        return None
    except Exception as e:
        logger.warning("Failed to parse EPUB file '%s': %s", file_path, e, exc_info=True)
        return None


def extract_mobi_metadata(file_path: str) -> dict[str, Any] | None:
    """STUB for extracting metadata from a MOBI file."""
    logger.warning("MOBI metadata extraction is not implemented (file: %s).", file_path)
    return None
