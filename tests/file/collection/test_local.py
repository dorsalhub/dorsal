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
import json
import datetime
from unittest.mock import MagicMock, patch, mock_open

from dorsal.file.collection.local import LocalFileCollection
from dorsal.common.exceptions import InvalidTagError, DorsalError, SyncConflictError
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.validators.file_record import FileRecordStrict, NewFileTag, ValidateTagsResult
from dorsal.client.validators import FileIndexResponse


@pytest.fixture
def mock_metadata_reader():
    """Mocks the MetadataReader to avoid filesystem scans."""
    with patch("dorsal.file.collection.local.MetadataReader") as mock_reader_class:
        mock_instance = MagicMock()
        mock_reader_class.return_value = mock_instance
        yield mock_instance


# --- Tests ---


def test_local_collection_init_from_path(mock_metadata_reader):
    """Test initialization from a directory path string."""
    mock_file = MagicMock(spec=LocalFile)
    mock_metadata_reader.scan_directory.return_value = ([mock_file], ["warning1"])
    collection = LocalFileCollection(source="/fake/dir")
    mock_metadata_reader.scan_directory.assert_called_once_with(
        dir_path="/fake/dir",
        recursive=False,
        return_errors=True,
        console=None,
        palette=None,
        skip_cache=False,
        overwrite_cache=False,
    )
    assert len(collection) == 1
    assert collection.warnings == ["warning1"]


def test_info_method():
    """Test the info() method for accurate statistical summaries."""
    # Arrange
    now = datetime.datetime.now(tz=datetime.UTC)
    file1 = MagicMock(
        spec=LocalFile,
        size=2000,
        media_type="application/pdf",
        _source="disk",
        date_modified=now,
    )
    file1.name = "f1.pdf"
    file2 = MagicMock(
        spec=LocalFile,
        size=1000,
        media_type="image/jpeg",
        _source="cache",
        date_modified=now,
    )
    file2.name = "f2.jpg"
    file3 = MagicMock(
        spec=LocalFile,
        size=3000,
        media_type="application/pdf",
        _source="disk",
        date_modified=now,
    )
    file3.name = "f3.pdf"
    collection = LocalFileCollection(source=[file1, file2, file3])

    info = collection.info()

    assert "overall" in info
    assert info["overall"]["total_files"] == 3
    assert info["overall"]["total_size"] == 6000
    assert info["overall"]["smallest_file"]["path"] == "f2.jpg"
    assert info["overall"]["largest_file"]["path"] == "f3.pdf"


def test_find_duplicates():
    """Test the find_duplicates() method."""

    file1 = MagicMock(spec=LocalFile, hash="duplicate", size=150)
    file1.name = "a.txt"
    file1.to_dict.return_value = {"name": "a.txt"}
    file2 = MagicMock(spec=LocalFile, hash="unique", size=200)
    file2.name = "b.txt"
    file3 = MagicMock(spec=LocalFile, hash="duplicate", size=150)
    file3.name = "c.txt"
    file3.to_dict.return_value = {"name": "c.txt"}
    collection = LocalFileCollection(source=[file1, file2, file3])

    result = collection.find_duplicates()

    assert result["total_sets"] == 1
    assert result["total_wasted_space"] == "150 B"


def test_filter_method():
    """Test the filter() method with various conditions."""
    # Arrange
    file1 = MagicMock(spec=LocalFile, media_type="image/jpeg", size=100)
    file2 = MagicMock(spec=LocalFile, media_type="image/jpeg", size=1000)
    file3 = MagicMock(spec=LocalFile, media_type="text/plain", size=500)
    collection = LocalFileCollection(source=[file1, file2, file3])

    filtered_by_type = collection.filter(media_type="image/jpeg")
    filtered_by_size = collection.filter(size__gt=600)

    assert len(filtered_by_type) == 2
    assert len(filtered_by_size) == 1
    assert filtered_by_size.files[0].size == 1000


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_add_tags(mock_get_client):
    """Test successfully adding tags to all files in a collection."""
    # Arrange
    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)
    mock_get_client.return_value = mock_client

    file1 = MagicMock(spec=LocalFile)
    file1._add_local_tag = MagicMock()
    file2 = MagicMock(spec=LocalFile)
    file2._add_local_tag = MagicMock()
    collection = LocalFileCollection(source=[file1, file2])
    tags_to_add = [{"name": "status", "value": "approved", "private": True}]

    collection.add_tags(tags=tags_to_add)

    file1._add_local_tag.assert_called_once_with(name="status", value="approved", private=True)


