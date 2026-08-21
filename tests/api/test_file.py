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

import datetime
import time
import hashlib
import pathlib
from unittest.mock import patch, MagicMock, call
import os
import uuid

import pytest
import tomlkit
import tomllib

from dorsal.api import file as file_api
from dorsal.common import constants
from dorsal.common.exceptions import (
    BatchIndexingError,
    DorsalError,
    DorsalClientError,
    DorsalConfigError,
    ExceedsApiLimitError,
    NotFoundError,
    ConflictError,
)
from dorsal.common.model import AnnotationModel, AnnotationModelSource
from dorsal.common.validators import Pagination
from dorsal.client.validators import (
    FileDeleteResponse,
    FileIndexResponse,
    FileTagResponse,
)
from dorsal.file.validators.base import FileCoreValidationModel
from dorsal.file.validators.file_record import (
    FileRecordStrict,
    FileRecordDateTime,
    FileSearchResponse,
    Annotations,
    Annotation_Base,
    AnnotationStub,
    GenericFileAnnotation,
    NewFileTag,
)


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
    """Mocks the get_shared_index function."""
    with patch("dorsal.session.get_shared_index") as mock_get:
        mock_cache_instance = MagicMock()

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


def test_identify_file_success_sha256(mock_shared_client, tmp_path):
    """Test identifying a file successfully using its SHA-256 hash."""

    file = tmp_path / "test.txt"
    file.write_text("content")

    expected_record = MockFileRecord(
        hash_value="ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73",
        name="test.txt",
    )
    mock_shared_client.download_file_record.return_value = expected_record

    result = file_api.identify_file(str(file), quick=False)

    mock_shared_client.download_file_record.assert_called_once()
    assert "SHA-256:" in mock_shared_client.download_file_record.call_args[1]["hash_string"]
    assert result.hash == expected_record.hash


def test_identify_file_quick_hash_fallback(mock_shared_client, tmp_path):
    """Test that identify_file falls back to SHA-256 if a quick hash is not found."""

    file = tmp_path / "large_file.bin"
    file.write_bytes(b"\0" * (32 * 1024 * 1024))

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


def test_get_dorsal_file_record_success(mock_shared_client):
    """Test a successful agnostic search for a file record."""
    hash_str = "some_hash"
    expected_record = MockFileRecord(hash_value=hash_str, name="found_file.zip")
    mock_shared_client.download_file_record.return_value = expected_record

    result = file_api.get_dorsal_file_record(hash_str, mode="pydantic")

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

    mock_shared_client.delete_file.assert_called_once_with(
        file_hash=file_hash, record="all", tags="all", annotations="all"
    )
    assert result.file_deleted == 1


def test_delete_dorsal_file_record_invalid_hash():
    """Test that _delete_dorsal_file_record raises ValueError for an invalid hash."""

    with pytest.raises(ValueError, match="file_hash must be a valid SHA-256 hash"):
        file_api._delete_dorsal_file_record("not-a-hash")


@patch("dorsal.file.dorsal_file.LocalFile")
def test_index_file_success(mock_local_file_cls, tmp_path):
    """Test successful indexing of a single file."""
    file = tmp_path / "things_and_stuff.txt"
    file.write_text("content")

    mock_instance = mock_local_file_cls.return_value
    mock_index_response = FileIndexResponse(total=1, success=1, error=0, unauthorized=0, results=[])
    mock_instance.push.return_value = mock_index_response

    result = file_api.index_file(str(file), public=False, use_cache=False)

    assert result == mock_index_response
    mock_local_file_cls.assert_called_with(file_path=str(file), use_cache=False)
    mock_instance.push.assert_called_with(public=False, api_key=None, strict=False)


def test_add_tag_to_file_success(mock_shared_client):
    """Test successfully adding a tag via the high-level function."""
    file_hash = "a" * 64
    tag_name = "status"
    tag_value = "reviewed"
    mock_response = FileTagResponse(success=True, hash=file_hash)
    mock_shared_client.add_tags_to_file.return_value = mock_response

    result = file_api.add_tag_to_file(file_hash, tag_name, tag_value, public=False)

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
        hash_string=file_hash, name="label", value=label, public=False, api_key=api_key
    )
    assert result == mock_response


