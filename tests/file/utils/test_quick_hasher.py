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


def test_get_total_chunks_error(hasher):
    hasher.chunk_size = 0
    with pytest.raises(QuickHashConfigurationError):
        hasher._get_total_chunks(100)


def test_make_seed_error(hasher):
    hasher.PREDICTABLE_SEQUENCE_LENGTH = 0
    with pytest.raises(QuickHashConfigurationError):
        hasher._make_seed(100)


def test_make_seed_valid(hasher):

    assert hasher._make_seed(100) == 100


def test_get_chunk_count(hasher):

    assert hasher._get_chunk_count(hasher.upper_filesize_chunks + 1) == hasher.max_chunks
    assert hasher._get_chunk_count(hasher.lower_filesize_chunks - 1) == hasher.min_chunks

    mid_size = hasher.lower_filesize_chunks * 2
    count = hasher._get_chunk_count(mid_size)
    assert hasher.min_chunks <= count <= hasher.max_chunks


def test_random_sample_chunk_indices_empty(hasher):
    assert hasher._random_sample_chunk_indices(0, 10, 0) == []
    assert hasher._random_sample_chunk_indices(100, 0, 10) == []


def test_random_sample_chunk_indices_logic(hasher):

    indices = hasher._random_sample_chunk_indices(1000, 5, 10)
    assert len(indices) == 5
    assert indices == sorted(indices)
    assert max(indices) < 10


def test_check_permitted_filesize(hasher):

    assert hasher._check_permitted_filesize("f", 1, raise_on_error=False) is False
    with pytest.raises(QuickHashFileSizeError):
        hasher._check_permitted_filesize("f", 1, raise_on_error=True)

    valid_size = hasher.min_permitted_filesize + 1
    assert hasher._check_permitted_filesize("f", valid_size, raise_on_error=True) is True


def test_hash_too_small_returns_none(hasher, small_file):
    """Test logic when file is valid but filtered out by min_permitted_filesize."""
    size = small_file.stat().st_size

    hasher.min_permitted_filesize = size + 100

    assert hasher.hash(str(small_file), size) is None


def test_hash_small_file_full_read(hasher, small_file):
    """Test that small files (within permitted range but < chunk size) are fully read."""
    size = small_file.stat().st_size
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = size + 100

    digest = hasher.hash(str(small_file), size)
    assert digest is not None

    import hashlib

    assert digest == hashlib.sha256(b"small_content").hexdigest()


def test_hash_sampling(hasher, large_file):
    """Test the sampling path."""
    size = large_file.stat().st_size
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = 10

    digest = hasher.hash(str(large_file), size)
    assert digest is not None
    assert len(digest) == 64


def test_hash_instability_offset_error(hasher, large_file, mocker):
    """Test file shrinking during hash (seek passes end of file)."""
    size = 1000
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = 10

    m = mocker.mock_open()
    mocker.patch("builtins.open", m)

    mocker.patch.object(hasher, "_random_sample_chunk_indices", return_value=[200])

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
    handle.read.return_value = b""

    mocker.patch.object(hasher, "_random_sample_chunk_indices", return_value=[0])

    with pytest.raises(QuickHashFileInstabilityError) as exc:
        hasher.hash("fake_path", size)
    assert "Read empty chunk" in str(exc.value)


def test_hash_os_error_during_read(hasher, small_file, mocker):
    """Test handling of OS errors during read operations."""
    size = small_file.stat().st_size
    hasher.min_permitted_filesize = 0
    hasher.chunk_size = size + 100

    mocker.patch("builtins.open", side_effect=OSError("Disk failure"))

    with pytest.raises(OSError):
        hasher.hash(str(small_file), size)
