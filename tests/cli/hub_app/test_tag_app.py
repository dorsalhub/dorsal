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
from typer.testing import CliRunner
from unittest.mock import MagicMock
from rich.panel import Panel

from dorsal.cli import app
from dorsal.common.exceptions import (
    NotFoundError,
    DuplicateTagError,
    DorsalClientError,
    ForbiddenError,
    BadRequestError,
    TaggingError,
    DorsalOfflineError,
    AuthError,
)

runner = CliRunner()
HASH_STRING = "sha256:123abc456def"
TAG_ID = "tag_xyz789"


@pytest.fixture
def mock_tag_app_cmds(mocker):
    """Mocks dependencies for the `record tag` subcommands."""

    mock_add_response = MagicMock()
    mock_add_response.model_dump_json.return_value = '{"success": true}'

    mock_add = mocker.patch("dorsal.api.file.add_tag_to_file", return_value=mock_add_response)

    mock_add_label = mocker.patch("dorsal.api.file.add_label_to_file", return_value=mock_add_response)

    mock_remove = mocker.patch("dorsal.api.file.remove_tag_from_file")

    return {
        "add_tag": mock_add,
        "add_label": mock_add_label,
        "add_response": mock_add_response,
        "remove_tag": mock_remove,
    }


def test_add_tag_success_private(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a private tag (the default)."""
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "key", "--value", "val"])

    assert result.exit_code == 0
    mock_tag_app_cmds["add_tag"].assert_called_once_with(hash_string=HASH_STRING, name="key", value="val", public=False)
    assert "Successfully added tag" in mock_rich_console.print.call_args.args[0]


def test_add_tag_success_public(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a public tag with the --public flag."""
    result = runner.invoke(
        app,
        [
            "hub",
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
    mock_tag_app_cmds["add_tag"].assert_called_once_with(hash_string=HASH_STRING, name="key", value="val", public=True)


def test_add_label_success(mock_rich_console, mock_tag_app_cmds):
    """Tests adding a simple label using the shorthand argument."""

    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "urgent"])

    assert result.exit_code == 0

    mock_tag_app_cmds["add_label"].assert_called_once_with(hash_string=HASH_STRING, label="urgent")

    mock_tag_app_cmds["add_tag"].assert_not_called()
    assert "(label)" in mock_rich_console.print.call_args_list[0].args[0]


def test_add_label_error_public(mock_rich_console, mock_tag_app_cmds):
    """Tests that combining a label with --public raises an error."""

    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "urgent", "--public"])

    assert result.exit_code == 1

    mock_tag_app_cmds["add_label"].assert_not_called()
    mock_tag_app_cmds["add_tag"].assert_not_called()

    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Simple labels must be PRIVATE" in str(printed_object.renderable)


def test_add_label_error_ambiguous(mock_rich_console, mock_tag_app_cmds):
    """Tests that combining a label with --name/--value raises an error."""

    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "urgent", "--name", "genre"])

    assert result.exit_code == 1
    mock_tag_app_cmds["add_label"].assert_not_called()

    printed_object = mock_rich_console.print.call_args.args[0]
    assert "Ambiguous Request" in str(printed_object.renderable)


def test_add_tag_missing_args(mock_rich_console, mock_tag_app_cmds):
    """Tests error when neither a label nor name/value pairs are provided."""

    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING])

    assert result.exit_code == 1
    printed_object = mock_rich_console.print.call_args.args[0]
    assert "Missing Arguments" in str(printed_object.renderable)


def test_add_tag_json_output(mock_rich_console, mock_tag_app_cmds):
    """Tests the --json output for the add command."""
    result = runner.invoke(
        app,
        ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v", "--json"],
    )

    assert result.exit_code == 0
    mock_tag_app_cmds["add_response"].model_dump_json.assert_called_once()
    mock_rich_console.print.assert_called_once_with('{"success": true}')


def test_add_tag_not_found_error(mock_rich_console, mock_tag_app_cmds):
    """Tests error handling when the target file for adding a tag is not found."""
    mock_tag_app_cmds["add_tag"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])

    assert result.exit_code != 0
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Cannot add tag: No file record found" in str(printed_object.renderable)