def test_remove_tag_from_file_success(mock_shared_client):
    """Test successfully removing a tag via the high-level function."""
    file_hash = _DUMMY_SHA256
    tag_id = "t_12345"

    mock_shared_client.delete_tag.return_value = None

    result = file_api.remove_tag_from_file(file_hash, tag_id)

    mock_shared_client.delete_tag.assert_called_once_with(file_hash=file_hash, tag_id=tag_id)
    assert result is None


@patch("dorsal.api.file.get_metadata_reader")
def test_search_user_files_success(mock_get_reader, mock_pagination_json):
    """Test a successful search scoped to the user."""
    mock_client = MagicMock()
    mock_get_reader.return_value._client = mock_client

    mock_pagination = mock_pagination_json
    mock_response = FileSearchResponse(api_version="1.0", pagination=mock_pagination, results=[], errors=[])
    mock_client.search_files.return_value = mock_response

    query = "extension:pdf"
    result = file_api.search_user_files(query)

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

    mock_metadata_reader.scan_file.assert_called_once_with(file_path=file_path, skip_cache=True, follow_symlinks=True)
    assert result == mock_local_file


def test_scan_directory_success(mock_metadata_reader):
    """Test that scan_directory correctly calls the underlying reader method."""
    dir_path = "/tmp/docs"
    mock_files = [MockLocalFile(path="/tmp/docs/a.txt", hash_value="a" * 64)]
    mock_metadata_reader.scan_directory.return_value = mock_files

    result = file_api.scan_directory(dir_path, recursive=True, use_cache=True)

    mock_metadata_reader.scan_directory.assert_called_once_with(
        dir_path=dir_path, recursive=True, skip_cache=False, follow_symlinks=True
    )
    assert result == mock_files


@patch("dorsal.api.file.get_metadata_reader")
def test_index_directory_success(mock_get_reader):
    """Test the orchestration logic of the index_directory function."""
    dir_path = "/tmp/assets"

    mock_reader = MagicMock()
    mock_get_reader.return_value = mock_reader

    mock_summary = {"total_records": 1, "success": 1, "failed": 0, "batches": [], "errors": []}
    mock_reader.index_directory.return_value = mock_summary
    summary = file_api.index_directory(dir_path, public=False)

    mock_get_reader.assert_called_once()

    # FIXED: Added include_oversized=False to the assertion
    mock_reader.index_directory.assert_called_once_with(
        dir_path=dir_path, recursive=False, public=False, skip_cache=False, fail_fast=True, include_oversized=False
    )
    assert summary == mock_summary


@patch("dorsal.api.file.get_metadata_reader")
def test_index_directory_include_oversized_propagation(mock_get_reader):
    """Test that the include_oversized flag propagates correctly to the reader."""
    dir_path = "/tmp/assets"
    mock_reader = MagicMock()
    mock_get_reader.return_value = mock_reader

    file_api.index_directory(dir_path, public=False, include_oversized=True)

    # Verify the flag is passed down as True
    mock_reader.index_directory.assert_called_once_with(
        dir_path=dir_path, recursive=False, public=False, skip_cache=False, fail_fast=True, include_oversized=True
    )


def test_find_duplicates_success(fs):
    """Test finding duplicate files in a directory.
    'fs' is a fixture provided by the pyfakefs library.
    """

    fs.create_file("/test/unique1.txt", contents="abc")
    fs.create_file("/test/duplicate1.txt", contents="12345")
    fs.create_dir("/test/subdir")
    fs.create_file("/test/subdir/duplicate2.txt", contents="12345")
    fs.create_file("/test/subdir/unique2.txt", contents="xyz")

    correct_hash = hashlib.sha256(b"12345").hexdigest()

    with patch("dorsal.api.file.get_shared_index") as mock_get_cache:
        mock_get_cache.return_value.get_hash.return_value = None
        result = file_api.find_duplicates("/test", recursive=True, mode="sha256")

    assert result["total_sets"] == 1
    duplicate_set = result["duplicate_sets"][0]
    assert duplicate_set["count"] == 2
    assert duplicate_set["hash"] == correct_hash

    expected_paths = {
        os.path.normpath("/test/duplicate1.txt"),
        os.path.normpath("/test/subdir/duplicate2.txt"),
    }
    assert set(duplicate_set["paths"]) == expected_paths


def test_find_duplicates_no_results(fs):
    """Test that find_duplicates returns an empty sets list when no duplicates are found."""
    fs.create_file("/test/unique1.txt", contents="abc")
    fs.create_file("/test/unique2.txt", contents="12345")

    result = file_api.find_duplicates("/test", mode="sha256")

    assert result["total_sets"] == 0
    assert result["duplicate_sets"] == []
    assert result["path"] == os.path.normpath("/test")


