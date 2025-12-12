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
import zipfile

from dorsal.file.utils.infer_mediatype import (
    get_media_type,
    _get_default_media_type,
    _strip_media_type_parameters,
    _get_mediainfo_format,
    _infer_mediatype_rule_mkv,
)


@pytest.fixture
def mock_magic(mocker):
    """Mocks the global 'magic' object inside the module."""
    return mocker.patch("dorsal.file.utils.infer_mediatype.magic")


@pytest.fixture
def mock_mediainfo(mocker):
    """Mocks the global 'MediaInfo' class inside the module."""
    return mocker.patch("dorsal.file.utils.infer_mediatype.MediaInfo")


def test_get_media_type_magic_success(mock_magic, tmp_path):
    """Test standard success path where libmagic identifies the file."""
    f = tmp_path / "test.jpg"
    f.touch()

    # Setup magic to return a clean mime type
    mock_magic.from_file.return_value = "image/jpeg"

    result = get_media_type(str(f), ".jpg")

    assert result == "image/jpeg"
    mock_magic.from_file.assert_called_once_with(str(f), mime=True)


def test_get_media_type_strip_parameters(mock_magic, tmp_path):
    """Test that charset parameters are stripped."""
    f = tmp_path / "doc.html"
    f.touch()

    mock_magic.from_file.return_value = "text/html; charset=utf-8"

    result = get_media_type(str(f), ".html")

    assert result == "text/html"


def test_get_media_type_empty_file_fallback(mock_magic, tmp_path):
    """
    Test that if magic returns nothing (or fails),
    an empty file returns application/x-empty.
    """
    # Use .unknown so mimetypes library doesn't auto-detect it as octet-stream
    f = tmp_path / "empty.unknown"
    f.touch()

    mock_magic.from_file.return_value = None

    result = get_media_type(str(f), ".unknown")

    assert result == "application/x-empty"


def test_get_media_type_binary_fallback(mock_magic, tmp_path):
    """
    Test that if magic returns nothing, a file with content
    returns application/octet-stream.
    """
    f = tmp_path / "data.unknown"
    f.write_bytes(b"\x00\x01\x02")

    mock_magic.from_file.return_value = None

    result = get_media_type(str(f), ".unknown")

    assert result == "application/octet-stream"


def test_mkv_custom_rule_magic_agrees(mock_magic, tmp_path):
    """
    Test the MKV optimization: if magic already says matroska, accept it.
    """
    f = tmp_path / "movie.mkv"
    f.touch()

    # Magic returns the x-matroska variant
    mock_magic.from_file.return_value = "video/x-matroska"

    result = get_media_type(str(f), ".mkv")

    # Logic normalizes it to video/matroska
    assert result == "video/matroska"


def test_mkv_custom_rule_mediainfo_fallback(mock_magic, mock_mediainfo, tmp_path):
    """
    Test the MKV optimization: if magic is wrong (e.g. octet-stream),
    we check MediaInfo.
    """
    f = tmp_path / "movie.mkv"
    f.touch()

    mock_magic.from_file.return_value = "application/octet-stream"

    # Mock MediaInfo parsing output
    mock_json = '{"media": {"track": [{"@type": "General", "Format": "Matroska"}]}}'
    mock_mediainfo.parse.return_value = mock_json

    result = get_media_type(str(f), ".mkv")

    assert result == "video/matroska"


def test_iso_extension_mapping(mock_magic, tmp_path, mocker):
    """Test that .iso extension forces specific mime type via MAP_EXTENSION_TO_MEDIATYPE."""
    f = tmp_path / "disk.iso"
    f.touch()

    # 1. Magic must return None to trigger fallback logic
    mock_magic.from_file.return_value = None

    mocker.patch("dorsal.file.utils.infer_mediatype.mimetypes.guess_type", return_value=(None, None))

    result = get_media_type(str(f), ".iso")

    assert result == "application/vnd.efi.iso"


def test_magic_exception_handling(mock_magic, tmp_path, caplog):
    """Test graceful degradation when libmagic raises an error."""
    f = tmp_path / "error.file"
    f.touch()

    mock_magic.from_file.side_effect = Exception("Magic crashed")

    result = get_media_type(str(f), None)

    assert result == "application/x-empty"
    assert "Unexpected error using libmagic" in caplog.text


