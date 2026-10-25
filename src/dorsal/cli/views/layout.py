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

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping, Union, cast

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.padding import Padding
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

INDENT = 2
GAP = 2
MIN_VALUE_WIDTH = 20


def is_borderless(ui_context: Mapping[str, Any]) -> bool:
    """Returns True when the active theme draws no borders."""
    return ui_context.get("borders") is None


def _as_text(value: str | Text, style: str = "") -> Text:
    if isinstance(value, Text):
        return value
    return Text.from_markup(value, style=style)


def _rstrip_line(line: list[Segment]) -> list[Segment]:
    while line:
        segment = line[-1]
        if segment.control or (segment.style is not None and segment.style.bgcolor is not None):
            break
        stripped = segment.text.rstrip(" ")
        if stripped:
            line[-1] = Segment(stripped, segment.style, segment.control)
            break
        line.pop()
    return line


class Trimmed:
    """Renders another renderable with trailing whitespace removed from every line."""

    def __init__(self, renderable: RenderableType) -> None:
        self.renderable = renderable

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        new_line = Segment.line()
        for line in console.render_lines(self.renderable, options, pad=False):
            yield from _rstrip_line(line)
            yield new_line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self.renderable)


class PlainTable(Table):
    """A Rich table that leaves no trailing whitespace at the end of its lines.

    `heading`, if set, is printed above the table at full width instead of as a title wrapped to the table's width.
    """

    heading: Text | None = None

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        title = self.title
        if self.heading is not None:
            yield self.heading
        elif title is not None:
            yield _as_text(title, style=str(self.title_style or "bold"))
        new_line = Segment.line()
        self.title = None
        try:
            segments = list(super().__rich_console__(console, options))
        finally:
            self.title = title
        for line in Segment.split_lines(cast(Iterable[Segment], segments)):
            yield from _rstrip_line(line)
            yield new_line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        measurement = super().__rich_measure__(console, options)
        if self.heading is None:
            return measurement
        width = min(cell_len(self.heading.plain), options.max_width)
        return Measurement(measurement.minimum, max(measurement.maximum, width))


def table(ui_context: UIContext, *, title: str | Text | None = None, **kwargs: Any) -> Table:
    """Creates a table styled for the active theme: bordered with the theme's box, or plain columns without one.

    Args:
        ui_context: The active UI context.
        title: Optional title, shown left-aligned above the table.
        **kwargs: Passed through to `rich.table.Table`.
    """
    palette = ui_context["palette"]
    kwargs.setdefault("header_style", palette.get("table_header", "bold"))
    kwargs.setdefault("title_justify", "left")
    kwargs.setdefault("title_style", palette.get("section_title", "bold"))
    borders = ui_context["borders"]
    if borders is None:
        kwargs.setdefault("padding", (0, GAP, 0, 0))
        kwargs.setdefault("pad_edge", False)
        kwargs.setdefault("show_edge", False)
        plain = PlainTable(box=None, **kwargs)
        if title is not None:
            plain.heading = _as_text(title, style=kwargs.get("title_style") or "bold")
        return plain
    return Table(title=title, box=borders, **kwargs)


def heading(title: str | Text, style: str = "bold") -> Text:
    """Returns a heading line. `title` may contain Rich markup."""
    return _as_text(title, style=style)


def section(
    title: str | Text | None,
    body: RenderableType,
    ui_context: UIContext,
    *,
    title_style: str | None = None,
    border_style: str | None = None,
    indent: bool = True,
    **panel_kwargs: Any,
) -> RenderableType:
    """Wraps `body` under `title`: a panel when the theme has borders, otherwise a heading with the body indented.

    Args:
        title: The heading or panel title. May contain Rich markup.
        body: The content.
        ui_context: The active UI context.
        title_style: Style for the title. Defaults to the palette's `panel_title`.
        border_style: Style for the panel border. Defaults to the palette's `panel_border`.
        indent: Indent the body under the heading when borderless.
        **panel_kwargs: Passed through to `rich.panel.Panel` when the theme has borders.
    """
    palette = ui_context["palette"]
    style = title_style or palette.get("panel_title", "bold")
    borders = ui_context["borders"]
    if borders is None:
        content = Padding(body, (0, 0, 0, INDENT)) if indent and title is not None else body
        if title is None:
            return content
        return Group(heading(title, style), Trimmed(content))
    panel_kwargs.setdefault("expand", False)
    panel_kwargs.setdefault("padding", (1, 2))
    panel_kwargs.setdefault("title_align", "left")
    return Panel(
        body,
        title=heading(title, style) if title is not None else None,
        border_style=border_style or palette.get("panel_border", "blue"),
        box=borders,
        **panel_kwargs,
    )


def message(
    title: str,
    body: RenderableType | str,
    ui_context: UIContext,
    *,
    level: str = "info",
    **panel_kwargs: Any,
) -> RenderableType:
    """Formats a titled status message (`level` is one of info, success, warning, error).

    Borderless, a one-line body is printed after the title as `Title: body`; longer bodies go under the title.
    """
    palette = ui_context["palette"]
    title_style = palette.get(f"panel_title_{level}", palette.get(level, "bold"))
    border_style = palette.get(f"panel_border_{level}", "")
    if is_borderless(ui_context):
        if isinstance(body, str) and "\n" not in body:
            return Text.assemble(Text(f"{title}: ", style=title_style), Text.from_markup(body))
        if isinstance(body, Text) and "\n" not in body.plain:
            return Text.assemble(Text(f"{title}: ", style=title_style), body)
    content = Text.from_markup(body) if isinstance(body, str) else body
    return section(title, content, ui_context, title_style=title_style, border_style=border_style, **panel_kwargs)


