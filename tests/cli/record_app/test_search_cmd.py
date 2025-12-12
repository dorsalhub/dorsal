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
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY
from rich.table import Table
from rich.panel import Panel


from dorsal.cli import app
from dorsal.cli.search_app import search_and_display
from dorsal.common.exceptions import AuthError, DorsalClientError, ForbiddenError

runner = CliRunner()
QUERY = "extension:pdf"


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

    # Create a mock pydantic-style response object
    mock_response = MagicMock()
    mock_response.api_version = "v2"
    mock_response.results = [mock_record]  # Use the configured mock record
    mock_response.pagination = MagicMock(page_count=1, has_next=False)
    mock_response.model_dump.return_value = {"results": [{"hash": "mock_hash"}]}

    # Patch the backend search functions at their source
    mock_user_search = mocker.patch("dorsal.api.file.search_user_files", return_value=mock_response)
    mock_global_search = mocker.patch("dorsal.api.file.search_global_files", return_value=mock_response)

    # Patch the helper that saves reports to the filesystem
    mock_save_helper = mocker.patch("dorsal.cli.search_app._save_search_results")

    return {
        "user_search": mock_user_search,
        "global_search": mock_global_search,
        "save_results": mock_save_helper,
    }


@pytest.mark.parametrize("command_path", [["search"], ["record", "search"]])
def test_search_user_scope_default(command_path, mock_rich_console, mock_search_cmd):
    """Tests a default search in the user scope, via both command paths."""
    result = runner.invoke(app, command_path + [QUERY])

    assert result.exit_code == 0
    mock_search_cmd["user_search"].assert_called_once_with(
        query=QUERY,
        page=1,
        per_page=30,
        sort_by="date_modified",
        sort_order="desc",
        match_any=False,
        mode="pydantic",
    )
    mock_search_cmd["global_search"].assert_not_called()
    mock_search_cmd["save_results"].assert_not_called()

    # Verify that a Table was printed. The search message is the first print call, the table is the second.
    printed_object = mock_rich_console.print.call_args_list[1].args[0]
    assert isinstance(printed_object, Table)


def test_search_global_scope(mock_rich_console, mock_search_cmd):
    """Tests a search in the global scope using the --global flag."""
    result = runner.invoke(app, ["record", "search", QUERY, "--global"])

    assert result.exit_code == 0
    mock_search_cmd["global_search"].assert_called_once()
    mock_search_cmd["user_search"].assert_not_called()


def test_search_json_output(mock_rich_console, mock_search_cmd):
    """Tests a successful search with --json output."""
    result = runner.invoke(app, ["record", "search", QUERY, "--json"])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 1

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data["results"][0]["hash"] == "mock_hash"
    mock_search_cmd["save_results"].assert_not_called()


def test_search_no_results(mock_rich_console, mock_search_cmd):
    """Tests the output when a search yields no results."""
    mock_search_cmd["user_search"].return_value.results = []

    result = runner.invoke(app, ["record", "search", QUERY])

    assert result.exit_code == 0
    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "No records found" in all_output


def test_search_forbidden_error_premium_feature(mock_rich_console, mock_search_cmd):
    """Tests the specific error handling for the premium feature gate."""
    mock_search_cmd["global_search"].side_effect = ForbiddenError("test")

    result = runner.invoke(app, ["record", "search", QUERY, "--global"])

    assert result.exit_code == 0  # Graceful exit with an upgrade message
    # Verify the special upgrade panel was printed
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Upgrade Required" in str(printed_object.title)


def test_search_api_error(mock_search_cmd):
    """Tests the handling of a generic API error."""
    mock_search_cmd["user_search"].side_effect = DorsalClientError("Invalid query syntax")

    result = runner.invoke(app, ["record", "search", QUERY])

    assert result.exit_code != 0
    assert "API Error: Invalid query syntax" in result.output
