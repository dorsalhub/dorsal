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

import json
import datetime
import pathlib
from unittest.mock import MagicMock, ANY

import pytest
import typer
from typer.testing import CliRunner
from rich.panel import Panel
from rich.table import Table

from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError, AuthError, DorsalError, PartialIndexingError, DorsalOfflineError

runner = CliRunner()



@pytest.fixture
def mock_rich_console(mocker):
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)
    mocker.patch("dorsal.cli.local_app.push_cmd.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_exit_cli(mocker):
    def _side_effect(code=0, message=None):
        raise typer.Exit(code)
    return mocker.patch("dorsal.cli.local_app.push_cmd.exit_cli", side_effect=_side_effect)


@pytest.fixture
def mock_file_deps(mocker):
    mock_local_file_class = mocker.patch("dorsal.file.dorsal_file.LocalFile")
    mock_instance = mock_local_file_class.return_value

    mock_api_response = MagicMock()
    mock_api_response.success = 1
    mock_api_response.error = 0
    mock_api_response.results = [MagicMock()]
    mock_api_response.results[0].hash = "mock_pushed_hash"
    mock_api_response.model_dump.return_value = {
        "success": 1,
        "error": 0,
        "results": [{"hash": "mock_pushed_hash"}],
    }

    mock_instance.push.return_value = mock_api_response

    return {
        "local_file_class": mock_local_file_class,
        "local_file_instance": mock_instance,
    }


@pytest.fixture
def mock_dir_deps(mocker):
    mock_collection_class = mocker.patch("dorsal.file.collection.local.LocalFileCollection")

    mock_instance = mock_collection_class.return_value
    mock_instance.warnings = []
    mock_instance.__len__.return_value = 2
    mock_instance.__bool__.side_effect = lambda: mock_instance.__len__() > 0
    mock_instance.files = [MagicMock(), MagicMock()] 

    mock_instance.push.return_value = {
        "total_records": 2,
        "processed": 2,
        "success": 2,
        "failed": 0,
        "batches": [{"batch_index": 0, "status": "success", "records_in_batch": 2}],
        "errors": [],
    }

    mock_remote_collection = MagicMock()
    mock_remote_collection.metadata.private_url = "https://dorsal.hub/c/user/mock-collection"
    mock_remote_collection.metadata.model_dump_json.return_value = '{"id": "mock_col"}'
    mock_instance.create_remote_collection.return_value = mock_remote_collection

    return {
        "collection_class": mock_collection_class,
        "collection_instance": mock_instance,
    }



def test_push_cache_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "push", str(target), "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(code=ANY, message="Error: --use-cache and --skip-cache flags cannot be used together.")

def test_push_skip_overwrite_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "push", str(target), "--skip-cache", "--overwrite-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(code=ANY, message="Error: --skip-cache and --overwrite-cache flags cannot be used together.")




def test_push_file_default(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "push", str(target)])

    assert result.exit_code == 0
    mock_file_deps["local_file_instance"].push.assert_called_once_with(public=False, strict=False)
    
    panel_output = mock_rich_console.print.call_args_list[-1].args[0]
    assert isinstance(panel_output, Panel)
    assert "Push Complete" in str(panel_output.title)

