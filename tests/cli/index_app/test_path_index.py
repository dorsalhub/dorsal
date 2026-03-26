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

from dorsal.cli import app

runner = CliRunner()

FAKE_INDEX_PATH = "/fake/home/.dorsal/cache.db"


@pytest.fixture
def mock_path_index_cmd(mocker):
    """Mocks dependencies for the `index path` command."""
    mock_get_path = mocker.patch("dorsal.api.index.get_path", return_value=FAKE_INDEX_PATH)
    return {"get_path": mock_get_path}


def test_get_index_path_plain_output(mock_rich_console, mock_path_index_cmd):
    """Tests the default command, expecting the plain path string."""
    result = runner.invoke(app, ["index", "path"])

    assert result.exit_code == 0
    mock_path_index_cmd["get_path"].assert_called_once()
    mock_rich_console.print.assert_called_once_with(FAKE_INDEX_PATH)


def test_get_index_path_json_output(mock_rich_console, mock_path_index_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["index", "path", "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {"path": FAKE_INDEX_PATH}


def test_get_index_path_exception_handling(mock_path_index_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_path_index_cmd["get_path"].side_effect = Exception("Index system unavailable")

    result = runner.invoke(app, ["index", "path"])

    assert result.exit_code != 0
    assert "An error occurred while getting index path: Index system unavailable" in result.output
