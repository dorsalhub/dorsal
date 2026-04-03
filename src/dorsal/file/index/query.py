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

import logging
from typing import Any

from dorsal.file.utils.size import parse_filesize

logger = logging.getLogger(__name__)


class QueryParser:
    """
    Stage 1: A safe, character-by-character scanner (State Machine).
    NEVER throws exceptions on bad syntax (e.g. unclosed quotes).
    """

    OPERATORS = {">=", "<=", ">", "<", "=", ":"}

    @classmethod
    def parse(cls, query_string: str) -> dict[str, list]:
        """Scans the query and categorizes tokens safely."""
        result: dict[str, list[str | tuple]] = {
            "text": [],
            "filters": [],
        }

        if not query_string or query_string.strip() == "*":
            return result

        tokens = cls._tokenize(query_string)

        for token in tokens:
            if token == "*":
                continue

            found_op = None
            for op in cls.OPERATORS:
                if op in token and not token.startswith(op) and not token.endswith(op):
                    key, val = token.split(op, 1)

                    result["filters"].append((key.lower(), op, val))
                    found_op = op
                    break

            if not found_op:
                result["text"].append(token)

        return result

    @classmethod
    def _tokenize(cls, query: str) -> list[str]:
        """
        A robust state-machine tokenizer.
        Ignores unclosed quotes instead of crashing (anti-shlex).
        """
        tokens = []
        current = []
        in_quotes = False
        quote_char = None

        for char in query:
            if char in ("'", '"'):
                if in_quotes and char == quote_char:
                    in_quotes = False
                    quote_char = None
                elif not in_quotes:
                    in_quotes = True
                    quote_char = char
                else:
                    current.append(char)
            elif char.isspace() and not in_quotes:
                if current:
                    tokens.append("".join(current))
                    current = []
            else:
                current.append(char)

        if current:
            tokens.append("".join(current))

        return tokens


class QueryCompiler:
    """
    Stage 2: Takes the structured output from the Processor and
    compiles it into optimized SQLite syntax for the LocalIndex.
    """

    BASE_COLUMNS = {
        "ext": "extension",
        "extension": "extension",
        "media_type": "media_type",
        "size": "size",
        "date": "modified_time",
        "date_modified": "modified_time",
        "sha256": "hash_sha256",
        "blake3": "hash_blake3",
        "quick": "hash_quick",
        "tlsh": "hash_tlsh",
    }

    SORT_COLUMNS = {
        "date_modified": "c.modified_time",
        "size": "c.size",
        "name": "c.name",
        "media_type": "c.media_type",
        "abspath": "c.abspath",
    }

    @classmethod
    def compile(
        cls,
        parsed_query: dict[str, list],
        *,
        or_logic: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: str = "date_modified",
        sort_desc: bool = True,
    ) -> tuple[str, list[Any]]:
        """
        Compiles tokens into a complete, paginated, and sorted SQL statement.
        """
        where_clauses, params = cls._build_where_clauses(parsed_query, or_logic)

        sql = "SELECT c.abspath FROM cached_files c"

        where_clauses.append("c.record IS NOT NULL")

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        sort_col = cls.SORT_COLUMNS.get(sort_by, "c.modified_time")
        direction = "DESC" if sort_desc else "ASC"
        sql += f" ORDER BY {sort_col} {direction}"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET ?"
                params.append(offset)

        return sql, params

    @classmethod
    def compile_count(cls, parsed_query: dict[str, list], *, or_logic: bool = False) -> tuple[str, list[Any]]:
        """
        Generates a query to count total matches for pagination footers.
        """
        where_clauses, params = cls._build_where_clauses(parsed_query, or_logic)

        sql = "SELECT COUNT(c.abspath) as total FROM cached_files c"

        where_clauses.append("c.record IS NOT NULL")

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        return sql, params

    @classmethod
    def _build_where_clauses(cls, parsed_query: dict[str, list], or_logic: bool) -> tuple[list[str], list[Any]]:
        """Shared logic for building WHERE conditions and parameter binding."""
        from dorsal.file.index.extractors import registry # <--- NEW IMPORT

        where_clauses = []
        params = []

        # 1. Process Property Filters FIRST (so parameter binding aligns correctly)
        for key, op, val in parsed_query.get("filters", []):
            sql_op = "=" if op == ":" else op
            is_wildcard_val = isinstance(val, str) and "*" in val

            if key in cls.BASE_COLUMNS:
                col_name = cls.BASE_COLUMNS[key]

                if sql_op == "=" and is_wildcard_val:
                    if val == "*":
                        where_clauses.append(f"c.{col_name} IS NOT NULL")
                        continue
                    else:
                        sql_op = "LIKE"
                        val = val.replace("*", "%")

                if col_name == "size" and isinstance(val, str):
                    try:
                        val = parse_filesize(val)
                    except ValueError:
                        pass
                elif col_name == "extension" and isinstance(val, str) and not is_wildcard_val:
                    if not val.startswith("."):
                        val = f".{val}"

                where_clauses.append(f"c.{col_name} {sql_op} ?")
                params.append(val)
                continue

            if key == "annotation":
                where_clauses.append(
                    "c.abspath IN (SELECT abspath FROM file_attributes WHERE schema_id = ?)"
                )
                params.append(val)
                continue

            # --- Type-Safe EAV Attribute Filtering ---
            is_numeric_attr = registry.is_numeric_key(key)
            
            if is_numeric_attr:
                try:
                    val = float(val)
                except ValueError:
                    pass

            val_col = "value_num" if is_numeric_attr else "value_text"

            if sql_op == "=" and is_wildcard_val:
                if val == "*":
                    where_clauses.append(
                        "c.abspath IN (SELECT abspath FROM file_attributes WHERE key = ?)"
                    )
                    params.append(key)
                    continue
                else:
                    sql_op = "LIKE"
                    val = val.replace("*", "%")
                    where_clauses.append(
                        f"c.abspath IN (SELECT abspath FROM file_attributes WHERE key = ? AND {val_col} {sql_op} ?)"
                    )
                    params.extend([key, val])
                    continue

            where_clauses.append(
                f"c.abspath IN (SELECT abspath FROM file_attributes WHERE key = ? AND {val_col} {sql_op} ?)"
            )
            params.extend([key, val])

        text_clauses = []
        fts_terms = []

        for text in parsed_query.get("text", []):
            is_wildcard = text.endswith("*")
            clean_text = text[:-1] if is_wildcard else text
            escaped_text = clean_text.replace('"', '""')
            fts_term = f'"{escaped_text}"*' if is_wildcard else f'"{escaped_text}"'

            is_hash = len(clean_text) == 64 and all(c.lower() in "0123456789abcdef" for c in clean_text)

            if is_hash:
                h = clean_text.lower()
                text_clauses.append(
                    "(c.hash_sha256 = ? OR c.hash_blake3 = ? OR c.abspath IN (SELECT abspath FROM dorsal_fts WHERE content MATCH ?))"
                )
                params.extend([h, h, fts_term])
            else:
                fts_terms.append(fts_term)

        if fts_terms:
            logical_join = " OR " if or_logic else " AND "
            fts_query = logical_join.join(fts_terms)
            text_clauses.append("c.abspath IN (SELECT abspath FROM dorsal_fts WHERE content MATCH ?)")
            params.append(fts_query)

        if text_clauses:
            text_logical_join = " OR " if or_logic else " AND "
            where_clauses.append(f"({text_logical_join.join(text_clauses)})")

        return where_clauses, params
