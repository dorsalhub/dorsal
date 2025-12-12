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

import functools
import json
import time
from typing import Any, Type
import pytest
from pydantic import BaseModel, ValidationError as PydanticValidationError
from unittest.mock import MagicMock

from dorsal.common.exceptions import (
    BaseModelProcessingError,
    DependencyNotMetError,
    MissingHashError,
    ModelExecutionError,
    ModelImportError,
    ModelRunnerConfigError,
    PipelineIntegrityError,
    DataQualityError,
    ModelRunnerConfigError,
    MissingHashError,
)
from dorsal.common.model import AnnotationModel
from dorsal.file.validators.file_record import FileRecordStrict
from dorsal.file.configs.model_runner import (
    RunModelResult,
    ModelRunnerPipelineStep,
    DependencyConfig,
)
from dorsal.common.validators import JsonSchemaValidator

from dorsal.file.model_runner import ModelRunner

import logging

logging.getLogger("dorsal").setLevel(logging.DEBUG)


@pytest.fixture(autouse=True)
def mock_langcodes_db(mocker):
    """
    Prevent 'langcodes' from loading its massive database file. Prevents a hang-interaction with pyfakefs.

    Note: removing this won't break, but will slow down the test suite.
    """
    import langcodes

    mocker.patch.object(langcodes.Language, "language_name", return_value="English")


