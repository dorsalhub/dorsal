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
from unittest.mock import MagicMock, ANY, patch

import pytest
import typer
from typer.testing import CliRunner
from rich.panel import Panel
from rich.table import Table

from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_rich_console(mocker):
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)
    mocker.patch("dorsal.cli.local_app.scan_cmd.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_exit_cli(mocker):
    """Patch the specific reference to exit_cli inside our command module."""

    def _side_effect(code=0, message=None):
        raise typer.Exit(code)

    return mocker.patch("dorsal.cli.local_app.scan_cmd.exit_cli", side_effect=_side_effect)


@pytest.fixture
def mock_file_deps(mocker):
    """Mocks backend dependencies for the file scan routing."""
    mock_local_file_class = mocker.patch("dorsal.file.dorsal_file.LocalFile")
    mock_instance = mock_local_file_class.return_value

    mock_instance.to_dict.return_value = {
        "name": "test.txt",
        "hashes": {"SHA-256": "mock_hash"},
        "local_attributes": {
            "file_path": "/fake/test.txt",
            "date_created": datetime.datetime(2025, 1, 1),
            "date_modified": datetime.datetime(2025, 1, 2),
        },
    }
    mock_instance.name = "test.txt"
    mock_instance._source = "disk"
    mock_instance._file_path = "/fake/test.txt"
    mock_instance.date_created = datetime.datetime(2025, 1, 1)
    mock_instance.date_modified = datetime.datetime(2025, 1, 2)

    return {
        "local_file_class": mock_local_file_class,
        "create_panel": mocker.patch("dorsal.cli.views.file.create_file_info_panel"),
        "generate_html": mocker.patch("dorsal.api.file.generate_html_file_report"),
    }


@pytest.fixture
def mock_dir_deps(mocker):
    """Mocks backend dependencies for the dir scan routing."""
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")
    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []
    mock_instance.__len__.return_value = 2
    mock_instance.__bool__.side_effect = lambda: mock_instance.__len__() > 0

    file_1 = MagicMock(size=512, media_type="text/plain", date_modified=datetime.datetime(2025, 1, 1))
    file_1.name = "file1.txt"
    file_1._file_path = "/fake/file1.txt"

    file_2 = MagicMock(size=1024, media_type="application/json", date_modified=datetime.datetime(2025, 1, 2))
    file_2.name = "file2.txt"
    file_2._file_path = "/fake/file2.txt"

    mock_instance.info.return_value = {
        "overall": {"total_files": 2, "total_size": 1536, "newest_file": {}, "oldest_file": {}},
        "by_type": [{"type": "text/plain", "count": 1}],
        "by_source": [{"source": "disk", "count": 2}],
    }
    mock_instance.__iter__.return_value = iter([file_1, file_2])
    mock_instance.to_dict.return_value = [{"name": "file1.txt"}]

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
        "generate_html": mocker.patch("dorsal.api.file.generate_html_directory_report"),
    }


def test_scan_cache_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "scan", str(target), "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(code=ANY, message="Error: --use-cache and --skip-cache cannot be used together.")


def test_scan_json_report_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "scan", str(target), "--json", "--report"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(
        code=ANY, message="Error: --json (stdout) and --report (HTML) flags are not compatible."
    )


def test_scan_output_inference_warning(mock_rich_console, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "scan", str(target), "--output", "report.unknown"])

    assert result.exit_code == 0
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "was specified, but no report type was requested" in printed_text


def test_scan_file_default(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target)])

    assert result.exit_code == 0
    mock_file_deps["local_file_class"].assert_called_once()
    mock_file_deps["create_panel"].assert_called_once()
    mock_file_deps["generate_html"].assert_not_called()


def test_scan_file_json_stdout(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert result.exit_code == 0
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)
    assert data["name"] == "test.txt"
    mock_file_deps["create_panel"].assert_not_called()


def test_scan_file_report(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "--report"])

    assert result.exit_code == 0
    mock_file_deps["generate_html"].assert_called_once()
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "HTML report saved" in printed_text


def test_scan_file_exception_handling(mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_file_deps["local_file_class"].side_effect = Exception("Disk read error")

    result = runner.invoke(app, ["local", "scan", str(target)])
    assert result.exit_code != 0
    mock_exit_cli.assert_called()
    assert "An unexpected error occurred: Disk read error" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_default(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target)])

    assert result.exit_code == 0
    mock_dir_deps["collection_class"].assert_called_once()

    print_calls = mock_rich_console.print.call_args_list
    assert any(isinstance(call.args[0], Panel) for call in print_calls)
    assert any(isinstance(call.args[0], Table) for call in print_calls)


