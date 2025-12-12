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
import pathlib
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY, patch


from dorsal.cli import app
from dorsal.cli.dir_app import push_dir_cmd
from dorsal.common.exceptions import DorsalError

runner = CliRunner()

TEST_DATA_DIR = "tests/data"

# A sample summary to be returned by collection.push()
MOCK_PUSH_SUMMARY = {
    "total_records_in_collection": 2,
    "total_records_to_push": 2,
    "total_records_accepted_by_api": 2,
    "total_batches_created": 1,
    "successful_api_batches": 1,
    "failed_api_batches": 0,
    "batch_processing_details": [],
}


@pytest.fixture
def mock_push_dir_cmd(mocker):
    """Mocks backend dependencies for the `dir push` command."""
    # Patch the LocalFileCollection at its source due to lazy loading
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    # Configure the instance that will be returned by the constructor
    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []
    mock_instance.__len__.return_value = 2
    mock_instance.push.return_value = MOCK_PUSH_SUMMARY

    # Mock the remote collection returned when creating a new one
    mock_remote_collection = MagicMock()
    mock_remote_collection.metadata.private_url = "https://dorsal.hub/c/user/mock-collection"
    mock_instance.create_remote_collection.return_value = mock_remote_collection

    # Patch the helper functions to isolate their logic and prevent actual output
    mocker.patch.object(push_dir_cmd, "_display_dry_run_panel")
    mocker.patch.object(push_dir_cmd, "_display_summary_panel")

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
        "display_dry_run": push_dir_cmd._display_dry_run_panel,
        "display_summary": push_dir_cmd._display_summary_panel,
    }


def test_push_dir_success_default(mock_push_dir_cmd):
    """Tests a default successful `dir push`."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR])

    assert result.exit_code == 0
    mock_push_dir_cmd["collection_instance"].push.assert_called_once_with(private=True, console=ANY, palette=ANY)
    mock_push_dir_cmd["display_summary"].assert_called_once()
    mock_push_dir_cmd["display_dry_run"].assert_not_called()


def test_push_dir_public(mock_push_dir_cmd):
    """Tests a public push with the --public flag."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--public"])

    assert result.exit_code == 0
    mock_push_dir_cmd["collection_instance"].push.assert_called_once_with(private=False, console=ANY, palette=ANY)


def test_push_dir_dry_run(mock_push_dir_cmd):
    """Tests that --dry-run prevents a real push."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--dry-run"])

    assert result.exit_code == 0
    mock_push_dir_cmd["collection_instance"].push.assert_not_called()
    mock_push_dir_cmd["display_dry_run"].assert_called_once()


def test_push_dir_ignore_duplicates(mock_push_dir_cmd):
    """Tests the --ignore-duplicates logic."""
    mock_collection_class = mock_push_dir_cmd["collection_class"]
    mock_collection_instance = mock_push_dir_cmd["collection_instance"]

    mock_file1 = MagicMock()
    mock_file1.hash = "hash_A"
    mock_file2 = MagicMock()
    mock_file2.hash = "hash_B"
    mock_file3 = MagicMock()
    mock_file3.hash = "hash_A"  # This is a duplicate of file 1
    mock_files = [mock_file1, mock_file2, mock_file3]

    mock_collection_instance.__len__.return_value = len(mock_files)  # Original count is 3
    mock_collection_instance.__iter__.return_value = iter(mock_files)

    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--ignore-duplicates"])

    assert result.exit_code == 0
    assert mock_collection_class.call_count == 2
    assert "Ignoring" in result.output and "duplicate files" in result.output


def test_push_dir_create_collection_success(mock_rich_console, mock_push_dir_cmd):
    """Tests successfully creating a remote collection."""
    result = runner.invoke(
        app,
        [
            "dir",
            "push",
            TEST_DATA_DIR,
            "--create-collection",
            "--name",
            "MyNewCollection",
        ],
    )

    assert result.exit_code == 0
    mock_push_dir_cmd["collection_instance"].create_remote_collection.assert_called_once_with(
        name="MyNewCollection", description=None, is_private=True
    )
    # Verify no standard push was attempted
    mock_push_dir_cmd["collection_instance"].push.assert_not_called()
    # Check that the success panel was printed
    assert "Successfully pushed 2 files and created collection" in mock_rich_console.print.call_args.args[0].renderable


def test_push_dir_json_output(mock_rich_console, mock_push_dir_cmd):
    """Tests a standard push with --json output."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["total_records_accepted_by_api"] == 2
    mock_push_dir_cmd["display_summary"].assert_not_called()


def test_push_dir_duplicate_error(mock_rich_console, mock_push_dir_cmd):
    """Tests the specific error handling for duplicate file errors."""
    failed_summary = {
        **MOCK_PUSH_SUMMARY,
        "failed_api_batches": 1,
        "successful_api_batches": 0,
        "batch_processing_details": [
            {
                "status": "failure",
                "error_message": "Cannot process duplicate files in the same request.",
            }
        ],
    }
    mock_push_dir_cmd["collection_instance"].push.return_value = failed_summary

    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert "Duplicate Files Detected" in mock_rich_console.print.call_args.args[0].title


def test_push_dir_generic_dorsal_error(mock_push_dir_cmd):
    """Tests that a generic DorsalError is handled correctly."""
    mock_push_dir_cmd["collection_instance"].push.side_effect = DorsalError("Generic API failure")

    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR])

    assert result.exit_code != 0
    assert "Generic API failure" in result.output
