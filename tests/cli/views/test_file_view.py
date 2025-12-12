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
from rich.console import Console
from dorsal.cli.views.file import create_file_info_panel

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
    """Smoke test for public file panel generation."""
    panel = create_file_info_panel(
        record_dict=DUMMY_FILE_RECORD, title="Test File", private=False, palette=DUMMY_PALETTE
    )

    # Render it to a dummy console to trigger any Rich rendering errors
    console = Console()
    with console.capture() as capture:
        console.print(panel)

    output = capture.get()
    assert "Test File" in output
    assert "test_file.txt" in output
    assert "Public Record" in output
    assert "apollo" in output  # Tag value
    assert "page_count" in output  # PDF annotation
    assert "manual (user_1)" in output  # Stub annotation


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
    # Verify private styling wasn't totally ignored (indirectly via output presence)
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
        private=None,  # None access
        palette=DUMMY_PALETTE,
    )
    console = Console()
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()
    assert "SHA-256" in output
    assert "No tags found" in output
