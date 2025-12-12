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

import datetime
import json
import logging
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner


from dorsal.cli import app
from dorsal.cli.file_app.scan_cmd import _save_html_report, _save_json_report

runner = CliRunner()

# Use a real file from your test data directory
TEST_FILE_PATH = "tests/data/valid.txt"

# A sample record to be returned by the mocked LocalFile
MOCK_FILE_RECORD = {
    "name": "valid.txt",
    "hashes": {"SHA-256": "mock_sha256_hash"},
    "tags": [],
    # Add the extra keys that the main function adds
    "local_filesystem": {
        "full_path": TEST_FILE_PATH,
        "date_created": "2025-08-15T10:00:00",
        "date_modified": "2025-08-15T11:00:00",
    },
}

# A sample palette used in the functions under test
SAMPLE_PALETTE = {
    "success": "green",
    "primary_value": "cyan",
    "error": "red",
}


# This fixture is kept local to this file.
@pytest.fixture
def mock_scan_cmd(mocker):
    """
    Mocks all backend dependencies for the `dorsal file scan` command.
    """
    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=True)
    mock_save_json = mocker.patch("dorsal.cli.file_app.scan_cmd._save_json_report")
    mock_save_html = mocker.patch("dorsal.cli.file_app.scan_cmd._save_html_report")

    mock_create_panel = mocker.patch("dorsal.cli.file_app.scan_cmd.create_file_info_panel")

    mock_local_file_class = mocker.patch("dorsal.cli.file_app.scan_cmd.LocalFile")
    mock_instance = mock_local_file_class.return_value

    mock_instance.to_dict.return_value = MOCK_FILE_RECORD
    mock_instance.name = "valid.txt"
    mock_instance._source = "cache"
    mock_instance._file_path = TEST_FILE_PATH
    mock_instance.date_created = datetime.datetime.fromisoformat("2025-08-15T10:00:00")
    mock_instance.date_modified = datetime.datetime.fromisoformat("2025-08-15T11:00:00")

    return {
        "local_file_class": mock_local_file_class,
        "save_json": mock_save_json,
        "save_html": mock_save_html,
        "create_panel": mock_create_panel,
    }


def test_scan_file_success_panel_output(mock_rich_console, mock_scan_cmd):
    """Tests the default `file scan` command, expecting a Rich Panel."""
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH])

    assert result.exit_code == 0, result.output
    mock_scan_cmd["local_file_class"].assert_called_once_with(
        file_path=str(pathlib.Path(TEST_FILE_PATH)), use_cache=False, overwrite_cache=False
    )

    # In interactive mode, no report should be saved
    mock_scan_cmd["save_json"].assert_not_called()
    mock_scan_cmd["save_html"].assert_not_called()

    # A panel should be created and printed
    mock_scan_cmd["create_panel"].assert_called_once()
    mock_rich_console.print.assert_any_call(mock_scan_cmd["create_panel"].return_value)


def test_scan_file_success_json_output(mock_rich_console, mock_scan_cmd):
    """Tests `file scan --json`, expecting JSON on stdout and an implicit save."""
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH, "--json"])

    assert result.exit_code == 0, result.output

    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data["name"] == "valid.txt"
    assert "local_filesystem" in data

    mock_scan_cmd["save_json"].assert_not_called()

    mock_scan_cmd["create_panel"].assert_not_called()
    mock_scan_cmd["save_html"].assert_not_called()


def test_scan_file_explicit_json_output(mock_rich_console, mock_scan_cmd):
    """Tests `file scan --json-output`, expecting an explicit save and NO panel."""
    with runner.isolated_filesystem():
        output_path = pathlib.Path("report.json")

        # Create the dummy file for the command to find.
        pathlib.Path(TEST_FILE_PATH).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(TEST_FILE_PATH).touch()

        result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH, "--save", "--output", str(output_path)])

        assert result.exit_code == 0, result.output

        # Should call the save helper with the specified path
        mock_scan_cmd["save_json"].assert_called_once()
        assert mock_scan_cmd["save_json"].call_args.kwargs["output_path"] == output_path.resolve()

        mock_scan_cmd["create_panel"].assert_called_once()


def test_scan_file_html_output(mock_rich_console, mock_scan_cmd):
    """Tests `file scan --html`, expecting an HTML report to be generated."""
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH, "--report"])

    assert result.exit_code == 0, result.output
    mock_scan_cmd["save_html"].assert_called_once()
    mock_scan_cmd["save_json"].assert_not_called()
    mock_scan_cmd["create_panel"].assert_called_once()


def test_scan_file_flag_conflict_cache():
    """Tests that using both --use-cache and --skip-cache fails."""
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH, "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    assert "Error: --use-cache and --skip-cache cannot be used together" in result.output


def test_scan_file_flag_conflict_output():
    """Tests that using both --json and --html fails."""
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH, "--json", "--report"])
    assert result.exit_code != 0
    assert "Error: --json (stdout) and --report (HTML) flags are not compatible." in result.output


