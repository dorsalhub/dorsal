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
import logging
import subprocess
from pathlib import Path
from unittest.mock import mock_open
from typer.testing import CliRunner
from rich.console import Console


from dorsal.cli import app
from dorsal.common.exceptions import AuthError, NetworkError


import typer
from rich.logging import RichHandler

app_repro = typer.Typer()


@app_repro.callback()
def main_callback():
    console = Console(legacy_windows=False, stderr=True)
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


def _printed(mock_console) -> str:
    """Renders everything printed to a mocked console as plain text."""
    console = Console(legacy_windows=False, record=True, width=120, file=io.StringIO())
    for call in mock_console.print.call_args_list:
        console.print(*call.args)
    return console.export_text()


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
    output = _printed(mock_rich_console)
    assert "Login successful\n  User ID         usr_12345\n" in output
    assert "  Account status  active\n" in output
    assert "Your API key has been saved to" in output
    assert str(Path("/fake/path/dorsal.toml")) in output
    assert "✅" not in output
    assert "Action required" not in output


def test_login_success_bordered(mocker, mock_rich_console, mock_auth_app):
    """Tests that `auth login` draws a panel when borders are enabled."""
    mocker.patch("dorsal.client.DorsalClient").return_value.verify_credentials.return_value = MOCK_USER_INFO
    mocker.patch("dorsal.common.config.get_global_config_path", return_value=Path("/fake/path/dorsal.toml"))

    result = runner.invoke(app, ["--borders", "rounded", "auth", "login", "--apikey", "test-key-123"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)
    assert "╭─ Login successful" in output
    assert "│  User ID         usr_12345" in output


def test_login_project_scope(mocker, mock_rich_console, mock_auth_app):
    """
    Tests 'auth login --project'.
    Covers the logic that warns the user about committing the config file.
    """
    mocker.patch("dorsal.client.DorsalClient").return_value.verify_credentials.return_value = MOCK_USER_INFO

    project_path = Path("/my/project/dorsal.toml")
    mocker.patch("dorsal.common.config.find_project_config_path", return_value=project_path)
    mock_write = mocker.patch("dorsal.common.auth.write_auth_config")

    result = runner.invoke(app, ["auth", "login", "--apikey", "pk_123", "--project"])

    assert result.exit_code == 0

    mock_write.assert_called_with(api_key="pk_123", email="test@example.com", scope="project")

    output_text = _printed(mock_rich_console)
    assert "\nAction required\n  The file 'dorsal.toml' now contains your API key." in output_text
    assert "must not" in output_text
    assert "dorsal auth gitignore" in output_text
    assert "🔒" not in output_text


def test_logout_success(mocker, mock_rich_console, mock_auth_app):
    """Tests a successful 'auth logout'."""
    from dorsal.common.auth import APIKeySource

    mocker.patch(
        "dorsal.common.auth.get_api_key_details", return_value={"source": APIKeySource.PROJECT, "value": "a-real-key"}
    )
    mocker.patch("dorsal.common.auth.remove_api_key", return_value=True)

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert _printed(mock_rich_console) == "You have been successfully logged out.\n"


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
    output_text = _printed(mock_rich_console)
    assert output_text.startswith("Environment variable active\n  You are currently authenticated")
    assert "No configuration files were changed." in output_text


def test_whoami_success(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth whoami' success path."""
    mocker.patch(
        "dorsal.session.get_shared_dorsal_client"
    ).return_value.verify_credentials.return_value = MOCK_USER_INFO

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 0
    output_text = _printed(mock_rich_console)
    assert output_text == (
        "Authenticated user\n"
        "  User ID         usr_12345\n"
        "  Name            Test User\n"
        "  Email           test@example.com\n"
        "  Account status  active\n"
    )


def test_whoami_json(mocker, mock_rich_console, mock_auth_app):
    """Tests 'auth whoami --json'."""
    mocker.patch(
        "dorsal.session.get_shared_dorsal_client"
    ).return_value.verify_credentials.return_value = MOCK_USER_INFO

    result = runner.invoke(app, ["auth", "whoami", "--json"])

    assert result.exit_code == 0

    output_str = mock_rich_console.print.call_args.args[0]
    assert '"user_id": "usr_12345"' in output_str
    assert '"email": "test@example.com"' in output_str


def test_whoami_auth_error(mocker, mock_auth_app):
    """
    Tests that the command bubbles up AuthError (does not swallow it).
    """

    mocker.patch("dorsal.session.get_shared_dorsal_client").side_effect = AuthError("Auth failed.")

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code != 0
    assert isinstance(result.exception, AuthError)


def test_gitignore_no_git(mocker, mock_rich_console, mock_error_console):
    """Tests behavior when 'git' is not installed."""
    mocker.patch("shutil.which", return_value=None)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code != 0
    assert "'git' command not found" in str(mock_error_console.print.call_args.args[0])


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

    mock_file = mock_open(read_data="random_file.txt\n/dorsal.toml\n")
    mocker.patch("builtins.open", mock_file)
    mocker.patch("pathlib.Path.exists", return_value=True)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0
    output_text = _printed(mock_rich_console)
    assert "Entry for 'dorsal.toml' already exists in .gitignore." in output_text
    assert "\n\nFile still tracked?\n  Note: If Git is still tracking" in output_text


def test_gitignore_add_success(mocker, mock_rich_console):
    """Tests successfully adding the config to .gitignore."""
    mocker.patch("shutil.which", return_value=True)
    mocker.patch("subprocess.run").return_value.stdout = "/repo/root"

    config_path = Path("/repo/root/dorsal.toml")
    mocker.patch("dorsal.common.config.get_project_level_config", return_value=({"auth": "secrets"}, config_path))

    mock_file = mock_open(read_data="")
    mocker.patch("builtins.open", mock_file)
    mocker.patch("pathlib.Path.exists", return_value=True)

    mocker.patch("typer.confirm", return_value=True)

    result = runner.invoke(app, ["auth", "gitignore"])

    assert result.exit_code == 0

    mock_file().write.assert_called()
    written_data = mock_file().write.call_args[0][0]
    assert "/dorsal.toml" in written_data

    assert "Successfully added" in str(mock_rich_console.print.call_args.args[0])


def test_final_diagnostic_with_caplog(caplog):
    """Runs diagnostic app and captures log."""
    with caplog.at_level(logging.INFO):
        result = runner.invoke(app_repro, ["hello"])
    assert result.exit_code == 0
    assert "Hello from command" in caplog.text
