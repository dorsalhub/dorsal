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

MOCK_OPTIMIZE_RESULTS = {
    "stale_records_removed": 15,
    "records_rewritten_for_compression": 100,
    "size_before_bytes": 20480,
    "size_after_bytes": 10240,
    "size_reclaimed_bytes": 10240,
}


@pytest.fixture
def mock_optimize_cache_cmd(mocker):
    """Mocks dependencies for the `cache optimize` command."""
    # Patch at the source due to lazy loading in the command
    mock_get_cache = mocker.patch("dorsal.session.get_shared_cache")

    # Configure the mock cache instance that the getter will return
    mock_cache_instance = MagicMock()
    mock_cache_instance.optimize.return_value = MOCK_OPTIMIZE_RESULTS
    mock_get_cache.return_value = mock_cache_instance

    return {"get_cache": mock_get_cache, "cache_instance": mock_cache_instance}


def test_optimize_cache_panel_output(mock_rich_console, mock_optimize_cache_cmd):
    """Tests the default command, expecting a Rich Panel summary."""
    result = runner.invoke(app, ["cache", "optimize"])

    assert result.exit_code == 0
    mock_optimize_cache_cmd["cache_instance"].optimize.assert_called_once()

    # Verify that a Panel was the object printed to the console
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Cache Optimization Complete" in str(printed_object.title)


def test_optimize_cache_json_output(mock_rich_console, mock_optimize_cache_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["cache", "optimize", "--json"])

    assert result.exit_code == 0
    mock_optimize_cache_cmd["cache_instance"].optimize.assert_called_once()
    mock_rich_console.print.assert_called_once()

    # Verify the output is the JSON representation of our mock results
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data == MOCK_OPTIMIZE_RESULTS


def test_optimize_cache_exception_handling(mock_optimize_cache_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_optimize_cache_cmd["cache_instance"].optimize.side_effect = Exception("General corruption")

    result = runner.invoke(app, ["cache", "optimize"])

    assert result.exit_code != 0
    assert "An error occurred while optimizing the cache: General corruption" in result.output
