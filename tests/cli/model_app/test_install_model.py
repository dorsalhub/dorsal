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

from unittest.mock import MagicMock
import pytest

import typer
from typer.testing import CliRunner
from rich.box import ROUNDED

from dorsal.cli.model_app.install_model_cmd import install_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError
from dorsal.api.model import ModelTargetResolution, ModelMetadata

cli_app = typer.Typer()

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = DUMMY_UI_CONTEXT


cli_app.command(name="install")(install_model)

runner = CliRunner()


@pytest.fixture
def mock_install_cmd(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `install_model` command.
    """
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_rich_console)

    mock_prepare = mocker.patch("dorsal.api.model.prepare_model_target")

    mock_resolution = ModelTargetResolution(
        target="dorsal/gpt-neo",
        strategy="registry_id",
        metadata=ModelMetadata(is_official=True, is_verified=True, description="Mocked model."),
    )
    mock_prepare.return_value = mock_resolution

    mock_installer = mocker.patch("dorsal.api.model.install_model")
    mock_installer.return_value = "dorsal-gpt-neo"

    mock_check = mocker.patch("dorsal.cli.model_app.checks.check_and_confirm_model_install")

    return {
        "prepare": mock_prepare,
        "installer": mock_installer,
        "check": mock_check,
        "resolution": mock_resolution,
    }


def test_install_model_basic_success(mock_rich_console, mock_install_cmd):
    """Tests a standard installation where the user confirms the prompt."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo"])

    assert result.exit_code == 0, result.output

    mock_install_cmd["prepare"].assert_called_once_with("dorsal/gpt-neo")
    mock_install_cmd["check"].assert_called_once()
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="project", force_reinstall=False)

    assert mock_rich_console.print.called
    assert "Successfully installed" in str(mock_rich_console.print.call_args_list[-1].args[0].renderable)


def test_install_model_interactive_decline(mock_rich_console, mock_install_cmd):
    """Tests that declining the confirmation prompt aborts the installation."""
    mock_install_cmd["check"].side_effect = typer.Exit(0)

    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo"])

    assert result.exit_code == 0
    mock_install_cmd["installer"].assert_not_called()


def test_install_model_yes_flag(mock_install_cmd):
    """Tests that --yes skips the confirmation prompt."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code == 0, result.output
    call_args = mock_install_cmd["check"].call_args
    assert call_args.kwargs.get("yes") is True
    mock_install_cmd["installer"].assert_called_once()


def test_install_model_global_flag(mock_install_cmd):
    """Tests that --global passes the correct scope to the installer."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--global", "--yes"])

    assert result.exit_code == 0, result.output
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="global", force_reinstall=False)


def test_install_model_force_flag(mock_install_cmd):
    """Tests that --force-reinstall passes force_reinstall=True and skips confirmation."""
    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--force-reinstall"])

    assert result.exit_code == 0, result.output
    call_args = mock_install_cmd["check"].call_args
    assert call_args.kwargs.get("force") is True
    mock_install_cmd["installer"].assert_called_once_with("dorsal/gpt-neo", scope="project", force_reinstall=True)


def test_install_model_registry_not_found(mock_rich_console, mock_install_cmd):
    """Tests handling of a 404 from the registry."""
    mock_install_cmd["prepare"].return_value = ModelTargetResolution(
        target="dorsal/missing-model",
        strategy="error",
        error_message="Model 'dorsal/missing-model' not found in registry.",
    )

    result = runner.invoke(cli_app, ["install", "dorsal/missing-model"])

    assert result.exit_code != 0
    assert mock_rich_console.print.called
    assert "not found in registry" in str(mock_rich_console.print.call_args[0][0])


def test_install_model_install_failure(mock_rich_console, mock_install_cmd):
    """Tests that installer exceptions are caught and reported."""
    mock_install_cmd["installer"].side_effect = DorsalError("Pip failed")

    result = runner.invoke(cli_app, ["install", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code != 0
    assert mock_rich_console.print.called
    assert "Install Failed" in str(mock_rich_console.print.call_args[0][0])
    assert "Pip failed" in str(mock_rich_console.print.call_args[0][0])