def test_get_directory_info_success(fs):
    """Test getting a statistical summary of a directory."""
    fs.create_file("/test/file1.txt", contents="a" * 100)
    fs.create_file("/test/file2.bin", contents="b" * 200)
    fs.create_dir("/test/subdir")
    fs.create_file("/test/subdir/file3.txt", contents="c" * 50)

    result = file_api.get_directory_info("/test", recursive=True)

    overall = result["overall"]
    assert overall["total_files"] == 3
    assert overall["total_dirs"] == 1
    assert overall["total_size"] == 350

    assert overall["largest_file"]["path"] == os.path.normpath("/test/file2.bin")
    assert overall["smallest_file"]["path"] == os.path.normpath("/test/subdir/file3.txt")
    assert len(result["by_type"]) > 0


@patch("dorsal.api.file.resolve_template_path")
def test_generate_html_file_report_success(mock_resolve, mock_jinja_env, mock_metadata_reader, tmp_path):
    """Test generating a file report with mocked Jinja2."""

    file_path = tmp_path / "report_target.txt"
    output_path = tmp_path / "report.html"
    file_path.write_text("data")

    mock_resolve.return_value = (pathlib.Path("default.html"), "/templates/base")

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

    mock_panel_config.return_value = {"overview": True, "duplicates": False}

    mock_resolve.return_value = (pathlib.Path("dashboard.html"), "/templates/base")

    mock_collection = MagicMock()
    mock_collection.to_dict.return_value = {"files": []}

    with patch.dict("dorsal.file.utils.reports.REPORT_DATA_GENERATORS", {"overview": lambda c: "overview_data"}):
        html_out = file_api.generate_html_directory_report(
            str(dir_path), local_collection=mock_collection, output_path=str(output_path)
        )

    assert html_out is None
    assert output_path.exists()

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

    with patch("dorsal.api.file.get_media_type", side_effect=lambda p, e: "text/plain"):
        result = file_api.get_directory_info("/data", recursive=False, media_type=True)

    overall = result["overall"]

    assert overall["permissions"]["executable"] >= 1
    assert overall["permissions"]["read_only"] >= 1

    assert overall["newest_mod_file"]["path"] == os.path.normpath("/data/new.txt")
    assert overall["oldest_mod_file"]["path"] == os.path.normpath("/data/old.txt")


def test_get_directory_info_progress_integration(fs):
    """Tests that get_directory_info interacts correctly with a Console progress bar."""
    fs.create_file("/data/f1.txt")
    fs.create_file("/data/f2.txt")

    mock_console = MagicMock()

    with patch("dorsal.api.file._create_rich_progress") as mock_create_progress:
        mock_progress_instance = MagicMock()
        mock_create_progress.return_value = mock_progress_instance

        file_api.get_directory_info("/data", progress_console=mock_console)

        mock_create_progress.assert_called_once()
        mock_progress_instance.add_task.assert_called()

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

    def mock_get_hash(path, hash_function):
        if "cached.txt" in path and hash_function == "QUICK":
            return "cached_hash_val"
        return None

    mock_cache.get_hash.side_effect = mock_get_hash

    with (
        patch("dorsal.api.file.get_shared_index", return_value=mock_cache),
        patch("dorsal.api.file.get_quick_hash") as mock_quick,
        patch("dorsal.api.file.get_sha256_hash") as mock_sha,
    ):

        def quick_side_effect(path, **kwargs):
            if "quick.txt" in str(path):
                return "quick_hash_val"
            return None

        mock_quick.side_effect = quick_side_effect
        mock_sha.return_value = "sha_fallback_val"

        result = file_api.find_duplicates("/", mode="quick", use_cache=True)

    assert mock_cache.get_hash.called

    assert mock_quick.call_count == 2

    assert mock_sha.call_count == 1

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

    mock_panel_config.return_value = {"overview": True, "missing_panel": True}

    mock_resolve.return_value = (pathlib.Path("default.html"), "/templates/base")

    mock_collection = MagicMock()
    mock_collection.to_dict.return_value = {"files": []}

    fake_generators = {"overview": lambda c: "data"}

    with (
        patch.dict("dorsal.file.utils.reports.REPORT_DATA_GENERATORS", fake_generators),
        patch("jinja2.Environment") as mock_env,
    ):
        mock_template = MagicMock()
        mock_template.render.return_value = "<html></html>"
        mock_env.return_value.get_template.return_value = mock_template

        file_api.generate_html_directory_report(
            str(dir_path), local_collection=mock_collection, output_path=str(output_path)
        )

        call_args = mock_template.render.call_args
        context = call_args[0][0]

        assert len(context["panels"]) == 1
        assert context["panels"][0]["id"] == "overview"


