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
import pathlib
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def init_model(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The human-readable name of your model (e.g. 'Receipt Scanner').")],
    target_dir: Annotated[
        pathlib.Path | None,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=True,
            help="The project directory. If `None`, current directory is used.",
        ),
    ] = None,
):
    """
    Scaffold a new Annotation Model project in the current directory.
    """
    from rich.panel import Panel
    from dorsal.common.exceptions import DorsalError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.initialize import create_new_annotation_model_project

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        result = create_new_annotation_model_project(name=name, target_dir=target_dir)

        console.print(
            Panel(
                f"Created new model project: [{palette.get('primary_value', 'cyan')}]{result.clean_name}[/]\n\n"
                f"To install it for testing:\n"
                f"  $ cd {result.clean_name}\n"
                f"  $ dorsal model install .",
                title="Model Initialized",
                border_style=palette.get("panel_border_success", "green"),
                title_align="left",
            )
        )

    except DorsalError as e:
        console.print(f"[{palette.get('error', 'bold red')}]Failed to create project:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        logger.exception("Unexpected error in model init")
        console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
