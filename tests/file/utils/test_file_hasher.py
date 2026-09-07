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

import os
import sys
import hashlib
import pytest

import blake3
from dorsal.file.utils.file_hasher import FileHasher


@pytest.fixture
def dummy_file(tmp_path):
    """Creates a small dummy file for hashing tests."""
    p = tmp_path / "test_file.txt"
    p.write_bytes(b"Hello World")
    return p


@pytest.fixture
def large_dummy_file(tmp_path):
    """Creates a file larger than the TLSH minimum size (50 bytes)."""
    p = tmp_path / "large_file.txt"
    p.write_bytes(b"A" * 100)
    return p


def test_hasher_defaults():
    """Verify that all default algorithms are registered."""
    hasher = FileHasher()
    assert "SHA-256" in hasher.hashers_constructors
    assert "BLAKE3" in hasher.hashers_constructors
    assert "MD5" in hasher.hashers_constructors
    assert "SHA-1" in hasher.hashers_constructors
    assert "BLAKE3-DORSAL" in hasher.hashers_constructors
    assert hasher._tlsh_available is None


def test_check_tlsh_availability_success(mocker):
    hasher = FileHasher()
    mocker.patch("importlib.util.find_spec", return_value=True)
    assert hasher._check_tlsh_availability() is True
    assert hasher._tlsh_available is True


def test_check_tlsh_availability_failure(mocker):
    hasher = FileHasher()
    mocker.patch("importlib.util.find_spec", return_value=None)
    assert hasher._check_tlsh_availability() is False
    assert hasher._tlsh_available is False


def test_dynamic_filesize_resolution(dummy_file):
    """Test that omitting file_size triggers automatic dynamic resolution."""
    hasher = FileHasher()

    result = hasher.hash(str(dummy_file), file_size=None, calculate_tlsh=False)

    expected_sha = hashlib.sha256(b"Hello World").hexdigest()
    assert result["SHA-256"] == expected_sha


def test_hash_threading_large_file(dummy_file, mocker):
    """Test that files exceeding threaded_min_size trigger the async pipeline."""
    hasher = FileHasher()

    hasher.threaded_min_size = 5

    spy_async = mocker.spy(hasher, "_yield_chunks_async")
    spy_sync = mocker.spy(hasher, "_yield_chunks")

    result = hasher.hash(str(dummy_file), file_size=11, calculate_tlsh=False)

    assert "SHA-256" in result
    assert "BLAKE3" in result

    spy_async.assert_called_once()
    spy_sync.assert_not_called()


def test_hash_sequential_small_file_fallback(dummy_file, mocker):
    """Test that small files correctly bypass the thread pool and read synchronously."""
    hasher = FileHasher()

    spy_async = mocker.spy(hasher, "_yield_chunks_async")
    spy_sync = mocker.spy(hasher, "_yield_chunks")

    result = hasher.hash(str(dummy_file), file_size=11, calculate_tlsh=False)

    assert "SHA-256" in result

    spy_sync.assert_called_once()
    spy_async.assert_not_called()


def test_hash_sequential_single_algorithm_fallback(dummy_file, mocker):
    """Test that requesting only one hash bypasses threads regardless of file size."""
    hasher = FileHasher()
    hasher.threaded_min_size = 5

    spy_async = mocker.spy(hasher, "_yield_chunks_async")
    spy_sync = mocker.spy(hasher, "_yield_chunks")

    hasher.hash(
        str(dummy_file),
        file_size=11,
        calculate_sha256=True,
        calculate_blake3=False,
        calculate_md5=False,
        calculate_sha1=False,
        calculate_blake3_dorsal=False,
        calculate_tlsh=False,
    )

    spy_sync.assert_called_once()
    spy_async.assert_not_called()


def test_hash_symlink_physical_mode(mocker):
    """Test that symlinks are read as physical pointer strings when follow_symlinks=False."""
    hasher = FileHasher()

    mocker.patch("os.path.islink", return_value=True)
    mocker.patch("os.readlink", return_value="/target/path")
    mock_lstat = mocker.patch("os.lstat")
    mock_lstat.return_value.st_size = 12

    result = hasher.hash("symlink.txt", file_size=None, follow_symlinks=False, calculate_tlsh=False)

    expected_sha = hashlib.sha256(b"/target/path").hexdigest()
    assert result["SHA-256"] == expected_sha


def test_hash_threadpool_import_error_fallback(dummy_file, mocker):
    """Test graceful fallback to synchronous reading if ThreadPoolExecutor fails."""
    hasher = FileHasher()
    hasher.threaded_min_size = 5

    mocker.patch("concurrent.futures.ThreadPoolExecutor", side_effect=RuntimeError("No threads"))

    spy_sync = mocker.spy(hasher, "_yield_chunks")

    result = hasher.hash(str(dummy_file), file_size=11, calculate_tlsh=False)

    assert "SHA-256" in result
    spy_sync.assert_called_once()


