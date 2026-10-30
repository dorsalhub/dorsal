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

from typing import Any

import pytest
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from dorsal.cli.themes import get_ui_theme
from dorsal.cli.themes.borders import get_borders
from dorsal.cli.themes.icons import get_icons
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.cli.views.layout import KeyValues, Trimmed, is_borderless, key_values, message, section, table

BORDERLESS: Any = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": None}
ROUNDED: Any = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": box.ROUNDED}


def _render(renderable, width: int = 80, legacy_windows: bool = False) -> list[str]:
    console = Console(legacy_windows=legacy_windows, width=width)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get().splitlines()


def test_defaults_are_borderless_without_emoji(monkeypatch):
    monkeypatch.delenv("DORSAL_BORDERS", raising=False)
    monkeypatch.delenv("DORSAL_ICONS", raising=False)

    ui = get_ui_theme()

    assert ui["borders"] is None
    assert set(ui["icons"].values()) == {""}
    assert get_borders() is None
    assert get_borders("no-such-style") is None
    assert get_borders("rounded") is box.ROUNDED
    assert get_icons("no-such-set") == get_icons("none")


def test_border_override_opts_in(monkeypatch):
    monkeypatch.setenv("DORSAL_BORDERS", "heavy")
    assert get_ui_theme()["borders"] is box.HEAVY
    assert get_ui_theme(border_override="none")["borders"] is None


def test_is_borderless():
    assert is_borderless(BORDERLESS)
    assert not is_borderless(ROUNDED)


def test_key_values_aligns_keys_per_level():
    kv = KeyValues()
    kv.add("Name", "report.pdf")
    kv.add("Media type", "application/pdf")
    nested = kv.section("Video")
    nested.add("Width", "720")
    nested.add("Frame rate", "29.97")
    kv.add("Size", "2 KiB")

    assert _render(kv) == [
        "Name        report.pdf",
        "Media type  application/pdf",
        "Video",
        "  Width       720",
        "  Frame rate  29.97",
        "Size        2 KiB",
    ]


def test_key_values_wraps_values_under_their_column():
    kv = KeyValues()
    kv.add("Settings", "alpha beta gamma delta epsilon zeta")

    assert _render(kv, width=34) == [
        "Settings  alpha beta gamma delta",
        "          epsilon zeta",
    ]


def test_key_values_moves_value_below_a_long_key_on_narrow_consoles():
    kv = KeyValues()
    kv.add("an_unusually_long_field_name", "a value that cannot fit beside it")

    lines = _render(kv, width=40)

    assert lines[0] == "an_unusually_long_field_name"
    assert lines[1].startswith("    a value")


def test_key_values_items_and_note():
    kv = KeyValues()
    items = kv.items("blocks", "3 items")
    first = items.add()
    first.add("id", "1")
    first.add("block_type", "box")
    items.add().add("id", "2")
    items.more("… 1 more")

    assert _render(kv) == [
        "blocks  3 items",
        "  - id          1",
        "    block_type  box",
        "  - id  2",
        "  … 1 more",
    ]


def test_key_values_values_are_not_markup():
    kv = KeyValues()
    kv.add("path", "[bold]x[/bold]")
    assert _render(kv) == ["path  [bold]x[/bold]"]


def test_key_values_helper_skips_none_and_uses_palette():
    kv = key_values(BORDERLESS, [("a", "1"), ("b", None)])
    assert len(kv) == 1
    assert kv.key_style == DEFAULT_PALETTE["key"]
    assert not key_values(BORDERLESS)


def test_section_borderless_indents_body_and_trims_whitespace():
    lines = _render(section("Summary", Text("line one\nline two"), BORDERLESS))
    assert lines == ["Summary", "  line one", "  line two"]


def test_section_bordered_is_a_panel():
    panel = section("Summary", Text("body"), ROUNDED)
    assert isinstance(panel, Panel)
    assert panel.box is box.ROUNDED
    assert _render(panel)[0].startswith("╭─ Summary ")


@pytest.mark.parametrize("body", ["It [bold]worked[/].", Text("It worked.")])
def test_message_borderless_is_one_line(body):
    assert _render(message("Done", body, BORDERLESS, level="success")) == ["Done: It worked."]


def test_message_multiline_falls_back_to_section():
    assert _render(message("Warnings", "- one\n- two", BORDERLESS, level="warning")) == [
        "Warnings",
        "  - one",
        "  - two",
    ]


def test_table_borderless_has_two_space_gaps_and_no_trailing_whitespace():
    t = table(BORDERLESS, title="Files")
    t.add_column("Name")
    t.add_column("Size")
    t.add_row("a.pdf", "2 KiB")
    t.add_row("movie.mkv", "19 MiB")

    assert _render(t) == [
        "Files",
        "Name       Size",
        "a.pdf      2 KiB",
        "movie.mkv  19 MiB",
    ]


def test_table_bordered_uses_theme_box():
    t = table(ROUNDED)
    t.add_column("Name")
    t.add_row("a")
    assert t.box is box.ROUNDED


BORDER_CORNERS = [
    ("rounded", "╭", "┌"),
    ("heavy", "┏", "┌"),
    ("square", "┌", "┌"),
    ("double", "╔", "╔"),
    ("ascii", "+", "+"),
]


@pytest.mark.parametrize(("name", "corner", "legacy_corner"), BORDER_CORNERS)
@pytest.mark.parametrize("legacy_windows", [False, True])
def test_section_corners_follow_the_style_and_console(name, corner, legacy_windows, legacy_corner):
    ui: Any = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": get_borders(name)}

    first_line = _render(section("Summary", Text("body"), ui), legacy_windows=legacy_windows)[0]

    assert first_line[0] == (legacy_corner if legacy_windows else corner)
    assert " Summary " in first_line


@pytest.mark.parametrize(("name", "corner", "legacy_corner"), BORDER_CORNERS)
@pytest.mark.parametrize("legacy_windows", [False, True])
def test_table_corners_follow_the_style_and_console(name, corner, legacy_windows, legacy_corner):
    ui: Any = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": get_borders(name)}
    t = table(ui)
    t.add_column("Name")
    t.add_row("a")

    assert _render(t, legacy_windows=legacy_windows)[0][0] == (legacy_corner if legacy_windows else corner)


def test_table_borderless_title_set_later_is_a_heading():
    t = table(BORDERLESS)
    t.add_column("Name")
    t.add_row("a")
    t.title = "A rather long title for a narrow table"

    assert _render(t) == ["A rather long title for a narrow table", "Name", "a"]


def test_trimmed_str_wraps_to_width_without_trailing_whitespace():
    path = "/" + "long-directory-name/" * 6 + "file.json"

    lines = _render(Trimmed(f"Report saved to: [cyan]{path}[/]"), width=40)

    assert lines[0] == "Report saved to:"
    assert max(len(line) for line in lines) <= 40
    assert all(line == line.rstrip() for line in lines)
    assert "".join(lines[1:]) == path
