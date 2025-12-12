# Copyright 2025 Dorsal Hub LTD
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
import json
import datetime
from typer.testing import CliRunner
from unittest.mock import MagicMock, patch
from rich.panel import Panel
from rich.table import Table


from dorsal.cli import app
from dorsal.cli.dir_app import info_dir_cmd

runner = CliRunner()


TEST_DATA_DIR = "tests/data"

MOCK_STATS_RESULT = {
    "overall": {
        "total_files": 10,
        "total_dirs": 2,
        "hidden_files": 1,
        "total_size": 10485760,  # 10 MiB
        "avg_size": 1048576.0,
        "largest_file": {"size": 5242880, "path": f"{TEST_DATA_DIR}/large.bin"},
        "smallest_file": {"size": 1024, "path": f"{TEST_DATA_DIR}/small.txt"},
        "newest_mod_file": {
            "date": datetime.datetime.now().isoformat(),
            "path": f"{TEST_DATA_DIR}/new.txt",
        },
        "oldest_mod_file": {
            "date": "2023-01-01T12:00:00+00:00",
            "path": f"{TEST_DATA_DIR}/old.txt",
        },
        "oldest_creation_file": {
            "date": "2023-01-01T10:00:00+00:00",
            "path": f"{TEST_DATA_DIR}/archive/first.log",
        },
        "permissions": {"executable": 2, "read_only": 1},
        "time_taken_seconds": 0.5,
        "time_taken_mt": 0.1,
    },
    "by_type": [
        {
            "media_type": "video/mp4",
            "count": 2,
            "total_size": 8388608,
            "percentage": 80.0,
        },
        {
            "media_type": "text/plain",
            "count": 8,
            "total_size": 2097152,
            "percentage": 20.0,
        },
    ],
}


@pytest.fixture
def mock_info_cmd(mocker):
    """Mocks backend dependencies for the `dir info` command."""
    mock_get_info = mocker.patch("dorsal.api.file.get_directory_info", return_value=MOCK_STATS_RESULT)
    mock_save_report = mocker.patch.object(info_dir_cmd, "_save_json_report")

    return {
        "get_directory_info": mock_get_info,
        "save_report": mock_save_report,
    }


@patch("rich.table.Table.grid")
def test_info_dir_success_panel_output(mock_table_grid, mock_rich_console, mock_info_cmd, mocker):
    """Tests the default case by inspecting the data added to the Rich Table."""
    mock_summary_table = MagicMock()
    mock_table_grid.return_value = mock_summary_table

    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR])

    assert result.exit_code == 0
    mock_info_cmd["get_directory_info"].assert_called_once()
    mock_info_cmd["save_report"].assert_not_called()
    assert mock_rich_console.print.call_count == 2
    assert isinstance(mock_rich_console.print.call_args.args[0], Panel)

    all_rows_text = ""
    for call_args in mock_summary_table.add_row.call_args_list:
        all_rows_text += " ".join(str(arg) for arg in call_args.args)

    assert "Total File Count:" in all_rows_text
    assert "10" in all_rows_text


def test_info_dir_success_with_media_type(mock_rich_console, mock_info_cmd):
    """Tests the --media-type flag, expecting an additional table."""
    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR, "--media-type"])

    assert result.exit_code == 0
    # The command prints a title, the panel, and the media type table
    assert mock_rich_console.print.call_count == 3

    table_output = mock_rich_console.print.call_args.args[0]
    assert isinstance(table_output, Table)
    assert "Media Type Breakdown" in str(table_output.title)


def test_info_dir_success_json_output(mock_rich_console, mock_info_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["overall"]["total_files"] == 10
    assert data["by_type"][0]["media_type"] == "video/mp4"
    mock_info_cmd["save_report"].assert_not_called()


def test_info_dir_no_files_found(mock_rich_console, mock_info_cmd):
    """Tests graceful handling when no files are found."""
    empty_stats = MOCK_STATS_RESULT.copy()
    empty_stats["overall"]["total_files"] = 0
    empty_stats["overall"]["total_size"] = 0
    mock_info_cmd["get_directory_info"].return_value = empty_stats

    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    assert "No files found or accessible" in mock_rich_console.print.call_args.args[0]


def test_info_dir_exception_handling(mock_info_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_info_cmd["get_directory_info"].side_effect = Exception("A critical error occurred")

    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert "A critical error occurred" in result.output


def test_info_dir_not_a_directory_error(mock_info_cmd):
    """Tests that a NotADirectoryError is handled gracefully."""
    error_msg = f"The specified path is not a directory: {TEST_DATA_DIR}"
    mock_info_cmd["get_directory_info"].side_effect = NotADirectoryError(error_msg)

    result = runner.invoke(app, ["dir", "info", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert error_msg in result.output
