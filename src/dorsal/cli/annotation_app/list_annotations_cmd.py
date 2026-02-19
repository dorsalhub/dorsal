# Copyright 2026 Dorsal Hub LTD
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
from rich.table import Table


logger = logging.getLogger(__name__)


def list_annotations(
    ctx: typer.Context,
    file_hash: Annotated[str, typer.Argument(help="The SHA-256 hash of the file.")],
):
    """List all annotation stubs attached to a file."""
    from dorsal.api.file import list_file_annotations
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console

    console = get_rich_console()
    error_console = get_error_console()
    palette = ctx.obj["palette"]

    with console.status(f"[{palette.get('info', 'dim')}]Fetching annotations...[/]"):
        try:
            annotations = list_file_annotations(file_hash, mode="dict")
        except Exception as e:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to fetch annotations:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    table = Table(box=None, show_header=True, header_style=palette.get("section_title", "bold cyan"))
    table.add_column("Schema")
    table.add_column("Annotation ID")
    table.add_column("Source")
    table.add_column("Modified")

    found_count = 0

    for schema_id, items in annotations.items():
        if isinstance(items, list):
            for item in items:
                found_count += 1
                anno_id = item.get("id", "Unknown")

                source_data = item.get("source", {})
                source_str = f"{source_data.get('type', 'Unknown')} ({source_data.get('id', 'Unknown')})"

                mod_date = item.get("date_modified", "").replace("Z", "").replace("T", " ")[:16]

                table.add_row(schema_id, anno_id, source_str, mod_date)

    if found_count == 0:
        console.print(f"[{palette.get('info', 'dim')}]No multi-value annotations found for this file.[/]")
        return

    console.print(f"🔎 Found {found_count} annotation(s) for file [bold]{file_hash[:16]}...[/]\n")
    console.print(table)
    console.print(
        f"\n💡 [dim]Tip: Use[/] dorsal annotation get {file_hash} <annotation_id> [dim]to view the full data.[/]"
    )
