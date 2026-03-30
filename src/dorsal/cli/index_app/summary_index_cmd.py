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

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dorsal.cli.themes import UIContext
from dorsal.cli.themes.borders import get_borders

logger = logging.getLogger(__name__)


def show_index_summary(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the summary as a raw JSON object."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show extended metrics and distributions."),
    ] = False,
):
    """
    Displays statistics and health metrics about the local file search index.
    """
    from datetime import datetime
    from rich.columns import Columns
    from dorsal.api.index import summary as get_index_summary
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context["icons"]
    borders = ui_context["borders"]

    try:
        summary = get_index_summary(verbose=verbose)

        if json_output:
            console.print(json.dumps(summary, indent=2))
            exit_cli()

        # Parse Dates safely
        created_dt = (
            datetime.fromtimestamp(summary.get("created_time", 0)).strftime("%Y-%m-%d %H:%M")
            if summary.get("created_time")
            else "N/A"
        )
        modified_dt = (
            datetime.fromtimestamp(summary.get("modified_time", 0)).strftime("%Y-%m-%d %H:%M")
            if summary.get("modified_time")
            else "N/A"
        )

        summary_table = Table.grid(expand=False)
        summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=22)
        summary_table.add_column(justify="left", style=palette.get("primary_value", "default"))

        # --- DEFAULT METRICS ---
        summary_table.add_row("Index Path:", str(summary.get("database_path", "N/A")))
        summary_table.add_row("Index DB Size:", human_filesize(summary.get("database_size_bytes", 0)))
        summary_table.add_row("Total Records:", f"{summary.get('total_records', 0):,}")
        summary_table.add_row("FTS Records:", f"{summary.get('fts_indexed_records', 0):,}")

        # --- VERBOSE METRICS (Seamless Continuation) ---
        if verbose:
            summary_table.add_row("Index Created:", created_dt)
            summary_table.add_row("Last Modified:", modified_dt)
            summary_table.add_row("Tracked File Data:", human_filesize(summary.get("total_tracked_file_bytes", 0)))

            comp_ratio = summary.get("compression_ratio_sample")
            if comp_ratio:
                summary_table.add_row("Est. Compression:", f"{comp_ratio:.2f}x")
            else:
                summary_table.add_row("Compressed Records:", f"{summary.get('compressed_records', 0):,}")

            summary_table.add_row("Hash Only Records:", f"{summary.get('hash_only_records', 0):,}")
            summary_table.add_row("Indexed Attributes:", f"{summary.get('indexed_attributes', 0):,}")

        is_none_style = borders == get_borders("none")
        title_text = f"[{palette.get('panel_title', 'bold white')}]{icons.get('search', '')}Index Summary[/]"

        if is_none_style:
            console.print(Group(Text.from_markup(f"{title_text}\n"), summary_table))
        else:
            console.print(
                Panel(
                    summary_table,
                    title=title_text,
                    border_style=palette.get("panel_border", "default"),
                    box=borders,
                    expand=False,
                )
            )

        # --- VERBOSE DISTRIBUTIONS (Side-by-side Tables) ---
        if verbose:

            def build_dist_table(title: str, data: dict):
                t = Table(
                    title=f"[{palette.get('panel_title', 'bold white')}]{title}[/]",
                    show_header=False,
                    box=borders,
                    expand=True,
                )
                t.add_column("Type", style=palette.get("key", "dim"))
                t.add_column("Count", justify="right", style=palette.get("primary_value", "default"))
                for k, v in data.items():
                    t.add_row(str(k), f"{v:,}")
                return t

            dist_tables = []

            top_exts = summary.get("top_extensions", {})
            if top_exts:
                dist_tables.append(build_dist_table("Top Extensions", top_exts))

            top_media = summary.get("top_media_types", {})
            if top_media:
                dist_tables.append(build_dist_table("Top Media Types", top_media))

            top_schemas = summary.get("top_schemas", {})
            if top_schemas:
                dist_tables.append(build_dist_table("Top Schemas", top_schemas))

            if dist_tables:
                console.print()  # Visual spacing
                console.print(Columns(dist_tables, equal=True, expand=True))

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to retrieve search index summary.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while getting search index info: {err}",
        )
