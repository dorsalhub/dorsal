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

from rich.panel import Panel
from rich.table import Table
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.file.validators.collection import FileCollection


def collection_metadata(collection: "FileCollection", palette: dict[str, str]) -> Panel:
    """Creates a rich Panel with the collection's metadata."""
    from dorsal.file.utils.size import human_filesize

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

    return Panel(
        metadata_table,
        title=f"[{palette.get('panel_title', 'default')}]Collection Metadata[/]",
        border_style=palette.get("panel_border", "default"),
        expand=False,
    )
