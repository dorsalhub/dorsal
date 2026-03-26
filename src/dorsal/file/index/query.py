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

        if not query_string:
            return result

        tokens = cls._tokenize(query_string)

        for token in tokens:
            
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

    @classmethod
    def compile(cls, processed_query: dict[str, list], or_logic: bool = False) -> tuple[str, list[Any]]:
        where_clauses = []
        params = []
        fts_terms = []

        
        for text in processed_query["text"]:
            if " " in text:
                fts_terms.append(f'"{text}"')
            else:
                fts_terms.append(text)

        
        for key, op, val in processed_query["filters"]:
            sql_op = "=" if op == ":" else op

            
            if key in cls.BASE_COLUMNS:
                col_name = cls.BASE_COLUMNS[key]

                
                if col_name == "size" and isinstance(val, str):
                    try:
                        val = parse_filesize(val)
                    except ValueError:
                        pass  

                
                elif col_name == "extension" and isinstance(val, str):
                    if not val.startswith("."):
                        val = f".{val}"

                where_clauses.append(f"c.{col_name} {sql_op} ?")
                params.append(val)
                continue

            
            if key == "annotation":
                where_clauses.append(
                    "EXISTS (SELECT 1 FROM file_attributes a WHERE a.abspath = c.abspath AND a.schema_id = ?)"
                )
                params.append(val)
                continue

            
            is_numeric = sql_op in (">", "<", ">=", "<=")
            if is_numeric:
                try:
                    val = float(val)
                except ValueError:
                    pass

            val_col = "value_num" if isinstance(val, float) else "value_text"

            where_clauses.append(
                f"EXISTS (SELECT 1 FROM file_attributes a WHERE a.abspath = c.abspath AND a.key = ? AND a.{val_col} {sql_op} ?)"
            )
            params.extend([key, val])

        
        if fts_terms:
            logical_join = " OR " if or_logic else " AND "
            fts_query = logical_join.join(fts_terms)
            where_clauses.append("f.content MATCH ?")
            params.append(fts_query)

        
        sql = "SELECT c.abspath FROM cached_files c"
        if fts_terms:
            sql += " JOIN dorsal_fts f ON c.abspath = f.abspath"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        sql += " ORDER BY c.modified_time DESC LIMIT 1000"

        return sql, params
