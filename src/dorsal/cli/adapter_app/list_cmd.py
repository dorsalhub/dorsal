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
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def list_adapters(
    ctx: typer.Context,
    schema_id: Annotated[
        str,
        typer.Argument(
            help="The schema ID to list supported formats for (e.g., 'open/audio-transcription').",
        ),
    ],
):
    """
    List supported export formats for a given Dorsal schema.
    """
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console
    from dorsal.api.adapters import get_supported_formats
    from dorsal.common.exceptions import DorsalError
    from rich.table import Table

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {}) if ctx.obj else {}

    try:
        formats = get_supported_formats(schema_id)
    except DorsalError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    if not formats:
        error_console.print(f"[{palette.get('warning', 'bold yellow')}]No formats found for schema '{schema_id}'.[/]")
        exit_cli(code=0)

    table = Table(
        title=f"[{palette.get('panel_title', 'bold')}]Supported Formats for '{schema_id}'[/]",
        header_style=palette.get("table_header", "bold blue"),
    )
    table.add_column("Format")
    table.add_column("Description")

    for fmt, desc in formats:
        table.add_row(f"[{palette.get('primary_value', 'cyan')}]{fmt}[/]", desc)

    console.print(table)
