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

from typing import Any

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text


def display_local_search_results(console: Console, response: Any, palette: dict[str, str]) -> None:
    """
    Renders the local search results to the console, dynamically adjusting
    the layout based on the available terminal width.
    """
    from dorsal.file.utils.size import human_filesize

    search_caption = (
        "Search powered by Dorsal Local Index. "
        "For search syntax, visit:\n   https://docs.dorsalhub.com/reference/search-syntax/"
    )

    table = Table(
        title="Local Search Results",
        show_header=True,
        header_style=palette.get("table_header", "bold blue"),
        caption=search_caption,
        caption_style="dim",
        caption_justify="left",
        expand=True,
        row_styles=["", palette.get("table_row_alt", "dim")],
    )

    # --- RESPONSIVE LAYOUT CHECK ---
    # 64 (hash) + 20 (name) + 15 (type) + 10 (size) + borders ≈ 115 columns needed
    if console.width < 115:
        # Narrow layout: Two-Line Stacked Table
        table.add_column("File Details (Name / Hash)", ratio=1, overflow="fold")
        table.add_column("Size / Type", justify="right", width=20)

        for record in response.records:
            name_text = Text(record.name or "Unknown", style=palette.get("primary_value", ""))
            hash_text = Text(record.hash_sha256, style=palette.get("hash_value", ""))
            details_group = Group(name_text, hash_text)

            size_text = Text(human_filesize(record.size or 0))
            type_text = Text(record.media_type or "Unknown", style=palette.get("info", "dim"))
            meta_group = Group(size_text, type_text)

            table.add_row(details_group, meta_group)
    else:
        # Wide layout: Standard Columns
        table.add_column("Name", ratio=1, min_width=20, overflow="fold", vertical="middle")
        table.add_column("Size", justify="right", min_width=7, vertical="middle")
        table.add_column("Media Type", min_width=8, vertical="middle")
        table.add_column(
            "SHA256 Hash",
            style=palette.get("hash_value", ""),
            no_wrap=True,
            width=64,
            vertical="middle",
        )

        for record in response.records:
            table.add_row(
                record.name or "Unknown",
                human_filesize(record.size or 0),
                record.media_type or "Unknown",
                record.hash_sha256,
            )

    console.print(table)

    # --- PAGINATION FOOTER ---
    pagination = response.pagination
    start_display = pagination.start_index + 1 if pagination.record_count > 0 else 0

    footer_text = (
        f"Showing page [bold]{pagination.current_page}[/] of [bold]{pagination.page_count}[/] | "
        f"Displaying records [bold]{start_display} - {pagination.end_index}[/] "
        f"of [bold]{pagination.record_count}[/] total."
    )
    console.print(footer_text)

    if pagination.has_next:
        console.print(
            f"To see the next page, run the command again with "
            f"[bold {palette.get('primary_value', '')}]--page {pagination.current_page + 1}[/]"
        )
