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
import re
import pathlib
from typer.testing import CliRunner
from unittest.mock import MagicMock, call


from dorsal.cli import app


from dorsal.cli.local_app import duplicates_cmd


runner = CliRunner()

TEST_DATA_DIR = "tests/data"

MOCK_DUPLICATES_RESULT = {
    "path": str(TEST_DATA_DIR),
    "total_sets": 1,
    "hashes_from_cache": 5,
    "duplicate_sets": [
        {
            "hash": "hash_val_1",
            "hash_type": "sha256",
            "count": 2,
            "file_size": "10.0 KB",
            "file_size_bytes": 10240,
            "paths": [f"{TEST_DATA_DIR}/file_a.txt", f"{TEST_DATA_DIR}/file_b.txt"],
        }
    ],
}


@pytest.fixture
def mock_duplicates_cmd(mocker):
    """Mocks backend dependencies for the `local duplicates` command."""
    import dorsal.api.file

    mocker.patch("dorsal.common.cli.determine_use_cache_value", return_value=True)

    mock_find_dupes = mocker.patch.object(dorsal.api.file, "find_duplicates", return_value=MOCK_DUPLICATES_RESULT)

    mock_save_report = mocker.patch.object(duplicates_cmd, "_save_duplicates_report")

    return {
        "find_duplicates": mock_find_dupes,
        "save_report": mock_save_report,
    }


def test_duplicates_dir_success_panel_output(mock_rich_console, mock_error_console, mock_duplicates_cmd, rendered):
    """Tests the default `local duplicates` command renders each set borderless, without emoji."""
    result = runner.invoke(app, ["local", "duplicates", TEST_DATA_DIR])

    assert result.exit_code == 0, f"CLI exited with error: {result.output}"

    text = rendered(mock_rich_console)
    lines = text.splitlines()
    assert "Duplicate set 1 of 1  10.0 KB each" in lines
    assert "  SHA256 hash_val_1" in lines
    assert f"  {TEST_DATA_DIR}/file_a.txt" in lines
    assert "Found 1 set(s) of duplicate files (5 hashes from cache)" in text
    assert "Searching for duplicate files" not in text
    assert "Searching for duplicate files" in rendered(mock_error_console)
    assert not re.search("[\u2600-\u27bf\U0001f000-\U0001faff\ufe0f]", text)
    assert all(line == line.rstrip() for line in lines)
    assert not text.startswith("\n")

    mock_duplicates_cmd["find_duplicates"].assert_called_once()
    mock_duplicates_cmd["save_report"].assert_not_called()


def test_duplicates_long_path_fits_console_width(
    mock_rich_console, mock_error_console, mock_duplicates_cmd, tmp_path, rendered
):
    target = tmp_path / ("a-long-directory-name-" * 4)
    target.mkdir()

    result = runner.invoke(app, ["local", "duplicates", str(target)])

    assert result.exit_code == 0
    lines = rendered(mock_error_console, width=80).splitlines()
    assert max(len(line) for line in lines) <= 80
    assert str(target) in "".join(lines)


def test_duplicates_dir_no_duplicates(mock_rich_console, mock_duplicates_cmd):
    """Tests the output when no duplicates are found."""
    mock_duplicates_cmd["find_duplicates"].return_value = {}

    result = runner.invoke(app, ["local", "duplicates", TEST_DATA_DIR])

    assert result.exit_code == 0, f"CLI exited with error: {result.output}"

    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "No duplicate files found" in all_printed_text


def test_duplicates_dir_json_output(mock_rich_console, mock_duplicates_cmd):
    """Tests the --json output flag."""
    result = runner.invoke(app, ["local", "duplicates", TEST_DATA_DIR, "--json"])

    assert result.exit_code == 0, f"CLI exited with error: {result.output}"

    mock_rich_console.print.assert_called_once()
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["total_sets"] == 1
    mock_duplicates_cmd["save_report"].assert_not_called()


def test_duplicates_dir_limit_output(mock_rich_console, mock_duplicates_cmd, rendered):
    """Tests that the --limit flag correctly limits the number of printed panels."""
    multi_result = {
        **MOCK_DUPLICATES_RESULT,
        "total_sets": 2,
        "duplicate_sets": [
            MOCK_DUPLICATES_RESULT["duplicate_sets"][0],
            {
                "hash": "hash_val_2",
                "paths": ["c.txt", "d.txt"],
                "file_size": "5.0 KB",
                "hash_type": "sha256",
                "count": 2,
                "file_size_bytes": 5120,
            },
        ],
    }
    mock_duplicates_cmd["find_duplicates"].return_value = multi_result

    result = runner.invoke(app, ["local", "duplicates", TEST_DATA_DIR, "--limit", "1"])

    assert result.exit_code == 0, f"CLI exited with error: {result.output}"
    text = rendered(mock_rich_console)
    assert "Duplicate set 1 of 2" in text
    assert "Duplicate set 2 of 2" not in text
    assert "Displaying the 1 largest duplicate sets." in text
    assert "… and 1 more sets." in text


def test_duplicates_dir_exception_handling(mock_rich_console, mock_duplicates_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_duplicates_cmd["find_duplicates"].side_effect = Exception("File system is unreadable")

    result = runner.invoke(app, ["local", "duplicates", TEST_DATA_DIR])

    assert result.exit_code != 0

    assert "File system is unreadable" in result.output