def test_scan_file_exception_handling(mock_scan_cmd):
    """Tests that an exception during file processing is handled gracefully."""
    mock_scan_cmd["local_file_class"].side_effect = ValueError("Test error")
    result = runner.invoke(app, ["file", "scan", TEST_FILE_PATH])
    assert result.exit_code != 0
    assert "An unexpected error occurred: Test error" in result.output


@patch("dorsal.cli.file_app.scan_cmd.json.dump")
@patch("builtins.open")
def test_save_json_report_default_path(mock_open, mock_json_dump, mock_rich_console, mocker):
    """Tests _save_json_report saving to a default, timestamped path."""
    mock_ctx = MagicMock()
    mock_ctx.params = {}
    mock_reports_dir = MagicMock(spec=pathlib.Path)
    mocker.patch("dorsal.common.constants.CLI_SCAN_REPORTS_DIR", mock_reports_dir)
    mock_dt = MagicMock()
    mock_dt.now.return_value.strftime.return_value = "20250815-100000"
    mocker.patch("dorsal.cli.file_app.scan_cmd.datetime", mock_dt)

    _save_json_report(
        ctx=mock_ctx,
        record=MOCK_FILE_RECORD,
        original_path=pathlib.Path(TEST_FILE_PATH),
        output_path=None,
        palette=SAMPLE_PALETTE,
    )

    mock_reports_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    expected_path = mock_reports_dir / "valid.txt-20250815-100000.json"
    mock_open.assert_called_once_with(expected_path, "w", encoding="utf-8")
    mock_json_dump.assert_called_once_with(
        MOCK_FILE_RECORD,
        mock_open().__enter__(),
        indent=2,
        default=str,
        ensure_ascii=False,
    )
    success_message = str(mock_rich_console.print.call_args.args[0])
    assert "JSON report saved to" in success_message
    assert str(expected_path) in success_message


@patch("dorsal.cli.file_app.scan_cmd.json.dump")
@patch("builtins.open")
def test_save_json_report_explicit_path(mock_open, mock_json_dump, mock_rich_console):
    """Tests _save_json_report saving to an explicitly provided file path."""
    mock_ctx = MagicMock()
    mock_ctx.params = {}
    output_path = MagicMock(spec=pathlib.Path)

    output_path.is_dir.return_value = False
    output_path.parent = MagicMock()

    _save_json_report(
        ctx=mock_ctx,
        record=MOCK_FILE_RECORD,
        original_path=pathlib.Path(TEST_FILE_PATH),
        output_path=output_path,
        palette=SAMPLE_PALETTE,
    )

    output_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_open.assert_called_once_with(output_path, "w", encoding="utf-8")
    mock_json_dump.assert_called_once()
    success_message = str(mock_rich_console.print.call_args.args[0])
    assert str(output_path) in success_message


@patch("pathlib.Path.mkdir")
@patch("builtins.open")
def test_save_json_report_os_error(mock_open, mock_mkdir, mock_rich_console, caplog):
    """Tests that a warning is printed if the JSON report cannot be saved."""
    mock_open.side_effect = OSError("Permission denied")
    mock_ctx = MagicMock()
    mock_ctx.params = {}
    output_path = pathlib.Path("/forbidden/dir/report.json")

    with caplog.at_level(logging.ERROR):
        _save_json_report(
            ctx=mock_ctx,
            record=MOCK_FILE_RECORD,
            original_path=pathlib.Path(TEST_FILE_PATH),
            output_path=output_path,
            palette=SAMPLE_PALETTE,
        )

    warning_message = str(mock_rich_console.print.call_args.args[0])
    assert "Could not save JSON report" in warning_message
    assert "Permission denied" in warning_message
    assert "Failed to save JSON report" in caplog.text


@patch("dorsal.cli.file_app.scan_cmd.generate_html_file_report")
def test_save_html_report_success(mock_generate_html, mock_rich_console, mocker):
    """Tests that the HTML report is generated and saved correctly."""
    mock_local_file = MagicMock()
    mock_local_file._file_path = TEST_FILE_PATH
    mock_reports_dir = MagicMock(spec=pathlib.Path)
    mocker.patch("dorsal.common.constants.CLI_SCAN_REPORTS_DIR", mock_reports_dir)
    mock_dt = MagicMock()
    mock_dt.now.return_value.strftime.return_value = "20250815-100000"
    mocker.patch("dorsal.cli.file_app.scan_cmd.datetime", mock_dt)

    _save_html_report(
        local_file=mock_local_file,
        original_path=pathlib.Path(TEST_FILE_PATH),
        output_path=None,
        palette=SAMPLE_PALETTE,
        template="default",
    )

    expected_path = mock_reports_dir / "valid.txt-20250815-100000.html"
    mock_generate_html.assert_called_once_with(
        file_path=TEST_FILE_PATH,
        local_file=mock_local_file,
        output_path=str(expected_path),
        template="default",
    )
    success_message = str(mock_rich_console.print.call_args.args[0])
    assert "HTML report saved to" in success_message
    assert str(expected_path) in success_message
