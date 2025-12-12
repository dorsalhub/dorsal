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
from typing import Any, Dict

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.rule import Rule
import typer


def _get_max_key_width(data: Dict, indent_level: int = 0, display_fields: set | None = None) -> int:
    """Recursively calculates the maximum width needed for keys in a nested dict."""
    max_width = 0
    indent = "  " * indent_level
    for key, value in data.items():
        if key == "file_hash":
            continue
        if display_fields and key not in display_fields:
            continue
        key_width = len(f"{indent}{key}:")
        if key_width > max_width:
            max_width = key_width

        if isinstance(value, dict):
            nested_width = _get_max_key_width(value, indent_level + 1, display_fields=display_fields)
            if nested_width > max_width:
                max_width = nested_width
    return max_width


def _build_dynamic_table(
    table: Table, data: Any, level: int = 0, is_stub: bool = False, display_fields: set | None = None
):
    """
    Recursively builds a rich Table from nested dictionaries or lists.
    Renders annotation stubs in a simplified format.
    """
    indent = "  " * level

    if isinstance(data, dict):
        if is_stub:
            source = data.get("source", {})
            source_type = source.get("type", "none")
            source_id = source.get("id", "none")

            table.add_row(f"{indent}Source:", f"{source_type} ({source_id})")
            if date_mod := data.get("date_modified"):
                dt_obj = datetime.datetime.fromisoformat(date_mod.replace("Z", "+00:00"))
                table.add_row(f"{indent}Modified:", dt_obj.strftime("%Y-%m-%d %H:%M"))

            if data.get("url") and data.get("id"):
                file_hash = data["url"].split("/")[2]
                anno_id = data["id"]
                cta = f"dorsal annotation get {file_hash} {anno_id}"
                table.add_row(f"{indent}To View:", Text(cta, style="cyan"))
        else:
            for key, value in data.items():
                if key == "file_hash":
                    continue

                if display_fields and key not in display_fields:
                    continue

                if not value:
                    continue

                key_text = f"{indent}{key}:"

                if isinstance(value, dict):
                    table.add_row(key_text, "")
                    _build_dynamic_table(table, value, level + 1, display_fields=display_fields)

                elif isinstance(value, list):
                    if all(not isinstance(item, (dict, list)) for item in value):
                        value_str = ", ".join(str(item) for item in value)
                        table.add_row(key_text, value_str)
                    else:
                        table.add_row(key_text, "")
                        _build_dynamic_table(table, value, level + 1, display_fields=display_fields)

                else:
                    table.add_row(key_text, str(value))

    elif isinstance(data, list):
        for item in data:
            _build_dynamic_table(table, item, level, is_stub=is_stub, display_fields=display_fields)


