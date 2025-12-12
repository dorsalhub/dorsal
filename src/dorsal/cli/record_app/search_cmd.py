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

from typing import Annotated, Optional
import typer
import pathlib

from dorsal.cli.search_app import search_and_display


def search_record(
    ctx: typer.Context,
    query: Annotated[
        str,
        typer.Argument(help="The search query string. Queries with spaces must be enclosed in quotes."),
    ],
    is_global: Annotated[
        bool,
        typer.Option(
            "--global",
            "-g",
            help="Perform a global search across all public files (Premium).",
            rich_help_panel="Search Options",
        ),
    ] = False,
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
            help="Field to sort results by.",
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
    match_any: Annotated[
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
    Search DorsalHub file records.
    """
    scope = "global" if is_global else "user"

    search_and_display(
        ctx=ctx,
        scope=scope,
        query=query,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
        json_output=json_output,
        match_any=match_any,
        save=save,
        output_path=output_path,
    )
