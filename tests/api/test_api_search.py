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
from dorsal.api.search import search_local, search_local_paginated, PaginatedSearchResults


class TestDorsalIndex:
    def test_index_initialization(self, test_index):
        """Verifies the schema and test data were inserted correctly."""
        summary = test_index.summary(verbose=True)
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


@patch("dorsal.api.search.create_index_instance")
def test_search_local_implicit_index_creation(mock_create_index):
    """Hits the branch where index is None and must be initialized."""
    mock_index_inst = mock_create_index.return_value

    mock_conn = MagicMock()
    mock_index_inst._ensure_connection.return_value = mock_conn
    mock_conn.cursor.return_value.fetchall.return_value = []

    with (
        patch("dorsal.api.search.QueryParser.parse"),
        patch("dorsal.api.search.QueryCompiler.compile", return_value=("SELECT 1", [])),
    ):
        search_local("test query", index=None)

    mock_create_index.assert_called_once()
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


class TestSearchLocalPaginated:
    """Test suite specifically targeting the UI-focused paginated search wrapper."""

    def test_paginated_success_and_math(self, test_index):
        """Validates that pagination math, limits, and offsets correctly slice the data."""

        result1 = search_local_paginated("ext:pdf", index=test_index, page=1, per_page=1)

        assert isinstance(result1, PaginatedSearchResults)
        assert result1.pagination.record_count == 2
        assert result1.pagination.page_count == 2
        assert len(result1.records) == 1
        assert result1.pagination.has_next is True
        assert result1.pagination.has_prev is False

        result2 = search_local_paginated("ext:pdf", index=test_index, page=2, per_page=1)

        assert len(result2.records) == 1
        assert result2.pagination.has_next is False
        assert result2.pagination.has_prev is True

        assert result1.records[0].abspath != result2.records[0].abspath

    def test_empty_query_returns_early(self):
        """Hits the early return for empty queries in the paginated flow."""
        result = search_local_paginated("   ", per_page=10)

        assert result.records == []
        assert result.pagination.record_count == 0
        assert result.pagination.per_page == 10

    def test_zero_matches_fast_path(self, test_index):
        """Hits the early return when COUNT(*) returns 0."""
        result = search_local_paginated("ext:doesnotexist", index=test_index)

        assert result.records == []
        assert result.pagination.record_count == 0

    @patch("dorsal.api.search.create_index_instance")
    def test_implicit_index_creation_and_close(self, mock_create_index):
        """Hits the branch where index is None and must be implicitly managed."""
        mock_index_inst = mock_create_index.return_value

        from dorsal.file.index.dorsal_index import CachedFileRecord

        dummy_record = CachedFileRecord(abspath="/fake", modified_time=123.0, record="{}", hash_sha256="fake_hash")
        mock_index_inst.get_record.return_value = dummy_record

        with (
            patch("dorsal.api.search.QueryParser.parse"),
            patch("dorsal.api.search.QueryCompiler.compile_count", return_value=("SELECT COUNT", [])),
            patch("dorsal.api.search.QueryCompiler.compile", return_value=("SELECT DATA", [])),
        ):
            mock_conn = MagicMock()
            mock_index_inst._ensure_connection.return_value = mock_conn
            mock_conn.cursor.return_value.fetchone.return_value = {"total": 5}
            mock_conn.cursor.return_value.fetchall.return_value = [{"abspath": "/fake"}]

            search_local_paginated("test query", index=None)

        mock_create_index.assert_called_once()  # <-- Assert against the new patch
        mock_index_inst.close.assert_called_once()

    def test_parse_compile_failure(self):
        """Tests the parser exception block."""
        with patch("dorsal.api.search.QueryParser.parse", side_effect=Exception("Parser Crash")):
            with pytest.raises(DorsalError, match="Invalid search syntax"):
                search_local_paginated("broken query")

    def test_count_execution_failure(self, test_index):
        """Tests database failure specifically during the initial COUNT(*) query."""
        with patch.object(test_index, "_ensure_connection") as mock_ensure:
            mock_conn = MagicMock()
            mock_ensure.return_value = mock_conn
            mock_conn.cursor.return_value.execute.side_effect = Exception("DB Count Error")

            with pytest.raises(DorsalError, match="Count execution failed"):
                search_local_paginated("valid query", index=test_index)

    def test_data_execution_failure(self, test_index):
        """Tests database failure during the secondary DATA query."""
        with patch.object(test_index, "_ensure_connection") as mock_ensure:
            mock_conn = MagicMock()
            mock_ensure.return_value = mock_conn

            def execute_side_effect(sql, *args, **kwargs):
                if "COUNT" in sql:
                    return None
                raise Exception("DB Data Error")

            mock_conn.cursor.return_value.execute.side_effect = execute_side_effect
            mock_conn.cursor.return_value.fetchone.return_value = {"total": 10}

            with pytest.raises(DorsalError, match="Data execution failed"):
                search_local_paginated("valid query", index=test_index)

    def test_hydration_failure(self, test_index):
        """Hits the branch where a path is returned from DB but file record is gone from disk/cache."""
        with (
            patch("dorsal.api.search.QueryCompiler.compile_count", return_value=("SELECT COUNT", [])),
            patch("dorsal.api.search.QueryCompiler.compile", return_value=("SELECT 'ghost_path' as abspath", [])),
        ):
            with patch.object(test_index, "_ensure_connection") as mock_ensure:
                mock_conn = MagicMock()
                mock_ensure.return_value = mock_conn
                mock_conn.cursor.return_value.fetchone.return_value = {"total": 1}
                mock_conn.cursor.return_value.fetchall.return_value = [{"abspath": "ghost_path"}]

                with patch.object(test_index, "get_record", return_value=None):
                    result = search_local_paginated("find ghost", index=test_index)

                    assert result.records == []
                    assert result.pagination.record_count == 1
