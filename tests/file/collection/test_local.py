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
import json
import datetime
from unittest.mock import MagicMock, patch, mock_open

from dorsal.file.collection.local import LocalFileCollection, _get_source_paths
from dorsal.common.exceptions import DorsalClientError, InvalidTagError, DorsalError, SyncConflictError
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
        follow_symlinks=True,
        lazy=False,
    )
    assert len(collection) == 1
    assert collection.warnings == ["warning1"]


def test_info_method():
    """Test the info() method for accurate statistical summaries."""

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

    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)
    mock_get_client.return_value = mock_client

    file1 = MagicMock(spec=LocalFile)
    file1._add_local_tag = MagicMock()
    file2 = MagicMock(spec=LocalFile)
    file2._add_local_tag = MagicMock()
    collection = LocalFileCollection(source=[file1, file2])
    tags_to_add = [{"name": "status", "value": "approved"}]

    collection.add_tags(tags=tags_to_add)

    file1._add_local_tag.assert_called_once_with(name="status", value="approved")


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
    mock_response.results = []
    mock_client.index_private_file_records.return_value = mock_response

    mock_get_client.return_value = mock_client

    file1 = MagicMock(spec=LocalFile)
    file1.validation_hash = "b" * 64
    file1.model = MagicMock(spec=FileRecordStrict)
    collection = LocalFileCollection(source=[file1])
    collection._client = mock_client

    summary = collection.push(public=False)

    mock_client.index_private_file_records.assert_called_once_with(file_records=[file1.model])
    assert summary["success"] == 1


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

    with patch.object(collection, "push", return_value={"success": 1}) as mock_push:
        collection.create_remote_collection(name="New Test Collection")

        mock_push.assert_called_once_with(public=False, api_key=None)
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


@patch("dorsal.file.collection.local.is_permitted_public_media_type")
def test_push_public_raises_error_for_restricted_types(mock_is_permitted):
    """
    Test that pushing with public=True raises a ValueError if the collection
    contains files with restricted media types.
    """

    mock_is_permitted.return_value = False

    file1 = MagicMock(spec=LocalFile, media_type="application/secret", hash="h1")
    file1.name = "secret_plans.doc"

    collection = LocalFileCollection(source=[file1])

    with pytest.raises(ValueError) as exc_info:
        collection.push(public=True)

    error_msg = str(exc_info.value)
    assert "restricted media types" in error_msg
    assert "'secret_plans.doc' (application/secret)" in error_msg


def test_collection_iteration_and_access_types():
    file1 = MagicMock(spec=LocalFile)
    file1.name = "file1"
    file1._file_path = "/local/path/file1"

    collection = LocalFileCollection(files=[file1])

    items = list(collection)
    assert len(items) == 1
    assert items[0] is file1
    assert items[0]._file_path == "/local/path/file1"

    item = collection[0]
    assert item is file1
    assert item._file_path == "/local/path/file1"


def test_get_source_paths_merged():
    """Covers the recursive _get_source_paths extraction for merged collections."""
    source_info = {
        "type": "merged",
        "sources": [
            {"type": "local", "path": "/dir/a"},
            {"type": "local", "path": "/dir/b"},
            {"type": "local", "path": "/dir/a"},
        ],
    }
    paths = _get_source_paths(source_info)
    assert paths == ["/dir/a", "/dir/b"]


def test_local_collection_addition():
    """Covers the __add__ method between two LocalFileCollections."""
    f1 = MagicMock(spec=LocalFile, hash="h1")
    f2 = MagicMock(spec=LocalFile, hash="h2")
    col1 = LocalFileCollection(source=[f1])
    col2 = LocalFileCollection(source=[f2])

    combined = col1 + col2
    assert len(combined) == 2
    assert combined.source_info["type"] == "merged"
    assert combined.source_info["operation"] == "addition"

    with pytest.raises(TypeError):
        col1 + "Not a collection"


def test_local_collection_subtraction():
    f1 = MagicMock(spec=LocalFile, hash="h1")
    f2 = MagicMock(spec=LocalFile, hash="h2")
    col1 = LocalFileCollection(source=[f1, f2])
    col2 = LocalFileCollection(source=[f2])

    subtracted = col1 - col2
    assert len(subtracted) == 1
    assert subtracted[0].hash == "h1"
    assert subtracted.source_info["operation"] == "subtraction"

    with pytest.raises(TypeError):
        _ = col1 - "Not a collection"


