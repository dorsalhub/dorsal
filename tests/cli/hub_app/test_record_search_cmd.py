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

import pytest
import json
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY
from rich.console import Console
from rich.table import Table


from dorsal.cli import app
from dorsal.cli.hub_app.remote_search import search_and_display
from dorsal.common.exceptions import AuthError, DorsalClientError, ForbiddenError

runner = CliRunner()
QUERY = "extension:pdf"


def _render(renderable, width: int = 120) -> str:
    console = Console(width=width)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _printed_table(mock_console) -> Table:
    tables = [call.args[0] for call in mock_console.print.call_args_list if isinstance(call.args[0], Table)]
    assert len(tables) == 1
    return tables[0]


@pytest.fixture
def mock_search_cmd(mocker):
    """Mocks dependencies for the search commands."""
    mock_base_record = MagicMock()
    mock_base_record.name = "test.pdf"
    mock_base_record.size = 12345
    mock_base_record.media_type = "application/pdf"

    mock_record = MagicMock()
    mock_record.annotations.file_base.record = mock_base_record
    mock_record.hash = "sha256:mockhash123"

    mock_response = MagicMock()
    mock_response.api_version = "v2"
    mock_response.results = [mock_record]
    mock_response.pagination = MagicMock(page_count=1, has_next=False)
    mock_response.model_dump.return_value = {"results": [{"hash": "mock_hash"}]}

    mock_user_search = mocker.patch("dorsal.api.file.search_user_files", return_value=mock_response)
    mock_global_search = mocker.patch("dorsal.api.file.search_global_files", return_value=mock_response)

    mock_save_helper = mocker.patch("dorsal.cli.hub_app.remote_search._save_search_results")

    return {
        "user_search": mock_user_search,
        "global_search": mock_global_search,
        "save_results": mock_save_helper,
    }


@pytest.mark.parametrize("command_path", [["hub", "search"]])
def test_search_user_scope_default(command_path, mock_rich_console, mock_search_cmd):
    """Tests a default search in the user scope, via both command paths."""
    result = runner.invoke(app, command_path + [QUERY])

    assert result.exit_code == 0
    mock_search_cmd["user_search"].assert_called_once_with(
        query=QUERY,
        page=1,
        per_page=25,
        sort_by="date_modified",
        sort_order="desc",
        match_any=False,
        mode="pydantic",
        deep=False,
    )
    mock_search_cmd["global_search"].assert_not_called()
    mock_search_cmd["save_results"].assert_not_called()

    assert isinstance(mock_rich_console.print.call_args_list[0].args[0], Table)


def test_search_global_scope(mock_rich_console, mock_search_cmd):
    """Tests a search in the global scope using the --global flag."""
    result = runner.invoke(app, ["hub", "search", QUERY, "--global"])

    assert result.exit_code == 0
    mock_search_cmd["global_search"].assert_called_once()
    mock_search_cmd["user_search"].assert_not_called()


def test_search_json_output(mock_rich_console, mock_search_cmd):
    """Tests a successful search with --json output."""
    result = runner.invoke(app, ["hub", "search", QUERY, "--json"])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 1

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data["results"][0]["hash"] == "mock_hash"
    mock_search_cmd["save_results"].assert_not_called()


def test_search_no_results(mock_rich_console, mock_search_cmd):
    """Tests the output when a search yields no results."""
    mock_search_cmd["user_search"].return_value.results = []

    result = runner.invoke(app, ["hub", "search", QUERY])

    assert result.exit_code == 0
    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "No records found" in all_output


def test_search_forbidden_error_premium_feature(mock_rich_console, mock_search_cmd, mock_error_console):
    """Tests the specific error handling for the premium feature gate."""
    mock_search_cmd["global_search"].side_effect = ForbiddenError("test")

    result = runner.invoke(app, ["hub", "search", QUERY, "--global"])

    assert result.exit_code == 0

    output = _render(mock_error_console.print.call_args.args[0])
    assert output.startswith("Upgrade required\n")
    assert "premium feature" in output
    assert "https://dorsalhub.com/pricing" in output
    mock_rich_console.print.assert_not_called()


