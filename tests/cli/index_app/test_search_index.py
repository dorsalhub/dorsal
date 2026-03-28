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

import builtins
import pytest
import json
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.table import Table

from dorsal.cli import app
from dorsal.cli.index_app.search_index_cmd import _save_local_search_results

runner = CliRunner()
QUERY = "ext:pdf"


@pytest.fixture
def mock_search_index_cmd(mocker):
    """Mocks dependencies for the local index search command."""
    mock_record = MagicMock()
    mock_record.name = "local_test.pdf"
    mock_record.size = 12345
    mock_record.media_type = "application/pdf"
    mock_record.hash_sha256 = "sha256:localhash123"

    mock_pagination = MagicMock()
    mock_pagination.current_page = 1
    mock_pagination.page_count = 1
    mock_pagination.record_count = 1
    mock_pagination.start_index = 0
    mock_pagination.end_index = 1
    mock_pagination.has_next = False

    mock_response = MagicMock()
    mock_response.records = [mock_record]
    mock_response.pagination = mock_pagination
    mock_response.model_dump.return_value = {"records": [{"hash_sha256": "sha256:localhash123"}]}

    mock_search_local_paginated = mocker.patch("dorsal.api.search.search_local_paginated", return_value=mock_response)

    mock_save_helper = mocker.patch("dorsal.cli.index_app.search_index_cmd._save_local_search_results")

    return {
        "search_api": mock_search_local_paginated,
        "save_results": mock_save_helper,
    }


def test_search_index_default(mock_rich_console, mock_search_index_cmd):
    """Tests a default local search, ensuring table and pagination footer are printed."""
    result = runner.invoke(app, ["index", "search", QUERY])

    assert result.exit_code == 0
    mock_search_index_cmd["search_api"].assert_called_once_with(
        query=QUERY,
        or_logic=False,
        page=1,
        per_page=30,
        sort_by="date_modified",
        sort_desc=True,
    )
    mock_search_index_cmd["save_results"].assert_not_called()

    tables = [call.args[0] for call in mock_rich_console.print.call_args_list if isinstance(call.args[0], Table)]
    assert len(tables) == 1
    assert "Local Search Results" in str(tables[0].title)


def test_search_index_json_output(mock_rich_console, mock_search_index_cmd):
    """Tests a successful local search with --json output."""
    result = runner.invoke(app, ["index", "search", QUERY, "--json"])

    assert result.exit_code == 0

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data["records"][0]["hash_sha256"] == "sha256:localhash123"
    mock_search_index_cmd["save_results"].assert_not_called()


def test_search_index_no_results(mock_rich_console, mock_search_index_cmd):
    """Tests the output when a local search yields no results."""
    mock_search_index_cmd["search_api"].return_value.records = []

    result = runner.invoke(app, ["index", "search", QUERY])

    assert result.exit_code == 0
    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "No records found" in all_output


def test_search_index_save_flag(mock_search_index_cmd):
    """Tests that the save helper is triggered when -s is passed."""
    result = runner.invoke(app, ["index", "search", QUERY, "-s"])
    assert result.exit_code == 0
    mock_search_index_cmd["save_results"].assert_called_once()


def test_search_index_output_extension_warning(mock_rich_console, mock_search_index_cmd):
    """Tests warning when --output has an unknown extension."""
    result = runner.invoke(app, ["index", "search", QUERY, "--output", "report.txt"])

    assert result.exit_code == 0
    printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "unknown extension" in printed_text


def test_search_index_exception_handling(mock_rich_console, mock_search_index_cmd):
    """Tests that an exception thrown by the API is handled gracefully."""
    mock_search_index_cmd["search_api"].side_effect = Exception("Corrupt Database")

    result = runner.invoke(app, ["index", "search", QUERY])

    assert result.exit_code != 0
    assert "An error occurred during local search: Corrupt Database" in result.output


def test_search_index_empty_query(mock_rich_console, mock_search_index_cmd):
    """Hits the early exit when an empty query string is provided."""
    result = runner.invoke(app, ["index", "search", "   "])
    assert result.exit_code != 0
    output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "Please provide a search query" in output


