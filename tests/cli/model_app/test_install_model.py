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

import datetime
from unittest.mock import MagicMock
import pytest
import typer
from typer.testing import CliRunner

# --- Application Imports ---
from dorsal.cli.model_app.install_model_cmd import install_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError, NotFoundError

# Create a test app
cli_app = typer.Typer()


# Define a callback to ensure ctx.obj is populated reliably
@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


# Register the command under test
cli_app.command(name="install")(install_model)

runner = CliRunner()


@pytest.fixture
def mock_install_cmd(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `install_model` command.
    """
    # 0. Mock the console in BOTH the common cli and the checks module
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.cli.model_app.checks.get_rich_console", return_value=mock_rich_console)

    # 1. Mock the upstream installer
    mock_installer = mocker.patch("dorsal.registry.installer.install_model_target")
    mock_installer.return_value = "dorsal-model-package"

    # 2. Mock the Registry Client
    # CRITICAL: We must patch 'get_shared_dorsal_client' in the 'checks' module
    # because it has already imported the real function.
    mock_get_client = mocker.patch("dorsal.cli.model_app.checks.get_shared_dorsal_client")
    mock_client_instance = mock_get_client.return_value

    # default registry data object
    mock_reg_data = MagicMock()
    mock_reg_data.namespace = "dorsal"
    mock_reg_data.name = "gpt-neo"
    mock_reg_data.is_official = True
    mock_reg_data.is_verified = True
    mock_reg_data.description = "A powerful mocked model."
    mock_reg_data.install_url = "git+https://github.com/dorsal/gpt-neo.git"
    mock_reg_data.created_at = datetime.datetime.now()
    mock_reg_data.package_name = "dorsal-gpt-neo"

    mock_client_instance.get_registry_model.return_value = mock_reg_data

    # 3. Mock Validators IN THE CHECKS MODULE
    # The checks module imports this function, so we must patch the reference there.
    mock_is_registry_id = mocker.patch("dorsal.cli.model_app.checks.is_registry_id", return_value=True)

    # 4. Mock shutil in the checks module
    mock_shutil_which = mocker.patch("dorsal.cli.model_app.checks.shutil.which", return_value="/usr/bin/git")

    # 5. Mock upstream Rich Confirm
    mock_confirm = mocker.patch("rich.prompt.Confirm.ask", return_value=True)

    return {
        "installer": mock_installer,
        "get_client": mock_get_client,
        "client": mock_client_instance,
        "reg_data": mock_reg_data,
        "is_registry_id": mock_is_registry_id,
        "shutil_which": mock_shutil_which,
        "confirm": mock_confirm,
    }


def test_install_model_basic_success(mock_rich_console, mock_install_cmd):
    """Tests a standard installation where the user confirms the prompt."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo"])

    assert result.exit_code == 0, result.output

    # Should check registry
    mock_install_cmd["client"].get_registry_model.assert_called_once_with("dorsal/gpt-neo")

    # Should ask for confirmation
    mock_install_cmd["confirm"].assert_called_once()

    # Should run installer
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="project", force_reinstall=False)

    # Should print success
    assert mock_rich_console.print.called
    assert "Successfully installed" in str(mock_rich_console.print.call_args_list[-1].args[0].renderable)


def test_install_model_interactive_decline(mock_rich_console, mock_install_cmd):
    """Tests that declining the confirmation prompt aborts the installation."""
    mock_install_cmd["confirm"].return_value = False

    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo"])

    assert result.exit_code == 0, result.output

    # Ensure "Cancelled" message was printed
    assert mock_rich_console.print.called
    assert "Cancelled" in str(mock_rich_console.print.call_args_list[-1].args[0])

    # Installer should NOT be called
    mock_install_cmd["installer"].assert_not_called()


def test_install_model_yes_flag(mock_install_cmd):
    """Tests that --yes skips the confirmation prompt."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code == 0, result.output
    mock_install_cmd["confirm"].assert_not_called()
    mock_install_cmd["installer"].assert_called_once()


def test_install_model_global_flag(mock_install_cmd):
    """Tests that --global passes the correct scope to the installer."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--global", "--yes"])

    assert result.exit_code == 0, result.output
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="global", force_reinstall=False)


def test_install_model_force_flag(mock_install_cmd):
    """Tests that --force passes force_reinstall=True and skips confirmation."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--force"])

    assert result.exit_code == 0, result.output
    mock_install_cmd["confirm"].assert_not_called()
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="project", force_reinstall=True)


def test_install_model_missing_git(mock_rich_console, mock_install_cmd):
    """Tests that missing git dependency causes an error exit."""
    # Simulate git missing from system
    mock_install_cmd["shutil_which"].return_value = None

    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo"])

    assert result.exit_code != 0

    assert mock_rich_console.print.called
    output_str = str(mock_rich_console.print.call_args_list[0].args[0].renderable)
    assert "requires Git to install" in output_str
    assert "Missing System Dependency" in str(mock_rich_console.print.call_args_list[0].args[0].title)


def test_install_model_registry_not_found(mock_rich_console, mock_install_cmd):
    """Tests handling of a 404 from the registry."""
    mock_install_cmd["client"].get_registry_model.side_effect = NotFoundError("Model not found")

    result = runner.invoke(cli_app, ["install", "dorsal/missing-model"])

    assert result.exit_code != 0
    assert mock_rich_console.print.called
    assert "Error: Model 'dorsal/missing-model' not found in registry" in str(mock_rich_console.print.call_args[0][0])


def test_install_model_unverified_warning(mock_rich_console, mock_install_cmd):
    """Tests that unverified models trigger a safety warning in the panel."""
    # Set model to unverified
    mock_install_cmd["reg_data"].is_official = False
    mock_install_cmd["reg_data"].is_verified = False

    runner.invoke(cli_app, ["install", "user/sketchy-model"])

    assert mock_rich_console.print.called

    # The FIRST print should be the Warning Panel
    panel = mock_rich_console.print.call_args_list[0].args[0]
    assert "Unverified" in str(panel.renderable)
    assert "Safety Warning" in str(panel.renderable)


def test_install_model_install_failure(mock_rich_console, mock_install_cmd):
    """Tests that installer exceptions are caught and reported."""
    mock_install_cmd["installer"].side_effect = DorsalError("Pip failed")

    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code != 0
    assert mock_rich_console.print.called
    assert "Install Failed" in str(mock_rich_console.print.call_args[0][0])
    assert "Pip failed" in str(mock_rich_console.print.call_args[0][0])
