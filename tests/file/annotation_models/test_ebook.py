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

import os
import xml.etree.ElementTree as ET
import zipfile
import pytest
from unittest.mock import MagicMock

from dorsal.file.annotation_models.ebook.model import EbookAnnotationModel
from dorsal.file.annotation_models.ebook import utils


class TestEbookAnnotationModel:
    @pytest.fixture
    def ebook_model(self):
        return EbookAnnotationModel(file_path="/fake/book.epub")

    def test_main_success_epub(self, ebook_model, mocker):
        """Hits the happy path for an EPUB file."""
        mock_extract = mocker.patch("dorsal.file.annotation_models.ebook.utils.extract_epub_metadata")
        mock_extract.return_value = {"title": "A Great Book"}

        result = ebook_model.main()

        mock_extract.assert_called_once_with("/fake/book.epub")
        assert result == {"title": "A Great Book"}
        assert ebook_model.variant == "epub_stdlib"
        assert ebook_model.error is None

    def test_main_unsupported_format(self, mocker):
        """Hits the branch where the format is not in the configuration mapping."""
        model = EbookAnnotationModel(file_path="/fake/book.pdf")

        result = model.main()

        assert result is None
        assert "Unsupported ebook format: '.pdf'" in model.error

    def test_main_extraction_returns_none(self, ebook_model, mocker):
        """Hits the branch where the extraction utility fails and returns None."""
        mock_extract = mocker.patch("dorsal.file.annotation_models.ebook.utils.extract_epub_metadata")
        mock_extract.return_value = None

        result = ebook_model.main()

        assert result is None
        assert "Failed to parse ebook metadata" in ebook_model.error

    def test_main_import_error(self, ebook_model, mocker):
        """Hits the ImportError branch (e.g., if a dependency is missing)."""
        mocker.patch(
            "dorsal.file.annotation_models.ebook.utils.extract_epub_metadata", side_effect=ImportError("missing lib")
        )

        result = ebook_model.main()

        assert result is None
        assert "Missing dependency for parser" in ebook_model.error

    def test_main_os_error(self, ebook_model, mocker):
        """Hits the FileNotFoundError/IOError/OSError branch, which MUST raise."""
        mocker.patch(
            "dorsal.file.annotation_models.ebook.utils.extract_epub_metadata",
            side_effect=FileNotFoundError("Missing file"),
        )

        with pytest.raises(FileNotFoundError):
            ebook_model.main()
        assert "File system error during ebook processing" in ebook_model.error

    def test_main_unexpected_error(self, ebook_model, mocker):
        """Hits the unexpected Exception branch, which MUST raise."""
        mocker.patch(
            "dorsal.file.annotation_models.ebook.utils.extract_epub_metadata",
            side_effect=RuntimeError("Cosmic ray bit flip"),
        )

        with pytest.raises(RuntimeError):
            ebook_model.main()
        assert "Unexpected error during EbookAnnotationModel processing" in ebook_model.error


