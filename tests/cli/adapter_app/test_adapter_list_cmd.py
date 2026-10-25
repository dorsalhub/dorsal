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
import pytest
import typer
from rich.box import ROUNDED
from rich.console import Console
from unittest.mock import MagicMock
from typer.testing import CliRunner

from dorsal.cli.adapter_app.list_cmd import list_adapters
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": None}


cli_app.command(name="list")(list_adapters)

runner = CliRunner()


def _render(renderable) -> str:
    """Renders a Rich renderable as plain text."""
    console = Console(record=True, width=120, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


@pytest.fixture
def mock_list_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `list` command.
    """
    mock_error_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_get_formats = mocker.patch("dorsal.api.adapters.get_supported_formats")

    return {
        "get_formats": mock_get_formats,
        "error_console": mock_error_console,
        "rich_console": mock_rich_console,
    }


def test_list_basic_success(mock_list_deps):
    """Tests a standard successful listing of formats which should output a table."""
    mock_list_deps["get_formats"].return_value = [
        ("srt", "SubRip Text (.srt) - A widely used, plaintext subtitle format."),
        ("vtt", "WebVTT (.vtt) - W3C standard web subtitle format."),
    ]

    result = runner.invoke(cli_app, ["list", "open/audio-transcription"])

    assert result.exit_code == 0, result.output

    mock_list_deps["get_formats"].assert_called_once_with("open/audio-transcription")

    assert _render(mock_list_deps["rich_console"].print.call_args.args[0]) == (
        "Supported formats for 'open/audio-transcription'\n"
        "Format  Description\n"
        "srt     SubRip Text (.srt) - A widely used, plaintext subtitle format.\n"
        "vtt     WebVTT (.vtt) - W3C standard web subtitle format.\n"
    )


def test_list_bordered(mock_list_deps):
    """Tests that the formats table uses the theme's box when borders are enabled."""
    mock_list_deps["get_formats"].return_value = [("srt", "SubRip")]
    bordered_app = typer.Typer()

    @bordered_app.callback()
    def bordered_callback(ctx: typer.Context):
        ctx.obj = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}

    bordered_app.command(name="list")(list_adapters)

    result = runner.invoke(bordered_app, ["list", "open/audio-transcription"])

    assert result.exit_code == 0, result.output
    output = _render(mock_list_deps["rich_console"].print.call_args.args[0])
    assert "│ srt    │ SubRip      │" in output


def test_list_empty_results(mock_list_deps):
    """Tests handling of a schema that exists but has no supported formats."""
    mock_list_deps["get_formats"].return_value = []

    result = runner.invoke(cli_app, ["list", "open/unknown-schema"])

    assert result.exit_code == 0

    warning_msg = str(mock_list_deps["error_console"].print.call_args.args[0])
    assert "No formats found for schema" in warning_msg
    assert "open/unknown-schema" in warning_msg


def test_list_missing_adapters_package(mock_list_deps):
    """Tests graceful failure when dorsalhub-adapters is missing, which raises a DorsalError."""
    mock_list_deps["get_formats"].side_effect = DorsalError("Please pip install dorsalhub-adapters to enable exports.")

    result = runner.invoke(cli_app, ["list", "open/audio-transcription"])

    assert result.exit_code != 0
    error_msg = str(mock_list_deps["error_console"].print.call_args.args[0])
    assert "Error:" in error_msg
    assert "Please pip install dorsalhub-adapters" in error_msg
