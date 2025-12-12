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
from unittest.mock import patch, MagicMock, ANY
import os
import json
import logging
from pathlib import Path
import requests

from dorsal.common import constants as dorsal_constants
from dorsal.version import __version__ as dorsal_actual_VERSION
from dorsal.client import DorsalClient
from dorsal.client.validators import FileIndexResponse
from dorsal.client.validators import IndexResult as ActualIndexResultItem
from dorsal.common.exceptions import (
    DorsalError,
    DorsalClientError,
    DuplicateFileError,
    BatchSizeError,
    ModelRunnerConfigError,
    BaseModelProcessingError,
    PipelineIntegrityError,
    MissingHashError,
    DependencyNotMetError,
    APIError as DorsalClientAPIError,
)
from dorsal.file.cache import DorsalCache


from dorsal.file.metadata_reader import MetadataReader, make_dorsalhub_file_url


from dorsal.file.model_runner import ModelRunner
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.validators.file_record import (
    FileRecordStrict,
    Annotations as ActualAnnotations,
)


from pydantic import BaseModel, Field
from typing import Literal


class MockAnnotationModelSource(BaseModel):
    type: Literal["Model"] = "Model"
    id: str = "dummy"
    version: str = "1.0"


class MockFileCoreValidationModelHashModel(BaseModel):
    id: str
    value: str


class MockFileCoreValidationModelModel(BaseModel):
    hash: str = "sha256_dummy_hash_value_from_base_record"
    name: str = "test_file.txt"
    extension: str | None = ".txt"
    size: int = 1024
    media_type: str = "text/plain"
    all_hashes: list[MockFileCoreValidationModelHashModel] | None = [
        MockFileCoreValidationModelHashModel(id="SHA-256", value="sha256_dummy_hash_value_from_base_record"),
        MockFileCoreValidationModelHashModel(id="BLAKE3", value="blake3_dummy_hash_value_for_base_record"),
    ]


class MockAnnotationRecordBase(BaseModel):
    record: MockFileCoreValidationModelModel = Field(default_factory=MockFileCoreValidationModelModel)
    source: MockAnnotationModelSource = Field(default_factory=MockAnnotationModelSource)
    error: str | None = None


class MockAnnotationsModel(BaseModel):
    file_base: MockAnnotationRecordBase = Field(default_factory=MockAnnotationRecordBase)
    file_mediainfo: MockAnnotationRecordBase | None = None
    file_pdf: MockAnnotationRecordBase | None = None


# --- Pytest Fixtures ---


@pytest.fixture(autouse=True)
def mock_api_key_env_for_metadata_reader(mocker):
    mocker.patch.dict(os.environ, {"DORSAL_API_KEY": "mock_metadata_reader_api_key"})


@pytest.fixture
def mock_dorsal_cache(mocker):
    """Mocks the shared cache to prevent any database interactions."""
    mock_cache_instance = MagicMock(spec=DorsalCache)
    mocker.patch("dorsal.file.metadata_reader.get_shared_cache", return_value=mock_cache_instance)
    return mock_cache_instance


@pytest.fixture
def mock_dorsal_client_for_reader(mocker):
    mock = mocker.MagicMock(spec=DorsalClient)
    mock_index_response = MagicMock(spec=FileIndexResponse)
    mock_index_response.total = 0
    mock_index_response.success = 0
    mock_index_response.error = 0
    mock_index_response.unauthorized = 0
    mock_index_response.results = []
    mock_index_response.response = MagicMock(spec=requests.Response, status_code=200)
    mock_index_response.created = False

    mock.index_private_file_records.return_value = mock_index_response
    mock.index_public_file_records.return_value = mock_index_response
    return mock


@pytest.fixture
def mock_model_runner_for_reader(mocker):
    """Mocks ModelRunner used directly by MetadataReader"""
    mock = mocker.MagicMock(spec=ModelRunner)

    mock_file_record = MagicMock(spec=FileRecordStrict)
    mock_file_record.hash = "default_mock_hash_from_runner"
    mock_file_record.tags = []
    mock_file_record.validation_hash = "default_validation_hash_from_runner"
    mock.run.return_value = mock_file_record
    return mock


