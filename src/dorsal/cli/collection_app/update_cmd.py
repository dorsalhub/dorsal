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
from typing import Annotated, Optional

import typer
from rich.panel import Panel
import json

logger = logging.getLogger(__name__)


def update_collection(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The unique ID of the collection to update.")],
    name: Annotated[
        Optional[str],
        typer.Option("--name", "-n", help="A new name for the collection."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option("--description", "-d", help="A new description for the collection."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the updated collection as a raw JSON object."),
    ] = False,
):
    """
    Update the name or description of a remote collection.
    """
    from dorsal.api.collection import update_collection as api_update_collection
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        # Show a status spinner only for the interactive mode
        status_message = f"Updating collection '[bold]{collection_id}[/]...'" if not json_output else ""
        with console.status(status_message):
            updated_collection = api_update_collection(
                collection_id=collection_id,
                name=name,
                description=description,
                mode="pydantic",
            )

    except typer.Exit:
        raise
    except ValueError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=str(e))
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection update'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")

    if json_output:
        console.print(updated_collection.model_dump_json(indent=2, by_alias=True, exclude_none=True))
    else:
        success_panel = Panel(
            f"✅ Collection '[bold]{updated_collection.name}[/]' updated successfully.",
            expand=False,
            title=f"[{palette.get('panel_title_success', 'bold green')}]Update Complete[/]",
            border_style=palette.get("panel_border_success", "green"),
        )
        console.print(success_panel)