def test_scan_dir_csv_output(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--csv"])

    assert result.exit_code == 0
    mock_dir_deps["collection_instance"].to_csv.assert_called_once()


def test_scan_dir_html_report(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--report"])

    assert result.exit_code == 0
    mock_dir_deps["generate_html"].assert_called_once()
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "HTML Directory report saved" in printed_text


def test_scan_dir_invalid_sort(mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--sort-by", "fake_col"])

    assert result.exit_code != 0
    mock_exit_cli.assert_called()
    assert "Invalid sorting option" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_empty_graceful_exit(mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    mock_dir_deps["collection_instance"].__len__.return_value = 0

    result = runner.invoke(app, ["local", "scan", str(target)])

    assert result.exit_code == 0
    mock_exit_cli.assert_called_once()


def test_scan_skip_overwrite_conflict(mock_exit_cli, tmp_path):
    """Hits the skip_cache + overwrite_cache conflict block."""
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "scan", str(target), "--skip-cache", "--overwrite-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(
        code=ANY, message="Error: --skip-cache and --overwrite-cache cannot be used together."
    )


def test_scan_output_inference_extensions(mock_file_deps, tmp_path):
    """Hits the output_path inference block for .json, .csv, and .html."""
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "scan", str(target), "--output", tmp_path / "report.json"])

    runner.invoke(app, ["local", "scan", str(target), "--output", tmp_path / "report.html"])
    mock_file_deps["generate_html"].assert_called()


def test_scan_file_ignored_dir_flags(mock_rich_console, mock_file_deps, tmp_path):
    """Hits the directory-flag warning when scanning a file."""
    target = tmp_path / "test.txt"
    target.touch()
    runner.invoke(app, ["local", "scan", str(target), "--csv", "--recursive", "--lazy"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Directory-specific flags" in printed_text
    assert "are ignored when scanning a single file" in printed_text


def test_scan_file_fallback_local_filesystem(mock_file_deps, tmp_path):
    """Hits the 'else' block where local_attributes is missing from the record_dict."""
    target = tmp_path / "test.txt"
    target.touch()

    mock_file_deps["local_file_class"].return_value.to_dict.return_value = {
        "name": "test.txt",
        "hashes": {"SHA-256": "mock_hash"},
    }

    result = runner.invoke(app, ["local", "scan", str(target)])
    assert result.exit_code == 0


@patch("builtins.open")
def test_scan_file_save_success_and_error(mock_open, mock_rich_console, mock_file_deps, tmp_path):
    """Hits the file save block and the exception block in _save_report_to_disk."""
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "scan", str(target), "-s"])
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "JSON report saved to" in printed_text

    mock_rich_console.reset_mock()
    mock_open.side_effect = Exception("Mock Write Failure")
    runner.invoke(app, ["local", "scan", str(target), "-s"])
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not save JSON report. Error: Mock Write Failure" in printed_text


def test_scan_file_html_error(mock_rich_console, mock_file_deps, tmp_path):
    """Hits the exception block during file HTML report generation."""
    target = tmp_path / "test.txt"
    target.touch()

    mock_file_deps["generate_html"].side_effect = Exception("Mock HTML Failure")
    runner.invoke(app, ["local", "scan", str(target), "--report"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not generate HTML report. Error: Mock HTML Failure" in printed_text


def test_scan_dir_init_error(mock_exit_cli, mock_dir_deps, tmp_path):
    """Hits the exception block when initializing LocalFileCollection."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps["collection_class"].side_effect = Exception("Init failed")
    runner.invoke(app, ["local", "scan", str(target)])

    mock_exit_cli.assert_called()
    assert "An error occurred during file discovery: Init failed" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_json_stdout(mock_rich_console, mock_exit_cli, mock_dir_deps, tmp_path):
    """Hits the early exit when outputting directory JSON to stdout."""
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "--json"])
    mock_exit_cli.assert_called()

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "total_files_found" in printed_text


def test_scan_dir_warnings(mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the warnings block for directory scans."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps["collection_instance"].warnings = ["This is a mock warning"]
    runner.invoke(app, ["local", "scan", str(target)])

    print_calls = mock_rich_console.print.call_args_list
    panels = [call.args[0] for call in print_calls if isinstance(call.args[0], Panel)]
    assert any("This is a mock warning" in str(p.renderable) for p in panels)


def test_scan_dir_save_json_success_and_error(mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the dir save logic and its exception handler."""
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "-s"])
    mock_dir_deps["collection_instance"].to_json.assert_called_once()

    mock_rich_console.reset_mock()
    mock_dir_deps["collection_instance"].to_json.side_effect = Exception("Mock Dir JSON Error")
    runner.invoke(app, ["local", "scan", str(target), "-s"])
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not save JSON report. Error: Mock Dir JSON Error" in printed_text


def test_scan_dir_save_csv_error(mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the exception handler when saving a dir CSV fails."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps["collection_instance"].to_csv.side_effect = Exception("Mock CSV Error")
    runner.invoke(app, ["local", "scan", str(target), "--csv"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not save CSV report. Error: Mock CSV Error" in printed_text


def test_scan_dir_save_html_error(mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the exception handler when saving a dir HTML fails."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps["generate_html"].side_effect = Exception("Mock Dir HTML Error")
    runner.invoke(app, ["local", "scan", str(target), "--report"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not generate HTML directory report. Error: Mock Dir HTML Error" in printed_text


def test_scan_output_path_is_dir(mock_file_deps, tmp_path):
    """Hits the block checking if output_path is an existing directory."""
    target = tmp_path / "test.txt"
    target.touch()

    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "-s", "--output", str(out_dir)])


@patch("pathlib.Path.is_symlink")
@patch("pathlib.Path.readlink")
def test_scan_dir_symlink_success_and_error(mock_readlink, mock_is_symlink, mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the symlink display logic and its OSError handler in the table printer."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_is_symlink.return_value = True

    mock_readlink.return_value = "/real/target/file.txt"
    runner.invoke(app, ["local", "scan", str(target)])

    mock_readlink.side_effect = OSError("Symlink broken")
    runner.invoke(app, ["local", "scan", str(target)])


def test_scan_dir_limit_message(mock_rich_console, mock_dir_deps, tmp_path):
    """Hits the check for limit < total files."""
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "--limit", "1"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Showing first 1 of 2 files" in printed_text
