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
