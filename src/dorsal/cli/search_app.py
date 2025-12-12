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

import datetime
import json
import logging
import pathlib
import re
from typing import Literal, cast, Optional

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

from dorsal.common import constants

logger = logging.getLogger(__name__)


def _save_search_results(
    query: str,
    scope: str,
    page_data: dict,
    palette: dict,
    output_path: Optional[pathlib.Path],
    json_to_stdout: bool,
):
    """
    Saves a page of search results to a timestamped JSON file.
    If output_path is provided, it's used. Otherwise, results are
    stored in a directory derived from the search query.
    """
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()
    filepath: pathlib.Path

    page_number = page_data.get("pagination", {}).get("current_page", 0)

    if output_path:
        if output_path.is_dir():
            safe_query = re.sub(r"[^\w\s-]", "", query).strip().replace(" ", "_")[:20]
            filename = f"search-{scope}-{safe_query}-p{page_number}.json"
            filepath = output_path / filename
        else:
            filepath = output_path
    else:
        sanitized_query = re.sub(r"[^\w\s-]", "", query).strip()
        sanitized_query = re.sub(r"[-\s]+", "_", sanitized_query).lower()
        truncated_query_name = sanitized_query[:200]
        if not truncated_query_name:
            truncated_query_name = "untitled_search"

        query_dir = constants.CLI_SEARCH_REPORTS_DIR / scope / truncated_query_name
        query_dir.mkdir(parents=True, exist_ok=True)

        try:
            with open(query_dir / "query.txt", "w", encoding="utf-8") as f:
                f.write(query)
        except IOError:
            console.print(f"[{palette['warning']}]Warning:[/] Could not write query.txt to report directory.")

        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-p{page_number}.json"
        filepath = query_dir / filename

    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(page_data, f, indent=2, default=str, ensure_ascii=False)

        if not json_to_stdout:
            console.print(
                f"[{palette['success']}]✅ Full JSON report saved to:[/] [{palette['primary_value']}]{filepath}[/]"
            )
    except IOError as e:
        console.print(f"[{palette['error']}]Warning:[/] Could not save JSON report. Error: {e}")


SortByField = Literal["date_modified", "date_created", "size", "name"]
SortOrder = Literal["asc", "desc"]


def search_and_display(
    ctx: typer.Context,
    scope: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str,
    sort_order: str,
    json_output: bool,
    match_any: bool,
    save: bool,
    output_path: Optional[pathlib.Path],
):
    """
    A helper function to perform the search and display results,
    shared by both 'user' and 'global' commands.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.api.file import search_user_files, search_global_files
    from dorsal.common.exceptions import AuthError, DorsalClientError, ForbiddenError
    from dorsal.file.utils.size import human_filesize

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not output_path.is_dir():
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style="yellow",
                )

    if not query:
        console.print(f"[{palette['error']}]Error:[/] Please provide a search query.")
        exit_cli(code=1)

    try:
        search_function = search_user_files if scope == "user" else search_global_files

        if not json_output:
            console.print(
                f"🔎 Searching [{palette['primary_value']}]{scope}[/] scope for records matching: [{palette['success']}]'{query}'[/]"
            )

        casted_sort_by = cast(SortByField, sort_by)
        casted_sort_order = cast(SortOrder, sort_order)

        response = search_function(
            query=query,
            page=page,
            per_page=per_page,
            sort_by=casted_sort_by,
            sort_order=casted_sort_order,
            match_any=match_any,
            mode="pydantic",
        )

        response_dict = response.model_dump(mode="json", by_alias=True, exclude_none=True)

        if json_output:
            console.print(json.dumps(response_dict, indent=2, default=str, ensure_ascii=False))
            exit_cli()

        if not response.results:
            console.print(f"\n[{palette['warning']}]No records found matching your criteria.[/]")
            exit_cli()

        search_caption = (
            f"Search powered by DorsalHub Search {response.api_version}. "
            f"For search syntax, visit: https://docs.dorsalhub.com/search"
        )

        table = Table(
            title=f"{scope.capitalize()} Search Results",
            show_header=True,
            header_style=palette["table_header"],
            caption=search_caption,
            caption_style="dim",
            caption_justify="left",
            expand=True,
            row_styles=["", palette.get("table_row_alt", "dim")],
        )

        table.add_column("Name", ratio=1, vertical="middle")
        table.add_column("Size", justify="right", min_width=7, vertical="middle")
        table.add_column("Media Type", min_width=8, vertical="middle")
        table.add_column(
            "SHA256 Hash",
            style=palette["hash_value"],
            no_wrap=True,
            width=66,
            vertical="middle",
        )

        for record in response.results:
            if not record.annotations or not record.annotations.file_base:
                logger.warning(
                    "Search result with hash %s is missing base annotations, skipping.",
                    record.hash,
                )
                continue

            base_record = record.annotations.file_base.record

            table.add_row(
                base_record.name,
                human_filesize(base_record.size),
                base_record.media_type,
                record.hash,
            )

        console.print(table)

        pagination = response.pagination
        footer_text = (
            f"Showing page [bold]{pagination.current_page}[/] of [bold]{pagination.page_count}[/] | "
            f"Displaying records [bold]{pagination.start_index} - {pagination.end_index}[/] "
            f"of [bold]{pagination.record_count}[/] total."
        )
        console.print(footer_text)

        if pagination.has_next:
            console.print(
                f"To see the next page, run the command again with [bold {palette['primary_value']}]--page {pagination.current_page + 1}[/]"
            )

        if save:
            _save_search_results(
                query=query,
                scope=scope,
                page_data=response_dict,
                palette=palette,
                output_path=output_path,
                json_to_stdout=json_output,
            )

    except ForbiddenError:
        if json_output:
            console.print(
                json.dumps(
                    {
                        "error": "Forbidden",
                        "detail": "Global search is a premium feature.",
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                )
            )
        else:
            upgrade_message = Text.assemble(
                ("The 'global' search scope is a premium feature.\n\n", "default"),
                ("To find out more, or to upgrade your account, visit:\n", "default"),
                ("https://dorsalhub.com/pricing", "underline blue"),
                style=palette.get("text_default", "default"),
            )

            panel = Panel(
                upgrade_message,
                title=f"[{palette.get('panel_title_warning', 'bold yellow')}]🔒 Upgrade Required[/]",
                border_style=palette.get("panel_border_warning", "yellow"),
                expand=False,
                padding=(1, 2),
            )
            console.print(panel)
    except DorsalClientError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {err}")
    except typer.Exit:
        raise
    except Exception as err:
        logging.getLogger(__name__).exception("CLI 'search' command failed.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")
