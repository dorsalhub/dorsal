# Copyright 2025-2026 Dorsal Hub LTD
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

from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET
import zipfile

from dorsal.file.annotation_models.office_document import utils_xlsx


def test_col_letter_to_int():
    """Test conversion of Excel column letters to 1-based indices."""
    assert utils_xlsx._col_letter_to_int("A") == 1
    assert utils_xlsx._col_letter_to_int("Z") == 26
    assert utils_xlsx._col_letter_to_int("AA") == 27
    assert utils_xlsx._col_letter_to_int("AB") == 28
    assert utils_xlsx._col_letter_to_int("AZ") == 52
    assert utils_xlsx._col_letter_to_int("BA") == 53


def test_parse_dimension_ref():
    """Test parsing of worksheet dimension strings."""

    assert utils_xlsx._parse_dimension_ref("A1:C3") == (3, 3)

    assert utils_xlsx._parse_dimension_ref("C5") == (5, 3)

    assert utils_xlsx._parse_dimension_ref(None) == (None, None)

    assert utils_xlsx._parse_dimension_ref("Invalid") == (None, None)


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._find_xml_element")
def test_get_cell_value(mock_find):
    """Test extraction of values from cell XML elements."""
    shared_strings = ["Apple", "Banana"]

    cell_s = ET.Element("c", {"t": "s"})

    val_el = ET.Element("v")
    val_el.text = "1"
    mock_find.return_value = val_el

    val = utils_xlsx._get_cell_value(cell_s, shared_strings)
    assert val == "Banana"

    cell_n = ET.Element("c", {"t": "n"})
    val_el.text = "42"
    mock_find.return_value = val_el
    val = utils_xlsx._get_cell_value(cell_n, shared_strings)
    assert val == 42

    cell_b = ET.Element("c", {"t": "b"})
    val_el.text = "1"
    mock_find.return_value = val_el
    val = utils_xlsx._get_cell_value(cell_b, shared_strings)
    assert val is True

    cell_str = ET.Element("c", {"t": "str"})
    val_el.text = "Raw Text"
    mock_find.return_value = val_el
    val = utils_xlsx._get_cell_value(cell_str, shared_strings)
    assert val == "Raw Text"

    mock_find.return_value = None
    val = utils_xlsx._get_cell_value(cell_s, shared_strings)
    assert val is None


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._findall_xml_elements")
def test_parse_shared_strings(mock_findall):
    """Test parsing the sharedStrings.xml file."""
    root = ET.Element("sst")

    si1 = ET.Element("si")
    t1 = ET.Element("t")
    t1.text = "Hello"

    si2 = ET.Element("si")
    t2 = ET.Element("t")
    t2.text = "World"

    def findall_side_effect(el, tag, ns):
        if tag == "m:si":
            return [si1, si2]
        if tag == ".//m:t":
            if el == si1:
                return [t1]
            if el == si2:
                return [t2]
        return []

    mock_findall.side_effect = findall_side_effect

    result = utils_xlsx._parse_shared_strings(root)
    assert result == ["Hello", "World"]


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._get_cell_value")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._findall_xml_elements")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._find_xml_element")
def test_parse_worksheet(mock_find, mock_findall, mock_get_val):
    """Test parsing dimensions and column headers from a worksheet."""
    root = ET.Element("worksheet")

    dim_el = ET.Element("dimension", {"ref": "A1:C10"})

    row1_el = ET.Element("row")
    cell_a1 = ET.Element("c")
    cell_b1 = ET.Element("c")

    def find_side_effect(el, tag, ns):
        if tag == "m:dimension":
            return dim_el
        if tag == "m:sheetData/m:row[@r='1']":
            return row1_el
        return None

    mock_find.side_effect = find_side_effect

    mock_findall.return_value = [cell_a1, cell_b1]

    mock_get_val.side_effect = ["Header1", "Header2"]

    shared_strings = []
    result = utils_xlsx._parse_worksheet(root, shared_strings)

    assert result["row_count"] == 10
    assert result["column_count"] == 3
    assert result["column_names"] == ["Header1", "Header2"]


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_excel_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_custom_properties_xml")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_content_types_xml")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_app_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_core_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._read_xml_from_zip")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._find_relationship_target")
@patch("zipfile.ZipFile")
def test_extract_xlsx_metadata_success(
    mock_zip_cls, mock_find_rel, mock_read_xml, mock_core, mock_app, mock_ct, mock_custom, mock_excel
):
    """Test the successful extraction of metadata combining all parts."""

    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    mock_read_xml.return_value = ET.Element("mock_root")

    mock_find_rel.side_effect = ["docProps/core.xml", "docProps/app.xml", "xl/sharedStrings.xml"]

    mock_core.return_value = {"author": "Tester"}
    mock_app.return_value = ({"app_version": "1.0"}, None)
    mock_ct.return_value = {"content_types": []}
    mock_custom.return_value = {"custom_k": "v"}
    mock_excel.return_value = {
        "active_sheet_name": "Sheet1",
        "sheets": [{"name": "Sheet1", "row_count": 5}],
        "has_macros": False,
    }

    result = utils_xlsx.extract_xlsx_metadata("dummy.xlsx")

    assert result is not None
    assert result["author"] == "Tester"
    assert result["custom_k"] == "v"
    assert result["excel"]["active_sheet_name"] == "Sheet1"
    assert result["is_password_protected"] is False

    mock_zip_cls.assert_called_with("dummy.xlsx", "r")

    mock_excel.assert_called_once()


@patch("zipfile.ZipFile")
def test_extract_xlsx_metadata_bad_zip(mock_zip_cls):
    """Test handling of corrupt or password protected zip files."""
    mock_zip_cls.side_effect = zipfile.BadZipFile("Bad zip")

    result = utils_xlsx.extract_xlsx_metadata("corrupt.xlsx")

    assert result is not None
    assert result["is_password_protected"] is True


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._read_xml_from_zip")
@patch("zipfile.ZipFile")
def test_extract_xlsx_metadata_empty_rels(mock_zip_cls, mock_read_xml):
    """Test case where _rels/.rels is missing (not a valid OOXML)."""
    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    mock_read_xml.return_value = None

    result = utils_xlsx.extract_xlsx_metadata("invalid.xlsx")
    assert result is None


@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_excel_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_custom_properties_xml")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_content_types_xml")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_app_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._parse_core_properties")
@patch("dorsal.file.annotation_models.office_document.utils_xlsx._read_xml_from_zip")
@patch("zipfile.ZipFile")
def test_extract_xlsx_metadata_has_macros(
    mock_zip_cls, mock_read_xml, mock_core, mock_app, mock_ct, mock_custom, mock_excel
):
    """Test macro detection logic."""
    mock_zip_instance = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance
    mock_read_xml.return_value = ET.Element("root")

    mock_ct.return_value = {"structural_parts": ["application/vnd.ms-office.vbaProject"]}
    mock_core.return_value = {}
    mock_app.return_value = ({}, None)
    mock_custom.return_value = {}

    mock_excel.return_value = {"has_macros": None}

    result = utils_xlsx.extract_xlsx_metadata("macro.xlsm")

    assert result["excel"]["has_macros"] is True
