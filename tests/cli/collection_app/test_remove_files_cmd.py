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
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


@pytest.fixture
def mock_remove_files_cmd(mocker):
    """Mocks dependencies for the `collection remove-files` command."""
    mock_remove_response = MagicMock()
    mock_remove_response.removed_count = 2
    mock_remove_response.not_found_count = 1
    mock_remove_response.model_dump_json.return_value = "{}"

    # Patch the backend API function at its source due to lazy loading
    mock_remove = mocker.patch(
        "dorsal.api.collection.remove_files_from_collection",
        return_value=mock_remove_response,
    )

    return {
        "remove_files": mock_remove,
        "remove_response": mock_remove_response,
    }


def test_remove_files_with_hash_options(mock_rich_console, mock_remove_files_cmd):
    """Tests removing files using multiple --hash options."""
    hashes_to_remove = ["hash1", "hash2"]
    result = runner.invoke(
        app,
        [
            "collection",
            "remove-files",
            COLLECTION_ID,
            "--hash",
            hashes_to_remove[0],
            "--hash",
            hashes_to_remove[1],
        ],
    )

    assert result.exit_code == 0
    # The command may change the order, so we check the contents
    called_hashes = mock_remove_files_cmd["remove_files"].call_args.kwargs["hashes"]
    assert sorted(called_hashes) == sorted(hashes_to_remove)

    # Check for the success panel
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Update Complete" in str(printed_object.title)


def test_remove_files_from_stdin(mock_rich_console, mock_remove_files_cmd, mocker):
    """Tests removing files by reading hashes from stdin."""
    hashes_to_remove = ["hash1", "hash2", "hash3"]

    mocker.patch(
        "dorsal.cli.collection_app.remove_files_cmd._get_hashes",
        return_value=hashes_to_remove,
    )

    result = runner.invoke(
        app,
        [
            "collection",
            "remove-files",
            COLLECTION_ID,
            "--from-stdin",
        ],
    )

    assert result.exit_code == 0
    called_hashes = mock_remove_files_cmd["remove_files"].call_args.kwargs["hashes"]
    assert sorted(called_hashes) == sorted(hashes_to_remove)


def test_remove_files_no_hashes_error():
    """Tests that the command fails if no hashes are provided."""
    result = runner.invoke(app, ["collection", "remove-files", COLLECTION_ID])

    assert result.exit_code != 0
    assert "No file hashes provided" in result.output


def test_remove_files_json_output(mock_rich_console, mock_remove_files_cmd):
    """Tests a successful remove with --json output."""
    result = runner.invoke(app, ["collection", "remove-files", COLLECTION_ID, "--hash", "hash1", "--json"])

    assert result.exit_code == 0
    mock_remove_files_cmd["remove_response"].model_dump_json.assert_called_once()
    mock_rich_console.print.assert_called_once_with(
        mock_remove_files_cmd["remove_response"].model_dump_json.return_value
    )


def test_remove_files_with_not_found_count(mock_rich_console, mock_remove_files_cmd):
    """Tests that the panel correctly reports files that were not found."""
    mock_remove_files_cmd["remove_response"].not_found_count = 1

    result = runner.invoke(app, ["collection", "remove-files", COLLECTION_ID, "--hash", "hash1"])

    assert result.exit_code == 0
    printed_object = mock_rich_console.print.call_args.args[0]
    panel_text = str(printed_object.renderable)
    assert "Removed: 2" in panel_text
    assert "Not Found (ignored): 1" in panel_text


def test_remove_files_api_error(mock_remove_files_cmd):
    """Tests graceful failure on a DorsalClientError."""
    mock_remove_files_cmd["remove_files"].side_effect = DorsalClientError("Collection not found")

    result = runner.invoke(app, ["collection", "remove-files", COLLECTION_ID, "--hash", "hash1"])

    assert result.exit_code != 0
    assert "API Error: Collection not found" in result.output