regression_test_cases = [
    (
        "tests/data/empty.txt",
        {
            "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "annotations.file_base.record.media_type": "application/x-empty",
        },
    ),
    (
        "tests/data/valid.docx",
        {
            "hash": "d46710698e1ca41d6ebc671cbdad362c8d60f0ba33c0e03974719c40ae0b0e03",
            "annotations.file_base.record.media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    ),
    (
        "tests/data/valid.epub",
        {
            "hash": "0250bcc7c398851f99ae2589c2173c4f446c9906201fe4afc1ab7ef79be87e25",
            "annotations.file_base.record.media_type": "application/epub+zip",
        },
    ),
    (
        "tests/data/valid.gif",
        {
            "hash": "0eafa55998d0d61f477653cb15168105c06763c74aaebe8ff7e55da98457f030",
            "annotations.file_base.record.media_type": "image/gif",
        },
    ),
    (
        "tests/data/valid.jpg",
        {
            "hash": "048494ec539b4d6b1d0f32a98abd805f614aaf10fe6a8e6f8f033d38acf6d2ec",
            "annotations.file_base.record.media_type": "image/jpeg",
        },
    ),
    (
        "tests/data/valid.png",
        {
            "hash": "603506996b902b8797cbc1dc4bf350440caad5c59feb97c39344fd7648403b5d",
            "annotations.file_base.record.media_type": "image/png",
        },
    ),
    (
        "tests/data/valid.pptx",
        {
            "hash": "32bffb2f9e70b526cefb98dd695d0a378c077ecbb1b5aa7520d685828ab79c7b",
            "annotations.file_base.record.media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        },
    ),
    (
        "tests/data/valid.txt",
        {
            "hash": "0425074d7748edc4faa98177678ef8e16a493504dfa15ca02bcdc56a848aca99",
            "annotations.file_base.record.media_type": "text/plain",
        },
    ),
    (
        "tests/data/valid.xlsx",
        {
            "hash": "deb0cf769a2fb5326b3c592e3d81303a7e3eeba10f76e745169f4658215a4eaf",
            "annotations.file_base.record.media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    ),
    (
        "tests/data/valid.mp4",
        {
            "hash": "3f2334555c564469898770fa5e4716859d9bea8a3b792fca86c180f729e96653",
            "annotations.file_base.record.media_type": "video/mp4",
            "annotations.file_mediainfo.record.Format": "MPEG-4",
        },
    ),
    (
        "tests/data/valid.pdf",
        {
            "hash": "4b7872aecb99cb61013e0c1a3e3a64b8226206e886e25dbbe28458f47ed05f41",
            "annotations.file_base.record.media_type": "application/pdf",
            "annotations.file_pdf.record.page_count": 1,
        },
    ),
    (
        "tests/data/valid.mkv",
        {
            "hash": "91accb084a35a4719ee0ec9702ecc08d91cde38820f68db4377acbfb94092333",
            "annotations.file_base.record.media_type": "video/matroska",
            "annotations.file_mediainfo.record.Format": "Matroska",
        },
    ),
    (
        "tests/data/valid.zip",
        {
            "hash": "6e8a4f9dc54a67f14524fd0daddefd89c581dea6a6994719a1998a7fc2f7a412",
            "annotations.file_base.record.media_type": "application/zip",
        },
    ),
]


def get_nested_attr(obj, path):
    """
    Accesses a nested attribute from an object using a dot-separated string path.
    Example: get_nested_attr(result, 'annotations.file_pdf.record.page_count')
    """
    return functools.reduce(getattr, path.split("."), obj)


@pytest.mark.parametrize("file_path, expectations", regression_test_cases)
def test_regression(file_path, expectations):
    """
    Runs an end-to-end test and performs a unique set of assertions
    for each file type based on the 'expectations' dictionary.
    """
    model_runner = ModelRunner(pipeline_config="default")
    result = model_runner.run(file_path=file_path)

    for path, expected_value in expectations.items():
        actual_value = get_nested_attr(result, path)
        assert actual_value == expected_value


class MockBaseAnnotationModel(AnnotationModel):
    """A mock base model that returns a valid core file record."""

    id = "dorsal/file-core"
    version = "1.0.0"

    def __init__(self, file_path: str):
        self.file_path = file_path

    def main(self, **kwargs) -> dict[str, Any]:
        # A valid base record with required hashes
        return {
            "hash": "a" * 64,
            "name": "test_file.txt",
            "extension": ".txt",
            "size": 123,
            "media_type": "text/plain",
            "all_hashes": [
                {"id": "SHA-256", "value": "a" * 64},
                {"id": "BLAKE3", "value": "b" * 64},
            ],
        }


class MockSuccessAnnotationModel(AnnotationModel):
    """A mock pipeline model that always succeeds."""

    id = "dorsal/success-model"
    version = "1.0.0"

    def __init__(self, file_path: str):
        self.file_path = file_path

    def main(self, **kwargs) -> dict[str, Any]:
        return {"status": "success", "data": 42}


class MockFailureAnnotationModel(AnnotationModel):
    """A mock pipeline model that always raises an exception."""

    id = "dorsal/failure-model"
    version = "1.0.0"

    def __init__(self, file_path: str):
        self.file_path = file_path

    def main(self, **kwargs) -> dict[str, Any]:
        raise ValueError("Model execution failed")


class MockNoneReturnModel(AnnotationModel):
    """A mock model that returns None."""

    id = "dorsal/none-return-model"
    version = "1.0.0"
    error = "Returned None intentionally"

    def __init__(self, file_path: str):
        self.file_path = file_path

    def main(self, **kwargs) -> None:
        return None


class MockPydanticValidator(BaseModel):
    """A Pydantic validator that expects the success model's output."""

    status: str
    data: int


# Mock Dependency Checkers
def mock_checker_true(results: list[RunModelResult], config: DependencyConfig) -> bool:
    return True


def mock_checker_false(results: list[RunModelResult], config: DependencyConfig) -> bool:
    return False


def mock_checker_error(results: list[RunModelResult], config: DependencyConfig) -> bool:
    raise RuntimeError("Checker crashed")


@pytest.fixture
def mock_fs(fs):
    """Fixture to create a fake file system with one test file."""
    fs.create_file("/test_file.txt", contents="hello world")
    yield fs


@pytest.fixture
def base_model_patch(mocker):
    """Mocks the import_callable to return our MockBaseAnnotationModel."""
    mocker.patch("dorsal.common.validators.import_callable", return_value=MockBaseAnnotationModel)
    mocker.patch(
        "dorsal.file.model_runner.ModelRunner._load_pre_pipeline_model_step",
        return_value=ModelRunnerPipelineStep(
            annotation_model={
                "module": "tests.unit.test_model_runner",
                "name": "MockBaseAnnotationModel",
            },
            schema_id="file/base",
        ),
    )


# --- Test Classes --------------------------------------------------------------


class TestModelRunnerInitialization:
    """Tests for the ModelRunner's __init__ method."""

    def test_init_with_list_config(self, base_model_patch):
        """Test successful initialization with a direct list configuration."""
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "schema_id": "success/test",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        assert len(runner.pipeline) == 1
        assert runner.pipeline[0].schema_id == "success/test"

    def test_init_with_none_config(self, base_model_patch):
        """Test initialization with `pipeline_config=None`."""
        runner = ModelRunner(pipeline_config=None)
        assert runner.pipeline == []
        assert "No pipeline" in runner.pipeline_config_source

    def test_init_with_empty_list_config(self, base_model_patch):
        """Test initialization with an empty list `[]`."""
        runner = ModelRunner(pipeline_config=[])
        assert runner.pipeline == []
        assert "0 step pipeline" in runner.pipeline_config_source

    def test_init_with_invalid_config_type(self, base_model_patch):
        """Test that a non-supported config type raises ModelRunnerConfigError."""
        with pytest.raises(ModelRunnerConfigError):
            ModelRunner(pipeline_config=123)

    def test_init_with_invalid_step_in_pipeline(self, base_model_patch):
        """Test that an invalid step in the pipeline raises ModelRunnerConfigError."""
        pipeline_config = [{"invalid_key": "some_value"}]
        with pytest.raises(ModelRunnerConfigError):
            ModelRunner(pipeline_config=pipeline_config)

    def test_init_base_model_override(self, base_model_patch, mocker):
        """Test that options for the base model are overridden if it's the first pipeline step."""
        mocker.patch(
            "dorsal.file.model_runner.ModelRunner._load_pre_pipeline_model_step",
            return_value=ModelRunnerPipelineStep(
                annotation_model={
                    "module": "tests.unit.test_model_runner",
                    "name": "MockBaseAnnotationModel",
                },
                schema_id="file/base",
            ),
        )

        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockBaseAnnotationModel",
                },
                "options": {"new_option": True},
                "schema_id": "dorsal/base-override",
            },
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "schema_id": "success/test",
            },
        ]

        runner = ModelRunner(pipeline_config=pipeline_config)
        assert runner.pre_model_options == {"new_option": True}
        assert len(runner.pipeline) == 1
        assert runner.pipeline[0].annotation_model.name == "MockSuccessAnnotationModel"

    def test_init_logs_warning_for_duplicate_models(self, base_model_patch, caplog):
        """Tests that a warning is logged for duplicate models in the config."""
        pipeline_config = [
            {
                "annotation_model": {"module": "m", "name": "DuplicateModel"},
                "schema_id": "dorsal/test1",
            },
            {
                "annotation_model": {"module": "m", "name": "DuplicateModel"},
                "schema_id": "dorsal/test2",
            },
        ]
        ModelRunner(pipeline_config=pipeline_config)
        assert "Configuration Warning: Duplicate model" in caplog.text
        assert "m.DuplicateModel" in caplog.text


class TestModelRunnerExecution:
    """Tests for the main `run()` method and its orchestration."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker, base_model_patch):
        """Mock all dynamic imports for execution tests."""
        mock_imports = {
            "tests.unit.test_model_runner.MockBaseAnnotationModel": MockBaseAnnotationModel,
            "tests.unit.test_model_runner.MockSuccessAnnotationModel": MockSuccessAnnotationModel,
            "tests.unit.test_model_runner.MockFailureAnnotationModel": MockFailureAnnotationModel,
            "tests.unit.test_model_runner.MockNoneReturnModel": MockNoneReturnModel,
            "tests.unit.test_model_runner.MockPydanticValidator": MockPydanticValidator,
            "tests.unit.test_model_runner.mock_checker_true": mock_checker_true,
            "tests.unit.test_model_runner.mock_checker_false": mock_checker_false,
            "tests.unit.test_model_runner.mock_checker_error": mock_checker_error,
        }

        def mock_import_callable(path_obj):
            path_str = f"{path_obj.module}.{path_obj.name}"
            if path_str in mock_imports:
                return mock_imports[path_str]
            raise ImportError(f"Mock import failed for {path_str}")

        mocker.patch("dorsal.file.model_runner.import_callable", mock_import_callable)

    def test_run_successful_pipeline(self, mock_fs):
        """Test a full successful run with one pipeline model."""
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "validation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockPydanticValidator",
                },
                "schema_id": "success/test",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")

        assert isinstance(result, FileRecordStrict)
        success_annotation_list = result.annotations.model_extra["success/test"]
        assert isinstance(success_annotation_list, list)
        assert success_annotation_list[0].record is not None
        assert success_annotation_list[0].record.status == "success"
        assert success_annotation_list[0].record.data == 42

    def test_run_with_debug_mode(self, mock_fs):
        runner = ModelRunner(pipeline_config=[], debug=True)
        runner.run("/test_file.txt")
        assert "MockBaseAnnotationModel" in runner.time_taken
        assert runner.time_taken["MockBaseAnnotationModel"] > 0

    def test_run_on_nonexistent_file(self):
        runner = ModelRunner(pipeline_config=[])
        with pytest.raises(FileNotFoundError):
            runner.run("/non_existent_file.txt")

    def test_run_base_model_fails(self, mock_fs, mocker):
        mocker.patch.object(MockBaseAnnotationModel, "main", side_effect=ValueError)
        runner = ModelRunner(pipeline_config=[])
        with pytest.raises(BaseModelProcessingError):
            runner.run("/test_file.txt")

    def test_run_pipeline_model_import_fails(self, mock_fs):
        pipeline_config = [
            {
                "annotation_model": {"module": "non.existent", "name": "BadModel"},
                "schema_id": "import/fail",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")
        assert "import/fail" not in result.annotations.model_extra

    def test_run_pipeline_model_execution_fails(self, mock_fs):
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockFailureAnnotationModel",
                },
                "schema_id": "exec/fail",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")
        assert "exec/fail" not in result.annotations.model_extra

    def test_run_pipeline_model_validation_fails(self, mock_fs):
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "validation_model": {"module": "pydantic", "name": "BaseModel"},
                "schema_id": "validation/fail",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")
        assert "validation/fail" not in result.annotations.model_extra

    def test_run_dependency_not_met_silent(self, mock_fs):
        """Test that a model with an unmet silent dependency is skipped."""
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "dependencies": [
                    {
                        "type": "media_type",
                        "silent": True,
                        "checker": {
                            "module": "tests.unit.test_model_runner",
                            "name": "mock_checker_false",
                        },
                    }
                ],
                "schema_id": "dep/skip",
            }
        ]

        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")

        # The runner's merge logic skips results with errors or unmet dependencies.
        assert "dep/skip" not in result.annotations.model_extra

    def test_run_dependency_not_met_non_silent(self, mock_fs):
        """Test that an unmet non-silent dependency halts the pipeline by raising an error."""
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "dependencies": [
                    {
                        "type": "media_type",
                        "silent": False,
                        "checker": {
                            "module": "tests.unit.test_model_runner",
                            "name": "mock_checker_false",
                        },
                    }
                ],
                "schema_id": "dep/halt",
            }
        ]

        runner = ModelRunner(pipeline_config=pipeline_config)
        with pytest.raises(DependencyNotMetError):
            runner.run("/test_file.txt")

    def test_run_dependency_checker_fails(self, mock_fs):
        """Test that a failing dependency checker skips the model."""
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "dependencies": [
                    {
                        "type": "media_type",
                        "checker": {
                            "module": "tests.unit.test_model_runner",
                            "name": "mock_checker_error",
                        },
                    }
                ],
                "schema_id": "dep/checker-fail",
            }
        ]

        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")

        # The runner's merge logic skips models where the dependency checker itself fails.
        assert "dep/checker-fail" not in result.annotations.model_extra


class TestModelRunnerResultMerging:
    """Tests focusing on the logic within `_merge_model_results`."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker, base_model_patch):
        mocker.patch(
            "dorsal.file.model_runner.import_callable",
            side_effect=lambda path_obj: {
                "tests.unit.test_model_runner.MockBaseAnnotationModel": MockBaseAnnotationModel,
                "tests.unit.test_model_runner.MockSuccessAnnotationModel": MockSuccessAnnotationModel,
            }[f"{path_obj.module}.{path_obj.name}"],
        )

    def test_merge_appends_duplicate_schema_id(self, mock_fs, caplog):
        pipeline_config = [
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "options": {"id": 1},
                "schema_id": "duplicate/data",
            },
            {
                "annotation_model": {
                    "module": "tests.unit.test_model_runner",
                    "name": "MockSuccessAnnotationModel",
                },
                "options": {"id": 2},
                "schema_id": "duplicate/data",
            },
        ]
        runner = ModelRunner(pipeline_config=pipeline_config)
        result = runner.run("/test_file.txt")

        assert "Duplicate target dataset ID 'duplicate/data' encountered" not in caplog.text

        annotations_list = result.annotations.model_extra["duplicate/data"]
        assert isinstance(annotations_list, list)
        assert len(annotations_list) == 2

    def test_merge_missing_blake3_hash_raises_error(self, mock_fs, mocker):
        mocker.patch.object(
            MockBaseAnnotationModel,
            "main",
            return_value={
                "hash": "a" * 64,
                "name": "test_file.txt",
                "extension": ".txt",
                "size": 123,
                "media_type": "text/plain",
                "all_hashes": [{"id": "SHA-256", "value": "a" * 64}],
            },
        )
        runner = ModelRunner(pipeline_config=[])
        with pytest.raises(PipelineIntegrityError):
            runner.run("/test_file.txt")

    def test_merge_final_validation_fails(self, mock_fs, mocker):
        mocker.patch.object(
            FileRecordStrict,
            "__init__",
            side_effect=PydanticValidationError.from_exception_data("Test", []),
        )
        runner = ModelRunner(pipeline_config=[])
        with pytest.raises(PipelineIntegrityError):
            runner.run("/test_file.txt")


