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

import tomllib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dorsal.api.model import (
    prepare_model_target,
    run_or_install_model,
    install_model,
    uninstall_model,
    init_model_project,
    _build_pipeline_step,
    _find_pipeline_step_by_target,
    get_model_help,
    ModelTargetResolution,
)
from dorsal.common.exceptions import DorsalError, DorsalConfigError, AuthError, NotFoundError
from dorsal.common.validators import CallableImportPath
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep


@pytest.fixture
def mock_prepare_model_target():
    with patch("dorsal.api.model.prepare_model_target") as mock:
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
def mock_install_model_target():
    with patch("dorsal.api.model.install_model_target") as mock:
        yield mock


@pytest.fixture
def mock_entry_points():
    with patch("importlib.metadata.entry_points") as mock:
        yield mock


@pytest.fixture
def mock_resources_files():
    with patch("importlib.resources.files") as mock:
        yield mock


@patch("dorsal.api.model.get_model_pipeline")
def test_prepare_model_target_pipeline(mock_pipeline):
    step = MagicMock()
    step.annotation_model.name = "BuiltInModel"
    step.package_name = "dorsal-builtin"
    mock_pipeline.return_value = [step]

    res = prepare_model_target("BuiltInModel")
    assert res.strategy == "pipeline"
    assert res.is_installed is True
    assert res.package_name == "dorsal-builtin"


@patch("dorsal.api.model.get_model_pipeline")
@patch("dorsal.api.model.resolve_target")
@patch("dorsal.api.model.is_package_installed")
@patch("dorsal.api.model.get_shared_dorsal_client")
def test_prepare_model_target_registry(mock_client, mock_installed, mock_resolve, mock_pipeline):
    mock_pipeline.return_value = []
    mock_resolve.return_value = ("registry_id", "my-pkg")
    mock_installed.return_value = False

    mock_reg_data = MagicMock()
    mock_reg_data.install_url = "git+https://github.com/a/b.git@abc"
    mock_reg_data.description = "Test description"
    mock_reg_data.namespace = "dorsalhub"
    mock_reg_data.name = "whisper"
    mock_reg_data.is_verified = True
    mock_reg_data.is_official = False
    mock_reg_data.created_at = None
    mock_client.return_value.get_registry_model.return_value = mock_reg_data

    res = prepare_model_target("dorsalhub/whisper")
    assert res.strategy == "registry_id"
    assert res.is_installed is False
    assert res.package_name == "my-pkg"
    assert res.metadata is not None
    assert res.metadata.is_verified is True
    assert res.metadata.source_url == "https://github.com/a/b.git"


@patch("dorsal.api.model.get_shared_dorsal_client")
@patch("dorsal.api.model.resolve_target")
@patch("dorsal.api.model.get_model_pipeline")
def test_prepare_model_target_registry_exceptions(mock_pipeline, mock_resolve, mock_client):
    mock_pipeline.return_value = []
    mock_resolve.return_value = ("registry_id", "my-pkg")

    mock_client.return_value.get_registry_model.side_effect = AuthError("Bad token")
    res = prepare_model_target("dorsalhub/whisper")
    assert res.strategy == "error"
    assert "Bad token" in res.error_message

    mock_client.return_value.get_registry_model.side_effect = Exception("Boom")
    res = prepare_model_target("dorsalhub/whisper")
    assert res.strategy == "error"
    assert "Registry connection failed: Boom" in res.error_message


@patch("dorsal.api.model.get_model_pipeline")
def test_prepare_model_target_local_path(mock_pipeline):
    mock_pipeline.return_value = []
    res = prepare_model_target("./local-model-dir")
    assert res.strategy == "local_path"
    assert res.is_installed is False


@patch("dorsal.api.model.is_package_installed")
@patch("dorsal.api.model.get_model_pipeline")
def test_prepare_model_target_package_and_fallback(mock_pipeline, mock_is_installed):
    mock_pipeline.return_value = []
    mock_is_installed.return_value = True
    res = prepare_model_target("some-package")
    assert res.strategy == "package"
    assert res.package_name == "some-package"

    mock_is_installed.return_value = False
    res = prepare_model_target("some-package")
    assert res.strategy == "error"
    assert "is not installed" in res.error_message


@patch("dorsal.api.model.create_new_annotation_model_project")
def test_init_model_project(mock_create):
    mock_create.return_value = "success"
    assert init_model_project("MyModel", None) == "success"
    mock_create.assert_called_once_with(name="MyModel", target_dir=None)


