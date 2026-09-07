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

from dorsal.cli.model_app.info_model_cmd import info_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.api.model import ModelTargetResolution, ModelMetadata
from dorsal.common.exceptions import DorsalError

cli_app = typer.Typer()

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = DUMMY_UI_CONTEXT


cli_app.command(name="info")(info_model)

runner = CliRunner()


@pytest.fixture
def mock_info_cmd(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `info_model` command.
    """
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)

    mock_exit_cli = mocker.patch("dorsal.cli.model_app.info_model_cmd.exit_cli", side_effect=typer.Exit(1))

    mock_prepare = mocker.patch("dorsal.api.model.prepare_model_target")
    mock_resolution = ModelTargetResolution(
        target="dorsalhub/receipt-scanner",
        strategy="registry_id",
        metadata=ModelMetadata(
            is_official=True,
            is_verified=True,
            description="Extracts data from receipts.",
            url="https://dorsalhub.com/receipt-scanner",
            source_url="https://github.com/dorsalhub/receipt-scanner",
        ),
    )
    mock_prepare.return_value = mock_resolution

    mock_get_help = mocker.patch("dorsal.api.model.get_model_help")
    mock_get_help.return_value = {
        "model_id": "dorsalhub/receipt-scanner",
        "model_version": "1.2.0",
        "class_description": "ReceiptScanner default fallback description",
        "package_name": "receipt-scanner",
    }

    mock_render_panel = mocker.patch("dorsal.cli.model_app.info_model_cmd.render_model_help_panel")
    mock_render_panel.return_value = None

    return {
        "prepare": mock_prepare,
        "get_help": mock_get_help,
        "render_panel": mock_render_panel,
        "resolution": mock_resolution,
        "exit_cli": mock_exit_cli,
    }


def test_info_model_basic_success(mock_rich_console, mock_info_cmd):
    """Tests a standard info lookup displaying model metadata and usage."""
    result = runner.invoke(cli_app, ["info", "dorsalhub/receipt-scanner"])

    assert result.exit_code == 0, result.output

    mock_info_cmd["prepare"].assert_called_once_with("dorsalhub/receipt-scanner")
    mock_info_cmd["get_help"].assert_called_once_with(target="dorsalhub/receipt-scanner")
    mock_info_cmd["render_panel"].assert_called_once()

    assert mock_rich_console.print.called

    panel = mock_rich_console.print.call_args_list[0].args[0]
    rendered_text = str(panel.renderable)

    assert "dorsalhub/receipt-scanner (v1.2.0)" in rendered_text
    assert "Extracts data from receipts." in rendered_text
    assert "https://dorsalhub.com/receipt-scanner" in rendered_text
    assert "https://github.com/dorsalhub/receipt-scanner" in rendered_text
    assert "dorsal model run dorsalhub/receipt-scanner ./path/to/file" in rendered_text


def test_info_model_resolution_error(mock_rich_console, mock_info_cmd):
    """Tests handling when the model target cannot be resolved (error strategy)."""
    mock_info_cmd["prepare"].return_value = ModelTargetResolution(
        target="missing-model",
        strategy="error",
        error_message="Model 'missing-model' not found in registry.",
    )

    runner.invoke(cli_app, ["info", "missing-model"])

    assert mock_info_cmd["exit_cli"].called

    assert mock_rich_console.print.called

    error_output = str(mock_rich_console.print.call_args_list[0].args[0])
    assert "Error:" in error_output
    assert "Model 'missing-model' not found in registry." in error_output


def test_info_model_fallback_description(mock_rich_console, mock_info_cmd):
    """Tests that class_description is used if metadata description is missing."""
    mock_info_cmd["resolution"].metadata.description = None

    result = runner.invoke(cli_app, ["info", "dorsalhub/receipt-scanner"])

    assert result.exit_code == 0

    panel = mock_rich_console.print.call_args_list[0].args[0]
    rendered_text = str(panel.renderable)

    assert "ReceiptScanner default fallback description" in rendered_text


def test_info_model_options_panel_rendered(mock_rich_console, mock_info_cmd):
    """Tests that an additional options panel is printed if returned by render_model_help_panel."""
    mock_options_panel = MagicMock()
    mock_info_cmd["render_panel"].return_value = mock_options_panel

    result = runner.invoke(cli_app, ["info", "dorsalhub/receipt-scanner"])

    assert result.exit_code == 0

    print_calls = mock_rich_console.print.call_args_list
    assert len(print_calls) >= 3
    assert print_calls[-1].args[0] == mock_options_panel
