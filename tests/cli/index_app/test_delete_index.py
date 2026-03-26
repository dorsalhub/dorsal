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
from typer.testing import CliRunner
from unittest.mock import MagicMock

from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_delete_index_cmd(mocker):
    """Mocks dependencies for the `index delete` command."""
    mock_get_index = mocker.patch("dorsal.session.get_shared_index")
    mock_clear_shared_index = mocker.patch("dorsal.session.clear_shared_index")

    mock_index_instance = MagicMock()
    mock_index_instance.db_path.resolve.return_value = "/fake/home/.dorsal/cache.db"
    mock_get_index.return_value = mock_index_instance

    return {
        "get_index": mock_get_index,
        "clear_shared_index": mock_clear_shared_index,
        "index_instance": mock_index_instance,
    }


def test_delete_index_with_yes_flag(mock_rich_console, mock_delete_index_cmd):
    """Tests clearing the index with the --yes flag."""
    result = runner.invoke(app, ["index", "delete", "--yes"])

    assert result.exit_code == 0
    mock_delete_index_cmd["index_instance"].clear.assert_called_once()
    mock_delete_index_cmd["clear_shared_index"].assert_called_once()

    success_msg = mock_rich_console.print.call_args.args[0]
    assert "Search Index cleared successfully" in success_msg


def test_delete_index_with_confirmation_yes(mock_rich_console, mock_delete_index_cmd):
    """Tests clearing the index by answering 'y' to the interactive prompt."""
    result = runner.invoke(app, ["index", "delete"], input="y\n")

    assert result.exit_code == 0
    mock_delete_index_cmd["index_instance"].clear.assert_called_once()
    mock_delete_index_cmd["clear_shared_index"].assert_called_once()

    success_msg = mock_rich_console.print.call_args.args[0]
    assert "Search Index cleared successfully" in success_msg


def test_delete_index_cancelled(mock_rich_console, mock_delete_index_cmd):
    """Tests cancelling the clear command by answering 'n' to the prompt."""
    result = runner.invoke(app, ["index", "delete"], input="n\n")

    assert result.exit_code == 0
    cancelled_msg = mock_rich_console.print.call_args.args[0]
    assert "Search index clearing cancelled" in cancelled_msg

    mock_delete_index_cmd["index_instance"].clear.assert_not_called()
    mock_delete_index_cmd["clear_shared_index"].assert_not_called()


def test_delete_index_exception_handling(mock_delete_index_cmd):
    """Tests that an exception during the clear operation is handled gracefully."""
    mock_delete_index_cmd["index_instance"].clear.side_effect = OSError("Permission denied")

    result = runner.invoke(app, ["index", "delete", "--yes"])

    assert result.exit_code != 0
    assert "An error occurred while clearing the search index: Permission denied" in result.output
