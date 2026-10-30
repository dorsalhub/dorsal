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
import os
import re
import typer
import pathlib
import datetime
import time
from enum import Enum
from typing import Annotated, Any, Optional, TYPE_CHECKING

from rich.cells import cell_len
from rich.markup import escape
from rich.text import Text

from dorsal.common import constants
from dorsal.common.cli import (
    exit_cli,
    EXIT_CODE_ERROR,
    get_error_console,
    get_rich_console,
    determine_use_cache_value,
    format_json_output,
    print_json_output,
)
from dorsal.cli.themes.palettes import get_palette
from dorsal.cli.themes.icons import get_icons
from dorsal.cli.themes.borders import get_borders

if TYPE_CHECKING:
    from dorsal.file.dorsal_file import LocalFile
    from dorsal.file.collection.local import LocalFileCollection

logger = logging.getLogger(__name__)


_REPORT_SUFFIXES = (".json", ".csv")


class SortBy(str, Enum):
    NAME = "name"
    SIZE = "size"
    TYPE = "type"
    DATE = "date"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


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
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Custom output path for generated reports. An existing directory, or a path ending in a separator, is treated as a directory.",
            rich_help_panel="Output Options",
        ),
    ] = None,
    deep: Annotated[
        bool,
        typer.Option(
            "--deep",
            "-d",
            help="Perform a deep scan, calculating all cryptographic hashes for the file.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Save a JSON report to the default directory or --output path.",
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
        Optional[str],
        typer.Option(
            "--template",
            "-t",
            help="Deprecated: has no effect since HTML reports were removed.",
            hidden=True,
        ),
    ] = None,
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
            min=1,
            help="[Dir Only] Limit the number of files displayed in the summary table.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = 20,
    sort_by: Annotated[
        SortBy,
        typer.Option(
            case_sensitive=False,
            help="[Dir Only] Column to sort by.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = SortBy.NAME,
    sort_order: Annotated[
        SortOrder,
        typer.Option(
            case_sensitive=False,
            help="[Dir Only] Sort order.",
            rich_help_panel="Directory Scan Options",
        ),
    ] = SortOrder.ASC,
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
    error_console = get_error_console()
    status_console = error_console if json_output else console
    palette = ctx.obj.get("palette", get_palette())
    icons = ctx.obj.get("icons", get_icons())
    borders = ctx.obj.get("borders", get_borders())

    if use_cache and skip_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --use-cache and --skip-cache cannot be used together.")
    if skip_cache and overwrite_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --skip-cache and --overwrite-cache cannot be used together.")

    warning_prefix = f"[{palette.get('warning', 'yellow')}]Warning:[/]"

    if template is not None:
        error_console.print(f"{warning_prefix} --template has no effect: HTML reports are no longer generated.")

    output_path: Optional[pathlib.Path] = None
    output_is_dir = False
    if output:
        separators = tuple(sep for sep in (os.sep, os.altsep) if sep)
        output_path = pathlib.Path(output).expanduser().resolve()
        output_is_dir = output.endswith(separators) or output_path.is_dir()
        if not (save or csv):
            out_suffix = output_path.suffix.lower()
            if not output_is_dir and out_suffix == ".json":
                save = True
            elif not output_is_dir and out_suffix == ".csv":
                csv = True
            else:
                error_console.print(
                    f"{warning_prefix} --output path '{escape(str(output_path))}' was specified, but no report type was requested."
                )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    if path.is_file():
        if csv or recursive or lazy:
            error_console.print(
                f"{warning_prefix} Directory-specific flags (--csv, --recursive, --lazy) are ignored when scanning a single file."
            )

        _process_file_scan(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            json_output=json_output,
            save=save,
            output_path=output_path,
            output_is_dir=output_is_dir,
            resolve_links=resolve_links,
            palette=palette,
            icons=icons,
            borders=borders,
            console=console,
            status_console=status_console,
            calculate_hashes=deep,
        )
    else:
        _process_dir_scan(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            json_output=json_output,
            save=save,
            csv=csv,
            output_path=output_path,
            output_is_dir=output_is_dir,
            resolve_links=resolve_links,
            recursive=recursive,
            limit=limit,
            sort_by=sort_by.value,
            sort_order=sort_order.value,
            lazy=lazy,
            palette=palette,
            icons=icons,
            borders=borders,
            console=console,
            status_console=status_console,
            calculate_hashes=deep,
        )


def _process_file_scan(
    ctx,
    path,
    use_cache_value,
    overwrite_cache,
    json_output,
    save,
    output_path,
    output_is_dir,
    resolve_links,
    palette,
    icons,
    borders,
    console,
    status_console,
    calculate_hashes,
) -> None:
    from dorsal.cli.views.file import create_file_info_panel
    from dorsal.file.dorsal_file import LocalFile

    try:
        with get_error_console().status(f"Scanning [{palette.get('primary_value', 'cyan')}]{escape(path.name)}[/]"):
            local_file = LocalFile(
                file_path=str(path),
                use_cache=use_cache_value,
                overwrite_cache=overwrite_cache,
                follow_symlinks=resolve_links,
                calculate_hashes=calculate_hashes,
            )

        record_dict: dict[str, Any] = local_file.to_dict(mode="json")
        if "local_attributes" in record_dict:
            record_dict["local_filesystem"] = dict(record_dict["local_attributes"])
            record_dict["local_filesystem"]["full_path"] = record_dict["local_attributes"].get("file_path", str(path))
            for key in ["date_created", "date_modified", "date_accessed"]:
                val = record_dict["local_filesystem"].get(key)
                if isinstance(val, datetime.datetime):
                    record_dict["local_filesystem"][key] = val.isoformat()
        else:
            record_dict["local_filesystem"] = {
                "full_path": local_file.file_path,
                "local_record_id": local_file.record_id,
                "date_created": (local_file.date_created.isoformat() if hasattr(local_file, "date_created") else None),
                "date_modified": (
                    local_file.date_modified.isoformat() if hasattr(local_file, "date_modified") else None
                ),
            }

        if json_output:
            print_json_output(record_dict, console)
        else:
            panel = create_file_info_panel(
                record_dict=record_dict,
                title=escape(local_file.name or path.name),
                palette=palette,
                icons=icons,
                box_style=borders,
                private=None,
                source=local_file._source,
            )
            console.print(panel)

        if save:
            final_path = _get_final_path(path, output_path, output_is_dir, ".json", is_dir=False)
            _save_report_to_disk(final_path, format_json_output(record_dict), "JSON", status_console, palette)

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
    csv,
    output_path,
    output_is_dir,
    resolve_links,
    recursive,
    limit,
    sort_by,
    sort_order,
    lazy,
    palette,
    icons,
    borders,
    console,
    status_console,
    calculate_hashes,
) -> None:
    from dorsal.file.collection.local import LocalFileCollection

    ui_context: Any = {"palette": palette, "icons": icons, "borders": borders}
    start_time = time.perf_counter()
    try:
        collection = LocalFileCollection(
            source=str(path),
            console=status_console,
            palette=palette,
            recursive=recursive,
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
            follow_symlinks=resolve_links,
            lazy=lazy,
            calculate_hashes=calculate_hashes,
        )
    except Exception as e:
        logger.exception("Failed to initialize FileCollection.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An error occurred during file discovery: {e}")

    duration = time.perf_counter() - start_time

    scan_data: dict[str, Any] | None = None
    if json_output or save:
        scan_data = collection.to_dict(exclude={"embeddings", "text_chunks"})
        scan_data["scan_metadata"]["duration_seconds"] = duration

    if json_output:
        print_json_output(scan_data, console)
    else:
        collection_info = collection.info()
        files_from_cache = sum(
            stat.get("count", 0) for stat in collection_info.get("by_source", []) if stat.get("source") == "cache"
        )
        cache_info_str = (
            f" ([{palette.get('success', 'green')}]{files_from_cache} from cache[/])" if files_from_cache > 0 else ""
        )

        from dorsal.cli.views.layout import Trimmed

        console.print(
            Trimmed(
                f"Found and processed [{palette.get('success', 'green')}]{len(collection)}[/] file(s) in [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]{cache_info_str} in {duration:.3f} seconds."
            )
        )

    if collection.warnings:
        from dorsal.cli.views.layout import message

        if len(collection.warnings) == 1:
            warning_body = Text(str(collection.warnings[0]))
        else:
            warning_body = Text("\n").join(Text(f"- {w}") for w in collection.warnings)
        title = "Warning" if len(collection.warnings) == 1 else "Warnings"
        get_error_console().print(message(title, warning_body, ui_context, level="warning", padding=(0, 1)))

    if not collection:
        exit_cli()

    if not json_output:
        console.print()
        _print_directory_summary_panel(collection_info, ui_context, console)
        console.print()
        _print_file_details_table(collection, ui_context, limit, sort_by, sort_order, console)

    if save:
        final_path = _get_final_path(path, output_path, output_is_dir, ".json", is_dir=True)
        _save_report_to_disk(final_path, format_json_output(scan_data), "JSON", status_console, palette)

    if csv:
        final_path = _get_final_path(path, output_path, output_is_dir, ".csv", is_dir=True)
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            collection.to_csv(str(final_path))
            status_console.print(
                f"CSV report saved to: [{palette.get('primary_value', 'cyan')}]{escape(str(final_path))}[/]"
            )
        except Exception as e:
            logger.error(f"Failed to save CSV report: {e}")
            get_error_console().print(
                f"[{palette.get('warning', 'yellow')}]Warning:[/] Could not save CSV report. Error: {escape(str(e))}"
            )


def _safe_report_name(source_path: pathlib.Path, is_dir: bool) -> str:
    resolved = source_path.resolve()
    name = resolved.name if is_dir else resolved.stem
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "root"


def _get_final_path(
    source_path: pathlib.Path,
    output_path: Optional[pathlib.Path],
    output_is_dir: bool,
    suffix: str,
    is_dir: bool,
) -> pathlib.Path:
    """Resolves where a report with the given `suffix` is written.

    - Directory output: `<output>/[scan-dir-]<name>_report<suffix>`.
    - File output: used as-is when its suffix matches; otherwise the suffix is swapped (or appended), e.g.
      `-o report.json --save --csv` writes `report.json` and `report.csv`.
    - No output: a timestamped file in the CLI reports directory, never overwriting an existing report.
    """
    prefix = "scan-dir-" if is_dir else ""
    name = _safe_report_name(source_path, is_dir)

    if output_path:
        if output_is_dir:
            return output_path / f"{prefix}{name}_report{suffix}"
        out_suffix = output_path.suffix.lower()
        if out_suffix == suffix:
            return output_path
        if out_suffix in _REPORT_SUFFIXES:
            return output_path.with_suffix(suffix)
        return output_path.with_name(output_path.name + suffix)

    reports_dir = constants.CLI_SCAN_REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}{name}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = reports_dir / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = reports_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _save_report_to_disk(path: pathlib.Path, content: str, doc_type: str, console, palette):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"{doc_type} report saved to: [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]")
    except Exception as e:
        logger.error(f"Failed to save {doc_type} report: {e}")
        get_error_console().print(
            f"[{palette.get('warning', 'yellow')}]Warning:[/] Could not save {doc_type} report. Error: {escape(str(e))}"
        )


