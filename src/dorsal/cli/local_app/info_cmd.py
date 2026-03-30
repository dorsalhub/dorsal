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

import datetime
import json
import logging
import pathlib
import os
from typing import Annotated, Any, TYPE_CHECKING, Optional

from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
from rich.text import Text
from rich.console import Group
import typer

from dorsal.common import constants
from dorsal.common.cli import EXIT_CODE_ERROR, get_rich_console, exit_cli
from dorsal.cli.themes import UIContext
from dorsal.cli.themes.borders import get_borders
from rich.box import Box

if TYPE_CHECKING:
    from dorsal.api.file import _DirectoryInfoResult
    from rich.console import Console

logger = logging.getLogger(__name__)


def info_target(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            help="The file or directory path to analyze.",
        ),
    ],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output a raw JSON object to stdout for scripting.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Save the JSON report to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "-o",
            "--output",
            help="Custom path to save the JSON report (e.g., 'info.json').",
            dir_okay=True,
            file_okay=True,
            writable=True,
            resolve_path=True,
            rich_help_panel="Output Options",
        ),
    ] = None,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive/--no-recursive",
            "-r/-R",
            help="[Dir Only] Scan subdirectories recursively.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
    media_type: Annotated[
        bool,
        typer.Option(
            "--media-type",
            "-m",
            help="[Dir Only] Include Media Type summary table. Reduces scan speed.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
) -> None:
    """
    Displays a high-level, fast summary of a local file or directory without hashing.
    """
    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    icons = ui_context["icons"]

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not json_output:
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style=palette.get("warning", "yellow"),
                )

    if path.is_file():
        if recursive or media_type:
            if not json_output:
                console.print(
                    "⚠️ [yellow]Warning:[/] Directory-specific flags (--recursive, --media-type) are ignored when analyzing a single file.",
                    style=palette.get("warning", "yellow"),
                )
        _process_file_info(
            path=path,
            json_output=json_output,
            save=save,
            output_path=output_path,
            palette=palette,
            borders=borders,
            icons=icons,
            console=console,
        )
    else:
        _process_dir_info(
            path=path,
            recursive=recursive,
            media_type=media_type,
            json_output=json_output,
            save=save,
            output_path=output_path,
            palette=palette,
            borders=borders,
            icons=icons,
            console=console,
        )


def _process_file_info(
    path: pathlib.Path,
    json_output: bool,
    save: bool,
    output_path: Optional[pathlib.Path],
    palette: dict[str, str],
    borders: Box,
    icons: dict[str, str],
    console: Console,
) -> None:
    from dorsal.file.utils.size import human_filesize
    from dorsal.file.utils.infer_mediatype import get_media_type

    try:
        file_stat = path.stat()
        mod_date = datetime.datetime.fromtimestamp(file_stat.st_mtime).astimezone()
        cre_date = datetime.datetime.fromtimestamp(file_stat.st_ctime).astimezone()

        file_extension = path.suffix.lower() or "No Extension"
        media_type = get_media_type(str(path), file_extension)

        file_info: dict[str, Any] = {
            "name": path.name,
            "path": str(path),
            "size_bytes": file_stat.st_size,
            "media_type": media_type,
            "date_modified": mod_date.isoformat(),
            "date_created": cre_date.isoformat(),
            "permissions": {
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
                "executable": os.access(path, os.X_OK),
            },
            "is_symlink": path.is_symlink(),
        }

        if json_output:
            console.print(json.dumps(file_info, indent=2, ensure_ascii=False))
            exit_cli()

        summary_table = Table.grid(expand=False, padding=(0, 1))
        summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=20)
        summary_table.add_column(justify="left", style=palette.get("primary_value", "cyan"))

        summary_table.add_row("Filename:", escape(file_info["name"]))
        if file_info["is_symlink"]:
            try:
                target = path.readlink()
                summary_table.add_row("Symlink Target:", f"[dim italic]→ {escape(str(target))}[/]")
            except OSError:
                summary_table.add_row("Symlink Target:", "[dim italic](unreadable)[/]")

        summary_table.add_row("Media Type:", str(file_info["media_type"]))
        summary_table.add_row("Size:", f"{human_filesize(file_info['size_bytes'])} ({file_info['size_bytes']:,} bytes)")
        summary_table.add_row()

        summary_table.add_row("Date Modified:", mod_date.strftime("%Y-%m-%d %H:%M:%S"))
        summary_table.add_row("Date Created:", cre_date.strftime("%Y-%m-%d %H:%M:%S"))
        summary_table.add_row()

        perms = []
        if file_info["permissions"]["readable"]:
            perms.append("Read")
        if file_info["permissions"]["writable"]:
            perms.append("Write")
        if file_info["permissions"]["executable"]:
            perms.append("Execute")
        summary_table.add_row("Permissions:", ", ".join(perms) if perms else "None")

        console.print(
            f"{icons.get('chart', '📊 ')}Summary of [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]"
        )

        is_none_style = borders == get_borders("none")
        title_text = f"[{palette.get('panel_title', 'bold default')}]{icons.get('file', '')}File Summary[/]"

        if is_none_style:
            console.print(summary_table)
        else:
            console.print(
                Panel(
                    summary_table,
                    title=title_text,
                    expand=False,
                    border_style=palette.get("panel_border", "blue"),
                    box=borders,
                )
            )

        if save:
            _save_json_report(
                info_data=file_info,
                source_path=path,
                output_path=output_path,
                palette=palette,
                is_dir=False,
                json_to_stdout=json_output,
                console=console,
            )

    except typer.Exit:
        raise

    except Exception as err:
        logger.exception("CLI 'info' command failed on file.")
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))


