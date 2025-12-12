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
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from dorsal.file.validators.collection import (
        SingleCollectionResponse,
        HydratedSingleCollectionResponse,
    )


logger = logging.getLogger(__name__)


def show_collection(
    ctx: typer.Context,
    collection_id: Annotated[str, typer.Argument(help="The unique ID of the collection to show.")],
    meta_only: Annotated[
        bool,
        typer.Option("--meta-only", help="Only display the collection's high-level metadata."),
    ] = False,
    page: Annotated[int, typer.Option("--page", "-p", help="The page number for the file list.")] = 1,
    per_page: Annotated[
        int,
        typer.Option("--per-page", help="The number of files to retrieve per page."),
    ] = 30,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the full, detailed collection data as a raw JSON object.",
        ),
    ] = False,
):
    """
    Shows metadata and file contents for a single collection.

    Note: the order of records will always be by date added.
    """
    from dorsal.api.collection import get_collection
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError, NotFoundError
    from dorsal.file.utils.size import human_filesize
    from dorsal.cli.views.collection import collection_metadata

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    if not json_output:
        console.print(f"🔎 Fetching collection '[bold]{collection_id}[/]'...")

    response: HydratedSingleCollectionResponse | SingleCollectionResponse

    try:
        if json_output:
            response = get_collection(
                collection_id=collection_id,
                hydrate=True,
                page=page,
                per_page=0 if meta_only else per_page,
                mode="pydantic",
            )
            console.print(response.model_dump_json(indent=2, by_alias=True, exclude_none=True))
            return exit_cli()
        else:
            response = get_collection(
                collection_id=collection_id,
                hydrate=False,
                page=page,
                per_page=0 if meta_only else per_page,
                mode="pydantic",
            )

        panel = collection_metadata(response.collection, palette)
        console.print(panel)

        if meta_only:
            exit_cli()

        if response.files:
            file_table = Table(
                title="Files in Collection",
                header_style=palette.get("table_header"),
                expand=False,
            )
            file_table.add_column("Name", no_wrap=True, max_width=70, overflow="ellipsis")
            file_table.add_column("Size", justify="right")
            file_table.add_column("Media Type")
            file_table.add_column("SHA256 Hash", style=palette.get("hash_value"), no_wrap=True)

            for file in response.files:
                file_table.add_row(file.name, human_filesize(file.size), file.media_type, file.hash)
            console.print(file_table)

            pagination = response.pagination
            if pagination.page_count > 1:
                footer = (
                    f"Showing page {pagination.current_page} of {pagination.page_count} | "
                    f"Displaying files {pagination.start_index} - {pagination.end_index} of {pagination.record_count} total."
                )
                if pagination.has_next:
                    footer += f"\nTo see the next page, run the command again with --page {pagination.current_page + 1}"
                console.print(f"\n[{palette.get('info')}]{footer}[/]")
        else:
            if response.collection.file_count == 0:
                console.print(f"\n[{palette.get('info')}]Collection contains no files.[/]")
            else:
                page_count = response.pagination.page_count
                message = (
                    f"Page {page} is out of range. "
                    f"For this collection, please select a page between 1 and {page_count}."
                )
                console.print(f"\n[{palette.get('warning')}]{message}[/]")

    except typer.Exit:
        raise
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        if isinstance(e, NotFoundError):
            exit_cli(code=EXIT_CODE_ERROR, message=f"Collection '{collection_id}' not found.")
        else:
            exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception("An unexpected error occurred in 'collection show'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
