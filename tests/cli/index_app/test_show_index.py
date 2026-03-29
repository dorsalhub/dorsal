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
from typer.testing import CliRunner
from rich.panel import Panel
from rich.console import Group

from dorsal.cli import app

runner = CliRunner()


MOCK_INDEX_SUMMARY = {
    "database_path": "/fake/home/.dorsal/cache.db",
    "database_size_bytes": 1234567,
    "total_records": 1234,
    "full_records": 1000,
    "hash_only_records": 234,
}


@pytest.fixture
def mock_show_index_cmd(mocker):
    """Mocks dependencies for the `index show` command."""
    # Mocking the new API function directly
    mock_summary = mocker.patch("dorsal.api.index.summary", return_value=MOCK_INDEX_SUMMARY)
    return {"summary": mock_summary}


def test_show_index_panel_output(mock_rich_console, mock_show_index_cmd):
    """Tests the default command, expecting a Rich Panel or Group."""
    result = runner.invoke(app, ["index", "show"])

    assert result.exit_code == 0
    mock_show_index_cmd["summary"].assert_called_once()

    # Verify that a Panel or Group was the object printed to the console
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, (Panel, Group))


def test_show_index_json_output(mock_rich_console, mock_show_index_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["index", "show", "--json"])

    assert result.exit_code == 0
    mock_show_index_cmd["summary"].assert_called_once()
    mock_rich_console.print.assert_called_once()

    # Verify the output is the JSON representation of our mock summary
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data == MOCK_INDEX_SUMMARY


def test_show_index_exception_handling(mock_show_index_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_show_index_cmd["summary"].side_effect = PermissionError("Permission denied")

    result = runner.invoke(app, ["index", "show"])

    assert result.exit_code != 0
    assert "An error occurred while getting search index info: Permission denied" in result.output