Value = Union[str, Text, None]


class KeyValues:
    """Left-aligned key/value rows that nest by indentation, with keys aligned within each level.

    Values wrap under their own column. Nested sections, and lists of nested items marked with `-`, are added with
    `section` and `items`.
    """

    def __init__(self, key_style: str = "dim", value_style: str = "") -> None:
        self.key_style = key_style
        self.value_style = value_style
        self.rows: list[tuple[Text, Text | None, KeyValues | _Items | None]] = []

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def _key(self, key: str | Text) -> Text:
        return key if isinstance(key, Text) else Text(key, style=self.key_style)

    def _value(self, value: Value, style: str | None) -> Text | None:
        if value is None:
            return None
        if isinstance(value, Text):
            return value
        return Text(str(value), style=self.value_style if style is None else style)

    def add(self, key: str | Text, value: Value, style: str | None = None) -> KeyValues:
        """Adds a row. A `str` value is shown verbatim (no markup) in `style`, or the default value style."""
        self.rows.append((self._key(key), self._value(value, style), None))
        return self

    def section(self, key: str | Text, summary: Value = None, style: str | None = None) -> KeyValues:
        """Adds a nested group under `key`, with an optional summary on the key's own line, and returns it."""
        child = KeyValues(self.key_style, self.value_style)
        self.rows.append((self._key(key), self._value(summary, style), child))
        return child

    def items(self, key: str | Text, summary: Value = None, style: str | None = None) -> _Items:
        """Adds a list of nested groups under `key`, each marked with `-`, and returns it."""
        child = _Items(self.key_style, self.value_style)
        self.rows.append((self._key(key), self._value(summary, style), child))
        return child

    def _lines(self, console: Console, width: int, indent: int) -> list[Text]:
        key_width = max((cell_len(key.plain) for key, _, _ in self.rows), default=0)
        lines: list[Text] = []
        for key, value, child in self.rows:
            if value is None or not value.plain:
                lines.append(Text(" " * indent) + key)
            else:
                value_col = indent + key_width + GAP
                if width - value_col < min(MIN_VALUE_WIDTH, cell_len(value.plain)):
                    value_col = indent + INDENT * 2
                    lines.append(Text(" " * indent) + key)
                    first_prefix = Text(" " * value_col)
                else:
                    first_prefix = Text(" " * indent) + key + Text(" " * (value_col - indent - cell_len(key.plain)))
                wrapped = value.wrap(console, max(width - value_col, 1), justify="default", overflow="fold")
                for i, line in enumerate(wrapped):
                    prefix = first_prefix if i == 0 else Text(" " * value_col)
                    lines.append(prefix + line)
            if child is not None:
                lines.extend(child._lines(console, width, indent + INDENT))
        return lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for line in self._lines(console, options.max_width, 0):
            line.rstrip()
            line.no_wrap = True
            line.overflow = "ignore"
            yield line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        widths = [cell_len(line.plain) for line in self._lines(console, options.max_width, 0)]
        return Measurement(1, min(max(widths, default=1), options.max_width))


class _Items:
    """A list of nested key/value groups, rendered as `- ` items, with an optional trailing note."""

    def __init__(self, key_style: str, value_style: str) -> None:
        self.key_style = key_style
        self.value_style = value_style
        self.entries: list[KeyValues] = []
        self.note: Text | None = None

    def add(self) -> KeyValues:
        """Adds an item and returns it for filling in."""
        entry = KeyValues(self.key_style, self.value_style)
        self.entries.append(entry)
        return entry

    def more(self, note: str | Text) -> None:
        """Sets a note shown after the items, such as how many were left out."""
        self.note = note if isinstance(note, Text) else Text(note, style="dim italic")

    def _lines(self, console: Console, width: int, indent: int) -> list[Text]:
        lines: list[Text] = []
        for entry in self.entries:
            entry_lines = entry._lines(console, width, indent + INDENT)
            if not entry_lines:
                continue
            lines.append(Text(" " * indent) + Text("- ", style="dim") + entry_lines[0][indent + INDENT :])
            lines.extend(entry_lines[1:])
        if self.note is not None:
            lines.append(Text(" " * indent) + self.note)
        return lines


def key_values(ui_context: UIContext, rows: Iterable[tuple[str, Value]] = (), **kwargs: Any) -> KeyValues:
    """Creates a `KeyValues` styled from the active palette, optionally filled from `(key, value)` pairs.

    Rows whose value is None are skipped.
    """
    palette = ui_context["palette"]
    kwargs.setdefault("key_style", palette.get("key", "dim"))
    kwargs.setdefault("value_style", palette.get("primary_value", ""))
    kv = KeyValues(**kwargs)
    for key, value in rows:
        if value is not None:
            kv.add(key, value)
    return kv
