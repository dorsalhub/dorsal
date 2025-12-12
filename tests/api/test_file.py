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

import datetime
import time
import hashlib
import pathlib
from unittest.mock import patch, MagicMock, call
import os

import pytest
import tomlkit
import tomllib

from dorsal.api import file as file_api
from dorsal.common.exceptions import (
    DorsalClientError,
    DorsalConfigError,
    NotFoundError,
    ConflictError,
)
from dorsal.common.model import AnnotationModel
from dorsal.common.validators import Pagination
from dorsal.client.validators import (
    FileDeleteResponse,
    FileIndexResponse,
    FileTagResponse,
)
from dorsal.file.validators.file_record import FileSearchResponse, NewFileTag


class MockFileRecord:
    def __init__(self, hash_value, name):
        self.hash = hash_value
        self.name = name

    def model_dump(self, **kwargs):
        return {"hash": self.hash, "name": self.name}

    def model_dump_json(self, **kwargs):
        import json

        return json.dumps(self.model_dump())


@pytest.fixture
def mock_shared_client():
    """Mocks the get_shared_dorsal_client function."""
    with patch("dorsal.session.get_shared_dorsal_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_cache():
    """Mocks the get_shared_cache function."""
    with patch("dorsal.session.get_shared_cache") as mock_get:
        mock_cache_instance = MagicMock()
        # Simulate cache miss by default
        mock_cache_instance.get_hash.return_value = None
        mock_get.return_value = mock_cache_instance
        yield mock_cache_instance


@pytest.fixture
def mock_pagination_json() -> dict:
    """Provides a valid dictionary for a Pagination API response."""
    return {
        "current_page": 1,
        "record_count": 1,
        "page_count": 1,
        "per_page": 50,
        "has_next": False,
        "has_prev": False,
        "start_index": 0,
        "end_index": 0,
        "total_items": 1,
        "total_pages": 1,
    }


@pytest.fixture
def mock_jinja_env():
    """Mocks the Jinja2 environment to avoid needing real templates."""
    with patch("jinja2.Environment") as mock_env:
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>Rendered Report</html>"
        mock_env.return_value.get_template.return_value = mock_template
        yield mock_env


class MockLocalFile:
    """A simple mock to stand in for the real LocalFile object."""

    def __init__(self, path, hash_value):
        self.path = path
        self.hash = hash_value


class MyTestModel(AnnotationModel):
    my_field: str

    @classmethod
    def process(cls, file, **kwargs) -> "MyTestModel":
        return MyTestModel(my_field="test")


@pytest.fixture
def mock_metadata_reader():
    """Mocks the get_metadata_reader function for dependency injection."""
    with patch("dorsal.api.file.get_metadata_reader") as mock_get:
        mock_reader_instance = MagicMock()
        mock_get.return_value = mock_reader_instance
        yield mock_reader_instance


_DUMMY_CLIENT = MagicMock()
_DUMMY_SHA256 = "a" * 64

# --- Tests for identify_file ---


def test_identify_file_success_sha256(mock_shared_client, tmp_path):
    """Test identifying a file successfully using its SHA-256 hash."""
    # Setup a fake file
    file = tmp_path / "test.txt"
    file.write_text("content")

    # Configure the mock client
    expected_record = MockFileRecord(
        hash_value="ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73",
        name="test.txt",
    )
    mock_shared_client.download_file_record.return_value = expected_record

    # Call the function under test
    result = file_api.identify_file(str(file), quick=False)

    # Assertions
    mock_shared_client.download_file_record.assert_called_once()
    assert "SHA-256:" in mock_shared_client.download_file_record.call_args[1]["hash_string"]
    assert result.hash == expected_record.hash


def test_identify_file_quick_hash_fallback(mock_shared_client, tmp_path):
    """Test that identify_file falls back to SHA-256 if a quick hash is not found."""
    # Setup a fake large file
    file = tmp_path / "large_file.bin"
    file.write_bytes(b"\0" * (32 * 1024 * 1024))  # 32MB file

    # Configure the mock to fail on quick hash and succeed on SHA-256
    sha256_record = MockFileRecord(hash_value="...", name="large_file.bin")
    mock_shared_client.download_file_record.side_effect = [
        NotFoundError("Quick hash not found", request_url="http://dorsalhub.test/missing-thing"),
        sha256_record,
    ]

    result = file_api.identify_file(str(file), quick=True)

    assert mock_shared_client.download_file_record.call_count == 2
    assert "QUICK:" in mock_shared_client.download_file_record.call_args_list[0][1]["hash_string"]
    assert "SHA-256:" in mock_shared_client.download_file_record.call_args_list[1][1]["hash_string"]
    assert result == sha256_record


def test_identify_file_not_found_raises_dorsal_error(mock_shared_client, tmp_path):
    """Test that a NotFoundError from the client is wrapped with a helpful message."""
    file = tmp_path / "test.txt"
    file.write_text("content")

    mock_shared_client.download_file_record.side_effect = NotFoundError(
        "Original not found", request_url="http://dorsalhub.test/missing-thing"
    )

    with pytest.raises(DorsalClientError):
        file_api.identify_file(str(file), quick=False)


@patch("dorsal.client.dorsal_client.read_api_key", return_value="dummy-key-for-test")
def test_identify_file_os_error_raises_file_not_found(mock_read_api_key):
    """Test that a non-existent file path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        file_api.identify_file("path/to/non_existent_file.txt")


# --- Tests for get_dorsal_file_record ---


def test_get_dorsal_file_record_success(mock_shared_client):
    """Test a successful agnostic search for a file record."""
    hash_str = "some_hash"
    expected_record = MockFileRecord(hash_value=hash_str, name="found_file.zip")
    mock_shared_client.download_file_record.return_value = expected_record

    result = file_api.get_dorsal_file_record(hash_str, mode="pydantic")

    # Assert that the client was called with the correct agnostic parameters
    mock_shared_client.download_file_record.assert_called_once_with(hash_string=hash_str, private=None)
    assert result == expected_record


@pytest.mark.parametrize("mode, expected_type", [("dict", dict), ("json", str)])
def test_get_dorsal_file_record_modes(mock_shared_client, mode, expected_type):
    """Test the 'mode' parameter returns the correct data type."""
    hash_str = "some_hash"
    mock_record = MockFileRecord(hash_value=hash_str, name="file.txt")
    mock_shared_client.download_file_record.return_value = mock_record

    result = file_api.get_dorsal_file_record(hash_str, mode=mode)

    assert isinstance(result, expected_type)


@patch("dorsal.client.DorsalClient")
def test_get_dorsal_file_record_with_api_key(mock_client_class, mock_shared_client):
    """Test that providing an api_key creates a temporary client."""
    # This test ensures the shared client is NOT used if an API key is passed.
    mock_temp_client = MagicMock()
    mock_client_class.return_value = mock_temp_client

    file_api.get_dorsal_file_record("some_hash", api_key="temp_key_123")

    mock_shared_client.download_file_record.assert_not_called()
    mock_client_class.assert_called_once_with(api_key="temp_key_123")
    mock_temp_client.download_file_record.assert_called_once()


def test_delete_dorsal_file_record_success(mock_shared_client):
    """Test successful agnostic deletion of a file record."""
    file_hash = "a" * 64
    mock_delete_response = FileDeleteResponse(file_deleted=1)
    mock_shared_client.delete_file.return_value = mock_delete_response

    result = file_api._delete_dorsal_file_record(file_hash)

    # Assert it calls the new granular client method with default 'all' parameters
    mock_shared_client.delete_file.assert_called_once_with(
        file_hash=file_hash, record="all", tags="all", annotations="all"
    )
    assert result.file_deleted == 1


def test_delete_dorsal_file_record_invalid_hash():
    """Test that _delete_dorsal_file_record raises ValueError for an invalid hash."""
    # Match the updated error message which now uses "file_hash"
    with pytest.raises(ValueError, match="file_hash must be a valid SHA-256 hash"):
        file_api._delete_dorsal_file_record("not-a-hash")


@patch("dorsal.api.file.get_metadata_reader")
def test_index_file_success(mock_get_reader, tmp_path):
    """Test successful indexing of a single file."""
    # Setup a fake file
    file = tmp_path / "index_me.txt"
    file.write_text("content")

    # Configure the mocked MetadataReader
    mock_reader_instance = MagicMock()
    mock_get_reader.return_value = mock_reader_instance
    mock_index_response = FileIndexResponse(total=1, success=1, error=0, unauthorized=0, results=[])
    mock_reader_instance.index_file.return_value = mock_index_response

    result = file_api.index_file(str(file), private=True, use_cache=False)

    # Assert that the underlying reader method was called correctly
    mock_reader_instance.index_file.assert_called_once_with(file_path=str(file), private=True, skip_cache=True)
    assert result.success == 1


def test_add_tag_to_file_success(mock_shared_client):
    """Test successfully adding a tag via the high-level function."""
    file_hash = "a" * 64
    tag_name = "status"
    tag_value = "reviewed"
    mock_response = FileTagResponse(success=True, hash=file_hash)
    mock_shared_client.add_tags_to_file.return_value = mock_response

    result = file_api.add_tag_to_file(file_hash, tag_name, tag_value, private=True)

    # Assert that the client method was called with a correctly constructed NewFileTag object
    mock_shared_client.add_tags_to_file.assert_called_once()
    call_args = mock_shared_client.add_tags_to_file.call_args[1]
    assert call_args["file_hash"] == file_hash
    assert isinstance(call_args["tags"][0], NewFileTag)
    assert call_args["tags"][0].name == tag_name
    assert call_args["tags"][0].value == tag_value
    assert call_args["tags"][0].private is True
    assert result.success is True


@patch("dorsal.api.file.add_tag_to_file")
def test_add_label_to_file_delegation(mock_add_tag):
    """Test that add_label_to_file correctly wraps add_tag_to_file."""
    file_hash = "a" * 64
    label = "urgent"
    api_key = "secret_key"

    mock_response = MagicMock()
    mock_add_tag.return_value = mock_response

    result = file_api.add_label_to_file(hash_string=file_hash, label=label, api_key=api_key)

    mock_add_tag.assert_called_once_with(
        hash_string=file_hash, name="label", value=label, private=True, api_key=api_key
    )
    assert result == mock_response


def test_remove_tag_from_file_success(mock_shared_client):
    """Test successfully removing a tag via the high-level function."""
    file_hash = _DUMMY_SHA256
    tag_id = "t_12345"

    # The client method returns None on success
    mock_shared_client.delete_tag.return_value = None

    result = file_api.remove_tag_from_file(file_hash, tag_id)

    mock_shared_client.delete_tag.assert_called_once_with(file_hash=file_hash, tag_id=tag_id)
    assert result is None


@patch("dorsal.api.file.get_metadata_reader")
def test_search_user_files_success(mock_get_reader, mock_pagination_json):
    """Test a successful search scoped to the user."""
    mock_client = MagicMock()
    mock_get_reader.return_value._client = mock_client

    # Create a mock response object that the client would return
    mock_pagination = mock_pagination_json
    mock_response = FileSearchResponse(api_version="1.0", pagination=mock_pagination, results=[], errors=[])
    mock_client.search_files.return_value = mock_response

    query = "extension:pdf"
    result = file_api.search_user_files(query)

    # Assert that the client's search method was called with scope='user'
    mock_client.search_files.assert_called_once()
    call_args = mock_client.search_files.call_args[1]
    assert call_args["q"] == query
    assert call_args["scope"] == "user"
    assert result == mock_response


@patch("dorsal.api.file.get_metadata_reader")
def test_search_global_files_success(mock_get_reader, mock_pagination_json):
    """Test a successful search scoped globally."""
    mock_client = MagicMock()
    mock_get_reader.return_value._client = mock_client

    mock_pagination = mock_pagination_json
    mock_response = FileSearchResponse(api_version="1.0", pagination=mock_pagination, results=[], errors=[])
    mock_client.search_files.return_value = mock_response

    query = "tag:research"
    result = file_api.search_global_files(query)

    # Assert that the client's search method was called with scope='global'
    mock_client.search_files.assert_called_once()
    call_args = mock_client.search_files.call_args[1]
    assert call_args["q"] == query
    assert call_args["scope"] == "global"
    assert result == mock_response


def test_scan_file_success(mock_metadata_reader):
    """Test that scan_file correctly calls the underlying reader method."""
    file_path = "/tmp/test.txt"
    mock_local_file = MockLocalFile(path=file_path, hash_value="a" * 64)
    mock_metadata_reader.scan_file.return_value = mock_local_file

    result = file_api.scan_file(file_path, use_cache=False)

    # Assert that the reader was called with the right parameters
    mock_metadata_reader.scan_file.assert_called_once_with(file_path=file_path, skip_cache=True)
    assert result == mock_local_file


def test_scan_directory_success(mock_metadata_reader):
    """Test that scan_directory correctly calls the underlying reader method."""
    dir_path = "/tmp/docs"
    mock_files = [MockLocalFile(path="/tmp/docs/a.txt", hash_value="a" * 64)]
    mock_metadata_reader.scan_directory.return_value = mock_files

    result = file_api.scan_directory(dir_path, recursive=True, use_cache=True)

    # Assert the reader was called with the correct parameters
    mock_metadata_reader.scan_directory.assert_called_once_with(dir_path=dir_path, recursive=True, skip_cache=False)
    assert result == mock_files


@patch("dorsal.api.file.get_metadata_reader")
def test_index_directory_success(mock_get_reader):
    """Test the orchestration logic of the index_directory function."""
    dir_path = "/tmp/assets"

    # Mock the MetadataReader and its internal client
    mock_reader = MagicMock()
    mock_client = MagicMock()
    mock_get_reader.return_value = mock_reader
    mock_reader._client = mock_client

    # 1. Mock the result of scanning the directory
    mock_records = [{"hash": "a" * 64, "source": "disk"}]
    mock_hash_map = {"a" * 64: "/tmp/assets/image.jpg"}
    mock_reader.generate_processed_records_from_directory.return_value = (
        mock_records,
        mock_hash_map,
    )

    # 2. Mock the result of the client indexing the records
    mock_index_response = FileIndexResponse(total=1, success=1, error=0, unauthorized=0, results=[])
    mock_client.index_private_file_records.return_value = mock_index_response

    # Call the function under test
    summary = file_api.index_directory(dir_path, private=True)

    # Assertions
    mock_reader.generate_processed_records_from_directory.assert_called_once()
    mock_client.index_private_file_records.assert_called_once_with(file_records=mock_records)

    assert summary["total_records_processed_locally"] == 1
    assert summary["total_records_accepted_by_api"] == 1
    assert summary["successful_api_batches"] == 1


def test_find_duplicates_success(fs):
    """Test finding duplicate files in a directory.
    'fs' is a fixture provided by the pyfakefs library.
    """
    # Create a fake directory structure with duplicate files
    fs.create_file("/test/unique1.txt", contents="abc")
    fs.create_file("/test/duplicate1.txt", contents="12345")
    fs.create_dir("/test/subdir")
    fs.create_file("/test/subdir/duplicate2.txt", contents="12345")
    fs.create_file("/test/subdir/unique2.txt", contents="xyz")

    correct_hash = hashlib.sha256(b"12345").hexdigest()

    with patch("dorsal.api.file.get_shared_cache") as mock_get_cache:
        mock_get_cache.return_value.get_hash.return_value = None
        result = file_api.find_duplicates("/test", recursive=True, mode="sha256")

    assert result["total_sets"] == 1
    duplicate_set = result["duplicate_sets"][0]
    assert duplicate_set["count"] == 2
    assert duplicate_set["hash"] == correct_hash

    # Normalize expected paths to be OS-agnostic
    expected_paths = {
        os.path.normpath("/test/duplicate1.txt"),
        os.path.normpath("/test/subdir/duplicate2.txt"),
    }
    assert set(duplicate_set["paths"]) == expected_paths


def test_find_duplicates_no_results(fs):
    """Test that find_duplicates returns an empty dict when no duplicates are found."""
    fs.create_file("/test/unique1.txt", contents="abc")
    fs.create_file("/test/unique2.txt", contents="12345")

    result = file_api.find_duplicates("/test", mode="sha256")
    assert not result


def test_get_directory_info_success(fs):
    """Test getting a statistical summary of a directory."""
    fs.create_file("/test/file1.txt", contents="a" * 100)  # 100 bytes
    fs.create_file("/test/file2.bin", contents="b" * 200)  # 200 bytes
    fs.create_dir("/test/subdir")
    fs.create_file("/test/subdir/file3.txt", contents="c" * 50)  # 50 bytes

    result = file_api.get_directory_info("/test", recursive=True)

    overall = result["overall"]
    assert overall["total_files"] == 3
    assert overall["total_dirs"] == 1
    assert overall["total_size"] == 350

    # Normalize paths for assertion
    assert overall["largest_file"]["path"] == os.path.normpath("/test/file2.bin")
    assert overall["smallest_file"]["path"] == os.path.normpath("/test/subdir/file3.txt")
    assert len(result["by_type"]) > 0


@patch("dorsal.api.file.resolve_template_path")
def test_generate_html_file_report_success(mock_resolve, mock_jinja_env, mock_metadata_reader, tmp_path):
    """Test generating a file report with mocked Jinja2."""
    # Setup
    file_path = tmp_path / "report_target.txt"
    output_path = tmp_path / "report.html"
    file_path.write_text("data")

    # Mock the Resolve Path to return dummy values
    mock_resolve.return_value = (pathlib.Path("default.html"), "/templates/base")

    # Mock the scan_file result
    mock_local_file = MagicMock()
    mock_local_file._file_path = str(file_path)
    mock_local_file.date_created = datetime.datetime.now()
    mock_local_file.date_modified = datetime.datetime.now()

    mock_local_file.to_dict.return_value = {
        "annotations": {"file/base": {"record": {"name": "report_target.txt", "size": 4}}}
    }

    html_out = file_api.generate_html_file_report(
        str(file_path), local_file=mock_local_file, output_path=str(output_path)
    )

    assert html_out is None
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == "<html>Rendered Report</html>"


@patch("dorsal.api.file.resolve_template_path")
@patch("dorsal.common.config.get_collection_report_panel_config")
def test_generate_html_directory_report_success(mock_panel_config, mock_resolve, mock_jinja_env, tmp_path):
    """Test generating a directory dashboard."""
    dir_path = tmp_path / "assets"
    dir_path.mkdir()
    output_path = tmp_path / "dashboard.html"

    # Mock Panel Config
    mock_panel_config.return_value = {"overview": True, "duplicates": False}

    # Mock Template Resolution
    mock_resolve.return_value = (pathlib.Path("dashboard.html"), "/templates/base")

    # Mock Collection
    mock_collection = MagicMock()
    mock_collection.to_dict.return_value = {"files": []}

    # Mock the Report Data Generators
    with patch.dict("dorsal.file.utils.reports.REPORT_DATA_GENERATORS", {"overview": lambda c: "overview_data"}):
        html_out = file_api.generate_html_directory_report(
            str(dir_path), local_collection=mock_collection, output_path=str(output_path)
        )

    assert html_out is None
    assert output_path.exists()

    # Verify context
    call_args = mock_jinja_env.return_value.get_template.return_value.render.call_args
    context = call_args[0][0]
    assert context["report_title"] == "Directory Report: assets"
    assert context["panels"][0]["id"] == "overview"


def test_get_directory_info_detailed_metrics(fs):
    """
    Tests the detailed metric collection: permissions, dates, and media types.
    Using pyfakefs to simulate file stats accurately.
    """
    fs.create_file("/data/ro.txt", contents="read only", st_mode=0o444)
    fs.create_file("/data/exe.sh", contents="exec", st_mode=0o755)
    fs.create_file("/data/old.txt", contents="old")
    fs.create_file("/data/new.txt", contents="new")

    now = time.time()

    os.utime("/data/ro.txt", (now - 500, now - 500))
    os.utime("/data/exe.sh", (now - 500, now - 500))
    os.utime("/data/old.txt", (now - 1000, now - 1000))
    os.utime("/data/new.txt", (now, now))

    # Run the analysis
    with patch("dorsal.api.file.get_media_type", side_effect=lambda p, e: "text/plain"):
        result = file_api.get_directory_info("/data", recursive=False, media_type=True)

    overall = result["overall"]

    # Permission checks
    assert overall["permissions"]["executable"] >= 1
    assert overall["permissions"]["read_only"] >= 1

    # Date checks
    # Use normpath to handle Windows backslashes vs Linux forward slashes
    assert overall["newest_mod_file"]["path"] == os.path.normpath("/data/new.txt")
    assert overall["oldest_mod_file"]["path"] == os.path.normpath("/data/old.txt")


def test_get_directory_info_progress_integration(fs):
    """Tests that get_directory_info interacts correctly with a Console progress bar."""
    fs.create_file("/data/f1.txt")
    fs.create_file("/data/f2.txt")

    mock_console = MagicMock()

    # We need to patch the _create_rich_progress helper
    with patch("dorsal.api.file._create_rich_progress") as mock_create_progress:
        mock_progress_instance = MagicMock()
        mock_create_progress.return_value = mock_progress_instance

        file_api.get_directory_info("/data", progress_console=mock_console)

        # Verify progress bar was created and advanced
        mock_create_progress.assert_called_once()
        mock_progress_instance.add_task.assert_called()
        # Should update for the 2 files
        assert mock_progress_instance.update.call_count >= 2


def test_find_duplicates_quick_internal_logic(fs):
    """
    Target lines 1786-1856 (_find_duplicates_quick).
    We setup 3 files to hit 3 specific code paths in the loop:
    1. 'cached.txt' -> Hits the Cache (skips calculation).
    2. 'quick.txt'  -> Misses Cache, Hits Quick Hash.
    3. 'fallback.txt' -> Misses Cache, Misses Quick Hash, Falls back to SHA256.
    """
    fs.create_file("/cached.txt", contents="A")
    fs.create_file("/quick.txt", contents="B")
    fs.create_file("/fallback.txt", contents="C")

    mock_cache = MagicMock()

    # define logic for cache.get_hash
    def mock_get_hash(path, hash_function):
        if "cached.txt" in path and hash_function == "QUICK":
            return "cached_hash_val"
        return None

    mock_cache.get_hash.side_effect = mock_get_hash

    with (
        patch("dorsal.api.file.get_shared_cache", return_value=mock_cache),
        patch("dorsal.api.file.get_quick_hash") as mock_quick,
        patch("dorsal.api.file.get_sha256_hash") as mock_sha,
    ):
        # Logic:
        # - /cached.txt: handled by cache side_effect above.
        # - /quick.txt: get_quick_hash returns value.
        # - /fallback.txt: get_quick_hash returns None -> calls get_sha256_hash.

        # NOTE: We use a more robust side_effect that handles PosixPath inputs
        def quick_side_effect(path, **kwargs):
            if "quick.txt" in str(path):
                return "quick_hash_val"
            return None

        mock_quick.side_effect = quick_side_effect
        mock_sha.return_value = "sha_fallback_val"

        # Call the public wrapper with mode='quick' to trigger the internal function
        result = file_api.find_duplicates("/", mode="quick", use_cache=True)

    # Verify the calls happened, proving we hit the lines:

    # 1. Cache was queried (Line ~1813)
    assert mock_cache.get_hash.called

    # 2. Quick hash calculated for quick.txt and fallback.txt (Line ~1823)
    # (cached.txt skipped this)
    assert mock_quick.call_count == 2

    # 3. SHA fallback called ONLY for fallback.txt (Line ~1841)
    assert mock_sha.call_count == 1

    # 4. Check we got the cache hit recorded
    assert result["hashes_from_cache"] == 1


@patch("dorsal.api.file.resolve_template_path")
@patch("dorsal.common.config.get_collection_report_panel_config")
def test_generate_html_directory_report_panels(mock_panel_config, mock_resolve, mock_metadata_reader, tmp_path):
    """
    Target lines 2337-2414 (generate_html_directory_report).
    We define a config with TWO panels:
    1. 'overview' -> Exists in generators (Hits 'if generator_func')
    2. 'missing_panel' -> Does NOT exist (Hits 'else: logger.warning')
    """
    dir_path = tmp_path / "report_test"
    dir_path.mkdir()
    output_path = tmp_path / "report.html"

    # Setup Config: 1 valid panel, 1 invalid panel
    mock_panel_config.return_value = {"overview": True, "missing_panel": True}

    # Mock Template stuff to pass checks
    mock_resolve.return_value = (pathlib.Path("default.html"), "/templates/base")

    mock_collection = MagicMock()
    mock_collection.to_dict.return_value = {"files": []}

    # Only define 'overview' in the generator map
    fake_generators = {"overview": lambda c: "data"}

    with (
        patch.dict("dorsal.file.utils.reports.REPORT_DATA_GENERATORS", fake_generators),
        patch("jinja2.Environment") as mock_env,
    ):
        # Setup template mock
        mock_template = MagicMock()
        mock_template.render.return_value = "<html></html>"
        mock_env.return_value.get_template.return_value = mock_template

        file_api.generate_html_directory_report(
            str(dir_path), local_collection=mock_collection, output_path=str(output_path)
        )

        # Verify context passed to render
        call_args = mock_template.render.call_args
        context = call_args[0][0]

        # We expect only 1 panel in the final context (overview),
        # because 'missing_panel' should have triggered the warning path and been skipped.
        assert len(context["panels"]) == 1
        assert context["panels"][0]["id"] == "overview"
