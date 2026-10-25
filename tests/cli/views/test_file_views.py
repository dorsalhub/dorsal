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
import os
import time

import pytest
from rich.console import Console
from dorsal.cli.views.file import create_file_info_panel, _build_annotation_table
from dorsal.cli.views.layout import KeyValues

DUMMY_FILE_RECORD = {
    "hash": "a" * 64,
    "validation_hash": "b" * 64,
    "quick_hash": "c" * 64,
    "similarity_hash": "d" * 64,
    "tags": [
        {"name": "project", "value": "apollo", "private": False, "id": "123"},
        {"name": "status", "value": "secret", "private": True},
    ],
    "annotations": {
        "file/base": {"record": {"name": "test_file.txt", "size": 1024, "media_type": "text/plain"}},
        "file/pdf": {"record": {"page_count": 5, "author": "Test Author"}},
        "something/anything": [
            {
                "source": {"type": "manual", "id": "user_1"},
                "date_modified": "2023-01-01T12:00:00Z",
                "url": "file/hash/123",
                "id": "anno_1",
            }
        ],
    },
    "local_filesystem": {"full_path": "/tmp/test_file.txt", "date_modified": datetime.datetime.now().isoformat()},
}

DUMMY_PALETTE = {
    "panel_border": "blue",
    "panel_border_alt": "red",
    "panel_title": "bold blue",
    "panel_title_alt": "bold red",
    "primary_value": "white",
    "primary_value_alt": "yellow",
    "key": "cyan",
    "hash_value": "green",
    "section_title": "bold white",
    "access_private": "red",
    "access_public": "green",
    "tag_private": "red",
    "tag_public": "blue",
    "tag_subtext": "dim",
    "info": "dim",
}


def test_create_file_info_panel_public(capsys):
    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Test File", private=False, palette=DUMMY_PALETTE
    )

    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "Test File" in output
    assert "test_file.txt" in output
    assert "apollo" in output
    assert "page_count" in output
    assert "user_1 (manual)" in output


def test_create_file_info_panel_private():
    """Smoke test for private file panel generation."""
    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Private File", private=True, palette=DUMMY_PALETTE
    )
    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "Access" in output
    assert "Private" in output

    assert "Private File" in output


def test_create_file_info_panel_from_cache():
    """Test cache source labeling."""
    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Cached File", private=False, palette=DUMMY_PALETTE, source="cache"
    )
    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "from cache" in output


def test_create_file_info_panel_minimal_data():
    """Test rendering with minimal data (empty dictionaries) to check for crashes."""
    minimal_record = {"hash": "123"}
    panel = create_file_info_panel(
        record_dict=minimal_record,
        title="Empty File",
        private=None,
        palette=DUMMY_PALETTE,
    )
    console = Console()
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()
    assert "SHA-256" in output


def _render_kv(kv: KeyValues, width: int = 120) -> str:
    console = Console(width=width)
    with console.capture() as capture:
        console.print(kv)
    return capture.get()


def test_build_annotation_table_dict_logic():
    """Nested dicts, lists, skipped keys and empty values."""
    kv = KeyValues()
    data = {
        "file_hash": "this_should_be_skipped",
        "empty_string": "",
        "none_value": None,
        "empty_list": [],
        "zero": 0,
        "simple_key": "simple_value",
        "nested_dict": {"inner_key": "inner_value", "deeper": {"leaf": [1, 2]}},
        "small_dict": {"x": 1, "y": 2},
        "simple_list": [1, 2, "three"],
        "complex_list": [{"list_dict_key": "val1"}, {"list_dict_key2": "val2"}],
    }

    _build_annotation_table(kv, data)
    lines = _render_kv(kv).splitlines()

    assert lines == [
        "zero          0",
        "simple_key    simple_value",
        "nested_dict",
        "  inner_key  inner_value",
        "  deeper",
        "    leaf  1, 2",
        "small_dict    x=1 y=2",
        "simple_list   1, 2, three",
        "complex_list  2 items",
        "  - list_dict_key  val1",
        "  - list_dict_key2  val2",
    ]


