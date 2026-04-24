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
import typer
from unittest.mock import MagicMock
from typer.testing import CliRunner
from rich.box import ROUNDED
from rich.table import Table

from dorsal.cli.hub_app.annotation_app.list_annotations_cmd import list_annotations
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = DUMMY_UI_CONTEXT


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


def test_list_annotations_narrow_console_and_borderless(mock_rich_console, mock_list_deps):
    from dorsal.cli.themes.borders import get_borders

    mock_rich_console.width = 110

    original_border = DUMMY_UI_CONTEXT["borders"]
    DUMMY_UI_CONTEXT["borders"] = get_borders("none")

    try:
        mock_list_deps["api_list"].return_value = {
            "AudioTranscription": [
                {
                    "id": "anno-123",
                    "source": {"type": "Model", "id": "dorsalhub/whisper"},
                    "date_modified": "2026-02-20T10:00:00Z",
                }
            ]
        }

        result = runner.invoke(cli_app, ["list", "fakehash123"])
        assert result.exit_code == 0

        tables = [call.args[0] for call in mock_rich_console.print.call_args_list if isinstance(call.args[0], Table)]
        if tables:
            assert tables[0].padding == (0, 1, 0, 1)

    finally:
        DUMMY_UI_CONTEXT["borders"] = original_border
