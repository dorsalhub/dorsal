# dorsal/cli/local_app/report_cmd.py

from __future__ import annotations

import logging
import typer
import pathlib
import datetime
from typing import Annotated, Optional

from rich.markup import escape

from dorsal.common.exceptions import DorsalError
from dorsal.common import constants
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    exit_cli,
    determine_use_cache_value,
)

logger = logging.getLogger(__name__)


def report_target(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            help="The path to the local file or directory to generate a report for.",
        ),
    ],
    output: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Custom path to save the HTML report. If omitted, a default path in ~/.dorsal/scan/ will be used.",
            dir_okay=True,
            file_okay=True,
            writable=True,
            resolve_path=True,
        ),
    ] = None,
    template: Annotated[
        str,
        typer.Option("--template", "-t", help="Name or path of the report template to use."),
    ] = "default",
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="[Dir Only] Scan subdirectories recursively.",
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
    open_report: Annotated[
        bool,
        typer.Option(
            "--open",
            help="Open the report in the default web browser after generation.",
        ),
    ] = False,
):
    """
    Generates a self-contained, interactive HTML report for a local file or directory.
    """
    # Keep heavy backend API imports lazy to speed up CLI boot time
    from dorsal.api.file import generate_html_file_report, generate_html_directory_report

    console = get_rich_console()
    palette = ctx.obj.get("palette", {})

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache cannot be used together.",
        )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)
    is_dir = path.is_dir()

    if path.is_file() and recursive:
        console.print(
            "⚠️ [yellow]Warning:[/] Directory-specific flags (--recursive) are ignored when reporting on a single file.",
            style=palette.get("warning", "yellow"),
        )

    final_output_path: pathlib.Path
    if output:
        final_output_path = output
        if output.is_dir():
            prefix = "dir-" if is_dir else ""
            final_output_path = output / f"{prefix}{path.stem}_report.html"
    else:
        constants.CLI_SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = path.name.replace(" ", "_")
        prefix = "dir-" if is_dir else ""
        final_output_path = constants.CLI_SCAN_REPORTS_DIR / f"{prefix}{safe_name}-{timestamp}.html"

    with console.status(f"📄 Generating HTML report for '[bold]{escape(path.name)}[/]'..."):
        try:
            if is_dir:
                generate_html_directory_report(
                    dir_path=str(path),
                    output_path=str(final_output_path),
                    template=template,
                    use_cache=use_cache_value,
                    recursive=recursive,
                )
            else:
                generate_html_file_report(
                    file_path=str(path),
                    output_path=str(final_output_path),
                    template=template,
                    use_cache=use_cache_value,
                )
        except DorsalError as err:
            exit_cli(code=EXIT_CODE_ERROR, message=f"Failed to generate report: {err}")
        except Exception as err:
            logger.exception("Unexpected error generating HTML report.")
            exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")

    console.print(f"✅ Report saved successfully to: [{palette.get('primary_value', 'cyan')}]{final_output_path}[/]")

    if open_report:
        try:
            import webbrowser

            webbrowser.open(f"file://{final_output_path.resolve()}")
        except Exception as err:
            console.print(f"⚠️  Could not automatically open the report: {err}", style=palette.get("warning", "yellow"))
