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

from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_clear_cache_cmd(mocker):
    """Mocks dependencies for the `cache clear` command."""
    mock_get_cache = mocker.patch("dorsal.session.get_shared_cache")
    mock_clear_shared_cache = mocker.patch("dorsal.session.clear_shared_cache")

    mock_cache_instance = MagicMock()
    mock_cache_instance.db_path.resolve.return_value = "/fake/home/.dorsal/cache.db"
    mock_get_cache.return_value = mock_cache_instance

    return {
        "get_cache": mock_get_cache,
        "clear_shared_cache": mock_clear_shared_cache,
        "cache_instance": mock_cache_instance,
    }


def test_clear_cache_with_yes_flag(mock_rich_console, mock_clear_cache_cmd):
    """Tests clearing the cache non-interactively with the --yes flag."""
    result = runner.invoke(app, ["cache", "clear", "--yes"])

    assert result.exit_code == 0
    mock_clear_cache_cmd["cache_instance"].clear.assert_called_once()
    mock_clear_cache_cmd["clear_shared_cache"].assert_called_once()

    success_msg = mock_rich_console.print.call_args.args[0]
    assert "Cache cleared successfully" in success_msg


def test_clear_cache_with_confirmation_yes(mock_rich_console, mock_clear_cache_cmd):
    """Tests clearing the cache by answering 'y' to the interactive prompt."""

    result = runner.invoke(app, ["cache", "clear"], input="y\n")

    assert result.exit_code == 0
    mock_clear_cache_cmd["cache_instance"].clear.assert_called_once()
    mock_clear_cache_cmd["clear_shared_cache"].assert_called_once()

    success_msg = mock_rich_console.print.call_args.args[0]
    assert "Cache cleared successfully" in success_msg


def test_clear_cache_aborted(mock_rich_console, mock_clear_cache_cmd):
    """Tests aborting the clear command by answering 'n' to the prompt."""
    result = runner.invoke(app, ["cache", "clear"], input="n\n")

    assert result.exit_code == 0
    aborted_msg = mock_rich_console.print.call_args.args[0]
    assert "Cache clearing aborted" in aborted_msg

    mock_clear_cache_cmd["cache_instance"].clear.assert_not_called()
    mock_clear_cache_cmd["clear_shared_cache"].assert_not_called()


def test_clear_cache_exception_handling(mock_clear_cache_cmd):
    """Tests that an exception during the clear operation is handled gracefully."""
    mock_clear_cache_cmd["cache_instance"].clear.side_effect = OSError("Permission denied")

    result = runner.invoke(app, ["cache", "clear", "--yes"])

    assert result.exit_code != 0
    assert "An error occurred while clearing the cache: Permission denied" in result.output
