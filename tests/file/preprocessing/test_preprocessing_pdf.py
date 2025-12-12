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
from unittest.mock import Mock, MagicMock, patch, call
import logging
import sys

from dorsal.file.preprocessing.pdf import (
    extract_pdf_layout_per_mille,
    extract_pdf_layout_normalized,
    extract_pdf_layout_pts,
    extract_pdf_pages,
    ocr_extract_pdf_text,
    DependencyError,
    PDFProcessingError,
    PDFPage,
    PDFToken,
)


@pytest.fixture
def mock_dependencies():
    """
    Patches 'pypdfium2' and 'PIL' in sys.modules.
    Returns (mock_pypdfium, mock_pillow).
    """
    mock_pdfium = MagicMock()
    mock_pdfium.PdfiumError = type("PdfiumError", (Exception,), {})
    mock_pil = MagicMock()

    with patch.dict(sys.modules, {"pypdfium2": mock_pdfium, "PIL": mock_pil}):
        yield mock_pdfium, mock_pil


@pytest.fixture
def dummy_pdf_path():
    return "dummy.pdf"


def create_mock_page(width=100, height=200, rects=None):
    """Helper to create a mock PDF page with specific geometry."""
    mock_page = Mock()
    mock_textpage = Mock()

    mock_page.get_size.return_value = (width, height)
    mock_page.get_textpage.return_value = mock_textpage

    if rects:
        mock_textpage.count_rects.return_value = len(rects)
        # side_effect allows iterating through the rects list on subsequent calls
        mock_textpage.get_rect.side_effect = [r["rect"] for r in rects]
        mock_textpage.get_text_bounded.side_effect = [r["text"] for r in rects]
    else:
        mock_textpage.count_rects.return_value = 0

    mock_textpage.get_text_range.return_value = " ".join([r["text"] for r in rects]) if rects else ""
    return mock_page


# --- Tests for extract_pdf_layout_per_mille ---


class TestExtractLayoutPerMille:
    def test_per_mille_math_and_types(self, mock_dependencies, dummy_pdf_path):
        """Test scaling to 1000 and integer casting."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Setup Page: 100x200
        # Rect: Left=10, Bottom=180, Right=50, Top=190
        # PDF Origin is Bottom-Left.
        # Top-Left conversion:
        #   y0 = 200 - 190 = 10
        #   y1 = 200 - 180 = 20
        # Scale (1000):
        #   x0 = (10/100)*1000 = 100
        #   y0 = (10/200)*1000 = 50
        #   x1 = (50/100)*1000 = 500
        #   y1 = (20/200)*1000 = 100
        rect_data = [{"rect": (10, 180, 50, 190), "text": "Header"}]
        mock_page = create_mock_page(100, 200, rect_data)

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        results = extract_pdf_layout_per_mille(dummy_pdf_path)

        assert len(results) == 1
        page = results[0]

        # Check Types
        assert isinstance(page, PDFPage)
        assert len(page.tokens) == 1
        token = page.tokens[0]
        assert isinstance(token, PDFToken)

        # Check Values
        assert token.text == "Header"
        assert token.box == (100, 50, 500, 100)

        # Verify strict Int typing
        for coord in token.box:
            assert isinstance(coord, int)

    def test_strict_mode_raises_on_invalid_dimensions(self, mock_dependencies, dummy_pdf_path):
        """Test strict=True raises error on 0x0 page."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Page with 0 width/height
        mock_page = create_mock_page(0, 0, [])
        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        with pytest.raises(PDFProcessingError) as exc:
            extract_pdf_layout_per_mille(dummy_pdf_path, strict=True)

        assert "invalid dimensions" in str(exc.value)

    def test_lax_mode_clamps_invalid_dimensions(self, mock_dependencies, dummy_pdf_path):
        """Test strict=False (default) clamps values safely."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Page 0x0. Logic uses 'else 1' for divisor.
        # Rect: 10, 10, 20, 20 (Left, Bottom, Right, Top)
        # X calculation: 10/1 * 1000 = 10000 -> Clamped to 1000
        # Y calculation (Flipped): 0 (height) - 20 (top) = -20 -> Clamped to 0 by max(0, ...)
        rect_data = [{"rect": (10, 10, 20, 20), "text": "Foo"}]
        mock_page = create_mock_page(0, 0, rect_data)

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        results = extract_pdf_layout_per_mille(dummy_pdf_path, strict=False)

        assert len(results) == 1
        # X is clamped to max (1000), Y is clamped to min (0) due to negative flip
        assert results[0].tokens[0].box == (1000, 0, 1000, 0)

    def test_input_floats_forced_to_ints(self, mock_dependencies, dummy_pdf_path):
        """Verify that if pdfium returns floats, we strictly cast to int."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Rect returns floats
        rect_data = [{"rect": (10.5, 180.5, 50.5, 190.5), "text": "Floaty"}]
        mock_page = create_mock_page(100, 200, rect_data)

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        results = extract_pdf_layout_per_mille(dummy_pdf_path)
        token = results[0].tokens[0]

        # Box values should be integers, not floats
        for val in token.box:
            assert isinstance(val, int)


