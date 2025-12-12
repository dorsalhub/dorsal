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

import json
import logging
import time
import pathlib
import datetime
import re
from typing import Annotated, Literal, Optional

from rich.panel import Panel
from rich.table import Table
from rich.markup import escape
import typer

from dorsal.api.file import find_duplicates
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    exit_cli,
    determine_use_cache_value,
)
from dorsal.common import constants

logger = logging.getLogger(__name__)


DuplicateMode = Literal["hybrid", "quick", "sha256"]


def duplicates_dir(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="The directory path to scan for duplicates.",
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
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            help="The number of duplicate sets to display.",
            rich_help_panel="Scan Options",
        ),
    ] = 5,
    min_size: Annotated[
        str,
        typer.Option(
            "--min-size",
            help="Only find duplicates larger than this size (e.g., '1MB', '500KB').",
            rich_help_panel="Scan Options",
        ),
    ] = "0",
    max_size: Annotated[
        str | None,
        typer.Option(
            "--max-size",
            help="Only find duplicates smaller than this size (e.g., '1GB').",
            rich_help_panel="Scan Options",
        ),
    ] = None,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Path to save the full JSON report (e.g., 'duplicates.json').",
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
            help="Save the full JSON report to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the full duplicate report as a raw JSON object to stdout for scripting.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    hybrid: Annotated[
        bool,
        typer.Option(
            "--hybrid",
            help="Use hybrid mode (default): fast initial scan with definitive SHA-256 verification.",
            rich_help_panel="Hashing Options",
        ),
    ] = False,
    quick: Annotated[
        bool,
        typer.Option(
            "--quick",
            "-q",
            help="Use QUICK hash only. Fastest, but may have rare false positives.",
            rich_help_panel="Hashing Options",
        ),
    ] = False,
    sha256: Annotated[
        bool,
        typer.Option(
            "--sha256",
            help="Use SHA-256 hash only. Slower, but provides definitive results.",
            rich_help_panel="Hashing Options",
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
            help="Bypass the local cache and re-calculate all hashes, overriding any global setting to enable it.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
):
    """
    Finds and reports files with identical content hashes.
    """
    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]
    progress_console = None if json_output else console

    start_time = time.perf_counter()

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache flags cannot be used together.",
        )

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not output_path.is_dir():
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style="yellow",
                )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    mode_flags = [hybrid, quick, sha256]
    if sum(mode_flags) > 1:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Please specify only one hashing mode: --hybrid, --quick, or --sha256.",
        )

    mode: DuplicateMode = "hybrid"
    if quick:
        mode = "quick"
    elif sha256:
        mode = "sha256"

    if not json_output:
        console.print(f"✨ Searching for duplicate files in [{palette['primary_value']}]{escape(str(path))}[/]")
        if mode == "quick":
            console.print(
                f"[{palette['info']}]Mode: Quick Hash. Results are based on file sampling and may contain rare false positives.[/]"
            )
        elif mode == "sha256":
            console.print(
                f"[{palette['info']}]Mode: Secure Hash. All files will be fully read for maximum accuracy.[/]"
            )
        else:
            console.print(f"[{palette['info']}]Mode: Hybrid. Using fast scan with secure verification.[/]")

    try:
        results = find_duplicates(
            path=path,
            recursive=recursive,
            min_size=min_size,
            max_size=max_size,
            mode=mode,
            progress_console=progress_console,
            palette=palette,
            use_cache=use_cache_value,
        )

        duration = time.perf_counter() - start_time

        results["duration_seconds"] = duration
        if "total_sets" not in results:
            results["total_sets"] = 0
        if "duplicate_sets" not in results:
            results["duplicate_sets"] = []
        if "path" not in results:
            results["path"] = str(path)

        if json_output:
            console.print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
            exit_cli()

        if not results or not results.get("duplicate_sets"):
            console.print(f"\n[{palette['success']}]✅ No duplicate files found in {duration:.3f} seconds.[/]")
            exit_cli()

        total_sets = results["total_sets"]
        hashes_from_cache = results.get("hashes_from_cache", 0)
        cache_info_str = (
            f" ([{palette.get('success', 'green')}]{hashes_from_cache} hashes from cache[/])"
            if hashes_from_cache > 0
            else ""
        )
        console.print(
            f"\n⚠️ Found [{palette['warning']}]{total_sets}[/] set(s) of duplicate files{cache_info_str} in {duration:.3f} seconds."
        )

        if total_sets > 0 and limit > 0:
            console.print(f"\nDisplaying the {min(limit, total_sets)} largest duplicate sets.")

        sets_to_display = results["duplicate_sets"][:limit]

        for i, dupe_set in enumerate(sets_to_display):
            size_str = dupe_set["file_size"]
            hash_str = dupe_set.get("hash", "N/A")
            hash_type = dupe_set.get("hash_type", "N/A").upper()

            title_base = f"Duplicate Set {i + 1} of {total_sets}"
            size_info = f"Size: [{palette['success']}]{size_str}[/] (each)"
            title = f"{title_base} | {size_info}"

            hash_info_body = f"[{palette['info']}]{hash_type}: {hash_str}[/]"

            paths_table = Table.grid(padding=(0, 1, 0, 3))
            paths_table.add_column(style=palette["primary_value"])
            for p in dupe_set["paths"]:
                paths_table.add_row(f"📄 {escape(p)}")

            content_grid = Table.grid(padding=(0, 0, 1, 0))
            content_grid.add_row(hash_info_body)
            content_grid.add_row(paths_table)

            console.print(
                Panel(
                    content_grid,
                    title=title,
                    expand=False,
                    border_style=palette["panel_border"],
                )
            )

        if total_sets > limit and limit > 0:
            console.print(f"\n... and {total_sets - limit} more sets.")

        if save:
            _save_duplicates_report(
                results=results,
                output_path=output_path,
                palette=palette,
                json_output=json_output,
                original_path=path,
            )

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("CLI 'duplicates' command failed.")
        console_in_handler = get_rich_console()
        logger.debug(f"DEBUG: Console ID in error handler: {id(console_in_handler)}")
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))


def _sanitize_path_for_filename(path: str) -> str:
    """Sanitizes a path to be used in a filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", path)
    sanitized = sanitized.strip("_ ")

    return sanitized[:50]


def _get_final_path(source_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            dir_name = _sanitize_path_for_filename(str(source_path.name))
            return output_path / f"{dir_name}{suffix}"
        else:
            return output_path

    constants.CLI_DUPLICATES_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%HM%S")
    dir_name = _sanitize_path_for_filename(str(source_path.name))
    return constants.CLI_DUPLICATES_REPORTS_DIR / f"{dir_name}_{timestamp}{suffix}"


def _save_duplicates_report(
    results: dict,
    output_path: Optional[pathlib.Path],
    palette: dict,
    json_output: bool,
    original_path: pathlib.Path,
):
    console = get_rich_console()

    save_path = _get_final_path(original_path, output_path, ".json")

    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        if not json_output:
            console.print(
                f"[{palette['success']}]✅ Full JSON report saved to:[/] [{palette['primary_value']}]{save_path}[/]"
            )
    except IOError as e:
        logger.error(f"Failed to save duplicates report: {e}")
        if not json_output:
            console.print(f"\n[{palette['error']}]Warning:[/] Could not save report to {save_path}. Error: {e}")
