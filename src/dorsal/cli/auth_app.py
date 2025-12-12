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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import pathlib
import subprocess
import shutil

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import json
import os
from typing import Annotated, Optional

logger = logging.getLogger(__name__)

app = typer.Typer(name="auth", help="Manage authentication and user sessions.", no_args_is_help=True)


def _display_user_info(user_info: dict, title: str, palette: dict, console: Console):
    name = user_info.get("name", "N/A")
    email = user_info.get("email", "N/A")
    account_status = user_info.get("account_status", "N/A")
    user_id = user_info.get("user_id", "N/A")
    info_text = Text.assemble(
        ("User ID:        ", palette["key"]),
        (str(user_id), palette["primary_value"]),
        "\n",
        ("Name:           ", palette["key"]),
        (name, palette["primary_value"]),
        "\n",
        ("Email:          ", palette["key"]),
        (email, palette["primary_value"]),
        "\n",
        ("Account Status: ", palette["key"]),
        (account_status, palette["primary_value"]),
    )
    panel = Panel(
        info_text,
        title=f"[{palette['panel_title_success']}]{title}[/]",
        border_style=palette["panel_border_success"],
        expand=False,
        padding=(1, 2),
    )
    console.print(panel)


@app.command()
def login(
    ctx: typer.Context,
    apikey: Annotated[
        Optional[str],
        typer.Option(
            "--apikey",
            help="Your DorsalHub API key. If not provided, you will be prompted.",
        ),
    ] = None,
    is_project: bool = typer.Option(
        False, "--project", help="Save the API key to the project-level configuration file (e.g., dorsal.toml)."
    ),
):
    """Log in to DorsalHub by providing an API key."""
    from dorsal.session import clear_shared_dorsal_client
    from dorsal.common.auth import write_auth_config
    from dorsal.common.config import find_project_config_path, get_global_config_path, load_config
    from dorsal.common.exceptions import AuthError, DorsalOfflineError, NetworkError
    from dorsal.common.cli import EXIT_CODE_ERROR, exit_cli, get_rich_console
    from dorsal.common import constants

    console = get_rich_console()

    if not apikey:
        console.print("🔑 Please enter your DorsalHub API key.")
        console.print("[dim]You can generate a key from your account settings page.[/dim]")
        apikey = typer.prompt("API Key", hide_input=True)

    if not apikey:
        return exit_cli(code=EXIT_CODE_ERROR, message="API key cannot be empty.")

    try:
        from dorsal.client import DorsalClient

        console.print(":key: Verifying key with DorsalHub...")
        temp_client = DorsalClient(api_key=apikey)
        user_info = temp_client.verify_credentials()

        email = user_info.get("email")
        if is_project:
            scope = "project"
            logger.debug("Writing to the project-level config toml.")
        else:
            scope = "global"
            logger.debug("Writing to the global config at %s", get_global_config_path())

        write_auth_config(api_key=apikey, email=email, scope=scope)

        clear_shared_dorsal_client()

        console.print()
        palette = ctx.obj["palette"]
        _display_user_info(user_info, title="✅ Login Successful", palette=palette, console=console)

        if is_project:
            project_config_path = find_project_config_path()
            if project_config_path:
                config_file_path = project_config_path
            else:
                config_file_path = pathlib.Path.cwd() / "dorsal.toml"
        else:
            config_file_path = get_global_config_path()

        console.print(
            f"\nYour API key has been saved to the {scope} config: [{palette['primary_value']}]{config_file_path}[/]"
        )

        if is_project:
            config_filename = config_file_path.name
            console.print()
            security_warning_text = Text.assemble(
                ("The file ", "default"),
                (f"'{config_filename}'", f"bold {palette['primary_value']}"),
                (" now contains your API key.\n\n", "default"),
                ("This file ", palette["warning"]),
                ("must not", palette["error"]),
                (" be committed to Git.\n", palette["warning"]),
                ("To automatically add this file to your .gitignore, please run:", "default"),
                ("\n  dorsal auth gitignore", f"bold {palette['primary_value']}"),
            )
            console.print(
                Panel(
                    security_warning_text,
                    title=f"[{palette['panel_title_warning']}]🔒 Action Required[/]",
                    border_style=palette["panel_border_warning"],
                    expand=False,
                    padding=(1, 2),
                )
            )

        exit_cli()
    except DorsalOfflineError:
        raise
    except AuthError:
        exit_cli(code=EXIT_CODE_ERROR, message="The provided API key is invalid or expired.")
    except NetworkError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Could not connect to DorsalHub. {err}")
    except OSError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Could not save API Key. {err}")


