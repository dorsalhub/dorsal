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
from unittest.mock import MagicMock, patch

from dorsal.common.exceptions import DorsalError
from dorsal.api.search import search_local


class TestDorsalIndex:
    def test_index_initialization(self, test_index):
        """Verifies the schema and test data were inserted correctly."""
        summary = test_index.summary()
        assert summary["total_records"] == 3

        assert summary["indexed_attributes"] > 0

    def test_search_base_columns(self, test_index):
        """Tests standard extension and size queries."""
        results = search_local("ext:pdf", index=test_index)
        assert len(results) == 2

        results = search_local("size>10mb", index=test_index)
        assert len(results) == 1
        assert results[0].abspath == "/tmp/video.mp4"

    def test_search_user_tags(self, test_index):
        """Tests the EAV exact match for custom tags."""
        results = search_local("status=draft", index=test_index)
        assert len(results) == 1
        assert results[0].abspath == "/tmp/report.pdf"

    def test_search_fts_and_schema(self, test_index):
        """Tests Full-Text Search and Dual-Indexed Schema Attributes."""

        results = search_local("learning", index=test_index)
        assert len(results) == 1
        assert results[0].abspath == "/tmp/paper.pdf"

        results = search_local('category="astro-ph"', index=test_index)
        assert len(results) == 1

        results = search_local("annotation:dorsal/arxiv", index=test_index)
        assert len(results) == 1

    def test_search_combined_power_query(self, test_index):
        """Tests compiling and executing all paradigms at once."""
        query = 'ext:pdf annotation:dorsal/arxiv "dark matter" category="astro-ph"'
        results = search_local(query, index=test_index)

        assert len(results) == 1
        assert results[0].abspath == "/tmp/paper.pdf"


def test_search_local_empty_query():
    """Hits the early return for empty or whitespace strings."""
    assert search_local("") == []
    assert search_local("   ") == []


@patch("dorsal.api.search.DorsalIndex")
def test_search_local_implicit_index_creation(mock_index_class):
    """Hits the branch where index is None and must be initialized."""
    mock_index_inst = mock_index_class.return_value

    with (
        patch("dorsal.api.search.QueryParser.parse"),
        patch("dorsal.api.search.QueryCompiler.compile", return_value=("SELECT 1", [])),
    ):
        search_local("test query", index=None)

    mock_index_class.assert_called_once()
    mock_index_inst.close.assert_called_once()


def test_search_local_parse_compile_failure():
    """Hits the first catch block: Invalid search syntax or compilation error."""

    with patch("dorsal.api.search.QueryParser.parse", side_effect=Exception("Parser Crash")):
        with pytest.raises(DorsalError, match="Invalid search syntax"):
            search_local("broken query")


def test_search_local_database_execution_failure(test_index):
    """Hits the second catch block: Database execution failed."""

    with patch.object(test_index, "_ensure_connection") as mock_ensure:
        mock_conn = MagicMock()
        mock_ensure.return_value = mock_conn
        mock_conn.cursor.return_value.execute.side_effect = Exception("DB Disk I/O Error")

        with pytest.raises(DorsalError, match="Search execution failed"):
            search_local("valid query", index=test_index)


def test_search_local_hydration_failure(test_index):
    """Hits the hydration failure branch (path returned but record is missing/stale)."""

    with patch("dorsal.api.search.QueryCompiler.compile", return_value=("SELECT 'ghost_path' as abspath", [])):
        with patch.object(test_index, "get_record", return_value=None):
            results = search_local("find ghost", index=test_index)

            assert results == []
