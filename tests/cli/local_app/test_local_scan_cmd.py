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

import io
import json
import os
import datetime
import pathlib
from unittest.mock import MagicMock, ANY, patch

import pytest
import typer
from typer.testing import CliRunner
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_rich_console(mocker):
    mock_console = MagicMock()
    mock_console.width = 120
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)
    mocker.patch("dorsal.cli.local_app.scan_cmd.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_error_console(mocker):
    mock_console = MagicMock()
    mocker.patch("dorsal.cli.local_app.scan_cmd.get_error_console", return_value=mock_console)
    return mock_console


def _printed_text(console) -> str:
    return "".join(str(c.args[0]) for c in console.print.call_args_list)


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
    mock_instance.file_path = "/fake/test.txt"
    mock_instance.date_created = datetime.datetime(2025, 1, 1)
    mock_instance.date_modified = datetime.datetime(2025, 1, 2)

    return {
        "local_file_class": mock_local_file_class,
        "create_panel": mocker.patch("dorsal.cli.views.file.create_file_info_panel"),
    }


@pytest.fixture
def mock_dir_deps(mocker):
    """Mocks backend dependencies for the dir scan routing."""
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")
    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []
    mock_instance.__len__.return_value = 2
    mock_instance.__bool__.side_effect = lambda: mock_instance.__len__() > 0

    file_1 = MagicMock(
        size=512, media_type="text/plain", date_modified=datetime.datetime(2025, 1, 1), record_id="rec_1"
    )
    file_1.name = "file1.txt"
    file_1.file_path = "/fake/file1.txt"

    file_2 = MagicMock(
        size=1024, media_type="application/json", date_modified=datetime.datetime(2025, 1, 2), record_id="rec_2"
    )
    file_2.name = "file2.txt"
    file_2.file_path = "/fake/file2.txt"

    mock_instance.info.return_value = {
        "overall": {"total_files": 2, "total_size": 1536, "newest_file": {}, "oldest_file": {}},
        "by_type": [{"type": "text/plain", "count": 1}],
        "by_source": [{"source": "disk", "count": 2}],
    }
    mock_instance.__iter__.return_value = iter([file_1, file_2])
    mock_instance.to_dict.return_value = {
        "scan_metadata": {"type": "local", "path": "/fake", "total_files_in_collection": 2},
        "results": [{"name": "file1.txt"}, {"name": "file2.txt"}],
    }

    return {"collection_class": mock_collection_class, "collection_instance": mock_instance}


def test_scan_cache_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "scan", str(target), "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(code=ANY, message="Error: --use-cache and --skip-cache cannot be used together.")


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


def test_scan_file_json_stdout(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert result.exit_code == 0
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)
    assert data["name"] == "test.txt"
    mock_file_deps["create_panel"].assert_not_called()


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
    # Assert that either a Panel or Group was used for the summary
    assert any(isinstance(call.args[0], (Panel, Group, Table)) for call in print_calls)


def test_scan_dir_csv_output(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--csv"])

    assert result.exit_code == 0
    mock_dir_deps["collection_instance"].to_csv.assert_called_once()


def test_scan_dir_invalid_sort(mock_dir_deps, tmp_path):
    """Invalid choices are rejected by Typer as a usage error before scanning."""
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--sort-by", "fake_col"])

    assert result.exit_code == 2
    mock_dir_deps["collection_class"].assert_not_called()


@pytest.mark.parametrize(
    "args", [["--sort-by", "SIZE", "--sort-order", "DESC"], ["--sort-by", "size", "--sort-order", "desc"]]
)
def test_scan_dir_sort_case_insensitive(mock_rich_console, mock_dir_deps, tmp_path, args):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), *args])

    assert result.exit_code == 0
    tables = [c.args[0] for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Table)]
    names = list(tables[0].columns[0].cells)
    assert names == ["file2.txt", "file1.txt"]


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_scan_dir_limit_must_be_positive(mock_dir_deps, tmp_path, limit):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--limit", limit])

    assert result.exit_code == 2
    mock_dir_deps["collection_class"].assert_not_called()


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


def test_scan_dir_init_error(mock_exit_cli, mock_dir_deps, tmp_path):
    """Hits the exception block when initializing LocalFileCollection."""
    target = tmp_path / "test_dir"
    target.mkdir()

    mock_dir_deps["collection_class"].side_effect = Exception("Init failed")
    runner.invoke(app, ["local", "scan", str(target)])

    mock_exit_cli.assert_called()
    assert "An error occurred during file discovery: Init failed" in mock_exit_cli.call_args.kwargs["message"]


def test_scan_dir_json_stdout(mock_rich_console, mock_error_console, mock_dir_deps, tmp_path):
    """Directory JSON is the only thing printed to stdout, with Rich wrapping/markup disabled."""
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 1
    call = mock_rich_console.print.call_args
    data = json.loads(call.args[0])
    assert data["scan_metadata"]["total_files_in_collection"] == 2
    assert "duration_seconds" in data["scan_metadata"]
    assert [r["name"] for r in data["results"]] == ["file1.txt", "file2.txt"]
    mock_dir_deps["collection_instance"].to_dict.assert_called_once_with(exclude={"embeddings", "text_chunks"})
    assert call.kwargs == {"markup": False, "highlight": False, "emoji": False, "soft_wrap": True}


