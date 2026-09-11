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

    def test_parse_operator_precedence(self):
        """Ensures >= and <= are matched before > and <."""
        result = QueryParser.parse("size>=20 page_count<=400")
        assert result["filters"] == [("size", ">=", "20"), ("page_count", "<=", "400")]

    def test_parse_phrase_and_eav_quotes(self):
        """Ensures spaces are kept inside quotes for both text and EAV values."""
        result = QueryParser.parse('"Design Patterns" creator:"Acrobat 5.0"')
        assert result["text"] == ["Design Patterns"]
        assert result["filters"] == [("creator", ":", "Acrobat 5.0")]

    def test_parse_tuple_input(self):
        """Ensures Typer's nargs=-1 tuple arguments are tokenized properly."""
        result = QueryParser.parse(("ext:mov", "size>20MiB"))
        assert result["filters"] == [("ext", ":", "mov"), ("size", ">", "20MiB")]
        assert result["text"] == []

    def test_parse_unclosed_quotes_safe_handling(self):
        result = QueryParser.parse('ext:pdf "broken quote')
        assert result["filters"] == [("ext", ":", "pdf")]
        assert result["text"] == ["broken quote"]

    def test_parse_empty_query(self):
        """Hits: if not query_string: return result"""
        result = QueryParser.parse("")
        assert result == {"text": [], "filters": []}

        result = QueryParser.parse(("*",))
        assert result == {"text": [], "filters": []}

    def test_tokenize_nested_quotes(self):
        """Hits the 'else: current.append(char)' inside the quote logic."""
        result = QueryParser.parse('"it\'s a test"')
        assert result["text"] == ["it's a test"]


