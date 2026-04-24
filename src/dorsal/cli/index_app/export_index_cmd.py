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

import typer
import pathlib
import logging
import datetime
from typing import Annotated, Literal, Optional, cast

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeRemainingColumn,
)

logger = logging.getLogger(__name__)


def export_index_cmd(
    ctx: typer.Context,
    output: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Path to save the exported dorsal index file. Defaults to the '.dorsal/export' directory.",
            writable=True,
            resolve_path=True,
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            help="Output format ('json' or 'json.gz'). If not provided, it's inferred from the output file extension.",
            case_sensitive=False,
        ),
    ] = None,
    no_records: Annotated[
        bool,
        typer.Option(
            "--no-records",
            help="Exclude full metadata records from the export to save space.",
        ),
    ] = False,
):
    """
    Exports the full contents of the local dorsal index to a file.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common import constants
    from dorsal.api.index import export

    console = get_rich_console()

    palette = ctx.obj["palette"]
    include_records = not no_records

    output_path = output
    if not output_path:
        try:
            constants.CLI_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = constants.CLI_EXPORTS_DIR / f"dorsal-index-export-{timestamp}.json.gz"
        except Exception as e:
            logger.error(f"Failed to create automatic export directory: {e}")
            return exit_cli(
                code=EXIT_CODE_ERROR,
                message=f"Could not create export directory at {constants.CLI_EXPORTS_DIR}.",
            )

    if not format:
        suffix = output_path.suffix.lower()
        if suffix == ".gz" and output_path.stem.endswith(".json"):
            format = "json.gz"
        elif suffix == ".json":
            format = "json"
        else:
            if output:
                console.print(
                    f"[{palette.get('info', 'dim')}]Info:[/] No valid format specified or inferred. Defaulting to 'json.gz'."
                )
                output_path = output.with_suffix(".json.gz")
                console.print(f"[{palette.get('info', 'dim')}]Info:[/] Output will be saved to: {output_path}")
            format = "json.gz"

    if format not in ["json", "json.gz"]:
        return exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"Invalid format '{format}'. Must be one of 'json' or 'json.gz'.",
        )

    literal_format = cast(Literal["json", "json.gz"], format)
    try:
        # Build the Rich Progress Context using Theme Palettes and the correct columns
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(
                style=palette.get("progress_bar", "red"), complete_style=palette.get("progress_percentage", "green")
            ),
            MofNCompleteColumn(),  # <-- This renders the "1,000 / 21,129"
            TaskProgressColumn(),  # <-- This renders the "5%"
            TimeRemainingColumn(),  # <-- This renders the ETA
            console=console,
        ) as progress:
            task_id = progress.add_task(f"Exporting dorsal index to '{output_path.name}'...", total=None)

            def _progress_cb(current: int, total: int):
                progress.update(task_id, completed=current, total=total)

            count = export(
                output_path=output_path,
                format=literal_format,
                include_records=include_records,
                progress_callback=_progress_cb,
            )

        console.print(
            f"\n[{palette.get('success', 'green')}]✅ Successfully exported {count:,} records to '{output_path}'[/]"
        )

    except (IOError, ValueError) as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Export failed: {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred during dorsal index export.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
