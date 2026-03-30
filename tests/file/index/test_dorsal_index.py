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

import pytest
import sqlite3
import zlib
import os
import time
import json
from unittest.mock import patch, MagicMock
from pathlib import Path

from dorsal.file.index.dorsal_index import DorsalIndex, CachedFileRecord


@pytest.fixture
def temp_index(tmp_path: Path) -> DorsalIndex:
    """
    Provides a clean DorsalIndex instance pointed to a unique temporary
    database file for each test. The tmp_path fixture is managed by pytest.
    """
    db_path = tmp_path / "test_index.db"
    index = DorsalIndex(db_path=db_path, use_compression=True)
    index.connect()
    yield index
    index.close()


@pytest.fixture
def mock_file_record_strict(mocker) -> MagicMock:
    """Provides a mock FileRecordStrict object configured to test FTS and EAV extraction."""
    record = mocker.MagicMock()

    record.annotations.file_base.record.name = "test.pdf"
    record.annotations.file_base.record.extension = ".pdf"
    record.annotations.file_base.record.size = 1024
    record.annotations.file_base.record.media_type = "application/pdf"
    record.annotations.file_base.record.all_hash_ids = {"SHA-256": "fakehash256"}

    tag = mocker.MagicMock()
    tag.name = "project"
    tag.value = "alpha"
    record.tags = [tag]

    record.annotations.model_dump.return_value = {
        "open/generic": {"record": {"description": "highly confidential financial data", "producer": "test-runner"}}
    }

    record.model_dump_json.return_value = '{"test": "data"}'
    return record


def test_upsert_and_get_record_compressed(temp_index: DorsalIndex, mock_file_record_strict):
    """Test inserting and retrieving a compressed record."""
    temp_index.upsert_record(path="/fake/test.pdf", modified_time=123.45, record=mock_file_record_strict)

    fetched = temp_index.get_record(path="/fake/test.pdf")
    assert fetched is not None
    assert fetched.abspath == "/fake/test.pdf"
    assert fetched.modified_time == 123.45
    assert fetched.name == "test.pdf"
    assert fetched.hash_sha256 == "fakehash256"
    assert json.loads(fetched.record_json) == {"test": "data"}


def test_upsert_and_get_record_uncompressed(temp_index: DorsalIndex, mock_file_record_strict):
    """Test inserting and retrieving an uncompressed record."""
    temp_index.use_compression = False
    temp_index.upsert_record(path="/fake/test.pdf", modified_time=123.45, record=mock_file_record_strict)

    fetched = temp_index.get_record(path="/fake/test.pdf")
    assert fetched is not None
    assert json.loads(fetched.record_json) == {"test": "data"}


def test_upsert_record_populates_search_indexes(temp_index: DorsalIndex, mock_file_record_strict):
    """Verifies that FTS5 and EAV tables are populated during an upsert."""
    temp_index.upsert_record(path="/fake/test.pdf", modified_time=123.45, record=mock_file_record_strict)

    cursor = temp_index.conn.cursor()

    cursor.execute("SELECT content FROM dorsal_fts WHERE abspath = ?", ("/fake/test.pdf",))
    fts_row = cursor.fetchone()
    assert fts_row is not None
    content = fts_row["content"]
    assert "test.pdf" in content
    assert ".pdf" in content
    assert "highly confidential financial data" in content

    cursor.execute("SELECT schema_id, key, value_text FROM file_attributes WHERE abspath = ?", ("/fake/test.pdf",))
    eav_rows = cursor.fetchall()
    assert len(eav_rows) > 0

    eav_dicts = [{"schema": r["schema_id"], "key": r["key"], "val": r["value_text"]} for r in eav_rows]

    assert {"schema": "tag", "key": "project", "val": "alpha"} in eav_dicts

    assert {"schema": "open/generic", "key": "producer", "val": "test-runner"} in eav_dicts