def test_scan_file_json_disables_rich_processing(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    tricky_name = "[bold]x[/] :smile: " + "long " * 100
    mock_file_deps["local_file_class"].return_value.to_dict.return_value = {"name": tricky_name}

    result = runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert result.exit_code == 0
    call = mock_rich_console.print.call_args
    assert json.loads(call.args[0])["name"] == tricky_name
    assert call.kwargs == {"markup": False, "highlight": False, "emoji": False, "soft_wrap": True}


def test_scan_dir_json_with_save_and_csv(mock_rich_console, mock_error_console, mock_dir_deps, tmp_path):
    """--json no longer exits before writing --save / --csv reports; confirmations go to stderr."""
    target = tmp_path / "test_dir"
    target.mkdir()
    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    result = runner.invoke(app, ["local", "scan", str(target), "--json", "--save", "--csv", "-o", str(out_dir)])

    assert result.exit_code == 0
    mock_dir_deps["collection_instance"].to_csv.assert_called_once()
    assert mock_rich_console.print.call_count == 1
    stdout_data = json.loads(mock_rich_console.print.call_args.args[0])
    saved = json.loads((out_dir / "scan-dir-test_dir_report.json").read_text(encoding="utf-8"))
    assert saved == stdout_data
    stderr_text = _printed_text(mock_error_console)
    assert "JSON report saved to" in stderr_text
    assert "CSV report saved to" in stderr_text


def test_scan_dir_json_warnings_go_to_stderr(mock_rich_console, mock_error_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    mock_dir_deps["collection_instance"].warnings = ["This is a mock warning"]

    runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert mock_rich_console.print.call_count == 1
    json.loads(mock_rich_console.print.call_args.args[0])
    panels = [c.args[0] for c in mock_error_console.print.call_args_list if isinstance(c.args[0], Panel)]
    assert any("This is a mock warning" in str(p.renderable) for p in panels)


def test_scan_dir_json_progress_goes_to_stderr(mock_rich_console, mock_error_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "--json"])

    assert mock_dir_deps["collection_class"].call_args.kwargs["console"] is mock_error_console


def test_scan_dir_json_skips_tables(mock_rich_console, mock_error_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "--json"])

    printed = [c.args[0] for c in mock_rich_console.print.call_args_list]
    assert not any(isinstance(p, (Panel, Group, Table)) for p in printed)
    mock_dir_deps["collection_instance"].info.assert_not_called()


def test_scan_file_json_warnings_go_to_stderr(mock_rich_console, mock_error_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "--json", "-r", "-o", str(tmp_path / "out.unknown")])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 1
    json.loads(mock_rich_console.print.call_args.args[0])
    stderr_text = _printed_text(mock_error_console)
    assert "Directory-specific flags" in stderr_text
    assert "no report type was requested" in stderr_text


@patch("builtins.open")
def test_scan_file_json_with_save_confirmation_to_stderr(
    mock_open, mock_rich_console, mock_error_console, mock_file_deps, tmp_path
):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "--json", "-s"])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 1
    json.loads(mock_rich_console.print.call_args.args[0])
    assert "JSON report saved to" in _printed_text(mock_error_console)


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
    out_file = tmp_path / "reports" / "dir.json"

    runner.invoke(app, ["local", "scan", str(target), "-s", "-o", str(out_file)])
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert "duration_seconds" in saved["scan_metadata"]
    assert len(saved["results"]) == 2

    mock_rich_console.reset_mock()
    with patch("builtins.open", side_effect=Exception("Mock Dir JSON Error")):
        runner.invoke(app, ["local", "scan", str(target), "-s", "-o", str(out_file)])
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


def test_scan_output_trailing_separator_creates_directory(mock_rich_console, mock_dir_deps, tmp_path):
    """A non-existent --output ending in a separator is a directory, not a file named after it."""
    target = tmp_path / "test_dir"
    target.mkdir()
    out_dir = tmp_path / "new_reports"

    result = runner.invoke(app, ["local", "scan", str(target), "-s", "-o", str(out_dir) + os.sep])

    assert result.exit_code == 0
    assert (out_dir / "scan-dir-test_dir_report.json").is_file()


def test_scan_output_file_with_save_and_csv_writes_both(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    out_file = tmp_path / "report.json"

    runner.invoke(app, ["local", "scan", str(target), "-s", "-c", "-o", str(out_file)])

    assert out_file.is_file()
    mock_dir_deps["collection_instance"].to_csv.assert_called_once_with(str(tmp_path / "report.csv"))


def test_scan_output_dir_without_report_type_warns(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    runner.invoke(app, ["local", "scan", str(target), "-o", str(tmp_path / "reports.json") + os.sep])

    assert "no report type was requested" in _printed_text(mock_rich_console)
    assert not (tmp_path / "reports.json").exists()


def test_scan_file_local_attributes_not_mutated(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "scan", str(target), "--json"])

    data = json.loads(mock_rich_console.print.call_args.args[0])
    assert "full_path" not in data["local_attributes"]
    assert data["local_filesystem"]["full_path"] == "/fake/test.txt"


def test_scan_template_is_deprecated(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "scan", str(target), "-t", "fancy"])

    assert result.exit_code == 0
    assert "--template has no effect" in _printed_text(mock_rich_console)


