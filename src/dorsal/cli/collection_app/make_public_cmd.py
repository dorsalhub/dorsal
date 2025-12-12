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
from typing import Annotated
import json
import typer
from rich.panel import Panel

logger = logging.getLogger(__name__)


def make_public(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The ID of the collection to make public.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the updated collection as a raw JSON object."),
    ] = False,
):
    """
    Makes a remote collection public.
    """
    from dorsal.api.collection import make_collection_public as api_make_public
    from dorsal.common.cli import get_rich_console, exit_cli, handle_error, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError, ConflictError

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        status_message = f"Updating collection '[bold]{collection_id}[/]'..." if not json_output else ""
        with console.status(status_message):
            response = api_make_public(collection_id=collection_id)

        if json_output:
            console.print(response.model_dump_json(by_alias=True, exclude_none=True, indent=2))
        else:
            success_panel = Panel(
                f"✅ Collection is now public.\n\n[dim]URL:[/] {response.location_url}",
                title=f"[{palette.get('panel_title_success', 'bold green')}]Update Complete[/]",
                border_style=palette.get("panel_border_success", "green"),
                expand=False,
            )
            console.print(success_panel)

    except ConflictError as e:
        handle_error(palette, e.message, json_output)
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        handle_error(palette, f"API Error: {e.message}", json_output)
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection make-public'")
        handle_error(palette, f"An unexpected error occurred: {e}", json_output)
