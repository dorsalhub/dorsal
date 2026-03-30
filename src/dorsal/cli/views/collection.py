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

from rich.panel import Panel
from rich.table import Table
from rich.console import Group, RenderableType
from rich.text import Text
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.file.validators.collection import FileCollection
    from dorsal.cli.themes import UIContext


def collection_metadata(collection: "FileCollection", ui_context: "UIContext") -> RenderableType:
    """Creates a rich visual block with the collection's metadata."""
    from dorsal.file.utils.size import human_filesize
    from dorsal.cli.themes.borders import get_borders

    palette = ui_context["palette"]
    borders = ui_context["borders"]

    if collection.date_modified is not None:
        date_modified = collection.date_modified.strftime("%Y-%m-%d %H:%M:%S")
    else:
        date_modified = "None"

    metadata_table = Table.grid(expand=False, padding=(0, 1))
    metadata_table.add_column(style=palette.get("key"), width=15)
    metadata_table.add_column(style=palette.get("primary_value"))

    metadata_table.add_row("ID:", collection.collection_id)
    metadata_table.add_row("Name:", collection.name)
    if collection.description:
        metadata_table.add_row("Description:", collection.description)
    metadata_table.add_row("File Count:", f"{collection.file_count:,}")
    metadata_table.add_row("Total Size:", human_filesize(collection.total_size))
    metadata_table.add_row("Access:", "Private" if collection.is_private else "Public")
    metadata_table.add_row("Modified:", date_modified)

    title_text = f"[{palette.get('panel_title', 'default')}]Collection Metadata[/]"

    if borders == get_borders("none"):
        return Group(Text.from_markup(f"\n{title_text}"), metadata_table)
    else:
        return Panel(
            metadata_table,
            title=title_text,
            border_style=palette.get("panel_border", "default"),
            expand=False,
            box=borders,
        )
