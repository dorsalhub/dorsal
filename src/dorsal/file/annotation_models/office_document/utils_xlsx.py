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

R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

XLSX_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

NS_MAP = BASE_NS_MAP.copy()
NS_MAP.update(
    {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    }
)

WORKSHEET_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
SHARED_STRINGS_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"

CELL_REF_RX = re.compile(r"([A-Z]+)(\d+)")


def _col_letter_to_int(col_str: str) -> int:
    """Converts a column letter (A, B, ... Z, AA, AB) to its 1-based index."""
    num = 0
    for c in col_str:
        num = num * 26 + (ord(c.upper()) - ord("A")) + 1
    return num


def _parse_dimension_ref(ref_str: str | None) -> tuple[int | None, int | None]:
    """Parses a dimension string (e.g., 'A1:F10' or 'C5') into (row_count, col_count)."""
    if not ref_str:
        return None, None

    if ":" in ref_str:
        _, end_ref = ref_str.split(":")
    else:
        end_ref = ref_str

    match = CELL_REF_RX.match(end_ref)
    if not match:
        return None, None

    try:
        col_str = match.group(1)
        row_str = match.group(2)
        return int(row_str), _col_letter_to_int(col_str)
    except Exception as e:
        logger.warning(f"Failed to parse dimension reference: '{end_ref}': {e}")
        return None, None


