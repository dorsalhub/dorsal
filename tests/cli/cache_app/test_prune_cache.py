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


from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_prune_cache_cmd(mocker):
    """Mocks dependencies for the `cache prune` command."""
    mock_get_cache = mocker.patch("dorsal.session.get_shared_cache")

    mock_cache_instance = MagicMock()
    mock_get_cache.return_value = mock_cache_instance

    return {"get_cache": mock_get_cache, "cache_instance": mock_cache_instance}


def test_prune_cache_with_stale_records(mock_rich_console, mock_prune_cache_cmd):
    """Tests the prune command when stale records are found and removed."""
    mock_prune_cache_cmd["cache_instance"].prune.return_value = (10, 100)

    result = runner.invoke(app, ["cache", "prune"])

    assert result.exit_code == 0
    mock_prune_cache_cmd["cache_instance"].prune.assert_called_once()

    success_msg = mock_rich_console.print.call_args.args[0]
    assert "Prune complete. Removed 10 of 100 records" in success_msg


def test_prune_cache_no_stale_records(mock_rich_console, mock_prune_cache_cmd):
    """Tests the prune command when no stale records are found."""
    mock_prune_cache_cmd["cache_instance"].prune.return_value = (0, 50)

    result = runner.invoke(app, ["cache", "prune"])

    assert result.exit_code == 0
    mock_prune_cache_cmd["cache_instance"].prune.assert_called_once()

    info_msg = mock_rich_console.print.call_args.args[0]
    assert "Prune complete. No stale records found out of 50 scanned" in info_msg


def test_prune_cache_json_output(mock_rich_console, mock_prune_cache_cmd):
    """Tests the --json output flag."""
    mock_prune_cache_cmd["cache_instance"].prune.return_value = (10, 100)
    result = runner.invoke(app, ["cache", "prune", "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()

    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == {
        "total_records_scanned": 100,
        "stale_records_removed": 10,
    }


def test_prune_cache_exception_handling(mock_prune_cache_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_prune_cache_cmd["cache_instance"].prune.side_effect = Exception("Database is corrupt")
    result = runner.invoke(app, ["cache", "prune"])
    assert result.exit_code != 0
    assert "An error occurred while pruning the cache: Database is corrupt" in result.output
