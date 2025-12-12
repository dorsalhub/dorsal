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
from dorsal.common.exceptions import NotFoundError, DuplicateTagError, DorsalClientError

runner = CliRunner()
HASH_STRING = "sha256:123abc456def"
TAG_ID = "tag_xyz789"


@pytest.fixture
def mock_tag_app_cmds(mocker):
    """Mocks dependencies for the `record tag` subcommands."""
    # Mock response object
    mock_add_response = MagicMock()
    mock_add_response.model_dump_json.return_value = '{"success": true}'

    # Mock standard tag addition
    mock_add = mocker.patch("dorsal.api.file.add_tag_to_file", return_value=mock_add_response)

    mock_add_label = mocker.patch("dorsal.api.file.add_label_to_file", return_value=mock_add_response)

    # Mock removal
    mock_remove = mocker.patch("dorsal.api.file.remove_tag_from_file")

    return {
        "add_tag": mock_add,
        "add_label": mock_add_label,
        "add_response": mock_add_response,
        "remove_tag": mock_remove,
    }


# --- Tests for `record tag add` ---


def test_add_tag_success_private(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a private tag (the default)."""
    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING, "--name", "key", "--value", "val"])

    assert result.exit_code == 0
    mock_tag_app_cmds["add_tag"].assert_called_once_with(hash_string=HASH_STRING, name="key", value="val", private=True)
    assert "Successfully added tag" in mock_rich_console.print.call_args.args[0]


def test_add_tag_success_public(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a public tag with the --public flag."""
    result = runner.invoke(
        app,
        [
            "record",
            "tag",
            "add",
            HASH_STRING,
            "--name",
            "key",
            "--value",
            "val",
            "--public",
        ],
    )

    assert result.exit_code == 0
    mock_tag_app_cmds["add_tag"].assert_called_once_with(
        hash_string=HASH_STRING, name="key", value="val", private=False
    )


def test_add_label_success(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a simple label using the shorthand argument."""
    # Command: dorsal record tag add <hash> "urgent"
    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING, "urgent"])

    assert result.exit_code == 0
    # Verify it delegates to the specific label API function
    mock_tag_app_cmds["add_label"].assert_called_once_with(hash_string=HASH_STRING, label="urgent")
    # Verify the standard add_tag was NOT called
    mock_tag_app_cmds["add_tag"].assert_not_called()
    assert "(label)" in mock_rich_console.print.call_args_list[0].args[0]


def test_add_label_error_public(mock_rich_console, mock_tag_app_cmds):
    """Tests that combining a label with --public raises an error."""
    # Command: dorsal record tag add <hash> "urgent" --public
    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING, "urgent", "--public"])

    assert result.exit_code == 1

    # Verify API was NOT called
    mock_tag_app_cmds["add_label"].assert_not_called()
    mock_tag_app_cmds["add_tag"].assert_not_called()

    # Verify error message
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Simple labels must be PRIVATE" in str(printed_object.renderable)


def test_add_label_error_ambiguous(mock_rich_console, mock_tag_app_cmds):
    """Tests that combining a label with --name/--value raises an error."""
    # Command: dorsal record tag add <hash> "urgent" --name "genre"
    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING, "urgent", "--name", "genre"])

    assert result.exit_code == 1
    mock_tag_app_cmds["add_label"].assert_not_called()

    printed_object = mock_rich_console.print.call_args.args[0]
    assert "Ambiguous Request" in str(printed_object.renderable)


def test_add_tag_missing_args(mock_rich_console, mock_tag_app_cmds):
    """Tests error when neither a label nor name/value pairs are provided."""
    # Command: dorsal record tag add <hash>
    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING])

    assert result.exit_code == 1
    printed_object = mock_rich_console.print.call_args.args[0]
    assert "Missing Arguments" in str(printed_object.renderable)


def test_add_tag_json_output(mock_rich_console, mock_tag_app_cmds):
    """Tests the --json output for the add command."""
    result = runner.invoke(
        app,
        ["record", "tag", "add", HASH_STRING, "--name", "k", "--value", "v", "--json"],
    )

    assert result.exit_code == 0
    mock_tag_app_cmds["add_response"].model_dump_json.assert_called_once()
    mock_rich_console.print.assert_called_once_with('{"success": true}')


def test_add_tag_not_found_error(mock_rich_console, mock_tag_app_cmds):
    """Tests error handling when the target file for adding a tag is not found."""
    mock_tag_app_cmds["add_tag"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["record", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])

    assert result.exit_code != 0
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Cannot add tag: No file record found" in str(printed_object.renderable)


def test_remove_tag_success(mock_rich_console, mock_tag_app_cmds):
    """Tests successfully removing a tag."""
    result = runner.invoke(app, ["record", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])

    assert result.exit_code == 0
    mock_tag_app_cmds["remove_tag"].assert_called_once_with(hash_string=HASH_STRING, tag_id=TAG_ID)
    assert "Successfully removed tag" in mock_rich_console.print.call_args.args[0]


def test_remove_tag_json_output(mock_rich_console, mock_tag_app_cmds):
    """Tests the --json output for the remove command."""
    result = runner.invoke(app, ["record", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data["success"] is True
    assert f"Tag '{TAG_ID}' removed" in data["detail"]


def test_remove_tag_not_found_error(mock_rich_console, mock_tag_app_cmds):
    """Tests error handling when the file or tag to remove is not found."""
    mock_tag_app_cmds["remove_tag"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["record", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])

    assert result.exit_code != 0
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Could not find a file with that hash" in str(printed_object.renderable)
