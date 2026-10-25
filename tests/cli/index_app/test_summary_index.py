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


import pytest
import json
from typer.testing import CliRunner

from dorsal.cli import app

runner = CliRunner()


MOCK_INDEX_SUMMARY = {
    "database_path": "/fake/home/.dorsal/cache.db",
    "database_size_bytes": 1234567,
    "total_records": 1234,
    "full_records": 1000,
    "hash_only_records": 234,
}


@pytest.fixture
def mock_summary_index_cmd_verbose(mocker):
    """Mocks dependencies with extended data for verbose output testing."""
    verbose_data = {
        **MOCK_INDEX_SUMMARY,
        "created_time": 1700000000,
        "modified_time": 1700005000,
        "total_tracked_file_bytes": 987654321,
        "compression_ratio_sample": 2.34,
        "indexed_attributes": 42,
        "top_extensions": {".txt": 100, ".py": 50},
        "top_media_types": {"text/plain": 100},
        "top_schemas": {"File": 150},
    }
    return mocker.patch("dorsal.api.index.summary", return_value=verbose_data)


@pytest.fixture
def mock_summary_index_cmd(mocker):
    """Mocks dependencies for the `index summary` command."""

    mock_summary = mocker.patch("dorsal.api.index.summary", return_value=MOCK_INDEX_SUMMARY)
    return {"summary": mock_summary}


def test_summary_index_panel_output(mock_rich_console, mock_summary_index_cmd, rendered):
    """Tests the bordered summary panel."""
    result = runner.invoke(app, ["--borders", "rounded", "index", "summary"])

    assert result.exit_code == 0
    mock_summary_index_cmd["summary"].assert_called_once()

    text = rendered(mock_rich_console)
    assert text.startswith("╭─ Index summary")
    assert "│  Index path         /fake/home/.dorsal/cache.db" in text


def test_summary_index_json_output(mock_rich_console, mock_summary_index_cmd):
    """Tests the --json flag, expecting raw JSON output."""
    result = runner.invoke(app, ["index", "summary", "--json"])

    assert result.exit_code == 0
    mock_summary_index_cmd["summary"].assert_called_once()
    mock_rich_console.print.assert_called_once()

    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)
    assert data == MOCK_INDEX_SUMMARY


def test_summary_index_exception_handling(mock_summary_index_cmd):
    """Tests that a generic exception is handled gracefully."""
    mock_summary_index_cmd["summary"].side_effect = PermissionError("Permission denied")

    result = runner.invoke(app, ["index", "summary"])

    assert result.exit_code != 0
    assert "An error occurred while getting search index info: Permission denied" in result.output


def test_summary_index_verbose_output(mock_rich_console, mock_summary_index_cmd_verbose, rendered):
    """Tests the --verbose flag, ensuring extended metrics and side-by-side distributions are printed."""
    result = runner.invoke(app, ["index", "summary", "--verbose"])

    assert result.exit_code == 0
    mock_summary_index_cmd_verbose.assert_called_once_with(verbose=True, limit=10)

    lines = rendered(mock_rich_console).splitlines()
    assert "  Compression ratio      2.34x" in lines
    assert any(line.startswith("Top extensions") and "Top media types" in line for line in lines)
    assert any(line.startswith(".txt") and "100" in line for line in lines)
    assert all(line == line.rstrip() for line in lines)


def test_summary_index_verbose_compressed_records_fallback(mock_rich_console, mocker):
    """Tests the --verbose flag fallback when compression_ratio_sample is missing."""
    no_ratio_data = {
        **MOCK_INDEX_SUMMARY,
        "compressed_records": 1024,
    }
    mock_summary = mocker.patch("dorsal.api.index.summary", return_value=no_ratio_data)

    result = runner.invoke(app, ["index", "summary", "--verbose"])

    assert result.exit_code == 0
    mock_summary.assert_called_once_with(verbose=True, limit=10)

    assert mock_rich_console.print.called


def test_summary_index_none_style_output(mock_rich_console, mock_summary_index_cmd, rendered):
    """Tests the default borderless output: a heading with left-aligned keys and no trailing whitespace."""
    result = runner.invoke(app, ["index", "summary"])

    assert result.exit_code == 0

    assert rendered(mock_rich_console).splitlines() == [
        "Index summary",
        "  Index path         /fake/home/.dorsal/cache.db",
        "  Index size         1,234 records",
        "  Record cache size  0 B",
        "  Search index size  0 B",
    ]