@patch("dorsal.api.model.prepare_model_target")
@patch("dorsal.api.model.install_model_target")
def test_install_model_wrapper(mock_install_target, mock_prepare):

    mock_prepare.return_value = ModelTargetResolution(target="foo/bar", strategy="registry_id")
    mock_install_target.return_value = "dorsal-bar"
    assert install_model("foo/bar") == "dorsal-bar"

    mock_prepare.return_value = ModelTargetResolution(target="BuiltIn", strategy="pipeline")
    with pytest.raises(DorsalError, match="built-in core model"):
        install_model("BuiltIn")

    mock_prepare.return_value = ModelTargetResolution(target="foo", strategy="error", error_message="Network Fail")
    with pytest.raises(DorsalError, match="Network Fail"):
        install_model("foo")

    mock_prepare.return_value = ModelTargetResolution(target="foo", strategy="error", error_message=None)
    with pytest.raises(DorsalError, match="Failed to resolve target 'foo'."):
        install_model("foo")


@patch("dorsal.api.model.prepare_model_target")
@patch("dorsal.api.model.uninstall_model_target")
def test_uninstall_model_wrapper(mock_uninstall_target, mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(target="foo/bar", strategy="registry_id")
    mock_uninstall_target.return_value = "dorsal-bar"
    assert uninstall_model("foo/bar") == "dorsal-bar"

    mock_prepare.return_value = ModelTargetResolution(target="BuiltIn", strategy="pipeline")
    with pytest.raises(DorsalError, match="Use 'dorsal config pipeline remove'"):
        uninstall_model("BuiltIn")

    mock_prepare.return_value = ModelTargetResolution(target="foo", strategy="error", error_message=None)
    with pytest.raises(DorsalError, match="Failed to resolve target 'foo'."):
        uninstall_model("foo")


def test_run_or_install_model_happy_path_existing_pipeline(
    mock_prepare_model_target,
    mock_get_model_pipeline,
    mock_resolve_pipeline_step_models,
    mock_run_model,
    mock_install_model_target,
):
    target = "WhisperModel"
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="pipeline", package_name="dorsal-whisper", is_installed=True
    )

    existing_step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="dorsal_whisper", name="WhisperModel"),
        schema_id="audio/transcription",
        package_name="dorsal-whisper",
    )
    mock_get_model_pipeline.return_value = [existing_step]

    mock_annotator = MagicMock()
    mock_validator = MagicMock()
    mock_resolve_pipeline_step_models.return_value = (mock_annotator, mock_validator)

    run_or_install_model(target, "/tmp/audio.mp3")

    mock_install_model_target.assert_not_called()
    mock_run_model.assert_called_once()


def test_run_or_install_model_auto_install_success(
    mock_prepare_model_target,
    mock_install_model_target,
    mock_entry_points,
    mock_resources_files,
    mock_resolve_pipeline_step_models,
    mock_run_model,
):
    target = "dorsalhub/whisper"
    package_name = "dorsal-whisper"

    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="registry_id", package_name=package_name, is_installed=False
    )

    mock_install_model_target.return_value = package_name

    mock_ep = MagicMock()
    mock_ep.dist.name = package_name
    mock_ep.module = "dorsal_whisper"
    mock_entry_points.return_value = [mock_ep]

    mock_resource_path = MagicMock()
    mock_resource_path.is_file.return_value = True
    mock_resource_path.read_text.return_value = """
        model_class = "WhisperTranscriber"
        schema_id = "audio/transcription"
        dependencies = []
    """
    mock_resources_files.return_value.__truediv__.return_value = mock_resource_path

    run_or_install_model(target, "file.wav")

    mock_install_model_target.assert_called_once_with(target)
    mock_run_model.assert_called_once()


def test_run_or_install_model_runtime_options(
    mock_prepare_model_target,
    mock_get_model_pipeline,
    mock_resolve_pipeline_step_models,
    mock_run_model,
):
    target = "MyOCR"
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="pipeline", package_name="dorsal-ocr", is_installed=True
    )

    base_step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="m", name="MyOCR"),
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
    mock_prepare_model_target, mock_get_model_pipeline, mock_resolve_pipeline_step_models, mock_run_model
):
    target = "FailModel"
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="pipeline", package_name="dorsal-fail", is_installed=True
    )
    step = ModelRunnerPipelineStep(
        annotation_model=CallableImportPath(module="m", name="FailModel"), schema_id="valid/schema-id"
    )
    mock_get_model_pipeline.return_value = [step]
    mock_run_model.side_effect = ValueError("Processing failed")

    with pytest.raises(ValueError, match="Processing failed"):
        run_or_install_model(target, "f.txt")


def test_run_or_install_model_auto_install_failure(mock_prepare_model_target, mock_install_model_target):
    target = "owner/broken-repo"
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="registry_id", package_name="dorsal-broken", is_installed=False
    )
    mock_install_model_target.side_effect = DorsalError("Network error")

    with pytest.raises(DorsalError, match="Network error"):
        run_or_install_model(target, "file.txt")


