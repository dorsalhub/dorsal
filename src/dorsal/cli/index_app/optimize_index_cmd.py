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
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

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
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        get_error_console,
        print_json_output,
    )
    from dorsal.cli.views.layout import key_values, section
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})

    try:
        status_console = get_error_console() if json_output else console
        with status_console.status("Optimizing search index... (this may take a moment)"):
            results = optimize(force_recompression=force_recompression)

        if json_output:
            print_json_output(results, console)
            exit_cli()

        summary_table = key_values(ui_context)
        summary_table.add("Records removed", f"{results.get('stale_records_removed', 0):,}")
        summary_table.add("Records reprocessed", f"{results.get('records_rewritten_for_compression', 0):,}")
        summary_table.add("Size before optimization", human_filesize(results.get("size_before_bytes", 0)))
        summary_table.add("Size after optimization", human_filesize(results.get("size_after_bytes", 0)))

        reclaimed_bytes = results.get("size_reclaimed_bytes", 0)
        if reclaimed_bytes < 0:
            summary_table.add("Index size increased", human_filesize(abs(reclaimed_bytes)))
        else:
            summary_table.add("Index size decreased", human_filesize(reclaimed_bytes))

        console.print(
            section(
                f"{icons.get('success', '')}Index optimization complete",
                summary_table,
                ui_context,
                title_style=palette.get("panel_title_success", "bold green"),
                border_style=palette.get("panel_border_success", "green"),
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
