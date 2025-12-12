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
import zipfile
import xml.etree.ElementTree as ET
from typing import Any


from .utils import (
    RELS_NS,
    CORE_PROPS_TYPE,
    APP_PROPS_TYPE,
    DEFAULT_CORE_PROPS_PATH,
    DEFAULT_APP_PROPS_PATH,
    BASE_NS_MAP,
    _find_relationship_target,
    _read_xml_from_zip,
    _parse_core_properties,
    _parse_app_properties,
    _parse_content_types_xml,
    _parse_custom_properties_xml,
    _find_xml_element,
    _findall_xml_elements,
)
from dorsal.common.language import normalize_language_name, extract_locale_code, normalize_language_alpha3

logger = logging.getLogger(__name__)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

NS_MAP = BASE_NS_MAP.copy()
NS_MAP.update(
    {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
)

HYPERLINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
IMAGE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
COMMENTS_TYPE = "http://schemas.openxmlformats.org/wordprocessingml/2006/relationships/comments"


def _parse_settings_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts language and track_changes from settings.xml."""
    if xml_root is None:
        return {}

    lang_el = _find_xml_element(xml_root, "w:lang", NS_MAP)
    if lang_el is None:
        lang_el = _find_xml_element(xml_root, "w:themeFontLang", NS_MAP)

    raw_lang_str = lang_el.get(f"{W_NS}val") if lang_el is not None else None
    track_changes_el = _find_xml_element(xml_root, "w:trackRevisions", NS_MAP)

    return {
        "language": normalize_language_name(raw_lang_str),
        "language_code": normalize_language_alpha3(raw_lang_str),
        "locale_code": extract_locale_code(raw_lang_str),
        "has_track_changes": (track_changes_el is not None),
    }


def _parse_styles_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts default font from styles.xml."""
    font_el = _find_xml_element(xml_root, "w:docDefaults/w:rPrDefault/w:rPr/w:rFonts", NS_MAP)
    font_text = font_el.get(f"{W_NS}ascii") if font_el is not None else None
    return {"default_font": font_text}


def _parse_font_table_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts all declared fonts from fontTable.xml."""
    if xml_root is None:
        return {"all_fonts": []}
    fonts = []
    for el in _findall_xml_elements(xml_root, "w:font", NS_MAP):
        font_name = el.get(f"{W_NS}name")
        if font_name:
            fonts.append(font_name)
    return {"all_fonts": sorted(list(set(fonts)))}


def _parse_document_rels_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts hyperlinks and embedded image paths from document.xml.rels."""
    if xml_root is None:
        return {"hyperlinks": [], "embedded_images": []}
    hyperlinks = []
    images = []
    for el in xml_root.findall(f"{RELS_NS}Relationship"):
        rel_type = el.get("Type")
        if rel_type == HYPERLINK_TYPE:
            target = el.get("Target")
            if target:
                hyperlinks.append(target)
        elif rel_type == IMAGE_TYPE:
            target = el.get("Target")
            if target:
                images.append(target)
    return {"hyperlinks": sorted(list(set(hyperlinks))), "embedded_images": sorted(list(set(images)))}


def extract_docx_metadata(file_path: str) -> dict[str, Any] | None:
    """
    Extracts metadata from a .docx file and returns it as a dictionary.
    """
    final_data: dict[str, Any] = {}
    word_specific_data: dict[str, Any] = {}
    is_password_protected = False

    core_props_path: str | None = None
    app_props_path: str | None = None

    try:
        with zipfile.ZipFile(file_path, "r") as z:
            rels_root = _read_xml_from_zip(z, "_rels/.rels")
            if rels_root is None:
                logger.warning("File is not a valid OOXML (missing _rels/.rels): '%s'", file_path)
                return None

            core_props_path = _find_relationship_target(rels_root, CORE_PROPS_TYPE)
            app_props_path = _find_relationship_target(rels_root, APP_PROPS_TYPE)

            if core_props_path is None:
                core_props_path = DEFAULT_CORE_PROPS_PATH
            if app_props_path is None:
                app_props_path = DEFAULT_APP_PROPS_PATH

            core_root = _read_xml_from_zip(z, core_props_path)
            app_root = _read_xml_from_zip(z, app_props_path)
            ct_root = _read_xml_from_zip(z, "[Content_Types].xml")
            custom_props_root = _read_xml_from_zip(z, "docProps/custom.xml")

            settings_root = _read_xml_from_zip(z, "word/settings.xml")
            styles_root = _read_xml_from_zip(z, "word/styles.xml")
            font_table_root = _read_xml_from_zip(z, "word/fontTable.xml")
            doc_rels_root = _read_xml_from_zip(z, "word/_rels/document.xml.rels")

            core_data = _parse_core_properties(core_root, NS_MAP)
            app_data, word_data = _parse_app_properties(app_root, NS_MAP)
            ct_data = _parse_content_types_xml(ct_root)
            custom_data = _parse_custom_properties_xml(custom_props_root, NS_MAP)

            settings_data = _parse_settings_xml(settings_root)
            styles_data = _parse_styles_xml(styles_root)
            font_data = _parse_font_table_xml(font_table_root)
            rels_data = _parse_document_rels_xml(doc_rels_root)

            final_data.update(core_data)
            final_data.update(app_data)
            final_data.update(ct_data)
            final_data.update(settings_data)
            final_data.update(styles_data)
            final_data.update(font_data)
            final_data.update(custom_data)

            word_specific_data.update(word_data)
            word_specific_data.update(rels_data)

            if "has_track_changes" in final_data:
                word_specific_data["has_track_changes"] = final_data.pop("has_track_changes")

    except zipfile.BadZipFile:
        logger.warning("File is not a valid ZIP (corrupt, password-protected, or owner file): '%s'", file_path)
        is_password_protected = True
    except Exception as e:
        logger.error(f"Unexpected error opening docx zip file '{file_path}': {e}", exc_info=True)
        return None

    final_data["is_password_protected"] = is_password_protected

    final_data["excel"] = None
    final_data["powerpoint"] = None
    final_data["word"] = word_specific_data

    found_data_keys = [
        k
        for k, v in final_data.items()
        if (v not in [None, [], {}]) and (k not in ["is_password_protected", "word", "excel", "powerpoint"])
    ]
    found_word_keys = [k for k, v in word_specific_data.items() if v not in [None, [], {}]]

    if not found_data_keys and not found_word_keys:
        if is_password_protected:
            return {"is_password_protected": True}

        logger.warning("Could not extract any metadata from '%s'. File is likely minimal or empty.", file_path)
        return None

    return final_data
