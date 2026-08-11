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

import importlib.metadata
import importlib.resources
import tomllib
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from dorsal.api.model import (
    run_or_install_model,
    _build_pipeline_step,
    get_model_help,
)
from dorsal.common.exceptions import DorsalError, DorsalConfigError
from dorsal.common.validators import CallableImportPath
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep


@pytest.fixture
def mock_resolve_target():
    with patch("dorsal.api.model.resolve_target") as mock:
        yield mock


@pytest.fixture
def mock_is_package_installed():
    with patch("dorsal.api.model.is_package_installed") as mock:
        yield mock


@pytest.fixture
def mock_install_model_target():
    with patch("dorsal.api.model.install_model_target") as mock:
        yield mock


@pytest.fixture
def mock_get_model_pipeline():
    with patch("dorsal.api.model.get_model_pipeline") as mock:
        yield mock


@pytest.fixture
def mock_resolve_pipeline_step_models():
    with patch("dorsal.api.model.resolve_pipeline_step_models") as mock:
        mock.return_value = (MagicMock(__name__="MockAnnotator"), MagicMock(__name__="MockValidator"))
        yield mock


@pytest.fixture
def mock_run_model():
    with patch("dorsal.api.model.run_model") as mock:
        yield mock


@pytest.fixture
def mock_entry_points():
    with patch("importlib.metadata.entry_points") as mock:
        yield mock


@pytest.fixture
def mock_resources_files():
    with patch("importlib.resources.files") as mock:
        yield mock


def test_run_or_install_model_happy_path_existing_pipeline(
    mock_resolve_target,
    mock_is_package_installed,
    mock_get_model_pipeline,
    mock_resolve_pipeline_step_models,
    mock_run_model,
    mock_install_model_target,
):
    """Test running a model that is installed and exists in the active pipeline."""
    target = "dorsal-whisper"
    file_path = "/tmp/audio.mp3"
    package_name = "dorsal-whisper"

    mock_resolve_target.return_value = ("package_name", package_name)
    mock_is_package_installed.return_value = True

    existing_step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="dorsal_whisper", name="WhisperModel"),
        schema_id="audio/transcription",
        package_name=package_name,
    )
    mock_get_model_pipeline.return_value = [existing_step]

    mock_annotator = MagicMock()
    mock_validator = MagicMock()
    mock_resolve_pipeline_step_models.return_value = (mock_annotator, mock_validator)

    run_or_install_model(target, file_path)

    mock_install_model_target.assert_not_called()

    mock_run_model.assert_called_once_with(
        annotation_model=mock_annotator,
        file_path=file_path,
        schema_id=existing_step.schema_id,
        schema_version=existing_step.schema_version,
        validation_model=mock_validator,
        dependencies=existing_step.dependencies,
        options=existing_step.options,
        ignore_linter_errors=existing_step.ignore_linter_errors,
        progress_callback=None,
    )


def test_run_or_install_model_auto_install_success(
    mock_resolve_target,
    mock_is_package_installed,
    mock_install_model_target,
    mock_get_model_pipeline,
    mock_entry_points,
    mock_resources_files,
    mock_resolve_pipeline_step_models,
    mock_run_model,
):
    """Test auto-installing a missing model, then constructing its step from metadata."""
    target = "dorsalhub/whisper"
    file_path = "/tmp/audio.wav"
    package_name = "dorsal-whisper"
    module_name = "dorsal_whisper"

    mock_resolve_target.return_value = ("registry_id", package_name)
    mock_is_package_installed.side_effect = [False, True]

    mock_get_model_pipeline.return_value = []

    mock_ep = MagicMock()
    mock_ep.dist.name = package_name
    mock_ep.module = module_name
    mock_entry_points.return_value = [mock_ep]

    mock_resource_path = MagicMock()
    mock_resource_path.is_file.return_value = True

    mock_resource_path.read_text.return_value = """
        model_class = "WhisperTranscriber"
        schema_id = "audio/transcription"
        dependencies = []
    """
    mock_resources_files.return_value.__truediv__.return_value = mock_resource_path

    run_or_install_model(target, file_path)

    mock_install_model_target.assert_called_once_with(target)

    call_args = mock_resolve_pipeline_step_models.call_args
    assert call_args is not None
    step_arg = call_args.args[0]

    assert isinstance(step_arg, ModelRunnerPipelineStep)
    assert step_arg.annotation_model.name == "WhisperTranscriber"
    assert step_arg.schema_id == "audio/transcription"
    assert step_arg.package_name == package_name

    mock_run_model.assert_called_once()


