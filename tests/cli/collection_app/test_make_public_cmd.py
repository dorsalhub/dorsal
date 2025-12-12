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
from dorsal.common.exceptions import DorsalClientError, ConflictError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


@pytest.fixture
def mock_make_public_cmd(mocker):
    """Mocks dependencies for the `collection make-public` command."""
    # Mock the response object returned on success
    mock_response = MagicMock()
    mock_response.location_url = f"https://dorsalhub.test/c/user/{COLLECTION_ID}"

    # Patch the backend function at its source due to lazy loading
    mock_api_call = mocker.patch("dorsal.api.collection.make_collection_public", return_value=mock_response)
    return mock_api_call


def test_make_public_success(mock_rich_console, mock_make_public_cmd):
    """Tests a successful run of the make-public command."""
    result = runner.invoke(app, ["collection", "make-public", COLLECTION_ID])

    assert result.exit_code == 0
    mock_make_public_cmd.assert_called_once_with(collection_id=COLLECTION_ID)

    # Check that a success panel was printed
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Update Complete" in str(printed_object.title)
    assert "Collection is now public" in str(printed_object.renderable)
    assert mock_make_public_cmd.return_value.location_url in str(printed_object.renderable)


def test_make_public_conflict_error(mock_make_public_cmd):
    """Tests handling of a ConflictError (e.g., collection is already public)."""
    error_msg = "Collection is already public."
    mock_make_public_cmd.side_effect = ConflictError(error_msg)

    result = runner.invoke(app, ["collection", "make-public", COLLECTION_ID])

    assert result.exit_code != 0
    assert error_msg in result.output


def test_make_public_api_error(mock_make_public_cmd):
    """Tests handling of a generic DorsalClientError (e.g., not found)."""
    error_msg = "Collection not found."
    mock_make_public_cmd.side_effect = DorsalClientError(error_msg)

    result = runner.invoke(app, ["collection", "make-public", COLLECTION_ID])

    assert result.exit_code != 0
    assert f"API Error: {error_msg}" in result.output
