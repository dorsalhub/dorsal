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

import typer
import pathlib
import datetime
from typing_extensions import Annotated, Optional

from dorsal.common import constants
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    exit_cli,
    determine_use_cache_value,
)
from dorsal.common.exceptions import DorsalError
from dorsal.api.file import generate_html_file_report


def make_file_report(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The path to the local file to generate a report for.",
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
            help="Bypass the local cache and re-process the file.",
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
    Generates a self-contained, interactive HTML report for a single file.
    """
    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache cannot be used together.",
        )

    console = get_rich_console()
    palette = ctx.obj.get("palette", {})

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    final_output_path: pathlib.Path
    if output:
        final_output_path = output
        if output.is_dir():
            final_output_path = output / f"{path.stem}_report.html"
    else:
        constants.CLI_SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_filename = path.name.replace(" ", "_")
        final_output_path = constants.CLI_SCAN_REPORTS_DIR / f"{safe_filename}-{timestamp}.html"

    with console.status(f"Generating report for '[bold]{path.name}[/]'..."):
        try:
            generate_html_file_report(
                file_path=str(path),
                output_path=str(final_output_path),
                template=template,
                use_cache=use_cache_value,
            )
        except DorsalError as err:
            exit_cli(code=EXIT_CODE_ERROR, message=f"Failed to generate report: {err}")
        except Exception as err:
            exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")

    console.print(f"✅ Report saved successfully to: [{palette.get('primary_value')}]{final_output_path}[/]")

    if open_report:
        try:
            import webbrowser

            webbrowser.open(f"file://{final_output_path.resolve()}")
        except Exception as err:
            console.print(f"⚠️  Could not automatically open the report: {err}", style="yellow")
