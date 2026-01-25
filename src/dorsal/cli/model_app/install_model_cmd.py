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


def install_model(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="The pip target (PyPI name, git URL, or local path).")],
    global_install: Annotated[
        bool, typer.Option("--global", "-g", help="Install to global user config instead of project config.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Force reinstall the pip package.")] = False,
):
    """
    Install a model from PyPI, Git, or a local folder.

    This command runs `pip install` and then automatically registers the model
    into your dorsal.toml configuration.
    """
    from rich.panel import Panel
    from dorsal.common.exceptions import DorsalError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.installer import install_model_target

    console = get_rich_console()
    palette = ctx.obj["palette"]
    scope: Literal["global", "project"] = "global" if global_install else "project"

    with console.status(f"Installing model from [{palette.get('primary_value', 'bold')}]{target}[/]..."):
        try:
            package_name = install_model_target(target, scope=scope, force_reinstall=force)
        except DorsalError as e:
            console.print(f"[{palette.get('error', 'bold red')}]Install Failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)
        except Exception as e:
            logger.exception("Unexpected error during installation")
            console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    console.print(
        Panel(
            f"Successfully installed [{palette.get('primary_value', 'cyan')}]{package_name}[/]\n"
            f"Active Scope: [{palette.get('warning', 'yellow')}]{scope}[/]",
            title="✅ Installation Complete",
            border_style=palette.get("panel_border_success", "green"),
        )
    )
