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
import json
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


def remove_files(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The ID of the collection to remove files from.")],
    hash_list: Annotated[
        Optional[List[str]],
        typer.Option(
            "--hash",
            "-h",
            help="A file hash to remove. This option can be used multiple times.",
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
    Remove one or more files from a remote collection by their hash.
    """
    from dorsal.api.collection import remove_files_from_collection
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    final_hash_list = _get_hashes(hash_list, from_stdin, json_output, console)

    try:
        if not json_output:
            with console.status(
                f"Removing {len(final_hash_list)} file(s) from collection '[bold]{collection_id}[/]'..."
            ):
                response = remove_files_from_collection(collection_id=collection_id, hashes=final_hash_list)
        else:
            response = remove_files_from_collection(collection_id=collection_id, hashes=final_hash_list)

    except ValueError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=str(e))
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection remove-files'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")

    if json_output:
        console.print(response.model_dump_json(indent=2))
        exit_cli()

    output_text = Text()
    output_text.append("✅ Operation complete.\n", style=palette.get("success", "green"))
    output_text.append(f"Removed: {response.removed_count}\n")

    if response.not_found_count > 0:
        output_text.append(
            f"Not Found (ignored): {response.not_found_count}",
            style=palette.get("info", "dim"),
        )

    success_panel = Panel(
        output_text,
        title=f"[{palette.get('panel_title_success', 'bold green')}]Update Complete[/]",
        border_style=palette.get("panel_border_success", "green"),
        expand=False,
    )
    console.print(success_panel)