def test_push_file_ignored_dir_flags(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    runner.invoke(app, ["local", "push", str(target), "--recursive"])
    
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Directory-specific push flags are ignored" in printed_text

def test_push_file_json_output(mock_rich_console, mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    runner.invoke(app, ["local", "push", str(target), "--json"])
    
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    data = json.loads(json_output_str)
    assert data["success"] == 1
    mock_exit_cli.assert_called_once()

def test_push_file_api_failure(mock_rich_console, mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    
    mock_api_response = mock_file_deps["local_file_instance"].push.return_value
    mock_api_response.success = 0
    mock_api_response.results[0].annotations[0].detail = "File already indexed"

    runner.invoke(app, ["local", "push", str(target)])
    
    panel_output = mock_rich_console.print.call_args_list[-1].args[0]
    assert "Push Failed" in str(panel_output.title)
    assert "File already indexed" in str(panel_output.renderable)

def test_push_file_partial_indexing_error(mock_rich_console, mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    
    error = PartialIndexingError("Strict mode failure", {"failures": ["Missing hash"]})
    mock_file_deps["local_file_instance"].push.side_effect = error

    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called()
    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Strict Mode Error" in printed_text
    
def test_push_file_partial_indexing_error_json(mock_rich_console, mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    
    error = PartialIndexingError("Strict mode failure", {"failures": ["Missing hash"]})
    mock_file_deps["local_file_instance"].push.side_effect = error

    runner.invoke(app, ["local", "push", str(target), "--json"])
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    assert "PartialIndexingError" in json_output_str

def test_push_file_client_error(mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_file_deps["local_file_instance"].push.side_effect = DorsalClientError("Connection timeout")
    
    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called()
    assert "API Error: Connection timeout" in mock_exit_cli.call_args.kwargs["message"]

def test_push_file_generic_error(mock_file_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_file_deps["local_file_instance"].push.side_effect = Exception("System Exploded")
    
    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called()
    assert "System Exploded" in mock_exit_cli.call_args.kwargs["message"]

def test_push_file_auth_error_bubbles(mock_file_deps, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_file_deps["local_file_instance"].push.side_effect = AuthError("Token expired")
    
    with pytest.raises(AuthError):
        runner.invoke(app, ["local", "push", str(target)], catch_exceptions=False)




def test_push_dir_default(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    result = runner.invoke(app, ["local", "push", str(target)])

    assert result.exit_code == 0
    mock_dir_deps["collection_instance"].push.assert_called_once()
    
    print_calls = mock_rich_console.print.call_args_list
    assert any(isinstance(call.args[0], Panel) and "Push Complete" in str(call.args[0].title) for call in print_calls)

def test_push_dir_empty_graceful_exit(mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    mock_dir_deps["collection_instance"].__len__.return_value = 0
    mock_dir_deps["collection_instance"].__bool__.side_effect = lambda: False
    
    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called_once()
    assert "No valid files found" in mock_exit_cli.call_args.kwargs["message"]

def test_push_dir_ignore_duplicates(mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    mock_file1 = MagicMock(hash="hash_A")
    mock_file2 = MagicMock(hash="hash_B")
    mock_file3 = MagicMock(hash="hash_A")
    mock_files = [mock_file1, mock_file2, mock_file3]

    mock_dir_deps["collection_instance"].__len__.return_value = len(mock_files)
    mock_dir_deps["collection_instance"].__iter__.return_value = iter(mock_files)

    runner.invoke(app, ["local", "push", str(target), "--ignore-duplicates"])
    assert mock_dir_deps["collection_class"].call_count == 2

def test_push_dir_dry_run(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    mock_file_cache = MagicMock()
    mock_file_cache.name = "test.txt"
    mock_file_cache.size = 100
    mock_file_cache.media_type = "text/plain"
    mock_file_cache._source = "cache"
    
    mock_file_disk = MagicMock()
    mock_file_disk.name = "test_disk.txt"
    mock_file_disk.size = 200
    mock_file_disk.media_type = "text/plain"
    mock_file_disk._source = "disk"
    
    mock_dir_deps["collection_instance"].__iter__.return_value = iter([mock_file_cache, mock_file_disk])
    
    runner.invoke(app, ["local", "push", str(target), "--dry-run"])
    mock_dir_deps["collection_instance"].push.assert_not_called()
    mock_exit_cli.assert_called_once()
    
    print_calls = mock_rich_console.print.call_args_list
    panels = [c.args[0] for c in print_calls if isinstance(c.args[0], Panel)]
    assert any("DRY RUN MODE" in str(p.renderable) for p in panels)

def test_push_dir_create_collection_fallback_name(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    runner.invoke(app, ["local", "push", str(target), "--create-collection"])
    mock_dir_deps["collection_instance"].create_remote_collection.assert_called_once_with(
        name="test_dir", description=None, public=False
    )

def test_push_dir_create_collection_json(mock_rich_console, mock_dir_deps, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    runner.invoke(app, ["local", "push", str(target), "--create-collection", "--json"])
    json_output_str = mock_rich_console.print.call_args_list[-1].args[0]
    assert "mock_col" in json_output_str

def test_push_dir_create_collection_too_large(mocker, mock_dir_deps, tmp_path):
    mocker.patch("dorsal.cli.local_app.push_cmd.API_MAX_BATCH_SIZE", 1)
    target = tmp_path / "test_dir"
    target.mkdir()
    
    runner.invoke(app, ["local", "push", str(target), "--create-collection"])
    
    mock_dir_deps["collection_instance"].create_remote_collection.assert_not_called()
    mock_dir_deps["collection_instance"].push.assert_called_once()

def test_push_dir_duplicate_error_handled(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    mock_dir_deps["collection_instance"].push.return_value = {
        "failed": 1,
        "errors": [{"error_message": "Cannot process duplicate files"}],
    }

    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called()
    panel_output = next(call.args[0] for call in mock_rich_console.print.call_args_list if isinstance(call.args[0], Panel))
    assert "Duplicate Files Detected" in str(panel_output.title)
    
    mock_rich_console.reset_mock()
    runner.invoke(app, ["local", "push", str(target), "--json"])
    json_str = mock_rich_console.print.call_args_list[0].args[0]
    assert "Cannot process duplicate files" in json_str

def test_push_dir_partial_indexing_error(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    error = PartialIndexingError("Strict fail", {"failures": ["Bad bad"], "errors": [{"message": "File corrupt"}]})
    mock_dir_deps["collection_instance"].push.side_effect = error
    
    runner.invoke(app, ["local", "push", str(target)])
    mock_exit_cli.assert_called()
    tables = [call.args[0] for call in mock_rich_console.print.call_args_list if isinstance(call.args[0], Table)]
    assert "Strict Integrity Failures" in str(tables[0].title)

def test_push_dir_partial_indexing_error_no_failures_key(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    error = PartialIndexingError("Strict fail", {"errors": [{"message": "File corrupt"}, "String error"]})
    mock_dir_deps["collection_instance"].push.side_effect = error
    
    runner.invoke(app, ["local", "push", str(target)])
    tables = [call.args[0] for call in mock_rich_console.print.call_args_list if isinstance(call.args[0], Table)]
    assert "Strict Integrity Failures" in str(tables[0].title)

def test_push_dir_partial_indexing_error_json(mock_rich_console, mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    error = PartialIndexingError("Strict fail", {"failures": ["Bad bad"]})
    mock_dir_deps["collection_instance"].push.side_effect = error
    
    runner.invoke(app, ["local", "push", str(target), "--json"])
    json_output_str = mock_rich_console.print.call_args_list[0].args[0]
    assert "PartialIndexingError" in json_output_str

def test_push_dir_generic_errors(mock_dir_deps, mock_exit_cli, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()
    
    mock_dir_deps["collection_instance"].push.side_effect = DorsalError("Dorsal API Broke")
    runner.invoke(app, ["local", "push", str(target)])
    assert "Dorsal API Broke" in mock_exit_cli.call_args.kwargs["message"]

    mock_dir_deps["collection_instance"].push.side_effect = Exception("System Crash")
    runner.invoke(app, ["local", "push", str(target)])
    assert "System Crash" in mock_exit_cli.call_args.kwargs["message"]

def test_push_dir_defensive_collection_name(mock_dir_deps, mock_exit_cli):
    """Hits the defensive 'if collection_name is None' block."""
    from dorsal.cli.local_app.push_cmd import _process_dir_push
    
    mock_path = MagicMock()
    mock_path.name = None 
    mock_path.__str__.return_value = "mock_path"
    
    with pytest.raises(typer.Exit):
        _process_dir_push(
            ctx=MagicMock(), path=mock_path, use_cache_value=False, overwrite_cache=False,
            public=False, strict=False, json_output=False, resolve_links=True,
            recursive=False, create_collection=True, collection_name=None,
            collection_desc=None, dry_run=False, ignore_duplicates=False,
            fail_fast=False, lazy=False, palette={}, console=MagicMock()
        )
    
    mock_exit_cli.assert_called()
    assert "Collection name was not set" in mock_exit_cli.call_args.kwargs["message"]

def test_push_exception_bubbling(mock_dir_deps, tmp_path):
    """Ensures specific exceptions bubble up without being caught by generic handlers."""
    target = tmp_path / "test_dir"
    target.mkdir()
    
    mock_dir_deps["collection_instance"].push.side_effect = AuthError("Token expired")
    with pytest.raises(AuthError):
        runner.invoke(app, ["local", "push", str(target)], catch_exceptions=False)
        
    mock_dir_deps["collection_instance"].push.side_effect = DorsalOfflineError()
    with pytest.raises(DorsalOfflineError):
        runner.invoke(app, ["local", "push", str(target)], catch_exceptions=False)




def test_display_summary_panel_with_failures(mocker):
    """Directly hits the failure block in _display_summary_panel."""
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)

    from dorsal.cli.local_app.push_cmd import _display_summary_panel
    
    summary_data = {
        "total_records": 10,
        "success": 5,
        "failed": 5,
        "errors": [{"batch_index": 1, "error_type": "HTTP 500", "error_message": "Server exploded"}],
        "batches": [{"status": "success"}, {"status": "failure"}],
    }

    mock_collection = MagicMock()
    mock_collection.__iter__.return_value = iter([])

    _display_summary_panel(summary_data, True, {}, False, mock_collection, mock_console)

    assert mock_console.print.call_count == 3
    last_print_arg = mock_console.print.call_args_list[-1].args[0]
    assert "Failed Batch Details" in str(last_print_arg.title)