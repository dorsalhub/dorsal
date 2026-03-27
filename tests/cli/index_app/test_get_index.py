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
import json
import pathlib
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.panel import Panel

from dorsal.cli import app

runner = CliRunner()
HASH_ID = "a" * 64


@pytest.fixture
def mock_get_index_cmd(mocker, tmp_path):
    """Mocks dependencies for the local index get command."""
    # Use tmp_path to generate a cross-platform absolute path
    path_id = str(tmp_path / "test.pdf")

    mock_record = MagicMock()
    mock_record.abspath = path_id
    mock_record.name = "test.pdf"
    mock_record.size = 12345
    mock_record.media_type = "application/pdf"
    mock_record.modified_time = 1700000000.0
    mock_record.hash_sha256 = HASH_ID
    mock_record.hash_blake3 = "fake_blake3"
    mock_record.hash_quick = None
    mock_record.hash_tlsh = None

    mock_record.record_json = json.dumps(
        {"annotations": {"file/base": {"record": {"name": "test.pdf", "size": 12345}, "private": False}}}
    )

    mock_index = MagicMock()
    mock_index.get_record.return_value = mock_record

    mock_get_shared_index = mocker.patch("dorsal.session.get_shared_index", return_value=mock_index)
    mock_search_local = mocker.patch("dorsal.api.search.search_local", return_value=[mock_record])
    mock_create_panel = mocker.patch("dorsal.cli.views.file.create_file_info_panel", return_value=Panel("Mock Panel"))

    mock_reports_dir = tmp_path / "reports"
    mocker.patch("dorsal.common.constants.CLI_GET_REPORTS_DIR", mock_reports_dir)

    return {
        "get_shared_index": mock_get_shared_index,
        "index_instance": mock_index,
        "search_local": mock_search_local,
        "create_panel": mock_create_panel,
        "record": mock_record,
        "tmp_path": tmp_path,
        "reports_dir": mock_reports_dir,
        "path_id": path_id,
    }


def test_get_index_by_path(mock_rich_console, mock_get_index_cmd):
    """Tests retrieving a record by its absolute path."""
    path_id = mock_get_index_cmd["path_id"]
    result = runner.invoke(app, ["index", "get", path_id])

    assert result.exit_code == 0
    mock_get_index_cmd["index_instance"].get_record.assert_called_once()
    mock_get_index_cmd["search_local"].assert_not_called()
    mock_get_index_cmd["create_panel"].assert_called_once()


def test_get_index_by_hash(mock_rich_console, mock_get_index_cmd):
    """Tests retrieving a record by its SHA256 hash using the search fallback."""
    mock_get_index_cmd["index_instance"].get_record.return_value = None

    result = runner.invoke(app, ["index", "get", HASH_ID])

    assert result.exit_code == 0
    mock_get_index_cmd["search_local"].assert_called_once()
    assert f"sha256:{HASH_ID}" in mock_get_index_cmd["search_local"].call_args.args[0]
    mock_get_index_cmd["create_panel"].assert_called_once()


def test_get_index_not_found(mock_rich_console, mock_get_index_cmd):
    """Tests graceful exit when no record is found by path or hash."""
    mock_get_index_cmd["index_instance"].get_record.return_value = None
    mock_get_index_cmd["search_local"].return_value = []

    result = runner.invoke(app, ["index", "get", HASH_ID])

    assert result.exit_code != 0

    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "No local records found" in all_output


def test_get_index_json_output(mock_rich_console, mock_get_index_cmd):
    """Tests retrieving and printing the raw JSON dictionary."""
    path_id = mock_get_index_cmd["path_id"]
    result = runner.invoke(app, ["index", "get", path_id, "--json"])

    assert result.exit_code == 0
    mock_get_index_cmd["create_panel"].assert_not_called()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data["hash"] == HASH_ID


def test_get_index_json_decode_error(mock_rich_console, mock_get_index_cmd):
    """Tests safety fallback if the SQLite database returns corrupted JSON."""
    mock_get_index_cmd["record"].record_json = "{ corrupted: json"
    path_id = mock_get_index_cmd["path_id"]

    result = runner.invoke(app, ["index", "get", path_id])

    assert result.exit_code != 0
    assert "Corrupted record found in local index" in result.output


def test_get_index_save_default_path(mock_get_index_cmd):
    """Tests saving the output to the default auto-generated directory."""
    path_id = mock_get_index_cmd["path_id"]
    result = runner.invoke(app, ["index", "get", path_id, "-s"])

    assert result.exit_code == 0
    saved_files = list(mock_get_index_cmd["reports_dir"].glob("*.json"))
    assert len(saved_files) == 1
    assert HASH_ID in saved_files[0].name


def test_get_index_output_file(mock_get_index_cmd):
    """Tests saving output to an explicitly named JSON file."""
    custom_out = mock_get_index_cmd["tmp_path"] / "custom_report.json"
    path_id = mock_get_index_cmd["path_id"]
    result = runner.invoke(app, ["index", "get", path_id, "--output", str(custom_out)])

    assert result.exit_code == 0
    assert custom_out.exists()


def test_get_index_output_dir(mock_get_index_cmd):
    """Tests saving output into an explicitly named directory."""
    custom_dir = mock_get_index_cmd["tmp_path"] / "custom_dir"
    custom_dir.mkdir()
    path_id = mock_get_index_cmd["path_id"]

    result = runner.invoke(app, ["index", "get", path_id, "-s", "--output", str(custom_dir)])

    assert result.exit_code == 0
    saved_files = list(custom_dir.glob("*.json"))
    assert len(saved_files) == 1


def test_get_index_output_extension_warning(mock_rich_console, mock_get_index_cmd):
    """Tests the warning generated when a non-JSON extension is provided without the save flag."""
    weird_out = mock_get_index_cmd["tmp_path"] / "report.txt"
    path_id = mock_get_index_cmd["path_id"]
    result = runner.invoke(app, ["index", "get", path_id, "--output", str(weird_out)])

    assert result.exit_code == 0

    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "unknown extension" in all_output


def test_get_index_save_ioerror(mock_get_index_cmd, mocker):
    """Tests the graceful exit when an IOError occurs during save."""
    mocker.patch("builtins.open", side_effect=IOError("Permission denied"))
    path_id = mock_get_index_cmd["path_id"]

    result = runner.invoke(app, ["index", "get", path_id, "-s"])

    assert result.exit_code != 0
    assert "Error writing to file" in result.output


def test_get_index_save_generic_error(mock_rich_console, mock_get_index_cmd, mocker):
    """Tests the warning panel fallback when a generic Exception occurs during save."""
    mocker.patch("builtins.open", side_effect=Exception("Unknown file error"))
    path_id = mock_get_index_cmd["path_id"]

    result = runner.invoke(app, ["index", "get", path_id, "-s"])

    assert result.exit_code == 0

    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "Could not save JSON report" in all_output
