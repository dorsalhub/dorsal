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

logger = logging.getLogger(__name__)


def install_model(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="The pip target (Registry ID, git URL, or local path).")],
    global_install: Annotated[
        bool, typer.Option("--global", "-g", help="Install to global user config instead of project config.")
    ] = False,
    force: Annotated[bool, typer.Option("--force-reinstall", "-f", help="Force reinstall the pip package.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the safety confirmation prompt.")] = False,
):
    """
    Install a model from DorsalHub or a local folder.

    This command runs `pip install` and then automatically registers the model
    into your dorsal.toml configuration.
    """
    from rich.text import Text
    from dorsal.common.exceptions import DorsalError, AuthError
    from dorsal.common.cli import (
        exit_cli,
        EXIT_CODE_ERROR,
        get_rich_console,
        get_error_console,
    )

    from dorsal.api.model import prepare_model_target, install_model as api_install_model
    from dorsal.cli.model_app.checks import check_and_confirm_model_install
    from dorsal.cli.views.layout import section

    console = get_rich_console()
    error_console = get_error_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    scope: Literal["global", "project"] = "global" if global_install else "project"

    resolution = prepare_model_target(target)
    if resolution.strategy == "error":
        error_console.print(f"[{palette.get('error', 'bold red')}]Install failed:[/] {resolution.error_message}")
        exit_cli(code=EXIT_CODE_ERROR)

    check_and_confirm_model_install(resolution, ui_context, force=force, yes=yes)

    status_color = palette.get("primary_value", "bold cyan")
    with error_console.status(f"Installing model from [{status_color}]{target}[/]..."):
        try:
            package_name = api_install_model(target, scope=scope, force_reinstall=force)

        except AuthError:
            raise

        except DorsalError as e:
            error_console.print(f"[{palette.get('error', 'bold red')}]Install failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)
        except Exception as e:
            logger.exception("Unexpected error during installation")
            error_console.print(f"[{palette.get('error', 'bold red')}]Unexpected error:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    success_color = palette.get("primary_value", "cyan")
    success_message = f"Successfully installed [{success_color}]{package_name}[/]"
    if scope == "global":
        scope_color = palette.get("warning", "yellow")
        success_message += f"\nActive scope: [{scope_color}]{scope}[/]"

    console.print(
        section(
            f"{ui_context['icons'].get('success', '')}Installation complete",
            Text.from_markup(success_message),
            ui_context,
            title_style=palette.get("panel_title_success", "bold green"),
            border_style=palette.get("panel_border_success", "green"),
        )
    )
