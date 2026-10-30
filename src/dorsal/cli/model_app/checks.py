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
from __future__ import annotations
import logging
import sys
import shutil
from typing import Any, Dict, TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.prompt import Confirm
from rich.style import Style
from rich.text import Text
import typer

from dorsal.cli.themes import UIContext

if TYPE_CHECKING:
    from dorsal.api.model import ModelTargetResolution


logger = logging.getLogger(__name__)


def check_and_confirm_model_install(
    resolution: "ModelTargetResolution", ui_context: UIContext, force: bool = False, yes: bool = False
) -> None:
    """
    Renders security prompts using the structured intent payload from the API.
    """
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_error_console
    from dorsal.cli.views.layout import key_values, section

    is_unverified = resolution.strategy == "local_path" or (
        resolution.strategy == "registry_id"
        and resolution.metadata
        and not (resolution.metadata.is_verified or resolution.metadata.is_official)
    )

    if force or yes or not is_unverified:
        return

    error_console = get_error_console()
    palette = ui_context["palette"]

    if "pipx" in sys.prefix:
        error_console.print(
            f"[{palette.get('info', 'dim')}]Note: You are running inside a pipx environment.\n"
            "The model will be available to the CLI, but NOT to external Python scripts.[/]"
        )

    display_meta: Dict[str, str | Text] = {"Model": resolution.target, "Source": "Local path"}
    status_badge = f"[{palette.get('warning', 'bold yellow')}]Unverified[/]"
    border_style = palette.get("panel_border_warning", "yellow")
    link_style = palette.get("link", "blue underline")

    if resolution.metadata:
        meta = resolution.metadata
        if meta.is_official or meta.is_verified:
            status_badge = f"[{palette.get('panel_border', 'bold blue')}]Verified[/]"
            border_style = palette.get("panel_border", "blue")

        display_meta = {
            "Model": resolution.target,
            "Status": status_badge,
        }
        if meta.url:
            display_meta["URL"] = Text(meta.url, style=Style.parse(link_style) + Style(link=meta.url))
        display_meta["Description"] = meta.description or "No description provided."

        if meta.source_url:
            if not shutil.which("git"):
                _handle_missing_git(ui_context)
            display_meta["Source code"] = Text(
                meta.source_url, style=Style.parse(link_style) + Style(link=meta.source_url)
            )

        if meta.published_date:
            display_meta["Published"] = str(meta.published_date)

    details = key_values(ui_context)
    for key, value in display_meta.items():
        details.add(key, Text.from_markup(value) if key == "Status" and isinstance(value, str) else value)

    body: RenderableType = details
    if "Unverified" in status_badge:
        body = Group(
            details,
            Text(""),
            Text(
                "You are about to install executable code from an unverified source.\n"
                "Please review the source above before proceeding."
            ),
        )

    error_console.print(
        section(
            "Model info",
            body,
            ui_context,
            title_style=palette.get("panel_title_warning", "bold yellow"),
            border_style=border_style,
            padding=(0, 1),
        )
    )

    if not Confirm.ask("Do you trust this source and want to proceed?", console=error_console):
        error_console.print(f"[{palette.get('error', 'bold red')}]Cancelled.[/]")
        exit_cli(code=0)


def _handle_missing_git(ui_context: UIContext):
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_error_console
    from dorsal.cli.views.layout import message as format_message

    error_console = get_error_console()
    palette = ui_context["palette"]

    message = Text.assemble(
        ("This model requires Git to install.\n\n", "default"),
        ("Dorsal could not find the ", "default"),
        ("git", f"bold {palette.get('primary_value', 'cyan')}"),
        (" command in your system PATH.\n\n", "default"),
        ("To proceed, please install Git from:\n", "default"),
        ("https://git-scm.com/downloads", palette.get("link", "blue underline")),
    )

    error_console.print(format_message("Missing system dependency", message, ui_context, level="error", padding=(0, 1)))
    exit_cli(code=EXIT_CODE_ERROR)


def _handle_registry_error(target: str, e: Exception, ui_context: UIContext):
    from dorsal.common.exceptions import NotFoundError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_error_console

    error_console = get_error_console()
    palette = ui_context["palette"]

    if isinstance(e, NotFoundError) or "404" in str(e):
        error_console.print(f"[{palette.get('error', 'bold red')}]Error: Model '{target}' not found in registry.[/]")
    else:
        error_console.print(
            f"[{palette.get('error', 'bold red')}]Error: Failed to connect to registry for '{target}'.[/]\n{e}"
        )
    exit_cli(code=EXIT_CODE_ERROR)
