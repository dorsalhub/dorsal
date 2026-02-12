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

import sys
import subprocess
import logging
from unittest.mock import MagicMock, patch, ANY
import pytest
import pathlib
import tomllib


from dorsal import AnnotationModel
from dorsal.registry import installer
from dorsal.common.exceptions import DorsalError, DorsalConfigError


@pytest.fixture
def mock_dorsal_client():
    """Mock the registry client to avoid network calls."""
    with patch("dorsal.registry.installer.get_shared_dorsal_client") as mock:
        client_instance = mock.return_value
        yield client_instance


@pytest.fixture
def mock_subprocess():
    """Capture pip execution to prevent actual installation."""
    with patch("subprocess.Popen") as mock_popen:
        process_mock = MagicMock()
        process_mock.stdout = []
        process_mock.wait.return_value = 0
        mock_popen.return_value = process_mock
        yield mock_popen


@pytest.fixture
def mock_register_model():
    """Mock the final step to verify what WOULD have been saved to config."""
    with patch("dorsal.registry.installer.register_model") as mock:
        yield mock


def test_get_local_pyproject_name(tmp_path):
    """Verify we can parse a name from a real TOML file."""
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "dorsal-super-model"\nversion = "0.1.0"', encoding="utf-8")

    name = installer._get_local_pyproject_name(tmp_path)
    assert name == "dorsal-super-model"


def test_get_local_pyproject_name_missing(tmp_path):
    """Verify it returns None if file is missing."""
    assert installer._get_local_pyproject_name(tmp_path) is None


def test_get_local_pyproject_name_malformed(tmp_path):
    """Verify it returns None (and logs debug) if TOML is invalid."""
    p = tmp_path / "pyproject.toml"
    p.write_text("INVALID TOML [ bla bla", encoding="utf-8")

    name = installer._get_local_pyproject_name(tmp_path)
    assert name is None


def test_load_packaged_model_config_success(tmp_path):
    """Verify loading a valid model_config.toml."""
    mock_files = MagicMock()
    mock_path = MagicMock()
    mock_path.is_file.return_value = True
    mock_path.read_text.return_value = 'model_class = "MyModel"\nschema_id = "test/schema"'

    mock_files.return_value.joinpath.return_value = mock_path

    mock_files.return_value.__truediv__.return_value = mock_path

    with patch("importlib.resources.files", mock_files):
        config = installer._load_packaged_model_config("dorsal_test_module")
        assert config["model_class"] == "MyModel"
        assert config["schema_id"] == "test/schema"


def test_load_packaged_model_config_missing_file():
    """Verify it returns empty dict if the file does not exist."""
    mock_files = MagicMock()
    mock_path = MagicMock()
    mock_path.is_file.return_value = False

    mock_files.return_value.__truediv__.return_value = mock_path

    with patch("importlib.resources.files", mock_files):
        config = installer._load_packaged_model_config("dorsal_test_module")
        assert config == {}


def test_load_packaged_model_config_import_error():
    """Verify it handles ImportError if the module doesn't exist."""
    with patch("importlib.resources.files", side_effect=ImportError("No module")):
        config = installer._load_packaged_model_config("non_existent_module")
        assert config == {}


def test_load_packaged_model_config_syntax_error():
    """Verify it raises DorsalConfigError on bad TOML syntax."""
    mock_files = MagicMock()
    mock_path = MagicMock()
    mock_path.is_file.return_value = True
    mock_path.read_text.return_value = "invalid_toml_key = "

    mock_files.return_value.__truediv__.return_value = mock_path

    with patch("importlib.resources.files", mock_files):
        with pytest.raises(DorsalConfigError) as exc:
            installer._load_packaged_model_config("dorsal_bad_toml")
        assert "Syntax error" in str(exc.value)


