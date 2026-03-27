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

from __future__ import annotations

import logging
import typer
import pathlib
import datetime
import json
import time
from typing import Annotated, Any, Optional, Literal, TYPE_CHECKING

from pydantic import BaseModel, ValidationError
from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
from rich.text import Text

from dorsal.common import constants
from dorsal.common.cli import (
    exit_cli,
    EXIT_CODE_ERROR,
    get_rich_console,
    determine_use_cache_value,
)

if TYPE_CHECKING:
    from dorsal.file.dorsal_file import LocalFile
    from dorsal.file.collection.local import LocalFileCollection

logger = logging.getLogger(__name__)


class SortBy(BaseModel):
    value: Literal["name", "size", "type", "date"]


class SortOrder(BaseModel):
    value: Literal["asc", "desc"]


def scan_target(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            help="The path to the file or directory to scan.",
        ),
    ],
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "-o",
            "--output",
            help="Custom output path (file or directory) for generated reports.",
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
            help="Save a JSON report to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    report: Annotated[
        bool,
        typer.Option(
            "--report",
            help="Generate a self-contained HTML report.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output JSON to stdout. Can be combined with --save.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    template: Annotated[
        str,
        typer.Option(
            "--template",
            "-t",
            help="Name or path of the report template to use.",
            rich_help_panel="Output Options",
        ),
    ] = "default",
    csv: Annotated[
        bool,
        typer.Option(
            "-c",
            "--csv",
            help="[Dir Only] Save the directory summary table as a CSV report.",
            rich_help_panel="Directory Output Options",
        ),
    ] = False,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="[Dir Only] Scan subdirectories recursively.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            help="[Dir Only] Limit the number of files displayed in the summary table.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = 20,
    sort_by: Annotated[
        str,
        typer.Option(
            case_sensitive=False,
            help="[Dir Only] Column to sort by. One of: name, size, type, date.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = "name",
    sort_order: Annotated[
        str,
        typer.Option(
            case_sensitive=False,
            help="[Dir Only] Sort order. One of: asc, desc.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = "asc",
    lazy: Annotated[
        bool,
        typer.Option(
            "--lazy",
            help="[Dir Only] Start processing immediately with a spinner. Useful for massive directories.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = False,
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
            help="Bypass the local cache and re-process the target.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process the target and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    resolve_links: Annotated[
        bool,
        typer.Option(
            "--follow-links/--no-follow-links",
            help="Follow symlinks to scan target content vs scanning the link itself.",
        ),
    ] = True,
):
    """
    Scans a local file or directory, extracts metadata, and generates reports.
    """
    console = get_rich_console()
    palette = ctx.obj.get("palette", {})

    if use_cache and skip_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --use-cache and --skip-cache cannot be used together.")
    if skip_cache and overwrite_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --skip-cache and --overwrite-cache cannot be used together.")
    if json_output and report:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --json (stdout) and --report (HTML) flags are not compatible.")

    if output_path:
        out_str = str(output_path).lower()
        if not (save or report or csv):
            if out_str.endswith(".json"):
                save = True
            elif out_str.endswith(".html"):
                report = True
            elif out_str.endswith(".csv"):
                csv = True
            else:
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified, but no report type was requested.",
                    style=palette.get("warning", "yellow"),
                )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    if path.is_file():
        if csv or recursive or lazy:
            console.print(
                "⚠️ [yellow]Warning:[/] Directory-specific flags (--csv, --recursive, --lazy) are ignored when scanning a single file.",
                style=palette.get("warning", "yellow"),
            )

        _process_file_scan(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            json_output=json_output,
            save=save,
            report=report,
            output_path=output_path,
            template=template,
            resolve_links=resolve_links,
            palette=palette,
            console=console,
        )
    else:
        try:
            SortBy(value=sort_by)
            SortOrder(value=sort_order)
        except ValidationError as e:
            exit_cli(code=EXIT_CODE_ERROR, message=f"Invalid sorting option provided: {e}")

        _process_dir_scan(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            json_output=json_output,
            save=save,
            report=report,
            csv=csv,
            output_path=output_path,
            template=template,
            resolve_links=resolve_links,
            recursive=recursive,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
            lazy=lazy,
            palette=palette,
            console=console,
        )


def _process_file_scan(
    ctx,
    path,
    use_cache_value,
    overwrite_cache,
    json_output,
    save,
    report,
    output_path,
    template,
    resolve_links,
    palette,
    console,
):
    from dorsal.cli.views.file import create_file_info_panel
    from dorsal.file.dorsal_file import LocalFile

    if not json_output:
        console.print(f"📄 Scanning metadata for [{palette.get('primary_value', 'cyan')}]{path.name}[/]")

    try:
        local_file = LocalFile(
            file_path=str(path),
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
            follow_symlinks=resolve_links,
        )

        record_dict: dict[str, Any] = local_file.to_dict(mode="json")
        if "local_attributes" in record_dict:
            record_dict["local_filesystem"] = record_dict["local_attributes"]
            record_dict["local_filesystem"]["full_path"] = record_dict["local_attributes"].get("file_path", str(path))
            for key in ["date_created", "date_modified", "date_accessed"]:
                val = record_dict["local_filesystem"].get(key)
                if isinstance(val, datetime.datetime):
                    record_dict["local_filesystem"][key] = val.isoformat()
        else:
            record_dict["local_filesystem"] = {
                "full_path": local_file._file_path,
                "date_created": (local_file.date_created.isoformat() if hasattr(local_file, "date_created") else None),
                "date_modified": (
                    local_file.date_modified.isoformat() if hasattr(local_file, "date_modified") else None
                ),
            }

        if json_output:
            console.print(json.dumps(record_dict, indent=2, default=str, ensure_ascii=False))
        else:
            panel = create_file_info_panel(
                record_dict=record_dict,
                title=f"File Record: {local_file.name}",
                palette=palette,
                private=None,
                source=local_file._source,
            )
            console.print(panel)

        if save:
            final_path = _get_final_path(path, output_path, ".json", is_dir=False)
            _save_report_to_disk(
                final_path, json.dumps(record_dict, indent=2, default=str, ensure_ascii=False), "JSON", console, palette
            )

        if report:
            from dorsal.api.file import generate_html_file_report

            final_path = _get_final_path(path, output_path, ".html", is_dir=False)
            try:
                with console.status(f"📄 Generating HTML report for '[bold]{path.name}[/]'..."):
                    generate_html_file_report(
                        file_path=local_file._file_path,
                        local_file=local_file,
                        output_path=str(final_path),
                        template=template,
                    )
                console.print(f"✅ HTML report saved to: [{palette.get('primary_value', 'cyan')}]{final_path}[/]")
            except Exception as e:
                logger.error(f"Failed to generate HTML report: {e}")
                console.print(f"⚠️ Could not generate HTML report. Error: {e}", style=palette.get("warning", "yellow"))

    except Exception as err:
        logger.exception(f"CLI 'scan' command failed while processing {path}.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")


def _process_dir_scan(
    ctx,
    path,
    use_cache_value,
    overwrite_cache,
    json_output,
    save,
    report,
    csv,
    output_path,
    template,
    resolve_links,
    recursive,
    limit,
    sort_by,
    sort_order,
    lazy,
    palette,
    console,
):
    from dorsal.file.collection.local import LocalFileCollection

    start_time = time.perf_counter()
    try:
        progress_console = None if json_output else console
        collection = LocalFileCollection(
            source=str(path),
            console=progress_console,
            palette=palette,
            recursive=recursive,
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
            follow_symlinks=resolve_links,
            lazy=lazy,
        )
    except Exception as e:
        logger.exception("Failed to initialize FileCollection.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An error occurred during file discovery: {e}")

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
    files_from_cache = sum(
        stat.get("count", 0) for stat in collection_info.get("by_source", []) if stat.get("source") == "cache"
    )
    cache_info_str = (
        f" ([{palette.get('success', 'green')}]{files_from_cache} from cache[/])" if files_from_cache > 0 else ""
    )

    console.print(
        f"Found and processed [{palette.get('success', 'green')}]{len(collection)}[/] file(s) in [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]{cache_info_str} in {duration:.3f} seconds."
    )

    if collection.warnings:
        console.print(
            Panel(
                "\n".join(f"- {w}" for w in collection.warnings),
                title=f"[{palette.get('panel_title_warning', 'yellow')}]Warnings[/]",
                border_style=palette.get("panel_border_warning", "yellow"),
                title_align="left",
                expand=False,
            )
        )

    if not collection:
        exit_cli()

    _print_directory_summary_panel(collection_info, palette, console)
    _print_file_details_table(collection, palette, limit, sort_by, sort_order, console)

    if save:
        final_path = _get_final_path(path, output_path, ".json", is_dir=True)
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            collection.to_json(str(final_path), exclude={"embeddings", "text_chunks"})
            console.print(f"✅ JSON report saved to: [{palette.get('primary_value', 'cyan')}]{final_path}[/]")
        except Exception as e:
            logger.error(f"Failed to save JSON report: {e}")
            console.print(f"⚠️ Could not save JSON report. Error: {e}", style=palette.get("warning", "yellow"))

    if csv:
        final_path = _get_final_path(path, output_path, ".csv", is_dir=True)
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            collection.to_csv(str(final_path))
            console.print(f"✅ CSV report saved to: [{palette.get('primary_value', 'cyan')}]{final_path}[/]")
        except Exception as e:
            logger.error(f"Failed to save CSV report: {e}")
            console.print(f"⚠️ Could not save CSV report. Error: {e}", style=palette.get("warning", "yellow"))

    if report:
        from dorsal.api.file import generate_html_directory_report

        final_path = _get_final_path(path, output_path, ".html", is_dir=True)
        try:
            with console.status(f"📄 Generating HTML Directory report for '[bold]{path.name}[/]'..."):
                generate_html_directory_report(
                    dir_path=str(path),
                    output_path=str(final_path),
                    local_collection=collection,
                    template=template,
                    use_cache=use_cache_value,
                    recursive=recursive,
                )
            console.print(f"✅ HTML Directory report saved to: [{palette.get('primary_value', 'cyan')}]{final_path}[/]")
        except Exception as e:
            logger.error(f"Failed to generate HTML report: {e}")
            console.print(
                f"⚠️ Could not generate HTML directory report. Error: {e}", style=palette.get("warning", "yellow")
            )


def _get_final_path(
    source_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str, is_dir: bool
) -> pathlib.Path:
    if output_path:
        if output_path.is_dir():
            prefix = "scan-dir-" if is_dir else ""
            return output_path / f"{prefix}{source_path.stem}_report{suffix}"
        return output_path

    constants.CLI_SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = source_path.name.replace(" ", "_")
    prefix = "scan-dir-" if is_dir else ""
    return constants.CLI_SCAN_REPORTS_DIR / f"{prefix}{safe_name}-{timestamp}{suffix}"


def _save_report_to_disk(path: pathlib.Path, content: str, doc_type: str, console, palette):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"✅ {doc_type} report saved to: [{palette.get('primary_value', 'cyan')}]{path}[/]")
    except Exception as e:
        logger.error(f"Failed to save {doc_type} report: {e}")
        console.print(f"⚠️ Could not save {doc_type} report. Error: {e}", style=palette.get("warning", "yellow"))


def _print_directory_summary_panel(collection_info: dict, palette: dict, console):
    from dorsal.file.utils.size import human_filesize

    overall, by_type = collection_info.get("overall", {}), collection_info.get("by_type", [])
    newest, oldest = overall.get("newest_file", {}), overall.get("oldest_file", {})

    newest_str = (
        f"{newest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({escape(newest['path'])})" if newest.get("path") else "N/A"
    )
    oldest_str = (
        f"{oldest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({escape(oldest['path'])})" if oldest.get("path") else "N/A"
    )

    summary_text = Text(no_wrap=True)
    for label, val in [
        ("       Total Files: ", str(overall.get("total_files", 0))),
        ("        Total Size: ", human_filesize(overall.get("total_size", 0))),
        ("Newest Modified File: ", newest_str),
        ("Oldest Modified File: ", oldest_str),
        ("\n       Media Types: ", str(len(by_type))),
    ]:
        summary_text.append(label, style=palette.get("key"))
        summary_text.append(val + "\n" if "\n" not in label else val, style=palette.get("value"))

    console.print(
        Panel(
            summary_text,
            title=f"[{palette.get('panel_title', 'bold default')}]Directory Scan Summary[/]",
            border_style=palette.get("panel_border", "blue"),
            title_align="left",
            expand=False,
        )
    )


def _print_file_details_table(collection, palette, limit, sort_by, sort_order, console):
    from dorsal.file.utils.size import human_filesize

    sort_key_map = {
        "name": lambda f: f.name.lower(),
        "size": lambda f: f.size,
        "type": lambda f: f.media_type,
        "date": lambda f: f.date_modified,
    }
    sorted_files = sorted(list(collection), key=sort_key_map[sort_by], reverse=(sort_order == "desc"))

    table = Table(
        title="File Scan Details", show_header=True, header_style=palette.get("table_header", "bold"), expand=False
    )
    table.add_column("Filename", style=palette.get("primary_value", "cyan"), min_width=30, overflow="ellipsis")
    table.add_column("Size", justify="right", style=palette.get("value"))
    table.add_column("Media Type", style=palette.get("value"))
    table.add_column("Modified Date", style=palette.get("value"))

    for file in sorted_files[:limit]:
        path_obj, display_name = pathlib.Path(file._file_path), file.name
        if path_obj.is_symlink():
            try:
                display_name = f"{escape(path_obj.name)} [dim italic]→ {escape(str(path_obj.readlink()))}[/]"
            except OSError:
                display_name = f"{escape(path_obj.name)} [dim italic](symlink)[/]"
        table.add_row(
            display_name, human_filesize(file.size), file.media_type, file.date_modified.strftime("%Y-%m-%d %H:%M:%S")
        )

    console.print(table)
    if len(collection) > limit:
        console.print(
            f"[{palette.get('info', 'dim')}]Showing first {limit} of {len(collection)} files. Use --limit to show more or save the full report.[/]"
        )
