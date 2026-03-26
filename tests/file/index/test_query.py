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
from dorsal.file.index.query import QueryParser, QueryCompiler


class TestQueryParser:
    def test_parse_simple_text(self):
        result = QueryParser.parse("annual report")
        assert result["text"] == ["annual", "report"]
        assert result["filters"] == []

    def test_parse_exact_phrase(self):
        result = QueryParser.parse('"annual report"')
        assert result["text"] == ["annual report"]

    def test_parse_filters(self):
        result = QueryParser.parse("ext:pdf size>5mb")
        assert result["text"] == []
        assert result["filters"] == [("ext", ":", "pdf"), ("size", ">", "5mb")]

    def test_parse_unclosed_quotes_safe_handling(self):
        result = QueryParser.parse('ext:pdf "broken quote')
        assert result["filters"] == [("ext", ":", "pdf")]
        # Expectation changed: unclosed quote is stripped
        assert result["text"] == ["broken quote"]


class TestQueryCompiler:
    def test_compile_base_columns(self):
        # 1. Test Base-10 (MB)
        processed_si = {"text": [], "filters": [("ext", ":", "pdf"), ("size", ">", "5mb")]}
        sql_si, params_si = QueryCompiler.compile(processed_si)

        assert "c.extension = ?" in sql_si
        assert "c.size > ?" in sql_si
        assert params_si == [".pdf", 5000000]  # SI base-10

        # 2. Test Base-2 (MiB)
        processed_iec = {"text": [], "filters": [("ext", ":", "pdf"), ("size", ">", "5mib")]}
        _, params_iec = QueryCompiler.compile(processed_iec)

        assert params_iec == [".pdf", 5242880]  # IEC base-2

    def test_compile_eav_tags(self):
        processed = {"text": [], "filters": [("project", "=", "alpha"), ("score", ">=", "0.9")]}
        sql, params = QueryCompiler.compile(processed)

        assert "a.value_text = ?" in sql
        assert "a.value_num >=" in sql
        assert "project" in params
        assert "alpha" in params
        assert "score" in params
        assert 0.9 in params

    def test_compile_fts_text(self):
        # We pass the unquoted string just like the parser would output
        processed = {"text": ["machine", "dark matter"], "filters": []}
        sql, params = QueryCompiler.compile(processed)

        assert "f.content MATCH ?" in sql
        # The compiler sees a space in 'dark matter' and automatically wraps it in quotes!
        assert params == ['machine AND "dark matter"']
