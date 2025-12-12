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
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def get_cache_path(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the path as a raw JSON object."),
    ] = False,
):
    """
    Prints the absolute path to the cache database file.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.session import get_shared_cache

    console = get_rich_console()

    try:
        cache = get_shared_cache()
        db_path_str = str(cache.db_path.resolve())

        if json_output:
            console.print(json.dumps({"path": db_path_str}))
        else:
            console.print(db_path_str)
    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to retrieve cache path.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while getting cache path: {err}",
        )
