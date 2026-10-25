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
import time
from typing import Annotated, Optional

import typer
import pathlib

logger = logging.getLogger(__name__)


def export_dorsal_collection(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The unique ID of the collection to export.")],
    output_dir: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory to save the export file. Defaults to ~/.dorsal/export/.",
            file_okay=False,
            dir_okay=True,
            writable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output a JSON summary of the export operation."),
    ] = False,
):
    """
    Export all file records from a remote collection to a local file.
    """
    from rich.markup import escape

    from dorsal.api.collection import export_collection
    from dorsal.common.cli import (
        get_error_console,
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        EXIT_CODE_SUCCESS,
        print_json_output,
    )
    from dorsal.common import constants
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    error_console = get_error_console()
    palette = ctx.obj["palette"]
    icons = ctx.obj.get("icons", {})

    if output_dir:
        save_dir = output_dir
    else:
        save_dir = constants.CLI_EXPORTS_DIR

    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"Could not create output directory at '{save_dir}': {e}",
        )

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_file = save_dir / f"{collection_id}-{timestamp}.json.gz"

    if not json_output:
        error_console.print(f"Exporting collection '[bold]{escape(collection_id)}[/]'")

    start_time = time.perf_counter()

    try:
        export_collection(
            collection_id=collection_id,
            output_path=output_file,
            console=error_console,
            palette=palette,
        )

        duration = time.perf_counter() - start_time

        if json_output:
            summary = {
                "success": True,
                "collection_id": collection_id,
                "output_path": str(output_file),
                "duration_seconds": duration,
            }
            print_json_output(summary, console)
        else:
            console.print(
                f"[{palette.get('success')}]{icons.get('success', '')}Export complete in {duration:.2f}s:[/] "
                f"[{palette.get('primary_value')}]{escape(str(output_file))}[/]"
            )

    except typer.Exit:
        raise
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection export'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