def test_scan_file_name_markup_is_escaped(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "[bold]x[red].txt"
    target.touch()
    mock_file_deps["local_file_class"].return_value.name = "[bold]x[red].txt"

    runner.invoke(app, ["local", "scan", str(target)])

    assert r"\[bold]x\[red].txt" in _printed_text(mock_rich_console)
    assert r"File Record: \[bold]x\[red].txt" in mock_file_deps["create_panel"].call_args.kwargs["title"]


@pytest.mark.parametrize(
    "source, is_dir, expected_prefix",
    [
        (".", True, "scan-dir-{cwd}-"),
        ("my dir [1]", True, "scan-dir-my_dir_1-"),
        ("report.final.pdf", False, "report.final-"),
    ],
)
def test_get_final_path_default_names(tmp_path, monkeypatch, source, is_dir, expected_prefix):
    from dorsal.cli.local_app import scan_cmd

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scan_cmd.constants, "CLI_SCAN_REPORTS_DIR", tmp_path / "scans")

    result = scan_cmd._get_final_path(pathlib.Path(source), None, False, ".json", is_dir=is_dir)

    assert result.parent == tmp_path / "scans"
    assert result.name.startswith(expected_prefix.format(cwd=tmp_path.name))
    assert result.suffix == ".json"


def test_get_final_path_root_and_collision(tmp_path, monkeypatch):
    from dorsal.cli.local_app import scan_cmd

    monkeypatch.setattr(scan_cmd.constants, "CLI_SCAN_REPORTS_DIR", tmp_path)
    frozen = datetime.datetime(2026, 1, 2, 3, 4, 5)
    monkeypatch.setattr(scan_cmd.datetime, "datetime", MagicMock(now=MagicMock(return_value=frozen)))

    root = pathlib.Path(tmp_path.anchor)
    first = scan_cmd._get_final_path(root, None, False, ".json", is_dir=True)
    assert first.name == "scan-dir-root-20260102-030405.json"

    first.touch()
    second = scan_cmd._get_final_path(root, None, False, ".json", is_dir=True)
    assert second.name == "scan-dir-root-20260102-030405-1.json"


@pytest.mark.parametrize(
    "output, suffix, expected",
    [
        ("r.json", ".json", "r.json"),
        ("r.json", ".csv", "r.csv"),
        ("r.CSV", ".csv", "r.CSV"),
        ("report", ".json", "report.json"),
        ("r.txt", ".json", "r.txt.json"),
    ],
)
def test_get_final_path_output_file(tmp_path, output, suffix, expected):
    from dorsal.cli.local_app import scan_cmd

    result = scan_cmd._get_final_path(pathlib.Path("src"), tmp_path / output, False, suffix, is_dir=True)

    assert result == tmp_path / expected


def _render(renderable_fn, width=80) -> str:
    console = Console(file=io.StringIO(), width=width, color_system=None)
    renderable_fn(console)
    return console.file.getvalue()


def test_file_table_escapes_names_and_truncates(mock_dir_deps):
    from dorsal.cli.local_app import scan_cmd
    from dorsal.cli.themes.borders import get_borders

    collection = mock_dir_deps["collection_instance"]
    files = list(collection.__iter__.return_value)
    files[0].name = "[bold]x[/] " + "long " * 40 + ".txt"
    collection.__iter__.return_value = iter(files)

    out = _render(lambda c: scan_cmd._print_file_details_table(collection, {}, {}, get_borders(), 20, "name", "asc", c))

    name_lines = [line for line in out.splitlines() if "[bold]x[/]" in line]
    assert len(name_lines) == 1
    assert "…" in name_lines[0]
    assert sum("long" in line for line in out.splitlines()) == 1


def test_summary_panel_has_no_trailing_blank_line():
    from dorsal.cli.local_app import scan_cmd
    from dorsal.cli.themes.borders import get_borders

    info = {
        "overall": {
            "total_files": 1,
            "total_size": 3,
            "newest_file": {"date": datetime.datetime(2025, 1, 1), "path": "[a].txt"},
            "oldest_file": {"date": datetime.datetime(2024, 1, 1), "path": "[a].txt"},
        },
        "by_type": [],
    }

    out = _render(lambda c: scan_cmd._print_directory_summary_panel(info, {}, get_borders(), c))

    lines = out.splitlines()
    assert "Media Types: 0" in lines[-3]
    assert lines[-2].strip("│ ") == ""
    assert "(\\[a].txt)" not in out
    assert "([a].txt)" in out