def create_file_info_panel(
    *,
    record_dict: dict,
    title: str,
    private: bool | None,
    palette: dict[str, str],
    override_title_style: str | None = None,
    override_border_style: str | None = None,
    source: str | None = None,
) -> Panel:
    """
    Creates a standardized rich Panel to display file information using a color palette.
    """
    from dorsal.file.utils.size import human_filesize
    from dorsal.cli.views.mediainfo import MEDIAINFO_DISPLAY_FIELDS

    if override_border_style:
        border = override_border_style
    else:
        border = palette["panel_border_alt"] if private else palette["panel_border"]
    if override_title_style:
        panel_title_style = override_title_style
    else:
        panel_title_style = palette["panel_title_alt"] if private else palette["panel_title"]
    primary_color = palette["primary_value_alt"] if private else palette["primary_value"]

    display_title = title
    if source == "cache":
        display_title = f"{title} [{palette.get('info', 'dim')}](from cache)[/]"

    access_text = None
    if private is not None:
        access_text = (
            Text("Private Record", style=palette["access_private"])
            if private
            else Text("Public Record", style=palette["access_public"])
        )

    renderables: list[RenderableType] = []

    hashes_table = Table(box=None, show_header=False, padding=(0, 1))
    hashes_table.add_column(style=palette["key"], justify="right", width=12)
    hashes_table.add_column(style=palette["hash_value"])
    if record_dict.get("hash"):
        hashes_table.add_row("SHA-256:", record_dict["hash"])
    if record_dict.get("validation_hash"):
        hashes_table.add_row("BLAKE3:", record_dict["validation_hash"])
    if record_dict.get("quick_hash"):
        hashes_table.add_row("QUICK:", record_dict["quick_hash"])
    if record_dict.get("similarity_hash"):
        hashes_table.add_row("TLSH:", record_dict["similarity_hash"])
    renderables.append(Group(Text.from_markup(f"[{palette['section_title']}]🔑 Hashes[/]"), hashes_table))
    renderables.append(Text(""))

    file_info_table = Table(box=None, show_header=False, padding=(0, 1))
    file_info_table.add_column(style=palette["key"], justify="right", width=12)
    file_info_table.add_column(style=primary_color)
    local_info = record_dict.get("local_filesystem", {})
    base_info = record_dict.get("annotations", {}).get("file/base", {}).get("record", {})
    if access_text:
        file_info_table.add_row("Access:", access_text)
    if local_info.get("full_path"):
        file_info_table.add_row("Full Path:", escape(local_info["full_path"]))
    if local_info.get("date_modified"):
        file_info_table.add_row(
            "Modified:",
            datetime.datetime.fromisoformat(local_info["date_modified"]).strftime("%Y-%m-%d %H:%M:%S"),
        )
    if base_info:
        file_info_table.add_row("Name:", base_info.get("name"))
        file_info_table.add_row("Size:", human_filesize(base_info.get("size", 0)))
        file_info_table.add_row("Media Type:", base_info.get("media_type"))
    renderables.append(
        Group(
            Text.from_markup(f"[{palette['section_title']}]📄 File Info[/]"),
            file_info_table,
        )
    )
    renderables.append(Text(""))

    tags = record_dict.get("tags", [])
    tags_table = Table(box=None, show_header=False, padding=(0, 2))
    tags_table.add_column(style=palette["key"], justify="right")
    tags_table.add_column()
    if tags:
        for tag in tags:
            tag_style = palette["tag_private"] if tag.get("private") else palette["tag_public"]
            tag_value = Text.assemble(
                (f"{tag.get('value')} ", tag_style),
                (f"({'private' if tag.get('private') else 'public'})", palette["tag_subtext"]),
            )
            tag_id = tag.get("id")
            if tag_id:
                tag_value.append(f" [id: {tag_id}]", style=palette["tag_subtext"])
            tags_table.add_row(f"{tag.get('name')}:", tag_value)
    else:
        tags_table.add_row("", Text("No tags found.", style=palette["info"]))
    renderables.append(Group(Text.from_markup(f"[{palette['section_title']}]🔖 Tags[/]"), tags_table))
    renderables.append(Text(""))

    annotations = record_dict.get("annotations", {})
    if annotations:
        for key, value in annotations.items():
            if key == "file/base" or value is None:
                continue

            items_to_render = value if isinstance(value, list) else [value]
            if not items_to_render:
                continue

            first_item = items_to_render[0]
            is_stub = isinstance(first_item, dict) and "record" not in first_item

            title_part = key.split("/")[-1]
            anno_title = f"{title_part.replace('_', ' ').title()} Info"

            renderables.append(Text.from_markup(f"[{palette['section_title']}]📊 {anno_title}[/]"))

            if is_stub:
                for i, item in enumerate(items_to_render):
                    if not isinstance(item, dict):
                        continue

                    if i > 0:
                        renderables.append(Rule(style=palette.get("info", "dim")))

                    annotation_table = Table.grid(padding=(0, 1, 0, 2), expand=False)
                    annotation_table.add_column(style=palette["key"], justify="right", width=12)
                    annotation_table.add_column(style=palette["primary_value"])
                    _build_dynamic_table(table=annotation_table, data=item, is_stub=True)
                    renderables.append(annotation_table)
            else:
                record_to_render = items_to_render[0].get("record", items_to_render[0])
                if not isinstance(record_to_render, dict):
                    continue

                display_fields = MEDIAINFO_DISPLAY_FIELDS if key == "file/mediainfo" else None
                max_width = _get_max_key_width(record_to_render, display_fields=display_fields)
                annotation_table = Table(box=None, show_header=False, padding=(0, 1))
                annotation_table.add_column(style=palette["key"], justify="right", min_width=max_width + 2)
                annotation_table.add_column(style=palette["primary_value"])
                _build_dynamic_table(table=annotation_table, data=record_to_render, display_fields=display_fields)
                renderables.append(annotation_table)

            renderables.append(Text(""))

    return Panel(
        Group(*renderables),
        title=f"[{panel_title_style}]{display_title}[/]",
        border_style=border,
        expand=False,
        padding=(1, 2),
    )