def test_hash_standard_algorithms(dummy_file):
    """Test standard algorithms output correctly."""
    hasher = FileHasher()
    size = dummy_file.stat().st_size

    result = hasher.hash(str(dummy_file), size, calculate_tlsh=False)

    assert "SHA-256" in result
    assert "BLAKE3" in result
    assert "MD5" in result
    assert "SHA-1" in result
    assert "BLAKE3-DORSAL" in result
    assert "TLSH" not in result

    expected_sha = hashlib.sha256(b"Hello World").hexdigest()
    expected_b3d = blake3.blake3(b"Hello World", derive_key_context="Dorsal Validation Hash Context").hexdigest()

    assert result["SHA-256"] == expected_sha
    assert result["BLAKE3-DORSAL"] == expected_b3d


def test_hash_tlsh_integration_success(large_dummy_file, mocker):
    """Test full hashing including TLSH when library is present."""
    hasher = FileHasher()
    size = large_dummy_file.stat().st_size

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    mock_tlsh_module = mocker.MagicMock()
    mock_instance = mock_tlsh_module.Tlsh.return_value
    mock_instance.hexdigest.return_value = "FAKE_TLSH_HASH"

    mocker.patch.dict(sys.modules, {"tlsh": mock_tlsh_module})

    result = hasher.hash(str(large_dummy_file), size, calculate_tlsh=True)

    assert result["TLSH"] == "FAKE_TLSH_HASH"
    mock_instance.update.assert_called()
    mock_instance.final.assert_called()


def test_hash_tlsh_too_small(dummy_file, mocker):
    """Test that TLSH is skipped if file is below min size."""
    hasher = FileHasher()
    size = dummy_file.stat().st_size

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    result = hasher.hash(str(dummy_file), size, calculate_tlsh=True)

    assert "TLSH" not in result


def test_hash_file_not_found():
    hasher = FileHasher()
    with pytest.raises((FileNotFoundError, OSError)):
        hasher.hash("ghost.txt", file_size=None)


def test_hash_permission_error(dummy_file, mocker):
    """Test handling of permission errors during read."""
    hasher = FileHasher()
    mocker.patch("builtins.open", side_effect=PermissionError("Access denied"))

    with pytest.raises(PermissionError):
        hasher.hash(str(dummy_file), file_size=100)


def test_hash_tlsh_finalization_error(large_dummy_file, mocker):
    """Test that if TLSH.final() raises ValueError, we handle it gracefully."""
    hasher = FileHasher()
    size = large_dummy_file.stat().st_size

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    mock_tlsh_module = mocker.MagicMock()
    mock_instance = mock_tlsh_module.Tlsh.return_value
    mock_instance.final.side_effect = ValueError("variance too low")

    mocker.patch.dict(sys.modules, {"tlsh": mock_tlsh_module})

    result = hasher.hash(str(large_dummy_file), size, calculate_tlsh=True)

    assert "TLSH" not in result
    assert "SHA-256" in result


def test_standalone_wrappers(dummy_file):
    """Test standalone hash wrapper methods."""
    hasher = FileHasher()

    sha = hasher.hash_sha256(str(dummy_file))
    assert sha == hashlib.sha256(b"Hello World").hexdigest()

    blake = hasher.hash_blake3(str(dummy_file))
    assert len(blake) == 64

    md5 = hasher.hash_md5(str(dummy_file))
    assert len(md5) == 32

    sha1 = hasher.hash_sha1(str(dummy_file))
    assert len(sha1) == 40

    b3_dorsal = hasher.hash_blake3_dorsal(str(dummy_file))
    assert len(b3_dorsal) == 64


def test_standalone_tlsh(large_dummy_file, mocker):
    """Test hash_tlsh standalone method."""
    hasher = FileHasher()
    size = large_dummy_file.stat().st_size

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    mock_tlsh_module = mocker.MagicMock()
    mock_instance = mock_tlsh_module.Tlsh.return_value
    mock_instance.hexdigest.return_value = "STANDALONE_HASH"

    mocker.patch.dict(sys.modules, {"tlsh": mock_tlsh_module})

    res = hasher.hash_tlsh(str(large_dummy_file), size)

    assert res == "STANDALONE_HASH"


def test_standalone_tlsh_missing_library(large_dummy_file, mocker):
    hasher = FileHasher()
    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=False)

    res = hasher.hash_tlsh(str(large_dummy_file), 100)
    assert res is None
