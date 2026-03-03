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
import pytest
from rich.console import Console
from rich.table import Table
from dorsal.cli.views.file import create_file_info_panel, _build_annotation_table

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
    assert "manual (user_1)" in output


def test_create_file_info_panel_private():
    """Smoke test for private file panel generation."""
    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Private File", private=True, palette=DUMMY_PALETTE
    )
    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "Private Record" in output

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
    assert "No tags found" in output


def _render_table_to_string(table: Table) -> str:
    """Helper to render a Rich Table to a string for assertion."""
    console = Console()
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def test_build_annotation_table_stub_full():
    """Test stub rendering with all expected fields."""
    table = Table()
    table.add_column("Key")
    table.add_column("Value")

    stub_data = {
        "source": {"type": "manual", "id": "user_42"},
        "date_modified": "2024-05-20T14:30:00Z",
        "id": "anno_123",
        "url": "api/v1/somehash/annotations",
    }

    _build_annotation_table("test_key", table, stub_data, is_stub=True)
    output = _render_table_to_string(table)

    assert "manual (user_42)" in output
    assert "2024-05-20 14:30" in output
    assert "anno_123" in output
    assert "dorsal annotation get somehash anno_123" in output


def test_build_annotation_table_stub_minimal():
    """Test stub rendering with missing optional fields."""
    table = Table()
    table.add_column("Key")
    table.add_column("Value")

    stub_data = {}

    _build_annotation_table("test_key", table, stub_data, is_stub=True)
    output = _render_table_to_string(table)

    assert "none (none)" in output
    assert "Modified" not in output
    assert "To View" not in output


def test_build_annotation_table_dict_logic():
    """Test nested dicts, lists, skipped keys, and empty values."""
    table = Table()
    table.add_column("Key")
    table.add_column("Value")

    data = {
        "file_hash": "this_should_be_skipped",
        "empty_string": "",
        "none_value": None,
        "empty_list": [],
        "simple_key": "simple_value",
        "nested_dict": {"inner_key": "inner_value"},
        "simple_list": [1, 2, "three"],
        "complex_list": [{"list_dict_key": "val1"}, {"list_dict_key2": "val2"}],
    }

    _build_annotation_table("test_key", table, data, is_stub=False)
    output = _render_table_to_string(table)

    assert "this_should_be_skipped" not in output
    assert "empty_string" not in output
    assert "none_value" not in output
    assert "empty_list" not in output

    assert "simple_key:" in output
    assert "simple_value" in output

    assert "nested_dict:" in output
    assert "inner_key:" in output
    assert "inner_value" in output

    assert "simple_list:" in output
    assert "1, 2, three" in output

    assert "complex_list:" in output
    assert "list_dict_key:" in output
    assert "val1" in output
    assert "list_dict_key2:" in output
    assert "val2" in output


def test_build_annotation_table_display_fields():
    """Test that display_fields correctly filters out unwanted keys recursively."""
    table = Table()
    table.add_column("Key")
    table.add_column("Value")

    data = {"keep_me": "yes", "drop_me": "no", "nested": {"keep_inner": "yes", "drop_inner": "no"}}

    _build_annotation_table("test_key", table, data, is_stub=False, display_fields={"keep_me", "nested", "keep_inner"})
    output = _render_table_to_string(table)

    assert "keep_me:" in output
    assert "drop_me:" not in output
    assert "nested:" in output
    assert "keep_inner:" in output
    assert "drop_inner:" not in output


def test_build_annotation_table_list_root():
    """Test when the root data passed in is a list instead of a dict."""
    table = Table()
    table.add_column("Key")
    table.add_column("Value")

    data = [{"root_list_item1": "valA"}, {"root_list_item2": "valB"}]

    _build_annotation_table("test_key", table, data, is_stub=False)
    output = _render_table_to_string(table)

    assert "root_list_item1:" in output
    assert "valA" in output
    assert "root_list_item2:" in output
    assert "valB" in output
