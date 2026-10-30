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


def test_compression_index_view_settings(mock_compression_api, mock_rich_console, rendered):
    """Tests viewing the compression settings when no arguments are provided."""
    result = runner.invoke(app, ["index", "compression"])

    assert result.exit_code == 0

    mock_compression_api["get_summary"].assert_called_once()

    lines = rendered(mock_rich_console).splitlines()
    assert lines[:4] == ["Index compression settings", "  Status  Enabled", "  Mode    zlib", "  Level   6"]

    mock_compression_api["set"].assert_not_called()


def test_compression_index_set_project(mock_compression_api, mock_rich_console, rendered):
    """Tests setting the compression algorithm and level at the project scope."""
    result = runner.invoke(app, ["index", "compression", "--mode", "zstd", "--level", "10"])

    assert result.exit_code == 0
    mock_compression_api["set"].assert_called_once_with(mode="zstd", level=10, scope="project")

    lines = rendered(mock_rich_console).splitlines()
    assert lines[:3] == ["Index compression settings updated in project config", "  Algorithm  zstd", "  Level      10"]


def test_compression_index_set_global_partial_args(mock_compression_api, mock_rich_console, rendered):
    """Tests setting only the mode at the global scope (leaving level as default/None)."""
    result = runner.invoke(app, ["index", "compression", "--mode", "zlib", "--global"])

    assert result.exit_code == 0
    mock_compression_api["set"].assert_called_once_with(mode="zlib", level=None, scope="global")

    lines = rendered(mock_rich_console).splitlines()
    assert lines[:3] == ["Index compression settings updated in global config", "  Algorithm  zlib", ""]


def test_compression_index_value_error_handling(mock_compression_api, mock_rich_console, mock_error_console):
    """Tests that ValueError from set_compression is caught and handled via exit_cli."""
    mock_compression_api["set"].side_effect = ValueError("Invalid compression level '99'.")

    result = runner.invoke(app, ["index", "compression", "--level", "99"])

    assert result.exit_code == EXIT_CODE_ERROR
    mock_compression_api["exit"].assert_called_once_with(code=EXIT_CODE_ERROR)

    printed_texts = [str(args[0]) for args, _ in mock_error_console.print.call_args_list]
    assert any("Validation error:" in text and "Invalid compression level '99'." in text for text in printed_texts)


def test_compression_index_exception_handling(mock_compression_api):
    """Tests that generic exceptions are caught and passed to exit_cli with a message."""
    mock_compression_api["set"].side_effect = Exception("File write failed")

    result = runner.invoke(app, ["index", "compression", "--mode", "zlib"])

    assert result.exit_code == EXIT_CODE_ERROR
    mock_compression_api["exit"].assert_called_once_with(
        code=EXIT_CODE_ERROR, message="Failed to save settings: File write failed"
    )


def test_compression_index_view_settings_disabled(mock_compression_api, mock_rich_console, rendered):
    """Tests viewing the compression settings when compression is disabled."""
    mock_compression_api["get_summary"].return_value = {
        "index_compression_enabled": False,
        "index_compression_mode": "zlib",
        "index_compression_level": 6,
    }

    result = runner.invoke(app, ["index", "compression"])

    assert result.exit_code == 0
    mock_compression_api["get_summary"].assert_called_once()

    lines = rendered(mock_rich_console).splitlines()
    assert lines[:2] == ["Index compression settings", "  Status  Not enabled"]
