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

import os
import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner
from rich.panel import Panel


from dorsal.cli import app

runner = CliRunner()

# Use a real file from your test data directory
TEST_FILE_PATH = "tests/data/valid.txt"

# A dictionary of mock hashes to be returned by the mocked HASH_READER
MOCK_HASHES = {
    "SHA-256": "sha256_hash_value",
    "BLAKE3": "blake3_hash_value",
    "TLSH": "tlsh_hash_value",
    "QUICK": "quick_hash_value",
}


# This fixture is kept local and no longer uses pyfakefs.
@pytest.fixture
def mock_hash_cmd(mocker):
    """
    Mocks dependencies for the `file hash` command.
    """
    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=True)
    mock_hash_reader = mocker.patch("dorsal.file.hash_reader.HASH_READER.get", return_value=MOCK_HASHES)
    mocker.patch(
        "dorsal.file.utils.quick_hasher.QuickHasher.min_permitted_filesize",
        10 * 1024 * 1024,
    )
    return mock_hash_reader


def test_hash_all_hashes_table_output(mock_rich_console, mock_hash_cmd):
    """Tests the default case with no flags, expecting a Rich Panel."""
    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH])

    assert result.exit_code == 0
    mock_hash_cmd.assert_called_once()
    assert set(mock_hash_cmd.call_args.kwargs["hashes"]) == {
        "SHA-256",
        "BLAKE3",
        "TLSH",
        "QUICK",
    }
    panel_output = mock_rich_console.print.call_args.args[0]
    assert isinstance(panel_output, Panel)


def test_hash_single_hash_plain_output(mock_rich_console, mock_hash_cmd):
    """Tests requesting a single hash, expecting plain text output."""
    normalized_path = os.path.normpath(str(TEST_FILE_PATH))
    result = runner.invoke(app, ["file", "hash", normalized_path, "--sha256"])

    assert result.exit_code == 0
    mock_hash_cmd.assert_called_once_with(file_path=normalized_path, hashes=["SHA-256"], skip_cache=False)
    mock_rich_console.print.assert_called_with("sha256_hash_value")


def test_hash_json_output(mock_rich_console, mock_hash_cmd):
    """Tests the --json flag, expecting a JSON string."""
    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH, "--json"])

    assert result.exit_code == 0
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data == MOCK_HASHES


def test_hash_cache_flag_conflict():
    """Tests that using both --use-cache and --skip-cache fails."""
    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH, "--use-cache", "--skip-cache"])

    assert result.exit_code != 0
    assert "Error: --use-cache and --skip-cache flags cannot be used together" in result.output


def test_hash_skip_cache_passthrough(mock_hash_cmd, mocker):
    """Tests that --skip-cache flag is passed correctly to the hash reader."""
    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=False)

    runner.invoke(app, ["file", "hash", TEST_FILE_PATH, "--skip-cache"])

    mock_hash_cmd.assert_called_once()
    assert mock_hash_cmd.call_args.kwargs["skip_cache"] is True


def test_hash_reader_exception(mock_hash_cmd):
    """Tests that an exception from the HASH_READER is handled gracefully."""
    mock_hash_cmd.side_effect = Exception("Disk read error")
    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH])

    assert result.exit_code != 0
    assert "Disk read error" in result.output


def test_hash_quickhash_too_small_single(mock_rich_console, mock_hash_cmd):
    """Tests the info message when only --quick is requested and the file is too small."""
    mock_hash_cmd.return_value = {"QUICK": None}
    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH, "--quick"])

    assert result.exit_code == 0
    info_message = mock_rich_console.print.call_args.args[0]
    assert "QuickHash not generated" in info_message
    assert "10MiB minimum" in info_message


@patch("rich.table.Table.grid")
def test_hash_quickhash_too_small_table(mock_table_grid, mock_rich_console, mock_hash_cmd):
    """Tests the info message within the table when all hashes are requested."""
    mock_table = MagicMock()
    mock_table_grid.return_value = mock_table
    mock_hash_cmd.return_value = {**MOCK_HASHES, "QUICK": None}

    result = runner.invoke(app, ["file", "hash", TEST_FILE_PATH])

    assert result.exit_code == 0
    all_rows_text = ""
    for call in mock_table.add_row.call_args_list:
        all_rows_text += " ".join(str(arg) for arg in call.args)

    assert "File size below 10MiB minimum" in all_rows_text
    assert "sha256_hash_value" in all_rows_text
