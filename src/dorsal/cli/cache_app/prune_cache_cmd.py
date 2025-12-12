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
from typing import Annotated
import json

logger = logging.getLogger(__name__)


def prune_cache(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the prune summary as a raw JSON object."),
    ] = False,
):
    """
    Scans the cache and removes stale records.

    A record is considered stale if the file it points to no longer exists
    or has been modified since it was cached.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.session import get_shared_cache

    console = get_rich_console()
    palette = ctx.obj["palette"]

    try:
        with console.status("Pruning stale records from cache..."):
            cache = get_shared_cache()
            pruned_count, total_records = cache.prune()

        result = {
            "total_records_scanned": total_records,
            "stale_records_removed": pruned_count,
        }

        if json_output:
            console.print(json.dumps(result))
            exit_cli()

        if pruned_count > 0:
            message = f"✅ Prune complete. Removed {pruned_count} of {total_records} records."
            style = palette.get("success", "green")
        else:
            message = f"✅ Prune complete. No stale records found out of {total_records} scanned."
            style = palette.get("info", "dim")

        console.print(f"[{style}]{message}[/]")

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to prune cache.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while pruning the cache: {err}",
        )
