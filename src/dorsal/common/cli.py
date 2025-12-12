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

import json
import sys
from typing import NoReturn

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from dorsal.common.exceptions import AuthError
from dorsal.file.cache.config import get_cache_enabled
import typer


EXIT_CODE_SUCCESS = 0
EXIT_CODE_ERROR = 1

_console_instance: Console | None = None


def get_rich_console() -> Console:
    """Returns a single, shared Console instance, creating it if necessary."""
    global _console_instance
    if _console_instance is None:
        _console_instance = Console()
    return _console_instance


def exit_cli(code: int = EXIT_CODE_SUCCESS, message: str | None = None) -> NoReturn:
    """Comprehensible and testable wrapper for exiting a CLI command.

    Args:
        code: The exit code to use. Defaults to 0 (success).
        message: An optional message to print to stderr before exiting.
                 If the code is > 0, the message will be prefixed with "Error: ".
    """
    if message:
        if code > 0:
            typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
        else:
            typer.secho(message, err=True)

    raise typer.Exit(code=code)


def determine_use_cache_value(use_cache: bool, skip_cache: bool) -> bool:
    use_cache_choice = None
    if use_cache:
        use_cache_choice = True
    elif skip_cache:
        use_cache_choice = False

    use_cache_value = get_cache_enabled(use_cache=use_cache_choice)

    return use_cache_value


def handle_error(palette: dict, message: str, json_output: bool):
    console = get_rich_console()

    if json_output:
        console.print(json.dumps({"error": True, "detail": message}, indent=2, ensure_ascii=False))
    else:
        panel = Panel(
            Text(message, justify="left"),
            title=f"[{palette.get('panel_title_error', 'bold red')}]Error[/]",
            border_style=palette.get("panel_border_error", "red"),
            expand=False,
            padding=(1, 2),
        )
        console.print(panel)
    exit_cli(code=EXIT_CODE_ERROR)


def handle_auth_error(err: AuthError, console: Console, palette: dict[str, str]) -> None:
    """Handler for AuthError."""
    if "--json" in sys.argv:
        error_payload = {
            "success": False,
            "error": "Authentication Required",
            "detail": "You are not currently logged in.",
            "original_message": str(err),
            "fix": "Run 'dorsal auth login' or set the DORSAL_API_KEY environment variable.",
        }
        print(json.dumps(error_payload, indent=2))
        return

    message = Text.assemble(
        ("You are not currently logged in.\n\n", palette["warning"]),
        ("To authenticate, you can either:\n", "default"),
        ("  1. Run ", "default"),
        ("dorsal auth login\n", f"bold {palette['primary_value']}"),
        ("  2. Set the ", "default"),
        ("DORSAL_API_KEY", f"bold {palette['primary_value']}"),
        (" environment variable.", "default"),
    )

    console.print(
        Panel(
            message,
            expand=False,
            title=f"[{palette['panel_title_info']}]Authentication Required[/]",
            border_style=palette["panel_border_info"],
        )
    )


def handle_offline_error(e: Exception, console: Console, palette: dict):
    """
    Centralized handler for DorsalOfflineError.
    """
    if "--json" in sys.argv:
        error_payload = {
            "success": False,
            "error": "Offline Mode Active",
            "detail": "Communication with DorsalHub is blocked because offline mode is enabled.",
            "original_message": str(e),
            "fix": "Unset the 'DORSAL_OFFLINE' environment variable.",
        }
        print(json.dumps(error_payload, indent=2))
        return

    message = Text.assemble(
        ("Offline Mode is currently active.\n\n", palette["warning"]),
        ("DorsalHub API Access is blocked.\n\n", "default"),
        ("To restore access, unset the", "default"),
        (" DORSAL_OFFLINE", f"bold {palette['primary_value']}"),
        (" environment variable.", "default"),
    )

    console.print(
        Panel(
            message,
            expand=False,
            title=f"[{palette['panel_title_warning']}]Dorsal API Access Blocked[/]",
            border_style=palette["panel_border_info"],
        )
    )
