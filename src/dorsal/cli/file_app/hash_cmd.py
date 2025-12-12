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
from typing import Annotated, List, Literal
import json

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markup import escape

from dorsal.common.literals import MiB
from dorsal.file.utils.quick_hasher import QuickHasher

logger = logging.getLogger(__name__)

HashType = Literal["BLAKE3", "SHA-256", "TLSH", "QUICK"]


def hash_file(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The path to the single file to hash.",
        ),
    ],
    sha256: Annotated[bool, typer.Option("--sha256", help="Display the SHA-256 hash.")] = False,
    blake3: Annotated[bool, typer.Option("--blake3", help="Display the BLAKE3 hash.")] = False,
    tlsh: Annotated[bool, typer.Option("--tlsh", help="Display the TLSH similarity hash.")] = False,
    quick: Annotated[bool, typer.Option("--quick", help="Display the sample-based QuickHash.")] = False,
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
            help="Bypass the local cache and re-calculate hashes, overriding any global setting.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output hashes as a raw JSON object.")] = False,
):
    """
    Calculates and displays cryptographic and specialized hashes for a single file.
    """
    from dorsal.common.cli import (
        EXIT_CODE_ERROR,
        get_rich_console,
        determine_use_cache_value,
        exit_cli,
    )
    from dorsal.file.hash_reader import HASH_READER

    console = get_rich_console()
    palette = ctx.obj["palette"]

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache flags cannot be used together.",
        )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    hashes_to_get: List[HashType] = []
    show_all = not any([sha256, blake3, tlsh, quick])

    if show_all or sha256:
        hashes_to_get.append("SHA-256")
    if show_all or blake3:
        hashes_to_get.append("BLAKE3")
    if show_all or tlsh:
        hashes_to_get.append("TLSH")
    if show_all or quick:
        hashes_to_get.append("QUICK")

    try:
        file_hashes = HASH_READER.get(
            file_path=str(path),
            hashes=list(set(hashes_to_get)),
            skip_cache=not use_cache_value,
        )
    except Exception as err:
        logger.exception(f"CLI 'hash' command failed for path {path}.")
        return exit_cli(code=EXIT_CODE_ERROR, message=str(err))

    if json_output:
        console.print(json.dumps(file_hashes, indent=2, ensure_ascii=False, default=str))
        return exit_cli()

    if len(hashes_to_get) == 1:
        hash_type = hashes_to_get[0]
        hash_value = file_hashes.get(hash_type)

        if hash_value is not None:
            console.print(hash_value)
        elif hash_type == "QUICK":
            min_size_mb = QuickHasher.min_permitted_filesize // MiB
            console.print(
                f"[{palette['info']}]Info:[/] QuickHash not generated. File size is below the {min_size_mb}MiB minimum."
            )
        elif hash_type == "TLSH":
            console.print(
                f"[{palette['info']}]Info:[/] TLSH hash not generated. To enable, please install the 'py-tlsh' Python package."
            )
        return exit_cli()

    if file_hashes:
        hash_grid = Table.grid(padding=(0, 2))
        hash_grid.add_column(justify="right", style=palette["key"])
        hash_grid.add_column(justify="left")

        for hash_function, hash_val in file_hashes.items():
            if hash_function == "TLSH" and hash_val is None and show_all:
                continue

            if hash_val is None and hash_function not in ["QUICK", "TLSH"]:
                continue

            value_style = palette.get("hash_value", "magenta")
            display_value = hash_val

            if hash_function == "QUICK" and hash_val is None:
                min_size_mb = QuickHasher.min_permitted_filesize // MiB
                display_value = f"File size below {min_size_mb}MiB minimum"
                value_style = palette.get("info", "dim")
            elif hash_function == "TLSH" and hash_val is None:
                display_value = "The 'py-tlsh' package is not installed"
                value_style = palette.get("info", "dim")

            hash_grid.add_row(f"{hash_function}:", Text(str(display_value), style=value_style))

        console.print(
            Panel(
                hash_grid,
                title=f"[{palette['panel_title']}]🔑 Hashes for {escape(path.name)}[/]",
                expand=False,
                border_style=palette["panel_border"],
            )
        )