@pytest.fixture
def dummy_file_record_dt_with_stubs() -> FileRecordDateTime:
    """Provides a valid FileRecordDateTime populated with a custom AnnotationStub."""
    base_record = FileCoreValidationModel(
        hash="a" * 64, name="test.txt", extension=".txt", size=100, media_type="text/plain"
    )
    file_base = Annotation_Base(
        record=base_record, source=AnnotationModelSource(type="Model", id="file/base", version="1.0.0")
    )
    annotations = Annotations(file_base=file_base)

    stub = AnnotationStub(
        hash="a" * 64,
        id=uuid.uuid4(),
        source=AnnotationModelSource(type="Model", id="custom_model"),
        user_id=1,
        date_modified=datetime.datetime.now(datetime.UTC),
    )

    annotations.__pydantic_extra__ = {"open/custom": [stub]}

    return FileRecordDateTime(
        hash="a" * 64,
        date_created=datetime.datetime.now(datetime.UTC),
        date_modified=datetime.datetime.now(datetime.UTC),
        annotations=annotations,
    )


def test_get_file_annotation_success(mock_shared_client):
    """Test directly fetching a specific annotation by ID."""

    dummy_response = GenericFileAnnotation(custom_field="hydrated_data")
    mock_shared_client.get_file_annotation.return_value = dummy_response

    result = file_api.get_file_annotation(hash_string="a" * 64, annotation_id="123")

    mock_shared_client.get_file_annotation.assert_called_once_with(file_hash="a" * 64, annotation_id="123")
    assert result == dummy_response


def test_get_file_annotation_not_found(mock_shared_client):
    """Test that a 404 is caught and wrapped with a clear error message."""
    mock_not_found = NotFoundError(message="404", request_url="http://test")

    mock_shared_client.get_file_annotation.side_effect = mock_not_found

    with pytest.raises(DorsalClientError, match="Annotation '123' not found for file"):
        file_api.get_file_annotation(hash_string="a" * 64, annotation_id="123")


def test_get_latest_file_annotation_success(mock_shared_client, dummy_file_record_dt_with_stubs):
    """Test retrieving and automatically hydrating the latest annotation."""

    mock_shared_client.download_file_record.return_value = dummy_file_record_dt_with_stubs

    dummy_hydrated = GenericFileAnnotation(custom_data="full_content")
    mock_shared_client.get_file_annotation.return_value = dummy_hydrated

    result = file_api.get_latest_file_annotation(hash_string="a" * 64, schema_id="open/custom")

    mock_shared_client.download_file_record.assert_called_once()
    mock_shared_client.get_file_annotation.assert_called_once()
    assert result == dummy_hydrated


def test_get_latest_file_annotation_formatting(mock_shared_client, dummy_file_record_dt_with_stubs):
    """Test that the hydrated data respects the 'mode' formatting argument."""
    mock_shared_client.download_file_record.return_value = dummy_file_record_dt_with_stubs

    dummy_hydrated = GenericFileAnnotation(custom_data="full_content")
    mock_shared_client.get_file_annotation.return_value = dummy_hydrated

    result_dict = file_api.get_latest_file_annotation(hash_string="a" * 64, schema_id="open/custom", mode="dict")
    assert isinstance(result_dict, dict)
    assert result_dict["custom_data"] == "full_content"


def test_get_latest_file_annotation_not_found(mock_shared_client, dummy_file_record_dt_with_stubs):
    """Test behavior when the requested schema doesn't exist on the file."""
    mock_shared_client.download_file_record.return_value = dummy_file_record_dt_with_stubs

    with pytest.raises(NotFoundError, match="No annotations found for schema 'open/missing'"):
        file_api.get_latest_file_annotation(hash_string="a" * 64, schema_id="open/missing")


