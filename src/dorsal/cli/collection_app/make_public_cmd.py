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
from typing import TYPE_CHECKING, Annotated
import json
import typer

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

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
    from rich.console import Group
    from rich.text import Text

    from dorsal.cli.views.layout import key_values, section
    from dorsal.common.cli import (
        get_error_console,
        get_rich_console,
        exit_cli,
        handle_error,
        EXIT_CODE_ERROR,
        print_raw_output,
    )
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError, ConflictError

    console = get_rich_console()
    ui_context: "UIContext" = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})

    try:
        with get_error_console().status(f"Updating collection '[bold]{collection_id}[/]'"):
            response = api_make_public(collection_id=collection_id)

        if json_output:
            print_raw_output(response.model_dump_json(indent=2, by_alias=True, exclude_none=True), console)
        else:
            body = Group(
                Text("Collection is now public."),
                key_values(ui_context, [("URL", str(response.location_url))]),
            )
            console.print(
                section(
                    f"{icons.get('success', '')}Update complete",
                    body,
                    ui_context,
                    title_style=palette.get("panel_title_success", "bold green"),
                    border_style=palette.get("panel_border_success", "green"),
                )
            )

    except ConflictError as e:
        handle_error(ui_context, e.message, json_output)
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        handle_error(ui_context, f"API Error: {e.message}", json_output)
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection make-public'")
        handle_error(ui_context, f"An unexpected error occurred: {e}", json_output)
