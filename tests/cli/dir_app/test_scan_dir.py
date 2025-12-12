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

import json
import os
import datetime
import pathlib
import typer
import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, patch, ANY
from rich.panel import Panel
from rich.table import Table


from dorsal.cli import app
from dorsal.cli.dir_app import scan_dir_cmd

runner = CliRunner()

TEST_DATA_DIR = "tests/data"


@pytest.fixture
def mock_rich_console(mocker):
    """Mocks the rich console to capture output."""
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_exit_cli(mocker):
    """
    Mocks exit_cli to ensure it raises typer.Exit with the correct code.
    This fixes the 'assert 0 != 0' failures by propagating the error code.
    """

    def _side_effect(code=0, message=None):
        raise typer.Exit(code)

    return mocker.patch("dorsal.common.cli.exit_cli", side_effect=_side_effect)


@pytest.fixture
def mock_scan_dir_cmd(mocker):
    """Mocks backend dependencies for the `dir scan` command."""
    # Patch LocalFileCollection at its source
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    # Configure the instance that will be returned by the constructor
    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []

    # Setup default behaviors
    mock_instance.__len__.return_value = 2
    mock_instance.__bool__.side_effect = lambda: mock_instance.__len__() > 0

    dt1 = datetime.datetime(2023, 1, 1, 10, 0, 0)
    dt2 = datetime.datetime(2023, 1, 2, 10, 0, 0)

    file_1 = MagicMock()
    file_1.name = "file1.txt"
    file_1.size = 512
    file_1.media_type = "text/plain"
    file_1.date_modified = dt1

    file_2 = MagicMock()
    file_2.name = "file2.txt"
    file_2.size = 1024
    file_2.media_type = "application/json"
    file_2.date_modified = dt2

    mock_instance.info.return_value = {
        "overall": {
            "total_files": 2,
            "total_size": 1536,
            "newest_file": {"path": "file2.txt", "date": dt2},
            "oldest_file": {"path": "file1.txt", "date": dt1},
        },
        "by_type": [{"type": "text/plain", "count": 1}, {"type": "application/json", "count": 1}],
        "by_source": [{"source": "disk", "count": 2}],
    }

    mock_instance.__iter__.return_value = iter([file_1, file_2])
    mock_instance.to_dict.return_value = [{"name": "file1.txt"}, {"name": "file2.txt"}]
    mock_instance.source_info = {"path": TEST_DATA_DIR}

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
    }


def test_scan_dir_success_default(mock_rich_console, mock_scan_dir_cmd, mock_exit_cli):
    """Tests the default `dir scan` command."""
    normalized_path = os.path.normpath(str(TEST_DATA_DIR))
    result = runner.invoke(app, ["dir", "scan", normalized_path])

    assert result.exit_code == 0

    mock_scan_dir_cmd["collection_class"].assert_called_once_with(
        source=normalized_path,
        console=mock_rich_console,
        palette=ANY,
        recursive=False,
        use_cache=False,
        overwrite_cache=False,
    )

    # Verify Summary Panel was printed
    print_calls = mock_rich_console.print.call_args_list
    panels = [call.args[0] for call in print_calls if isinstance(call.args[0], Panel)]
    assert any("Directory Scan Summary" in str(p.title) for p in panels)

    # Verify Table was printed
    tables = [call.args[0] for call in print_calls if isinstance(call.args[0], Table)]
    assert any("File Scan Details" in str(t.title) for t in tables)


def test_scan_dir_json_output(mock_rich_console, mock_scan_dir_cmd, mock_exit_cli):
    """Tests the `dir scan --json` command."""
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called()
    mock_exit_cli.assert_called()

    # Capture the raw JSON output
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)

    assert data["scan_metadata"]["total_files_found"] == 2
    assert data["results"][0]["name"] == "file1.txt"


def test_scan_dir_output_to_file_csv(mock_rich_console, mock_scan_dir_cmd, mock_exit_cli):
    """Tests saving the report to a file with --output."""
    output_file = "my_report.csv"
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--output", output_file])

    assert result.exit_code == 0

    # Verify to_csv was called on the collection
    mock_scan_dir_cmd["collection_instance"].to_csv.assert_called_once()
    args, _ = mock_scan_dir_cmd["collection_instance"].to_csv.call_args
    assert output_file in args[0]

    # Verify success message
    assert "CSV report saved" in str(mock_rich_console.print.call_args_list[-1].args[0])


@pytest.mark.parametrize("sort_by, sort_order", [("size", "desc"), ("date", "asc")])
def test_scan_dir_sorting_options(sort_by, sort_order, mock_scan_dir_cmd, mock_rich_console):
    """Tests that sorting options are passed correctly and table is rendered."""
    result = runner.invoke(
        app,
        [
            "dir",
            "scan",
            TEST_DATA_DIR,
            "--sort-by",
            sort_by,
            "--sort-order",
            sort_order,
        ],
    )

    assert result.exit_code == 0

    # Check that a table was actually generated
    print_calls = mock_rich_console.print.call_args_list
    tables = [call.args[0] for call in print_calls if isinstance(call.args[0], Table)]
    assert len(tables) > 0
    assert "File Scan Details" in str(tables[0].title)


