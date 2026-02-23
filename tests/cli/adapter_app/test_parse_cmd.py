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

import json
import pathlib
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from dorsal.cli.adapter_app.parse_cmd import parse_adapter
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


cli_app.command(name="parse")(parse_adapter)

runner = CliRunner()


@pytest.fixture
def mock_parse_deps(mocker):
    """Mocks backend dependencies for the `adapter parse` command."""
    mock_rich_console = MagicMock()
    mock_error_console = MagicMock()

    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_parse_api = mocker.patch("dorsal.api.adapters.parse_file")
    mock_parse_api.return_value = {
        "producer": "mock-adapter",
        "text": "Hello world",
        "segments": [],
    }

    return {
        "parse_api": mock_parse_api,
        "rich_console": mock_rich_console,
        "error_console": mock_error_console,
    }


def test_parse_cmd_success(mock_parse_deps):
    """Tests standard successful file parsing and saving."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.srt")
        test_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello world", encoding="utf-8")

        result = runner.invoke(cli_app, ["parse", str(test_file), "open/audio-transcription", "srt"])

        assert result.exit_code == 0

        # Check that the API was called correctly
        mock_parse_deps["parse_api"].assert_called_once()
        kwargs = mock_parse_deps["parse_api"].call_args.kwargs
        assert kwargs["schema_id"] == "open/audio-transcription"
        assert kwargs["source_format"] == "srt"

        # Check standard out output
        printed_json = mock_parse_deps["rich_console"].print.call_args.args[0]
        data = json.loads(printed_json)
        assert data["schema_id"] == "open/audio-transcription"
        assert data["record"]["text"] == "Hello world"

        # Check auto-save functionality
        expected_save_path = pathlib.Path.cwd() / "test.dorsal.json"
        assert expected_save_path.exists()
        saved_data = json.loads(expected_save_path.read_text(encoding="utf-8"))
        assert saved_data["record"]["text"] == "Hello world"


def test_parse_cmd_with_options(mock_parse_deps):
    """Tests that CLI options are correctly inferred and threaded to the parser."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.txt")
        test_file.write_text("Hello world", encoding="utf-8")

        result = runner.invoke(
            cli_app,
            ["parse", str(test_file), "open/document-extraction", "txt", "--opt", "strict=true", "-o", "chunk=5"],
        )

        assert result.exit_code == 0

        # Verify options were parsed into correct types and passed to parse_file
        kwargs = mock_parse_deps["parse_api"].call_args.kwargs
        assert kwargs["strict"] is True
        assert kwargs["chunk"] == 5


def test_parse_cmd_no_save_flag(mock_parse_deps):
    """Tests that --no-save prevents file creation."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.vtt")
        test_file.write_text("WEBVTT\n\nHello", encoding="utf-8")

        result = runner.invoke(cli_app, ["parse", str(test_file), "open/audio-transcription", "vtt", "--no-save"])

        assert result.exit_code == 0

        # Verify no file was created
        expected_save_path = pathlib.Path.cwd() / "test.dorsal.json"
        assert not expected_save_path.exists()

        # The JSON should still be printed to stdout
        assert mock_parse_deps["rich_console"].print.called


def test_parse_cmd_missing_adapters(mock_parse_deps, mocker):
    """Tests handling of an environment missing the adapters package."""
    mock_parse_deps["parse_api"].side_effect = DorsalError("Please pip install dorsalhub-adapters to enable exports.")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.srt")
        test_file.write_text("mock content", encoding="utf-8")

        result = runner.invoke(cli_app, ["parse", str(test_file), "open/audio-transcription", "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_parse_deps["error_console"].print.call_args.args[0])
        assert "Parse Failed" in error_msg
        assert "dorsalhub-adapters" in error_msg


def test_parse_cmd_dorsal_error(mock_parse_deps):
    """Tests that specific parsing errors are caught and displayed nicely."""
    mock_parse_deps["parse_api"].side_effect = DorsalError("Failed to parse record from fake_format: unsupported")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.fake")
        test_file.write_text("mock content", encoding="utf-8")

        result = runner.invoke(cli_app, ["parse", str(test_file), "open/audio-transcription", "fake_format"])

        assert result.exit_code != 0
        error_msg = str(mock_parse_deps["error_console"].print.call_args.args[0])
        assert "unsupported" in error_msg