def _process_dir_info(
    path: pathlib.Path,
    recursive: bool,
    media_type: bool,
    json_output: bool,
    save: bool,
    output_path: Optional[pathlib.Path],
    palette: dict[str, str],
    borders: Box,
    icons: dict[str, str],
    console: Console,
) -> None:
    from dorsal.api.file import get_directory_info
    from dorsal.file.utils.size import human_filesize

    progress_console = None if json_output else console
    try:
        dir_info = get_directory_info(
            dir_path=str(path),
            recursive=recursive,
            media_type=media_type,
            progress_console=progress_console,
            palette=palette,
        )

        successfully_processed = dir_info["overall"]["total_size"] > 0 or dir_info["overall"]["total_files"] > 0
        if not dir_info or not successfully_processed:
            if not json_output:
                console.print(
                    f"[{palette.get('warning', 'yellow')}]⚠️ No files found or accessible in '{escape(str(path))}'.[/]"
                )
            exit_cli()

        if json_output:
            console.print(json.dumps(dir_info, indent=2, default=str, ensure_ascii=False))
            exit_cli()

        overall: dict[str, Any] = dir_info["overall"]
        duration_val = overall["time_taken_seconds"]
        duration_str = f"{duration_val:.2f} seconds" if duration_val >= 0.01 else "< 0.01 seconds"

        summary_table = Table.grid(expand=False, padding=(0, 2))
        summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=24)
        summary_table.add_column(justify="left", style=palette.get("primary_value", "cyan"))

        summary_table.add_row("Total File Count:", f"{overall['total_files']:,}")
        summary_table.add_row("Total Directories:", f"{overall['total_dirs']:,}")
        summary_table.add_row("Hidden Files:", f"{overall['hidden_files']:,}")
        summary_table.add_row("Total Size:", human_filesize(overall["total_size"]))
        summary_table.add_row("Scan Duration:", duration_str)
        summary_table.add_row()

        summary_table.add_row("Average File Size:", human_filesize(overall["avg_size"]))
        largest_path = escape(overall["largest_file"]["path"]) if overall["largest_file"]["path"] else "N/A"
        smallest_path = escape(overall["smallest_file"]["path"]) if overall["smallest_file"]["path"] else "N/A"
        summary_table.add_row("Largest File:", f"{largest_path} ({human_filesize(overall['largest_file']['size'])})")
        summary_table.add_row("Smallest File:", f"{smallest_path} ({human_filesize(overall['smallest_file']['size'])})")
        summary_table.add_row()

        def format_date_row(data: dict):
            p = escape(data["path"]) if data["path"] else "N/A"
            d_str = "N/A"
            if data["date"]:
                date_obj = datetime.datetime.fromisoformat(data["date"])
                d_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            return f"{d_str} ({p})"

        summary_table.add_row("Newest Modified File:", format_date_row(overall["newest_mod_file"]))
        summary_table.add_row("Oldest Modified File:", format_date_row(overall["oldest_mod_file"]))
        summary_table.add_row("Oldest Creation Date:", format_date_row(overall["oldest_creation_file"]))

        permissions = overall.get("permissions", {})
        if permissions:
            summary_table.add_row()
            summary_table.add_row("Executable Files:", f"{permissions.get('executable', 0):,}")
            summary_table.add_row("Read-Only Files:", f"{permissions.get('read_only', 0):,}")

        console.print(
            f"{icons.get('chart', '📊 ')}Summary of [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]"
        )

        is_none_style = borders == get_borders("none")
        title_text = f"[{palette.get('panel_title', 'bold default')}]{icons.get('folder', '')}Directory Summary[/]"

        if is_none_style:
            console.print(summary_table)
        else:
            console.print(
                Panel(
                    summary_table,
                    title=title_text,
                    expand=False,
                    border_style=palette.get("panel_border", "blue"),
                    box=borders,
                )
            )

        if media_type and dir_info["by_type"]:
            by_type_table = Table(
                title=f"[{palette.get('table_header', 'bold')}]{icons.get('info', '')}Media Type Breakdown[/]",
                show_header=True,
                header_style=palette.get("table_header", "bold"),
                box=borders,
                expand=False,
            )

            if is_none_style:
                by_type_table.padding = (0, 1)

            by_type_table.add_column("Media Type", style=palette.get("primary_value", "cyan"), ratio=55)
            by_type_table.add_column("Count", justify="right", ratio=15)
            by_type_table.add_column("Total Size", justify="right", ratio=15)
            by_type_table.add_column("% of Total", justify="right", ratio=15)
            for item in dir_info["by_type"]:
                by_type_table.add_row(
                    item["media_type"],
                    f"{item['count']:,}",
                    human_filesize(item["total_size"]),
                    f"{item['percentage']:.2f}%",
                )
            console.print(by_type_table)

        if save:
            _save_json_report(
                info_data=dir_info,
                source_path=path,
                output_path=output_path,
                palette=palette,
                is_dir=True,
                json_to_stdout=json_output,
                console=console,
            )

    except (FileNotFoundError, NotADirectoryError) as e:
        exit_cli(code=EXIT_CODE_ERROR, message=str(e))
    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("CLI 'info' command failed on directory.")
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))


