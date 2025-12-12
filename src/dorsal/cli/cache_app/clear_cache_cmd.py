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

logger = logging.getLogger(__name__)


def clear_cache(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Bypass the confirmation prompt and clear the cache immediately.",
        ),
    ] = False,
):
    """
    Deletes the entire cache database file, permanently removing all cached data.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.session import get_shared_cache, clear_shared_cache

    console = get_rich_console()

    palette = ctx.obj["palette"]

    try:
        cache = get_shared_cache()
        cache_path_str = str(cache.db_path.resolve())

        if not yes:
            typer.confirm(
                f"Are you sure you want to delete the entire cache at {cache_path_str}?\nThis action cannot be undone.",
                abort=True,
            )

        with console.status("Clearing cache..."):
            cache.clear()
            clear_shared_cache()

        success_msg = f"[{palette.get('success', 'green')}]✅ Cache cleared successfully.[/]"
        console.print(success_msg)

    except typer.Abort:
        console.print("Cache clearing aborted.")
        exit_cli()
    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to clear cache.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while clearing the cache: {err}",
        )
