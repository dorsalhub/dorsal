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

from rich.markup import escape
from rich.text import Text
import typer

from dorsal.common import constants
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    exit_cli,
    print_json_output,
    get_error_console,
)

if TYPE_CHECKING:
    from dorsal.api.file import _DirectoryInfoResult
    from dorsal.cli.themes import UIContext
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
    error_console = get_error_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    warning_prefix = f"[{palette.get('warning', 'yellow')}]Warning:[/]"

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not json_output:
                error_console.print(
                    f"{warning_prefix} --output path '{escape(str(output_path))}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file."
                )

    if path.is_file():
        if recursive or media_type:
            if not json_output:
                error_console.print(
                    f"{warning_prefix} Directory-specific flags (--recursive, --media-type) are ignored when analyzing a single file."
                )
        _process_file_info(
            path=path,
            json_output=json_output,
            save=save,
            output_path=output_path,
            ui_context=ui_context,
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
            ui_context=ui_context,
            console=console,
        )


def _process_file_info(
    path: pathlib.Path,
    json_output: bool,
    save: bool,
    output_path: Optional[pathlib.Path],
    ui_context: UIContext,
    console: Console,
) -> None:
    from dorsal.cli.views.layout import key_values, section
    from dorsal.file.utils.size import human_filesize
    from dorsal.file.utils.infer_mediatype import get_media_type

    palette = ui_context["palette"]

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
            print_json_output(file_info, console)
            exit_cli()

        summary = key_values(ui_context)
        summary.add("Filename", file_info["name"])
        if file_info["is_symlink"]:
            try:
                summary.add("Symlink target", Text(f"→ {path.readlink()}", style="dim italic"))
            except OSError:
                summary.add("Symlink target", Text("(unreadable)", style="dim italic"))

        summary.add("Media type", str(file_info["media_type"]))
        summary.add("Size", f"{human_filesize(file_info['size_bytes'])} ({file_info['size_bytes']:,} bytes)")
        summary.add("Date modified", mod_date.strftime("%Y-%m-%d %H:%M:%S"))
        summary.add("Date created", cre_date.strftime("%Y-%m-%d %H:%M:%S"))

        perms = []
        if file_info["permissions"]["readable"]:
            perms.append("Read")
        if file_info["permissions"]["writable"]:
            perms.append("Write")
        if file_info["permissions"]["executable"]:
            perms.append("Execute")
        summary.add("Permissions", ", ".join(perms) if perms else "None")

        title = f"File summary of [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]"
        console.print(section(title, summary, ui_context))

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
    ui_context: UIContext,
    console: Console,
) -> None:
    from dorsal.api.file import get_directory_info
    from dorsal.cli.views.layout import key_values, section, table
    from dorsal.file.utils.size import human_filesize

    palette = ui_context["palette"]

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
                get_error_console().print(
                    f"[{palette.get('warning', 'yellow')}]No files found or accessible in '{escape(str(path))}'.[/]"
                )
            exit_cli()

        if json_output:
            print_json_output(dir_info, console)
            exit_cli()

        overall: dict[str, Any] = dir_info["overall"]
        duration_val = overall["time_taken_seconds"]
        duration_str = f"{duration_val:.2f} seconds" if duration_val >= 0.01 else "< 0.01 seconds"

        summary = key_values(ui_context)
        summary.add("Total file count", f"{overall['total_files']:,}")
        summary.add("Total directories", f"{overall['total_dirs']:,}")
        summary.add("Hidden files", f"{overall['hidden_files']:,}")
        summary.add("Total size", human_filesize(overall["total_size"]))
        summary.add("Scan duration", duration_str)
        summary.add("Average file size", human_filesize(overall["avg_size"]))
        largest_path = overall["largest_file"]["path"] or "N/A"
        smallest_path = overall["smallest_file"]["path"] or "N/A"
        summary.add("Largest file", f"{largest_path} ({human_filesize(overall['largest_file']['size'])})")
        summary.add("Smallest file", f"{smallest_path} ({human_filesize(overall['smallest_file']['size'])})")

        def format_date_row(data: dict) -> str:
            p = data["path"] or "N/A"
            d_str = "N/A"
            if data["date"]:
                date_obj = datetime.datetime.fromisoformat(data["date"])
                d_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            return f"{d_str} ({p})"

        summary.add("Newest modified file", format_date_row(overall["newest_mod_file"]))
        summary.add("Oldest modified file", format_date_row(overall["oldest_mod_file"]))
        summary.add("Oldest creation date", format_date_row(overall["oldest_creation_file"]))

        permissions = overall.get("permissions", {})
        if permissions:
            summary.add("Executable files", f"{permissions.get('executable', 0):,}")
            summary.add("Read-only files", f"{permissions.get('read_only', 0):,}")

        title = f"Directory summary of [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]"
        console.print(section(title, summary, ui_context))

        if media_type and dir_info["by_type"]:
            by_type_table = table(ui_context, title="Media type breakdown", expand=False)
            by_type_table.add_column("Media type", style=palette.get("primary_value", "cyan"))
            by_type_table.add_column("Count", justify="right")
            by_type_table.add_column("Total size", justify="right")
            by_type_table.add_column("% of total", justify="right")
            for item in dir_info["by_type"]:
                by_type_table.add_row(
                    escape(item["media_type"]),
                    f"{item['count']:,}",
                    human_filesize(item["total_size"]),
                    f"{item['percentage']:.2f}%",
                )
            console.print()
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
    error_console = get_error_console()
    final_path = _get_final_path(source_path, output_path, ".json", is_dir=is_dir)

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(info_data, f, default=str, indent=2, ensure_ascii=False)

        if not json_to_stdout:
            console.print(f"JSON report saved to: [{palette.get('primary_value', 'cyan')}]{escape(str(final_path))}[/]")
    except IOError as e:
        logger.exception(f"Failed to write to output file: {final_path}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {e}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        error_console.print(
            f"[{palette.get('warning', 'yellow')}]Warning:[/] Could not save JSON report to {escape(str(final_path))}. Error: {escape(str(e))}"
        )
