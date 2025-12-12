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
import logging
from dorsal.file.utils import get_quick_hash, multi_hash
from dorsal.common.exceptions import QuickHashFileSizeError, QuickHashFileInstabilityError


# --- Fixtures ---
@pytest.fixture
def mock_file_hasher(mocker):
    return mocker.patch("dorsal.file.utils.FILE_HASHER")


@pytest.fixture
def mock_quick_hasher(mocker):
    return mocker.patch("dorsal.file.utils.QUICK_HASHER")


@pytest.fixture
def mock_filesize(mocker):
    return mocker.patch("dorsal.file.utils.get_filesize", return_value=1000)


@pytest.fixture
def mock_os_path_getsize(mocker):
    return mocker.patch("os.path.getsize", return_value=1000)


# --- get_quick_hash Tests ---


def test_get_quick_hash_success(mock_quick_hasher, mock_filesize):
    mock_quick_hasher.hash.return_value = "qh123"
    assert get_quick_hash("file.txt") == "qh123"
    mock_quick_hasher.hash.assert_called_with(file_path="file.txt", file_size=1000)


def test_get_quick_hash_fallback(mock_quick_hasher, mock_filesize, mocker):
    """Test fallback to SHA256 when quick hash returns None."""
    mock_quick_hasher.hash.return_value = None
    mocker.patch("dorsal.file.utils._calculate_sha256", return_value="sha123")

    assert get_quick_hash("file.txt", fallback_to_sha256=True) == "sha123"


def test_get_quick_hash_os_error(mock_filesize):
    mock_filesize.side_effect = OSError("Disk error")
    with pytest.raises(OSError):
        get_quick_hash("file.txt")


# --- multi_hash Tests ---


def test_multi_hash_success(mock_file_hasher, mock_quick_hasher, mock_os_path_getsize):
    """Test full success path."""
    # Setup returns
    mock_file_hasher.hash.return_value = {"SHA-256": "sha", "BLAKE3": "blake"}
    mock_quick_hasher.hash.return_value = "quick"

    result = multi_hash("file.txt", similarity_hash=True)

    assert result["SHA-256"] == "sha"
    assert result["BLAKE3"] == "blake"
    assert result["QUICK"] == "quick"

    # Verify calculate_tlsh was passed through
    call_kwargs = mock_file_hasher.hash.call_args[1]
    assert call_kwargs["calculate_tlsh"] is True


def test_multi_hash_quick_fail_graceful(mock_file_hasher, mock_quick_hasher, mock_os_path_getsize, caplog):
    """Test that QuickHash failure doesn't crash the whole operation."""
    mock_file_hasher.hash.return_value = {"SHA-256": "sha"}
    mock_quick_hasher.hash.side_effect = QuickHashFileInstabilityError("Changed")

    result = multi_hash("file.txt")

    assert "SHA-256" in result
    assert "QUICK" not in result
    assert "QuickHash generation for 'file.txt' failed" in caplog.text


def test_multi_hash_main_hasher_fail(mock_file_hasher, mock_os_path_getsize):
    """Test that main hasher failure DOES crash the operation."""
    mock_file_hasher.hash.side_effect = OSError("Read fail")

    with pytest.raises(OSError):
        multi_hash("file.txt")


def test_multi_hash_getsize_fail(mock_os_path_getsize):
    mock_os_path_getsize.side_effect = OSError("Stat fail")
    with pytest.raises(OSError):
        multi_hash("file.txt")
