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


from dorsal.cli import app

runner = CliRunner()

FAKE_CACHE_PATH = "/fake/home/.dorsal/cache.db"


@pytest.fixture
def mock_path_cache_cmd(mocker):
    """Mocks dependencies for the `cache path` command."""
    # Patch at the source due to lazy loading in the command
    mock_get_cache = mocker.patch("dorsal.session.get_shared_cache")

    # Configure the mock cache instance and its path attribute so .resolve() can be called
    mock_cache_instance = MagicMock()
    mock_cache_instance.db_path.resolve.return_value = FAKE_CACHE_PATH
    mock_get_cache.return_value = mock_cache_instance

    return {
        "get_cache": mock_get_cache,
    }


def test_get_cache_path_plain_output(mock_rich_console, mock_path_cache_cmd):
    """Tests the default command, expecting the plain path string."""
    result = runner.invoke(app, ["cache", "path"])

    assert result.exit_code == 0
    mock_path_cache_cmd["get_cache"].assert_called_once()
    mock_rich_console.print.assert_called_once_with(FAKE_CACHE_PATH)


def test_get_cache_path_json_output(mock_rich_console, mock_path_cache_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["cache", "path", "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {"path": FAKE_CACHE_PATH}


def test_get_cache_path_exception_handling(mock_path_cache_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_path_cache_cmd["get_cache"].side_effect = Exception("Cache system unavailable")

    result = runner.invoke(app, ["cache", "path"])

    assert result.exit_code != 0
    assert "An error occurred while getting cache path: Cache system unavailable" in result.output