@pytest.fixture
def metadata_reader_base(
    mocker,
    mock_dorsal_client_for_reader,
    mock_model_runner_for_reader,
    mock_dorsal_cache,
):
    """
    Provides a base MetadataReader instance by injecting its mocked dependencies
    (DorsalClient, ModelRunner, and DorsalCache).
    """
    with patch(
        "dorsal.file.metadata_reader.ModelRunner",
        return_value=mock_model_runner_for_reader,
    ):
        reader = MetadataReader(client=mock_dorsal_client_for_reader)
        reader._test_mock_client = mock_dorsal_client_for_reader
        reader._test_mock_runner = mock_model_runner_for_reader
    return reader


@pytest.fixture
def mock_local_file_instance(mocker):
    """Creates a reusable, well-configured mock LocalFile instance."""
    instance = MagicMock(spec=LocalFile)
    instance.path = "/mock/local_file.txt"
    instance.hash = "mock_localfile_hash_from_instance_fixture"

    internal_model_mock = MagicMock(spec=FileRecordStrict)
    internal_model_mock.hash = "internal_hash_for_lf_instance"
    internal_model_mock.validation_hash = "internal_validation_hash_for_lf_instance"
    internal_model_mock.annotations = MagicMock(spec=ActualAnnotations)
    internal_model_mock.tags = []
    instance.model = internal_model_mock
    return instance


@pytest.fixture
def mock_get_file_paths(mocker):
    return mocker.patch("dorsal.file.metadata_reader.get_file_paths")


@pytest.fixture
def temp_dir_with_files(tmp_path: Path):
    (tmp_path / "root_file1.txt").write_text("root_content1")
    (tmp_path / "root_file2.txt").write_text("root_content2")

    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir1 / "file1_in_dir1.txt").write_text("content1")
    (dir1 / "file2_in_dir1.txt").write_text("content2")

    subdir1 = dir1 / "subdir_in_dir1"
    subdir1.mkdir()
    (subdir1 / "file_in_subdir1.txt").write_text("content3")
    return tmp_path


# --- Tests for make_dorsalhub_file_url ---
def test_make_dorsalhub_file_url_basic(mocker):
    mocker.patch.object(dorsal_constants, "BASE_URL", "http://example.com")
    assert make_dorsalhub_file_url("somehash123") == "http://example.com/file/somehash123"


def test_make_dorsalhub_file_url_with_slashes(mocker):
    mocker.patch.object(dorsal_constants, "BASE_URL", "http://example.com/")
    assert make_dorsalhub_file_url("/somehash123/") == "http://example.com/file/somehash123"


class TestMetadataReaderInit:
    def test_init_defaults_and_lazy_client(self, mocker, mock_dorsal_cache):
        mock_get_client = mocker.patch("dorsal.file.metadata_reader.get_shared_dorsal_client")
        mock_mr_constructor = mocker.patch("dorsal.file.metadata_reader.ModelRunner")

        reader = MetadataReader()
        assert not reader._ignore_duplicates
        mock_mr_constructor.assert_called_once_with(pipeline_config="default")
        mock_get_client.assert_not_called()
        assert reader._client_instance is None

        client = reader._client
        mock_get_client.assert_called_once_with(api_key=None)
        assert client is mock_get_client.return_value

        _ = reader._client
        mock_get_client.assert_called_once()

    def test_init_custom_params_and_injected_client(self, mocker, mock_dorsal_cache):
        mock_get_client = mocker.patch("dorsal.file.metadata_reader.get_shared_dorsal_client")

        mock_client_constructor = mocker.patch("dorsal.file.metadata_reader.DorsalClient")
        mock_new_client_instance = MagicMock(spec=DorsalClient)
        mock_client_constructor.return_value = mock_new_client_instance

        mock_mr_constructor = mocker.patch("dorsal.file.metadata_reader.ModelRunner")
        mock_preconfigured_client = MagicMock(spec=DorsalClient)

        api_key = "test_key_custom"
        model_config = {"custom": "config"}

        reader_lazy = MetadataReader(api_key=api_key, model_config=model_config)
        mock_mr_constructor.assert_called_once_with(pipeline_config=model_config)

        client_from_key = reader_lazy._client

        mock_get_client.assert_not_called()
        mock_client_constructor.assert_called_once_with(api_key=api_key)
        assert client_from_key is mock_new_client_instance

        mock_get_client.reset_mock()
        mock_client_constructor.reset_mock()

        reader_injected = MetadataReader(client=mock_preconfigured_client)

        assert reader_injected._client is mock_preconfigured_client
        mock_get_client.assert_not_called()
        mock_client_constructor.assert_not_called()


