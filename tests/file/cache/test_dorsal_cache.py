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
import sqlite3
import zlib
import os
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

from dorsal.file.cache.dorsal_cache import DorsalCache, CachedFileRecord


@pytest.fixture
def temp_cache(tmp_path: Path) -> DorsalCache:
    """
    Provides a clean DorsalCache instance pointed to a unique temporary
    database file for each test. The tmp_path fixture is managed by pytest.
    """
    db_path = tmp_path / "test_cache.db"
    cache = DorsalCache(db_path=db_path)
    cache.connect()
    yield cache
    cache.close()


@pytest.fixture
def mock_file_record_strict() -> MagicMock:
    """Provides a mock FileRecordStrict object for testing insertions."""
    record = MagicMock()
    record.annotations.file_base.record.name = "test.pdf"
    record.annotations.file_base.record.size = 1024
    record.annotations.file_base.record.extension = ".pdf"
    record.annotations.file_base.record.media_type = "application/pdf"
    record.annotations.file_base.record.all_hash_ids = {
        "SHA-256": "a" * 64,
        "QUICK": "b" * 64,
    }
    record.model_dump_json.return_value = '{"hash": "a...'
    return record


# --- Tests ---


def test_initialization_and_schema(temp_cache: DorsalCache):
    """Test that the database table and indexes are created on connection."""
    cursor = temp_cache.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cached_files'")
    assert cursor.fetchone() is not None

    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_hash_sha256'")
    assert cursor.fetchone() is not None


def test_upsert_and_get_record_uncompressed(temp_cache: DorsalCache, mock_file_record_strict):
    """Test inserting and retrieving a record with compression disabled."""
    temp_cache.use_compression = False
    path, mtime = "/fake/file.pdf", 12345.6789

    temp_cache.upsert_record(path=path, modified_time=mtime, record=mock_file_record_strict)
    cached_record = temp_cache.get_record(path=path)

    assert isinstance(cached_record, CachedFileRecord)
    assert cached_record.abspath == path
    assert cached_record.name == "test.pdf"


def test_upsert_and_get_record_compressed(temp_cache: DorsalCache, mock_file_record_strict):
    """Test that records are correctly compressed and decompressed."""
    temp_cache.use_compression = True
    path, mtime = "/fake/file.pdf", 12345.6789

    temp_cache.upsert_record(path=path, modified_time=mtime, record=mock_file_record_strict)
    cached_record = temp_cache.get_record(path=path)

    assert cached_record is not None
    assert cached_record.record_json == '{"hash": "a...'

    cursor = temp_cache.conn.cursor()
    cursor.execute("SELECT is_compressed FROM cached_files WHERE abspath = ?", (path,))
    assert cursor.fetchone()["is_compressed"] == 1


def test_get_record_not_found(temp_cache: DorsalCache):
    """Test that get_record returns None for a path that doesn't exist."""
    assert temp_cache.get_record(path="/does/not/exist.txt") is None


def test_upsert_and_get_hash_success(temp_cache: DorsalCache, fs):
    """Test inserting a single hash and retrieving it successfully."""
    file_path = "/fake/file.txt"
    fs.create_file(file_path)
    current_mtime = os.path.getmtime(file_path)

    temp_cache.upsert_hash(
        path=file_path,
        modified_time=current_mtime,
        hash_function="SHA-256",
        hash_value="a" * 64,
    )

    retrieved_hash = temp_cache.get_hash(path=file_path, hash_function="SHA-256")
    assert retrieved_hash == "a" * 64


def test_get_hash_stale_record(temp_cache: DorsalCache, fs):
    """Test that get_hash returns None if the file's modification time has changed."""
    file_path = "/fake/file.txt"
    fs.create_file(file_path)
    old_mtime = os.path.getmtime(file_path)

    temp_cache.upsert_hash(
        path=file_path,
        modified_time=old_mtime,
        hash_function="SHA-256",
        hash_value="a" * 64,
    )

    time.sleep(0.01)  # Ensure timestamp will be different
    new_mtime = time.time()
    os.utime(file_path, (new_mtime, new_mtime))

    retrieved_hash = temp_cache.get_hash(path=file_path, hash_function="SHA-256")
    assert retrieved_hash is None


def test_clear(temp_cache: DorsalCache):
    """Test that the clear method deletes the database file."""
    db_path = temp_cache.db_path
    assert db_path.exists()

    temp_cache.clear()

    assert not db_path.exists()
    assert temp_cache.conn is None


def test_summary(temp_cache: DorsalCache, mock_file_record_strict):
    """Test that the cache summary provides accurate counts."""
    # 1. Insert one full record
    temp_cache.upsert_record(path="/fake/full.pdf", modified_time=123.45, record=mock_file_record_strict)

    # 2. Insert one hash-only record
    temp_cache.upsert_hash(
        path="/fake/hash_only.txt",
        modified_time=123.45,
        hash_function="SHA-256",
        hash_value="b" * 64,
    )

    summary = temp_cache.summary()

    assert summary["total_records"] == 2
    assert summary["full_records"] == 1
    assert summary["hash_only_records"] == 1
    assert summary["database_size_bytes"] > 0


