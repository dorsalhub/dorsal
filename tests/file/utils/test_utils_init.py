import pytest
import logging
from dorsal.file.utils import (
    get_md5_hash,
    get_quick_hash,
    get_sha1_hash,
    get_validation_hash,
    multi_hash,
)
from dorsal.common.exceptions import QuickHashFileSizeError, QuickHashFileInstabilityError


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


def test_get_quick_hash_success(mock_quick_hasher, mock_filesize):
    mock_quick_hasher.hash.return_value = "qh123"
    assert get_quick_hash("file.txt") == "qh123"
    mock_quick_hasher.hash.assert_called_with(file_path="file.txt", file_size=1000, follow_symlinks=True)


def test_get_quick_hash_fallback(mock_quick_hasher, mock_filesize, mocker):
    """Test fallback to SHA256 when quick hash returns None."""
    mock_quick_hasher.hash.return_value = None
    mocker.patch("dorsal.file.utils.FILE_HASHER.hash_sha256", return_value="sha123")

    assert get_quick_hash("file.txt", fallback_to_sha256=True) == "sha123"


def test_get_quick_hash_os_error(mock_filesize):
    mock_filesize.side_effect = OSError("Disk error")
    with pytest.raises(OSError):
        get_quick_hash("file.txt")


@pytest.mark.parametrize(
    "func,hasher_method",
    [
        (get_sha1_hash, "hash_sha1"),
        (get_md5_hash, "hash_md5"),
        (get_validation_hash, "hash_dorsal_validation"),
    ],
)
def test_get_hash_functions_success(mock_file_hasher, func, hasher_method):
    """Test success path for get_sha1_hash, get_md5_hash, and get_validation_hash."""
    method_mock = getattr(mock_file_hasher, hasher_method)
    method_mock.return_value = "hashed_value"

    result = func("file.txt", follow_symlinks=True)

    assert result == "hashed_value"
    method_mock.assert_called_once_with(file_path="file.txt", follow_symlinks=True)


@pytest.mark.parametrize(
    "func,hasher_method",
    [
        (get_sha1_hash, "hash_sha1"),
        (get_md5_hash, "hash_md5"),
        (get_validation_hash, "hash_dorsal_validation"),
    ],
)
@pytest.mark.parametrize("exc", [IOError("Read failure"), PermissionError("Access denied")])
def test_get_hash_functions_exceptions(mock_file_hasher, func, hasher_method, exc):
    """Test IOError and PermissionError propagation for hash wrapper functions."""
    method_mock = getattr(mock_file_hasher, hasher_method)
    method_mock.side_effect = exc

    with pytest.raises(type(exc)):
        func("file.txt")


def test_multi_hash_success(mock_file_hasher, mock_quick_hasher, mock_os_path_getsize):
    """Test full success path."""

    mock_file_hasher.hash.return_value = {"SHA-256": "sha", "BLAKE3": "blake"}
    mock_quick_hasher.hash.return_value = "quick"

    result = multi_hash("file.txt", similarity_hash=True)

    assert result["SHA-256"] == "sha"
    assert result["BLAKE3"] == "blake"
    assert result["QUICK"] == "quick"

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