def test_mediainfo_parsing_error(mock_mediainfo, tmp_path):
    """Test that _get_mediainfo_format handles parsing errors gracefully."""
    f = tmp_path / "corrupt.mkv"
    f.touch()

    mock_mediainfo.parse.side_effect = RuntimeError("MediaInfo missing")

    fmt = _get_mediainfo_format(str(f))
    assert fmt is None


def test_get_default_media_type_io_error(tmp_path, mocker):
    """Test IOError handling when reading file for default type."""
    f = tmp_path / "locked.file"
    f.touch()

    mocker.patch("builtins.open", side_effect=IOError("Disk error"))

    with pytest.raises(IOError):
        _get_default_media_type(str(f))


def test_refine_rule_inode_blockdevice(mock_magic, tmp_path):
    """Test logic path for PREFER_BUILTIN_MIMETYPES."""
    f = tmp_path / "blockdev"
    f.touch()

    mock_magic.from_file.return_value = "inode/blockdevice"

    # If mimetypes library returns None (which it does for files with no extension),
    # your code preserves the original magic type "inode/blockdevice".
    result = get_media_type(str(f), None)
    assert result == "inode/blockdevice"


def test_strip_parameters_none():
    """Edge case for helper function."""
    assert _strip_media_type_parameters(None) is None


@pytest.mark.parametrize(
    "ext, internal_file, expected_mime",
    [
        (".docx", "word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (".xlsx", "xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (".pptx", "ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ],
)
def test_office_xml_rule_success_windows_simulation(mock_magic, tmp_path, ext, internal_file, expected_mime):
    """
    Simulate Windows behavior: Magic returns 'application/zip', but the file
    is a valid Office file. The code should inspect the zip and find the type.
    """
    f = tmp_path / f"test{ext}"

    # Create a valid zip file with the specific signature file inside
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr(internal_file, "<xml></xml>")

    # 1. Simulate the "Dumb" Windows Libmagic response
    mock_magic.from_file.return_value = "application/zip"

    # 2. Run inference
    result = get_media_type(str(f), ext)

    # 3. Assert the code upgraded the type based on internal structure
    assert result == expected_mime


def test_office_xml_rule_structure_mismatch(mock_magic, tmp_path):
    """
    Test a file that IS a zip and HAS a .docx extension, but lacks the
    internal Word structure. Should fallback to generic zip.
    """
    f = tmp_path / "malware.docx"

    # Create a valid zip, but put random junk in it, not 'word/document.xml'
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("malicious.exe", "binary code")

    # Magic sees a zip
    mock_magic.from_file.return_value = "application/zip"

    result = get_media_type(str(f), ".docx")

    # Result should NOT be promoted to word document
    # It should fall back to what magic said (or mimetypes guess)
    assert result != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert result == "application/zip"


def test_office_xml_rule_not_a_zip(mock_magic, tmp_path):
    """
    Test a file that has .docx extension but is just random binary noise.
    Should not crash, and should return the original magic type.
    """
    f = tmp_path / "noise.docx"
    f.write_bytes(b"\x00\x01\x02\x03")  # Not a zip header

    # Magic usually calls random bytes octet-stream
    mock_magic.from_file.return_value = "application/octet-stream"

    result = get_media_type(str(f), ".docx")

    assert result == "application/octet-stream"


def test_office_xml_optimization_linux(mock_magic, tmp_path, mocker):
    """
    If Magic already identifies it as a Word doc (standard on Linux),
    we should NOT attempt to open the zip file (optimization).
    """
    f = tmp_path / "test.docx"
    f.touch()  # Empty file is fine because we shouldn't read it

    expected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_magic.from_file.return_value = expected

    # Spy on zipfile.is_zipfile to ensure it's NOT called
    spy_is_zip = mocker.spy(zipfile, "is_zipfile")

    result = get_media_type(str(f), ".docx")

    assert result == expected
    # Crucial: Proof that we short-circuited the logic
    spy_is_zip.assert_not_called()