@patch("os.lstat")
def test_upsert_hash_and_get_hash(mock_lstat, temp_index: DorsalIndex):
    """Test inserting and retrieving a single hash."""
    mock_stat = MagicMock()
    mock_stat.st_mtime = 123.45
    mock_lstat.return_value = mock_stat

    temp_index.upsert_hash(
        path="/fake/hash_only.pdf",
        modified_time=123.45,
        hash_function="BLAKE3",
        hash_value="abc123blake",
    )

    fetched_hash = temp_index.get_hash(path="/fake/hash_only.pdf", hash_function="BLAKE3")
    assert fetched_hash == "abc123blake"


@patch("os.path.exists")
@patch("os.lstat")
def test_prune_removes_stale_records_and_indexes(
    mock_lstat, mock_exists, temp_index: DorsalIndex, mock_file_record_strict
):
    """Test that prune removes records AND their search indexes if files are missing or modified."""

    temp_index.upsert_record(path="/fake/missing.pdf", modified_time=100.0, record=mock_file_record_strict)

    mock_exists.return_value = False

    removed, total = temp_index.prune()
    assert removed == 1
    assert total == 1

    cursor = temp_index.conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM cached_files")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM dorsal_fts")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM file_attributes")
    assert cursor.fetchone()[0] == 0


@patch("dorsal.file.index.dorsal_index.DorsalIndex.prune")
@patch("dorsal.file.index.dorsal_index.DorsalIndex._sync_compression")
@patch("dorsal.file.index.dorsal_index.DorsalIndex.vacuum")
def test_optimize_runs_all_maintenance(mock_vacuum, mock_sync, mock_prune, temp_index: DorsalIndex):
    """Test that optimize calls prune, sync, and vacuum."""
    mock_prune.return_value = (5, 10)
    mock_sync.return_value = 2

    result = temp_index.optimize()

    mock_prune.assert_called_once()
    mock_sync.assert_called_once()
    mock_vacuum.assert_called_once()

    assert result["stale_records_removed"] == 5
    assert result["records_rewritten_for_compression"] == 2


def test_sync_compression_compresses_records(temp_index: DorsalIndex):
    """Test that _sync_compression correctly compresses uncompressed records."""
    temp_index.use_compression = True
    uncompressed_data = b'{"test": "data"}'

    cursor = temp_index.conn.cursor()
    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, record, is_compressed) VALUES (?, ?, ?, ?)",
        ("/fake/file.txt", 123.45, uncompressed_data, 0),
    )
    temp_index.conn.commit()

    rewritten_count = temp_index._sync_compression()
    assert rewritten_count == 1

    cursor.execute(
        "SELECT record, is_compressed FROM cached_files WHERE abspath = ?",
        ("/fake/file.txt",),
    )
    row = cursor.fetchone()
    assert row["is_compressed"] == 1
    assert zlib.decompress(row["record"]) == uncompressed_data


def test_export_json_gz(temp_index: DorsalIndex, mock_file_record_strict, tmp_path):
    """Test exporting the index to a gzipped JSON file."""
    temp_index.upsert_record(path="/fake/export.pdf", modified_time=123.45, record=mock_file_record_strict)

    export_path = tmp_path / "export.json.gz"
    exported_count = temp_index.export(output_path=export_path, format="json.gz", include_records=True)

    assert exported_count == 1
    assert export_path.exists()


def test_get_record_null_blob(temp_index: DorsalIndex):
    """Covers the branch where a DB row exists, but the record blob is NULL."""
    cursor = temp_index.conn.cursor()

    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, hash_sha256) VALUES (?, ?, ?)",
        ("/fake/null_blob.txt", 100.0, "dummy_hash"),
    )
    temp_index.conn.commit()

    assert temp_index.get_record(path="/fake/null_blob.txt") is None


def test_hash_functions_unsupported(temp_index: DorsalIndex):
    """Covers the ValueError branches for unsupported hash functions."""
    with pytest.raises(ValueError, match="Unsupported hash function"):
        temp_index.upsert_hash(path="/fake/a.txt", modified_time=100.0, hash_function="MD5", hash_value="123")

    with pytest.raises(ValueError, match="Unsupported hash function"):
        temp_index.get_hash(path="/fake/a.txt", hash_function="INVALID_HASH")