@app.command()
def logout(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Required to confirm the deletion of a global API key.",
        ),
    ] = False,
):
    """
    Log out by removing the API key from the local configuration.
    """
    from dorsal.session import clear_shared_dorsal_client
    from dorsal.common.auth import get_api_key_details, remove_api_key, APIKeySource
    from dorsal.common.cli import EXIT_CODE_ERROR, exit_cli, get_rich_console

    console = get_rich_console()
    palette = ctx.obj["palette"]

    try:
        details = get_api_key_details()
        active_source = details["source"]

        if active_source == APIKeySource.ENV:
            warning_message = Text.assemble(
                ("You are currently authenticated via an environment variable.\n\n", palette["warning"]),
                ("The ", "default"),
                ("DORSAL_API_KEY", f"bold {palette['primary_value']}"),
                (" is set. This command only removes keys from configuration files.\n\n", "default"),
                ("To complete the logout process for this session, please unset this environment variable.", "default"),
            )
            console.print(
                Panel(
                    warning_message,
                    title=f"[{palette['panel_title_warning']}]Environment Variable Active[/]",
                    border_style=palette["panel_border_warning"],
                )
            )
            console.print("No configuration files were changed.")
            return exit_cli()

        if active_source == APIKeySource.NONE:
            console.print("You are not currently logged in.")
            return exit_cli()

        if active_source == APIKeySource.GLOBAL and not force:
            console.print(f"[{palette['warning']}]Warning:[/] You are using a global API key.")
            console.print("Logging out will remove it and affect all your projects.")
            console.print("\nTo confirm, run the command again with the --force flag:")
            console.print(f"  [{palette['primary_value']}]dorsal auth logout --force[/]")
            return exit_cli()

        key_was_removed = remove_api_key(scope=active_source)
        clear_shared_dorsal_client()

        if key_was_removed:
            console.print(f"[{palette['success']}]✅ You have been successfully logged out.[/]")
        else:
            console.print("You are not currently logged in (or the key could not be removed).")
        return exit_cli()

    except OSError as err:
        console.print(f"[{palette['error']}]Error:[/] Could not modify config file. {err}")
        return exit_cli(code=EXIT_CODE_ERROR, message=f"Could not modify config file. {err}")