class TestEbookUtilsHelpers:
    def test_strip_html(self):
        """Tests HTML tag removal and None fallbacks."""
        assert utils._strip_html("<p>Hello <b>World</b></p>") == "Hello World"
        assert utils._strip_html("   <br>   ") is None
        assert utils._strip_html(None) is None
        assert utils._strip_html("") is None

    def test_parse_date(self, mocker):
        """Tests parsing using the imported PDF_DATETIME utility."""
        mock_parser = MagicMock()
        mock_parser.parse.return_value = "parsed_date_obj"
        mocker.patch("dorsal.file.annotation_models.ebook.utils.PDF_DATETIME", mock_parser)

        assert utils._parse_date("2026-01-01") == "parsed_date_obj"
        assert utils._parse_date(None) is None

        mocker.patch("dorsal.file.annotation_models.ebook.utils.PDF_DATETIME", None)
        assert utils._parse_date("2026-01-01") is None

    def test_extract_isbn(self):
        """Tests ISBN regex extraction for various formats."""
        assert utils._extract_isbn("urn:isbn:9781234567890") == "9781234567890"
        assert utils._extract_isbn("ISBN: 123456789X") == "123456789X"
        assert utils._extract_isbn("978-1-234-56789-0") == "9781234567890"
        assert utils._extract_isbn("invalid-isbn-string") is None
        assert utils._extract_isbn(None) is None

    def test_get_meta_text_and_list(self):
        """Tests metadata extraction with and without namespaces."""
        xml_str = """
        <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>Namespaced Title</dc:title>
            <title>Fallback Title</title>
            <dc:subject>Math</dc:subject>
            <dc:subject>Science</dc:subject>
            <subject>History</subject>
            <empty></empty>
        </metadata>
        """
        root = ET.fromstring(xml_str)

        assert utils._get_meta_text(root, "title") == "Namespaced Title"

        assert utils._get_meta_text(root, "title") == "Namespaced Title"
        assert utils._get_meta_text(root, "empty") is None

        assert utils._get_meta_list(root, "subject") == ["Math", "Science"]
        assert utils._get_meta_list(root, "nonexistent") == []

    def test_get_all_epub_dates(self):
        """Tests sorting of dates based on opf:event attributes."""
        xml_str = """
        <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
            <dc:date opf:event="creation">2020-01-01</dc:date>
            <dc:date opf:event="publication">2021-01-01</dc:date>
            <dc:date opf:event="modification">2022-01-01</dc:date>
            <dc:date>2023-01-01</dc:date>
            <date>2024-01-01</date>
        </metadata>
        """
        root = ET.fromstring(xml_str)
        dates = utils._get_all_epub_dates(root)

        assert dates["creation"] == "2020-01-01"
        assert dates["publication"] == "2021-01-01"
        assert dates["modification"] == "2022-01-01"
        assert dates["first_unspecified"] == "2023-01-01"

    def test_get_cover_path_success(self):
        """Hits the full success branch resolving a cover ID to a manifest path."""
        xml_str = """
        <package xmlns:opf="http://www.idpf.org/2007/opf">
            <opf:metadata>
                <opf:meta name="cover" content="cover-img"/>
            </opf:metadata>
            <opf:manifest>
                <opf:item id="cover-img" href="images/cover.jpg"/>
            </opf:manifest>
        </package>
        """
        assert utils._get_cover_path(ET.fromstring(xml_str)) == "images/cover.jpg"

    def test_get_cover_path_failures(self):
        """Tests all failure branches in cover resolution."""

        assert utils._get_cover_path(ET.fromstring("<package></package>")) is None

        assert (
            utils._get_cover_path(
                ET.fromstring(
                    "<package><opf:metadata xmlns:opf='http://www.idpf.org/2007/opf'></opf:metadata></package>"
                )
            )
            is None
        )

        xml_no_manifest = "<package xmlns:opf='http://www.idpf.org/2007/opf'><opf:metadata><opf:meta name='cover' content='cover-img'/></opf:metadata></package>"
        assert utils._get_cover_path(ET.fromstring(xml_no_manifest)) is None

        xml_no_item = "<package xmlns:opf='http://www.idpf.org/2007/opf'><opf:metadata><opf:meta name='cover' content='cover-img'/></opf:metadata><opf:manifest></opf:manifest></package>"
        assert utils._get_cover_path(ET.fromstring(xml_no_item)) is None

        xml_no_href = "<package xmlns:opf='http://www.idpf.org/2007/opf'><opf:metadata><opf:meta name='cover' content='cover-img'/></opf:metadata><opf:manifest><opf:item id='cover-img'/></opf:manifest></package>"
        assert utils._get_cover_path(ET.fromstring(xml_no_href)) is None

    def test_extract_mobi_metadata(self, caplog):
        """Hits the stub function for MOBI."""
        result = utils.extract_mobi_metadata("file.mobi")
        assert result is None
        assert "MOBI metadata extraction is not implemented" in caplog.text