def test_to_json_export():
    """Test exporting the collection to a JSON string."""
    file1 = MagicMock(spec=LocalFile)
    file1.to_dict.return_value = {"name": "a.txt", "hash": "h1"}
    file1.date_modified = datetime.datetime(2025, 1, 1, 1, 1, tzinfo=datetime.UTC)
    file1.date_created = datetime.datetime(2025, 1, 1, 1, 1, tzinfo=datetime.UTC)
    file1.size = 1000
    file1.name = "a.txt"
    file1.media_type = "text/plain"
    file1._source = "test"
    file1._file_path = "a.txt"

    collection = LocalFileCollection(source=[file1], source_info={"path": "/fake/dir"})

    assert collection._is_populated is True

    json_output = collection.to_json()
    data = json.loads(json_output)

    assert data["scan_metadata"]["path"] == "/fake/dir"
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "a.txt"


@patch("builtins.open", new_callable=mock_open)
def test_to_csv_export(mock_file_open):
    """Test exporting the collection to a CSV file."""
    file1 = MagicMock(spec=LocalFile, hash="h1", _file_path="/fake/a.txt")
    collection = LocalFileCollection(source=[file1], source_info={"path": "/fake/"})

    collection.to_csv("output.csv")

    mock_file_open.assert_called_once_with(file="output.csv", mode="w", newline="", encoding="utf-8")
    handle = mock_file_open()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)

    assert "hash,file_path,source_path" in written_data
    assert "h1,/fake/a.txt,/fake/" in written_data


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_push(mock_get_client):
    """Test pushing file records to the API."""
    mock_client = MagicMock()

    mock_response = MagicMock(spec=FileIndexResponse)
    mock_response.success = 1
    mock_client.index_private_file_records.return_value = mock_response

    mock_get_client.return_value = mock_client

    file1 = MagicMock(spec=LocalFile)
    file1.validation_hash = "b" * 64
    file1.model = MagicMock(spec=FileRecordStrict)
    collection = LocalFileCollection(source=[file1])
    collection._client = mock_client

    summary = collection.push(private=True)

    mock_client.index_private_file_records.assert_called_once_with(file_records=[file1.model])
    assert summary["total_records_accepted_by_api"] == 1


@patch("dorsal.file.collection.remote.DorsalFileCollection")
@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_create_remote_collection(mock_get_client, mock_remote_class):
    """Test the multi-step process of creating a new remote collection."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_client.create_collection.return_value = MagicMock(collection_id="new_col_123")
    mock_client.add_files_to_collection.return_value = MagicMock(added_count=1, duplicate_count=0)
    final_state = MagicMock()
    final_state.collection.date_modified = datetime.datetime.now()
    final_state.collection.file_count = 1
    mock_client.get_collection.return_value = final_state

    file1 = MagicMock(spec=LocalFile, hash="h1", validation_hash="vh1")
    file1.model = MagicMock()
    collection = LocalFileCollection(source=[file1])
    collection._client = mock_client

    with patch.object(collection, "push", return_value={"total_records_accepted_by_api": 1}) as mock_push:
        # Act
        collection.create_remote_collection(name="New Test Collection")

        # Assert
        mock_push.assert_called_once_with(private=True, api_key=None)
        mock_client.create_collection.assert_called_once()
        assert collection.remote_collection_id == "new_col_123"


def test_to_sqlite_export(tmp_path):
    """Test exporting the collection to an SQLite database by inspecting the output file."""
    sqlite3 = pytest.importorskip("sqlite3")

    file1 = MagicMock(spec=LocalFile, hash="h1", _file_path="/fake/a.txt")
    collection = LocalFileCollection(source=[file1], source_info={"path": "/fake/"})

    db_path = tmp_path / "test.db"

    collection.to_sqlite(str(db_path))

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT hash, file_path, source_path FROM files")
    result = cursor.fetchone()
    conn.close()

    assert result is not None
    assert result[0] == "h1"
    assert result[1] == "/fake/a.txt"
    assert result[2] == "/fake/"


def test_to_dataframe_export():
    """Test exporting the collection to a pandas DataFrame by inspecting the output."""
    pd = pytest.importorskip("pandas")

    file1 = MagicMock(spec=LocalFile, hash="h1", name="a.txt", _file_path="/fake/a.txt")
    collection = LocalFileCollection(source=[file1], source_info={"path": "/fake/"})

    df = collection.to_dataframe()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert list(df.columns) == ["hash", "file_path", "source_path"]
    assert df.iloc[0]["hash"] == "h1"
    assert df.iloc[0]["file_path"] == "/fake/a.txt"
