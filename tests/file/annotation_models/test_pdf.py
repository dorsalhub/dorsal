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

import pytest
from unittest.mock import MagicMock
import datetime

from dorsal.file.annotation_models.pdf.utils import pdfium_extract_pdf_metadata
from dorsal.file.annotation_models.pdf.model import PDFAnnotationModel


@pytest.fixture
def mock_pypdfium2(mocker):
    """Provides a safely mocked pypdfium2 module to avoid real C-bindings."""
    pdfium = MagicMock()

    class PdfiumError(Exception):
        pass

    pdfium.PdfiumError = PdfiumError
    mocker.patch.dict("sys.modules", {"pypdfium2": pdfium})
    return pdfium


class TestPdfiumExtractPdfMetadata:
    def test_extract_success(self, mock_pypdfium2):
        """Hits the complete happy path: metadata, version, and page count are extracted."""
        mock_doc = MagicMock()
        mock_doc.get_metadata_dict.return_value = {"Title": "A Great Book"}
        mock_doc.get_version.return_value = 17
        mock_doc.__len__.return_value = 42
        mock_pypdfium2.PdfDocument.return_value = mock_doc

        result = pdfium_extract_pdf_metadata("/fake/path.pdf", password="pass")

        assert result == {"Title": "A Great Book", "version": "1.7", "page_count": 42}
        mock_pypdfium2.PdfDocument.assert_called_once_with("/fake/path.pdf", password="pass")
        mock_doc.close.assert_called_once()

    def test_extract_import_error(self, mocker):
        """Hits the ImportError branch if pypdfium2 is not installed."""
        mocker.patch.dict("sys.modules", {"pypdfium2": None})

        with pytest.raises(ImportError):
            pdfium_extract_pdf_metadata("/fake/path.pdf")

    def test_extract_pdfium_error(self, mock_pypdfium2):
        """Hits the PdfiumError branch (e.g., bad password or corrupt file)."""
        mock_pypdfium2.PdfDocument.side_effect = mock_pypdfium2.PdfiumError("Corrupt PDF")

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")
        assert result is None

    def test_extract_unexpected_error(self, mock_pypdfium2):
        """Hits the generic Exception branch during document initialization."""
        mock_pypdfium2.PdfDocument.side_effect = RuntimeError("Something completely unexpected")

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")
        assert result is None

    def test_extract_version_unknown(self, mock_pypdfium2):
        """Hits the branch where get_version returns an integer not in the map."""
        mock_doc = MagicMock()
        mock_doc.get_metadata_dict.return_value = {}
        mock_doc.get_version.return_value = 99
        mock_pypdfium2.PdfDocument.return_value = mock_doc

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")
        assert result["version"] is None

    def test_extract_version_exception(self, mock_pypdfium2):
        """Hits the branch where get_version raises an Exception."""
        mock_doc = MagicMock()
        mock_doc.get_metadata_dict.return_value = {}
        mock_doc.get_version.side_effect = Exception("Version read failed")
        mock_pypdfium2.PdfDocument.return_value = mock_doc

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")
        assert result["version"] is None

    def test_extract_page_count_exception(self, mock_pypdfium2):
        """Hits the branch where len(document) raises an Exception."""
        mock_doc = MagicMock()
        mock_doc.get_metadata_dict.return_value = {}
        mock_doc.__len__.side_effect = Exception("Page count failed")
        mock_pypdfium2.PdfDocument.return_value = mock_doc

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")
        assert result["page_count"] is None

    def test_extract_close_exception(self, mock_pypdfium2, caplog):
        """Hits the branch where document.close() fails in the finally block."""
        mock_doc = MagicMock()
        mock_doc.get_metadata_dict.return_value = {}
        mock_doc.close.side_effect = Exception("Close failed")
        mock_pypdfium2.PdfDocument.return_value = mock_doc

        result = pdfium_extract_pdf_metadata("/fake/path.pdf")

        assert result is not None
        assert "Error closing PDF document" in caplog.text


@pytest.fixture
def pdf_model(mocker):
    """Provides a PDFAnnotationModel with a safely mocked mapping dictionary."""
    mocker.patch(
        "dorsal.file.annotation_models.pdf.model.PDFIUM_METADATA_FIELD_MAPPING",
        {"Title": "title", "Keywords": "keywords", "CreationDate": "creation_date", "ModDate": "modified_date"},
    )
    return PDFAnnotationModel(file_path="/fake/model.pdf")