def _print_directory_summary_panel(collection_info: dict, ui_context, console):
    from dorsal.cli.views.layout import key_values, section
    from dorsal.file.utils.size import human_filesize

    overall, by_type = collection_info.get("overall", {}), collection_info.get("by_type", [])
    newest, oldest = overall.get("newest_file", {}), overall.get("oldest_file", {})

    newest_str = f"{newest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({newest['path']})" if newest.get("path") else "N/A"
    oldest_str = f"{oldest['date'].strftime('%Y-%m-%d %H:%M:%S')} ({oldest['path']})" if oldest.get("path") else "N/A"

    summary = key_values(ui_context)
    summary.add("Total files", str(overall.get("total_files", 0)))
    summary.add("Total size", human_filesize(overall.get("total_size", 0)))
    summary.add("Newest modified file", newest_str)
    summary.add("Oldest modified file", oldest_str)
    summary.add("Media types", str(len(by_type)))

    console.print(section("Directory scan summary", summary, ui_context))


def _print_file_details_table(collection, ui_context, limit, sort_by, sort_order, console):
    from dorsal.cli.views.layout import is_borderless, table
    from dorsal.file.utils.size import human_filesize

    palette = ui_context["palette"]
    sort_key_map = {
        "name": lambda f: f.name.lower(),
        "size": lambda f: f.size,
        "type": lambda f: f.media_type,
        "date": lambda f: f.date_modified,
    }
    sorted_files = sorted(list(collection), key=sort_key_map[sort_by], reverse=(sort_order == "desc"))

    details_table = table(ui_context, title="File scan details", expand=False)

    headers = ("Size", "Media type", "Record ID", "Modified date")
    rows = []
    for file in sorted_files[:limit]:
        path_obj, display_name = pathlib.Path(file.file_path), escape(file.name)
        if path_obj.is_symlink():
            try:
                display_name = f"{escape(path_obj.name)} [dim italic]→ {escape(str(path_obj.readlink()))}[/]"
            except OSError:
                display_name = f"{escape(path_obj.name)} [dim italic](symlink)[/]"

        rows.append(
            (
                display_name,
                human_filesize(file.size),
                file.media_type,
                file.record_id,
                file.date_modified.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    metadata_width = sum(
        max([cell_len(h)] + [cell_len(str(r[i + 1])) for r in rows]) + 2 for i, h in enumerate(headers)
    )
    frame = 0 if is_borderless(ui_context) else len(headers) + 4
    filename_width = max(30, console.width - metadata_width - frame)

    details_table.add_column(
        "Filename",
        style=palette.get("primary_value", "cyan"),
        min_width=30,
        max_width=filename_width,
        no_wrap=True,
        overflow="ellipsis",
    )
    details_table.add_column(headers[0], justify="right", style=palette.get("value"))
    details_table.add_column(headers[1], style=palette.get("value"))
    details_table.add_column(headers[2], style=palette.get("hash_value", "magenta"))
    details_table.add_column(headers[3], style=palette.get("value"))

    for row in rows:
        details_table.add_row(*row)

    console.print(details_table)
    if len(collection) > limit:
        console.print(
            f"[{palette.get('info', 'dim')}]Showing first {limit} of {len(collection)} files. Use --limit to show more or save the full report.[/]"
        )
