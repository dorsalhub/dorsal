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
import pytest
from unittest.mock import MagicMock
from dorsal.file.utils.reports import (
    get_collection_overview_data,
    get_dynamic_size_histogram_data,
    resolve_template_path,
    TemplateNotFoundError,
)


# Mocking the LocalFileCollection interface
class MockFile:
    def __init__(self, name, size, media_type, extension, date_modified):
        self.name = name
        self.size = size
        self.media_type = media_type
        self.extension = extension
        self.date_modified = date_modified

    def to_dict(self):
        return {"name": self.name, "size": self.size, "date_modified": self.date_modified.isoformat()}


@pytest.fixture
def mock_collection():
    collection = MagicMock()

    # Create a diverse set of files
    files = [
        MockFile("a.txt", 100, "text/plain", ".txt", datetime.datetime(2023, 1, 1)),
        MockFile("b.jpg", 5000, "image/jpeg", ".jpg", datetime.datetime(2023, 1, 2)),
        MockFile("c.pdf", 200, "application/pdf", ".pdf", datetime.datetime(2023, 1, 3)),
        MockFile("d.txt", 100, "text/plain", ".txt", datetime.datetime(2023, 1, 4)),
    ]

    collection.files = files

    # Mock the .info() return
    collection.info.return_value = {
        "overall": {"total_size": 5400, "count": 4},
        "by_type": [
            {"media_type": "image/jpeg", "total_size": 5000, "count": 1},
            {"media_type": "application/pdf", "total_size": 200, "count": 1},
            {"media_type": "text/plain", "total_size": 200, "count": 2},
        ],
    }
    return collection


def test_get_collection_overview_data(mock_collection):
    """Smoke test for collection overview data generation."""
    data = get_collection_overview_data(mock_collection)

    assert data["most_recent_file_record"]["name"] == "d.txt"

    # Check Media Type Aggregation
    assert len(data["media_type"]["by_count"]) == 3
    text_entry = next(x for x in data["media_type"]["by_count"] if x["media_type"] == "text/plain")
    assert text_entry["count"] == 2

    # Check Extension Aggregation
    assert len(data["extension"]["by_size"]) == 3
    jpg_entry = next(x for x in data["extension"]["by_size"] if x["extension"] == ".jpg")
    assert jpg_entry["total_size"] == 5000

    # Check Timeline Data
    assert len(data["timeline_data"]) == 4
    assert data["timeline_data"][0]["y"] == "a.txt"


def test_get_collection_overview_empty():
    """Test behavior with an empty collection."""
    collection = MagicMock()
    collection.files = []
    data = get_collection_overview_data(collection)
    assert data == {}


def test_get_dynamic_size_histogram_data(mock_collection):
    """Test histogram binning logic."""
    data = get_dynamic_size_histogram_data(mock_collection)

    assert len(data) > 0
    assert "bin_label" in data[0]
    assert "count" in data[0]


def test_get_dynamic_size_histogram_large_dataset():
    """Test histogram binning with enough data to trigger the statistical binning logic."""
    collection = MagicMock()
    # Generate 50 files with varying sizes
    collection.files = [MockFile(f"f{i}", i * 100, "t", ".t", datetime.datetime.now()) for i in range(50)]

    data = get_dynamic_size_histogram_data(collection)
    assert len(data) > 1  # Should have multiple bins
    # Check that it produced valid chart data structure
    assert all("bin_label" in item and "count" in item for item in data)


def test_resolve_template_path_failure():
    """Test that invalid templates raise the correct error."""
    # We don't want to test file system search (too fragile), just the failure case
    with pytest.raises(TemplateNotFoundError):
        resolve_template_path("report_type", "non_existent_template_xyz_123")
