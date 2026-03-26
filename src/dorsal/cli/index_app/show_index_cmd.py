# Copyright 2025-2026 Dorsal Hub LTD
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
import logging
import typer
from typing import Annotated

from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)


def show_index_summary(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the summary as a raw JSON object."),
    ] = False,
):
    """
    Displays statistics about the local file search index.
    """
    from dorsal.api.index import summary as get_index_summary
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        summary = get_index_summary()

        if json_output:
            console.print(json.dumps(summary, indent=2))
            exit_cli()

        summary_table = Table.grid(expand=False)
        summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=22)
        summary_table.add_column(justify="left", style=palette.get("primary_value", "default"))

        summary_table.add_row("Database Path:", str(summary.get("database_path", "N/A")))
        summary_table.add_row("Database Size:", human_filesize(summary.get("database_size_bytes", 0)))
        summary_table.add_row("File Count:", f"{summary.get('total_records', 0):,}")
        summary_table.add_row("Hash Index:", f"{summary.get('hash_only_records', 0):,}")

        console.print(
            Panel(
                summary_table,
                title=f"[{palette.get('panel_title', 'bold white')}]Index Summary[/]",
                border_style=palette.get("panel_border", "default"),
                expand=False,
            )
        )

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to retrieve search index summary.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while getting search index info: {err}",
        )
