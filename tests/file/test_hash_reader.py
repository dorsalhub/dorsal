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
from unittest.mock import MagicMock, patch

from dorsal.file.hash_reader import HashReader
from dorsal.common.exceptions import QuickHashFileSizeError


@pytest.fixture
def mock_cache():
    """
    Mocks the shared cache dependency for all tests in this module.
    This provides a clean, isolated cache for each test function.
    """
    with patch("dorsal.file.hash_reader.get_shared_cache") as mock_get_cache:
        cache_instance = MagicMock()
        mock_get_cache.return_value = cache_instance
        yield cache_instance


@pytest.fixture
def test_file(tmp_path):
    """
    Creates a temporary file with known content for hashing tests.
    """
    file_path = tmp_path / "test_file.txt"
    content = b"hello world"
    file_path.write_bytes(content)
    return file_path


def test_get_hash_from_cache(mock_cache, test_file):
    """
    Tests the CACHE HIT path: If a hash is in the cache, it should be returned
    without calling the underlying hashers.
    """
    mock_cache.get_hash.return_value = "cached_sha256_hash"

    with (
        patch("dorsal.file.hash_reader.FILE_HASHER") as mock_file_hasher,
        patch("dorsal.file.hash_reader.QUICK_HASHER") as mock_quick_hasher,
    ):
        reader = HashReader()

        result = reader.get(file_path=test_file, hashes=["SHA-256"])

        assert result["SHA-256"] == "cached_sha256_hash"
        mock_cache.get_hash.assert_called_once_with(path=test_file, hash_function="SHA-256")
        mock_file_hasher.hash.assert_not_called()
        mock_quick_hasher.hash.assert_not_called()


@patch("dorsal.file.hash_reader.FILE_HASHER")
def test_get_hash_cache_miss(mock_file_hasher, mock_cache, test_file):
    """
    Tests the CACHE MISS path: If a hash is not in the cache, it should be
    calculated, returned, and then written back to the cache.
    """
    mock_cache.get_hash.return_value = None
    mock_file_hasher.hash.return_value = {"SHA-256": "calculated_sha256_hash"}

    reader = HashReader()

    result = reader.get(file_path=test_file, hashes=["SHA-256"])

    assert result["SHA-256"] == "calculated_sha256_hash"
    mock_cache.get_hash.assert_called_once_with(path=test_file, hash_function="SHA-256")
    mock_file_hasher.hash.assert_called_once()
    mock_cache.upsert_hash.assert_called_once()
    assert mock_cache.upsert_hash.call_args.kwargs["hash_value"] == "calculated_sha256_hash"


@patch("dorsal.file.hash_reader.FILE_HASHER")
def test_get_hash_skip_cache(mock_file_hasher, mock_cache, test_file):
    """
    Tests that `skip_cache=True` bypasses the cache read but still
    calculates the hash. It should NOT write back to the cache.
    """
    mock_file_hasher.hash.return_value = {"SHA-256": "calculated_sha256_hash"}
    reader = HashReader()

    result = reader.get(file_path=test_file, hashes=["SHA-256"], skip_cache=True)

    assert result["SHA-256"] == "calculated_sha256_hash"
    mock_cache.get_hash.assert_not_called()
    mock_file_hasher.hash.assert_called_once()
    mock_cache.upsert_hash.assert_not_called()


def test_get_multiple_hashes_with_mixed_cache(mock_cache, test_file):
    """
    Tests requesting multiple hashes where one is in the cache and another is not.
    """
    # Arrange
    mock_cache.get_hash.side_effect = lambda path, hash_function: (
        "cached_sha256" if hash_function == "SHA-256" else None
    )

    with patch("dorsal.file.hash_reader.FILE_HASHER") as mock_file_hasher:
        mock_file_hasher.hash.return_value = {"BLAKE3": "calculated_blake3"}
        reader = HashReader()
        result = reader.get(file_path=str(test_file), hashes=["SHA-256", "BLAKE3"])

        assert result["SHA-256"] == "cached_sha256"
        assert result["BLAKE3"] == "calculated_blake3"
        mock_file_hasher.hash.assert_called_once_with(
            file_path=str(test_file),
            file_size=11,
            calculate_sha256=False,
            calculate_blake3=True,
            calculate_tlsh=False,
        )
        mock_cache.upsert_hash.assert_called_once_with(
            path=str(test_file),
            modified_time=pytest.approx(test_file.stat().st_mtime),
            hash_function="BLAKE3",
            hash_value="calculated_blake3",
        )


def test_get_hash_for_non_existent_file(mock_cache):
    """
    Tests that the method handles an OSError (e.g., file not found) gracefully
    and returns None for all requested hashes.
    """
    mock_cache.get_hash.return_value = None
    reader = HashReader()
    non_existent_path = "/path/that/does/not/exist"

    result = reader.get(file_path=non_existent_path, hashes=["SHA-256", "QUICK"])

    assert result["SHA-256"] is None
    assert result["QUICK"] is None
    mock_cache.get_hash.assert_called()
    mock_cache.upsert_hash.assert_not_called()


@patch("dorsal.file.hash_reader.QUICK_HASHER")
def test_get_quick_hash_failure(mock_quick_hasher, mock_cache, test_file):
    """
    Tests that if QUICK_HASHER raises a specific exception, the result for
    'QUICK' is None, but other hashes can still be processed.
    """
    mock_cache.get_hash.return_value = None
    mock_quick_hasher.hash.side_effect = QuickHashFileSizeError("File too small")

    with patch("dorsal.file.hash_reader.FILE_HASHER") as mock_file_hasher:
        mock_file_hasher.hash.return_value = {"SHA-256": "sha256_ok"}
        reader = HashReader()

        result = reader.get(file_path=str(test_file), hashes=["SHA-256", "QUICK"])

        assert result["SHA-256"] == "sha256_ok"
        assert result["QUICK"] is None
        mock_cache.upsert_hash.assert_called_once_with(
            path=str(test_file),
            modified_time=pytest.approx(test_file.stat().st_mtime),
            hash_function="SHA-256",
            hash_value="sha256_ok",
        )