def test_run_or_install_model_runtime_options(
    mock_resolve_target,
    mock_is_package_installed,
    mock_get_model_pipeline,
    mock_resolve_pipeline_step_models,
    mock_run_model,
):
    """Test applying runtime options and linter flags."""
    target = "dorsal-ocr"
    mock_resolve_target.return_value = ("package_name", "dorsal-ocr")
    mock_is_package_installed.return_value = True

    base_step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="m", name="c"),
        schema_id="valid/schema-id",
        options={"lang": "en"},
        package_name="dorsal-ocr",
    )
    mock_get_model_pipeline.return_value = [base_step]

    run_or_install_model(target, "doc.pdf", options={"lang": "fr", "fast": True}, ignore_linter_errors=True)

    call_args = mock_run_model.call_args

    assert call_args.kwargs["options"] == {"lang": "fr", "fast": True}
    assert call_args.kwargs["ignore_linter_errors"] is True


def test_annotator_execution_failure_propagates(
    mock_resolve_target,
    mock_is_package_installed,
    mock_get_model_pipeline,
    mock_resolve_pipeline_step_models,
    mock_run_model,
):
    """Test that exceptions raised during annotation are propagated."""
    mock_resolve_target.return_value = ("package_name", "dorsal-fail")
    mock_is_package_installed.return_value = True

    step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="m", name="c"),
        schema_id="valid/schema-id",
        package_name="dorsal-fail",
    )
    mock_get_model_pipeline.return_value = [step]

    mock_run_model.side_effect = ValueError("Processing failed")

    with pytest.raises(ValueError, match="Processing failed"):
        run_or_install_model("dorsal-fail", "f.txt")


def test_run_or_install_model_auto_install_failure(
    mock_resolve_target, mock_is_package_installed, mock_install_model_target
):
    target = "owner/broken-repo"
    mock_resolve_target.return_value = ("registry_id", "dorsal-broken")
    mock_is_package_installed.return_value = False
    mock_install_model_target.side_effect = Exception("Network error")

    with pytest.raises(DorsalError, match="Failed to auto-install model"):
        run_or_install_model(target, "file.txt")


def test_construct_step_missing_entry_point(
    mock_resolve_target, mock_is_package_installed, mock_get_model_pipeline, mock_entry_points
):
    target = "dorsal-ghost"
    mock_resolve_target.return_value = ("package_name", "dorsal-ghost")
    mock_is_package_installed.return_value = True
    mock_get_model_pipeline.return_value = []

    mock_ep = MagicMock()
    mock_ep.dist.name = "other-package"
    mock_entry_points.return_value = [mock_ep]

    with pytest.raises(DorsalError, match="does not declare a 'dorsal.models' entry point"):
        run_or_install_model(target, "f.txt")


def test_load_package_config_missing_file(
    mock_resolve_target, mock_is_package_installed, mock_get_model_pipeline, mock_entry_points, mock_resources_files
):
    mock_resolve_target.return_value = ("package_name", "dorsal-pkg")
    mock_is_package_installed.return_value = True
    mock_get_model_pipeline.return_value = []

    mock_ep = MagicMock()
    mock_ep.dist.name = "dorsal-pkg"
    mock_ep.module = "dorsal_pkg"
    mock_entry_points.return_value = [mock_ep]

    mock_path = MagicMock()
    mock_path.is_file.return_value = False
    mock_resources_files.return_value.__truediv__.return_value = mock_path

    with pytest.raises(DorsalConfigError, match="missing 'model_config.toml'"):
        run_or_install_model("dorsal-pkg", "f.txt")


