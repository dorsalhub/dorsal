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
from typing import Annotated, TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

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
    limit: Annotated[int, typer.Option("--limit", "-l", help="Length limit for the tables in verbose view.")] = 10,
):
    """
    Displays statistics and health metrics about the local file search index.
    """
    from datetime import datetime
    from rich.columns import Columns
    from rich.console import Group
    from rich.text import Text
    from dorsal.api.index import summary as get_index_summary
    from dorsal.cli.views.layout import Trimmed, heading, is_borderless, key_values, section, table
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        print_json_output,
    )
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    ui_context: "UIContext" = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context["icons"]

    try:
        summary = get_index_summary(verbose=verbose, limit=limit)

        if json_output:
            print_json_output(summary, console)
            exit_cli()

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

        summary_table = key_values(ui_context)
        summary_table.add("Index path", str(summary.get("database_path", "N/A")))
        summary_table.add("Index size", f"{summary.get('total_records', 0):,} records")
        summary_table.add("Record cache size", human_filesize(summary.get("record_cache_size_bytes", 0)))
        summary_table.add("Search index size", human_filesize(summary.get("search_index_size_bytes", 0)))

        if verbose:
            summary_table.add("Total DB size", human_filesize(summary.get("database_size_bytes", 0)))
            summary_table.add("Full-text index", f"{summary.get('fts_indexed_records', 0):,} records")
            summary_table.add("Index created", created_dt)
            summary_table.add("Last modified", modified_dt)
            summary_table.add("Tracked file data", human_filesize(summary.get("total_tracked_file_bytes", 0)))

            summary_table.add("Avg index record size", human_filesize(summary.get("avg_record_size_bytes", 0)))
            summary_table.add("Max index record size", human_filesize(summary.get("max_record_size_bytes", 0)))

            summary_table.add("Unique files (hash)", f"{summary.get('unique_files_by_hash', 0):,}")
            summary_table.add("Duplicate files", f"{summary.get('duplicate_files_detected', 0):,}")

            oldest_ts = summary.get("oldest_record_timestamp")
            if oldest_ts:
                summary_table.add("Oldest tracked file", datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d"))
            newest_ts = summary.get("newest_record_timestamp")
            if newest_ts:
                summary_table.add("Newest tracked file", datetime.fromtimestamp(newest_ts).strftime("%Y-%m-%d"))

            comp_mode = summary.get("compression_mode", "None")
            comp_level = summary.get("compression_level")
            comp_str = f"{comp_mode} (Level {comp_level})" if comp_level else comp_mode
            summary_table.add("Compression config", comp_str)

            comp_ratio = summary.get("compression_ratio_sample")
            if comp_ratio:
                summary_table.add("Compression ratio", f"{comp_ratio:.2f}x")
            else:
                summary_table.add("Compressed records", f"{summary.get('compressed_records', 0):,}")

            summary_table.add("Hash-only records", f"{summary.get('hash_only_records', 0):,}")
            summary_table.add("Indexed attributes", f"{summary.get('indexed_attributes', 0):,}")

        title_text = f"{icons.get('search', '')}Index summary"
        console.print(section(title_text, summary_table, ui_context))

        if verbose:
            borderless = is_borderless(ui_context)

            def build_dist_table(title: str, key_header: str, data: dict, limit: int | None = None):
                t = table(ui_context, title=None if borderless else title, expand=False)
                t.add_column(key_header, style=palette.get("key", "dim"))
                t.add_column("Count", justify="right", style=palette.get("primary_value", "default"))
                for k, v in list(data.items())[:limit]:
                    t.add_row(Text(str(k)), f"{v:,}")
                if borderless:
                    return Group(heading(title, palette.get("section_title", "bold")), t)
                return t

            dist_tables = []

            top_exts = summary.get("top_extensions", {})
            if top_exts:
                dist_tables.append(build_dist_table("Top extensions", "Extension", top_exts, limit=limit))

            top_media = summary.get("top_media_types", {})
            if top_media:
                dist_tables.append(build_dist_table("Top media types", "Media type", top_media, limit=limit))

            top_schemas = summary.get("top_schemas", {})
            if top_schemas:
                dist_tables.append(build_dist_table("Top schemas", "Schema", top_schemas, limit=limit))

            top_attrs = summary.get("top_attribute_keys", {})
            if top_attrs:
                dist_tables.append(build_dist_table("Top attributes", "Attribute", top_attrs, limit=limit))

            if dist_tables:
                console.print()
                console.print(Trimmed(Columns(dist_tables, padding=(0, 4 if borderless else 2))))

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to retrieve search index summary.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while getting search index info: {err}",
        )
