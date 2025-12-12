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
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, mock_open
from typer.testing import CliRunner
from rich.console import Console
from rich.text import Text
from rich.panel import Panel


from dorsal.cli import app
from dorsal.common.exceptions import AuthError, NetworkError


import typer
from rich.logging import RichHandler

app_repro = typer.Typer()


@app_repro.callback()
def main_callback():
    console = Console(stderr=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@app_repro.command()
def hello():
    logging.info("Hello from command")
    raise typer.Exit()


runner = CliRunner()

MOCK_USER_INFO = {
    "user_id": "usr_12345",
    "name": "Test User",
    "email": "test@example.com",
    "account_status": "active",
}


def test_login_success(mocker, mock_rich_console, mock_auth_app):
    """Tests a successful 'auth login' (Global scope)."""
    mocker.patch("dorsal.client.DorsalClient").return_value.verify_credentials.return_value = MOCK_USER_INFO
    mocker.patch("dorsal.common.config.get_global_config_path", return_value=Path("/fake/path/dorsal.toml"))

    result = runner.invoke(app, ["auth", "login", "--apikey", "test-key-123"])

    assert result.exit_code == 0
    final_message = str(mock_rich_console.print.call_args_list[3].args[0])
    assert "Your API key has been saved to" in final_message
    assert str(Path("/fake/path/dorsal.toml")) in final_message


def test_login_project_scope(mocker, mock_rich_console, mock_auth_app):
    """
    Tests 'auth login --project'.
    Covers the logic that warns the user about committing the config file.
    """
    mocker.patch("dorsal.client.DorsalClient").return_value.verify_credentials.return_value = MOCK_USER_INFO

    # Mock finding a local dorsal.toml
    project_path = Path("/my/project/dorsal.toml")
    mocker.patch("dorsal.common.config.find_project_config_path", return_value=project_path)
    mock_write = mocker.patch("dorsal.common.auth.write_auth_config")

    result = runner.invoke(app, ["auth", "login", "--apikey", "pk_123", "--project"])

    assert result.exit_code == 0

    # Verify we wrote to project scope
    mock_write.assert_called_with(api_key="pk_123", email="test@example.com", scope="project")

    # Verify the security warning panel was printed
    # It's usually the last thing printed
    last_print_arg = mock_rich_console.print.call_args[0][0]
    assert isinstance(last_print_arg, Panel)
    assert "Action Required" in str(last_print_arg.title)
    assert "must not" in str(last_print_arg.renderable)
    assert "dorsal auth gitignore" in str(last_print_arg.renderable)


# --- Logout Tests ---


def test_logout_success(mocker, mock_rich_console, mock_auth_app):
    """Tests a successful 'auth logout'."""
    from dorsal.common.auth import APIKeySource

    mocker.patch(
        "dorsal.common.auth.get_api_key_details", return_value={"source": APIKeySource.PROJECT, "value": "a-real-key"}
    )
    mocker.patch("dorsal.common.auth.remove_api_key", return_value=True)

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    printed_text = mock_rich_console.print.call_args.args[0]
    assert "✅ You have been successfully logged out." in str(printed_text)


def test_logout_global_needs_force(mocker, mock_rich_console, mock_auth_app):
    """Tests that logging out of GLOBAL scope requires --force."""
    from dorsal.common.auth import APIKeySource

    mocker.patch(
        "dorsal.common.auth.get_api_key_details", return_value={"source": APIKeySource.GLOBAL, "value": "g-key"}
    )

    result = runner.invoke(app, ["auth", "logout"])

    # Should fail/exit early asking for confirmation
    assert result.exit_code == 0
    printed_text = str(mock_rich_console.print.call_args_list)
    assert "Warning" in printed_text
    assert "--force" in printed_text

    # Now try with force
    mock_remove = mocker.patch("dorsal.common.auth.remove_api_key", return_value=True)
    result_force = runner.invoke(app, ["auth", "logout", "--force"])

    assert result_force.exit_code == 0
    mock_remove.assert_called_with(scope=APIKeySource.GLOBAL)
    assert "successfully logged out" in str(mock_rich_console.print.call_args.args[0])


def test_logout_not_logged_in(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth logout' when no key exists."""
    from dorsal.common.auth import APIKeySource

    mocker.patch("dorsal.common.auth.get_api_key_details", return_value={"source": APIKeySource.NONE, "value": None})

    result = runner.invoke(app, ["auth", "logout"])
    assert result.exit_code == 0
    assert "not currently logged in" in str(mock_rich_console.print.call_args.args[0])


def test_logout_with_env_var_warning(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth logout' with an active ENV VAR."""
    from dorsal.common.auth import APIKeySource

    mocker.patch(
        "dorsal.common.auth.get_api_key_details", return_value={"source": APIKeySource.ENV, "value": "env-key"}
    )

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    panel_output = mock_rich_console.print.call_args_list[0].args[0]
    assert isinstance(panel_output, Panel)
    assert "Environment Variable Active" in str(panel_output.title)


# --- Whoami Tests ---


def test_whoami_success(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth whoami' success path."""
    mocker.patch(
        "dorsal.session.get_shared_dorsal_client"
    ).return_value.verify_credentials.return_value = MOCK_USER_INFO

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 0
    panel_output = mock_rich_console.print.call_args_list[2].args[0]
    assert isinstance(panel_output, Panel)
    assert "👤 Authenticated User" in str(panel_output.title)
    assert "Test User" in str(panel_output.renderable)


def test_whoami_json(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth whoami --json'."""
    mocker.patch(
        "dorsal.session.get_shared_dorsal_client"
    ).return_value.verify_credentials.return_value = MOCK_USER_INFO

    result = runner.invoke(app, ["auth", "whoami", "--json"])

    assert result.exit_code == 0
    # Verify the output was raw JSON (not a panel)
    output_str = mock_rich_console.print.call_args.args[0]
    assert '"user_id": "usr_12345"' in output_str
    assert '"email": "test@example.com"' in output_str


def test_whoami_auth_error(mocker, mock_auth_app):
    """
    Tests that the command bubbles up AuthError (does not swallow it).
    """
    # 1. Setup failure
    mocker.patch("dorsal.session.get_shared_dorsal_client").side_effect = AuthError("Auth failed.")

    # 2. Run command
    result = runner.invoke(app, ["auth", "whoami"])

    # 3. Assert CRASH (Not 0) and correct Exception type
    assert result.exit_code != 0
    assert isinstance(result.exception, AuthError)


# --- Gitignore Tests (High Coverage Gain) ---


def test_gitignore_no_git(mocker, mock_rich_console):
    """Tests behavior when 'git' is not installed."""
    mocker.patch("shutil.which", return_value=None)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code != 0
    assert "'git' command not found" in str(mock_rich_console.print.call_args.args[0])


def test_gitignore_not_repo(mocker, mock_rich_console):
    """Tests behavior when not in a git repository."""
    mocker.patch("shutil.which", return_value="/usr/bin/git")
    mocker.patch("subprocess.run", side_effect=subprocess.CalledProcessError(128, "git"))

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0
    assert "does not appear to be a Git repository" in str(mock_rich_console.print.call_args.args[0])


def test_gitignore_no_config(mocker, mock_rich_console):
    """Tests behavior when no dorsal.toml is found."""
    mocker.patch("shutil.which", return_value=True)
    mocker.patch("subprocess.run").return_value.stdout = "/repo/root"
    mocker.patch("dorsal.common.config.get_project_level_config", return_value=(None, None))

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0
    assert "No project-level config file found" in str(mock_rich_console.print.call_args.args[0])


def test_gitignore_config_safe(mocker, mock_rich_console):
    """Tests behavior when config exists but has no auth section."""
    mocker.patch("shutil.which", return_value=True)
    mocker.patch("subprocess.run").return_value.stdout = "/repo/root"

    # Config exists, is NOT empty, but has NO auth section
    config_path = Path("/repo/root/dorsal.toml")
    safe_config_data = {"general": {"theme": "dark"}}
    mocker.patch("dorsal.common.config.get_project_level_config", return_value=(safe_config_data, config_path))

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0

    all_output = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert "contains no 'auth' section" in all_output


def test_gitignore_already_exists(mocker, mock_rich_console):
    """Tests behavior when config is already in .gitignore."""
    mocker.patch("shutil.which", return_value=True)
    mocker.patch("subprocess.run").return_value.stdout = "/repo/root"

    config_path = Path("/repo/root/dorsal.toml")
    mocker.patch("dorsal.common.config.get_project_level_config", return_value=({"auth": "secrets"}, config_path))

    # Mock reading .gitignore
    mock_file = mock_open(read_data="random_file.txt\n/dorsal.toml\n")
    mocker.patch("builtins.open", mock_file)
    mocker.patch("pathlib.Path.exists", return_value=True)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0
    assert "already exists in .gitignore" in str(mock_rich_console.print.call_args_list[-2].args[0])
    # Should print the "File Still Tracked?" panel
    assert "File Still Tracked?" in str(mock_rich_console.print.call_args_list[-1].args[0].title)


def test_gitignore_add_success(mocker, mock_rich_console):
    """Tests successfully adding the config to .gitignore."""
    mocker.patch("shutil.which", return_value=True)
    mocker.patch("subprocess.run").return_value.stdout = "/repo/root"

    config_path = Path("/repo/root/dorsal.toml")
    mocker.patch("dorsal.common.config.get_project_level_config", return_value=({"auth": "secrets"}, config_path))

    # Mock reading .gitignore (empty) and checking existence
    mock_file = mock_open(read_data="")
    mocker.patch("builtins.open", mock_file)
    mocker.patch("pathlib.Path.exists", return_value=True)

    # Force user confirmation "y"
    mocker.patch("typer.confirm", return_value=True)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0

    # Check it wrote to the file
    mock_file().write.assert_called()
    written_data = mock_file().write.call_args[0][0]
    assert "/dorsal.toml" in written_data

    # Verify success message
    assert "Successfully added" in str(mock_rich_console.print.call_args.args[0])


def test_final_diagnostic_with_caplog(caplog):
    """Runs diagnostic app and captures log."""
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app_repro, ["hello"])
    assert result.exit_code == 0
    assert "Hello from command" in caplog.text
