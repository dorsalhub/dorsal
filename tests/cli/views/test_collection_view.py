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
from unittest.mock import Mock, MagicMock
import pytest
from rich.panel import Panel

from dorsal.cli.views.collection import collection_metadata


@pytest.fixture
def mock_palette():
    return {"key": "bold cyan", "primary_value": "green", "panel_title": "bold white", "panel_border": "blue"}


@pytest.fixture
def mock_collection():
    col = Mock()
    col.collection_id = "123-abc"
    col.name = "Test Collection"
    col.description = "A test description"
    col.file_count = 1000
    col.total_size = 1024 * 1024 * 50  # 50MB
    col.is_private = True
    col.date_modified = datetime.datetime(2025, 1, 1, 12, 0, 0)
    return col


def test_collection_metadata_render_full(mock_collection, mock_palette):
    """Test rendering with all fields present."""

    panel = collection_metadata(mock_collection, mock_palette)

    assert isinstance(panel, Panel)
    assert "Collection Metadata" in panel.title

    # We can inspect the renderable table to verify content logic
    table = panel.renderable

    assert table.columns[0].style == "bold cyan"


def test_collection_metadata_no_description(mock_collection, mock_palette):
    """Test rendering when description is None."""
    mock_collection.description = None

    panel = collection_metadata(mock_collection, mock_palette)

    assert isinstance(panel, Panel)


def test_collection_metadata_no_date(mock_collection, mock_palette):
    """Test rendering when date_modified is None."""
    mock_collection.date_modified = None

    panel = collection_metadata(mock_collection, mock_palette)
    assert isinstance(panel, Panel)


def test_collection_metadata_public(mock_collection, mock_palette):
    """Test rendering for public collection."""
    mock_collection.is_private = False
    panel = collection_metadata(mock_collection, mock_palette)
    assert isinstance(panel, Panel)
