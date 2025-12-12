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

import logging
import typer
import pathlib
import datetime
import json
from typing import Annotated, Optional

from dorsal.common import constants
from dorsal.cli.views.file import create_file_info_panel
from dorsal.common.cli import (
    exit_cli,
    EXIT_CODE_ERROR,
    get_rich_console,
    determine_use_cache_value,
)
from dorsal.file.dorsal_file import LocalFile
from dorsal.api.file import generate_html_file_report

logger = logging.getLogger(__name__)


def scan_file(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The path to the file to scan.",
        ),
    ],
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
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process the file and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
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
            help="Generate a self-contained HTML report to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
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
    template: Annotated[
        str,
        typer.Option(
            "--template",
            "-t",
            help="Name or path of the report template to use.",
            rich_help_panel="Output Options",
        ),
    ] = "default",
):
    """
    Scans and displays the full metadata for a file, with options to save reports.
    """
    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache cannot be used together.",
        )

    if skip_cache and overwrite_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --skip-cache and --overwrite-cache cannot be used together.",
        )

    if json_output and report:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --json (stdout) and --report (HTML) flags are not compatible.",
        )

    console = get_rich_console()
    if output_path and not (save or report):
        if str(output_path).lower().endswith(".json"):
            save = True
        if str(output_path).lower().endswith(".html"):
            report = True
        if not (save or report):
            console.print(
                f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified, but no report"
                f" type was requested. (Did you forget --save or --report?)",
                style="yellow",
            )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)
    palette = ctx.obj["palette"]

    if not json_output:
        console.print(f"📄 Scanning metadata for [{palette['primary_value']}]{path.name}[/]")

    try:
        local_file = LocalFile(file_path=str(path), use_cache=use_cache_value, overwrite_cache=overwrite_cache)

        record_dict = local_file.to_dict(mode="json")
        record_dict["local_filesystem"] = {
            "full_path": local_file._file_path,
            "date_created": (local_file.date_created.isoformat() if hasattr(local_file, "date_created") else None),
            "date_modified": (local_file.date_modified.isoformat() if hasattr(local_file, "date_modified") else None),
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
            _save_json_report(
                ctx=ctx,
                record=record_dict,
                original_path=path,
                output_path=output_path,
                palette=palette,
            )

        if report:
            _save_html_report(
                local_file=local_file,
                original_path=path,
                output_path=output_path,
                palette=palette,
                template=template,
            )

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception(f"CLI 'scan' command failed while processing {path}.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")


def _get_final_path(original_path: pathlib.Path, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            return output_path / f"{original_path.stem}_report{suffix}"
        else:
            return output_path

    constants.CLI_SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_filename = original_path.name.replace(" ", "_")
    return constants.CLI_SCAN_REPORTS_DIR / f"{safe_filename}-{timestamp}{suffix}"


def _save_json_report(
    ctx: typer.Context,
    record: dict,
    original_path: pathlib.Path,
    output_path: Optional[pathlib.Path],
    palette: dict,
):
    """Saves the JSON scan report to a specified or default path."""
    console = get_rich_console()

    num_reports = ctx.params.get("save", 0) + ctx.params.get("report", 0)
    if output_path and not output_path.is_dir() and num_reports > 1:
        console.print(
            "⚠️ [yellow]Warning:[/] Both --save and --report are specified, but --output"
            " is a single file. Reports may overwrite each other.",
            style="yellow",
        )

    final_path = _get_final_path(original_path, output_path, ".json")

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str, ensure_ascii=False)

        if not ctx.params.get("json_output"):
            console.print(f"✅ JSON report saved to: [{palette.get('primary_value')}]{final_path}[/]")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        console.print(f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style="yellow")


def _save_html_report(
    local_file: LocalFile,
    original_path: pathlib.Path,
    output_path: Optional[pathlib.Path],
    palette: dict,
    template: str,
):
    """Handles the logic for generating and saving the HTML report."""
    console = get_rich_console()
    final_path = _get_final_path(original_path, output_path, ".html")

    try:
        with console.status(f"📄 Generating HTML report for '[bold]{original_path.name}[/]'..."):
            generate_html_file_report(
                file_path=local_file._file_path,
                local_file=local_file,
                output_path=str(final_path),
                template=template,
            )
        console.print(f"✅ HTML report saved to: [{palette.get('primary_value')}]{final_path}[/]")

    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}")
        console.print(f"⚠️ Could not generate HTML report. Error: {e}", style="yellow")
