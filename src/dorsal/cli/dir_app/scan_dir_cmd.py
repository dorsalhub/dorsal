# Copyright 2025 Dorsal Hub LTD
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


from __future__ import annotations
import json
import typer
import pathlib
import datetime
import time
from typing import Annotated, TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ValidationError
from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
from rich.text import Text
import logging

from dorsal.file.utils.size import human_filesize
from dorsal.common import constants

if TYPE_CHECKING:
    from dorsal.file.collection.local import LocalFileCollection

logger = logging.getLogger(__name__)


class SortBy(BaseModel):
    value: Literal["name", "size", "type", "date"]


class SortOrder(BaseModel):
    value: Literal["asc", "desc"]


def scan_directory(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="The path to the directory to scan.",
        ),
    ],
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Path to save an output file. Extension (.json or .csv) determines format.",
            dir_okay=True,
            file_okay=True,
            writable=True,
            resolve_path=True,
            rich_help_panel="Output Options",
        ),
    ] = None,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Save the full JSON metadata report to the default scan directory.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    csv: Annotated[
        bool,
        typer.Option(
            "-c",
            "--csv",
            help="Save the summary file table as a CSV report.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the full metadata as a raw JSON object to stdout for scripting.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="Scan subdirectories recursively.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            help="Limit the number of files displayed in the summary table.",
            rich_help_panel="Scan Options",
        ),
    ] = 20,
    sort_by: Annotated[
        str,
        typer.Option(
            case_sensitive=False,
            help="Column to sort by. One of: name, size, type, date.",
            rich_help_panel="Scan Options",
        ),
    ] = "name",
    sort_order: Annotated[
        str,
        typer.Option(
            case_sensitive=False,
            help="Sort order. One of: asc, desc.",
            rich_help_panel="Scan Options",
        ),
    ] = "asc",
    use_cache: Annotated[
        bool,
        typer.Option(
            "--use-cache",
            help="Force the use of the cache, overriding any global setting.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    skip_cache: Annotated[
        bool,
        typer.Option(
            "--skip-cache",
            help="Bypass the local cache and re-process all files, overriding any global setting.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process all files and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
):
    """
    Scans a directory, generates metadata for all files, and displays or saves the results.
    """
    from dorsal.common.cli import (
        EXIT_CODE_ERROR,
        get_rich_console,
        exit_cli,
        determine_use_cache_value,
    )
    from dorsal.file.collection.local import LocalFileCollection

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    start_time = time.perf_counter()

    try:
        SortBy(value=sort_by)
        SortOrder(value=sort_order)
    except ValidationError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Invalid sorting option provided: {e}")

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache flags cannot be used together.",
        )

    if skip_cache and overwrite_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --skip-cache and --overwrite-cache flags cannot be used together.",
        )

    if output_path and not (save or csv):
        if str(output_path).lower().endswith(".json"):
            save = True
        elif str(output_path).lower().endswith(".csv"):
            csv = True
        else:
            console.print(
                f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                f" Please use -s (for .json) or -c (for .csv) to specify the report type.",
                style="yellow",
            )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    try:
        progress_console = None if json_output else console
        collection = LocalFileCollection(
            source=str(path),
            console=progress_console,
            palette=palette,
            recursive=recursive,
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
        )
    except Exception as e:
        logger.exception("Failed to initialize FileCollection.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred during file discovery: {e}",
        )

    duration = time.perf_counter() - start_time

    if json_output:
        scan_data = {
            "scan_metadata": {
                "path": str(path),
                "recursive": recursive,
                "duration_seconds": duration,
                "total_files_found": len(collection),
            },
            "results": collection.to_dict(),
        }
        console.print(json.dumps(scan_data, indent=2, default=str))
        exit_cli()

    collection_info = collection.info()
    source_breakdown: list[dict] = collection_info.get("by_source", [])
    files_from_cache = 0
    for source_stat in source_breakdown:
        if source_stat.get("source") == "cache":
            files_from_cache = source_stat.get("count", 0)
            break

    cache_info_str = (
        f" ([{palette.get('success', 'green')}]{files_from_cache} from cache[/])" if files_from_cache > 0 else ""
    )

    console.print(
        f"✨ Found and processed [{palette['success']}]{len(collection)}[/] file(s) in [{palette['primary_value']}]{escape(str(path))}[/]{cache_info_str} in {duration:.3f} seconds."
    )

    if collection.warnings:
        warning_panel = Panel(
            "\n".join(f"- {w}" for w in collection.warnings),
            title=f"[{palette['panel_title_warning']}]Warnings[/]",
            border_style=palette["panel_border_warning"],
            title_align="left",
            expand=False,
        )
        console.print(warning_panel)

    if not collection:
        exit_cli()

    _print_directory_summary_panel(collection_info=collection_info, palette=palette)
    _print_file_details_table(
        collection=collection,
        palette=palette,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    if save:
        _save_json_report(
            collection=collection,
            output_path=output_path,
            palette=palette,
        )

    if csv:
        _save_csv_report(collection=collection, output_path=output_path, palette=palette)


def _get_final_path(source_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            dir_name = source_path.name
            return output_path / f"scan-dir-{dir_name}{suffix}"
        else:
            return output_path

    constants.CLI_SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_name = source_path.name.replace(" ", "_")
    return constants.CLI_SCAN_REPORTS_DIR / f"scan-dir-{dir_name}-{timestamp}{suffix}"


def _save_json_report(
    collection: "LocalFileCollection",
    output_path: Optional[pathlib.Path],
    palette: dict,
):
    """Saves the full JSON metadata report."""
    from dorsal.common.cli import EXIT_CODE_ERROR, get_rich_console, exit_cli

    console = get_rich_console()

    source_path = pathlib.Path(collection.source_info.get("path", "unknown-dir"))
    final_path = _get_final_path(source_path, output_path, ".json")

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        collection.to_json(str(final_path), exclude={"embeddings", "text_chunks"})
        console.print(f"✅ JSON report saved to: [{palette.get('primary_value')}]{final_path}[/]")
    except IOError as e:
        logger.exception(f"Failed to write to output file: {final_path}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {e}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        console.print(f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style="yellow")


def _save_csv_report(
    collection: "LocalFileCollection",
    output_path: Optional[pathlib.Path],
    palette: dict,
):
    """Saves the summary table as a CSV report."""
    from dorsal.common.cli import EXIT_CODE_ERROR, get_rich_console, exit_cli

    console = get_rich_console()

    source_path = pathlib.Path(collection.source_info.get("path", "unknown-dir"))
    final_path = _get_final_path(source_path, output_path, ".csv")

    console.print("\n📄 Saving table as CSV report...")
    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        collection.to_csv(
            str(final_path),
        )
        console.print(f"✅ CSV report saved to: [{palette.get('primary_value')}]{final_path}[/]")
    except IOError as e:
        logger.exception(f"Failed to write to output file: {final_path}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {e}")
    except Exception as e:
        logger.error(f"Failed to save CSV report: {e}")
        console.print(f"⚠️ Could not save CSV report to {final_path}. Error: {e}", style="yellow")


def _print_directory_summary_panel(collection_info: dict, palette: dict):
    """Prints a rich summary panel of the directory's contents."""
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()

    overall = collection_info.get("overall", {})
    by_type = collection_info.get("by_type", [])

    total_files = overall.get("total_files", 0)
    total_size = human_filesize(overall.get("total_size", 0))
    media_type_count = len(by_type)

    newest = overall.get("newest_file", {})
    oldest = overall.get("oldest_file", {})

    newest_str = (
        f"{newest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({escape(newest['path'])})" if newest.get("path") else "N/A"
    )
    oldest_str = (
        f"{oldest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({escape(oldest['path'])})" if oldest.get("path") else "N/A"
    )

    summary_text = Text(no_wrap=True)
    summary_text.append("       Total Files: ", style=palette.get("key"))
    summary_text.append(str(total_files), style=palette.get("value"))
    summary_text.append("\n")
    summary_text.append("        Total Size: ", style=palette.get("key"))
    summary_text.append(total_size, style=palette.get("value"))
    summary_text.append("\n")
    summary_text.append("Newest Modified File: ", style=palette.get("key"))
    summary_text.append(newest_str, style=palette.get("value"))
    summary_text.append("\n")
    summary_text.append("Oldest Modified File: ", style=palette.get("key"))
    summary_text.append(oldest_str, style=palette.get("value"))
    summary_text.append("\n\n")
    summary_text.append("       Media Types: ", style=palette.get("key"))
    summary_text.append(str(media_type_count), style=palette.get("value"))

    panel = Panel(
        summary_text,
        title=f"[{palette.get('panel_title', 'bold default')}]Directory Scan Summary[/]",
        border_style=palette.get("panel_border", "blue"),
        title_align="left",
        expand=False,
    )
    console.print(panel)


def _print_file_details_table(
    collection: "LocalFileCollection",
    palette: dict,
    limit: int,
    sort_by: str,
    sort_order: str,
):
    """Prints a rich, detailed table of individual files to the console."""
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()

    total_files = len(collection)

    sort_key_map = {
        "name": lambda file: file.name.lower(),
        "size": lambda file: file.size,
        "type": lambda file: file.media_type,
        "date": lambda file: file.date_modified,
    }
    key_func = sort_key_map[sort_by]
    is_reverse = sort_order == "desc"
    sorted_files = sorted(list(collection), key=key_func, reverse=is_reverse)
    files_to_display = sorted_files[:limit]

    table = Table(
        title="File Scan Details",
        show_header=True,
        header_style=palette["table_header"],
        expand=False,
    )

    table.add_column("Filename", style=palette["primary_value"], min_width=30, overflow="ellipsis")
    table.add_column("Size", justify="right", style=palette.get("value"))
    table.add_column("Media Type", style=palette.get("value"))
    table.add_column("Modified Date", style=palette.get("value"))

    for file in files_to_display:
        modified_date_str = file.date_modified.strftime("%Y-%m-%d %H:%M:%S")

        table.add_row(
            file.name,
            human_filesize(file.size),
            file.media_type,
            modified_date_str,
        )

    console.print(table)

    if total_files > limit:
        console.print(
            f"[{palette.get('info', 'dim')}]Showing first {limit} of {total_files} files. Use --limit to show more or save the full report.[/]"
        )
