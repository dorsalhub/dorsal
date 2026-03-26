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

import os
import json

import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY

from dorsal.cli import app

runner = CliRunner()

TEST_DATA_DIR = "tests/data"


MOCK_INFO_RESULT = {
    "by_source": [
        {"source": "cache", "count": 10},
        {"source": "disk", "count": 5},
    ]
}


@pytest.fixture
def mock_build_index_cmd(mocker):
    """Mocks dependencies for the `index build` command."""

    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    mock_instance = mock_collection_class.return_value
    mock_instance.__len__.return_value = 15
    mock_instance.info.return_value = MOCK_INFO_RESULT

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
    }


def test_build_index_default(mock_rich_console, mock_build_index_cmd):
    """Tests the default behavior of building the index."""
    result = runner.invoke(app, ["index", "build", TEST_DATA_DIR])

    assert result.exit_code == 0
    mock_build_index_cmd["collection_class"].assert_called_once()

    all_printed_text = " ".join([call.args[0] for call in mock_rich_console.print.call_args_list if call.args])

    assert "Search Index updated successfully" in all_printed_text
    assert "Loaded from index: 10" in all_printed_text
    assert "Newly added to index: 5" in all_printed_text


def test_build_index_force(mock_rich_console, mock_build_index_cmd):
    """Tests a forced index build with the --force flag, which re-processes all files."""
    result = runner.invoke(app, ["index", "build", TEST_DATA_DIR, "--force"])

    assert result.exit_code == 0

    assert mock_build_index_cmd["collection_class"].call_args.kwargs["use_cache"] is False


def test_build_index_json_output(mock_rich_console, mock_build_index_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["index", "build", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {
        "success": True,
        "total_files_processed": 15,
        "loaded_from_index": 10,
        "newly_added_to_index": 5,
    }


def test_build_index_exception_handling(mock_build_index_cmd):
    """Tests that an exception during collection is handled gracefully."""
    mock_build_index_cmd["collection_class"].side_effect = PermissionError("Cannot read directory")

    result = runner.invoke(app, ["index", "build", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert "Cannot read directory" in result.output
