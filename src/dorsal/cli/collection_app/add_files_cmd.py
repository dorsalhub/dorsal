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

import logging
import sys
from typing import Annotated, Optional, List, TYPE_CHECKING

import typer
from rich.console import Group, RenderableType
from rich.text import Text

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

logger = logging.getLogger(__name__)


def _get_hashes(hash_list: Optional[List[str]], from_stdin: bool, json_output: bool, console) -> List[str]:
    all_hashes = set(hash_list) if hash_list else set()

    if from_stdin:
        if not sys.stdin.isatty():
            stdin_hashes = {line.strip() for line in sys.stdin if line.strip()}
            all_hashes.update(stdin_hashes)
        elif not json_output:
            console.print("[yellow]Warning:[/] --from-stdin flag was used, but no input was received.")

    if not all_hashes:
        from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR

        exit_cli(
            code=EXIT_CODE_ERROR,
            message="No file hashes provided. Use --hash or pipe input via --from-stdin.",
        )
    return list(all_hashes)


def add_files(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The ID of the collection to add files to.")],
    hash_list: Annotated[
        Optional[List[str]],
        typer.Option(
            "--hash",
            "-h",
            help="A file hash to add. This option can be used multiple times.",
            show_default=False,
        ),
    ] = None,
    from_stdin: Annotated[
        bool,
        typer.Option(
            "--from-stdin",
            help="Read a list of hashes from standard input (one hash per line).",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the results as a raw JSON object."),
    ] = False,
):
    """
    Add one or more files to a remote collection by their hash.

    You can provide hashes in multiple ways:
    - Using multiple --hash options: --hash <hash1> --hash <hash2>
    - Piping from another command: cat my_hashes.txt | dorsal collection add-files <id> --from-stdin
    """
    from dorsal.api.collection import add_files_to_collection, get_collection
    from dorsal.cli.views.layout import key_values, section
    from dorsal.common.cli import (
        get_error_console,
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        print_raw_output,
    )
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    error_console = get_error_console()
    ui_context: "UIContext" = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})

    final_hash_list = _get_hashes(hash_list, from_stdin, json_output, error_console)

    try:
        with error_console.status(f"Adding {len(final_hash_list)} file(s) to collection '[bold]{collection_id}[/]'"):
            response = add_files_to_collection(collection_id=collection_id, hashes=final_hash_list)

    except ValueError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=str(e))
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection add-files'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")

    if json_output:
        print_raw_output(response.model_dump_json(indent=2), console)
        exit_cli()

    counts = key_values(ui_context)
    counts.add("Added", str(response.added_count))
    counts.add("Duplicates ignored", str(response.duplicate_count))
    body: RenderableType = counts

    if response.invalid_count > 0:
        counts.add("Not added", str(response.invalid_count), style=palette.get("error", "bold red"))
        info_style = palette.get("info", "dim")
        generic_note = "Note: Files can only be added to a collection if they match a public file record, or you have indexed them."

        try:
            with error_console.status("Fetching collection details for context"):
                collection_data = get_collection(collection_id=collection_id, hydrate=False, mode="pydantic")
                is_public_collection = not collection_data.collection.is_private

            if is_public_collection:
                note = (
                    "Note: This is a public collection, which means only hashes matching public file records can be "
                    "added. Try pushing the file(s) with the --public flag first."
                )
            else:
                note = generic_note
        except DorsalClientError:
            note = generic_note

        body = Group(counts, Text(""), Text(note, style=info_style))

    console.print(
        section(
            f"{icons.get('success', '')}Update complete",
            body,
            ui_context,
            title_style=palette.get("panel_title_success", "bold green"),
            border_style=palette.get("panel_border_success", "green"),
        )
    )