@app.command()
def gitignore(ctx: typer.Context):
    """
    Check if the project config file is in .gitignore, and add it if not.
    """
    from dorsal.common.cli import EXIT_CODE_ERROR, exit_cli, get_rich_console
    from dorsal.common.config import get_project_level_config
    from dorsal.common import constants

    console = get_rich_console()
    palette = ctx.obj["palette"]
    logger.debug("--- Running 'dorsal auth gitignore' ---")

    if not shutil.which("git"):
        logger.warning("'git' command not found.")
        console.print(f"[{palette['warning']}]'git' command not found. Cannot check or update .gitignore.[/]")
        return exit_cli(code=EXIT_CODE_ERROR)

    current_cwd = pathlib.Path.cwd()
    logger.debug(f"Checking for git repo in CWD: {current_cwd}")
    try:
        root_result_args = ["git", "rev-parse", "--show-toplevel"]
        root_result = subprocess.run(
            root_result_args, capture_output=True, text=True, check=True, cwd=current_cwd, encoding="utf-8"
        )
        repo_root = pathlib.Path(root_result.stdout.strip())
        logger.debug(f"Git root found at: {repo_root}")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.debug(f"Not a git repo (or 'git rev-parse' failed): {e}")
        console.print(f"[{palette['info']}]This directory does not appear to be a Git repository. Nothing to do.[/]")
        return exit_cli()

    project_config_data, project_config_path = get_project_level_config()
    logger.debug(f"'get_project_level_config' returned path: {project_config_path}")

    if not project_config_path:
        logger.debug("No project-level config file found.")
        console.print(f"[{palette['info']}]No project-level config file found. Nothing to do.[/]")
        return exit_cli()

    if not project_config_data:
        logger.debug(f"Project config file found ('{project_config_path.name}'), but it is empty or invalid.")
        console.print(
            f"[{palette['info']}]Project config file '{project_config_path.name}' is empty or invalid. Nothing to do.[/]"
        )
        return exit_cli()

    config_filename = project_config_path.name
    logger.debug(f"Config filename basename: {config_filename}")

    auth_section_present = project_config_data.get(constants.CONFIG_SECTION_AUTH) is not None

    if not auth_section_present:
        logger.debug("Config file found, but it contains no 'auth' section.")
        console.print(
            f"[{palette['success']}]✅ Your '{config_filename}' file contains no 'auth' section.[/]", highlight=False
        )
        console.print("It is safe to commit and share with your team. No changes made to .gitignore.")
        exit_cli()

    logger.debug("Config file contains an 'auth' section. Proceeding with .gitignore check.")

    gitignore_path = repo_root / ".gitignore"
    logger.debug(f"Target .gitignore path: {gitignore_path}")

    found_in_gitignore = False
    if gitignore_path.exists():
        logger.debug(f"'{gitignore_path}' exists. Reading contents.")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            if stripped_line == config_filename or stripped_line == f"/{config_filename}":
                logger.debug(f"Found matching entry on line {i + 1}: '{stripped_line}'")
                found_in_gitignore = True
                break
    else:
        logger.debug(f"'{gitignore_path}' does not exist.")

    if found_in_gitignore:
        logger.debug("Entry already exists. No action taken.")
        console.print(f"[{palette['success']}]✅ Entry for '{config_filename}' already exists in .gitignore.[/]")

        note_text = Text.assemble(
            ("Note: If Git is still tracking this file, run the following command to stop tracking it:", "default"),
            (f"\n  git rm --cached {config_filename}", palette["primary_value"]),
        )
        console.print(
            Panel(
                note_text,
                title=f"[{palette['panel_title_info']}]File Still Tracked?[/]",
                border_style=palette["panel_border_info"],
                expand=False,
                padding=(1, 2),
            )
        )
        exit_cli()

    logger.debug("File is not in .gitignore. Asking for user consent.")
    console.print(f"The config file '[{palette['primary_value']}]{config_filename}[/]' is not in your .gitignore.")

    try:
        if not typer.confirm("Do you want to add it to the project's root .gitignore file?"):
            logger.debug("User consent denied (N).")
            console.print("Operation cancelled. Please add the file to .gitignore manually.")
            exit_cli()

        logger.debug("User consent granted (y).")
    except typer.Abort:
        logger.debug("User aborted consent (Ctrl+C).")
        console.print("\nOperation cancelled.")
        exit_cli()

    logger.debug("Proceeding to write to .gitignore.")
    try:
        entry_to_add = f"\n# Dorsal config file (contains secrets)\n/{config_filename}\n"
        logger.debug(f"Entry to add: {entry_to_add.strip()}")

        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(entry_to_add)

        logger.debug("Successfully wrote to .gitignore.")
        console.print(f"[{palette['success']}]✅ Successfully added '/{config_filename}' to {gitignore_path}.[/]")
        exit_cli()

    except (OSError, subprocess.CalledProcessError) as e:
        logger.error(f"Failed during .gitignore write operation: {e}", exc_info=True)
        console.print(f"[{palette['error']}]Error:[/] Could not write to .gitignore: {e}")
        console.print("Please add the file to .gitignore manually.")
        exit_cli(code=EXIT_CODE_ERROR)


@app.command()
def whoami(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the user info as a raw JSON object to stdout for scripting.",
        ),
    ] = False,
):
    """
    Check the currently authenticated user and session status.
    """
    from dorsal.session import get_shared_dorsal_client
    from dorsal.common.cli import EXIT_CODE_ERROR, exit_cli, get_rich_console
    from dorsal.common.exceptions import AuthError, NetworkError

    console = get_rich_console()

    try:
        client = get_shared_dorsal_client()

        if not json_output:
            console.print("Verifying session with DorsalHub...")

        user_info = client.verify_credentials()

        if json_output:
            console.print(json.dumps(user_info, indent=2, default=str, ensure_ascii=False))
        else:
            palette = ctx.obj["palette"]
            console.print()
            _display_user_info(
                user_info,
                title="👤 Authenticated User",
                palette=palette,
                console=console,
            )
        exit_cli()

    except NetworkError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Could not connect to DorsalHub. {err}")
