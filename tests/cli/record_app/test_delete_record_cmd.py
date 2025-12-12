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
from dorsal.common.exceptions import DorsalClientError, NotFoundError

runner = CliRunner()
HASH_STRING = "sha256:123abc456def"


@pytest.fixture
def mock_delete_cmd(mocker):
    """Mocks dependencies for the `record delete` command."""
    # Mock API responses
    mock_delete_response = MagicMock()
    mock_delete_response.file_deleted = 1
    mock_delete_response.file_modified = 0
    mock_delete_response.tags_deleted = 5
    mock_delete_response.annotations_deleted = 2
    mock_delete_response.model_dump_json.return_value = "{}"

    mock_get_response = MagicMock()
    mock_get_response.model_dump.return_value = {"name": "file_to_delete.txt"}

    # Patch dependencies at their source due to lazy loading
    mock_delete = mocker.patch("dorsal.api.file._delete_dorsal_file_record", return_value=mock_delete_response)
    mock_get = mocker.patch("dorsal.api.file.get_dorsal_file_record", return_value=mock_get_response)

    # Patch the view helper
    mock_create_panel = mocker.patch("dorsal.cli.views.file.create_file_info_panel")

    return {
        "delete_record": mock_delete,
        "get_record": mock_get,
        "create_panel": mock_create_panel,
        "delete_response": mock_delete_response,
    }


def test_delete_record_with_yes_flag(mock_rich_console, mock_delete_cmd):
    """Tests a non-interactive delete using the --yes flag."""
    result = runner.invoke(app, ["record", "delete", HASH_STRING, "--yes"])

    assert result.exit_code == 0
    mock_delete_cmd["delete_record"].assert_called_once_with(
        file_hash=HASH_STRING, record="all", tags="all", annotations="all"
    )
    # get_record should NOT be called in non-interactive mode
    mock_delete_cmd["get_record"].assert_not_called()

    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Deletion Complete" in str(printed_object.title)


def test_delete_record_interactive_confirm(mock_rich_console, mock_delete_cmd):
    """Tests an interactive delete where the user confirms with 'y'."""
    result = runner.invoke(app, ["record", "delete", HASH_STRING], input="y\n")

    assert result.exit_code == 0
    mock_delete_cmd["get_record"].assert_called_once()
    mock_delete_cmd["create_panel"].assert_called_once()
    mock_delete_cmd["delete_record"].assert_called_once()

    # The last thing printed should be the success panel
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Deletion Complete" in str(printed_object.title)


def test_delete_record_interactive_abort(mock_rich_console, mock_delete_cmd):
    """Tests aborting an interactive delete."""
    result = runner.invoke(app, ["record", "delete", HASH_STRING], input="n\n")

    assert result.exit_code == 0  # The command catches the abort and exits cleanly
    mock_delete_cmd["delete_record"].assert_not_called()

    aborted_msg = mock_rich_console.print.call_args.args[0]
    assert "Deletion aborted by user" in aborted_msg


def test_delete_record_success_json_output(mock_rich_console, mock_delete_cmd):
    """Tests a successful delete with --json output."""
    result = runner.invoke(app, ["record", "delete", HASH_STRING, "--yes", "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    mock_delete_cmd["delete_response"].model_dump_json.assert_called_once()
    assert mock_rich_console.print.call_args.args[0] == mock_delete_cmd["delete_response"].model_dump_json.return_value


def test_delete_record_not_found(mock_rich_console, mock_delete_cmd):
    """Tests error handling when the record to delete is not found in interactive mode."""
    mock_delete_cmd["get_record"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["record", "delete", HASH_STRING])  # No --yes flag

    assert result.exit_code != 0
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Error" in str(printed_object.title)
    assert "Cannot delete" in str(printed_object.renderable)
    assert "not found" in str(printed_object.renderable)


def test_delete_record_flag_conflict(mock_rich_console):
    """Tests that using an invalid scope for a granular delete option fails."""
    result = runner.invoke(
        app,
        ["record", "delete", HASH_STRING, "--record", "invalid-scope"],
        env={"TERM": "dumb"},  # force plain-text
    )

    assert result.exit_code != 0

    assert "Invalid value for '--record'" in result.output

    mock_rich_console.print.assert_not_called()
