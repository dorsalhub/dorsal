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

from dorsal.cli.model_app.uninstall_model_cmd import uninstall_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError
from dorsal.api.model import ModelTargetResolution

cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


cli_app.command(name="uninstall")(uninstall_model)

runner = CliRunner()


@pytest.fixture
def mock_uninstall_cmd(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `uninstall_model` command.
    """
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)

    mock_prepare = mocker.patch("dorsal.api.model.prepare_model_target")
    mock_prepare.return_value = ModelTargetResolution(target="dorsal/gpt-neo", strategy="registry_id")

    mock_uninstaller = mocker.patch("dorsal.api.model.uninstall_model")
    mock_uninstaller.return_value = "dorsal-gpt-neo"

    mock_confirm = mocker.patch("rich.prompt.Confirm.ask", return_value=True)

    return {
        "prepare": mock_prepare,
        "uninstaller": mock_uninstaller,
        "confirm": mock_confirm,
    }


def test_uninstall_model_interactive_success(mock_rich_console, mock_uninstall_cmd):
    """Tests a standard interactive uninstallation where the user confirms."""
    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo"])

    assert result.exit_code == 0, result.output

    mock_uninstall_cmd["confirm"].assert_called_once()
    mock_uninstall_cmd["uninstaller"].assert_called_once_with("dorsal/gpt-neo", scope="project")

    assert mock_rich_console.print.called
    panel = mock_rich_console.print.call_args_list[-1].args[0]
    assert "Successfully uninstalled" in panel.renderable
    assert "dorsal-gpt-neo" in panel.renderable
    assert "Uninstall Complete" in str(panel.title)


def test_uninstall_model_interactive_decline(mock_rich_console, mock_uninstall_cmd):
    """Tests that declining the confirmation prompt aborts the operation."""
    mock_uninstall_cmd["confirm"].return_value = False

    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo"])

    assert result.exit_code == 0, result.output
    assert "Cancelled" in str(mock_rich_console.print.call_args.args[0])

    mock_uninstall_cmd["uninstaller"].assert_not_called()


def test_uninstall_model_yes_flag(mock_uninstall_cmd):
    """Tests that --yes skips the confirmation prompt."""
    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code == 0, result.output
    mock_uninstall_cmd["confirm"].assert_not_called()
    mock_uninstall_cmd["uninstaller"].assert_called_once()


def test_uninstall_model_global_flag(mock_uninstall_cmd):
    """Tests that --global passes the correct scope to the uninstaller."""
    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo", "--global", "--yes"])

    assert result.exit_code == 0, result.output
    mock_uninstall_cmd["uninstaller"].assert_called_once_with("dorsal/gpt-neo", scope="global")


def test_uninstall_model_dorsal_error(mock_rich_console, mock_uninstall_cmd):
    """Tests handling of specific DorsalErrors (e.g., package not found)."""
    mock_uninstall_cmd["uninstaller"].side_effect = DorsalError("Package not installed.")

    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code != 0

    assert mock_rich_console.print.called
    output_str = str(mock_rich_console.print.call_args.args[0])
    assert "Uninstall Failed" in output_str
    assert "Package not installed" in output_str


def test_uninstall_model_unexpected_error(mock_rich_console, mock_uninstall_cmd):
    """Tests handling of generic unexpected exceptions."""
    mock_uninstall_cmd["uninstaller"].side_effect = Exception("Permission denied")

    result = runner.invoke(cli_app, ["uninstall", "dorsal/gpt-neo", "--yes"])

    assert result.exit_code != 0

    assert mock_rich_console.print.called
    output_str = str(mock_rich_console.print.call_args.args[0])
    assert "Unexpected Error" in output_str
    assert "Permission denied" in output_str


def test_uninstall_model_pipeline_error(mock_rich_console, mock_uninstall_cmd):
    """Tests that the CLI blocks uninstalling a core pipeline model."""
    mock_uninstall_cmd["prepare"].return_value = ModelTargetResolution(target="BuiltIn", strategy="pipeline")

    result = runner.invoke(cli_app, ["uninstall", "BuiltIn", "--yes"])

    assert result.exit_code != 0
    output_str = str(mock_rich_console.print.call_args.args[0])
    assert "built-in core model" in output_str
