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
from typing import Any

from dorsal.file.utils.dates import PDF_DATETIME

logger = logging.getLogger(__name__)

RELS_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
CP_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
VT_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"


BASE_NS_MAP = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "cpcp": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}

CORE_PROPS_TYPE = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
APP_PROPS_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"

DEFAULT_CORE_PROPS_PATH = "docProps/core.xml"
DEFAULT_APP_PROPS_PATH = "docProps/app.xml"

KEYWORD_SPLIT_RX = re.compile(r"[;,]")


def _split_keywords(kw_str: str | None) -> list[str]:
    if not kw_str:
        return []
    return [k.strip() for k in KEYWORD_SPLIT_RX.split(kw_str) if k.strip()]


def _find_xml_element(xml_root: ET.Element | None, namespaced_path: str, ns_map: dict[str, str]) -> ET.Element | None:
    """
    Robust helper to find an XML element.
    Tries the namespaced path first, then falls back to a non-namespaced path.
    """
    if xml_root is None:
        return None

    el = xml_root.find(namespaced_path, ns_map)

    if el is None:
        local_name = namespaced_path.split(":")[-1]
        el = xml_root.find(local_name)

    return el


def _findall_xml_elements(
    xml_root: ET.Element | None, namespaced_path: str, ns_map: dict[str, str]
) -> list[ET.Element]:
    """
    Robust helper to find all XML elements.
    Tries the namespaced path first, then falls back to a non-namespaced path.
    """
    if xml_root is None:
        return []

    elements = xml_root.findall(namespaced_path, ns_map)

    if not elements:
        local_name = namespaced_path.split(":")[-1]
        elements = xml_root.findall(local_name)

    return elements


def _get_xml_text(xml_root: ET.Element | None, namespaced_path: str, ns_map: dict[str, str]) -> str | None:
    """
    Robust v6 helper to find text in an XML element.
    Uses the robust _find_xml_element helper.
    """
    el = _find_xml_element(xml_root, namespaced_path, ns_map)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _get_xml_text_as_int(xml_root: ET.Element | None, namespaced_path: str, ns_map: dict[str, str]) -> int | None:
    text = _get_xml_text(xml_root, namespaced_path, ns_map)
    if text and text.isdigit():
        return int(text)
    return None


def _parse_date(date_str: str | None) -> Any:
    if not date_str or not PDF_DATETIME:
        return None
    return PDF_DATETIME.parse(date_str)


def _find_relationship_target(rels_root: ET.Element | None, type_url: str) -> str | None:
    """Parses a .rels file to find the 'Target' for a given 'Type'."""
    if rels_root is None:
        return None

    for el in rels_root.findall(f"{RELS_NS}Relationship"):
        if el.get("Type") == type_url:
            target = el.get("Target")
            if target:
                return target.lstrip("/")
    return None


def _read_xml_from_zip(z: zipfile.ZipFile, path: str) -> ET.Element | None:
    """Robust helper to read and parse an XML file from a zip."""
    try:
        xml_data = z.read(path)
        return ET.fromstring(xml_data)
    except KeyError:
        logger.debug(f"[v6] XML file not found in zip: '{path}'")
    except ET.ParseError as e:
        logger.warning(f"[v6] Failed to parse XML file '{path}': {e}")
    except Exception as e:
        logger.error(f"[v6] Unexpected error reading '{path}': {e}", exc_info=True)
    return None


def _parse_core_properties(xml_root: ET.Element | None, ns_map: dict[str, str]) -> dict[str, Any]:
    """Extracts metadata from the core.xml element tree."""
    if xml_root is None:
        return {}
    return {
        "author": _get_xml_text(xml_root, "dc:creator", ns_map),
        "last_modified_by": _get_xml_text(xml_root, "cp:lastModifiedBy", ns_map),
        "title": _get_xml_text(xml_root, "dc:title", ns_map),
        "subject": _get_xml_text(xml_root, "dc:subject", ns_map),
        "keywords": _split_keywords(_get_xml_text(xml_root, "cp:keywords", ns_map)),
        "revision": _get_xml_text_as_int(xml_root, "cp:revision", ns_map),
        "creation_date": _parse_date(_get_xml_text(xml_root, "dcterms:created", ns_map)),
        "modified_date": _parse_date(_get_xml_text(xml_root, "dcterms:modified", ns_map)),
    }


def _parse_app_properties(xml_root: ET.Element | None, ns_map: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extracts metadata from the app.xml element tree."""
    if xml_root is None:
        return {}, {}

    app_data = {
        "application_name": _get_xml_text(xml_root, "ep:Application", ns_map),
        "application_version": _get_xml_text(xml_root, "ep:AppVersion", ns_map),
        "template": _get_xml_text(xml_root, "ep:Template", ns_map),
    }
    word_specific_data = {
        "page_count": _get_xml_text_as_int(xml_root, "ep:Pages", ns_map),
        "word_count": _get_xml_text_as_int(xml_root, "ep:Words", ns_map),
        "char_count": _get_xml_text_as_int(xml_root, "ep:Characters", ns_map),
        "paragraph_count": _get_xml_text_as_int(xml_root, "ep:Paragraphs", ns_map),
    }
    return app_data, word_specific_data


def _parse_content_types_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts structural parts and has_comments from [Content_Types].xml."""
    if xml_root is None:
        return {}
    parts = []
    has_comments = False

    for el in xml_root.findall(f"{CT_NS}Default") + xml_root.findall(f"{CT_NS}Override"):
        part = el.get("ContentType")
        if part:
            parts.append(part)
            if not has_comments and "comments" in part:
                has_comments = True

    return {"structural_parts": sorted(list(set(parts))), "has_comments": has_comments}


def _parse_custom_properties_xml(xml_root: ET.Element | None, ns_map: dict[str, str]) -> dict[str, Any]:
    """Extracts key-value pairs from custom.xml."""
    if xml_root is None:
        return {}
    props = {}

    for el in _findall_xml_elements(xml_root, "cpcp:property", ns_map):
        name = el.get("name")
        if not name:
            continue

        val_el = next(iter(el), None)
        if val_el is not None and val_el.text:
            props[name] = val_el.text.strip()

    return {"custom_properties": props}