def test_add_tags_empty_exits():
    """Covers early exits when adding tags to an empty collection or passing no tags."""
    col = LocalFileCollection(source=[])
    assert col.add_tags([{"name": "tag", "value": "val"}]) is col

    col2 = LocalFileCollection(source=[MagicMock(spec=LocalFile)])
    assert col2.add_tags([]) is col2


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_add_tags_parse_failure(mock_get_client):
    """Covers the error handling when tag parsing fails."""
    col = LocalFileCollection(source=[MagicMock(spec=LocalFile)])
    col.offline = False

    with pytest.raises(DorsalClientError, match="Failed to parse input tags"):
        col.add_tags(["not-a-dict"])


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_add_tags_validation_failure(mock_get_client):
    """Covers the branch where the server rejects the tags."""
    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=False, message="Bad Tag")
    mock_get_client.return_value = mock_client

    col = LocalFileCollection(source=[MagicMock(spec=LocalFile)])
    col.offline = False

    with pytest.raises(InvalidTagError, match="Bad Tag"):
        col.add_tags([{"name": "bad", "value": "tag"}])


def test_add_tags_offline_mode():
    """Covers the offline branch of add_tags, skipping server validation."""
    mock_file = MagicMock(spec=LocalFile)
    col = LocalFileCollection(source=[mock_file], offline=True)

    col.add_tags([{"name": "status", "value": "offline_test"}])
    mock_file._add_local_tag.assert_called_once_with(name="status", value="offline_test")


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
@patch("dorsal.file.collection.local.is_jupyter_environment", return_value=True)
def test_add_tags_jupyter_tqdm(mock_jupyter, mock_get_client):
    """Covers the tqdm iteration branch in add_tags."""
    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)
    mock_get_client.return_value = mock_client

    mock_file = MagicMock(spec=LocalFile)
    col = LocalFileCollection(source=[mock_file])

    col.add_tags([{"name": "test", "value": "val"}])
    mock_file._add_local_tag.assert_called_once()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_add_tags_rich_console(mock_get_client):
    """Covers the Rich Console iteration branch in add_tags."""
    from rich.console import Console

    mock_client = MagicMock()
    mock_client.validate_tag.return_value = ValidateTagsResult(valid=True)
    mock_get_client.return_value = mock_client

    mock_file = MagicMock(spec=LocalFile)
    col = LocalFileCollection(source=[mock_file])

    col.add_tags([{"name": "test", "value": "val"}], console=Console())
    mock_file._add_local_tag.assert_called_once()


def test_push_empty_collection():
    """Covers the early exit when there are no valid strict records to push."""
    col = LocalFileCollection(source=[])
    res = col.push()
    assert res["total_records"] == 0


