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

import pytest
import json
import typer
from typer.testing import CliRunner

from dorsal.cli import app
from dorsal.common.cli import EXIT_CODE_ERROR

runner = CliRunner()


@pytest.fixture
def mock_rebuild_api(mocker):
    """Mocks the core API and CLI utilities for the rebuild command."""

    def _mock_rebuild_execution(*args, **kwargs):
        progress_cb = kwargs.get("progress_callback")
        if progress_cb:
            progress_cb(10, 42)
            progress_cb(42, 42)
        return 42

    mock_rebuild = mocker.patch("dorsal.api.index.rebuild", side_effect=_mock_rebuild_execution)

    mock_exit = mocker.patch("dorsal.common.cli.exit_cli", side_effect=SystemExit(EXIT_CODE_ERROR))

    return {
        "rebuild": mock_rebuild,
        "exit": mock_exit,
    }


def test_rebuild_index_default_progress_bar(mock_rebuild_api):
    """Tests the standard interactive execution with the progress bar."""
    result = runner.invoke(app, ["index", "rebuild", "--batch-size", "50"])

    assert result.exit_code == 0
    mock_rebuild_api["rebuild"].assert_called_once()

    kwargs = mock_rebuild_api["rebuild"].call_args.kwargs
    assert kwargs.get("batch_size") == 50
    assert "progress_callback" in kwargs

    assert "Successfully rebuilt search indexes for 42 records" in result.output


def test_rebuild_index_json_output(mock_rebuild_api):
    """Tests the --json flag execution (no progress bar, JSON stdout)."""
    result = runner.invoke(app, ["index", "rebuild", "--json", "--batch-size", "25"])

    assert result.exit_code == 0
    mock_rebuild_api["rebuild"].assert_called_once()

    kwargs = mock_rebuild_api["rebuild"].call_args.kwargs
    assert "progress_callback" not in kwargs
    assert kwargs.get("batch_size") == 25

    data = json.loads(result.output)

    assert data["success"] is True
    assert data["total_records_rebuilt"] == 42


def test_rebuild_index_exception_handling(mock_rebuild_api):
    """Tests that generic exceptions are caught and passed to exit_cli with a message."""
    mock_rebuild_api["rebuild"].side_effect = Exception("Database locked")

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == EXIT_CODE_ERROR
    mock_rebuild_api["exit"].assert_called_once_with(
        code=EXIT_CODE_ERROR, message="An unexpected error occurred while rebuilding the index: Database locked"
    )


def test_rebuild_index_typer_exit_propagation(mock_rebuild_api):
    """Tests that intentional typer.Exit exceptions are propagated natively, not caught as errors."""
    mock_rebuild_api["rebuild"].side_effect = typer.Exit(0)

    result = runner.invoke(app, ["index", "rebuild"])

    assert result.exit_code == 0
    mock_rebuild_api["exit"].assert_not_called()
