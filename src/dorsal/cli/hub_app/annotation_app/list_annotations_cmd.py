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
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Group
from rich.text import Text

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

logger = logging.getLogger(__name__)


def list_annotations(
    ctx: typer.Context,
    file_hash: Annotated[str, typer.Argument(help="The SHA-256 hash of the file.")],
):
    """List all annotation stubs attached to a file."""
    from dorsal.api.file import list_file_annotations
    from dorsal.cli.views.layout import table as themed_table
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console

    console = get_rich_console()
    error_console = get_error_console()

    ui_context: "UIContext" = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})

    with error_console.status(f"[{palette.get('info', 'dim')}]Fetching annotations[/]"):
        try:
            annotations = list_file_annotations(file_hash, mode="dict")
        except Exception as e:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to fetch annotations:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    narrow = console.width < 115
    rows: list[tuple] = []
    first_anno = None

    for schema_id, items in annotations.items():
        if not isinstance(items, list):
            continue
        for item in items:
            anno_id = item.get("id", "Unknown")
            if first_anno is None:
                first_anno = anno_id

            source_data = item.get("source", {})
            source_str = f"{source_data.get('type', 'Unknown')} ({source_data.get('id', 'Unknown')})"

            mod_date = item.get("date_modified", "").replace("Z", "").replace("T", " ")[:16]

            if narrow:
                id_text = Text(anno_id, style=palette.get("primary_value", "cyan"))
                schema_text = Text(schema_id, style=palette.get("info", "dim"))
                mod_text = Text(mod_date)
                source_text = Text(source_str, style=palette.get("info", "dim"))
                rows.append((Group(id_text, schema_text), Group(mod_text, source_text)))
            else:
                rows.append((schema_id, anno_id, source_str, mod_date))

    if not rows:
        console.print(f"[{palette.get('info', 'dim')}]No multi-value annotations found for this file.[/]")
        return

    title = Text.assemble(
        f"{icons.get('search', '')}Found {len(rows)} annotation(s) for file ",
        (f"{file_hash[:16]}…", "bold"),
        style=palette.get("section_title", "bold"),
    )
    table = themed_table(
        ui_context, title=title, show_header=True, header_style=palette.get("section_title", "bold cyan")
    )

    if narrow:
        table.add_column("Annotation (ID / schema)", ratio=1, overflow="fold")
        table.add_column("Metadata (modified / source)", justify="right", width=38)
    else:
        table.add_column("Schema")
        table.add_column("Annotation ID", no_wrap=True)
        table.add_column("Source")
        table.add_column("Modified")

    for row in rows:
        table.add_row(*row)

    console.print(table)

    if first_anno:
        command_style = palette.get("primary_value", "cyan")
        console.print()
        console.print(
            Text.assemble(
                ("To view an annotation, run ", "dim"),
                (f"dorsal hub annotation get {first_anno}", command_style),
            )
        )
