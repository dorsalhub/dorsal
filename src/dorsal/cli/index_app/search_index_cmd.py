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

import datetime
import json
import logging
import pathlib
import re
from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dorsal.common import constants

logger = logging.getLogger(__name__)


def _save_local_search_results(
    query: str,
    page_data: dict,
    palette: dict,
    output_path: Optional[pathlib.Path],
    json_to_stdout: bool,
):
    """
    Saves a page of local search results to a timestamped JSON file.
    Matches the behavior of remote_search._save_search_results.
    """
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()
    filepath: pathlib.Path

    page_number = page_data.get("pagination", {}).get("current_page", 0)

    if output_path:
        if output_path.is_dir():
            safe_query = re.sub(r"[^\w\s-]", "", query).strip().replace(" ", "_")[:20]
            filename = f"search-local-{safe_query}-p{page_number}.json"
            filepath = output_path / filename
        else:
            filepath = output_path
    else:
        sanitized_query = re.sub(r"[^\w\s-]", "", query).strip()
        sanitized_query = re.sub(r"[-\s]+", "_", sanitized_query).lower()
        truncated_query_name = sanitized_query[:200]
        if not truncated_query_name:
            truncated_query_name = "untitled_search"

        query_dir = constants.CLI_SEARCH_REPORTS_DIR / "local" / truncated_query_name
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


def search_index_cmd(
    ctx: typer.Context,
    query: Annotated[
        str,
        typer.Argument(help="The search query string. Queries with spaces must be enclosed in quotes."),
    ] = "*",
    page: Annotated[
        int,
        typer.Option(
            "--page",
            "-p",
            help="The page number of results to display.",
            rich_help_panel="Search Options",
        ),
    ] = 1,
    per_page: Annotated[
        int,
        typer.Option(
            "--per-page",
            help="The number of results to display per page.",
            rich_help_panel="Search Options",
        ),
    ] = 30,
    sort_by: Annotated[
        str,
        typer.Option(
            "--sort-by",
            help="Field to sort results by (e.g. date_modified, size, name).",
            rich_help_panel="Search Options",
        ),
    ] = "date_modified",
    sort_order: Annotated[
        str,
        typer.Option(
            "--sort-order",
            help="Sort order ('asc' or 'desc').",
            rich_help_panel="Search Options",
        ),
    ] = "desc",
    or_logic: Annotated[
        bool,
        typer.Option(
            "--or",
            help="Use OR logic for the query. By default, multiple terms are combined with AND.",
            rich_help_panel="Search Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output results as a raw JSON object.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Save the JSON search results to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "-o",
            "--output",
            help="Custom path to save the JSON search results (e.g., 'results.json').",
            dir_okay=True,
            file_okay=True,
            writable=True,
            resolve_path=True,
            rich_help_panel="Output Options",
        ),
    ] = None,
):
    """
    Search Dorsal's local file index.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.api.search import search_local_paginated
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes import UIContext

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context["icons"]

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not output_path.is_dir():
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style=palette.get("warning", "yellow"),
                )

    if not query or not query.strip():
        console.print(f"[{palette['error']}]Error:[/] Please provide a search query.")
        exit_cli(code=EXIT_CODE_ERROR)

    try:
        if not json_output:
            console.print(
                f"{icons.get('search')}Searching [{palette['primary_value']}]index[/] for records matching: [{palette['success']}]'{query}'[/]"
            )

        sort_desc = sort_order.lower() == "desc"

        response = search_local_paginated(
            query=query,
            or_logic=or_logic,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_desc=sort_desc,
        )

        response_dict = response.model_dump(mode="json", by_alias=True, exclude_none=True)

        if json_output:
            console.print(json.dumps(response_dict, indent=2, default=str, ensure_ascii=False))
            exit_cli()

        if not response.records:
            console.print(f"\n[{palette['warning']}]No records found matching your criteria.[/]")
            exit_cli()

        display_local_search_results(console=console, response=response, ui_context=ui_context)

        if save:
            _save_local_search_results(
                query=query,
                page_data=response_dict,
                palette=palette,
                output_path=output_path,
                json_to_stdout=json_output,
            )

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Local search failed.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An error occurred during local search: {e}")
