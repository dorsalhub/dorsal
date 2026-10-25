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

import io
import json

import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.console import Console


from dorsal.cli import app
from dorsal.common.exceptions import DorsalClientError

runner = CliRunner()
COLLECTION_ID = "col_abc123"


def _render(renderable, width: int = 120) -> str:
    console = Console(width=width)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


class StdinSimulator(io.StringIO):
    def isatty(self):
        return False


@pytest.fixture
def mock_add_files_cmd(mocker):
    """Mocks dependencies for the `collection add-files` command."""
    mock_add_response = MagicMock()
    mock_add_response.added_count = 2
    mock_add_response.duplicate_count = 1
    mock_add_response.invalid_count = 0
    mock_add_response.model_dump_json.return_value = "{}"

    mock_get_collection_response = MagicMock()
    mock_get_collection_response.collection.is_private = True

    mock_add = mocker.patch("dorsal.api.collection.add_files_to_collection", return_value=mock_add_response)
    mock_get = mocker.patch(
        "dorsal.api.collection.get_collection",
        return_value=mock_get_collection_response,
    )

    return {
        "add_files": mock_add,
        "get_collection": mock_get,
        "add_response": mock_add_response,
        "get_collection_response": mock_get_collection_response,
    }


def test_add_files_with_hash_options(mock_rich_console, mock_add_files_cmd):
    """Tests adding files using multiple --hash options."""
    hashes_to_add = ["hash1", "hash2"]
    result = runner.invoke(
        app,
        [
            "collection",
            "add-files",
            COLLECTION_ID,
            "--hash",
            hashes_to_add[0],
            "--hash",
            hashes_to_add[1],
        ],
    )

    assert result.exit_code == 0
    # The command may change the order, so we check the contents
    called_hashes = mock_add_files_cmd["add_files"].call_args.kwargs["hashes"]
    assert sorted(called_hashes) == sorted(hashes_to_add)

    lines = _render(mock_rich_console.print.call_args.args[0]).splitlines()
    assert lines[0] == "Update complete"
    assert lines[1].split() == ["Added", "2"]
    assert lines[2].split() == ["Duplicates", "ignored", "1"]
    assert lines[1].index("2") == lines[2].index("1")
    assert all(line.startswith("  ") and line == line.rstrip() for line in lines[1:])


def test_add_files_bordered(mock_rich_console, mock_add_files_cmd):
    """With --borders rounded the result is a panel."""
    result = runner.invoke(app, ["--borders", "rounded", "collection", "add-files", COLLECTION_ID, "--hash", "h1"])

    assert result.exit_code == 0
    output = _render(mock_rich_console.print.call_args.args[0])
    assert output.startswith("╭─ Update complete ")
    assert "Added" in output


def test_add_files_from_stdin(mock_rich_console, mock_add_files_cmd, mocker):
    """Tests adding files by reading hashes from stdin."""
    hashes_to_add = ["hash1", "hash2", "hash3"]

    mocker.patch(
        "dorsal.cli.collection_app.add_files_cmd._get_hashes",
        return_value=hashes_to_add,
    )

    result = runner.invoke(
        app,
        [
            "collection",
            "add-files",
            COLLECTION_ID,
            "--from-stdin",
        ],
    )

    assert result.exit_code == 0
    called_hashes = mock_add_files_cmd["add_files"].call_args.kwargs["hashes"]
    assert sorted(called_hashes) == sorted(hashes_to_add)


def test_add_files_no_hashes_error():
    """Tests that the command fails if no hashes are provided."""
    result = runner.invoke(app, ["collection", "add-files", COLLECTION_ID])

    assert result.exit_code != 0
    assert "No file hashes provided" in result.output


def test_add_files_json_output(mock_rich_console, mock_add_files_cmd):
    """Tests a successful add with --json output."""
    result = runner.invoke(app, ["collection", "add-files", COLLECTION_ID, "--hash", "hash1", "--json"])

    assert result.exit_code == 0
    mock_add_files_cmd["add_response"].model_dump_json.assert_called_once()
    mock_rich_console.file.write.assert_called_once_with(
        mock_add_files_cmd["add_response"].model_dump_json.return_value + "\n"
    )


def test_add_files_with_invalid_count(mock_rich_console, mock_add_files_cmd):
    """Tests that the command fetches collection info when some hashes are invalid."""
    mock_add_files_cmd["add_response"].invalid_count = 1

    result = runner.invoke(app, ["collection", "add-files", COLLECTION_ID, "--hash", "hash1"])

    assert result.exit_code == 0

    mock_add_files_cmd["get_collection"].assert_called_once_with(
        collection_id=COLLECTION_ID, hydrate=False, mode="pydantic"
    )

    output = _render(mock_rich_console.print.call_args.args[0])
    assert any(line.split() == ["Not", "added", "1"] for line in output.splitlines())
    assert "Note: Files can only be added" in output
