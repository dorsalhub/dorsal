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
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.panel import Panel


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


@pytest.fixture
def mock_update_collection_cmd(mocker):
    """Mocks dependencies for the `collection update` command."""
    # Mock the Pydantic model that is returned on a successful update
    mock_updated_collection = MagicMock()
    mock_updated_collection.name = "My Updated Collection Name"

    # Patch the backend API function at its source due to lazy loading
    mock_update = mocker.patch("dorsal.api.collection.update_collection", return_value=mock_updated_collection)
    return mock_update


def test_update_collection_name_and_desc(mock_rich_console, mock_update_collection_cmd):
    """Tests updating both name and description successfully."""
    result = runner.invoke(
        app,
        [
            "collection",
            "update",
            COLLECTION_ID,
            "--name",
            "New Name",
            "--description",
            "New Desc",
        ],
    )

    assert result.exit_code == 0
    mock_update_collection_cmd.assert_called_once_with(
        collection_id=COLLECTION_ID,
        name="New Name",
        description="New Desc",
        mode="pydantic",
    )

    # Check that a success panel was printed
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Update Complete" in str(printed_object.title)
    assert "updated successfully" in str(printed_object.renderable)


def test_update_collection_only_name(mock_rich_console, mock_update_collection_cmd):
    """Tests updating only the collection name."""
    runner.invoke(app, ["collection", "update", COLLECTION_ID, "--name", "Only The Name"])

    mock_update_collection_cmd.assert_called_once_with(
        collection_id=COLLECTION_ID,
        name="Only The Name",
        description=None,
        mode="pydantic",
    )


def test_update_collection_only_desc(mock_rich_console, mock_update_collection_cmd):
    """Tests updating only the collection description."""
    runner.invoke(app, ["collection", "update", COLLECTION_ID, "--description", "Only The Desc"])

    mock_update_collection_cmd.assert_called_once_with(
        collection_id=COLLECTION_ID,
        name=None,
        description="Only The Desc",
        mode="pydantic",
    )


def test_update_collection_no_options_error(mock_update_collection_cmd):
    """Tests that providing no update options results in a ValueError from the API."""
    error_msg = "At least one field (name or description) must be provided to update."
    mock_update_collection_cmd.side_effect = ValueError(error_msg)

    result = runner.invoke(app, ["collection", "update", COLLECTION_ID])

    assert result.exit_code != 0
    assert error_msg in result.output


def test_update_collection_api_error(mock_update_collection_cmd):
    """Tests graceful failure on a DorsalClientError."""
    mock_update_collection_cmd.side_effect = DorsalClientError("Collection not found")

    result = runner.invoke(app, ["collection", "update", COLLECTION_ID, "--name", "New Name"])

    assert result.exit_code != 0
    assert "API Error: Collection not found" in result.output
