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
import math
from typing import Sequence

from pydantic import BaseModel

from dorsal.common.exceptions import DorsalError
from dorsal.common.validators import Pagination
from dorsal.file.index.dorsal_index import DorsalIndex, CachedFileRecord
from dorsal.file.index.query import QueryParser, QueryCompiler

logger = logging.getLogger(__name__)


class PaginatedSearchResults(BaseModel):
    """Structured response for paginated UI search views."""

    records: list[CachedFileRecord]
    pagination: Pagination


def search_local(
    query: str,
    or_logic: bool = False,
    index: DorsalIndex | None = None,
    limit: int = 1000,
    sort_by: str = "date_modified",
    sort_desc: bool = True,
) -> Sequence[CachedFileRecord]:
    """
    Standard search returning a flat list of records.
    Fastest option. Does not calculate total matches.
    """
    logger.debug(f"Starting standard local search for query: '{query}'")

    if not query or not query.strip():
        return []

    close_after = False
    if index is None:
        index = DorsalIndex()
        close_after = True

    try:
        try:
            processed_query = QueryParser.parse(query)
            sql, params = QueryCompiler.compile(
                processed_query, or_logic=or_logic, limit=limit, sort_by=sort_by, sort_desc=sort_desc
            )
        except Exception as e:
            raise DorsalError(f"Invalid search syntax or compilation error: {e}") from e

        conn = index._ensure_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        except Exception as e:
            raise DorsalError(f"Search execution failed: {e}") from e

        results: list[CachedFileRecord] = []
        for row in rows:
            record = index.get_record(path=row["abspath"])
            if record:
                results.append(record)

        return results

    finally:
        if close_after and index:
            index.close()


def search_local_paginated(
    query: str,
    or_logic: bool = False,
    index: DorsalIndex | None = None,
    page: int = 1,
    per_page: int = 30,
    sort_by: str = "date_modified",
    sort_desc: bool = True,
) -> PaginatedSearchResults:
    """
    UI-focused search. Executes a data query AND a count query
    to provide full pagination metadata using the standard Pagination model.
    """
    logger.debug(f"Starting paginated local search for query: '{query}' (Page {page})")

    if not query or not query.strip():
        empty_pagination = Pagination(
            current_page=page,
            record_count=0,
            page_count=0,
            per_page=per_page,
            has_next=False,
            has_prev=False,
            start_index=0,
            end_index=0,
        )
        return PaginatedSearchResults(records=[], pagination=empty_pagination)

    close_after = False
    if index is None:
        index = DorsalIndex()
        close_after = True

    try:
        try:
            processed_query = QueryParser.parse(query)
            count_sql, count_params = QueryCompiler.compile_count(processed_query, or_logic=or_logic)
        except Exception as e:
            raise DorsalError(f"Invalid search syntax or compilation error: {e}") from e

        conn = index._ensure_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(count_sql, count_params)
            total_matches = cursor.fetchone()["total"]
        except Exception as e:
            raise DorsalError(f"Count execution failed: {e}") from e

        total_pages = math.ceil(total_matches / per_page) if per_page > 0 else 0
        start_index = (page - 1) * per_page
        end_index = min(start_index + per_page, total_matches)

        pagination = Pagination(
            current_page=page,
            record_count=total_matches,
            page_count=total_pages,
            per_page=per_page,
            has_next=page < total_pages,
            has_prev=page > 1,
            start_index=start_index,
            end_index=end_index,
        )

        if total_matches == 0:
            return PaginatedSearchResults(records=[], pagination=pagination)

        try:
            data_sql, data_params = QueryCompiler.compile(
                processed_query,
                or_logic=or_logic,
                limit=per_page,
                offset=start_index,
                sort_by=sort_by,
                sort_desc=sort_desc,
            )
            cursor.execute(data_sql, data_params)
            rows = cursor.fetchall()
        except Exception as e:
            raise DorsalError(f"Data execution failed: {e}") from e

        results: list[CachedFileRecord] = []
        for row in rows:
            record = index.get_record(path=row["abspath"])
            if record:
                results.append(record)

        return PaginatedSearchResults(records=results, pagination=pagination)

    finally:
        if close_after and index:
            index.close()