def test_search_index_has_next_page(mock_rich_console, mock_search_index_cmd):
    """Hits the 'To see the next page...' footer rendering."""
    mock_search_index_cmd["search_api"].return_value.pagination.has_next = True
    mock_search_index_cmd["search_api"].return_value.pagination.current_page = 1

    result = runner.invoke(app, ["index", "search", QUERY])

    assert result.exit_code == 0
    output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "To see the next page" in output
    assert "--page 2" in output


def test_save_local_search_results_output_dir(tmp_path, mock_rich_console):
    """Tests saving when an explicit output directory is provided."""
    page_data = {"pagination": {"current_page": 2}}
    palette = {"success": "green", "primary_value": "blue"}

    _save_local_search_results("my query", page_data, palette, tmp_path, False)

    expected_file = tmp_path / "search-local-my_query-p2.json"
    assert expected_file.exists()

    with open(expected_file) as f:
        data = json.load(f)
        assert data["pagination"]["current_page"] == 2


def test_save_local_search_results_output_file(tmp_path, mock_rich_console):
    """Tests saving when an explicit output file path is provided."""
    file_path = tmp_path / "custom.json"
    palette = {"success": "green", "primary_value": "blue"}

    _save_local_search_results("test query", {}, palette, file_path, False)
    assert file_path.exists()


def test_save_local_search_results_default_path(tmp_path, mocker, mock_rich_console):
    """Tests saving when no path is provided (falls back to constant reports dir)."""
    mock_dir = tmp_path / "reports"
    mocker.patch("dorsal.common.constants.CLI_SEARCH_REPORTS_DIR", mock_dir)
    palette = {"success": "green", "primary_value": "blue", "warning": "yellow"}

    _save_local_search_results("test?! query", {}, palette, None, False)

    query_file = mock_dir / "local" / "test_query" / "query.txt"
    assert query_file.exists()
    assert query_file.read_text() == "test?! query"

    json_files = list((mock_dir / "local" / "test_query").glob("*.json"))
    assert len(json_files) == 1


def test_save_local_search_results_untitled_fallback(tmp_path, mocker, mock_rich_console):
    """Tests saving when the query sanitization yields an empty string."""
    mock_dir = tmp_path / "reports"
    mocker.patch("dorsal.common.constants.CLI_SEARCH_REPORTS_DIR", mock_dir)

    _save_local_search_results("!@#$", {}, {"success": "g", "primary_value": "b"}, None, False)

    query_file = mock_dir / "local" / "untitled_search" / "query.txt"
    assert query_file.exists()


def test_save_local_search_results_ioerror_query_txt(tmp_path, mocker, mock_rich_console):
    """Tests the graceful handling of an IOError when writing the query.txt file."""
    mock_dir = tmp_path / "reports"
    mocker.patch("dorsal.common.constants.CLI_SEARCH_REPORTS_DIR", mock_dir)

    # We want open() to fail ONLY when it tries to write query.txt
    original_open = builtins.open

    def mock_open(path, *args, **kwargs):
        if "query.txt" in str(path):
            raise IOError("Simulated query.txt error")
        return original_open(path, *args, **kwargs)

    mocker.patch("builtins.open", side_effect=mock_open)

    _save_local_search_results(
        "test query", {}, {"warning": "yellow", "success": "green", "primary_value": "blue"}, None, False
    )

    output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "Could not write query.txt" in output


def test_save_local_search_results_ioerror_json(tmp_path, mocker, mock_rich_console):
    """Tests the graceful handling of an IOError when writing the final JSON payload."""
    file_path = tmp_path / "custom.json"
    mocker.patch("builtins.open", side_effect=IOError("Simulated json dump error"))

    _save_local_search_results("test query", {}, {"error": "red"}, file_path, False)

    output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list if call.args)
    assert "Could not save JSON report" in output


def test_search_index_implicit_save_with_json_ext(mock_search_index_cmd, tmp_path):
    """Tests that providing a .json output path implicitly enables the save flag."""
    custom_out = tmp_path / "implicit_save.json"

    result = runner.invoke(app, ["index", "search", QUERY, "--output", str(custom_out)])

    assert result.exit_code == 0

    mock_search_index_cmd["save_results"].assert_called_once()