def test_get_file_annotations_summary(mock_shared_client, dummy_file_record_dt_with_stubs):
    """Test retrieving a lightweight summary list of stubs."""
    mock_shared_client.download_file_record.return_value = dummy_file_record_dt_with_stubs

    result = file_api.get_file_annotations_summary(hash_string="a" * 64, schema_id="open/custom")

    assert isinstance(result, list)
    assert len(result) == 1

    stub_summary = result[0]
    assert "id" in stub_summary
    assert "source" in stub_summary
    assert "url" in stub_summary

    mock_shared_client.get_file_annotation.assert_not_called()


@patch("dorsal.api.file.get_sha256_hash")
def test_identify_file_quick_hash_collision(mock_sha256, mock_shared_client, tmp_path):
    """Test that a ConflictError on a quick hash falls back to SHA-256."""
    file = tmp_path / "large_file.bin"
    file.write_bytes(b"\0" * (32 * 1024 * 1024))

    expected_record = MockFileRecord(hash_value="sha256-hash-value", name="large_file.bin")

    mock_shared_client.download_file_record.side_effect = [
        ConflictError("Collision detected"),
        expected_record,
    ]
    mock_sha256.return_value = "sha256-hash-value"

    result = file_api.identify_file(str(file), quick=True)

    assert mock_shared_client.download_file_record.call_count == 2
    assert "QUICK:" in mock_shared_client.download_file_record.call_args_list[0][1]["hash_string"]
    assert "SHA-256:" in mock_shared_client.download_file_record.call_args_list[1][1]["hash_string"]
    assert result == expected_record


@patch("dorsal.api.file.get_sha256_hash")
def test_identify_file_sha256_failure(mock_sha256, mock_shared_client, tmp_path):
    """Test behavior when SHA-256 generation fails (returns None)."""
    file = tmp_path / "test.txt"
    file.write_text("content")

    mock_sha256.return_value = None

    with pytest.raises(DorsalError, match="Could not generate SHA-256 hash for file"):
        file_api.identify_file(str(file), quick=False)


def test_identify_file_unexpected_error(mock_shared_client, tmp_path):
    """Test that unexpected exceptions are wrapped in a DorsalError."""
    file = tmp_path / "test.txt"
    file.write_text("content")

    mock_shared_client.download_file_record.side_effect = Exception("Random crash")

    with pytest.raises(DorsalError, match="An unexpected error occurred while identifying file"):
        file_api.identify_file(str(file), quick=False)


@pytest.mark.parametrize("invalid_hash", ["", "   ", None])
def test_get_dorsal_file_record_empty_hash(invalid_hash, mock_shared_client):
    """Test that empty or whitespace-only hashes raise a ValueError."""
    with pytest.raises(ValueError, match="hash_string must be a non-empty string"):
        file_api.get_dorsal_file_record(invalid_hash)  # type: ignore


def test_get_dorsal_file_record_not_found(mock_shared_client):
    """Test that NotFoundError is caught and context is added to the message."""
    mock_not_found = NotFoundError(message="Original 404", request_url="http://test")

    mock_shared_client.download_file_record.side_effect = mock_not_found

    with pytest.raises(DorsalClientError, match="File not found in 'Agnostic.*' scope for hash 'missing_hash'"):
        file_api.get_dorsal_file_record("missing_hash")


def test_get_dorsal_file_record_unexpected_error(mock_shared_client):
    """Test that generic exceptions are wrapped in DorsalError."""
    mock_shared_client.download_file_record.side_effect = Exception("Network timeout")

    with pytest.raises(DorsalError, match="An unexpected error occurred while getting metadata for hash 'crash_hash'"):
        file_api.get_dorsal_file_record("crash_hash")


def test_get_dorsal_file_record_invalid_mode(mock_shared_client):
    """Test that an invalid mode literal raises a ValueError."""
    mock_shared_client.download_file_record.return_value = MockFileRecord("abc", "test.txt")

    with pytest.raises(ValueError, match="Invalid mode: 'xml'"):
        file_api.get_dorsal_file_record("abc", mode="xml")  # type: ignore


def test_get_file_annotation_generic_client_error(mock_shared_client):
    """Test that a non-404 DorsalClientError is re-raised directly."""

    mock_shared_client.get_file_annotation.side_effect = DorsalClientError("Permission Denied")

    with pytest.raises(DorsalClientError, match="Permission Denied"):
        file_api.get_file_annotation("anno_123", "hash_abc")


def test_get_file_annotation_unexpected_error(mock_shared_client):
    """Test that generic exceptions are wrapped in DorsalError."""
    mock_shared_client.get_file_annotation.side_effect = Exception("System fault")

    with pytest.raises(DorsalError, match="Unexpected error fetching annotation 'anno_123'"):
        file_api.get_file_annotation("anno_123", "hash_abc")


