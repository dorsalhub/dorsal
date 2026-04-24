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
from rich.console import Group
from rich.text import Text

from dorsal.cli.themes import UIContext
from dorsal.cli.themes.borders import get_borders

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

    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    with console.status(f"[{palette.get('info', 'dim')}]Fetching annotations...[/]"):
        try:
            annotations = list_file_annotations(file_hash, mode="dict")
        except Exception as e:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to fetch annotations:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    table = Table(box=borders, show_header=True, header_style=palette.get("section_title", "bold cyan"))

    if borders == get_borders("none"):
        table.padding = (0, 1)

    if console.width < 115:
        table.add_column("Annotation (ID / Schema)", ratio=1, overflow="fold")
        table.add_column("Metadata (Modified / Source)", justify="right", width=38)
    else:
        table.add_column("Schema")
        table.add_column("Annotation ID", no_wrap=True)
        table.add_column("Source")
        table.add_column("Modified")

    found_count = 0
    first_anno = None

    ann_items = list(annotations.items())
    for schema_id, items in ann_items:
        if isinstance(items, list):
            for item in items:
                found_count += 1
                anno_id = item.get("id", "Unknown")
                if found_count == 1:
                    first_anno = anno_id

                source_data = item.get("source", {})
                source_str = f"{source_data.get('type', 'Unknown')} ({source_data.get('id', 'Unknown')})"

                mod_date = item.get("date_modified", "").replace("Z", "").replace("T", " ")[:16]

                if console.width < 115:
                    id_text = Text(anno_id, style=palette.get("primary_value", "cyan"))
                    schema_text = Text(schema_id, style=palette.get("info", "dim"))
                    col1 = Group(id_text, schema_text)

                    mod_text = Text(mod_date)
                    source_text = Text(source_str, style=palette.get("info", "dim"))
                    col2 = Group(mod_text, source_text)

                    table.add_row(col1, col2)
                else:
                    table.add_row(schema_id, anno_id, source_str, mod_date)

    if found_count == 0:
        console.print(f"[{palette.get('info', 'dim')}]No multi-value annotations found for this file.[/]")
        return

    console.print(f"🔎 Found {found_count} annotation(s) for file [bold]{file_hash[:16]}...[/]\n")
    console.print(table)

    if first_anno:
        console.print(
            f"\n[dim]To view an annotation use[/] [{palette.get('primary_value', 'cyan')}]dorsal hub annotation get[/]"
            f"\n[dim]  Example:[/] [{palette.get('primary_value', 'cyan')}]dorsal hub annotation get {first_anno}[/]"
        )