def test_search_auto_save_with_json_output_path(mock_rich_console, mock_search_cmd):
    """Tests that --output with a .json file automatically enables the save routine."""
    result = runner.invoke(app, ["hub", "search", QUERY, "--output", "custom_results.json"])

    assert result.exit_code == 0

    mock_search_cmd["save_results"].assert_called_once()


def test_search_borderless_by_default(mock_rich_console, mock_search_cmd):
    """By default the results are a plain titled table with no box characters or trailing whitespace."""
    result = runner.invoke(app, ["hub", "search", QUERY])

    assert result.exit_code == 0

    output = _render(_printed_table(mock_rich_console))
    lines = output.splitlines()
    assert lines[0] == "User search results"
    assert lines[1].startswith("Name ")
    assert "Media type" in lines[1]
    assert "test.pdf" in output
    assert not any(ch in output for ch in "│─╭╰")
    assert all(line == line.rstrip() for line in lines)
    assert "https://docs.dorsalhub.com/reference/search-syntax/" in output


def test_search_bordered(mock_rich_console, mock_search_cmd):
    """With --borders rounded the results table is boxed."""
    result = runner.invoke(app, ["--borders", "rounded", "hub", "search", QUERY])

    assert result.exit_code == 0

    output = _render(_printed_table(mock_rich_console))
    assert "User search results" in output.splitlines()[0]
    assert "╭" in output
    assert "test.pdf" in output


def test_search_unknown_output_extension_warns_on_stderr(mock_rich_console, mock_error_console, mock_search_cmd):
    """An --output path with an unknown extension is warned about on stderr."""
    result = runner.invoke(app, ["hub", "search", QUERY, "--output", "results.txt"])

    assert result.exit_code == 0
    warnings = [str(call.args[0]) for call in mock_error_console.print.call_args_list]
    assert any("Warning:" in w and "unknown extension" in w for w in warnings)
    assert not any("unknown extension" in str(call.args[0]) for call in mock_rich_console.print.call_args_list)


def test_search_narrow_console_and_missing_annotations(mock_rich_console, mock_search_cmd, caplog):
    """Tests the condensed table layout (< 115 width) and skipping records with missing annotations."""

    mock_rich_console.width = 100

    bad_record = MagicMock()
    bad_record.annotations = None
    bad_record.hash = "bad_hash_narrow"

    good_record = mock_search_cmd["user_search"].return_value.results[0]
    mock_search_cmd["user_search"].return_value.results = [bad_record, good_record]

    import logging

    with caplog.at_level(logging.WARNING):
        result = runner.invoke(app, ["hub", "search", QUERY])

    assert result.exit_code == 0

    assert "Search result with hash bad_hash_narrow is missing base annotations, skipping." in caplog.text

    printed_table = _printed_table(mock_rich_console)
    assert len(printed_table.columns) == 2
    assert printed_table.columns[0].header == "File details (name / hash)"


def test_search_wide_console_missing_annotations(mock_rich_console, mock_search_cmd, caplog):
    """Tests skipping records with missing annotations in the standard wide layout (>= 115 width)."""

    mock_rich_console.width = 120

    bad_record = MagicMock()
    bad_record.annotations = None
    bad_record.hash = "bad_hash_wide"

    mock_search_cmd["user_search"].return_value.results = [bad_record]

    import logging

    with caplog.at_level(logging.WARNING):
        result = runner.invoke(app, ["hub", "search", QUERY])

    assert result.exit_code == 0
    assert "Search result with hash bad_hash_wide is missing base annotations, skipping." in caplog.text

    printed_table = _printed_table(mock_rich_console)
    assert len(printed_table.columns) == 4
    assert printed_table.columns[0].header == "Name"
    assert len(printed_table.rows) == 0
