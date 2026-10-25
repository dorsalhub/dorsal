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
from typing import Any

from rich.box import Box
from rich.console import Group, RenderableType
from rich.text import Text

from dorsal.cli.themes.icons import get_icons
from dorsal.cli.views.layout import KeyValues, heading, section

CORE_ANNOTATION_NAMES = {
    "file/pdf": "PDF",
    "file/mediainfo": "MediaInfo",
    "file/ebook": "Ebook",
    "file/office": "Office",
}

ENVELOPE_KEYS = {
    "source",
    "private",
    "schema_version",
    "group",
    "id",
    "annotation_id",
    "date_created",
    "date_modified",
    "file_hash",
}

INLINE_DICT_MAX_KEYS = 6
INLINE_DICT_MAX_WIDTH = 60


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and not value)


def _is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def _inline_dict(value: dict) -> str | None:
    if len(value) > INLINE_DICT_MAX_KEYS or not all(_is_scalar(v) for v in value.values()):
        return None
    rendered = " ".join(f"{k}={v}" for k, v in value.items() if not _is_empty(v))
    if not rendered or len(rendered) > INLINE_DICT_MAX_WIDTH:
        return None
    return rendered


def _build_annotation_table(
    kv: KeyValues,
    data: dict,
    display_fields: set | None = None,
    max_items: int = 3,
    preserve_whitespace: bool = False,
) -> None:
    """Adds the fields of an annotation record to `kv`, nesting dicts and lists of dicts."""
    for key, value in data.items():
        if key == "file_hash" or _is_empty(value):
            continue
        if display_fields and key not in display_fields:
            continue

        if isinstance(value, dict):
            if display_fields:
                value = {k: v for k, v in value.items() if k in display_fields}
                if not value:
                    continue
            inline = _inline_dict(value)
            if inline is not None:
                kv.add(key, inline)
            else:
                _build_annotation_table(
                    kv.section(key), value, display_fields, max_items, preserve_whitespace=preserve_whitespace
                )

        elif isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], dict):
                _build_annotation_table(
                    kv.section(key), value[0], display_fields, max_items, preserve_whitespace=preserve_whitespace
                )
            elif all(_is_scalar(item) for item in value):
                value_str = ", ".join(str(item) for item in value[:max_items])
                if len(value) > max_items:
                    value_str += f", … (+{len(value) - max_items} more)"
                kv.add(key, value_str)
            else:
                items = kv.items(key, f"{len(value)} items" if len(value) > 1 else None, style="dim")
                for entry in value[:max_items]:
                    if isinstance(entry, dict):
                        _build_annotation_table(
                            items.add(), entry, display_fields, max_items, preserve_whitespace=preserve_whitespace
                        )
                    else:
                        items.add().add("value", str(entry))
                if len(value) > max_items:
                    items.more(f"… {len(value) - max_items} more")

        elif isinstance(value, str):
            kv.add(key, value if preserve_whitespace else " ".join(value.split()))

        else:
            kv.add(key, str(value))


def to_local_time(value: datetime.datetime) -> datetime.datetime:
    """Return `value` in the local time zone, or unchanged if the platform cannot convert it."""
    try:
        return value.astimezone()
    except (OSError, OverflowError, ValueError):
        return value


def _annotation_title(schema_id: str) -> str:
    if schema_id in CORE_ANNOTATION_NAMES:
        return CORE_ANNOTATION_NAMES[schema_id]
    if schema_id.startswith("file/"):
        return schema_id.split("/", 1)[1].replace("_", " ").replace("-", " ").title()
    return schema_id


