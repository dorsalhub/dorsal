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
from typing import Sequence

from dorsal.common.exceptions import DorsalError
from dorsal.file.index.dorsal_index import DorsalIndex, CachedFileRecord
from dorsal.file.index.query import QueryParser, QueryCompiler

logger = logging.getLogger(__name__)


def search_local(
    query: str,
    or_logic: bool = False,
    index: DorsalIndex | None = None,
    limit: int = 1000,
) -> Sequence[CachedFileRecord]:
    """
    Searches the local Dorsal metadata index using the DorsalHub query syntax.

    Args:
        query: The search string (e.g., 'ext:pdf "machine learning" size>5mb').
        or_logic: If True, combines free-text FTS terms with OR instead of AND.
        index: An optional pre-initialized DorsalIndex instance. If not provided,
               a new connection to the default local cache will be opened.
        limit: The maximum number of results to return.

    Returns:
        A list of hydrated CachedFileRecord objects matching the search criteria.

    Raises:
        DorsalError: If the search query fails to parse or execute.
    """
    logger.debug(f"Starting local search for query: '{query}'")

    if not query or not query.strip():
        logger.debug("Empty query provided. Returning empty result set.")
        return []

    
    
    close_after = False
    if index is None:
        index = DorsalIndex()
        close_after = True

    try:
        
        try:
            processed_query = QueryParser.parse(query)
            
            sql, params = QueryCompiler.compile(processed_query, or_logic=or_logic)
        except Exception as e:
            logger.error(f"Failed to parse or compile search query '{query}': {e}")
            raise DorsalError(f"Invalid search syntax or compilation error: {e}") from e

        
        conn = index._ensure_connection()
        cursor = conn.cursor()

        logger.debug(f"Executing SQL: {sql} with params: {params}")
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"Database execution failed for query '{query}': {e}")
            raise DorsalError(f"Search execution failed: {e}") from e

        
        
        
        results: list[CachedFileRecord] = []
        for row in rows:
            path = row["abspath"]
            record = index.get_record(path=path)
            if record:
                results.append(record)
            else:
                logger.debug(f"Search index returned path '{path}', but record hydration failed (cache miss/stale).")

        logger.info(f"Local search for '{query}' returned {len(results)} results.")
        return results

    finally:
        
        if close_after and index:
            index.close()