class TestQueryCompiler:
    def test_compile_base_columns(self):
        processed_si = {"text": [], "filters": [("ext", ":", "pdf"), ("size", ">", "5mb")]}
        sql_si, params_si = QueryCompiler.compile(processed_si)

        assert "c.extension = ?" in sql_si
        assert "c.size > ?" in sql_si
        assert params_si == [".pdf", 5000000]

        processed_iec = {"text": [], "filters": [("ext", ":", "pdf"), ("size", ">", "5mib")]}
        _, params_iec = QueryCompiler.compile(processed_iec)

        assert params_iec == [".pdf", 5242880]

    def test_compile_eav_tags(self):
        processed = {"text": [], "filters": [("project", "=", "alpha"), ("score", ">=", "0.9")]}
        sql, params = QueryCompiler.compile(processed)

        assert "value_text = ?" in sql
        assert "value_text >=" in sql
        assert "project" in params
        assert "alpha" in params
        assert "score" in params
        assert "0.9" in params

    def test_compile_numeric_eav_routing(self):
        """Ensures registered numeric fields route to value_num."""
        processed = {"text": [], "filters": [("page_count", ">=", "10")]}
        sql, params = QueryCompiler.compile(processed)
        assert "value_num >=" in sql
        assert "page_count" in params
        assert 10.0 in params

    def test_compile_wildcard_presence(self):
        """Tests the translation of exact '*' to IS NOT NULL and trailing '*' to LIKE."""

        processed_eav = {"text": [], "filters": [("title", ":", "*")]}
        sql_eav, params_eav = QueryCompiler.compile(processed_eav)
        assert "c.abspath IN (SELECT abspath FROM file_attributes WHERE key = ?)" in sql_eav
        assert params_eav == ["title"]

        processed_base = {"text": [], "filters": [("ext", ":", "*")]}
        sql_base, params_base = QueryCompiler.compile(processed_base)
        assert "c.extension IS NOT NULL" in sql_base
        assert len(params_base) == 0

        processed_like = {"text": [], "filters": [("media_type", ":", "video/*")]}
        sql_like, params_like = QueryCompiler.compile(processed_like)
        assert "c.media_type LIKE ?" in sql_like
        assert params_like == ["video/%"]

    def test_compile_annotation_schema_filter(self):
        """Ensures 'annotation:' targets the schema_id column."""
        processed = {"text": [], "filters": [("annotation", ":", "file/office")]}
        sql, params = QueryCompiler.compile(processed)
        assert "c.abspath IN (SELECT abspath FROM file_attributes WHERE schema_id = ?)" in sql
        assert params == ["file/office"]

    def test_compile_fts_text(self):
        processed = {"text": ["machine", "dark matter"], "filters": []}
        sql, params = QueryCompiler.compile(processed)

        assert "WHERE content MATCH ?" in sql
        assert params == ['"machine" AND "dark matter"']

    def test_compile_or_logic_parenthesization(self):
        """Tests that the --or flag correctly wraps user clauses without breaking base DB requirements."""
        processed = {"text": ["fall"], "filters": [("ext", ":", "epub"), ("size", ">", "100kb")]}
        sql, params = QueryCompiler.compile(processed, or_logic=True)

        assert "AND c.record IS NOT NULL" in sql

        assert (
            "(c.extension = ? OR c.size > ? OR (c.abspath IN (SELECT abspath FROM dorsal_fts WHERE content MATCH ?)))"
            in sql
        )

    def test_compile_invalid_filesize(self):
        """Hits the ValueError pass for parse_filesize."""
        processed = {"text": [], "filters": [("size", ">", "huge")]}
        sql, params = QueryCompiler.compile(processed)

        assert "c.size > ?" in sql
        assert "huge" in params

    def test_compile_invalid_numeric_filter(self):
        """Hits the ValueError pass for float(val) in EAV filters."""
        processed = {"text": [], "filters": [("custom_field", ">", "not_a_number")]}
        sql, params = QueryCompiler.compile(processed)

        assert "value_text > ?" in sql
        assert "not_a_number" in params

    def test_compile_pagination(self):
        """Tests that LIMIT and OFFSET are correctly appended to the SQL."""
        processed = {"text": [], "filters": []}

        sql, params = QueryCompiler.compile(processed, limit=10)
        assert "LIMIT ?" in sql
        assert "OFFSET ?" not in sql
        assert params == [10]

        sql, params = QueryCompiler.compile(processed, limit=50, offset=100)
        assert "LIMIT ?" in sql
        assert "OFFSET ?" in sql
        assert params == [50, 100]

    def test_compile_count(self):
        """Tests the compile_count method for pagination footers."""
        processed = {"text": ["machine"], "filters": [("ext", ":", "pdf")]}
        sql, params = QueryCompiler.compile_count(processed)

        assert sql.startswith("SELECT COUNT(c.abspath) as total FROM cached_files c")

        assert "JOIN dorsal_fts" not in sql
        assert "c.extension =" in sql
        assert "WHERE content MATCH ?" in sql

        assert "ORDER BY" not in sql
        assert "LIMIT" not in sql

        assert params == [".pdf", '"machine"']

    def test_compile_sorting(self):
        """Tests deterministic sorting and injection prevention in the compiler."""
        processed = {"text": [], "filters": []}

        sql, _ = QueryCompiler.compile(processed)
        assert "ORDER BY c.modified_time DESC" in sql

        sql, _ = QueryCompiler.compile(processed, sort_by="size", sort_desc=False)
        assert "ORDER BY c.size ASC" in sql

        sql, _ = QueryCompiler.compile(processed, sort_by="drop_tables_hacker_column")
        assert "ORDER BY c.modified_time DESC" in sql

    def test_compile_fts_wildcard(self):
        """Tests that explicit wildcards are placed outside the quotes for FTS5 prefix matching."""
        processed = {"text": ["ren*", "exact", 'weird"quote*'], "filters": []}
        sql, params = QueryCompiler.compile(processed)

        assert "WHERE content MATCH ?" in sql
        assert params == ['"ren"* AND "exact" AND "weird""quote"*']

    def test_compile_deep_flag(self):
        """Tests that the deep=True flag correctly checks for populated hashes."""
        processed = {"text": [], "filters": []}

        sql, _ = QueryCompiler.compile(processed, deep=True)
        assert "(c.hash_sha256 IS NOT NULL AND c.hash_sha256 != '')" in sql

        count_sql, _ = QueryCompiler.compile_count(processed, deep=True)
        assert "(c.hash_sha256 IS NOT NULL AND c.hash_sha256 != '')" in count_sql
