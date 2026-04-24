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
from typer.testing import CliRunner
from rich.panel import Panel

from dorsal.cli import app
from dorsal.common.cli import EXIT_CODE_ERROR

runner = CliRunner()


@pytest.fixture
def mock_compression_api(mocker, mock_rich_console):
    """Mocks the exact config API and CLI utilities used in the compression command."""

    mock_get_summary = mocker.patch("dorsal.api.config.get_config_summary")
    mock_get_summary.return_value = {
        "index_compression_enabled": True,
        "index_compression_mode": "zlib",
        "index_compression_level": 6,
    }

    mock_set = mocker.patch("dorsal.api.config.set_compression")

    mock_exit = mocker.patch("dorsal.common.cli.exit_cli", side_effect=SystemExit(EXIT_CODE_ERROR))

    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)

    return {
        "get_summary": mock_get_summary,
        "set": mock_set,
        "exit": mock_exit,
    }


def test_compression_index_view_settings(mock_compression_api, mock_rich_console):
    """Tests viewing the compression settings when no arguments are provided."""
    result = runner.invoke(app, ["index", "compression"])

    assert result.exit_code == 0

    mock_compression_api["get_summary"].assert_called_once()

    printed_objects = [args[0] for args, _ in mock_rich_console.print.call_args_list]
    assert any(isinstance(obj, Panel) and "Index Compression Settings" in str(obj.title) for obj in printed_objects)

    mock_compression_api["set"].assert_not_called()


def test_compression_index_set_project(mock_compression_api, mock_rich_console):
    """Tests setting the compression algorithm and level at the project scope."""
    result = runner.invoke(app, ["index", "compression", "--mode", "zstd", "--level", "10"])

    assert result.exit_code == 0
    mock_compression_api["set"].assert_called_once_with(mode="zstd", level=10, scope="project")

    printed_texts = [str(args[0]) for args, _ in mock_rich_console.print.call_args_list]
    assert any("settings updated in project config" in text for text in printed_texts)
    assert any("Algorithm: " in text and "zstd" in text for text in printed_texts)
    assert any("Level: " in text and "10" in text for text in printed_texts)


def test_compression_index_set_global_partial_args(mock_compression_api, mock_rich_console):
    """Tests setting only the mode at the global scope (leaving level as default/None)."""
    result = runner.invoke(app, ["index", "compression", "--mode", "zlib", "--global"])

    assert result.exit_code == 0
    mock_compression_api["set"].assert_called_once_with(mode="zlib", level=None, scope="global")

    printed_texts = [str(args[0]) for args, _ in mock_rich_console.print.call_args_list]
    assert any("settings updated in global config" in text for text in printed_texts)
    assert any("Algorithm: " in text and "zlib" in text for text in printed_texts)

    assert not any("Level: " in text for text in printed_texts if "✅" in text)


def test_compression_index_value_error_handling(mock_compression_api, mock_rich_console):
    """Tests that ValueError from set_compression is caught and handled via exit_cli."""
    mock_compression_api["set"].side_effect = ValueError("Invalid compression level '99'.")

    result = runner.invoke(app, ["index", "compression", "--level", "99"])

    assert result.exit_code == EXIT_CODE_ERROR
    mock_compression_api["exit"].assert_called_once_with(code=EXIT_CODE_ERROR)

    printed_texts = [str(args[0]) for args, _ in mock_rich_console.print.call_args_list]
    assert any("Validation Error:" in text and "Invalid compression level '99'." in text for text in printed_texts)


def test_compression_index_exception_handling(mock_compression_api):
    """Tests that generic exceptions are caught and passed to exit_cli with a message."""
    mock_compression_api["set"].side_effect = Exception("File write failed")

    result = runner.invoke(app, ["index", "compression", "--mode", "zlib"])

    assert result.exit_code == EXIT_CODE_ERROR
    mock_compression_api["exit"].assert_called_once_with(
        code=EXIT_CODE_ERROR, message="Failed to save settings: File write failed"
    )


def test_compression_index_view_settings_disabled(mock_compression_api, mock_rich_console):
    """Tests viewing the compression settings when compression is disabled."""
    from rich.panel import Panel
    from rich.console import Console

    mock_compression_api["get_summary"].return_value = {
        "index_compression_enabled": False,
        "index_compression_mode": "zlib",
        "index_compression_level": 6,
    }

    result = runner.invoke(app, ["index", "compression"])

    assert result.exit_code == 0
    mock_compression_api["get_summary"].assert_called_once()

    printed_objects = [args[0] for args, _ in mock_rich_console.print.call_args_list]
    panel = next((obj for obj in printed_objects if isinstance(obj, Panel)), None)

    assert panel is not None, "A Rich Panel was not printed."

    capture_console = Console(force_terminal=False)
    with capture_console.capture() as capture:
        capture_console.print(panel)

    rendered_text = capture.get()

    assert "Not Enabled" in rendered_text
