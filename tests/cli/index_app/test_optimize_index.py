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
def mock_optimize_index_cmd(mocker):
    """Mocks dependencies for the `index optimize` command."""
    # Directly mock the API wrapper instead of the class instance
    mock_optimize = mocker.patch("dorsal.api.index.optimize", return_value=MOCK_OPTIMIZE_RESULTS)
    return {"optimize": mock_optimize}


def test_optimize_index_panel_output(mock_rich_console, mock_optimize_index_cmd):
    """Tests the default command, expecting a Rich Panel summary."""
    result = runner.invoke(app, ["index", "optimize"])

    assert result.exit_code == 0
    mock_optimize_index_cmd["optimize"].assert_called_once()

    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Index Optimization Complete" in str(printed_object.title)


def test_optimize_index_json_output(mock_rich_console, mock_optimize_index_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["index", "optimize", "--json"])

    assert result.exit_code == 0
    mock_optimize_index_cmd["optimize"].assert_called_once()
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data == MOCK_OPTIMIZE_RESULTS


def test_optimize_index_exception_handling(mock_optimize_index_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_optimize_index_cmd["optimize"].side_effect = Exception("General corruption")

    result = runner.invoke(app, ["index", "optimize"])

    assert result.exit_code != 0
    assert "An error occurred while optimizing the search index: General corruption" in result.output
