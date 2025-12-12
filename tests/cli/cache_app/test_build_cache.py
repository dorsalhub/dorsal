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

import os
import json

import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY


from dorsal.cli import app

runner = CliRunner()

TEST_DATA_DIR = "tests/data"

# A sample return value for the collection.info() method
MOCK_INFO_RESULT = {
    "by_source": [
        {"source": "cache", "count": 10},
        {"source": "disk", "count": 5},
    ]
}


@pytest.fixture
def mock_build_cache_cmd(mocker):
    """Mocks dependencies for the `cache build` command."""
    # Patch LocalFileCollection at its source due to lazy loading
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    # Configure the mock instance that the constructor will return
    mock_instance = mock_collection_class.return_value
    mock_instance.__len__.return_value = 15  # 10 from cache + 5 from disk
    mock_instance.info.return_value = MOCK_INFO_RESULT

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
    }


def test_build_cache_default(mock_rich_console, mock_build_cache_cmd):
    """Tests a default cache build, which should run in 'update' mode."""
    # Normalize the path for the CLI runner and the mock assertion
    normalized_path = os.path.normpath(str(TEST_DATA_DIR))
    result = runner.invoke(app, ["cache", "build", normalized_path])

    assert result.exit_code == 0
    # In default mode, it should use the cache to only process new/modified files
    mock_build_cache_cmd["collection_class"].assert_called_once_with(
        source=normalized_path,
        recursive=False,
        console=mock_rich_console,
        palette=ANY,
        use_cache=True,
    )

    # Check the formatted text output
    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "Cache build complete" in all_printed_text
    assert "Total files processed: 15" in all_printed_text
    assert "Loaded from cache: 10" in all_printed_text
    assert "Newly added to cache: 5" in all_printed_text


def test_build_cache_force(mock_rich_console, mock_build_cache_cmd):
    """Tests a forced cache build with the --yes flag, which re-processes all files."""
    result = runner.invoke(app, ["cache", "build", TEST_DATA_DIR, "--force"])

    assert result.exit_code == 0
    # With the --force flag, use_cache must be False
    assert mock_build_cache_cmd["collection_class"].call_args.kwargs["use_cache"] is False


def test_build_cache_json_output(mock_rich_console, mock_build_cache_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["cache", "build", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {
        "success": True,
        "total_files_processed": 15,
        "loaded_from_cache": 10,
        "newly_added_to_cache": 5,
    }


def test_build_cache_exception_handling(mock_build_cache_cmd):
    """Tests that an exception during collection is handled gracefully."""
    mock_build_cache_cmd["collection_class"].side_effect = Exception("Cannot read directory")

    result = runner.invoke(app, ["cache", "build", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert "An error occurred while building the cache: Cannot read directory" in result.output