def test_scan_dir_invalid_sort_option(mock_exit_cli):
    """Tests that an invalid sorting option causes a graceful exit."""
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--sort-by", "invalid_column"])

    # Expect exit code != 0 (default error code is usually 1)
    assert result.exit_code != 0
    mock_exit_cli.assert_called()
    assert "Invalid sorting option" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_cache_flag_conflict(mock_exit_cli):
    """Tests that using both --use-cache and --skip-cache fails."""
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--use-cache", "--skip-cache"])

    assert result.exit_code != 0
    mock_exit_cli.assert_called()
    assert "cannot be used together" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_collection_init_failure(mock_scan_dir_cmd, mock_exit_cli):
    """Tests graceful failure if the LocalFileCollection fails to initialize."""
    mock_scan_dir_cmd["collection_class"].side_effect = Exception("Failed to access directory")

    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR])

    assert result.exit_code != 0
    mock_exit_cli.assert_called()
    assert "An error occurred during file discovery" in mock_exit_cli.call_args.kwargs["message"]


# --- Expanded Coverage Tests ---


def test_scan_dir_recursive_flag(mock_rich_console, mock_scan_dir_cmd):
    """Tests that the recursive flag is correctly passed to the collection."""
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--recursive"])

    assert result.exit_code == 0
    mock_scan_dir_cmd["collection_class"].assert_called_once_with(
        source=ANY, console=ANY, palette=ANY, recursive=True, use_cache=ANY, overwrite_cache=ANY
    )


def test_scan_dir_limit_option(mock_rich_console, mock_scan_dir_cmd):
    """Tests that the limit flag affects table rendering."""
    # We set a low limit
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--limit", "1"])

    assert result.exit_code == 0

    # Check the "Showing first X of Y files" message
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Showing first 1 of 2 files" in printed_text


def test_scan_dir_smart_output_unknown_extension(mock_rich_console, mock_scan_dir_cmd):
    """Tests warning when --output has an unknown extension."""
    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--output", "report.txt"])

    assert result.exit_code == 0

    # Warning should be printed
    printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "unknown extension" in printed_text

    # Neither save method should be called
    mock_scan_dir_cmd["collection_instance"].to_json.assert_not_called()
    mock_scan_dir_cmd["collection_instance"].to_csv.assert_not_called()


def test_scan_dir_explicit_save_flags(mock_scan_dir_cmd):
    """Tests that --save and --csv flags force saving."""
    # Case 1: -s flag (save JSON)
    runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "-s"])
    mock_scan_dir_cmd["collection_instance"].to_json.assert_called_once()

    # Case 2: -c flag (save CSV)
    runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--csv"])
    mock_scan_dir_cmd["collection_instance"].to_csv.assert_called_once()


def test_scan_dir_empty_directory(mock_rich_console, mock_scan_dir_cmd, mock_exit_cli):
    """Tests behavior when the directory contains no files."""
    # Set length to 0
    mock_scan_dir_cmd["collection_instance"].__len__.return_value = 0

    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR])

    assert result.exit_code == 0  # It exits cleanly via exit_cli

    # Verify exit_cli was called (which signifies the command stopped early)
    mock_exit_cli.assert_called()

    # Verify the "processed 0 files" message
    processed_msg = str(mock_rich_console.print.call_args_list[0].args[0])
    assert "processed" in processed_msg

    # Ensure NO Panel or Table was printed (meaning code stopped before _print_directory_summary_panel)
    print_calls = mock_rich_console.print.call_args_list
    panels = [call.args[0] for call in print_calls if isinstance(call.args[0], Panel)]
    tables = [call.args[0] for call in print_calls if isinstance(call.args[0], Table)]

    assert len(panels) == 0, "Summary panel was printed despite empty collection"
    assert len(tables) == 0, "Table was printed despite empty collection"


def test_scan_dir_with_warnings(mock_rich_console, mock_scan_dir_cmd):
    """Tests that the warnings panel is displayed if warnings exist."""
    # Inject warnings
    mock_scan_dir_cmd["collection_instance"].warnings = ["Permission denied: /root"]

    result = runner.invoke(app, ["dir", "scan", TEST_DATA_DIR])

    assert result.exit_code == 0

    # Find the warning panel
    print_calls = mock_rich_console.print.call_args_list
    panels = [call.args[0] for call in print_calls if isinstance(call.args[0], Panel)]
    warning_panel = next((p for p in panels if "Warnings" in str(p.title)), None)

    assert warning_panel is not None
    assert "Permission denied" in str(warning_panel.renderable)


def test_scan_save_errors(mock_rich_console, mock_scan_dir_cmd, mock_exit_cli):
    """Tests error handling during file save operations."""
    # Simulate IOError during JSON save
    mock_scan_dir_cmd["collection_instance"].to_json.side_effect = IOError("Disk full")

    runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "-s"])
    mock_exit_cli.assert_called()
    assert "Error writing to file" in mock_exit_cli.call_args.kwargs["message"]

    # Reset for next case
    mock_exit_cli.reset_mock()

    # Simulate Generic Exception during CSV save
    mock_scan_dir_cmd["collection_instance"].to_csv.side_effect = Exception("Random Error")

    runner.invoke(app, ["dir", "scan", TEST_DATA_DIR, "--csv"])
    # Should NOT exit cli, but print warning
    assert mock_exit_cli.call_count == 0
    printed = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not save CSV report" in printed
