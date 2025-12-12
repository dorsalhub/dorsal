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

import pytest
from unittest.mock import Mock, MagicMock, patch
import logging
import sys
import zipfile
import xml.etree.ElementTree as ET


from dorsal.file.preprocessing.office import extract_docx_text

# --- Helpers ---

DOC_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def build_docx_xml(body_content: str) -> bytes:
    """
    Wraps content in a valid OpenXML document structure with namespaces.
    Returns bytes, as zipfile.read() returns bytes.
    """
    xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {DOC_NS}>"
        f"<w:body>{body_content}</w:body>"
        f"</w:document>"
    )
    return xml.encode("utf-8")


@pytest.fixture
def mock_zip():
    """
    Patches zipfile.ZipFile to avoid file I/O.
    Returns the mock instance that the context manager yields.
    """
    with patch("zipfile.ZipFile") as MockZipFile:
        mock_instance = MockZipFile.return_value
        # Setup context manager protocol
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        yield mock_instance


# --- Tests ---


class TestExtractDocxText:
    def test_single_page_simple_text(self, mock_zip):
        """Test basic extraction of paragraphs and text."""
        # <w:p><w:r><w:t>Hello World</w:t></w:r></w:p>
        content = "<w:p><w:r><w:t>Hello World</w:t></w:r></w:p>"

        mock_zip.read.return_value = build_docx_xml(content)

        pages = extract_docx_text("dummy.docx")

        # The function logic:
        # <w:p> adds "\n"
        # <w:t> adds "Hello World"
        # Result "Hello World" (stripped)
        assert len(pages) == 1
        assert pages[0] == "Hello World"
        mock_zip.read.assert_called_with("word/document.xml")

    def test_explicit_page_break(self, mock_zip):
        """Test splitting text on hard page breaks."""
        # Page 1: "Page One"
        # Break: <w:br w:type="page"/>
        # Page 2: "Page Two"
        content = '<w:p><w:t>Page One</w:t></w:p><w:p><w:br w:type="page"/></w:p><w:p><w:t>Page Two</w:t></w:p>'
        mock_zip.read.return_value = build_docx_xml(content)

        pages = extract_docx_text("dummy.docx")

        assert len(pages) == 2
        assert pages[0] == "Page One"
        assert pages[1] == "Page Two"

    def test_formatting_elements(self, mock_zip):
        """Test handling of tabs and line breaks."""
        # "Line\nBreak" and "Tab\tCharacter"
        # <w:br/> is a line break, <w:tab/> is a tab
        content = (
            "<w:p><w:t>Line</w:t><w:br/><w:t>Break</w:t></w:p><w:p><w:t>Tab</w:t><w:tab/><w:t>Character</w:t></w:p>"
        )
        mock_zip.read.return_value = build_docx_xml(content)

        pages = extract_docx_text("dummy.docx")

        assert len(pages) == 1
        text = pages[0]
        assert "Line\nBreak" in text
        assert "Tab\tCharacter" in text

    def test_handles_invalid_zip(self, mock_zip):
        """Test that BadZipFile is caught and logs error."""
        # Make the constructor raise, simulating a corrupt file
        # We need to patch the constructor directly, but since our fixture
        # already mocked the class, we can set the side_effect on the mock class calls
        # However, it's cleaner to patch specific behavior for this test.

        # Resetting logic: The function does `with zipfile.ZipFile(...)`.
        # If construction fails:
        with patch("zipfile.ZipFile", side_effect=zipfile.BadZipFile("Bad zip")):
            pages = extract_docx_text("corrupt.docx")

        assert pages == []

    def test_handles_missing_document_xml(self, mock_zip):
        """Test that KeyError (missing file in zip) is caught."""
        # Simulation: zip file opens fine, but 'word/document.xml' is missing
        mock_zip.read.side_effect = KeyError("word/document.xml not found")

        pages = extract_docx_text("empty_zip.docx")

        assert pages == []

    def test_handles_malformed_xml(self, mock_zip):
        """Test that XML parse errors are caught."""
        # Return invalid XML bytes
        mock_zip.read.return_value = b"<w:document> <UnclosedTag> </w:document>"

        pages = extract_docx_text("bad_xml.docx")

        assert pages == []

    def test_empty_text_nodes(self, mock_zip):
        """Test that <w:t> tags with no content (None) don't crash."""
        # <w:t/> with no text
        content = "<w:p><w:t/></w:p>"
        mock_zip.read.return_value = build_docx_xml(content)

        pages = extract_docx_text("dummy.docx")

        # Should return empty string page (or nothing depending on stripping)
        # ".strip()" on empty list join result "" is ""
        # If the page has content "\n" (from <w:p>), it strips to ""
        assert len(pages) == 0 or (len(pages) == 1 and pages[0] == "")
