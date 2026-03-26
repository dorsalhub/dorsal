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