def test_sync_with_remote_no_remote_id():
    """Covers the error when trying to sync an unlinked collection."""
    col = LocalFileCollection(source=[])
    with pytest.raises(DorsalError, match="requires a linked remote collection"):
        col.sync_with_remote()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_sync_with_remote_conflict(mock_get_client):
    """Covers the SyncConflictError when remote state has changed."""
    mock_client = MagicMock()

    remote_state = MagicMock()
    remote_state.collection.date_modified = "2026-01-01"
    remote_state.collection.file_count = 10
    mock_client.get_collection.return_value = remote_state
    mock_get_client.return_value = mock_client

    col = LocalFileCollection(source=[])
    col.remote_collection_id = "col_123"
    col.remote_last_modified = "2025-01-01"
    col.remote_file_count = 10

    with pytest.raises(SyncConflictError):
        col.sync_with_remote()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_sync_with_remote_public_failure(mock_get_client, mocker):
    """Covers the error when a public sync cannot push all files."""
    mock_client = MagicMock()
    remote_state = MagicMock()
    remote_state.collection.date_modified = "2026-01-01"
    remote_state.collection.file_count = 10
    remote_state.collection.is_private = False
    mock_client.get_collection.return_value = remote_state
    mock_get_client.return_value = mock_client

    col = LocalFileCollection(source=[])
    col.remote_collection_id = "col_123"
    col.remote_last_modified = "2026-01-01"
    col.remote_file_count = 10

    mocker.patch.object(col, "push", return_value={"total_records_to_push": 1, "success": 0})

    with pytest.raises(DorsalClientError, match="Cannot sync with a public collection"):
        col.sync_with_remote()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_sync_with_remote_success(mock_get_client, mocker):
    """Covers the full successful execution of sync_with_remote."""
    mock_client = MagicMock()
    remote_state = MagicMock()
    remote_state.collection.date_modified = "2026-01-01"
    remote_state.collection.file_count = 10
    remote_state.collection.is_private = True
    mock_client.get_collection.return_value = remote_state

    mock_sync_response = MagicMock()
    mock_sync_response.added_count = 1
    mock_sync_response.removed_count = 0
    mock_sync_response.unchanged_count = 0
    mock_sync_response.model_dump.return_value = {"synced": True}
    mock_client.sync_collection_by_hash.return_value = mock_sync_response
    mock_get_client.return_value = mock_client

    mock_file = MagicMock(spec=LocalFile, hash="h1")
    col = LocalFileCollection(source=[mock_file])
    col.remote_collection_id = "col_123"
    col.remote_last_modified = "2026-01-01"
    col.remote_file_count = 10

    mocker.patch.object(col, "push", return_value={"total_records_to_push": 1, "success": 1})

    res = col.sync_with_remote()
    assert res == {"synced": True}
    mock_client.sync_collection_by_hash.assert_called_once()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_create_remote_collection_push_fails(mock_get_client, mocker):
    """Covers the error when creating a remote collection but 0 files are successfully pushed."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    col = LocalFileCollection(source=[])
    mocker.patch.object(col, "push", return_value={"success": 0})

    with pytest.raises(DorsalClientError, match="No files were successfully indexed"):
        col.create_remote_collection(name="Test")


def test_push_strict_mode_missing_model():
    """Covers the early exit when a file lacks a strict model."""
    mock_file = MagicMock(spec=LocalFile)
    mock_file.model = None
    col = LocalFileCollection(source=[mock_file])

    result = col.push(strict=True)
    assert result["total_records"] == 0


def test_push_strict_mode_upload_failures(mocker):
    from dorsal.common.exceptions import PartialIndexingError
    from dorsal.file.validators.file_record import FileRecordStrict

    mock_file = MagicMock(spec=LocalFile)
    mock_file.model = MagicMock()
    mock_file.model.__class__ = FileRecordStrict

    col = LocalFileCollection(source=[mock_file])
    col._client = MagicMock()

    mocker.patch(
        "dorsal.file.metadata_reader.MetadataReader.upload_records",
        return_value={"failed": 1, "errors": ["Server rejected record"]},
    )

    with pytest.raises(PartialIndexingError, match="1 errors detected"):
        col.push(strict=True)


def test_push_exception_handling(mocker):
    from dorsal.file.validators.file_record import FileRecordStrict

    mock_file = MagicMock(spec=LocalFile)
    mock_file.model = MagicMock()
    mock_file.model.__class__ = FileRecordStrict

    col = LocalFileCollection(source=[mock_file])
    col._client = MagicMock()

    mocker.patch(
        "dorsal.file.metadata_reader.MetadataReader.upload_records",
        side_effect=RuntimeError("Network connection severed"),
    )

    with pytest.raises(RuntimeError, match="Network connection severed"):
        col.push()


@patch("dorsal.file.collection.local.get_shared_dorsal_client")
def test_create_remote_collection_success(mock_get_client, mocker):
    mock_client = MagicMock()
    mock_client.create_collection.return_value = MagicMock(collection_id="col_123")
    mock_client.get_collection.return_value.collection.date_modified = "now"
    mock_client.get_collection.return_value.collection.file_count = 2

    mock_add_response = MagicMock()
    mock_add_response.added_count = 2
    mock_add_response.duplicate_count = 0
    mock_client.add_files_to_collection.return_value = mock_add_response

    mock_get_client.return_value = mock_client

    mock_f1 = MagicMock(spec=LocalFile, hash="h1")
    mock_f2 = MagicMock(spec=LocalFile, hash="h2")
    col = LocalFileCollection(source=[mock_f1, mock_f2])
    col.source_info = {"type": "local", "path": "/dir"}

    mocker.patch.object(col, "push", return_value={"success": 2})

    remote_col = col.create_remote_collection(name="TestCol")

    assert remote_col.collection_id == "col_123"
    assert col.remote_collection_id == "col_123"
    mock_client.create_collection.assert_called_once_with(
        name="TestCol",
        description=None,
        is_private=True,
        source={
            "caller": "dorsal.LocalFileCollection",
            "local_directories": ["/dir"],
            "comment": "Created via the Dorsal Python library.",
        },
    )
    mock_client.add_files_to_collection.assert_called_once_with(collection_id="col_123", hashes=["h1", "h2"])


def test_local_collection_to_dict():
    """Covers the local_attributes augmentation in to_dict()."""
    mock_file = MagicMock(spec=LocalFile)
    mock_file.date_modified = 123.0
    mock_file.date_created = 100.0
    mock_file._file_path = "/path/to/file"
    col = LocalFileCollection(source=[mock_file])

    with patch("dorsal.file.collection.base._BaseFileCollection.to_dict") as mock_super:
        mock_super.return_value = {"results": [{}]}

        data = col.to_dict()

        assert "local_attributes" in data["results"][0]
        assert data["results"][0]["local_attributes"]["file_path"] == "/path/to/file"
        assert data["results"][0]["local_attributes"]["date_modified"] == 123.0