class TestPDFAnnotationModel:
    def test_main_success(self, pdf_model, mocker):
        """Hits the complete happy path for main()."""
        mock_extract = mocker.patch("dorsal.file.annotation_models.pdf.model.pdfium_extract_pdf_metadata")
        mock_extract.return_value = {"Title": "Valid Output"}

        result = pdf_model.main(password="secret")

        mock_extract.assert_called_once_with(file_path="/fake/model.pdf", password="secret")
        assert result["title"] == "Valid Output"
        assert pdf_model.error is None

    def test_main_import_error(self, pdf_model, mocker):
        """Hits the ImportError branch in main() if pypdfium2 is missing."""
        mocker.patch("dorsal.file.annotation_models.pdf.model.pdfium_extract_pdf_metadata", side_effect=ImportError)

        with pytest.raises(ImportError):
            pdf_model.main()
        assert "pypdfium2 library not found" in pdf_model.error

    def test_main_extract_exception(self, pdf_model, mocker):
        """Hits the generic Exception branch in main() during extraction."""
        mocker.patch(
            "dorsal.file.annotation_models.pdf.model.pdfium_extract_pdf_metadata",
            side_effect=RuntimeError("Disk crash"),
        )

        result = pdf_model.main()
        assert result is None
        assert "Unexpected error during raw PDF metadata extraction: Disk crash" in pdf_model.error

    def test_main_extract_returns_none(self, pdf_model, mocker):
        """Hits the branch where pdfium_extract_pdf_metadata returns None safely."""
        mocker.patch("dorsal.file.annotation_models.pdf.model.pdfium_extract_pdf_metadata", return_value=None)

        result = pdf_model.main()
        assert result is None
        assert "could not be extracted" in pdf_model.error

    def test_main_normalize_exception(self, pdf_model, mocker):
        """Hits the generic Exception branch in main() during normalization."""
        mocker.patch(
            "dorsal.file.annotation_models.pdf.model.pdfium_extract_pdf_metadata", return_value={"Title": "Crash"}
        )
        mocker.patch.object(pdf_model, "_normalize_pdf_metadata", side_effect=ValueError("Bad normalizer"))

        result = pdf_model.main()
        assert result is None
        assert "Failed to normalize extracted PDF metadata: Bad normalizer" in pdf_model.error

    def test_normalize_keywords_valid(self, pdf_model):
        """Hits the keyword parsing branch with standard delimiters."""
        raw = {"Keywords": "finance, reporting; 2026,  taxes "}
        res = pdf_model._normalize_pdf_metadata(raw)
        assert res["keywords"] == ["finance", "reporting", "2026", "taxes"]

    def test_normalize_keywords_empty_or_nonstring(self, pdf_model):
        """Hits the keyword parsing fallback branch for empty or invalid types."""
        res_empty = pdf_model._normalize_pdf_metadata({"Keywords": ""})
        res_none = pdf_model._normalize_pdf_metadata({"Keywords": None})
        res_int = pdf_model._normalize_pdf_metadata({"Keywords": 123})

        assert res_empty["keywords"] == []
        assert res_none["keywords"] == []
        assert res_int["keywords"] == []

    def test_normalize_unmapped_fields(self, pdf_model, caplog):
        """Hits the unmapped field ignore branch and logging."""
        raw = {"Title": "Valid", "UnknownField123": "Ghost data"}
        res = pdf_model._normalize_pdf_metadata(raw)

        assert "UnknownField123" not in res
        assert "Ignoring unmapped PDF metadata field" in caplog.text
        assert "UnknownField123" in caplog.text

    def test_normalize_empty_mapped_fields(self, pdf_model, caplog):
        """Hits the fallback branch when mapped fields exist but are empty strings."""
        raw = {"Title": ""}
        res = pdf_model._normalize_pdf_metadata(raw)

        assert res["title"] is None
        assert "missing or empty. Setting to None" in caplog.text

    def test_normalize_date_fields_success(self, pdf_model, mocker):
        """Hits the successful date string parsing branch."""
        mock_date = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        mocker.patch("dorsal.file.annotation_models.pdf.model.PDF_DATETIME.parse", return_value=mock_date)

        raw = {"CreationDate": "D:20260101000000Z"}
        res = pdf_model._normalize_pdf_metadata(raw)

        assert res["creation_date"] == mock_date

    def test_normalize_date_fields_parse_failure(self, pdf_model, mocker, caplog):
        """Hits the branch where a date string exists but fails to parse."""
        mocker.patch("dorsal.file.annotation_models.pdf.model.PDF_DATETIME.parse", return_value=None)

        raw = {"CreationDate": "totally_invalid_date"}
        res = pdf_model._normalize_pdf_metadata(raw)

        assert res["creation_date"] is None
        assert "Failed to parse date string" in caplog.text

    def test_normalize_date_fields_wrong_type(self, pdf_model, caplog):
        """Hits the branch where a date field is provided, but isn't a string."""
        raw = {"CreationDate": 20260101}
        res = pdf_model._normalize_pdf_metadata(raw)

        assert res["creation_date"] is None
        assert "Expected string for date field 'creation_date', but got type 'int'" in caplog.text