class MockJsonSchemaModel(AnnotationModel):
    """Returns data to be validated by a JSON schema."""

    id = "dorsal/json-schema"
    version = "1.0.0"

    def __init__(self, file_path: str):
        self.file_path = file_path

    def main(self, **kwargs) -> dict[str, Any]:
        return {"score": 100, "label": "perfect"}


# --- Advanced Test Class ---


class TestModelRunnerAdvanced:
    """
    Targets specific coverage gaps: file loading, JSON schema validation,
    linter integration, and data integrity failures.
    """

    @pytest.fixture(autouse=True)
    def setup_advanced_mocks(self, mocker, base_model_patch):
        """Extends the existing mocks with our new edge-case models."""

        mock_imports = {
            "tests.unit.test_model_runner.MockBaseAnnotationModel": MockBaseAnnotationModel,
            "tests.unit.test_model_runner.MockSuccessAnnotationModel": MockSuccessAnnotationModel,
            "tests.unit.test_model_runner.MockNoneReturnModel": MockNoneReturnModel,
            "tests.unit.test_model_runner.MockJsonSchemaModel": MockJsonSchemaModel,
        }

        def mock_import_callable(path_obj):
            # Handle dictionary lookups (used by JSON Schema loading logic)
            if isinstance(path_obj, dict):
                return None

            path_str = f"{path_obj.module}.{path_obj.name}"
            if path_str in mock_imports:
                return mock_imports[path_str]
            raise ImportError(f"Mock import failed for {path_str}")

        mocker.patch("dorsal.file.model_runner.import_callable", side_effect=mock_import_callable)

        # Mock get_json_schema_validator to return a dummy validator
        mock_validator = MagicMock(spec=JsonSchemaValidator)
        mock_validator.schema = {"version": "0.1.0"}
        mocker.patch("dorsal.common.validators.json_schema.get_json_schema_validator", return_value=mock_validator)

        # We mock the module-level function used by the runner
        mocker.patch(
            "dorsal.file.model_runner.json_schema_validate_records",
            return_value={"valid_records": 1, "error_details": []},
        )

    # --- Pipeline Config Loading Tests (Lines 212-249) ---

    def test_load_config_from_valid_json_file(self, mock_fs):
        """Test loading pipeline from a valid JSON file."""
        config_data = [
            {
                "annotation_model": {"module": "tests.unit.test_model_runner", "name": "MockSuccessAnnotationModel"},
                "schema_id": "test/file-json",
            }
        ]
        mock_fs.create_file("/pipeline.json", contents=json.dumps(config_data))

        runner = ModelRunner(pipeline_config="/pipeline.json")
        assert len(runner.pipeline) == 1
        assert runner.pipeline[0].schema_id == "test/file-json"

    def test_load_config_file_not_found(self, mock_fs):
        """Test FileNotFoundError handling."""
        with pytest.raises(ModelRunnerConfigError) as exc:
            ModelRunner(pipeline_config="/nonexistent.json")
        assert "Pipeline config file not found" in str(exc.value)

    def test_load_config_invalid_json(self, mock_fs):
        """Test JSONDecodeError handling."""
        mock_fs.create_file("/bad_json.json", contents="{ invalid json [")
        with pytest.raises(ModelRunnerConfigError) as exc:
            ModelRunner(pipeline_config="/bad_json.json")
        assert "Cannot parse pipeline config file" in str(exc.value)

    def test_load_config_not_a_list(self, mock_fs):
        """Test validation that the root JSON element is a list."""
        mock_fs.create_file("/dict_config.json", contents=json.dumps({"some": "dict"}))
        with pytest.raises(ModelRunnerConfigError) as exc:
            ModelRunner(pipeline_config="/dict_config.json")
        # The runner wraps the error, so we check for the outer wrapper message
        assert "Cannot read/parse config file" in str(exc.value)

    # --- Edge Case Execution Tests ---

    def test_run_model_returns_none(self, mock_fs):
        """Test a model that returns None (Lines 579-592)."""
        pipeline = [
            {
                "annotation_model": {"module": "tests.unit.test_model_runner", "name": "MockNoneReturnModel"},
                "schema_id": "test/none",
            }
        ]
        runner = ModelRunner(pipeline_config=pipeline)
        result = runner.run("/test_file.txt")

        annotations_dict = result.annotations.model_dump(exclude_none=True, by_alias=True)

        assert "test/none" not in annotations_dict

        assert "file/base" in annotations_dict

    def test_json_schema_validation_flow(self, mock_fs, mocker):
        """Test the JSON Schema validation branch (Lines 334-342, 632)."""
        # Config where validation_model is a dict (Schema)
        pipeline = [
            {
                "annotation_model": {"module": "tests.unit.test_model_runner", "name": "MockJsonSchemaModel"},
                "validation_model": {"type": "object", "properties": {"score": {"type": "integer"}}},
                "schema_id": "test/json-schema",
            }
        ]

        runner = ModelRunner(pipeline_config=pipeline)
        result = runner.run("/test_file.txt")

        # Access the dynamic field. Since extra="allow", it's available in model_extra.
        annotation_list = result.annotations.model_extra["test/json-schema"]

        assert isinstance(annotation_list, list)
        assert annotation_list[0].record.score == 100

    def test_linter_error_blocking(self, mock_fs, mocker):
        """Test that linter errors block result inclusion (Lines 695-704)."""

        # Define a side effect that only fails for our specific test schema
        def linter_side_effect(schema_id, record, raise_on_error):
            if schema_id == "test/linter-fail":
                raise DataQualityError("Lint failed")
            return None

        mocker.patch("dorsal.file.model_runner.apply_linter", side_effect=linter_side_effect)

        pipeline = [
            {
                "annotation_model": {"module": "tests.unit.test_model_runner", "name": "MockSuccessAnnotationModel"},
                "schema_id": "test/linter-fail",
                "ignore_linter_errors": False,  # Default
            }
        ]

        runner = ModelRunner(pipeline_config=pipeline)
        result = runner.run("/test_file.txt")

        annotations_dict = result.annotations.model_dump()
        assert "test/linter-fail" not in annotations_dict

    def test_deactivated_step(self, mock_fs, caplog):
        """Test that deactivated steps are skipped (Lines 860-865)."""
        pipeline = [
            {
                "annotation_model": {"module": "tests.unit.test_model_runner", "name": "MockSuccessAnnotationModel"},
                "schema_id": "test/skipped",
                "deactivated": True,
            }
        ]

        ModelRunner(pipeline_config=pipeline).run("/test_file.txt")
        assert "Skipping deactivated model" in caplog.text

    def test_critical_missing_hash_in_merge(self, mock_fs, mocker):
        """Test critical failure if base model implies no BLAKE3 hash (Lines 1060-1065)."""
        # 1. Mock the AnnotationModel output to look valid enough to run
        mocker.patch.object(
            MockBaseAnnotationModel,
            "main",
            return_value={
                "hash": "a" * 64,
                "name": "t.txt",
                "extension": ".txt",
                "size": 10,
                "media_type": "text/plain",
                "all_hashes": [{"id": "SHA-256", "value": "a" * 64}, {"id": "BLAKE3", "value": "b" * 64}],
            },
        )

        mock_validated_record = MagicMock()
        mock_validated_record.hash = "a" * 64
        mock_validated_record.similarity_hash = None
        mock_validated_record.all_hash_ids = {"SHA-256": "a" * 64}

        mocker.patch(
            "dorsal.file.validators.base.FileCoreValidationModelStrict.model_validate",
            return_value=mock_validated_record,
        )

        runner = ModelRunner(pipeline_config=[])
        with pytest.raises(MissingHashError):
            runner.run("/test_file.txt")

    def test_schema_id_none_skips_merge(self, mock_fs):
        """Test that a result with no schema_id is skipped (Lines 1080-1084)."""

        step_config = ModelRunnerPipelineStep(
            annotation_model={"module": "tests.unit.test_model_runner", "name": "MockSuccessAnnotationModel"},
            schema_id="test/valid",
        )
        step_config.schema_id = None  # type: ignore

        runner = ModelRunner(pipeline_config=[])
        runner.pipeline = [step_config]

        result = runner.run("/test_file.txt")

        assert len(result.annotations.model_dump(exclude_none=True)) == 1