def test_remove_tag_success(mock_rich_console, mock_tag_app_cmds):
    """Tests successfully removing a tag."""
    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])

    assert result.exit_code == 0
    mock_tag_app_cmds["remove_tag"].assert_called_once_with(hash_string=HASH_STRING, tag_id=TAG_ID)
    assert "Successfully removed tag" in mock_rich_console.print.call_args.args[0]


def test_remove_tag_json_output(mock_rich_console, mock_tag_app_cmds):
    """Tests the --json output for the remove command."""
    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID, "--json"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    json_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_str)
    assert data["success"] is True
    assert f"Tag '{TAG_ID}' removed" in data["detail"]


def test_remove_tag_not_found_error(mock_rich_console, mock_tag_app_cmds):
    """Tests error handling when the file or tag to remove is not found."""
    mock_tag_app_cmds["remove_tag"].side_effect = NotFoundError("test")

    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])

    assert result.exit_code != 0
    printed_object = mock_rich_console.print.call_args.args[0]
    assert isinstance(printed_object, Panel)
    assert "Could not find a file with that hash" in str(printed_object.renderable)


def test_add_tag_forbidden_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = ForbiddenError("Permission denied.")
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])
    assert result.exit_code != 0
    assert "Cannot add tag. Permission denied." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_add_tag_bad_request_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = BadRequestError("Invalid payload.", "https://api.dorsal.hub/tags")
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])

    assert result.exit_code != 0
    assert "The server rejected the tag 'k:v'." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_add_tag_duplicate_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = DuplicateTagError("Tag already exists.")
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])
    assert result.exit_code != 0
    assert "Invalid Tag: Tag already exists." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_add_tag_offline_error(mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = DorsalOfflineError()

    with pytest.raises(DorsalOfflineError):
        runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"], catch_exceptions=False)


def test_add_tag_auth_error(mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = AuthError("Token expired.")

    with pytest.raises(AuthError):
        runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"], catch_exceptions=False)


def test_add_tag_client_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = DorsalClientError("Connection reset.")
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])
    assert result.exit_code != 0
    assert "API Error: Connection reset." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_add_tag_generic_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["add_tag"].side_effect = Exception("System meltdown.")
    result = runner.invoke(app, ["hub", "tag", "add", HASH_STRING, "--name", "k", "--value", "v"])
    assert result.exit_code != 0
    assert "An unexpected error occurred: System meltdown." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_remove_tag_value_error(mock_rich_console, mock_tag_app_cmds):

    mock_tag_app_cmds["remove_tag"].side_effect = ValueError("Malformed tag ID.")
    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])
    assert result.exit_code != 0
    assert "Invalid Request: Malformed tag ID." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_remove_tag_offline_error(mock_tag_app_cmds):
    mock_tag_app_cmds["remove_tag"].side_effect = DorsalOfflineError()
    with pytest.raises(DorsalOfflineError):
        runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID], catch_exceptions=False)


def test_remove_tag_auth_error(mock_tag_app_cmds):
    mock_tag_app_cmds["remove_tag"].side_effect = AuthError("Invalid credentials.")
    with pytest.raises(AuthError):
        runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID], catch_exceptions=False)


def test_remove_tag_client_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["remove_tag"].side_effect = DorsalClientError("Gateway timeout.")
    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])
    assert result.exit_code != 0
    assert "API Error: Gateway timeout." in str(mock_rich_console.print.call_args.args[0].renderable)


def test_remove_tag_generic_error(mock_rich_console, mock_tag_app_cmds):
    mock_tag_app_cmds["remove_tag"].side_effect = Exception("Database locked.")
    result = runner.invoke(app, ["hub", "tag", "rm", HASH_STRING, "--tag-id", TAG_ID])
    assert result.exit_code != 0
    assert "An unexpected error occurred: Database locked." in str(mock_rich_console.print.call_args.args[0].renderable)