def test_upsert_hash_overwrites_stale_full_record(temp_index: DorsalIndex, mock_file_record_strict):
    """
    Covers the branch where upsert_hash detects a stale FULL record (mtime mismatch),
    and actively deletes the FTS and EAV indexes before inserting the new hash.
    """
    path = "/fake/stale_upsert.pdf"

    temp_index.upsert_record(path=path, modified_time=100.0, record=mock_file_record_strict)

    cursor = temp_index.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dorsal_fts WHERE abspath = ?", (path,))
    assert cursor.fetchone()[0] == 1

    temp_index.upsert_hash(path=path, modified_time=200.0, hash_function="SHA-256", hash_value="new_hash")

    assert temp_index.get_record(path=path) is None

    cursor.execute("SELECT COUNT(*) FROM dorsal_fts WHERE abspath = ?", (path,))
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM file_attributes WHERE abspath = ?", (path,))
    assert cursor.fetchone()[0] == 0


def test_get_hash_file_not_found(temp_index: DorsalIndex, fs):
    """Covers the branch where os.lstat raises FileNotFoundError."""
    path = "/fake/missing.txt"
    fs.create_file(path)

    temp_index.upsert_hash(path=path, modified_time=os.lstat(path).st_mtime, hash_function="SHA-256", hash_value="abc")

    os.remove(path)

    assert temp_index.get_hash(path=path) is None


def test_get_hash_missing_specific_hash(temp_index: DorsalIndex, fs):
    """Covers the branch where the record exists, but the requested hash type does not."""
    path = "/fake/partial_hash.txt"
    fs.create_file(path)
    mtime = os.lstat(path).st_mtime

    temp_index.upsert_hash(path=path, modified_time=mtime, hash_function="SHA-256", hash_value="abc")

    assert temp_index.get_hash(path=path, hash_function="BLAKE3") is None


def test_default_db_path_and_mkdir(mocker, tmp_path):
    """Covers the default Path.home() routing and automatic directory creation."""

    mocker.patch("pathlib.Path.home", return_value=tmp_path)

    index = DorsalIndex(db_path=None)

    expected_dir = tmp_path / ".dorsal"
    expected_path = expected_dir / "cache.db"

    assert index.db_path == expected_path
    assert expected_dir.exists()


def test_ensure_connection_failure():
    """Covers the RuntimeError when a connection completely fails to establish."""
    index = DorsalIndex()

    index.connect = lambda: None

    with pytest.raises(RuntimeError, match="Database connection could not be established."):
        index._ensure_connection()


def test_finalize_connection_exception(mocker):
    """Covers the silent Exception swallowing in the weakref finalizer."""
    mock_conn = mocker.MagicMock()
    mock_conn.close.side_effect = Exception("Simulated connection teardown error")

    DorsalIndex._finalize_connection(mock_conn)
    mock_conn.close.assert_called_once()


def test_clear_os_error(temp_index: DorsalIndex, mocker, caplog):
    """Covers the OSError branch when the database file cannot be deleted."""

    mocker.patch("os.remove", side_effect=OSError("Simulated Permission Denied"))

    temp_index.clear()

    assert "Error removing file at" in caplog.text


def test_summary_file_not_found(temp_index: DorsalIndex, mocker):
    """Covers the FileNotFoundError when generating a summary of a missing DB file."""

    mocker.patch("os.stat", side_effect=FileNotFoundError())

    summary = temp_index.summary()

    assert summary["database_size_bytes"] == 0


def test_sync_compression_none_data_and_already_synced(temp_index: DorsalIndex):
    """Covers the 'data is None' branch and the 'already synced' else branch."""
    conn = temp_index.conn
    cursor = conn.cursor()

    cursor.execute("INSERT INTO cached_files (abspath, modified_time) VALUES (?, ?)", ("/fake/null.txt", 123.0))
    conn.commit()

    rewritten = temp_index._sync_compression()
    assert rewritten == 0

    rewritten = temp_index._sync_compression()
    assert rewritten == 0