class TestExtractEpubMetadata:
    @pytest.fixture
    def mock_zipfile_setup(self, mocker):
        """Mocks the context manager for zipfile.ZipFile."""
        mock_zip = mocker.patch("dorsal.file.annotation_models.ebook.utils.zipfile.ZipFile")
        mock_zip_instance = MagicMock()
        mock_zip.return_value.__enter__.return_value = mock_zip_instance
        return mock_zip_instance

    @pytest.fixture
    def mock_normalizers(self, mocker):
        """Mocks the language normalizers."""
        mocker.patch("dorsal.file.annotation_models.ebook.utils.normalize_language_name", return_value="English")
        mocker.patch("dorsal.file.annotation_models.ebook.utils.normalize_language_alpha3", return_value="eng")
        mocker.patch("dorsal.file.annotation_models.ebook.utils.extract_locale_code", return_value="en-US")

    def test_extract_epub_metadata_success(self, mock_zipfile_setup, mock_normalizers):
        """Hits the full end-to-end extraction path for EPUB files."""
        container_xml = b"""
        <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
            <rootfiles>
                <rootfile full-path="OEBPS/content.opf"/>
            </rootfiles>
        </container>
        """
        opf_xml = b"""
        <package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
            <metadata>
                <dc:title>Test Book</dc:title>
                <dc:creator>Test Author</dc:creator>
                <dc:language>en</dc:language>
                <dc:identifier>urn:isbn:9781234567890</dc:identifier>
                <dc:identifier>custom-id-123</dc:identifier>
                <dc:contributor>calibre</dc:contributor>
                <dc:contributor>Some Editor</dc:contributor>
                <opf:meta name="generator" content="Adobe"/>
            </metadata>
        </package>
        """

        def mock_read(path):
            if path == "META-INF/container.xml":
                return container_xml
            if path == "OEBPS/content.opf":
                return opf_xml
            raise KeyError(path)

        mock_zipfile_setup.read.side_effect = mock_read

        result = utils.extract_epub_metadata("/fake/path.epub")

        assert result is not None
        assert result["title"] == "Test Book"
        assert result["authors"] == ["Test Author"]
        assert result["language"] == "English"
        assert result["isbn"] == "9781234567890"
        assert "custom-id-123" in result["other_identifiers"]

        assert "calibre" in result["tools"]
        assert "Adobe" in result["tools"]
        assert "Some Editor" in result["contributors"]

    def test_extract_epub_metadata_no_container(self, mock_zipfile_setup):
        """Hits the KeyError branch when container.xml is missing."""
        mock_zipfile_setup.read.side_effect = KeyError("Not found")

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None

    def test_extract_epub_metadata_no_rootfile(self, mock_zipfile_setup):
        """Hits the branch where container.xml has no rootfile path."""
        mock_zipfile_setup.read.return_value = b"""<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles></rootfiles></container>"""

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None

    def test_extract_epub_metadata_no_metadata(self, mock_zipfile_setup):
        """Hits the branch where opf file is found but lacks a metadata tag."""
        container_xml = b"""<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>"""
        opf_xml = b"""<package xmlns="http://www.idpf.org/2007/opf"></package>"""

        mock_zipfile_setup.read.side_effect = lambda p: container_xml if "container" in p else opf_xml

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None

    def test_extract_epub_metadata_bad_zip(self, mocker, caplog):
        """Hits the BadZipFile catch block."""
        mocker.patch(
            "dorsal.file.annotation_models.ebook.utils.zipfile.ZipFile", side_effect=zipfile.BadZipFile("Not a zip")
        )

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None
        assert "not a valid ZIP archive" in caplog.text

    def test_extract_epub_metadata_parse_error(self, mock_zipfile_setup, caplog):
        """Hits the ParseError catch block."""
        mock_zipfile_setup.read.return_value = b"<! Not valid XML >"

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None
        assert "Failed to parse XML from ebook" in caplog.text

    def test_extract_epub_metadata_generic_exception(self, mock_zipfile_setup, caplog):
        """Hits the generic Exception catch block."""
        mock_zipfile_setup.read.side_effect = Exception("System Crash")

        result = utils.extract_epub_metadata("/fake/path.epub")
        assert result is None
        assert "Failed to parse EPUB file" in caplog.text