def test_build_pipeline_step_missing_schema_id():
    """Test that a missing schema_id raises a DorsalConfigError."""
    config = {"model_class": "MyModel"}
    with pytest.raises(DorsalConfigError, match="missing required field 'schema_id'"):
        _build_pipeline_step(config, "my_module", "my_pkg")


def test_build_pipeline_step_options_parsing():
    """Test the parsing of different dictionary structures in raw_options."""
    config = {
        "model_class": "MyModel",
        "schema_id": "test/schema",
        "options": {
            "flat_val": "value",
            "dict_with_default": {"default": 42, "help": "number"},
            "dict_no_default": {"help": "just help text"},
        },
    }
    step = _build_pipeline_step(config, "my_module", "my_pkg")
    assert step.schema_id == "test/schema"
    assert step.annotation_model.name == "MyModel"


@patch("dorsal.api.model.ModelRunnerPipelineStep")
def test_build_pipeline_step_exception(mock_step_class):
    """Test that construction exceptions (e.g. ValidationError) are wrapped in DorsalError."""
    mock_step_class.side_effect = ValueError("Pydantic validation failed")
    config = {"model_class": "MyModel", "schema_id": "test/schema"}

    with pytest.raises(DorsalError, match="Failed to construct pipeline step for 'my_pkg'"):
        _build_pipeline_step(config, "my_module", "my_pkg")


@patch("dorsal.api.model.resolve_target")
def test_get_model_help_resolve_error(mock_resolve):
    """Test get_model_help handles resolution errors correctly."""
    mock_resolve.side_effect = DorsalError("Target not found")

    res = get_model_help("bad-target")
    assert res["status"] == "error"
    assert res["error"] == "Target not found"


@patch("dorsal.api.model.resolve_target")
@patch("dorsal.api.model.is_package_installed")
def test_get_model_help_not_installed(mock_installed, mock_resolve):
    """Test get_model_help when the package is resolved but not installed."""
    mock_resolve.return_value = ("package_name", "my-pkg")
    mock_installed.return_value = False

    res = get_model_help("my-pkg")
    assert res["status"] == "not_installed"
    assert res["package_name"] == "my-pkg"


@patch("dorsal.api.model.resolve_target")
@patch("dorsal.api.model.is_package_installed")
@patch("dorsal.api.model._resolve_module_from_package")
def test_get_model_help_config_error(mock_mod, mock_installed, mock_resolve):
    """Test get_model_help when the configuration file fails to load."""
    mock_resolve.return_value = ("package_name", "my-pkg")
    mock_installed.return_value = True
    mock_mod.side_effect = DorsalConfigError("Missing module")

    res = get_model_help("my-pkg")
    assert res["status"] == "config_error"
    assert "Missing module" in res["error"]


@patch("dorsal.api.model.resolve_target")
@patch("dorsal.api.model.is_package_installed")
@patch("dorsal.api.model._resolve_module_from_package")
@patch("dorsal.api.model._load_package_config")
def test_get_model_help_success(mock_load, mock_mod, mock_installed, mock_resolve):
    """Test get_model_help properly normalizes flat vs nested configuration dictionaries."""
    mock_resolve.return_value = ("package_name", "my-pkg")
    mock_installed.return_value = True
    mock_mod.return_value = "my_module"

    mock_load.return_value = {
        "model_class": "MyModel",
        "options": {
            "flat_option": 10,
            "dict_option": {"default": 20, "help": "a number"},
            "dict_no_default": {"help": "no default provided"},
        },
    }

    res = get_model_help("my-pkg")

    assert res["status"] == "success"
    assert res["options"]["flat_option"]["default"] == 10
    assert res["options"]["dict_option"]["default"] == 20
    assert res["options"]["dict_option"]["help"] == "a number"
    assert res["options"]["dict_no_default"]["default"] == ""
    assert res["options"]["dict_no_default"]["help"] == "no default provided"