def test_get_file_annotation_invalid_mode(mock_shared_client):
    """Test that an invalid mode raises a ValueError."""
    mock_shared_client.get_file_annotation.return_value = GenericFileAnnotation()

    with pytest.raises(ValueError, match="Invalid mode: 'yaml'"):
        file_api.get_file_annotation("anno_123", "hash_abc", mode="yaml")  # type: ignore


@patch("dorsal.file.dorsal_file.DorsalFile")
def test_get_latest_file_annotation_generic_client_error(mock_dorsal_file_cls, mock_shared_client):
    """Test that DorsalClientError propagates up."""
    mock_instance = mock_dorsal_file_cls.return_value
    mock_instance.get_latest_annotation.side_effect = DorsalClientError("Rate Limited")

    with pytest.raises(DorsalClientError, match="Rate Limited"):
        file_api.get_latest_file_annotation("hash_abc", "open/schema")


@patch("dorsal.file.dorsal_file.DorsalFile")
def test_get_latest_file_annotation_unexpected_error(mock_dorsal_file_cls, mock_shared_client):
    """Test that unexpected exceptions are wrapped in a DorsalError."""
    mock_instance = mock_dorsal_file_cls.return_value
    mock_instance.get_latest_annotation.side_effect = TypeError("Bad serialization")

    with pytest.raises(DorsalError, match="Unexpected error fetching latest 'open/schema' annotation:"):
        file_api.get_latest_file_annotation("hash_abc", "open/schema")


@patch("dorsal.file.dorsal_file.DorsalFile")
def test_get_latest_file_annotation_invalid_mode(mock_dorsal_file_cls, mock_shared_client):
    """Test that an invalid mode raises a ValueError."""
    mock_instance = mock_dorsal_file_cls.return_value

    mock_instance.get_latest_annotation.return_value = GenericFileAnnotation()

    with pytest.raises(ValueError, match="Invalid mode: 'csv'"):
        file_api.get_latest_file_annotation("hash_abc", "open/schema", mode="csv")  # type: ignore


def test_list_file_annotations_invalid_mode():
    """Test that an invalid mode raises a ValueError."""
    with pytest.raises(ValueError, match="Invalid mode: 'xml'"):
        file_api.list_file_annotations("abc", mode="xml")  # type: ignore


@patch("dorsal.api.file.get_dorsal_file_record")
def test_list_file_annotations_pydantic(mock_get_record):
    """Test retrieving annotations as a pydantic object/dictionary directly."""
    mock_record = MagicMock()
    mock_record.annotations = {"AudioTranscription": [{"id": "123"}]}
    mock_get_record.return_value = mock_record

    result = file_api.list_file_annotations("hash_123", mode="pydantic")

    mock_get_record.assert_called_once_with(hash_string="hash_123", mode="pydantic", api_key=None)
    assert result == {"AudioTranscription": [{"id": "123"}]}


@patch("dorsal.api.file.get_dorsal_file_record")
def test_list_file_annotations_dict(mock_get_record):
    """Test retrieving annotations as a standard dictionary via model_dump."""
    mock_record = MagicMock()

    mock_record.model_dump.return_value = {"annotations": {"AudioTranscription": [{"id": "123"}]}}
    mock_get_record.return_value = mock_record

    result = file_api.list_file_annotations("hash_123", mode="dict")
    assert result == {"AudioTranscription": [{"id": "123"}]}


@patch("dorsal.api.file.get_dorsal_file_record")
def test_list_file_annotations_json(mock_get_record):
    """Test retrieving annotations as a JSON string."""
    mock_record = MagicMock()
    mock_record.model_dump.return_value = {"annotations": {"AudioTranscription": [{"id": "123"}]}}
    mock_get_record.return_value = mock_record

    result = file_api.list_file_annotations("hash_123", mode="json")
    assert isinstance(result, str)
    assert '"AudioTranscription"' in result
    assert '"123"' in result


@patch("dorsal.api.file.get_dorsal_file_record")
def test_list_file_annotations_exception(mock_get_record):
    """Test that unexpected exceptions are logged and re-raised."""
    mock_get_record.side_effect = Exception("API Offline")

    with pytest.raises(Exception, match="API Offline"):
        file_api.list_file_annotations("hash_123")
