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
import sys
import hashlib
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
    hasher = FileHasher()
    assert "SHA-256" in hasher.hashers_constructors
    assert "BLAKE3" in hasher.hashers_constructors
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


def test_hash_standard_algorithms(dummy_file):
    """Test SHA-256 and BLAKE3 without TLSH."""
    hasher = FileHasher()
    size = dummy_file.stat().st_size

    # Disable TLSH to test core logic
    result = hasher.hash(str(dummy_file), size, calculate_sha256=True, calculate_blake3=True, calculate_tlsh=False)

    assert "SHA-256" in result
    assert "BLAKE3" in result
    assert "TLSH" not in result

    # Verify correctness against standard lib
    expected_sha = hashlib.sha256(b"Hello World").hexdigest()
    assert result["SHA-256"] == expected_sha


def test_hash_tlsh_integration_success(large_dummy_file, mocker):
    """Test full hashing including TLSH when library is present."""
    hasher = FileHasher()
    size = large_dummy_file.stat().st_size

    # Mock availability
    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    # Mock the actual tlsh module import and class
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
    size = dummy_file.stat().st_size  # 11 bytes < 50 bytes

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    result = hasher.hash(str(dummy_file), size, calculate_tlsh=True)

    assert "TLSH" not in result


def test_hash_file_not_found(mocker):
    hasher = FileHasher()
    with pytest.raises(FileNotFoundError):
        hasher.hash("ghost.txt", 100)


def test_hash_permission_error(dummy_file, mocker):
    """Test handling of permission errors during read."""
    hasher = FileHasher()
    mocker.patch("builtins.open", side_effect=PermissionError("Access denied"))

    with pytest.raises(PermissionError):
        hasher.hash(str(dummy_file), 100)


def test_hash_tlsh_finalization_error(large_dummy_file, mocker):
    """Test that if TLSH.final() raises ValueError (e.g. not enough variance), we handle it gracefully."""
    hasher = FileHasher()
    size = large_dummy_file.stat().st_size

    mocker.patch.object(hasher, "_check_tlsh_availability", return_value=True)

    mock_tlsh_module = mocker.MagicMock()
    mock_instance = mock_tlsh_module.Tlsh.return_value
    # Simulate variance error
    mock_instance.final.side_effect = ValueError("variance too low")

    mocker.patch.dict(sys.modules, {"tlsh": mock_tlsh_module})

    result = hasher.hash(str(large_dummy_file), size, calculate_tlsh=True)

    assert "TLSH" not in result
    # Other hashes should still be present
    assert "SHA-256" in result


def test_standalone_wrappers(dummy_file):
    """Test hash_sha256 and hash_blake3 standalone methods."""
    hasher = FileHasher()

    sha = hasher.hash_sha256(str(dummy_file))
    assert sha == hashlib.sha256(b"Hello World").hexdigest()

    # We verify blake3 by just ensuring it runs and returns a hex string
    blake = hasher.hash_blake3(str(dummy_file))
    assert isinstance(blake, str)
    assert len(blake) == 64


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