class TestMetadataReaderInternalRunModels:
    def test_run_models_success(self, metadata_reader_base, fs):
        reader = metadata_reader_base
        mock_record = MagicMock(spec=FileRecordStrict)
        reader._test_mock_runner.run.return_value = mock_record
        file_path = "/fake/file.txt"
        fs.create_file(file_path)

        result = reader._run_models(file_path=file_path)

        assert result is mock_record
        reader._test_mock_runner.run.assert_called_once_with(file_path=file_path)

    def test_run_models_file_not_found(self, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/nonexistent.txt"
        reader._test_mock_runner.run.side_effect = FileNotFoundError()

        with pytest.raises(FileNotFoundError):
            reader._run_models(file_path=file_path)
        assert "File not found by ModelRunner" in caplog.text

    def test_run_models_io_error(self, metadata_reader_base, caplog, fs):
        reader = metadata_reader_base
        file_path = "/fake/unreadable.txt"
        fs.create_file(file_path)
        reader._test_mock_runner.run.side_effect = IOError()

        with pytest.raises(IOError):
            reader._run_models(file_path=file_path)
        assert "IOError processing file" in caplog.text

    @pytest.mark.parametrize(
        "internal_exception",
        [
            ModelRunnerConfigError,
            BaseModelProcessingError,
            PipelineIntegrityError,
            MissingHashError,
            DependencyNotMetError,
            ValueError,
            Exception,
        ],
    )
    def test_run_models_wraps_other_model_runner_exceptions(self, metadata_reader_base, internal_exception, caplog, fs):
        reader = metadata_reader_base
        file_path = "/fake/problem_file.txt"
        fs.create_file(file_path)

        if internal_exception is DependencyNotMetError:
            side_effect_exception = internal_exception("mock error", dependency_type="test", silent=True)
        else:
            side_effect_exception = internal_exception("mock error")
        reader._test_mock_runner.run.side_effect = side_effect_exception

        with pytest.raises(DorsalClientError) as exc_info:
            reader._run_models(file_path=file_path)

        assert isinstance(exc_info.value.original_exception, internal_exception)
        assert "Error running models on file" in caplog.text


@patch("dorsal.file.metadata_reader.MetadataReader._get_or_create_record")
class TestMetadataReaderIndexFile:
    def test_index_file_success_newly_indexed(self, mock_get_record, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/new_file.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="newhash123")
        mock_get_record.return_value = mock_file_record

        mock_result_item = MagicMock(spec=ActualIndexResultItem)
        mock_result_item.hash = "newhash123"
        mock_result_item.url = "http://dorsal/file/newhash123"
        mock_result_item.file_path = None

        client_response_mock = reader._test_mock_client.index_private_file_records.return_value
        client_response_mock.total = 1
        client_response_mock.success = 1
        client_response_mock.error = 0
        client_response_mock.unauthorized = 0
        client_response_mock.results = [mock_result_item]
        client_response_mock.response.status_code = 201

        response = reader.index_file(file_path=file_path, private=True)

        assert response is client_response_mock
        mock_get_record.assert_called_once_with(file_path=file_path, skip_cache=False, overwrite_cache=False)
        reader._test_mock_client.index_private_file_records.assert_called_once_with(file_records=[mock_file_record])
        assert response.results[0].file_path == file_path
        assert "newly indexed" in caplog.text

    def test_index_file_success_updated_existing(self, mock_get_record, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/existing_file.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="existinghash")
        mock_get_record.return_value = mock_file_record

        mock_result_item = MagicMock(
            spec=ActualIndexResultItem,
            hash="existinghash",
            url="http://dorsal/file/existinghash",
            file_path=None,
        )
        client_response_mock = reader._test_mock_client.index_public_file_records.return_value
        client_response_mock.total = 1
        client_response_mock.success = 1
        client_response_mock.error = 0
        client_response_mock.unauthorized = 0
        client_response_mock.results = [mock_result_item]
        client_response_mock.response.status_code = 200

        response = reader.index_file(file_path=file_path, private=False)

        assert response is client_response_mock
        mock_get_record.assert_called_once_with(file_path=file_path, skip_cache=False, overwrite_cache=False)
        reader._test_mock_client.index_public_file_records.assert_called_once_with(file_records=[mock_file_record])
        assert response.results[0].file_path == file_path
        assert "updated/existing" in caplog.text

    def test_index_file_unauthorized_with_results(self, mock_get_record, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/restricted.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="restrictedhash")
        mock_get_record.return_value = mock_file_record

        mock_result_item = MagicMock(spec=ActualIndexResultItem, hash="restrictedhash", url="N/A", file_path=None)
        client_response_mock = reader._test_mock_client.index_private_file_records.return_value
        client_response_mock.total = 1
        client_response_mock.success = 0
        client_response_mock.error = 0
        client_response_mock.unauthorized = 1
        client_response_mock.results = [mock_result_item]
        client_response_mock.response.status_code = 401

        reader.index_file(file_path=file_path, private=True)
        assert "unauthorized" in caplog.text

    def test_index_file_api_error_count_triggers_log(self, mock_get_record, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/error_file_with_count.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="errorcount_hash")
        mock_get_record.return_value = mock_file_record

        mock_result_item = MagicMock(
            spec=ActualIndexResultItem,
            hash="errorcount_hash",
            url="N/A",
            file_path=None,
        )
        client_response_mock = reader._test_mock_client.index_private_file_records.return_value
        client_response_mock.total = 1
        client_response_mock.success = 0
        client_response_mock.error = 1
        client_response_mock.unauthorized = 0
        client_response_mock.results = [mock_result_item]
        client_response_mock.response.status_code = 500

        reader.index_file(file_path=file_path, private=True)
        assert "error during indexing attempt" in caplog.text

    def test_index_file_error_count_no_results_logs_error(self, mock_get_record, metadata_reader_base, caplog):
        reader = metadata_reader_base
        file_path = "/fake/error_no_results.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="error_no_results_hash")
        mock_get_record.return_value = mock_file_record

        client_response_mock = reader._test_mock_client.index_private_file_records.return_value
        client_response_mock.results = []
        client_response_mock.error = 1
        client_response_mock.total = 1
        client_response_mock.success = 0
        client_response_mock.unauthorized = 0
        client_response_mock.response.status_code = 200

        reader.index_file(file_path=file_path, private=True)
        assert "Failed to index file" in caplog.text

    def test_index_file_run_models_fails(self, mock_get_record, metadata_reader_base):
        reader = metadata_reader_base
        file_path = "/fake/bad_processing.txt"
        mock_get_record.side_effect = FileNotFoundError("Cannot find this")

        with pytest.raises(FileNotFoundError):
            reader.index_file(file_path=file_path)

    def test_index_file_client_raises_api_error(self, mock_get_record, metadata_reader_base):
        reader = metadata_reader_base
        file_path = "/fake/client_api_error.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="clientapierrorhash")
        mock_get_record.return_value = mock_file_record

        simulated_client_error = DorsalClientAPIError(
            status_code=503, detail="Service Unavailable", request_url="http://test"
        )
        reader._test_mock_client.index_private_file_records.side_effect = simulated_client_error

        with pytest.raises(DorsalClientAPIError) as exc_info:
            reader.index_file(file_path=file_path)
        assert exc_info.value is simulated_client_error

    def test_index_file_api_response_unexpected_no_results_no_errors_attr(
        self, mock_get_record, metadata_reader_base, caplog
    ):
        reader = metadata_reader_base
        file_path = "/fake/unexpected_resp.txt"
        mock_file_record = MagicMock(spec=FileRecordStrict, hash="hash_unexpected")
        mock_get_record.return_value = mock_file_record

        client_response_mock = reader._test_mock_client.index_public_file_records.return_value
        client_response_mock.results = []
        client_response_mock.error = 0
        client_response_mock.total = 1
        client_response_mock.success = 0
        client_response_mock.unauthorized = 0
        client_response_mock.response.status_code = 200
        client_response_mock.response.text = "Unexpected server text"
        if hasattr(client_response_mock, "errors"):
            del client_response_mock.errors

        reader.index_file(file_path=file_path, private=False)
        assert "Unexpected response from server" in caplog.text


class TestMetadataReaderIndexDirectory:
    @pytest.fixture
    def reader_for_index_dir(
        self,
        mocker,
        mock_get_file_paths,
        mock_dorsal_client_for_reader,
        mock_model_runner_for_reader,
        mock_dorsal_cache,
    ):
        mocker.patch(
            "dorsal.file.metadata_reader.constants.API_MAX_BATCH_SIZE",
            1000,
            create=True,
        )
        mocker.patch(
            "dorsal.file.metadata_reader.constants.MAX_FILES_FOR_LOCAL_PROCESSING_IN_ONE_GO",
            50000,
            create=True,
        )

        mocker.patch("dorsal.file.metadata_reader.get_shared_cache", return_value=mock_dorsal_cache)
        with patch(
            "dorsal.file.metadata_reader.ModelRunner",
            return_value=mock_model_runner_for_reader,
        ):
            reader = MetadataReader(client=mock_dorsal_client_for_reader)
            reader._test_mock_client = mock_dorsal_client_for_reader
            reader._test_mock_runner = mock_model_runner_for_reader
            reader._test_mock_get_file_paths = mock_get_file_paths

            yield reader

    def test_index_directory_not_found(self, reader_for_index_dir, caplog):
        reader = reader_for_index_dir
        dir_path = "/nonexistent"
        reader._test_mock_get_file_paths.side_effect = FileNotFoundError(f"Dir not found: {dir_path}")

        with pytest.raises(FileNotFoundError):
            reader.index_directory(dir_path=dir_path)
        assert "Directory not found for generating records" in caplog.text

    def test_index_directory_scan_error(self, reader_for_index_dir):
        reader = reader_for_index_dir
        dir_path = "/protected_dir"
        reader._test_mock_get_file_paths.side_effect = OSError("Scan permission denied")
        with pytest.raises(DorsalClientError) as exc_info:
            reader.index_directory(dir_path=dir_path)
        assert isinstance(exc_info.value.original_exception, OSError)

    def test_index_directory_empty(self, reader_for_index_dir, caplog):
        reader = reader_for_index_dir
        dir_path = "/empty_dir"
        reader._test_mock_get_file_paths.return_value = []
        response = reader.index_directory(dir_path=dir_path)

        assert response.total == 0
        reader._test_mock_client.index_private_file_records.assert_not_called()
        assert "No unique files from" in caplog.text

    def test_index_directory_success(self, reader_for_index_dir, temp_dir_with_files, caplog):
        reader = reader_for_index_dir
        f1_path = str(temp_dir_with_files / "f1.txt")
        (temp_dir_with_files / "f1.txt").touch()
        f2_path = str(temp_dir_with_files / "f2.txt")
        (temp_dir_with_files / "f2.txt").touch()
        file_paths = [f1_path, f2_path]
        reader._test_mock_get_file_paths.return_value = file_paths

        mock_record1 = MagicMock(spec=FileRecordStrict, hash="hash1")
        mock_record2 = MagicMock(spec=FileRecordStrict, hash="hash2")
        reader._test_mock_runner.run.side_effect = [mock_record1, mock_record2]

        client_response_mock = reader._test_mock_client.index_private_file_records.return_value
        client_response_mock.total = 2
        client_response_mock.success = 2
        result_item1 = MagicMock(spec=ActualIndexResultItem, hash="hash1", url="url1", file_path=None)
        result_item2 = MagicMock(spec=ActualIndexResultItem, hash="hash2", url="url2", file_path=None)
        client_response_mock.results = [result_item1, result_item2]

        response = reader.index_directory(dir_path=str(temp_dir_with_files), private=True)

        reader._test_mock_get_file_paths.assert_called_once_with(dir_path=str(temp_dir_with_files), recursive=False)
        assert reader._test_mock_runner.run.call_count == 2
        reader._test_mock_client.index_private_file_records.assert_called_once_with(
            file_records=[mock_record1, mock_record2]
        )

        # Sort results to make assertion deterministic
        response.results.sort(key=lambda x: x.hash)
        file_paths.sort()

        assert response.results[0].file_path == f1_path
        assert response.results[1].file_path == f2_path
        assert "Indexing complete for" in caplog.text

    def test_index_directory_public_indexing(self, reader_for_index_dir, temp_dir_with_files, caplog):
        reader = reader_for_index_dir
        f_path = str(temp_dir_with_files / "public_f1.txt")
        (temp_dir_with_files / "public_f1.txt").touch()
        file_paths = [f_path]
        reader._test_mock_get_file_paths.return_value = file_paths

        mock_record_public = MagicMock(spec=FileRecordStrict, hash="hash_public")
        reader._test_mock_runner.run.return_value = mock_record_public

        client_response_mock = reader._test_mock_client.index_public_file_records.return_value
        client_response_mock.total = 1
        client_response_mock.success = 1
        result_item_public = MagicMock(
            spec=ActualIndexResultItem,
            hash="hash_public",
            url="url_public",
            file_path=None,
        )
        client_response_mock.results = [result_item_public]

        response = reader.index_directory(dir_path=str(temp_dir_with_files), private=False)

        reader._test_mock_client.index_public_file_records.assert_called_once_with(file_records=[mock_record_public])
        reader._test_mock_client.index_private_file_records.assert_not_called()
        assert response.results[0].file_path == file_paths[0]
        assert "Indexing complete for" in caplog.text

    def test_index_directory_all_files_skipped_or_error(self, reader_for_index_dir, temp_dir_with_files, caplog):
        reader = reader_for_index_dir
        reader._ignore_duplicates = True

        dir_to_scan = str(temp_dir_with_files / "subdir_for_all_skip")
        Path(dir_to_scan).mkdir(exist_ok=True)
        f1 = Path(dir_to_scan) / "f1_skip.txt"
        f1.touch()
        f2 = Path(dir_to_scan) / "f2_skip_err.txt"
        f2.touch()

        reader._test_mock_get_file_paths.return_value = [str(f1), str(f2)]
        reader._test_mock_runner.run.side_effect = IOError("All files error out in _run_models")

        response_all_error = reader.index_directory(dir_path=dir_to_scan)

        assert response_all_error.total == 0
        assert response_all_error.success == 0
        reader._client.index_private_file_records.assert_not_called()
        assert "No unique files from" in caplog.text

    def test_index_directory_raises_correct_duplicate_file_error(
        self,
        mocker,
        temp_dir_with_files,
        mock_get_file_paths,
        mock_model_runner_for_reader,
        mock_dorsal_cache,
    ):
        mocker.patch("dorsal.file.metadata_reader.get_shared_cache", return_value=mock_dorsal_cache)
        mock_client_on_reader = mocker.MagicMock(spec=DorsalClient)
        with patch(
            "dorsal.file.metadata_reader.ModelRunner",
            return_value=mock_model_runner_for_reader,
        ):
            reader = MetadataReader(ignore_duplicates=False, client=mock_client_on_reader)

        file_path1 = str(temp_dir_with_files / "fileA.txt")
        (temp_dir_with_files / "fileA.txt").touch()
        file_path2 = str(temp_dir_with_files / "fileB_dupA.txt")
        (temp_dir_with_files / "fileB_dupA.txt").touch()
        mock_get_file_paths.return_value = [file_path1, file_path2]

        mock_record_A = MagicMock(spec=FileRecordStrict, hash="hashA_dup_check")
        mock_model_runner_for_reader.run.side_effect = [mock_record_A, mock_record_A]

        with pytest.raises(DuplicateFileError) as exc_info:
            reader.index_directory(dir_path=str(temp_dir_with_files))

        assert "Duplicate file content detected" in str(exc_info.value)
        assert file_path1 in exc_info.value.file_paths
        assert file_path2 in exc_info.value.file_paths
        mock_client_on_reader.index_private_file_records.assert_not_called()

    def test_index_directory_client_raises_batch_size_error(self, reader_for_index_dir, temp_dir_with_files):
        reader = reader_for_index_dir
        f1_path = str(temp_dir_with_files / "f1.txt")
        (temp_dir_with_files / "f1.txt").touch()
        reader._test_mock_get_file_paths.return_value = [f1_path]

        mock_run_output = MagicMock(spec=FileRecordStrict, hash="h1_batch_err")
        reader._test_mock_runner.run.return_value = mock_run_output

        simulated_api_error = DorsalClientAPIError(
            detail="Batch too large from client",
            status_code=413,
            request_url="http://test",
        )
        reader._test_mock_client.index_private_file_records.side_effect = simulated_api_error

        with pytest.raises(DorsalClientAPIError) as exc_info:
            reader.index_directory(dir_path=str(temp_dir_with_files))

        assert exc_info.value is simulated_api_error


class TestMetadataReaderReadMethods:
    @pytest.fixture(autouse=True)
    def patch_libmagic(self, mocker):
        mocker.patch(
            "dorsal.file.utils.infer_mediatype.magic.from_file",
            return_value="text/plain",
        )

    @pytest.fixture
    def reader_for_read_methods(self, mock_dorsal_client_for_reader, mock_dorsal_cache):
        return MetadataReader(client=mock_dorsal_client_for_reader)

    def test_scan_file_success(self, reader_for_read_methods, caplog, fs):
        reader = reader_for_read_methods
        file_path = "/fake/readable.txt"
        fs.create_file(file_path, contents="data")

        result = reader.scan_file(file_path=file_path, skip_cache=True, overwrite_cache=False)

        assert isinstance(result, LocalFile)
        assert result.hash is not None
        assert "Successfully processed file" in caplog.text

    @pytest.mark.parametrize("exception_type", [FileNotFoundError, IOError])
    @patch("dorsal.file.dorsal_file.LocalFile._generate_record")
    def test_scan_file_raises_file_io_errors(self, mock_generate, reader_for_read_methods, exception_type, caplog, fs):
        reader = reader_for_read_methods
        file_path = "/fake/error_on_read.txt"
        fs.create_file(file_path)

        simulated_error = exception_type("Simulated error from LocalFile")
        mock_generate.side_effect = simulated_error

        with pytest.raises(exception_type) as exc_info:
            reader.scan_file(file_path=file_path, skip_cache=True, overwrite_cache=False)
        assert exc_info.value is simulated_error

    @patch("dorsal.file.dorsal_file.LocalFile._generate_record")
    def test_scan_file_wraps_other_localfile_exceptions(self, mock_generate, reader_for_read_methods, caplog, fs):
        reader = reader_for_read_methods
        file_path = "/fake/localfile_generic_error.txt"
        fs.create_file(file_path)
        original_exc = ModelRunnerConfigError("Some config issue")
        mock_generate.side_effect = original_exc

        with pytest.raises(DorsalError) as exc_info:
            reader.scan_file(file_path=file_path, skip_cache=True, overwrite_cache=False)

        assert exc_info.value.original_exception is original_exc
        assert "Failed to read/process file" in caplog.text

    def test_scan_directory_success(self, reader_for_read_methods, mock_get_file_paths, temp_dir_with_files, caplog):
        reader = reader_for_read_methods
        file_paths = [str(p) for p in temp_dir_with_files.glob("**/*") if p.is_file()]
        mock_get_file_paths.return_value = file_paths

        results = reader.scan_directory(dir_path=str(temp_dir_with_files))

        assert len(results) == 5
        assert all(isinstance(f, LocalFile) for f in results)
        assert "Successfully processed 5 files" in caplog.text

    def test_scan_directory_skips_on_localfile_error(
        self,
        mocker,
        reader_for_read_methods,
        mock_get_file_paths,
        temp_dir_with_files,
        caplog,
        fs,
    ):
        reader = reader_for_read_methods

        dir_path = str(temp_dir_with_files)
        file_good = str(temp_dir_with_files / "good.txt")
        fs.create_file(file_good)
        file_bad_io = str(temp_dir_with_files / "bad_io.txt")
        fs.create_file(file_bad_io)
        file_bad_other = str(temp_dir_with_files / "bad_other.txt")
        fs.create_file(file_bad_other)

        mock_get_file_paths.return_value = [file_good, file_bad_io, file_bad_other]

        original_init = LocalFile.__init__

        def side_effect(self, file_path, **kwargs):
            if file_path == file_bad_io:
                raise IOError("IO error for skip test")
            if file_path == file_bad_other:
                raise ValueError("Other processing error for skip test")
            kwargs["file_path"] = file_path
            original_init(self, **kwargs)

        mocker.patch.object(LocalFile, "__init__", side_effect=side_effect, autospec=True)

        results, warnings = reader.scan_directory(dir_path=dir_path, return_errors=True)

        assert len(results) == 1
        assert len(warnings) == 2
        assert results[0].name == "good.txt"
        assert "Skipping 'bad_io.txt'" in warnings[0]
        assert "Skipping 'bad_other.txt'" in warnings[1]

    def test_scan_directory_empty(self, reader_for_read_methods, mock_get_file_paths, caplog):
        reader = reader_for_read_methods
        dir_path = "/empty_read_dir"
        mock_get_file_paths.return_value = []
        results = reader.scan_directory(dir_path=dir_path)
        assert len(results) == 0
        assert "No files found to read" in caplog.text

    def test_scan_directory_get_file_paths_generic_exception(self, reader_for_read_methods, mock_get_file_paths):
        reader = reader_for_read_methods
        dir_path = "/some_dir_scan_fail"
        generic_error = Exception("Generic scan error from get_file_paths")
        mock_get_file_paths.side_effect = generic_error

        with pytest.raises(DorsalError) as exc_info:
            reader.scan_directory(dir_path=dir_path)

        assert exc_info.value.original_exception is generic_error

    def test_scan_directory_get_file_paths_raises_file_not_found(
        self, reader_for_read_methods, mock_get_file_paths, caplog
    ):
        reader = reader_for_read_methods
        dir_path = "/non_existent_dir_for_read_dir"
        fnf_error = FileNotFoundError(f"Directory not found: {dir_path}")
        mock_get_file_paths.side_effect = fnf_error

        with pytest.raises(FileNotFoundError) as exc_info:
            reader.scan_directory(dir_path=dir_path)

        assert exc_info.value is fnf_error
        assert "Directory not found" in caplog.text