def test_build_annotation_table_truncates_lists():
    """Long lists show the first items and how many were left out."""
    kv = KeyValues()
    data = {"scalars": list(range(10)), "blocks": [{"id": i, "text": f"block {i}"} for i in range(5)]}

    _build_annotation_table(kv, data, max_items=2)
    output = _render_kv(kv)

    assert "0, 1, … (+8 more)" in output
    assert "blocks   5 items" in output
    assert "  - id    0" in output
    assert "    text  block 1" in output
    assert "block 2" not in output
    assert "  … 3 more" in output


def test_build_annotation_table_single_item_list_is_a_section():
    """A list holding one dict is shown as a nested section, without a `-` marker."""
    kv = KeyValues()
    _build_annotation_table(kv, {"Audio": [{"Format": "AC-3", "Channels": "2"}]})

    assert _render_kv(kv).splitlines() == ["Audio", "  Format    AC-3", "  Channels  2"]


def test_build_annotation_table_display_fields():
    """`display_fields` filters keys at every level."""
    kv = KeyValues()
    data = {"keep_me": "yes", "drop_me": "no", "nested": {"keep_inner": "yes", "drop_inner": "no", "more": 1}}

    _build_annotation_table(kv, data, display_fields={"keep_me", "nested", "keep_inner"})
    output = _render_kv(kv)

    assert "keep_me" in output
    assert "drop_me" not in output
    assert "nested" in output
    assert "keep_inner" in output
    assert "drop_inner" not in output


def test_build_annotation_table_collapses_whitespace():
    kv = KeyValues()
    _build_annotation_table(kv, {"text": "a\n  b"})
    assert "a b" in _render_kv(kv)

    kv = KeyValues()
    _build_annotation_table(kv, {"text": "a\nb"}, preserve_whitespace=True)
    assert _render_kv(kv).splitlines() == ["text  a", "      b"]


def test_create_file_info_panel_borderless_layout():
    """Borderless output has the title, headed sections with left-aligned keys, and no trailing whitespace."""
    record = {
        "local_filesystem": {"full_path": "/tmp/test_file.txt"},
        "annotations": {
            "file/base": {"record": {"name": "test_file.txt", "size": 1024, "media_type": "text/plain"}},
            "file/pdf": {"source": {"type": "Model", "id": "dorsal/pdf"}, "record": {"page_count": 5}},
            "open/classification": {"source": {"type": "Model", "id": "acme/cls"}, "record": {"labels": ["a"]}},
        },
    }

    panel = create_file_info_panel(record_dict=record, title="test_file.txt", private=None, palette=DUMMY_PALETTE)
    console = Console(width=100)
    with console.capture() as capture:
        console.print(panel)
    lines = capture.get().splitlines()

    assert lines == [
        "test_file.txt",
        "",
        "File",
        "  Path        /tmp/test_file.txt",
        "  Name        test_file.txt",
        "  Size        1 KiB",
        "  Media type  text/plain",
        "",
        "PDF",
        "  page_count  5",
        "",
        "open/classification  acme/cls",
        "  labels  a",
    ]


def test_create_file_info_panel_bordered():
    """With a box style the record is drawn in a panel titled with `title`."""
    from rich import box

    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Boxed", private=False, palette=DUMMY_PALETTE, box_style=box.ROUNDED
    )
    console = Console(width=120)
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()

    assert output.startswith("╭─ Boxed ")
    assert "│    Media type  text/plain" in output


def test_create_file_info_panel_annotations_edge_cases():

    record_with_edge_cases = {
        "annotations": {
            "test/empty_list": [],
            "test/wrapped_data": [{"annotations": [{"record": {"hidden_key": "hidden_value"}}]}],
            "test/non_dict_item": ["just a string, not a dict", 42],
            "test/multi_and_source": [
                {
                    "record": {"first_item": "yes"},
                    "source": {
                        "type": "scanner",
                        "id": "s1",
                        "name": "SuperScan",
                        "execution_part": 1,
                        "execution_total_parts": 3,
                    },
                },
                {"record": {"second_item": "yes"}, "source": {"type": "scanner", "id": "s2"}},
            ],
        }
    }

    panel = create_file_info_panel(
        record_dict=record_with_edge_cases, title="Edge Case File", private=False, palette=DUMMY_PALETTE
    )

    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()

    assert "hidden_key" in output
    assert "hidden_value" in output

    assert "2 records" in output
    assert "s1 (scanner), part 1 of 3" in output

    assert "first_item" in output
    assert "second_item" in output

    assert "just a string, not a dict" not in output


