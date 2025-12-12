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
from unittest.mock import MagicMock
from rich.panel import Panel


from dorsal.cli import app

runner = CliRunner()


MOCK_CACHE_SUMMARY = {
    "database_path": "/fake/home/.dorsal/cache.db",
    "database_size_bytes": 1234567,
    "total_records": 1234,
    "full_records": 1000,
    "hash_only_records": 234,
}


@pytest.fixture
def mock_show_cache_cmd(mocker):
    """Mocks dependencies for the `cache show` command."""
    mock_get_cache = mocker.patch("dorsal.session.get_shared_cache")

    # Configure the mock cache instance that the getter will return
    mock_cache_instance = MagicMock()
    mock_cache_instance.summary.return_value = MOCK_CACHE_SUMMARY
    mock_get_cache.return_value = mock_cache_instance

    return {
        "get_cache": mock_get_cache,
        "cache_instance": mock_cache_instance,
    }


def test_show_cache_panel_output(mock_rich_console, mock_show_cache_cmd):
    """Tests the default command, expecting a Rich Panel."""
    result = runner.invoke(app, ["cache", "show"])

    assert result.exit_code == 0
    mock_show_cache_cmd["cache_instance"].summary.assert_called_once()

    # Verify that a Panel was the object printed to the console
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Cache Summary" in str(printed_object.title)


def test_show_cache_json_output(mock_rich_console, mock_show_cache_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["cache", "show", "--json"])

    assert result.exit_code == 0
    mock_show_cache_cmd["cache_instance"].summary.assert_called_once()
    mock_rich_console.print.assert_called_once()

    # Verify the output is the JSON representation of our mock summary
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data == MOCK_CACHE_SUMMARY


def test_show_cache_exception_handling(mock_show_cache_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_show_cache_cmd["get_cache"].side_effect = Exception("Permission denied")

    result = runner.invoke(app, ["cache", "show"])

    assert result.exit_code != 0
    assert "An error occurred while getting cache info: Permission denied" in result.output
