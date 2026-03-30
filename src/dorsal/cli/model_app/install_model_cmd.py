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

from dorsal.cli.themes import UIContext
from dorsal.cli.themes.borders import get_borders
from rich.console import Group
from rich.text import Text

logger = logging.getLogger(__name__)


def install_model(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="The pip target (Registry ID, git URL, or local path).")],
    global_install: Annotated[
        bool, typer.Option("--global", "-g", help="Install to global user config instead of project config.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Force reinstall the pip package.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the safety confirmation prompt.")] = False,
):
    """
    Install a model from DorsalHub or a local folder.

    This command runs `pip install` and then automatically registers the model
    into your dorsal.toml configuration.
    """
    from rich.panel import Panel
    from dorsal.common.exceptions import DorsalError, AuthError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.installer import install_model_target
    from dorsal.cli.model_app.checks import check_and_confirm_model_install

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    scope: Literal["global", "project"] = "global" if global_install else "project"

    # Pass the full ui_context to the checker so it can render borderless!
    check_and_confirm_model_install(target, ui_context, force=force, yes=yes)

    status_color = palette.get("primary_value", "bold cyan")
    with console.status(f"Installing model from [{status_color}]{target}[/]..."):
        try:
            package_name = install_model_target(target, scope=scope, force_reinstall=force)

        except AuthError:
            raise

        except DorsalError as e:
            console.print(f"[{palette.get('error', 'bold red')}]Install Failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)
        except Exception as e:
            logger.exception("Unexpected error during installation")
            console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    success_color = palette.get("primary_value", "cyan")
    success_message = f"Successfully installed [{success_color}]{package_name}[/]"
    if scope == "global":
        scope_color = palette.get("warning", "yellow")
        success_message += f"\nActive Scope: [{scope_color}]{scope}[/]"

    is_none_style = borders == get_borders("none")
    title_text = f"[{palette.get('panel_title_success', 'bold green')}]✅ Installation Complete[/]"

    if is_none_style:
        console.print(Group(Text.from_markup(f"\n{title_text}"), Text.from_markup(success_message)))
    else:
        console.print(
            Panel(
                success_message,
                title=title_text,
                border_style=palette.get("panel_border_success", "green"),
                expand=False,
                box=borders,
            )
        )
