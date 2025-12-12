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
from unittest.mock import MagicMock
from rich.panel import Panel


from dorsal.cli import app
from dorsal.cli.record_app import get_cmd
from dorsal.common.exceptions import NotFoundError, AuthError, DorsalClientError

runner = CliRunner()
HASH_STRING = "sha256:123abc456def"
MOCK_RECORD_DICT = {"name": "test.txt", "hash": HASH_STRING}


@pytest.fixture
def mock_get_cmd(mocker):
    """Mocks dependencies for the `record get` command."""
    # Mock the Pydantic model returned by the API
    mock_record_model = MagicMock()
    mock_record_model.model_dump.return_value = MOCK_RECORD_DICT
    # Use model_dump's return value for the json dump as well
    mock_record_model.model_dump_json.return_value = json.dumps(MOCK_RECORD_DICT)

    # Patch dependencies at their source due to lazy loading
    mock_get_record = mocker.patch("dorsal.api.get_dorsal_file_record", return_value=mock_record_model)
    mock_create_panel = mocker.patch("dorsal.cli.views.file.create_file_info_panel", return_value=Panel("Mock Panel"))
    mock_save_report = mocker.patch.object(get_cmd, "_save_json_report")

    return {
        "get_dorsal_file_record": mock_get_record,
        "create_file_info_panel": mock_create_panel,
        "save_get_report": mock_save_report,
    }


def test_get_record_success_default(mock_rich_console, mock_get_cmd):
    """Tests the default successful get, expecting a Rich Panel."""
    result = runner.invoke(app, ["record", "get", HASH_STRING])

    assert result.exit_code == 0
    mock_get_cmd["get_dorsal_file_record"].assert_called_once_with(
        hash_string=HASH_STRING, private=None, mode="pydantic"
    )
    mock_get_cmd["create_file_info_panel"].assert_called_once()
    mock_get_cmd["save_get_report"].assert_not_called()

    # Check that the status message and panel were printed
    assert mock_rich_console.print.call_count == 2
    assert isinstance(mock_rich_console.print.call_args.args[0], Panel)


@pytest.mark.parametrize("flag, expected_scope", [("--private", True), ("--public", False)])
def test_get_record_scopes(flag, expected_scope, mock_get_cmd):
    """Tests the --private and --public scope flags."""
    runner.invoke(app, ["record", "get", HASH_STRING, flag])

    assert mock_get_cmd["get_dorsal_file_record"].call_args.kwargs["private"] is expected_scope


def test_get_record_json_output(mock_rich_console, mock_get_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["record", "get", HASH_STRING, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)

    assert data == MOCK_RECORD_DICT
    # UI and save helpers should not be called in JSON mode
    mock_get_cmd["create_file_info_panel"].assert_not_called()
    mock_get_cmd["save_get_report"].assert_not_called()


def test_get_record_save_to_output_file(mock_get_cmd, tmp_path):
    """Tests that the --output flag triggers the save helper with the correct path."""
    output_file = tmp_path / "record.json"
    runner.invoke(app, ["record", "get", HASH_STRING, "--output", str(output_file)])

    mock_get_cmd["save_get_report"].assert_called_once()
    assert mock_get_cmd["save_get_report"].call_args.kwargs["output_path"] == output_file


def test_get_record_not_found_panel(mock_rich_console, mock_get_cmd):
    """Tests the not-found case with standard output."""
    mock_get_cmd["get_dorsal_file_record"].side_effect = NotFoundError("No file found.")

    result = runner.invoke(app, ["record", "get", HASH_STRING])

    assert result.exit_code == 0  # Graceful exit with message
    assert "Not Found" in mock_rich_console.print.call_args.args[0]


def test_get_record_not_found_json(mock_rich_console, mock_get_cmd):
    """Tests the not-found case with --json output."""
    mock_get_cmd["get_dorsal_file_record"].side_effect = NotFoundError("No file found.")

    result = runner.invoke(app, ["record", "get", HASH_STRING, "--json"])

    assert result.exit_code != 0
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data["success"] is False
    assert data["error"] == "Not Found"


def test_get_record_flag_conflict():
    """Tests that using both --private and --public fails."""
    result = runner.invoke(app, ["record", "get", HASH_STRING, "--private", "--public"])

    assert result.exit_code != 0
    assert "Cannot use --private and --public flags simultaneously" in result.output


def test_get_record_api_error(mock_get_cmd):
    """Tests that a generic DorsalClientError is handled correctly."""
    mock_get_cmd["get_dorsal_file_record"].side_effect = DorsalClientError("Connection failed.")

    result = runner.invoke(app, ["record", "get", HASH_STRING])

    assert result.exit_code != 0
    assert "API Error: Connection failed." in result.output