def _describe_source(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    src_id = source.get("id")
    src_type = source.get("type")
    if not src_id and not src_type:
        return None
    description = str(src_id or src_type)
    if src_type and src_id and src_type != "Model":
        description = f"{src_id} ({str(src_type).lower()})"
    part = source.get("execution_part")
    total_parts = source.get("execution_total_parts")
    if part and total_parts:
        description += f", part {part} of {total_parts}"
    return description


def create_file_info_panel(
    *,
    record_dict: dict,
    title: str,
    private: bool | None,
    palette: dict[str, str],
    override_title_style: str | None = None,
    override_border_style: str | None = None,
    source: str | None = None,
    icons: dict[str, str] | None = None,
    box_style: Box | None = None,
    preserve_whitespace: bool = False,
) -> RenderableType:
    """Renders a file record: a panel when `box_style` is set, otherwise headed, indented sections.

    `title` may contain Rich markup.
    """
    from dorsal.file.utils.size import human_filesize
    from dorsal.cli.views.mediainfo import MEDIAINFO_DISPLAY_FIELDS

    if icons is None:
        icons = get_icons()

    border = override_border_style or (palette["panel_border_alt"] if private else palette["panel_border"])
    title_style = override_title_style or (palette["panel_title_alt"] if private else palette["panel_title"])
    primary_color = palette["primary_value_alt"] if private else palette["primary_value"]
    key_style = palette.get("key", "dim")
    section_style = palette.get("section_title", "bold")
    dim_style = palette.get("info", "dim")

    def new_kv() -> KeyValues:
        return KeyValues(key_style=key_style, value_style=primary_color)

    def add_section(name: str, body: RenderableType, suffix: str | None = None) -> None:
        line = Text(name, style=section_style)
        if suffix:
            line.append(f"  {suffix}", style=dim_style)
        renderables.append(section(line, body, borderless_ui))
        renderables.append(Text(""))

    borderless_ui: Any = {"palette": palette, "borders": None}
    renderables: list[RenderableType] = []

    local_info: dict[str, Any] = record_dict.get("local_filesystem", {})
    annotations: dict[str, Any] = record_dict.get("annotations", {})
    base_info = (annotations.get("file/base") or {}).get("record", {})
    all_hash_ids = base_info.get("all_hash_ids") or {}

    file_kv = new_kv()
    if private:
        file_kv.add("Access", Text("Private", style=palette["access_private"]))
    if local_info.get("local_record_id"):
        file_kv.add("Record ID", str(local_info["local_record_id"]), style=palette.get("hash_value", "magenta"))
    if local_info.get("is_symlink"):
        file_kv.add("Type", Text("Symbolic link", style=f"{palette['primary_value']} italic"))
        if local_info.get("full_path"):
            file_kv.add("Link path", local_info["full_path"])
        file_kv.add("Target", str(local_info.get("symlink_target", "Unknown")))
    elif local_info.get("full_path"):
        file_kv.add("Path", local_info["full_path"])
    if local_info.get("date_modified"):
        modified = to_local_time(datetime.datetime.fromisoformat(local_info["date_modified"]))
        file_kv.add("Modified", modified.strftime("%Y-%m-%d %H:%M:%S"))
    if base_info:
        if base_info.get("name"):
            file_kv.add("Name", str(base_info["name"]))
        file_kv.add("Size", human_filesize(base_info.get("size", 0)))
        if base_info.get("media_type"):
            file_kv.add("Media type", str(base_info["media_type"]))
    if file_kv:
        add_section(f"{icons['file']}File", file_kv)

    hash_display_order = [
        ("SHA-256", record_dict.get("hash") or all_hash_ids.get("SHA-256")),
        ("BLAKE3", all_hash_ids.get("BLAKE3")),
        ("MD5", all_hash_ids.get("MD5")),
        ("SHA-1", all_hash_ids.get("SHA-1")),
        ("QUICK", record_dict.get("quick_hash") or all_hash_ids.get("QUICK")),
        ("DORSAL", record_dict.get("validation_hash") or all_hash_ids.get("DORSAL")),
        ("TLSH", record_dict.get("similarity_hash") or all_hash_ids.get("TLSH")),
    ]
    hashes_kv = new_kv()
    for label, val in hash_display_order:
        if val:
            hashes_kv.add(label, str(val), style=palette["hash_value"])
    if hashes_kv:
        add_section(f"{icons['key']}Hashes", hashes_kv)

    tags = record_dict.get("tags", [])
    if tags:
        tags_kv = new_kv()
        for tag in tags:
            tag_style = palette["tag_private"] if tag.get("private") else palette["tag_public"]
            tag_value = Text.assemble(
                (f"{tag.get('value')} ", tag_style),
                (f"({'private' if tag.get('private') else 'public'})", palette["tag_subtext"]),
            )
            if tag.get("id"):
                tag_value.append(f" [id: {tag['id']}]", style=palette["tag_subtext"])
            tags_kv.add(str(tag.get("name")), tag_value)
        add_section(f"{icons['tags']}Tags", tags_kv)

    for key, value in annotations.items():
        if key == "file/base" or value is None:
            continue

        items_to_render = value if isinstance(value, list) else [value]
        unwrapped_items: list[dict] = []
        for item in items_to_render:
            if isinstance(item, dict) and "annotations" in item and "record" not in item:
                unwrapped_items.extend(i for i in item["annotations"] if isinstance(i, dict))
            elif isinstance(item, dict):
                unwrapped_items.append(item)
        if not unwrapped_items:
            continue

        display_fields = MEDIAINFO_DISPLAY_FIELDS if key == "file/mediainfo" else None
        single = len(unwrapped_items) == 1
        core = key.startswith("file/")
        bodies: list[RenderableType] = []

        for item in unwrapped_items:
            item_kv = new_kv()
            source_text = None if core else _describe_source(item.get("source"))
            if not single and source_text:
                item_kv.add("Source", source_text)
            anno_id = item.get("annotation_id") or item.get("id")
            if anno_id:
                item_kv.add("ID", str(anno_id))

            record_to_render = item.get("record", item)
            filtered_record = {k: v for k, v in record_to_render.items() if k not in ENVELOPE_KEYS}
            _build_annotation_table(
                item_kv, filtered_record, display_fields=display_fields, preserve_whitespace=preserve_whitespace
            )
            bodies.append(item_kv)

        if not single:
            suffix: str | None = f"{len(unwrapped_items)} records"
        else:
            suffix = None if core else _describe_source(unwrapped_items[0].get("source"))
        body: RenderableType = bodies[0] if single else Group(*_join(bodies))
        add_section(f"{icons['info']}{_annotation_title(key)}", body, suffix)

    if renderables:
        renderables.pop()

    display_title = Text.from_markup(title, style=title_style)
    if source == "cache":
        display_title.append(" (from cache)", style=dim_style)

    if box_style is None:
        return Group(display_title, Text(""), *renderables)

    return section(
        display_title,
        Group(*renderables),
        {"palette": palette, "icons": icons, "borders": box_style},
        border_style=border,
    )


def _join(bodies: list[RenderableType]) -> list[RenderableType]:
    joined: list[RenderableType] = []
    for i, body in enumerate(bodies):
        if i:
            joined.append(Text(""))
        joined.append(body)
    return joined