# --- Tests for extract_pdf_layout_normalized ---


class TestExtractLayoutNormalized:
    def test_normalized_math(self, mock_dependencies, dummy_pdf_path):
        """Test scaling to 0.0-1.0 floats."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Page: 100x200
        # Rect: L=10, B=180, R=50, T=190
        # Y-Flip: T=10, B=20
        # Normalized:
        # x0 = 10/100 = 0.1
        # y0 = 10/200 = 0.05
        # x1 = 50/100 = 0.5
        # y1 = 20/200 = 0.1
        rect_data = [{"rect": (10, 180, 50, 190), "text": "Norm"}]
        mock_page = create_mock_page(100, 200, rect_data)

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        results = extract_pdf_layout_normalized(dummy_pdf_path)
        token = results[0].tokens[0]

        assert token.box == (0.1, 0.05, 0.5, 0.1)
        for val in token.box:
            assert isinstance(val, float)

    def test_strict_mode_normalized(self, mock_dependencies, dummy_pdf_path):
        """Test strict mode prevents garbage normalization on 0x0 pages."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()
        mock_page = create_mock_page(0, 0, [])
        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        with pytest.raises(PDFProcessingError):
            extract_pdf_layout_normalized(dummy_pdf_path, strict=True)


# --- Tests for extract_pdf_layout_pts ---


class TestExtractLayoutPts:
    def test_pts_math_no_scaling(self, mock_dependencies, dummy_pdf_path):
        """Test raw PTs (only Y-flip, no scaling)."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()

        # Page: 100x200
        # Rect: L=10, B=180, R=50, T=190
        # Expected (Top-Left Origin):
        # x0 = 10
        # y0 = 200 - 190 = 10
        # x1 = 50
        # y1 = 200 - 180 = 20
        rect_data = [{"rect": (10, 180, 50, 190), "text": "Points"}]
        mock_page = create_mock_page(100, 200, rect_data)

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__iter__ = Mock(return_value=iter([mock_page]))

        results = extract_pdf_layout_pts(dummy_pdf_path)
        token = results[0].tokens[0]

        # Should be floats, matched exactly to coordinates
        assert token.box == (10.0, 10.0, 50.0, 20.0)


# --- Common Exception Handling ---


class TestCommonErrors:
    def test_missing_dependency(self, dummy_pdf_path):
        with patch.dict(sys.modules, {"pypdfium2": None}):
            with pytest.raises(DependencyError) as exc:
                extract_pdf_layout_per_mille(dummy_pdf_path)
            assert "pypdfium2" in str(exc.value)

    def test_pdfium_crash_cleanup(self, mock_dependencies, dummy_pdf_path):
        """Ensure file is closed even if processing crashes."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = Mock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        # Crash during iteration
        mock_doc.__iter__ = Mock(side_effect=ValueError("Deep internal crash"))

        with pytest.raises(PDFProcessingError):
            extract_pdf_layout_per_mille(dummy_pdf_path)

        mock_doc.close.assert_called_once()


# --- Tests for extract_pdf_pages ---