def test_ensure_git_installed_missing():
    """Verify DorsalError is raised if git is missing."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(DorsalError) as exc:
            installer._ensure_git_installed()
        assert "Git is not installed" in str(exc.value)


@pytest.mark.parametrize(
    "error_snippet, expected_msg",
    [
        ("Repository not found", "repository for 'target' could not be found"),
        ("Authentication failed", "Authentication failed while accessing"),
        ("No matching distribution found", "Could not find a package for 'target'"),
        ("Some random error", "Installation failed for 'target'"),
    ],
)
def test_pip_install_streaming_specific_errors(mock_subprocess, error_snippet, expected_msg):
    """Verify specific pip error messages are translated to specific DorsalErrors."""
    process_mock = mock_subprocess.return_value
    process_mock.wait.return_value = 1

    process_mock.stdout = [f"Err: {error_snippet}\n"]

    with pytest.raises(DorsalError) as exc:
        installer._run_pip_install_streaming(["pip", "install"], "target")

    assert expected_msg in str(exc.value)


def test_install_registry_target_success(mock_dorsal_client, mock_subprocess):
    """Full flow: Registry ID -> Resolve URL -> Run Pip -> Register"""
    valid_sha = "a" * 40
    mock_dorsal_client.get_registry_model.return_value.install_url = (
        f"git+https://github.com/dorsalhub/whisper.git@{valid_sha}"
    )
    mock_dorsal_client.get_registry_model.return_value.package_name = "dorsal-whisper"

    with patch("dorsal.registry.installer.install_model_from_package") as mock_install_pkg:
        installer.install_model_target("dorsalhub/whisper")

        mock_dorsal_client.get_registry_model.assert_called_with("dorsalhub/whisper")

        args, _ = mock_subprocess.call_args
        assert f"git+https://github.com/dorsalhub/whisper.git@{valid_sha}" in args[0]

        mock_install_pkg.assert_called_with("dorsal-whisper", scope="project")


def test_install_registry_target_ambiguous(tmp_path):
    """Fail if Registry ID matches a local directory."""

    (tmp_path / "dorsalhub").mkdir()
    (tmp_path / "dorsalhub" / "whisper").mkdir()

    with patch("os.getcwd", return_value=str(tmp_path)):
        with patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(DorsalError) as exc:
                installer.install_model_target("dorsalhub/whisper")
            assert "Ambiguous Target" in str(exc.value)


def test_install_local_target_no_pyproject(tmp_path):
    """Fail if local path exists but has no pyproject.toml."""
    local_dir = tmp_path / "my-model"
    local_dir.mkdir()

    with pytest.raises(DorsalError) as exc:
        installer.install_model_target(str(local_dir))
    assert "Could not determine package name" in str(exc.value)


def test_install_invalid_target_format():
    """Fail if target is neither a valid Registry ID nor a valid path."""
    with pytest.raises(DorsalError) as exc:
        installer.install_model_target("invalid_target_string")
    assert "Invalid install target" in str(exc.value)


def test_install_from_package_missing_config(mock_register_model):
    """Fail if model_config.toml is missing from the installed package."""
    mock_ep = MagicMock()
    mock_ep.name = "dorsal-broken"
    mock_ep.dist.name = "dorsal-broken"
    mock_ep.module = "dorsal_broken_module"

    mock_ep.load.return_value = MagicMock()

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        with patch("dorsal.registry.installer._load_packaged_model_config", return_value={}):
            with pytest.raises(DorsalError) as exc:
                installer.install_model_from_package("dorsal-broken")
            assert "Missing 'model_config.toml'" in str(exc.value)


def test_install_from_package_missing_model_class_key(mock_register_model):
    """Fail if config exists but lacks 'model_class'."""
    mock_ep = MagicMock()
    mock_ep.name = "dorsal-bad-config"
    mock_ep.dist.name = "dorsal-bad-config"
    mock_ep.module = "mod"
    mock_ep.load.return_value = MagicMock()

    bad_config = {"schema_id": "foo"}

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        with patch("dorsal.registry.installer._load_packaged_model_config", return_value=bad_config):
            with pytest.raises(DorsalError) as exc:
                installer.install_model_from_package("dorsal-bad-config")
            assert "Missing required key 'model_class'" in str(exc.value)


def test_install_from_package_attribute_error(mock_register_model):
    """Fail if 'model_class' points to a non-existent attribute in the module."""
    mock_ep = MagicMock()
    mock_ep.name = "dorsal-missing-attr"
    mock_ep.dist.name = "dorsal-missing-attr"
    mock_ep.module = "mod"

    mock_module = MagicMock(spec=[])
    mock_ep.load.return_value = mock_module

    config = {"model_class": "GhostClass"}

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        with patch("dorsal.registry.installer._load_packaged_model_config", return_value=config):
            with pytest.raises(DorsalError) as exc:
                installer.install_model_from_package("dorsal-missing-attr")
            assert "was not exported by module" in str(exc.value)


def test_install_model_from_package_success(mock_register_model):
    """
    Test the complex logic of extracting config from an installed package.
    """
    mock_ep = MagicMock()
    mock_ep.name = "dorsal-fake"
    mock_ep.dist.name = "dorsal-fake"
    mock_ep.module = "dorsal_fake_module"

    class FakeModel(AnnotationModel):
        id = "fake/model"
        version = "0.0.1"

        def main(self):
            pass

    mock_module = MagicMock()
    mock_module.MyModelClass = FakeModel
    mock_ep.load.return_value = mock_module

    fake_config = {
        "model_class": "MyModelClass",
        "schema_id": "open/specific",
        "dependencies": [{"type": "media_type", "include": ["image/png"]}],
    }

    with (
        patch("importlib.metadata.entry_points", return_value=[mock_ep]),
        patch("dorsal.registry.installer._load_packaged_model_config", return_value=fake_config),
    ):
        installer.install_model_from_package("dorsal-fake")

        mock_register_model.assert_called_once()
        call_kwargs = mock_register_model.call_args.kwargs

        assert call_kwargs["annotation_model"] == FakeModel
        assert call_kwargs["schema_id"] == "open/specific"

        deps = call_kwargs["dependencies"]
        assert len(deps) == 1
        assert deps[0].type == "media_type"


def test_install_from_package_missing_entry_point():
    """If the package installs but doesn't expose an entry point, fail."""
    with patch("importlib.metadata.entry_points", return_value=[]):
        with pytest.raises(DorsalError) as exc:
            installer.install_model_from_package("ghost-package")

        assert "does not expose a 'dorsal.models' entry point" in str(exc.value)
