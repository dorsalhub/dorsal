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
import datetime
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.table import Table


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()


mock_collection_record = MagicMock()
mock_collection_record.collection_id = "col_abc123"
mock_collection_record.name = "My Research Data"
mock_collection_record.file_count = 152
mock_collection_record.total_size = 545259520  # 520 MiB
mock_collection_record.is_private = True
mock_collection_record.date_modified = datetime.datetime(2025, 8, 9, 10, 30)

mock_pagination = MagicMock()
mock_pagination.page_count = 1
mock_pagination.current_page = 1
mock_pagination.start_index = 1
mock_pagination.end_index = 1
mock_pagination.record_count = 1
mock_pagination.has_next = False

MOCK_API_RESPONSE = MagicMock()
MOCK_API_RESPONSE.records = [mock_collection_record]
MOCK_API_RESPONSE.pagination = mock_pagination
MOCK_API_RESPONSE.model_dump_json.return_value = json.dumps(
    {
        "records": [{"collection_id": "col_abc123", "name": "My Research Data"}],
        "pagination": {"page_count": 1, "record_count": 1},
    }
)


@pytest.fixture
def mock_list_collections_cmd(mocker):
    """Mocks dependencies for the `collection list` command."""
    # Patch list_collections at its source due to lazy loading in the command
    mock_list = mocker.patch("dorsal.api.collection.list_collections", return_value=MOCK_API_RESPONSE)
    return mock_list


def test_list_collections_success_table_output(mock_rich_console, mock_list_collections_cmd):
    """Tests the default command, expecting a Rich Table."""
    result = runner.invoke(app, ["collection", "list"])

    assert result.exit_code == 0
    mock_list_collections_cmd.assert_called_once_with(page=1, per_page=25, mode="pydantic")

    # The command prints a status message, then the table
    assert mock_rich_console.print.call_count == 2
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Table)
    assert "DorsalHub Collections" in str(printed_object.title)


def test_list_collections_with_pagination(mock_rich_console, mock_list_collections_cmd):
    """Tests that the pagination footer is displayed correctly."""
    mock_list_collections_cmd.return_value.pagination.page_count = 5
    mock_list_collections_cmd.return_value.pagination.has_next = True

    result = runner.invoke(app, ["collection", "list"])

    assert result.exit_code == 0
    # Combine all printed output to check for the footer
    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "Showing page 1 of 5" in all_printed_text
    assert "To see the next page, run the command again with --page 2" in all_printed_text


def test_list_collections_no_results(mock_rich_console, mock_list_collections_cmd):
    """Tests the output when no collections are found."""

    mock_list_collections_cmd.return_value.records = []

    result = runner.invoke(app, ["collection", "list"])

    assert result.exit_code == 0
    info_message = mock_rich_console.print.call_args.args[0]
    assert "No collections found" in info_message


def test_list_collections_json_output(mock_rich_console, mock_list_collections_cmd):
    """Tests the --json output."""
    result = runner.invoke(app, ["collection", "list", "--json"])

    assert result.exit_code == 0
    # Verifies the model's dump method was called and the result printed
    mock_list_collections_cmd.return_value.model_dump_json.assert_called_once()
    mock_rich_console.print.assert_called_once_with(mock_list_collections_cmd.return_value.model_dump_json.return_value)


def test_list_collections_api_error(mock_list_collections_cmd):
    """Tests graceful failure on a DorsalClientError."""
    mock_list_collections_cmd.side_effect = DorsalClientError("Authentication failed")

    result = runner.invoke(app, ["collection", "list"])

    assert result.exit_code != 0
    assert "API Error: Authentication failed" in result.output
