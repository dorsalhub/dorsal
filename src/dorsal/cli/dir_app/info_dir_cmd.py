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
import datetime
import json
import logging
import pathlib
from typing import Annotated, TYPE_CHECKING, Optional

from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
import typer

from dorsal.common import constants
from dorsal.file.utils.size import human_filesize

if TYPE_CHECKING:
    from dorsal.api.file import _DirectoryInfoResult

logger = logging.getLogger(__name__)


def info_directory(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="The directory path to analyze.",
        ),
    ],
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive/--no-recursive",
            "-r/-R",
            help="Scan subdirectories recursively.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
    media_type: Annotated[
        bool,
        typer.Option(
            "--media-type",
            "-m",
            help="Include Media Type summary table. Reduces scan speed.",
            rich_help_panel="Scan Options",
        ),
    ] = False,
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
):
    """
    Displays summary of files in a directory.
    """
    from dorsal.api.file import get_directory_info
    from dorsal.common.cli import EXIT_CODE_ERROR, get_rich_console, exit_cli

    console = get_rich_console()
    palette = ctx.obj["palette"]

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not json_output:
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style="yellow",
                )

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
                console.print(f"[{palette['warning']}]⚠️ No files found or accessible in '{escape(str(path))}'.[/]")
            exit_cli()

        if json_output:
            console.print(json.dumps(dir_info, indent=2, default=str, ensure_ascii=False))
            exit_cli()

        overall = dir_info["overall"]
        duration_val = overall["time_taken_seconds"]
        duration_str = f"{duration_val:.2f} seconds" if duration_val >= 0.01 else "< 0.01 seconds"
        summary_table = Table.grid(expand=False)
        summary_table.add_column(justify="right", style=palette["key"], width=24)
        summary_table.add_column(justify="left", style=palette["primary_value"])
        summary_table.add_row("Total File Count:", f"{overall['total_files']:,}")
        summary_table.add_row("Total Directories:", f"{overall['total_dirs']:,}")
        summary_table.add_row("Hidden Files:", f"{overall['hidden_files']:,}")
        summary_table.add_row("Total Size:", human_filesize(overall["total_size"]))
        summary_table.add_row("Scan Duration:", duration_str)
        summary_table.add_row()
        summary_table.add_row("Average File Size:", human_filesize(overall["avg_size"]))
        largest_path = escape(overall["largest_file"]["path"]) if overall["largest_file"]["path"] else "N/A"
        smallest_path = escape(overall["smallest_file"]["path"]) if overall["smallest_file"]["path"] else "N/A"
        summary_table.add_row(
            "Largest File:",
            f"{largest_path} ({human_filesize(overall['largest_file']['size'])})",
        )
        summary_table.add_row(
            "Smallest File:",
            f"{smallest_path} ({human_filesize(overall['smallest_file']['size'])})",
        )
        summary_table.add_row()

        def format_date_row(data: dict):
            path = escape(data["path"]) if data["path"] else "N/A"
            date_str = "N/A"
            if data["date"]:
                date_obj = datetime.datetime.fromisoformat(data["date"])
                date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            return f"{date_str} ({path})"

        summary_table.add_row("Newest Modified File:", format_date_row(overall["newest_mod_file"]))
        summary_table.add_row("Oldest Modified File:", format_date_row(overall["oldest_mod_file"]))
        summary_table.add_row("Oldest Creation Date:", format_date_row(overall["oldest_creation_file"]))
        permissions = overall.get("permissions", {})
        if permissions:
            summary_table.add_row()
            summary_table.add_row("Executable Files:", f"{permissions.get('executable', 0):,}")
            summary_table.add_row("Read-Only Files:", f"{permissions.get('read_only', 0):,}")

        console.print(f"📊 Summary of [{palette['primary_value']}]{escape(str(path))}[/]")
        console.print(
            Panel(
                summary_table,
                title=f"[{palette['panel_title']}]Directory Summary[/]",
                expand=False,
                border_style=palette["panel_border"],
            )
        )

        if media_type and dir_info["by_type"]:
            by_type_table = Table(
                title="Media Type Breakdown",
                show_header=True,
                header_style=palette["table_header"],
                expand=False,
            )
            by_type_table.add_column("Media Type", style=palette["primary_value"], ratio=55)
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
                dir_info=dir_info,
                source_path=path,
                output_path=output_path,
                palette=palette,
                json_to_stdout=json_output,
            )

    except (FileNotFoundError, NotADirectoryError) as e:
        exit_cli(code=EXIT_CODE_ERROR, message=str(e))
    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("CLI 'info' command failed.")
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))


def _get_final_path(source_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            dir_name = source_path.name
            return output_path / f"stats-{dir_name}{suffix}"
        else:
            return output_path

    constants.CLI_STATS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_name = source_path.name.replace(" ", "_")
    return constants.CLI_STATS_REPORTS_DIR / f"stats-{dir_name}-{timestamp}{suffix}"


def _save_json_report(
    dir_info: _DirectoryInfoResult,
    source_path: pathlib.Path,
    output_path: Optional[pathlib.Path],
    palette: dict,
    json_to_stdout: bool,
):
    """Saves the dir_info dictionary to a JSON file."""
    from dorsal.common.cli import EXIT_CODE_ERROR, get_rich_console, exit_cli

    console = get_rich_console()

    final_path = _get_final_path(source_path, output_path, ".json")

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(dir_info, f, default=str, indent=2, ensure_ascii=False)

        if not json_to_stdout:
            console.print(f"✅ JSON report saved to: [{palette.get('primary_value')}]{final_path}[/]")
    except IOError as e:
        logger.exception(f"Failed to write to output file: {final_path}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {e}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        console.print(f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style="yellow")
