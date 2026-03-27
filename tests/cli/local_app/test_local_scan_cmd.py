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
from unittest.mock import MagicMock, ANY

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
