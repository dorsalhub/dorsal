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


import pathlib
from typing import Literal

from dorsal.file.index.dorsal_index import DorsalIndex
from dorsal.session import get_shared_index, clear_shared_index


def _get_active_index(index: DorsalIndex | None) -> DorsalIndex:
    """Helper to resolve the index instance to use."""
    return index if index is not None else get_shared_index()


def optimize(*, index: DorsalIndex | None = None) -> dict:
    """
    Runs a full maintenance routine on the local search index.

    Args:
        index: Optional custom DorsalIndex instance. Defaults to shared index.
    """
    active_index = _get_active_index(index)
    return active_index.optimize()


def prune(*, index: DorsalIndex | None = None) -> tuple[int, int]:
    """
    Scans the local search index and removes stale records.

    Args:
        index: Optional custom DorsalIndex instance. Defaults to shared index.
    """
    active_index = _get_active_index(index)
    return active_index.prune()


def clear(*, index: DorsalIndex | None = None) -> None:
    """
    Permanently deletes the entire local search index database file.

    Args:
        index: Optional custom DorsalIndex instance. Defaults to shared index.
    """
    active_index = _get_active_index(index)
    active_index.clear()

    if index is None:
        clear_shared_index()


def summary(*, index: DorsalIndex | None = None) -> dict:
    """
    Retrieves statistics about the local search index.

    Args:
        index: Optional custom DorsalIndex instance. Defaults to shared index.
    """
    active_index = _get_active_index(index)
    return active_index.summary()


def get_path(*, index: DorsalIndex | None = None) -> pathlib.Path:
    """
    Retrieves the absolute path to the local search index database file.

    Args:
        index: Optional custom DorsalIndex instance. Defaults to shared index.
    """
    active_index = _get_active_index(index)
    return active_index.db_path.resolve()


def export(
    output_path: pathlib.Path,
    format: Literal["json", "json.gz"] = "json.gz",
    include_records: bool = True,
    *,
    index: DorsalIndex | None = None,
) -> int:
    """
    Args:
        output_path: The path to save the exported file.
        format: The desired output format. Defaults to "json.gz".
        include_records: Whether to include the record content in the export. Defaults to True.

    Returns:
        The total number of records exported.
    """
    active_index = _get_active_index(index)
    return active_index.export(output_path=output_path, format=format, include_records=include_records)