def test_run_or_install_model_cannot_autoinstall(mock_prepare_model_target):
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target="my-pkg", strategy="package", is_installed=False
    )
    with pytest.raises(DorsalError, match="cannot be auto-installed"):
        run_or_install_model("my-pkg", "f.txt")


def test_construct_step_missing_entry_point(mock_prepare_model_target, mock_entry_points):
    target = "dorsal-ghost"
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target=target, strategy="package", package_name="dorsal-ghost", is_installed=True
    )

    mock_ep = MagicMock()
    mock_ep.dist.name = "other-package"
    mock_entry_points.return_value = [mock_ep]

    with pytest.raises(DorsalError, match="does not declare a 'dorsal.models' entry point"):
        run_or_install_model(target, "f.txt")


def test_load_package_config_missing_file(mock_prepare_model_target, mock_entry_points, mock_resources_files):
    mock_prepare_model_target.return_value = ModelTargetResolution(
        target="dorsal-pkg", strategy="package", package_name="dorsal-pkg", is_installed=True
    )
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
    config = {"model_class": "MyModel"}
    with pytest.raises(DorsalConfigError, match="missing required field 'schema_id'"):
        _build_pipeline_step(config, "my_module", "my_pkg")


def test_build_pipeline_step_options_parsing():
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
    assert step.options == {"flat_val": "value", "dict_with_default": 42, "dict_no_default": {"help": "just help text"}}


@patch("dorsal.api.model.get_model_pipeline")
def test_find_pipeline_step_by_target(mock_pipeline):
    step1 = MagicMock()
    step1.annotation_model.name = "ModelOne"
    step1.package_name = "pkg-one"

    step2 = MagicMock()
    step2.annotation_model.name = "ModelTwo"
    step2.package_name = "pkg-two"

    mock_pipeline.return_value = [step1, step2]

    assert _find_pipeline_step_by_target("ModelOne") == step1
    assert _find_pipeline_step_by_target("pkg-two") == step2
    assert _find_pipeline_step_by_target("Missing") is None


@patch("dorsal.api.model.prepare_model_target")
def test_get_model_help_resolve_error(mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(
        target="bad-target", strategy="error", error_message="Target not found"
    )
    res = get_model_help("bad-target")
    assert res["status"] == "error"
    assert res["error"] == "Target not found"


@patch("dorsal.api.model.prepare_model_target")
def test_get_model_help_not_installed(mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(
        target="my-pkg", strategy="registry_id", package_name="my-pkg", is_installed=False
    )
    res = get_model_help("my-pkg")
    assert res["status"] == "not_installed"
    assert res["package_name"] == "my-pkg"


@patch("dorsal.api.model.prepare_model_target")
def test_get_model_help_no_package_name(mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(
        target="tgt", strategy="package", is_installed=True, package_name=None
    )
    res = get_model_help("tgt")
    assert res["status"] == "error"
    assert "No package name found" in res["error"]


@patch("dorsal.api.model.prepare_model_target")
@patch("dorsal.api.model.get_model_pipeline")
@patch("dorsal.api.model._load_package_config")
def test_get_model_help_pipeline_branches(mock_load, mock_pipeline, mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(target="Missing", strategy="pipeline", is_installed=True)
    mock_pipeline.return_value = []
    res = get_model_help("Missing")
    assert res["status"] == "error"
    assert "Failed to retrieve pipeline step" in res["error"]

    mock_prepare.return_value = ModelTargetResolution(target="Found", strategy="pipeline", is_installed=True)
    step = MagicMock()
    step.annotation_model.name = "Found"
    step.package_name = "pkg"
    step.options = {"my_opt": 1}
    mock_pipeline.return_value = [step]

    mock_load.side_effect = DorsalConfigError("No config")
    res = get_model_help("Found")
    assert res["status"] == "success"
    assert res["options"]["my_opt"]["default"] == 1


@patch("dorsal.api.model.prepare_model_target")
@patch("dorsal.api.model._resolve_module_from_package")
def test_get_model_help_config_error(mock_mod, mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(
        target="my-pkg", strategy="registry_id", package_name="my-pkg", is_installed=True
    )
    mock_mod.side_effect = DorsalConfigError("Missing module")

    res = get_model_help("my-pkg")
    assert res["status"] == "config_error"
    assert "Missing module" in res["error"]


@patch("dorsal.api.model.prepare_model_target")
@patch("dorsal.api.model._resolve_module_from_package")
@patch("dorsal.api.model._load_package_config")
def test_get_model_help_success(mock_load, mock_mod, mock_prepare):
    mock_prepare.return_value = ModelTargetResolution(
        target="my-pkg", strategy="registry_id", package_name="my-pkg", is_installed=True
    )
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
    options = res["options"]
    assert options["flat_option"]["default"] == 10
    assert options["dict_no_default"]["default"] is None
