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
from unittest.mock import MagicMock, ANY


from dorsal.cli import app
from dorsal.cli.collection_app import export_cmd
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


@pytest.fixture
def mock_export_collection_cmd(mocker):
    """Mocks dependencies for the `collection export` command."""

    mock_export = mocker.patch("dorsal.api.collection.export_collection")

    mock_exports_dir = MagicMock(spec=pathlib.Path)

    default_save_dir = MagicMock(spec=pathlib.Path)
    final_path_obj = MagicMock(spec=pathlib.Path)

    mock_exports_dir.__truediv__.return_value = default_save_dir
    default_save_dir.__truediv__.return_value = final_path_obj

    expected_path_str = f"/fake/exports/{COLLECTION_ID}/export-{COLLECTION_ID}-20250101-120000.json.gz"
    final_path_obj.__str__.return_value = expected_path_str

    mocker.patch("dorsal.common.constants.CLI_EXPORTS_DIR", mock_exports_dir)

    # Mock time.strftime to create a predictable timestamp
    mocker.patch.object(export_cmd.time, "strftime", return_value="20250101-120000")

    return {
        "export_collection": mock_export,
        "exports_dir": mock_exports_dir,
    }


def test_export_collection_default_path(mock_rich_console, mock_export_collection_cmd):
    """Tests exporting with the default output path logic."""
    result = runner.invoke(app, ["collection", "export", COLLECTION_ID])

    assert result.exit_code == 0

    save_dir_mock = mock_export_collection_cmd["exports_dir"]
    save_dir_mock.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    expected_file = save_dir_mock / f"export-{COLLECTION_ID}-20250101-120000.json.gz"

    mock_export_collection_cmd["export_collection"].assert_called_once_with(
        collection_id=COLLECTION_ID,
        output_path=expected_file,
        console=mock_rich_console,
        palette=ANY,
    )
    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "Export complete" in all_printed_text


def test_export_collection_with_output_dir(mock_export_collection_cmd, tmp_path):
    """Tests exporting to a user-specified directory."""
    result = runner.invoke(app, ["collection", "export", COLLECTION_ID, "--output-dir", str(tmp_path)])

    assert result.exit_code == 0

    expected_file = tmp_path / f"{COLLECTION_ID}-20250101-120000.json.gz"

    assert mock_export_collection_cmd["export_collection"].call_args.kwargs["output_path"] == expected_file


def test_export_collection_json_output(mock_rich_console, mock_export_collection_cmd):
    """Tests a successful export with --json output."""
    expected_filename = f"{COLLECTION_ID}-20250101-120000.json.gz"
    expected_full_path_str = f"/tmp/dorsal/exports/{expected_filename}"
    save_dir_mock = mock_export_collection_cmd["exports_dir"]
    output_file_mock = MagicMock(spec=pathlib.Path)
    save_dir_mock.__truediv__.return_value = output_file_mock
    output_file_mock.__str__.return_value = expected_full_path_str

    result = runner.invoke(app, ["collection", "export", COLLECTION_ID, "--json"])
    assert result.exit_code == 0

    mock_rich_console.print.assert_called_once()
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data["success"] is True
    assert data["collection_id"] == COLLECTION_ID
    assert data["output_path"] == expected_full_path_str

    assert expected_filename in data["output_path"]


def test_export_collection_api_error(mock_export_collection_cmd):
    """Tests graceful failure on a DorsalClientError from the backend."""
    mock_export_collection_cmd["export_collection"].side_effect = DorsalClientError("Collection is empty")

    result = runner.invoke(app, ["collection", "export", COLLECTION_ID])

    assert result.exit_code != 0
    assert "API Error: Collection is empty" in result.output
