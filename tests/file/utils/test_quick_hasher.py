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
import os
from dorsal.file.utils.quick_hasher import QuickHasher
from dorsal.common.exceptions import QuickHashConfigurationError, QuickHashFileSizeError, QuickHashFileInstabilityError


@pytest.fixture
def hasher():
    return QuickHasher()


@pytest.fixture
def small_file(tmp_path):
    """File smaller than one chunk."""
    p = tmp_path / "small.bin"
    p.write_bytes(b"small_content")
    return p


@pytest.fixture
def large_file(tmp_path):
    """File large enough to trigger sampling."""
    p = tmp_path / "large.bin"
    p.write_bytes(b"A" * 1024)
    return p


# --- Tests ---


def test_get_total_chunks_error(hasher):
    hasher.chunk_size = 0
    with pytest.raises(QuickHashConfigurationError):
        hasher._get_total_chunks(100)


def test_make_seed_error(hasher):
    hasher.PREDICTABLE_SEQUENCE_LENGTH = 0
    with pytest.raises(QuickHashConfigurationError):
        hasher._make_seed(100)


def test_make_seed_valid(hasher):
    # 100 % 1024 = 100
    assert hasher._make_seed(100) == 100


def test_get_chunk_count(hasher):
    # Test boundary logic
    assert hasher._get_chunk_count(hasher.upper_filesize_chunks + 1) == hasher.max_chunks
    assert hasher._get_chunk_count(hasher.lower_filesize_chunks - 1) == hasher.min_chunks

    # Test bisect logic (middle ground)
    # We use a specific value we know falls in the middle
    mid_size = hasher.lower_filesize_chunks * 2
    count = hasher._get_chunk_count(mid_size)
    assert hasher.min_chunks <= count <= hasher.max_chunks


def test_random_sample_chunk_indices_empty(hasher):
    assert hasher._random_sample_chunk_indices(0, 10, 0) == []
    assert hasher._random_sample_chunk_indices(100, 0, 10) == []


def test_random_sample_chunk_indices_logic(hasher):
    # Request 5 chunks from a file with 10 chunks
    indices = hasher._random_sample_chunk_indices(1000, 5, 10)
    assert len(indices) == 5
    assert indices == sorted(indices)
    assert max(indices) < 10


def test_check_permitted_filesize(hasher):
    # Too small
    assert hasher._check_permitted_filesize("f", 1, raise_on_error=False) is False
    with pytest.raises(QuickHashFileSizeError):
        hasher._check_permitted_filesize("f", 1, raise_on_error=True)

    # Valid
    valid_size = hasher.min_permitted_filesize + 1
    assert hasher._check_permitted_filesize("f", valid_size, raise_on_error=True) is True


def test_hash_too_small_returns_none(hasher, small_file):
    """Test logic when file is valid but filtered out by min_permitted_filesize."""
    size = small_file.stat().st_size
    # Ensure our small file is actually below the threshold for the test
    hasher.min_permitted_filesize = size + 100

    assert hasher.hash(str(small_file), size) is None


def test_hash_small_file_full_read(hasher, small_file):
    """Test that small files (within permitted range but < chunk size) are fully read."""
    size = small_file.stat().st_size
    hasher.min_permitted_filesize = 0  # Allow it
    hasher.chunk_size = size + 100  # Ensure it's treated as < 1 chunk

    digest = hasher.hash(str(small_file), size)
    assert digest is not None
    # Should match standard sha256 of content
    import hashlib

    assert digest == hashlib.sha256(b"small_content").hexdigest()


def test_hash_sampling(hasher, large_file):
    """Test the sampling path."""
    size = large_file.stat().st_size
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = 10  # Small chunks to force sampling logic

    digest = hasher.hash(str(large_file), size)
    assert digest is not None
    assert len(digest) == 64  # Hex string length for sha256


def test_hash_instability_offset_error(hasher, large_file, mocker):
    """Test file shrinking during hash (seek passes end of file)."""
    size = 1000
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = 10

    # Mock open to allow context manager
    m = mocker.mock_open()
    mocker.patch("builtins.open", m)

    # We need to simulate _random_sample_chunk_indices returning at least one index
    # that will calculate an offset > file_size
    mocker.patch.object(hasher, "_random_sample_chunk_indices", return_value=[200])  # 200 * 10 = 2000 > 1000

    with pytest.raises(QuickHashFileInstabilityError) as exc:
        hasher.hash("fake_path", size)
    assert "exceeds current file size" in str(exc.value)


def test_hash_instability_empty_chunk(hasher, large_file, mocker):
    """Test file shrinking during hash (read returns empty bytes)."""
    size = 1000
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = 10

    m = mocker.mock_open()
    mocker.patch("builtins.open", m)
    handle = m()
    handle.read.return_value = b""  # EOF too early

    mocker.patch.object(hasher, "_random_sample_chunk_indices", return_value=[0])

    with pytest.raises(QuickHashFileInstabilityError) as exc:
        hasher.hash("fake_path", size)
    assert "Read empty chunk" in str(exc.value)


def test_hash_os_error_during_read(hasher, small_file, mocker):
    """Test handling of OS errors during read operations."""
    size = small_file.stat().st_size
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = size + 100  # Full read path

    mocker.patch("builtins.open", side_effect=OSError("Disk failure"))

    with pytest.raises(OSError):
        hasher.hash(str(small_file), size)
