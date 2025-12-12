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
from rich.table import Table
from rich.panel import Panel


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError, NotFoundError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


mock_file = MagicMock()
mock_file.name = "research_paper.pdf"
mock_file.size = 1048576
mock_file.media_type = "application/pdf"
mock_file.hash = "sha256:mockhash123"

mock_collection = MagicMock()
mock_collection.file_count = 1


mock_pagination = MagicMock()
mock_pagination.page_count = 1


MOCK_API_RESPONSE = MagicMock()
MOCK_API_RESPONSE.collection = mock_collection
MOCK_API_RESPONSE.files = [mock_file]
MOCK_API_RESPONSE.pagination = mock_pagination
MOCK_API_RESPONSE.model_dump_json.return_value = json.dumps(
    {
        "collection": {"id": COLLECTION_ID, "file_count": 1},
        "files": [{"name": "research_paper.pdf"}],
    }
)


@pytest.fixture
def mock_show_collection_cmd(mocker):
    """Mocks dependencies for the `collection show` command."""
    mock_get = mocker.patch("dorsal.api.collection.get_collection", return_value=MOCK_API_RESPONSE)

    mock_view = mocker.patch(
        "dorsal.cli.views.collection.collection_metadata",
        return_value=Panel("Mock Metadata Panel"),
    )

    return {
        "get_collection": mock_get,
        "view": mock_view,
    }


def test_show_collection_success_default(mock_rich_console, mock_show_collection_cmd):
    """Tests the default successful command, expecting a panel and a table."""
    result = runner.invoke(app, ["collection", "show", COLLECTION_ID])

    assert result.exit_code == 0
    mock_show_collection_cmd["get_collection"].assert_called_once_with(
        collection_id=COLLECTION_ID, hydrate=False, page=1, per_page=30, mode="pydantic"
    )
    mock_show_collection_cmd["view"].assert_called_once()

    assert mock_rich_console.print.call_count == 3
    assert isinstance(mock_rich_console.print.call_args_list[1].args[0], Panel)
    assert isinstance(mock_rich_console.print.call_args_list[2].args[0], Table)


def test_show_collection_meta_only(mock_rich_console, mock_show_collection_cmd):
    """Tests that --meta-only shows the panel but not the file table."""
    result = runner.invoke(app, ["collection", "show", COLLECTION_ID, "--meta-only"])

    assert result.exit_code == 0
    assert mock_show_collection_cmd["get_collection"].call_args.kwargs["per_page"] == 0

    assert mock_rich_console.print.call_count == 2
    assert isinstance(mock_rich_console.print.call_args.args[0], Panel)


def test_show_collection_no_files(mock_rich_console, mock_show_collection_cmd):
    """Tests the output when a collection is empty."""
    MOCK_API_RESPONSE.files = []
    MOCK_API_RESPONSE.collection.file_count = 0

    result = runner.invoke(app, ["collection", "show", COLLECTION_ID])

    assert result.exit_code == 0
    assert mock_rich_console.print.call_count == 3
    assert "Collection contains no files" in mock_rich_console.print.call_args.args[0]


def test_show_collection_json_output(mock_rich_console, mock_show_collection_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["collection", "show", COLLECTION_ID, "--json"])

    assert result.exit_code == 0
    # hydrate should be True for JSON output
    assert mock_show_collection_cmd["get_collection"].call_args.kwargs["hydrate"] is True

    mock_rich_console.print.assert_called_once()
    MOCK_API_RESPONSE.model_dump_json.assert_called_once()
    # The view helper should NOT be called in JSON mode
    mock_show_collection_cmd["view"].assert_not_called()


def test_show_collection_not_found(mock_show_collection_cmd):
    """Tests that a NotFoundError is handled gracefully."""
    mock_show_collection_cmd["get_collection"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["collection", "show", COLLECTION_ID])

    assert result.exit_code != 0
    assert f"Collection '{COLLECTION_ID}' not found" in result.output


def test_show_collection_api_error(mock_show_collection_cmd):
    """Tests that a generic DorsalClientError is handled gracefully."""
    mock_show_collection_cmd["get_collection"].side_effect = DorsalClientError("Permission Denied")

    result = runner.invoke(app, ["collection", "show", COLLECTION_ID])

    assert result.exit_code != 0
    assert "API Error: Permission Denied" in result.output
