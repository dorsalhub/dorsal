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

logger = logging.getLogger(__name__)

P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

NS_MAP = BASE_NS_MAP.copy()
NS_MAP.update(
    {
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
)

SLIDE_MASTER_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"


def _parse_presentation_xml(xml_root: ET.Element | None) -> dict[str, Any]:
    """Extracts slide count from presentation.xml."""
    if xml_root is None:
        return {"slide_count": None}

    slide_id_list_el = _find_xml_element(xml_root, "p:sldIdLst", NS_MAP)

    if slide_id_list_el is None:
        return {"slide_count": 0}

    slide_ids = _findall_xml_elements(slide_id_list_el, "p:sldId", NS_MAP)

    return {"slide_count": len(slide_ids)}


def extract_pptx_metadata(file_path: str) -> dict[str, Any] | None:
    """
    Extracts metadata from a .pptx file and returns it as a dictionary.
    """
    final_data: dict[str, Any] = {}
    powerpoint_specific_data: dict[str, Any] = {}
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

            pres_root = _read_xml_from_zip(z, "ppt/presentation.xml")

            core_data = _parse_core_properties(core_root, NS_MAP)

            app_data, _ = _parse_app_properties(app_root, NS_MAP)
            ct_data = _parse_content_types_xml(ct_root)
            custom_data = _parse_custom_properties_xml(custom_props_root, NS_MAP)

            pres_data = _parse_presentation_xml(pres_root)

            final_data.update(core_data)
            final_data.update(app_data)
            final_data.update(ct_data)
            final_data.update(custom_data)

            powerpoint_specific_data.update(pres_data)

    except zipfile.BadZipFile:
        logger.warning("File is not a valid ZIP (corrupt, password-protected, or owner file): '%s'", file_path)
        is_password_protected = True
    except Exception as e:
        logger.error(f"Unexpected error opening pptx zip file '{file_path}': {e}", exc_info=True)
        return None

    final_data["is_password_protected"] = is_password_protected
    final_data["word"] = None
    final_data["excel"] = None
    final_data["powerpoint"] = powerpoint_specific_data

    found_data_keys = [
        k
        for k, v in final_data.items()
        if (v not in [None, [], {}]) and (k not in ["is_password_protected", "word", "excel", "powerpoint"])
    ]
    found_pptx_keys = [k for k, v in powerpoint_specific_data.items() if (v not in [None, [], {}])]

    if not found_data_keys and not found_pptx_keys:
        if is_password_protected:
            return {"is_password_protected": True}

        logger.warning("Could not extract any metadata from '%s'. File is likely minimal or empty.", file_path)
        return None

    return final_data
