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

import io
import pathlib
from unittest.mock import MagicMock
import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from dorsal.cli.model_app.init_model_cmd import init_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": None}


cli_app.command(name="init")(init_model)

runner = CliRunner()


def _render(renderable) -> str:
    """Renders a Rich renderable as plain text."""
    console = Console(record=True, width=120, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


@pytest.fixture
def mock_init_cmd(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `init_model` command.
    """
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)

    # FIX: Patch the true source of the API wrapper, since it is locally imported inside the command.
    mock_create_project = mocker.patch("dorsal.api.model.init_model_project")

    mock_result = MagicMock()
    mock_result.clean_name = "receipt-scanner"
    mock_result.path = pathlib.Path("/tmp/receipt-scanner")
    mock_create_project.return_value = mock_result

    return {
        "create_project": mock_create_project,
        "result": mock_result,
    }


def test_init_model_success_default_dir(mock_rich_console, mock_init_cmd):
    """Tests initializing a model in the current directory (default)."""
    result = runner.invoke(cli_app, ["init", "Receipt Scanner"])

    assert result.exit_code == 0, result.output

    mock_init_cmd["create_project"].assert_called_once_with(name="Receipt Scanner", target_dir=None)

    assert mock_rich_console.print.called
    assert _render(mock_rich_console.print.call_args.args[0]) == (
        "Model initialized\n"
        "  Created new model project: receipt-scanner\n"
        "\n"
        "  To install it for testing:\n"
        "    $ cd receipt-scanner\n"
        "    $ dorsal model install .\n"
    )


def test_init_model_success_explicit_dir(mock_rich_console, mock_init_cmd, tmp_path, monkeypatch):
    """Tests initializing a model with a specific target directory."""
    monkeypatch.chdir(tmp_path)
    target_path = pathlib.Path("my_projects")
    target_path.mkdir()

    result = runner.invoke(cli_app, ["init", "Receipt Scanner", str(target_path)])

    assert result.exit_code == 0, result.output

    args = mock_init_cmd["create_project"].call_args
    assert args.kwargs["name"] == "Receipt Scanner"
    assert args.kwargs["target_dir"].name == "my_projects"


def test_init_model_dorsal_error(mock_rich_console, mock_init_cmd, mock_error_console):
    """Tests handling of specific DorsalErrors (e.g., directory already exists)."""
    mock_init_cmd["create_project"].side_effect = DorsalError("Project directory already exists.")

    result = runner.invoke(cli_app, ["init", "Receipt Scanner"])

    assert result.exit_code != 0

    assert mock_error_console.print.called
    output_str = str(mock_error_console.print.call_args.args[0])
    assert "Failed to create project" in output_str
    assert "Project directory already exists" in output_str


def test_init_model_unexpected_error(mock_rich_console, mock_init_cmd, mock_error_console):
    """Tests handling of generic unexpected exceptions."""
    mock_init_cmd["create_project"].side_effect = Exception("Disk full")

    result = runner.invoke(cli_app, ["init", "Receipt Scanner"])

    assert result.exit_code != 0

    assert mock_error_console.print.called
    output_str = str(mock_error_console.print.call_args.args[0])
    assert "Unexpected error" in output_str
    assert "Disk full" in output_str
