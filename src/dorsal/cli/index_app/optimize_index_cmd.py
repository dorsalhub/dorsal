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

import logging
import typer
from typing import Annotated
import json

from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)


def optimize_search_index(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the optimization summary as a raw JSON object."),
    ] = False,
    force_recompression: Annotated[
        bool, typer.Option("--force-recompression", help="Recompress all records using current settings.")
    ] = False,
):
    """
    Runs maintenance on the SQLite search index.

    - Pruning stale records (for deleted or modified files).
    - Syncing record compression with the current config.
    - Reclaiming disk space (VACUUM).
    """
    from dorsal.api.index import optimize
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        with console.status("Optimizing search index... (this may take a moment)"):
            results = optimize(force_recompression=force_recompression)

        if json_output:
            console.print(json.dumps(results))
            exit_cli()

        summary_table = Table.grid(expand=False)
        summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=35)
        summary_table.add_column(justify="left", style=palette.get("primary_value", "default"))

        summary_table.add_row("Records Removed:", f"{results.get('stale_records_removed', 0):,}")
        summary_table.add_row(
            "Records Reprocessed:",
            f"{results.get('records_rewritten_for_compression', 0):,}",
        )
        summary_table.add_row()
        summary_table.add_row(
            "Size Before Optimization:",
            human_filesize(results.get("size_before_bytes", 0)),
        )
        summary_table.add_row(
            "Size After Optimization:",
            human_filesize(results.get("size_after_bytes", 0)),
        )

        reclaimed_bytes = results.get("size_reclaimed_bytes", 0)
        if reclaimed_bytes < 0:
            summary_table.add_row(
                "Index Size Increased:",
                human_filesize(abs(reclaimed_bytes)),
            )
        else:
            summary_table.add_row(
                "Index Size Decreased:",
                human_filesize(reclaimed_bytes),
            )

        console.print(
            Panel(
                summary_table,
                title=f"[{palette.get('panel_title_success', 'bold green')}]✅ Index Optimization Complete[/]",
                border_style=palette.get("panel_border_success", "green"),
                expand=False,
            )
        )

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to optimize search index.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while optimizing the search index: {err}",
        )
