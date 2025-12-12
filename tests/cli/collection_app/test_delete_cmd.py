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
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


@pytest.fixture
def mock_delete_collection_cmd(mocker):
    """Mocks dependencies for the `collection delete` command."""
    # Patch the backend API function at its source due to lazy loading
    mock_delete = mocker.patch("dorsal.api.collection.delete_collection")
    return mock_delete


def test_delete_collection_with_yes_flag(mock_rich_console, mock_delete_collection_cmd):
    """Tests a non-interactive delete with the --yes flag."""
    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID, "--yes"])

    assert result.exit_code == 0
    mock_delete_collection_cmd.assert_called_once_with(collection_id=COLLECTION_ID)

    # The command prints a status message, then the success message
    success_msg = mock_rich_console.print.call_args_list[1].args[0]
    assert f"Collection '{COLLECTION_ID}' was successfully deleted" in success_msg


def test_delete_collection_with_confirmation_yes(mock_rich_console, mock_delete_collection_cmd):
    """Tests an interactive delete by confirming 'y'."""
    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID], input="y\n")

    assert result.exit_code == 0
    mock_delete_collection_cmd.assert_called_once()

    success_msg = mock_rich_console.print.call_args_list[1].args[0]
    assert f"Collection '{COLLECTION_ID}' was successfully deleted" in success_msg


def test_delete_collection_aborted(mock_delete_collection_cmd):
    """Tests aborting an interactive delete by confirming 'n'."""
    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID], input="n\n")

    assert result.exit_code != 0
    assert "Aborted." in result.output
    mock_delete_collection_cmd.assert_not_called()


def test_delete_collection_success_json_output(mock_rich_console, mock_delete_collection_cmd):
    """Tests a successful delete with --json output."""
    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID, "--yes", "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {"success": True, "collection_id": COLLECTION_ID, "deleted": True}


def test_delete_collection_api_error_panel_output(mock_delete_collection_cmd):
    """Tests an API error with standard panel output."""
    mock_delete_collection_cmd.side_effect = DorsalClientError("Permission denied")

    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID, "--yes"])

    assert result.exit_code != 0
    assert "API Error: Permission denied" in result.output


def test_delete_collection_api_error_json_output(mock_rich_console, mock_delete_collection_cmd):
    """Tests an API error with --json output."""
    mock_delete_collection_cmd.side_effect = DorsalClientError("Permission denied")

    result = runner.invoke(app, ["collection", "delete", COLLECTION_ID, "--yes", "--json"])

    assert result.exit_code != 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {
        "success": False,
        "error": "Permission denied",
        "collection_id": COLLECTION_ID,
    }