def test_prune(temp_cache: DorsalCache, fs):
    """Test that prune correctly removes records for deleted or modified files."""
    # 1. Setup the fake filesystem and cache records
    fs.create_file("/fake/current.txt")
    fs.create_file("/fake/stale.txt")
    fs.create_file("/fake/deleted.txt")

    mtime_current = os.path.getmtime("/fake/current.txt")
    mtime_stale = os.path.getmtime("/fake/stale.txt")
    mtime_deleted = os.path.getmtime("/fake/deleted.txt")

    temp_cache.upsert_hash(
        path="/fake/current.txt",
        modified_time=mtime_current,
        hash_function="SHA-256",
        hash_value="a" * 64,
    )
    temp_cache.upsert_hash(
        path="/fake/stale.txt",
        modified_time=mtime_stale,
        hash_function="SHA-256",
        hash_value="b" * 64,
    )
    temp_cache.upsert_hash(
        path="/fake/deleted.txt",
        modified_time=mtime_deleted,
        hash_function="SHA-256",
        hash_value="c" * 64,
    )

    # 2. Alter the filesystem
    os.remove("/fake/deleted.txt")
    time.sleep(0.01)
    # Update the modification time of the stale file
    with open("/fake/stale.txt", "w") as f:
        f.write("new content")

    # 3. Run prune and check the results
    pruned_count, total_records = temp_cache.prune()

    assert pruned_count == 2
    assert total_records == 3

    # 4. Verify the correct records remain in the DB
    assert temp_cache.get_hash(path="/fake/current.txt") is not None
    assert temp_cache.get_hash(path="/fake/stale.txt") is None
    assert temp_cache.get_hash(path="/fake/deleted.txt") is None


def test_close_connection(temp_cache: DorsalCache):
    """Test that the close method closes the database connection."""
    connection = temp_cache.conn
    assert connection is not None

    temp_cache.close()

    assert temp_cache.conn is None
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database."):
        connection.execute("SELECT 1")


def test_vacuum(temp_cache: DorsalCache):
    """Test that the vacuum method executes the VACUUM command."""
    executed_sql = []

    def trace_callback(statement):
        executed_sql.append(statement)

    # Use the built-in sqlite3 tracer to record executed commands
    temp_cache.conn.set_trace_callback(trace_callback)

    temp_cache.vacuum()

    # Assert that the VACUUM command was present in the executed statements
    assert "VACUUM" in " ".join(executed_sql)


@patch("dorsal.file.cache.dorsal_cache.os.path.getsize")
def test_optimize(mock_getsize, temp_cache: DorsalCache):
    """Test the optimize method to ensure it orchestrates other methods correctly."""
    # Mock the methods that optimize calls
    temp_cache.prune = MagicMock(return_value=(5, 100))  # 5 pruned
    temp_cache._sync_compression = MagicMock(return_value=10)  # 10 rewritten
    temp_cache.vacuum = MagicMock()

    # Mock the file size before and after
    mock_getsize.side_effect = [2048, 1024]  # size_before, size_after

    result = temp_cache.optimize()

    # Assert that all underlying methods were called
    temp_cache.prune.assert_called_once()
    temp_cache._sync_compression.assert_called_once()
    temp_cache.vacuum.assert_called_once()

    # Assert the summary is calculated correctly
    assert result["stale_records_removed"] == 5
    assert result["records_rewritten_for_compression"] == 10
    assert result["size_before_bytes"] == 2048
    assert result["size_after_bytes"] == 1024
    assert result["size_reclaimed_bytes"] == 1024


def test_sync_compression_compresses_records(temp_cache: DorsalCache):
    """Test that _sync_compression correctly compresses uncompressed records."""
    temp_cache.use_compression = True
    uncompressed_data = b'{"test": "data"}'

    # Manually insert an uncompressed record
    cursor = temp_cache.conn.cursor()
    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, record, is_compressed) VALUES (?, ?, ?, ?)",
        ("/fake/file.txt", 123.45, uncompressed_data, 0),
    )
    temp_cache.conn.commit()

    rewritten_count = temp_cache._sync_compression()
    assert rewritten_count == 1

    # Verify the record is now compressed
    cursor.execute(
        "SELECT record, is_compressed FROM cached_files WHERE abspath = ?",
        ("/fake/file.txt",),
    )
    row = cursor.fetchone()
    assert row["is_compressed"] == 1
    assert zlib.decompress(row["record"]) == uncompressed_data


def test_sync_compression_decompresses_records(temp_cache: DorsalCache):
    """Test that _sync_compression correctly decompresses compressed records."""
    temp_cache.use_compression = False
    uncompressed_data = b'{"test": "data"}'
    compressed_data = zlib.compress(uncompressed_data)

    # Manually insert a compressed record
    cursor = temp_cache.conn.cursor()
    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, record, is_compressed) VALUES (?, ?, ?, ?)",
        ("/fake/file.txt", 123.45, compressed_data, 1),
    )
    temp_cache.conn.commit()

    rewritten_count = temp_cache._sync_compression()
    assert rewritten_count == 1

    # Verify the record is now uncompressed
    cursor.execute(
        "SELECT record, is_compressed FROM cached_files WHERE abspath = ?",
        ("/fake/file.txt",),
    )
    row = cursor.fetchone()
    assert row["is_compressed"] == 0
    assert row["record"] == uncompressed_data