class TestRenderPages:
    def test_render_all_pages(self, mock_dependencies, dummy_pdf_path):
        mock_pdfium, _ = mock_dependencies
        mock_doc = MagicMock()
        mock_page = Mock()
        mock_bitmap = Mock()

        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page

        mock_page.render.return_value = mock_bitmap
        mock_bitmap.to_pil.return_value = "PILImage"

        gen = extract_pdf_pages(dummy_pdf_path)
        images = list(gen)

        assert len(images) == 1
        assert images[0] == "PILImage"
        mock_doc.close.assert_called_once()

    def test_render_skipped_invalid_index(self, mock_dependencies, dummy_pdf_path):
        """Test skipping out of bounds pages."""
        mock_pdfium, _ = mock_dependencies
        mock_doc = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc
        mock_doc.__len__.return_value = 5  # 0-4 valid

        # Request 10 (invalid)
        gen = extract_pdf_pages(dummy_pdf_path, pages=[10])
        images = list(gen)
        assert len(images) == 0


class TestOCRExtraction:
    @pytest.fixture
    def mock_pytesseract(self):
        """
        Creates a mock pytesseract module with necessary Exception classes attached.
        """
        mock = MagicMock()
        # Define the specific exceptions pytesseract uses so catches work
        mock.TesseractNotFoundError = type("TesseractNotFoundError", (Exception,), {})
        mock.TesseractError = type("TesseractError", (Exception,), {})
        return mock

    def test_ocr_missing_library(self, dummy_pdf_path):
        """Ensure DependencyError is raised if pytesseract pip package is missing."""
        with patch.dict(sys.modules, {"pytesseract": None}):
            with pytest.raises(DependencyError) as exc:
                ocr_extract_pdf_text(dummy_pdf_path)
            assert "pip install pytesseract" in str(exc.value)

    def test_ocr_missing_binary(self, dummy_pdf_path, mock_pytesseract):
        """Ensure DependencyError is raised if tesseract binary is not in PATH."""
        # 1. Setup the check to fail
        mock_pytesseract.get_tesseract_version.side_effect = mock_pytesseract.TesseractNotFoundError("Binary not found")

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract}):
            with pytest.raises(DependencyError) as exc:
                ocr_extract_pdf_text(dummy_pdf_path)

            # Verify we point users to the official docs, not a specific command
            assert "tesseract-ocr.github.io" in str(exc.value)

    @patch("dorsal.file.preprocessing.pdf.extract_pdf_pages")
    def test_ocr_happy_path(self, mock_extract_pages, dummy_pdf_path, mock_pytesseract):
        """Test successful text extraction from pages."""
        # 1. Setup Mock Images
        mock_image_1 = Mock(name="Image1")
        mock_image_2 = Mock(name="Image2")
        mock_extract_pages.return_value = iter([mock_image_1, mock_image_2])

        # 2. Setup OCR responses
        mock_pytesseract.image_to_string.side_effect = ["Page One Text", "Page Two Text"]

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract}):
            results = ocr_extract_pdf_text(dummy_pdf_path, language="fra", config="--psm 6", render_scale=4.0)

        # 3. Assertions
        assert len(results) == 2
        assert results[0] == "Page One Text"
        assert results[1] == "Page Two Text"

        # Verify arguments passed to renderer
        mock_extract_pages.assert_called_once_with(dummy_pdf_path, scale=4.0, password=None)

        # Verify arguments passed to tesseract
        mock_pytesseract.image_to_string.assert_has_calls(
            [call(mock_image_1, lang="fra", config="--psm 6"), call(mock_image_2, lang="fra", config="--psm 6")]
        )

    @patch("dorsal.file.preprocessing.pdf.extract_pdf_pages")
    def test_ocr_partial_failure(self, mock_extract_pages, dummy_pdf_path, mock_pytesseract):
        """Test that if one page fails OCR, we log it and continue (returning empty str), rather than crashing."""
        mock_extract_pages.return_value = iter([Mock(), Mock()])

        # First page fails, Second succeeds
        mock_pytesseract.image_to_string.side_effect = [
            mock_pytesseract.TesseractError(1, "Error processing image"),
            "Success Text",
        ]

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract}):
            results = ocr_extract_pdf_text(dummy_pdf_path)

        assert len(results) == 2
        assert results[0] == ""  # Empty string on failure
        assert results[1] == "Success Text"