def test_display_local_search_results_wide_console():
    """Covers search.py rendering wide tables with Record ID, Modified Date, and SHA256 Hash."""
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes.borders import get_borders
    from rich.console import Console
    from types import SimpleNamespace

    console = Console(width=200)

    ts = 1700000000.0
    records = [
        SimpleNamespace(
            name="file_with_hash.bin",
            size=2048,
            media_type="application/octet-stream",
            local_record_id="rec_1234567890",
            modified_time=ts,
            hash_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        SimpleNamespace(
            name=None,
            size=None,
            media_type=None,
            local_record_id=None,
            modified_time=ts,
            hash_sha256=None,
        ),
    ]

    response = SimpleNamespace(
        records=records,
        pagination=SimpleNamespace(
            start_index=0, record_count=2, current_page=1, page_count=1, end_index=2, has_next=False
        ),
    )

    ui_context = {"palette": DUMMY_PALETTE, "icons": {}, "borders": get_borders("none")}

    with console.capture() as capture:
        display_local_search_results(console, response, ui_context)

    output = capture.get()

    lines = output.splitlines()
    assert lines[0] == "Local search results"
    assert lines[1].startswith("Name ")
    assert all(line == line.rstrip() for line in lines)
    assert not any(ch in output for ch in "│─╭╰┃━")

    assert "Media type" in output
    assert "Record ID" in output
    assert "Modified date" in output
    assert "SHA256 hash" in output

    assert "file_with_hash.bin" in output
    assert "rec_1234567890" in output
    assert datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") in output
    assert "e3b0c442" in output

    assert "Unknown" in output
    assert "N/A" in output
    assert "-" in output


def test_display_local_search_results_wide_console_no_hashes():
    """Covers search.py rendering wide tables when no hashes are present."""
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes.borders import get_borders
    from rich.console import Console
    from types import SimpleNamespace

    console = Console(width=200)

    ts = 1700000000.0
    records = [
        SimpleNamespace(
            name="no_hash.txt",
            size=1024,
            media_type="text/plain",
            local_record_id="rec_0001",
            modified_time=ts,
            hash_sha256=None,
        ),
    ]

    response = SimpleNamespace(
        records=records,
        pagination=SimpleNamespace(
            start_index=0, record_count=1, current_page=1, page_count=1, end_index=1, has_next=False
        ),
    )

    ui_context = {"palette": DUMMY_PALETTE, "icons": {}, "borders": get_borders("none")}

    with console.capture() as capture:
        display_local_search_results(console, response, ui_context)

    output = capture.get()

    assert "Record ID" in output
    assert "Modified date" in output
    assert "SHA256 hash" not in output
    assert "rec_0001" in output


def test_display_local_search_results_bordered():
    """With a border style set, the results are drawn as a boxed table under the title."""
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes.borders import get_borders
    from types import SimpleNamespace

    record = SimpleNamespace(
        name="boxed.txt",
        size=1,
        media_type="text/plain",
        local_record_id="rec_0002",
        modified_time=1700000000.0,
        hash_sha256=None,
    )
    response = SimpleNamespace(
        records=[record],
        pagination=SimpleNamespace(
            start_index=0, record_count=1, current_page=1, page_count=1, end_index=1, has_next=False
        ),
    )
    ui_context = {"palette": DUMMY_PALETTE, "icons": {}, "borders": get_borders("rounded")}
    console = Console(width=200)

    with console.capture() as capture:
        display_local_search_results(console, response, ui_context)

    lines = capture.get().splitlines()
    assert lines[0].strip() == "Local search results"
    assert lines[1].startswith("╭")
    assert any("boxed.txt" in line and "│" in line for line in lines)


@pytest.fixture
def utc_plus_9():
    """Run the test with the process time zone set to a fixed UTC+9."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "XST-9"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.mark.parametrize(("width", "expected"), [(200, "2023-11-15 07:13:20"), (80, "2023-11-15 07:13")])
def test_display_local_search_results_shows_local_time(utc_plus_9, width, expected):
    """Search results show the modified time in the local time zone, as `dorsal scan` does."""
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes.borders import get_borders
    from types import SimpleNamespace

    record = SimpleNamespace(
        name="file.txt",
        size=1,
        media_type="text/plain",
        local_record_id="d4797053287babe5",
        modified_time=1700000000.0,
        hash_sha256=None,
    )
    response = SimpleNamespace(
        records=[record],
        pagination=SimpleNamespace(
            start_index=0, record_count=1, current_page=1, page_count=1, end_index=1, has_next=False
        ),
    )
    ui_context = {"palette": DUMMY_PALETTE, "icons": {}, "borders": get_borders("none")}
    console = Console(width=width)

    with console.capture() as capture:
        display_local_search_results(console, response, ui_context)

    output = capture.get()
    assert expected in output
    assert "22:13" not in output


@pytest.mark.parametrize(
    "date_modified",
    [
        "2023-11-14T22:13:20+00:00",
        lambda: datetime.datetime.fromtimestamp(1700000000.0).astimezone().isoformat(),
    ],
    ids=["utc-from-index", "local-from-scan"],
)
def test_create_file_info_panel_shows_local_time(utc_plus_9, date_modified):
    """The file panel shows the modified time in the local time zone, whichever zone the record carries."""
    value = date_modified() if callable(date_modified) else date_modified
    record_dict = {**DUMMY_FILE_RECORD, "local_filesystem": {"full_path": "/f.txt", "date_modified": value}}

    panel = create_file_info_panel(record_dict=record_dict, title="File", private=False, palette=DUMMY_PALETTE)
    console = Console(width=200)
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "2023-11-15 07:13:20" in output
    assert "22:13" not in output


def _render_search_results(modified_time: float, width: int = 200) -> str:
    from dorsal.cli.views.search import display_local_search_results
    from dorsal.cli.themes.borders import get_borders
    from types import SimpleNamespace

    record = SimpleNamespace(
        name="file.txt",
        size=1,
        media_type="text/plain",
        local_record_id="d4797053287babe5",
        modified_time=modified_time,
        hash_sha256=None,
    )
    response = SimpleNamespace(
        records=[record],
        pagination=SimpleNamespace(
            start_index=0, record_count=1, current_page=1, page_count=1, end_index=1, has_next=False
        ),
    )
    ui_context = {"palette": DUMMY_PALETTE, "icons": {}, "borders": get_borders("none")}
    console = Console(width=width)
    with console.capture() as capture:
        display_local_search_results(console, response, ui_context)
    return capture.get()


@pytest.mark.parametrize("width", [200, 80])
def test_display_local_search_results_near_epoch(width):
    """A modified time just after the epoch renders on every platform, Windows included."""
    output = _render_search_results(1.0, width=width)

    assert "file.txt" in output
    assert "1970-01-01" in output or "1969-12-31" in output


@pytest.mark.parametrize("width", [200, 80])
def test_display_local_search_results_falls_back_to_utc(utc_plus_9, width):
    """A time that cannot be shown in local time is shown in UTC instead of failing."""
    year_9999 = datetime.datetime(9999, 12, 31, 23, 0, tzinfo=datetime.timezone.utc).timestamp()

    output = _render_search_results(year_9999, width=width)

    assert "9999-12-31 23:00" in output


def test_create_file_info_panel_falls_back_to_utc(utc_plus_9):
    """The file panel shows a time it cannot convert to local time in UTC instead of failing."""
    record_dict = {
        **DUMMY_FILE_RECORD,
        "local_filesystem": {"full_path": "/f.txt", "date_modified": "9999-12-31T23:00:00+00:00"},
    }

    panel = create_file_info_panel(record_dict=record_dict, title="File", private=False, palette=DUMMY_PALETTE)
    console = Console(width=200)
    with console.capture() as capture:
        console.print(panel)

    assert "9999-12-31 23:00:00" in capture.get()