def test_sync_compression_decompression(temp_index: DorsalIndex):
    """Covers the decompression branch in _sync_compression."""

    temp_index.use_compression = False
    conn = temp_index.conn
    cursor = conn.cursor()

    fake_data = b'{"hello": "world"}'
    compressed_data = zlib.compress(fake_data)

    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, record, is_compressed) VALUES (?, ?, ?, ?)",
        ("/fake/compressed.txt", 123.0, compressed_data, 1),
    )
    conn.commit()

    rewritten = temp_index._sync_compression()
    assert rewritten == 1

    cursor.execute("SELECT record, is_compressed FROM cached_files WHERE abspath = ?", ("/fake/compressed.txt",))
    row = cursor.fetchone()
    assert row["is_compressed"] == 0
    assert row["record"] == fake_data


def test_export_unwritable_path(temp_index: DorsalIndex, mocker):
    """Covers the IOError branch when export path is not writable."""

    mocker.patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied"))

    out_path = Path("/fake/unwritable/export.json.gz")
    with pytest.raises(IOError, match="is not writable"):
        temp_index.export(output_path=out_path)


def test_export_decode_error(temp_index: DorsalIndex, tmp_path):
    """Covers the zlib/json decode error fallback branch during export."""
    conn = temp_index.conn
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO cached_files (abspath, modified_time, record, is_compressed) VALUES (?, ?, ?, ?)",
        ("/fake/corrupt.txt", 123.0, b"this is not valid zlib data", 1),
    )
    conn.commit()

    out_path = tmp_path / "corrupt_export.json"

    exported_count = temp_index.export(output_path=out_path, format="json")
    assert exported_count == 1

    with open(out_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data[0]["abspath"] == "/fake/corrupt.txt"
    assert data[0]["record"] == {"error": "Could not decode record"}


def test_export_json_format(temp_index: DorsalIndex, tmp_path, mock_file_record_strict):
    """Covers the standard uncompressed 'json' format export branch."""
    temp_index.upsert_record(path="/fake/valid.pdf", modified_time=123.0, record=mock_file_record_strict)

    out_path = tmp_path / "standard_export.json"
    exported_count = temp_index.export(output_path=out_path, format="json")

    assert exported_count == 1
    assert out_path.exists()

    with open(out_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data[0]["abspath"] == "/fake/valid.pdf"
    assert "test" in data[0]["record"]


def test_export_unsupported_format(temp_index: DorsalIndex, tmp_path):
    """Covers the ValueError branch for an unknown export format."""
    out_path = tmp_path / "bad_format.csv"
    with pytest.raises(ValueError, match="Unsupported export format: csv"):
        temp_index.export(output_path=out_path, format="csv")


def test_extract_search_data_no_annotations(temp_index):
    mock_record = MagicMock()
    mock_record.annotations = None

    fts, eav = temp_index._extract_search_data(mock_record)
    assert fts == []
    assert eav == []


def test_extract_search_data_null_and_malformed_annotations(temp_index):
    """Hits 188↛189 and 198↛199: None values and non-dict records in annotation list."""
    mock_record = MagicMock()

    mock_record.annotations.file_base = None

    mock_record.annotations.model_dump.return_value = {
        "schema/null": None,
        "schema/bad-type": [{"record": "not-a-dict"}],
    }
    fts, eav = temp_index._extract_search_data(mock_record)

    assert fts == []
    assert eav == []


def test_extract_search_data_nested_model_dump(temp_index):
    mock_inner_model = MagicMock()
    mock_inner_model.model_dump.return_value = {"producer": "nested-pydantic"}

    mock_record = MagicMock()
    mock_record.annotations.model_dump.return_value = {"open/generic": [{"record": mock_inner_model}]}
    fts, eav = temp_index._extract_search_data(mock_record)

    assert any("nested-pydantic" in str(x) for x in eav)


def test_get_record_miss(temp_index):
    assert temp_index.get_record(path="/non/existent/path") is None


def test_get_hash_miss_and_stale(temp_index, fs):
    path = "/fake/file.txt"
    fs.create_file(path)

    assert temp_index.get_hash(path=path) is None

    temp_index.upsert_hash(path=path, modified_time=100.0, hash_function="SHA-256", hash_value="abc")
    os.utime(path, (200.0, 200.0))
    assert temp_index.get_hash(path=path) is None


def test_clear_file_exists(temp_index):
    db_path = temp_index.db_path
    assert db_path.exists()
    temp_index.clear()
    assert not db_path.exists()


def test_prune_no_stale_records(temp_index, fs, mock_file_record_strict):
    path = "/fake/fresh.pdf"
    fs.create_file(path)
    temp_index.upsert_record(path=path, modified_time=os.path.getmtime(path), record=mock_file_record_strict)

    pruned, total = temp_index.prune()
    assert pruned == 0
    assert total == 1


def test_prune_file_disappeared_during_check(temp_index, fs, mock_file_record_strict, mocker):
    path = "/fake/ghost.pdf"
    fs.create_file(path)
    temp_index.upsert_record(path=path, modified_time=os.path.getmtime(path), record=mock_file_record_strict)

    mocker.patch("os.lstat", side_effect=FileNotFoundError)

    pruned, total = temp_index.prune()
    assert pruned == 1


def test_vacuum_execution(temp_index):
    """Ensures the vacuum method runs without error."""

    temp_index.vacuum()


def test_export_uncompressed_decode(temp_index, fs, mock_file_record_strict, tmp_path):
    temp_index.use_compression = False
    path = "/fake/uncompressed.pdf"
    fs.create_file(path)
    temp_index.upsert_record(path=path, modified_time=100.0, record=mock_file_record_strict)

    out = tmp_path / "export.json"
    temp_index.export(output_path=out, format="json")

    with open(out, "r") as f:
        data = json.load(f)
    assert data[0]["record"]["test"] == "data"


def test_prune_mtime_mismatch(temp_index, fs, mock_file_record_strict):
    """Specifically hits the mtime mismatch branch in prune()."""
    path = "/fake/stale_file.pdf"
    fs.create_file(path)

    temp_index.upsert_record(path=path, modified_time=100.0, record=mock_file_record_strict)

    os.utime(path, (200.0, 200.0))

    removed, total = temp_index.prune()

    assert removed == 1
    assert total == 1


def test_summary_base_metrics_only(temp_index: DorsalIndex, mock_file_record_strict):
    """Test that default summary() only returns base metrics."""
    temp_index.upsert_record(path="/fake/test.pdf", modified_time=123.45, record=mock_file_record_strict)

    summary = temp_index.summary()  # verbose=False by default

    # Assert base keys are present
    assert "total_records" in summary
    assert summary["total_records"] == 1
    assert "database_size_bytes" in summary
    assert "fts_indexed_records" in summary

    # Assert verbose keys are ABSENT
    assert "indexed_attributes" not in summary
    assert "total_tracked_file_bytes" not in summary
    assert "compressed_records" not in summary
    assert "top_extensions" not in summary


def test_summary_verbose_metrics(temp_index: DorsalIndex, mock_file_record_strict):
    """Test that summary(verbose=True) includes extended metrics."""
    temp_index.upsert_record(path="/fake/test.pdf", modified_time=123.45, record=mock_file_record_strict)

    summary = temp_index.summary(verbose=True)

    # Assert verbose keys are present
    assert "indexed_attributes" in summary
    assert summary["indexed_attributes"] > 0
    assert "total_tracked_file_bytes" in summary
    assert "compressed_records" in summary
    assert "top_extensions" in summary
    assert "top_media_types" in summary
    assert "top_schemas" in summary
