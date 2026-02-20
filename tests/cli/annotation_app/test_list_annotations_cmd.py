# tests/cli/record_app/test_list_annotations_cmd.py

import pytest
import typer
from unittest.mock import MagicMock
from typer.testing import CliRunner

from dorsal.cli.annotation_app.list_annotations_cmd import list_annotations
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


cli_app.command(name="list")(list_annotations)
runner = CliRunner()


@pytest.fixture
def mock_list_deps(mocker, mock_rich_console):
    mock_error_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_api_list = mocker.patch("dorsal.api.file.list_file_annotations")

    return {
        "api_list": mock_api_list,
        "error_console": mock_error_console,
    }


def test_list_annotations_success(mock_rich_console, mock_list_deps):
    mock_list_deps["api_list"].return_value = {
        "AudioTranscription": [
            {
                "id": "anno-123",
                "source": {"type": "Model", "id": "dorsalhub/whisper"},
                "date_modified": "2026-02-20T10:00:00Z",
            }
        ],
        "ImageClassification": [],
    }

    result = runner.invoke(cli_app, ["list", "fakehash123"])

    assert result.exit_code == 0
    mock_list_deps["api_list"].assert_called_with("fakehash123", mode="dict")

    # Check that Table was printed and the summary string
    calls = mock_rich_console.print.call_args_list
    assert any("Found 1 annotation(s) for file" in str(call.args[0]) for call in calls)


def test_list_annotations_empty(mock_rich_console, mock_list_deps):
    mock_list_deps["api_list"].return_value = {"AudioTranscription": []}

    result = runner.invoke(cli_app, ["list", "fakehash123"])

    assert result.exit_code == 0
    calls = mock_rich_console.print.call_args_list
    assert any("No multi-value annotations found" in str(call.args[0]) for call in calls)


def test_list_annotations_api_error(mock_list_deps):
    mock_list_deps["api_list"].side_effect = Exception("API Offline")

    result = runner.invoke(cli_app, ["list", "fakehash123"])

    assert result.exit_code != 0
    error_msg = str(mock_list_deps["error_console"].print.call_args.args[0])
    assert "Failed to fetch annotations" in error_msg
    assert "API Offline" in error_msg
