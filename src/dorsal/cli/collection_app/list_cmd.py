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
from typing import Annotated, TYPE_CHECKING

import typer
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from dorsal.client.validators import CollectionsResponse


logger = logging.getLogger(__name__)


def list_dorsal_collections(
    ctx: typer.Context,
    page: Annotated[int, typer.Option("--page", "-p", help="The page number to retrieve.")] = 1,
    per_page: Annotated[
        int,
        typer.Option("--per-page", help="The number of collections to retrieve per page."),
    ] = 25,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the full collection list as a raw JSON object."),
    ] = False,
):
    """
    Lists all available collections on DorsalHub.
    """
    from dorsal.api.collection import list_collections
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    palette = ctx.obj["palette"]

    if not json_output:
        console.print(f"🔎 Fetching collections from DorsalHub (page {page})...")

    try:
        response: CollectionsResponse = list_collections(page=page, per_page=per_page, mode="pydantic")
        logger.debug("PAGINATION OBJECT BEFORE DUMP: %s", response.pagination.model_dump())
        raw_dump = response.model_dump(by_alias=True, exclude_none=True)
        logger.debug("MANUAL DUMP OF PAGINATION: %s", raw_dump.get("pagination"))

        if json_output:
            console.print(response.model_dump_json(indent=2, by_alias=True, exclude_none=True))
            exit_cli()

        if not response.records:
            console.print(f"\n[{palette.get('info')}]No collections found.[/]")
            exit_cli()

        table = Table(
            title="DorsalHub Collections",
            header_style=palette.get("table_header"),
            expand=False,
        )
        table.add_column("ID", style=palette.get("key"), no_wrap=True)
        table.add_column(
            "Name",
            style=palette.get("primary_value"),
            max_width=40,
            overflow="ellipsis",
        )
        table.add_column("Files", justify="right")
        table.add_column("Total Size", justify="right")
        table.add_column("Access")
        table.add_column("Last Modified", justify="right")

        for collection in response.records:
            access_str = "Private" if collection.is_private else "Public"
            access_style = palette.get("access_private") if collection.is_private else palette.get("access_public")
            date_modified_str = (
                collection.date_modified.strftime("%Y-%m-%d %H:%M") if collection.date_modified else "None"
            )
            table.add_row(
                collection.collection_id,
                collection.name,
                f"{collection.file_count:,}",
                human_filesize(collection.total_size),
                Text(access_str, style=access_style),
                date_modified_str,
            )

        console.print(table)

        pagination = response.pagination
        if pagination.page_count > 1:
            footer_text = (
                f"Showing page {pagination.current_page} of {pagination.page_count} | "
                f"Displaying records {pagination.start_index} - {pagination.end_index} of {pagination.record_count} total."
            )
            if pagination.has_next:
                footer_text += (
                    f"\nTo see the next page, run the command again with --page {pagination.current_page + 1}"
                )

            console.print(f"\n[{palette.get('info')}]{footer_text}[/]")
    except typer.Exit:
        raise
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection list'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
