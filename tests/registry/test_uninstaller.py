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
from unittest.mock import MagicMock, patch

from dorsal.registry import uninstaller
from dorsal.common.exceptions import DorsalError


@pytest.fixture
def mock_subprocess():
    """Capture pip execution to prevent actual uninstallation."""
    with patch("subprocess.Popen") as mock_popen:
        process_mock = MagicMock()
        process_mock.stdout = []
        process_mock.wait.return_value = 0
        mock_popen.return_value = process_mock
        yield mock_popen


@pytest.fixture
def mock_resolve_target():
    """Mock target resolution to avoid hitting the registry/disk."""
    with patch("dorsal.registry.uninstaller.resolve_target") as mock_resolve:
        mock_resolve.return_value = ("package", "dorsal-test-model")
        yield mock_resolve


@pytest.fixture
def mock_unregister():
    """Mock the config modification."""
    with patch("dorsal.registry.uninstaller.unregister_model") as mock_unreg:
        yield mock_unreg


def test_run_pip_uninstall_success(mock_subprocess):
    """Verify it returns True when pip successfully removes a package."""
    process_mock = mock_subprocess.return_value
    process_mock.stdout = ["Uninstalling dorsal-test-model...\n", "Successfully uninstalled.\n"]
    process_mock.wait.return_value = 0

    result = uninstaller._run_pip_uninstall_streaming("dorsal-test-model")
    assert result is True


def test_run_pip_uninstall_skipped(mock_subprocess):
    """Verify it returns False if pip reports the package wasn't installed."""
    process_mock = mock_subprocess.return_value
    process_mock.stdout = ["Skipping dorsal-test-model as it is not installed.\n"]
    process_mock.wait.return_value = 0

    result = uninstaller._run_pip_uninstall_streaming("dorsal-test-model")
    assert result is False


def test_run_pip_uninstall_error(mock_subprocess):
    """Verify it returns False if the pip command fails entirely."""
    process_mock = mock_subprocess.return_value
    process_mock.stdout = ["Permission denied\n"]
    process_mock.wait.return_value = 1

    result = uninstaller._run_pip_uninstall_streaming("dorsal-test-model")
    assert result is False


def test_uninstall_target_full_success(mock_resolve_target, mock_unregister):
    """Happy path: Removes from config AND uninstalls from pip."""
    with patch("dorsal.registry.uninstaller._run_pip_uninstall_streaming", return_value=True):
        result = uninstaller.uninstall_model_target("target-string")

        mock_resolve_target.assert_called_once_with("target-string")
        mock_unregister.assert_called_once_with(package_name="dorsal-test-model", scope="project")
        assert result == "dorsal-test-model"


def test_uninstall_target_only_config(mock_resolve_target, mock_unregister):
    """Partial success: Removes from config, but pip says it's not installed."""
    with patch("dorsal.registry.uninstaller._run_pip_uninstall_streaming", return_value=False):
        result = uninstaller.uninstall_model_target("target-string")

        assert result == "dorsal-test-model"


def test_uninstall_target_only_pip(mock_resolve_target, mock_unregister):
    """Partial success: Config raises KeyError (not found), but pip uninstalls it."""
    mock_unregister.side_effect = KeyError("Not in config")

    with patch("dorsal.registry.uninstaller._run_pip_uninstall_streaming", return_value=True):
        result = uninstaller.uninstall_model_target("target-string")

        assert result == "dorsal-test-model"


def test_uninstall_target_nothing_done(mock_resolve_target, mock_unregister):
    """Failure: Missing from config AND missing from pip."""
    mock_unregister.side_effect = KeyError("Not in config")

    with patch("dorsal.registry.uninstaller._run_pip_uninstall_streaming", return_value=False):
        with pytest.raises(DorsalError) as exc:
            uninstaller.uninstall_model_target("ghost-model")

        assert "Could not find model" in str(exc.value)
        assert "in the project configuration OR installed" in str(exc.value)


def test_uninstall_target_config_error(mock_resolve_target, mock_unregister):
    """Failure: Unregistering raises a genuine exception (e.g. file permission error)."""
    mock_unregister.side_effect = Exception("Permission denied writing dorsal.toml")

    with pytest.raises(DorsalError) as exc:
        uninstaller.uninstall_model_target("target-string")

    assert "Failed to update dorsal configuration" in str(exc.value)
    assert "Permission denied writing dorsal.toml" in str(exc.value)
