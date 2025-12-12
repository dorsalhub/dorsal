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

import json
import os

import pytest
from typer.testing import CliRunner
from rich.panel import Panel


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError, NotFoundError

runner = CliRunner()

# Use a real file from your test data directory
TEST_FILE_PATH = "tests/data/valid.txt"

# A sample record to be returned by the mocked identify_file function
MOCK_FILE_RECORD = {
    "name": "valid.txt",
    "hashes": {"SHA-256": "mock_sha256_hash"},
}


@pytest.fixture
def mock_identify_cmd(mocker):
    """
    Mocks all backend dependencies for the `dorsal file identify` command.
    """
    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=True)
    mock_identify = mocker.patch("dorsal.api.file.identify_file", return_value=MOCK_FILE_RECORD)
    mock_panel = mocker.patch("dorsal.cli.views.file.create_file_info_panel")

    return {
        "identify_file": mock_identify,
        "create_panel": mock_panel,
    }


@pytest.mark.parametrize("command", ["identify", "id"])
def test_identify_success_quick_mode(command, mock_rich_console, mock_identify_cmd):
    """Tests successful identification in default (quick) mode."""
    normalized_path = os.path.normpath(str(TEST_FILE_PATH))
    result = runner.invoke(app, ["file", command, normalized_path])

    assert result.exit_code == 0
    # Verify identify_file was called with quick=True
    mock_identify_cmd["identify_file"].assert_called_once_with(
        file_path=normalized_path, quick=True, use_cache=True, mode="dict"
    )
    # Verify the panel was created and printed
    mock_identify_cmd["create_panel"].assert_called_once()
    mock_rich_console.print.assert_called_with(mock_identify_cmd["create_panel"].return_value)


def test_identify_success_secure_mode(mock_rich_console, mock_identify_cmd):
    """Tests successful identification with the --secure flag."""
    normalized_path = os.path.normpath(str(TEST_FILE_PATH))
    result = runner.invoke(app, ["file", "identify", normalized_path, "--secure"])

    assert result.exit_code == 0
    # Verify identify_file was called with quick=False
    mock_identify_cmd["identify_file"].assert_called_once_with(
        file_path=normalized_path, quick=False, use_cache=True, mode="dict"
    )
    mock_identify_cmd["create_panel"].assert_called_once()


def test_identify_success_json_output(mock_rich_console, mock_identify_cmd):
    """Tests successful identification with --json output."""
    result = runner.invoke(app, ["file", "identify", TEST_FILE_PATH, "--json"])

    assert result.exit_code == 0
    # Verify the output was a JSON string
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data["name"] == "valid.txt"
    # Verify the panel was NOT created
    mock_identify_cmd["create_panel"].assert_not_called()


def test_identify_not_found_panel_output(mock_rich_console, mock_identify_cmd):
    """Tests the 'Not Found' case with Rich Panel output."""
    mock_identify_cmd["identify_file"].side_effect = NotFoundError("File not in database")

    result = runner.invoke(app, ["file", "identify", TEST_FILE_PATH])

    assert result.exit_code != 0
    panel_output = mock_rich_console.print.call_args.args[0]
    assert isinstance(panel_output, Panel)
    assert "Not Found" in str(panel_output.title)
    assert "dorsal file push" in str(panel_output.renderable)  # Check for suggestion


def test_identify_not_found_json_output(mock_rich_console, mock_identify_cmd):
    """Tests the 'Not Found' case with --json output."""
    mock_identify_cmd["identify_file"].side_effect = NotFoundError("File not in database")

    result = runner.invoke(app, ["file", "identify", TEST_FILE_PATH, "--json"])

    assert result.exit_code != 0
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data["success"] is False
    assert data["error"] == "Not Found"


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_identify_api_error(json_flag, mock_rich_console, mock_identify_cmd):
    """Tests a generic DorsalClientError with and without --json."""
    mock_identify_cmd["identify_file"].side_effect = DorsalClientError("Invalid API Key")

    result = runner.invoke(app, ["file", "identify", TEST_FILE_PATH] + json_flag)

    assert result.exit_code != 0
    if json_flag:
        json_output_str = mock_rich_console.print.call_args.args[0]
        data = json.loads(json_output_str)
        assert data["error"] == "API Error"
        assert "Invalid API Key" in data["detail"]
    else:
        assert "API Error: Invalid API Key" in result.output


def test_identify_cache_flag_conflict():
    """Tests that using both --use-cache and --skip-cache fails."""
    result = runner.invoke(app, ["file", "id", TEST_FILE_PATH, "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    assert "Error: --use-cache and --skip-cache flags cannot be used together" in result.output
