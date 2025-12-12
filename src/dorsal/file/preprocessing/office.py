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

logger = logging.getLogger(__name__)

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_docx_text(file_path: str) -> list[str]:
    """
    Extracts text from a .docx file using the standard library.

    Returns a list of strings, where each string represents a 'page'.

    NOTE: .docx is flow-based, so 'pages' are not strictly defined,
          so this function splits only on explicit page breaks
    """
    try:
        with zipfile.ZipFile(file_path) as zf:
            xml_content = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        logger.error(f"Failed to read .docx structure: {e}")
        return []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error(f"Failed to parse XML content: {e}")
        return []

    pages = []
    current_page_text = []

    W_P = f"{{{NS['w']}}}p"  # Paragraph
    W_T = f"{{{NS['w']}}}t"  # Text
    W_TAB = f"{{{NS['w']}}}tab"  # Tab
    W_BR = f"{{{NS['w']}}}br"  # Line/Page Break

    for elem in root.iter():
        if elem.tag == W_P:
            current_page_text.append("\n")

        elif elem.tag == W_T:
            if elem.text:
                current_page_text.append(elem.text)

        elif elem.tag == W_TAB:
            current_page_text.append("\t")

        elif elem.tag == W_BR:
            br_type = elem.get(f"{{{NS['w']}}}type")
            if br_type == "page":
                pages.append("".join(current_page_text).strip())
                current_page_text = []
            else:
                current_page_text.append("\n")

    if current_page_text:
        pages.append("".join(current_page_text).strip())

    return pages
