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
from unittest.mock import Mock

import pytest
from rich.box import ROUNDED
from rich.console import Console

from dorsal.cli.views.collection import collection_metadata

PALETTE = {"key": "bold cyan", "primary_value": "green", "panel_title": "bold white", "panel_border": "blue"}


def _render(renderable, width: int = 120) -> list[str]:
    console = Console(legacy_windows=False, width=width)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get().splitlines()


@pytest.fixture
def mock_ui_context():
    return {"palette": PALETTE, "borders": ROUNDED, "icons": {}}


@pytest.fixture
def borderless_ui_context():
    return {"palette": PALETTE, "borders": None, "icons": {}}


@pytest.fixture
def mock_collection():
    col = Mock()
    col.collection_id = "123-abc"
    col.name = "Test Collection"
    col.description = "A test description"
    col.file_count = 1000
    col.total_size = 1024 * 1024 * 50
    col.is_private = True
    col.date_modified = datetime.datetime(2025, 1, 1, 12, 0, 0)
    return col


def test_collection_metadata_borderless(mock_collection, borderless_ui_context):
    """Borderless: a heading, then left-aligned keys without colons, indented under it."""
    lines = _render(collection_metadata(mock_collection, borderless_ui_context))

    assert lines[0] == "Collection metadata"
    assert lines[1].startswith("  ID ")
    assert lines[1].endswith("123-abc")
    assert any(line.startswith("  Description ") and line.endswith("A test description") for line in lines)
    assert any(line.startswith("  File count ") and line.endswith("1,000") for line in lines)
    assert any(line.startswith("  Access ") and line.endswith("Private") for line in lines)
    assert any(line.startswith("  Modified ") and line.endswith("2025-01-01 12:00:00") for line in lines)
    assert all(line == line.rstrip() for line in lines)
    assert not any(":" in line.split()[0] for line in lines if line.strip())
    value_columns = {line.index(line.split()[-1]) for line in lines[1:] if len(line.split()) == 2}
    assert len(value_columns) == 1


def test_collection_metadata_bordered(mock_collection, mock_ui_context):
    """Bordered: the same rows inside a rounded panel titled "Collection metadata"."""
    lines = _render(collection_metadata(mock_collection, mock_ui_context))

    assert lines[0].startswith("╭─ Collection metadata ")
    assert lines[-1].startswith("╰")
    assert any("Test Collection" in line for line in lines)


def test_collection_metadata_no_description(mock_collection, borderless_ui_context):
    """The description row is left out when there is none."""
    mock_collection.description = None

    output = "\n".join(_render(collection_metadata(mock_collection, borderless_ui_context)))

    assert "Description" not in output


def test_collection_metadata_no_date(mock_collection, borderless_ui_context):
    """A missing modified date is shown as None."""
    mock_collection.date_modified = None

    lines = _render(collection_metadata(mock_collection, borderless_ui_context))

    assert any(line.startswith("  Modified ") and line.endswith("None") for line in lines)


def test_collection_metadata_public(mock_collection, borderless_ui_context):
    """A public collection is shown as Public."""
    mock_collection.is_private = False

    lines = _render(collection_metadata(mock_collection, borderless_ui_context))

    assert any(line.startswith("  Access ") and line.endswith("Public") for line in lines)
