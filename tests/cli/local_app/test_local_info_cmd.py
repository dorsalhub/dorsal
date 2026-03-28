# Copyright 2025-2026 Dorsal Hub LTD
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
import datetime
import pathlib
import os
from unittest.mock import MagicMock, ANY, patch

import pytest
import typer
from typer.testing import CliRunner
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_rich_console(mocker):
    mock_console = MagicMock()

    mocker.patch("dorsal.cli.local_app.info_cmd.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_exit_cli(mocker):
    def _side_effect(code=0, message=None):
        raise typer.Exit(code)

    return mocker.patch("dorsal.cli.local_app.info_cmd.exit_cli", side_effect=_side_effect)


@pytest.fixture
def mock_file_deps(mocker):
    """Mocks fast file access dependencies at their source."""
    return mocker.patch("dorsal.file.utils.infer_mediatype.get_media_type", return_value="text/plain")


@pytest.fixture
def mock_dir_deps(mocker):
    """Mocks directory info at its source."""
    dt1 = "2025-01-01T10:00:00"
    mock_dir_info_data = {
        "overall": {
            "total_files": 2,
            "total_dirs": 1,
            "hidden_files": 0,
            "total_size": 2048,
            "time_taken_seconds": 0.05,
            "avg_size": 1024,
            "largest_file": {"path": "file2.txt", "size": 2000},
            "smallest_file": {"path": "file1.txt", "size": 48},
            "newest_mod_file": {"path": "file2.txt", "date": dt1},
            "oldest_mod_file": {"path": "file1.txt", "date": dt1},
            "oldest_creation_file": {"path": "file1.txt", "date": dt1},
            "permissions": {"executable": 0, "read_only": 0},
        },
        "by_type": [{"media_type": "text/plain", "count": 2, "total_size": 2048, "percentage": 100.0}],
    }
    return mocker.patch("dorsal.api.file.get_directory_info", return_value=mock_dir_info_data)


def test_info_file_success(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.write_text("hello world")

    result = runner.invoke(app, ["local", "info", str(target)])

    assert result.exit_code == 0
    mock_file_deps.assert_called_once()

    print_calls = mock_rich_console.print.call_args_list
    assert any(isinstance(c.args[0], Panel) and "File Summary" in str(c.args[0].title) for c in print_calls)


def test_info_file_json(mock_rich_console, mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.write_text("hello world")

    runner.invoke(app, ["local", "info", str(target), "--json"])

    mock_exit_cli.assert_called_once()
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)
    assert data["name"] == "test.txt"
    assert data["size_bytes"] == 11


def test_info_file_ignored_dir_flags(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "info", str(target), "--recursive", "--media-type"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Directory-specific flags" in printed_text


def test_info_file_symlink(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    symlink_path = tmp_path / "link.txt"
    symlink_path.symlink_to(target)

    runner.invoke(app, ["local", "info", str(symlink_path)])

    panels = [c.args[0] for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Panel)]

    console = Console(width=200)
    with console.capture() as capture:
        console.print(panels[0])

    assert "test.txt" in capture.get()


@patch("pathlib.Path.readlink")
def test_info_file_symlink_broken(mock_readlink, mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    symlink_path = tmp_path / "link.txt"
    symlink_path.symlink_to(target)

    mock_readlink.side_effect = OSError("Broken Link")
    runner.invoke(app, ["local", "info", str(symlink_path)])

    panels = [c.args[0] for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Panel)]

    # Render the panel to a string to inspect its contents
    console = Console()
    with console.capture() as capture:
        console.print(panels[-1])

    assert "(unreadable)" in capture.get()


def test_info_file_error(mock_exit_cli, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    mock_file_deps.side_effect = Exception("File locked")

    runner.invoke(app, ["local", "info", str(target)])
    mock_exit_cli.assert_called_once()
    assert "File locked" in mock_exit_cli.call_args.kwargs["message"]


def test_info_dir_success(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "info", str(target)])

    assert result.exit_code == 0
    mock_dir_deps.assert_called_once()

    print_calls = mock_rich_console.print.call_args_list
    assert any(isinstance(c.args[0], Panel) and "Directory Summary" in str(c.args[0].title) for c in print_calls)


def test_info_dir_json(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "info", str(target), "--json"])

    mock_exit_cli.assert_called_once()
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)
    assert data["overall"]["total_size"] == 2048


def test_info_dir_media_type_table(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "info", str(target), "--media-type"])

    tables = [c.args[0] for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Table)]
    assert any("Media Type Breakdown" in str(t.title) for t in tables)


def test_info_dir_empty(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps.return_value = {"overall": {"total_size": 0, "total_files": 0}}

    runner.invoke(app, ["local", "info", str(target)])

    mock_exit_cli.assert_called_once()
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "No files found or accessible" in printed_text


def test_info_dir_os_error(mock_exit_cli, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    mock_dir_deps.side_effect = FileNotFoundError("Missing directory")

    runner.invoke(app, ["local", "info", str(target)])
    mock_exit_cli.assert_called_once()
    assert "Missing directory" in mock_exit_cli.call_args.kwargs["message"]


def test_info_dir_generic_error(mock_exit_cli, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    mock_dir_deps.side_effect = Exception("System Crash")

    runner.invoke(app, ["local", "info", str(target)])
    mock_exit_cli.assert_called_once()
    assert "System Crash" in mock_exit_cli.call_args.kwargs["message"]


def test_info_output_inference(mock_file_deps, tmp_path):
    target_file = tmp_path / "test.txt"
    target_file.touch()
    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    runner.invoke(app, ["local", "info", str(target_file), "--save", "--output", str(out_dir)])

    expected_file = out_dir / "info-file-test.txt.json"
    assert expected_file.exists()


@patch("builtins.open")
def test_info_save_io_error(mock_open, mock_rich_console, mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_open.side_effect = IOError("Disk full")

    runner.invoke(app, ["local", "info", str(target), "-s"])
    mock_exit_cli.assert_called()
    assert "Error writing to file: Disk full" in mock_exit_cli.call_args.kwargs["message"]


@patch("json.dump")
@patch("builtins.open")
def test_info_save_generic_error(mock_open, mock_json, mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_json.side_effect = TypeError("Not serializable")

    runner.invoke(app, ["local", "info", str(target), "-s"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not save JSON report" in printed_text
    assert "Not serializable" in printed_text


def test_info_unknown_extension_warning(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "info", str(target), "--output", "report.xml"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "was specified with an unknown extension" in printed_text