def _get_cell_value(cell_el: ET.Element | None, shared_strings: list[str]) -> Any | None:
    """Gets the value from a <c> cell element, looking up shared strings if needed."""
    if cell_el is None:
        return None

    val_el = _find_xml_element(cell_el, "m:v", NS_MAP)

    if val_el is None or val_el.text is None:
        return None

    cell_type = cell_el.get("t")

    try:
        if cell_type == "s":  # Shared String
            return shared_strings[int(val_el.text)]
        if cell_type == "b":  # Boolean
            return bool(int(val_el.text))
        if cell_type == "str":  # Inline String
            return val_el.text
        if cell_type == "e":  # Error
            logger.debug(f"Ignoring cell with error value: {val_el.text}")
            return None
        if cell_type == "n" or cell_type is None:  # Number
            try:
                if "." in val_el.text:
                    return float(val_el.text)
                return int(val_el.text)
            except ValueError:
                return val_el.text
        return val_el.text
    except (IndexError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse cell value (type={cell_type}, val='{val_el.text}'): {e}")
        return None


def _parse_shared_strings(xml_root: ET.Element | None) -> list[str]:
    """Parses the sharedStrings.xml file into a simple list."""
    if xml_root is None:
        return []

    strings: list[str] = []

    for si_el in _findall_xml_elements(xml_root, "m:si", NS_MAP):
        text_parts = [t.text for t in _findall_xml_elements(si_el, ".//m:t", NS_MAP) if t.text]
        strings.append("".join(text_parts))
    return strings


def _parse_worksheet(xml_root: ET.Element | None, shared_strings: list[str]) -> dict[str, Any]:
    """Parses a single sheetN.xml file for dimensions and column headers."""
    if xml_root is None:
        return {"row_count": None, "column_count": None, "column_names": []}

    dim_el = _find_xml_element(xml_root, "m:dimension", NS_MAP)
    row_count, col_count = _parse_dimension_ref(dim_el.get("ref") if dim_el is not None else None)

    column_names: list[str] = []
    row_1 = _find_xml_element(xml_root, "m:sheetData/m:row[@r='1']", NS_MAP)

    if row_1 is not None:
        for cell_el in _findall_xml_elements(row_1, "m:c", NS_MAP):
            val = _get_cell_value(cell_el, shared_strings)
            if val is not None:
                column_names.append(str(val))

    return {"row_count": row_count, "column_count": col_count, "column_names": column_names}


def _parse_excel_properties(
    workbook_root: ET.Element | None,
    workbook_rels_root: ET.Element | None,
    shared_strings_root: ET.Element | None,
    z: zipfile.ZipFile,
) -> dict[str, Any]:
    """Parses workbook.xml and all associated worksheets. Returns a dict."""

    if workbook_root is None:
        return {"active_sheet_name": None, "sheet_names": [], "sheets": [], "has_macros": None}

    shared_strings = _parse_shared_strings(shared_strings_root)

    rId_to_path_map: dict[str, str] = {}
    if workbook_rels_root is not None:
        for el in workbook_rels_root.findall(f"{RELS_NS}Relationship"):
            if el.get("Type") == WORKSHEET_TYPE:
                rId = el.get("Id")
                target = el.get("Target")
                if rId and target:
                    rId_to_path_map[rId] = f"xl/{target.lstrip('/')}"

    sheet_names: list[str] = []
    sheet_info_list: list[dict[str, Any]] = []

    sheets_el = _find_xml_element(workbook_root, "m:sheets", NS_MAP)

    if sheets_el is not None:
        for sheet_el in _findall_xml_elements(sheets_el, "m:sheet", NS_MAP):
            name = sheet_el.get("name")
            rId = sheet_el.get(f"{R_NS}id")
            if name and rId:
                sheet_info_list.append(
                    {
                        "name": name,
                        "rId": rId,
                        "state": sheet_el.get("state"),
                    }
                )
                sheet_names.append(name)

    active_sheet_name: str | None = None
    view_el = _find_xml_element(workbook_root, "m:bookViews/m:workbookView", NS_MAP)

    if view_el is not None:
        try:
            active_tab_index = int(view_el.get("activeTab", "0"))
            if 0 <= active_tab_index < len(sheet_names):
                active_sheet_name = sheet_names[active_tab_index]
        except (ValueError, TypeError):
            pass

    sheets: list[dict[str, Any]] = []
    for sheet_info in sheet_info_list:
        sheet_path = rId_to_path_map.get(sheet_info["rId"])
        if not sheet_path:
            logger.warning(
                f"Sheet '{sheet_info['name']}' (rId: {sheet_info['rId']}) found in workbook but not in rels."
            )
            continue

        sheet_root = _read_xml_from_zip(z, sheet_path)

        sheet_data_dict = _parse_worksheet(sheet_root, shared_strings)

        sheet_data_dict["name"] = sheet_info["name"]
        sheet_data_dict["is_hidden"] = sheet_info.get("state") == "hidden"

        sheets.append(sheet_data_dict)

    return {
        "active_sheet_name": active_sheet_name,
        "sheet_names": sheet_names,
        "sheets": sheets,
        "has_macros": None,
    }


def extract_xlsx_metadata(file_path: str) -> dict[str, Any] | None:
    """
    Extracts metadata from a .xlsx file and returns it as a dictionary.
    """
    final_data: dict[str, Any] = {}
    excel_specific_data: dict[str, Any] = {}
    is_password_protected = False

    core_props_path: str | None = None
    app_props_path: str | None = None
    shared_strings_path: str | None = None

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

            workbook_root = _read_xml_from_zip(z, "xl/workbook.xml")
            workbook_rels_root = _read_xml_from_zip(z, "xl/_rels/workbook.xml.rels")

            if workbook_rels_root is not None:
                ss_target = _find_relationship_target(workbook_rels_root, SHARED_STRINGS_TYPE)
                if ss_target:
                    shared_strings_path = f"xl/{ss_target.lstrip('/')}"

            shared_strings_root = _read_xml_from_zip(z, shared_strings_path or "xl/sharedStrings.xml")

            core_data = _parse_core_properties(core_root, NS_MAP)
            app_data, _ = _parse_app_properties(app_root, NS_MAP)
            ct_data = _parse_content_types_xml(ct_root)
            custom_data = _parse_custom_properties_xml(custom_props_root, NS_MAP)

            excel_specific_data = _parse_excel_properties(workbook_root, workbook_rels_root, shared_strings_root, z)

            final_data.update(core_data)
            final_data.update(app_data)
            final_data.update(ct_data)
            final_data.update(custom_data)

            if "structural_parts" in final_data:
                parts = final_data.get("structural_parts", [])
                if (
                    "application/vnd.ms-excel.sheet.macroEnabled.main+xml" in parts
                    or "application/vnd.ms-office.vbaProject" in parts
                ):
                    excel_specific_data["has_macros"] = True
                elif parts:
                    excel_specific_data["has_macros"] = False

    except zipfile.BadZipFile:
        logger.warning("File is not a valid ZIP (corrupt, password-protected, or owner file): '%s'", file_path)
        is_password_protected = True
    except Exception as e:
        logger.error(f"Unexpected error opening xlsx zip file '{file_path}': {e}", exc_info=True)
        return None

    final_data["is_password_protected"] = is_password_protected
    final_data["word"] = None
    final_data["excel"] = excel_specific_data
    final_data["powerpoint"] = None

    found_data_keys = [
        k
        for k, v in final_data.items()
        if (v not in [None, [], {}]) and (k not in ["is_password_protected", "word", "excel", "powerpoint"])
    ]
    found_excel_keys = [k for k, v in excel_specific_data.items() if (v not in [None, [], {}])]

    if not found_data_keys and not found_excel_keys:
        if is_password_protected:
            return {"is_password_protected": True}

        logger.warning("Could not extract any metadata from '%s'. File is likely minimal or empty.", file_path)
        return None

    return final_data
