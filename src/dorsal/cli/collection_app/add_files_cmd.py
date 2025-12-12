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
import sys
from typing import Annotated, Optional, List

import typer
from rich.panel import Panel
from rich.text import Text

logger = logging.getLogger(__name__)


def _get_hashes(hash_list: Optional[List[str]], from_stdin: bool, json_output: bool, console) -> List[str]:
    all_hashes = set(hash_list) if hash_list else set()

    if from_stdin:
        if not sys.stdin.isatty():
            stdin_hashes = {line.strip() for line in sys.stdin if line.strip()}
            all_hashes.update(stdin_hashes)
        elif not json_output:
            console.print("[warning]--from-stdin flag was used, but no input was received.[/warning]")

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
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    final_hash_list = _get_hashes(hash_list, from_stdin, json_output, console)

    try:
        if not json_output:
            with console.status(f"Adding {len(final_hash_list)} file(s) to collection '[bold]{collection_id}[/]'..."):
                response = add_files_to_collection(collection_id=collection_id, hashes=final_hash_list)
        else:
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
        console.print(response.model_dump_json(indent=2))
        exit_cli()

    output_text = Text()
    output_text.append("✅ Operation complete.\n", style=palette.get("success", "green"))
    output_text.append(f"Added: {response.added_count}\n")
    output_text.append(f"Duplicates ignored: {response.duplicate_count}\n")

    if response.invalid_count > 0:
        output_text.append(
            f"Not Added: {response.invalid_count}\n",
            style=palette.get("error", "bold red"),
        )
        info_style = palette.get("info", "dim")
        output_text.append("\n")

        try:
            with console.status("Fetching collection details for context..."):
                collection_data = get_collection(collection_id=collection_id, hydrate=False, mode="pydantic")
                is_public_collection = not collection_data.collection.is_private

            if is_public_collection:
                output_text.append(
                    "Note: This is a public collection, which means only hashes matching public file records can be added. "
                    "Try pushing the file(s) with the --public flag first.",
                    style=info_style,
                )
            else:
                output_text.append(
                    "Note: Files can only be added to a collection if they match a public file record, or you have indexed them.",
                    style=info_style,
                )
        except DorsalClientError:
            output_text.append(
                "Note: Files can only be added to a collection if they match a public file record, or you have indexed them.",
                style=info_style,
            )

    success_panel = Panel(
        output_text,
        title=f"[{palette.get('panel_title_success', 'bold green')}]Update Complete[/]",
        border_style=palette.get("panel_border_success", "green"),
        expand=False,
    )
    console.print(success_panel)
