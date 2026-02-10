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
from typing import Annotated, Literal

import typer

logger = logging.getLogger(__name__)


def uninstall_model(
    ctx: typer.Context,
    target: Annotated[
        str, typer.Argument(help="The Registry ID (e.g. dorsalhub/whisper) or package name to uninstall.")
    ],
    global_install: Annotated[
        bool, typer.Option("--global", "-g", help="Uninstall from global user config instead of project config.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
):
    """
    Uninstall a model.

    This removes the model from your dorsal.toml configuration and uninstalls
    the underlying pip package.
    """
    from rich.panel import Panel
    from rich.prompt import Confirm
    from dorsal.common.exceptions import DorsalError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.uninstaller import uninstall_model_target

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]
    scope: Literal["global", "project"] = "global" if global_install else "project"

    # --- 1. Confirmation ---
    if not yes:
        message = (
            f"Are you sure you want to uninstall [bold]{target}[/]?\n"
            f"This will remove it from your model pipeline and uninstall the python package."
        )

        if not Confirm.ask(message):
            console.print(f"[{palette.get('error', 'bold red')}]Cancelled.[/]")
            exit_cli(code=0)

    # --- 2. Execution ---
    status_color = palette.get("primary_value", "bold cyan")

    with console.status(f"Uninstalling [{status_color}]{target}[/]..."):
        try:
            package_name = uninstall_model_target(target, scope=scope)

        except DorsalError as e:
            console.print(f"[{palette.get('error', 'bold red')}]Uninstall Failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)
        except Exception as e:
            logger.exception("Unexpected error during uninstall")
            console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    # --- 3. Success Output ---
    success_color = palette.get("primary_value", "cyan")

    console.print(
        Panel(
            f"Successfully uninstalled [{success_color}]{package_name}[/]",
            title=f"[{palette.get('panel_title_success', 'bold green')}]🗑️ Uninstall Complete[/]",
            border_style=palette.get("panel_border_success", "green"),
            expand=False,
        )
    )
