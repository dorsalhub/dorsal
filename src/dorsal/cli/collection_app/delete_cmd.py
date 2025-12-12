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
import json
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


def delete_collection(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The unique ID of the collection to delete.")],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Bypass the interactive confirmation prompt. Use with caution.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the result as a raw JSON object."),
    ] = False,
):
    """
    Permanently deletes a collection from DorsalHub.
    """
    from dorsal.api.collection import delete_collection
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()

    palette = ctx.obj["palette"]

    if not json_output:
        if not yes:
            typer.confirm(
                f"Are you sure you want to permanently delete collection '{collection_id}'?",
                abort=True,
            )
        console.print(f"🗑️  Deleting collection '[bold]{collection_id}[/]'...")

    try:
        delete_collection(collection_id=collection_id)

        if json_output:
            console.print(
                json.dumps(
                    {"success": True, "collection_id": collection_id, "deleted": True},
                    indent=2,
                )
            )
        else:
            console.print(f"\n[{palette.get('success')}]✅ Collection '{collection_id}' was successfully deleted.[/]")
    except DorsalOfflineError:
        raise
    except AuthError:
        raise

    except DorsalClientError as e:
        if json_output:
            error_payload = {
                "success": False,
                "error": e.message,
                "collection_id": collection_id,
            }
            console.print(json.dumps(error_payload, indent=2))
            exit_cli(code=EXIT_CODE_ERROR)
        else:
            exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")

    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection delete'")
        if json_output:
            error_payload = {
                "success": False,
                "error": str(e),
                "collection_id": collection_id,
            }
            console.print(json.dumps(error_payload, indent=2))
            exit_cli(code=EXIT_CODE_ERROR)
        else:
            exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
