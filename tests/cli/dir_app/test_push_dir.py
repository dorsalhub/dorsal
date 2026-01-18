# Copyright 2025-2026 Dorsal Hub LTD
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

MOCK_PUSH_SUMMARY = {
    "total_records": 2,
    "processed": 2,
    "success": 2,
    "failed": 0,
    "batches": [{"batch_index": 0, "status": "success", "records_in_batch": 2}],
    "errors": [],
}


@pytest.fixture
def mock_push_dir_cmd(mocker):
    """Mocks backend dependencies for the `dir push` command."""
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []
    mock_instance.__len__.return_value = 2
    mock_instance.push.return_value = MOCK_PUSH_SUMMARY

    mock_remote_collection = MagicMock()
    mock_remote_collection.metadata.private_url = "https://dorsal.hub/c/user/mock-collection"
    mock_instance.create_remote_collection.return_value = mock_remote_collection

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
    mock_push_dir_cmd["collection_instance"].push.assert_called_once_with(
        public=False, console=ANY, palette=ANY, fail_fast=True, strict=False
    )
    mock_push_dir_cmd["display_summary"].assert_called_once()
    mock_push_dir_cmd["display_dry_run"].assert_not_called()


def test_push_dir_public(mock_push_dir_cmd):
    """Tests a public push with the --public flag."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--public"])

    assert result.exit_code == 0
    mock_push_dir_cmd["collection_instance"].push.assert_called_once_with(
        public=True, console=ANY, palette=ANY, fail_fast=True, strict=False
    )


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
    mock_file3.hash = "hash_A"
    mock_files = [mock_file1, mock_file2, mock_file3]

    mock_collection_instance.__len__.return_value = len(mock_files)
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
        name="MyNewCollection", description=None, public=False
    )
    mock_push_dir_cmd["collection_instance"].push.assert_not_called()
    assert "Successfully pushed 2 files and created collection" in mock_rich_console.print.call_args.args[0].renderable


def test_push_dir_json_output(mock_rich_console, mock_push_dir_cmd):
    """Tests a standard push with --json output."""
    result = runner.invoke(app, ["dir", "push", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["success"] == 2
    mock_push_dir_cmd["display_summary"].assert_not_called()


def test_push_dir_duplicate_error(mock_rich_console, mock_push_dir_cmd):
    """Tests the specific error handling for duplicate file errors."""
    failed_summary = {
        **MOCK_PUSH_SUMMARY,
        "success": 0,
        "failed": 2,
        "errors": [
            {
                "batch_index": 0,
                "status": "failure",
                "error_message": "Cannot process duplicate files in the same request.",
                "error_type": "DuplicateFileError",
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


def test_display_dry_run_panel_output(mocker):
    """
    Directly tests _display_dry_run_panel.
    Fix: Patches dorsal.common.cli.get_rich_console because the import is local to the function.
    """
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)

    mock_file_cache = MagicMock()
    mock_file_cache.name = "cached_file.txt"
    mock_file_cache.size = 1024
    mock_file_cache.media_type = "text/plain"
    mock_file_cache._source = "cache"

    mock_file_disk = MagicMock()
    mock_file_disk.name = "new_file.jpg"
    mock_file_disk.size = 2048 * 1024
    mock_file_disk.media_type = "image/jpeg"
    mock_file_disk._source = "disk"

    mock_collection = MagicMock()
    mock_collection.__len__.return_value = 2
    mock_collection.__iter__.return_value = iter([mock_file_cache, mock_file_disk])

    palette = {
        "primary_value": "blue",
        "success": "green",
        "key": "dim",
        "panel_border_warning": "yellow",
        "table_header": "bold magenta",
    }

    from dorsal.cli.dir_app.push_dir_cmd import _display_dry_run_panel

    _display_dry_run_panel(collection=mock_collection, use_cache=True, palette=palette)

    assert mock_console.print.call_count >= 2
    args, _ = mock_console.print.call_args_list[0]
    assert "DRY RUN MODE" in str(args[0].renderable)


def test_display_summary_panel_output_success(mocker):
    """
    Directly tests _display_summary_panel for success.
    Fix: Patches dorsal.common.cli.get_rich_console.
    """
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)

    palette = {
        "key": "cyan",
        "success": "green",
        "error": "red",
        "primary_value": "blue",
        "panel_title_success": "bold green",
        "panel_border_success": "green",
        "access_public": "bold yellow",
        "access_private": "dim",
    }

    summary_data = {"total_records": 10, "success": 10, "failed": 0, "batches": [{"status": "success"}]}

    mock_collection = MagicMock()
    mock_collection.__iter__.return_value = iter([])

    from dorsal.cli.dir_app.push_dir_cmd import _display_summary_panel

    _display_summary_panel(
        summary=summary_data, public=False, palette=palette, use_cache=False, collection=mock_collection
    )

    assert mock_console.print.called
    printed_obj = mock_console.print.call_args[0][0]
    assert "Push Complete" in str(printed_obj.title)


def test_display_summary_panel_with_failures(mocker):
    """
    Tests failure rendering in _display_summary_panel.
    Fix: Patches dorsal.common.cli.get_rich_console.
    """
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)

    palette = {
        "key": "cyan",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "primary_value": "blue",
        "table_header": "bold red",
    }

    summary_data = {
        "total_records": 5,
        "success": 3,
        "failed": 2,
        "errors": [{"batch_index": 1, "error_type": "HTTP 500", "error_message": "Server exploded"}],
        "batches": [{"status": "failure"}],
    }

    mock_collection = MagicMock()
    mock_collection.__iter__.return_value = iter([])

    from dorsal.cli.dir_app.push_dir_cmd import _display_summary_panel

    _display_summary_panel(
        summary=summary_data, public=True, palette=palette, use_cache=False, collection=mock_collection
    )

    assert mock_console.print.call_count >= 2
    last_print_arg = mock_console.print.call_args[0][0]
    assert "Failed Batch Details" in str(last_print_arg.title)