def _get_final_path(
    source_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str, is_dir: bool
) -> pathlib.Path:
    if output_path:
        if output_path.is_dir():
            prefix = "info-dir-" if is_dir else "info-file-"
            return output_path / f"{prefix}{source_path.name}{suffix}"
        else:
            return output_path

    constants.CLI_STATS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = source_path.name.replace(" ", "_")
    prefix = "stats-dir-" if is_dir else "stats-file-"
    return constants.CLI_STATS_REPORTS_DIR / f"{prefix}{safe_name}-{timestamp}{suffix}"


def _save_json_report(
    info_data: dict | _DirectoryInfoResult,
    source_path: pathlib.Path,
    output_path: Optional[pathlib.Path],
    palette: dict,
    is_dir: bool,
    json_to_stdout: bool,
    console,
) -> None:
    final_path = _get_final_path(source_path, output_path, ".json", is_dir=is_dir)

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(info_data, f, default=str, indent=2, ensure_ascii=False)

        if not json_to_stdout:
            console.print(f"✅ JSON report saved to: [{palette.get('primary_value', 'cyan')}]{final_path}[/]")
    except IOError as e:
        logger.exception(f"Failed to write to output file: {final_path}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {e}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        console.print(
            f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style=palette.get("warning", "yellow")
        )
