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
from rich.panel import Panel


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError, AuthError

runner = CliRunner()

# Use a real file from your test data directory
TEST_FILE_PATH = "tests/data/valid.txt"


@pytest.fixture
def mock_push_cmd(mocker):
    """
    Mocks dependencies for the `file push` command.
    """
    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=True)

    # Mock the LocalFile class
    mock_local_file_class = mocker.patch("dorsal.file.dorsal_file.LocalFile")

    # Configure the instance that will be returned by the LocalFile constructor
    mock_instance = mock_local_file_class.return_value

    # Create a mock for the API response object returned by the .push() method
    mock_api_response = MagicMock()
    mock_api_response.success = 1
    mock_api_response.results = [MagicMock()]
    mock_api_response.results[0].hash = "mock_pushed_hash"
    # .model_dump() is called for JSON output, so we mock it too
    mock_api_response.model_dump.return_value = {
        "success": 1,
        "results": [{"hash": "mock_pushed_hash"}],
    }

    mock_instance.push.return_value = mock_api_response

    return {
        "local_file_class": mock_local_file_class,
        "local_file_instance": mock_instance,
    }


def test_push_success_private_panel(mock_rich_console, mock_push_cmd):
    """Tests a successful private push (the default)."""
    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH])

    assert result.exit_code == 0
    # Verify push was called with private=True
    mock_push_cmd["local_file_instance"].push.assert_called_once_with(private=True)

    # Verify a success panel was printed
    panel_output = mock_rich_console.print.call_args_list[1].args[0]
    assert isinstance(panel_output, Panel)
    assert "Push Complete" in str(panel_output.title)
    assert "mock_pushed_hash" in str(panel_output.renderable)


def test_push_success_public_panel(mock_rich_console, mock_push_cmd):
    """Tests a successful public push using the --public flag."""
    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH, "--public"])

    assert result.exit_code == 0
    # Verify push was called with private=False
    mock_push_cmd["local_file_instance"].push.assert_called_once_with(private=False)

    panel_output = mock_rich_console.print.call_args_list[1].args[0]
    assert isinstance(panel_output, Panel)
    assert "Push Complete" in str(panel_output.title)


def test_push_success_json_output(mock_rich_console, mock_push_cmd):
    """Tests a successful push with --json output."""
    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH, "--json"])

    assert result.exit_code == 0
    # In JSON mode, the API response's model_dump is printed directly
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data["success"] == 1
    assert data["results"][0]["hash"] == "mock_pushed_hash"


def test_push_api_failure_panel(mock_rich_console, mock_push_cmd):
    """Tests a failed push due to an API-side reason."""
    mock_api_response = mock_push_cmd["local_file_instance"].push.return_value
    mock_api_response.success = 0
    mock_api_response.results[0].annotations[0].detail = "File already indexed"

    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH])

    assert result.exit_code == 0  # The command succeeds, but the push fails
    panel_output = mock_rich_console.print.call_args_list[1].args[0]
    assert isinstance(panel_output, Panel)
    assert "Push Failed" in str(panel_output.title)
    assert "File already indexed" in str(panel_output.renderable)


def test_push_auth_error(mock_push_cmd):
    """
    Tests that the command bubbles up AuthError (does not swallow it).
    """
    mock_push_cmd["local_file_instance"].push.side_effect = AuthError("test_msg")

    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH])

    assert result.exit_code != 0
    assert isinstance(result.exception, AuthError)


def test_push_client_error(mock_push_cmd):
    """Tests that a DorsalClientError is handled correctly."""
    mock_push_cmd["local_file_instance"].push.side_effect = DorsalClientError("Connection timeout")
    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH])

    assert result.exit_code != 0
    assert "API Error: Connection timeout" in result.output


def test_push_cache_flag_conflict():
    """Tests that using both --use-cache and --skip-cache fails."""
    result = runner.invoke(app, ["file", "push", TEST_FILE_PATH, "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    assert "Error: --use-cache and --skip-cache flags cannot be used together" in result.output
