# Copyright 2026 Dorsal Hub LTD
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

import logging
import sys
import shutil
from typing import Any, Dict

from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text
import typer


logger = logging.getLogger(__name__)


def check_and_confirm_model_install(
    target: str, palette: Dict[str, str], force: bool = False, yes: bool = False
) -> None:
    """
    Checks if a model target is safe to install and prompts the user for confirmation.

    Args:
        target: The model identifier (registry ID, git URL, etc).
        palette: The CLI color palette.
        force: If True, skips checks (assumes user knows what they are doing).
        yes: If True, skips interactive confirmation.
    """
    from dorsal.common.constants import WEB_URL
    from dorsal.common.exceptions import AuthError
    from dorsal.common.cli import exit_cli, get_error_console
    from dorsal.session import get_shared_dorsal_client
    from dorsal.registry.validators import is_registry_id

    if force or yes:
        return

    error_console = get_error_console()

    if "pipx" in sys.prefix:
        error_console.print(
            f"[{palette.get('info', 'dim')}]Note: You are running inside a pipx environment.\n"
            "The model will be available to the CLI, but NOT to external Python scripts.[/]"
        )

    display_meta = {"Model": target, "Source": "Local Path"}
    status_badge = f"[{palette.get('warning', 'bold yellow')}]Unverified[/]"
    border_style = palette.get("panel_border_warning", "yellow")
    link_style = palette.get("link", "blue underline")

    if is_registry_id(target):
        try:
            with error_console.status(f"[{palette.get('info', 'dim')}]Fetching model details...[/]"):
                client = get_shared_dorsal_client()
                reg_data = client.get_registry_model(target)

                if reg_data.is_official or reg_data.is_verified:
                    status_badge = f"[{palette.get('panel_border', 'bold blue')}]Verified[/]"
                    border_style = palette.get("panel_border", "blue")

                dorsalhub_url = f"{WEB_URL}/models/{reg_data.namespace}/{reg_data.name}"
                display_meta = {
                    "Model": f"{reg_data.namespace}/{reg_data.name}",
                    "Status": status_badge,
                    "URL": f"[{link_style} link={dorsalhub_url}]{dorsalhub_url}[/]",
                    "Description": reg_data.description or "No description provided.",
                }

                if reg_data.install_url:
                    if reg_data.install_url.startswith("git+") and not shutil.which("git"):
                        _handle_missing_git(palette)

                    raw_url = reg_data.install_url.replace("git+", "").split("@")[0]
                    display_meta["Source Code"] = f"[{link_style} link={raw_url}]{raw_url}[/]"

                if reg_data.created_at:
                    display_meta["Published"] = reg_data.created_at.date().isoformat()

        except AuthError:
            raise
        except typer.Exit:
            raise
        except Exception as e:
            logger.debug(f"Metadata fetch failed: {e}")
            if "/" in target:
                _handle_registry_error(target, e, palette)
            display_meta["Warning"] = "Could not fetch remote metadata."

    msg_lines = []
    for k, v in display_meta.items():
        msg_lines.append(f"[{palette.get('key', 'dim')}]{k}:[/] {v}")

    if "Unverified" in status_badge:
        msg_lines.append("\nYou are about to install executable code from an unverified source.")
        msg_lines.append("Please review the source above before proceeding.")

    error_console.print(
        Panel(
            "\n".join(msg_lines),
            title=f"[{palette.get('panel_title_warning', 'bold yellow')}]Model Info[/]",
            border_style=border_style,
            expand=False,
        )
    )

    if not Confirm.ask("Do you trust this source and want to proceed?", console=error_console):
        error_console.print(f"[{palette.get('error', 'bold red')}]Cancelled.[/]")
        exit_cli(code=0)


def _handle_missing_git(palette: Dict[str, str]):
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_error_console

    error_console = get_error_console()
    message = Text.assemble(
        ("This model requires Git to install.\n\n", "default"),
        ("Dorsal could not find the ", "default"),
        ("git", f"bold {palette.get('primary_value', 'cyan')}"),
        (" command in your system PATH.\n\n", "default"),
        ("To proceed, please install Git from:\n", "default"),
        ("https://git-scm.com/downloads", palette.get("link", "blue underline")),
    )
    error_console.print(
        Panel(
            message,
            expand=False,
            title=f"[{palette.get('panel_title_error', 'bold red')}]Missing System Dependency[/]",
            border_style=palette.get("panel_border_error", "red"),
        )
    )
    exit_cli(code=EXIT_CODE_ERROR)


def _handle_registry_error(target: str, e: Exception, palette: Dict[str, str]):
    from dorsal.common.exceptions import NotFoundError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_error_console

    error_console = get_error_console()
    if isinstance(e, NotFoundError) or "404" in str(e):
        error_console.print(f"[{palette.get('error', 'bold red')}]Error: Model '{target}' not found in registry.[/]")
    else:
        error_console.print(
            f"[{palette.get('error', 'bold red')}]Error: Failed to connect to registry for '{target}'.[/]\n{e}"
        )
    exit_cli(code=EXIT_CODE_ERROR)
