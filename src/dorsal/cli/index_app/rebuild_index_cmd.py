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

import json
import logging
import typer
from typing import Annotated

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


def rebuild_index_cmd(
    ctx: typer.Context,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            "-b",
            help="The number of records to process and commit per batch.",
        ),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the result as a raw JSON object."),
    ] = False,
):
    """
    Rebuilds the FTS and EAV search indexes from the compressed cache.

    Use this command after updating your Dorsal version or modifying custom
    extractors to ensure all cached files are fully searchable under the new rules.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.api.index import rebuild

    console = get_rich_console()
    palette = ctx.obj["palette"]

    try:
        if json_output:
            count = rebuild(batch_size=batch_size)
            result = {
                "success": True,
                "total_records_rebuilt": count,
            }
            console.print(json.dumps(result, indent=2))
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(
                style=palette.get("progress_bar", "blue"),
                complete_style=palette.get("progress_percentage", "green"),
            ),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Rebuilding search index...", total=None)

            def _progress_cb(current: int, total: int):
                progress.update(task_id, completed=current, total=total)

            count = rebuild(progress_callback=_progress_cb, batch_size=batch_size)

        console.print(
            f"\n[{palette.get('success', 'green')}]✅ Successfully rebuilt search indexes for {count:,} records.[/]"
        )

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("An unexpected error occurred during index rebuild.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred while rebuilding the index: {e}")
