# Copyright 2025 Dorsal Hub LTD
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

from __future__ import annotations
import csv
from collections import defaultdict
import datetime
import json
import logging
import operator
import os
import sqlite3
from typing import Any, Iterator, Sequence, TYPE_CHECKING, TypedDict, cast, Iterable

from dorsal.common.environment import is_jupyter_environment
from dorsal.file.dorsal_file import _DorsalFile
from dorsal.file.utils.size import human_filesize
from dorsal.version import __version__

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


class _StatInfo(TypedDict):
    size: float
    path: str | None


class _DateStatInfo(TypedDict):
    date: datetime.datetime
    path: str | None


def _check_file_for_filter(file_obj: _DorsalFile, filter_criteria: dict) -> bool:
    """
    Checks if a single file object meets all specified filter criteria.

    Args:
        file_obj: The _DorsalFile object to check.
        filter_criteria: A dictionary of filter conditions to apply.

    Returns:
        True if the file meets all criteria, False otherwise.
    """
    op_map = {
        "gt": operator.gt,
        "lt": operator.lt,
        "gte": operator.ge,
        "lte": operator.le,
        "contains": lambda a, v: v in a if hasattr(a, "__contains__") else False,
        "in": lambda a, v: a in v if hasattr(v, "__contains__") else False,
    }

    for key, filter_value in filter_criteria.items():
        parts = key.split("__")
        attr_path_parts = parts[:-1] if len(parts) > 1 and parts[-1] in op_map else parts
        op_str = parts[-1] if len(parts) > 1 and parts[-1] in op_map else "exact"

        try:
            current_attr = file_obj
            for part in attr_path_parts:
                current_attr = getattr(current_attr, part)

            if op_str == "exact":
                if current_attr != filter_value:
                    return False
            else:
                op_func = op_map.get(op_str)
                if not op_func or not op_func(current_attr, filter_value):
                    return False
        except (AttributeError, TypeError):
            return False

    return True


class _BaseFileCollection:
    """Base class providing shared functionality for file collections."""

    def __init__(self, files: Sequence[_DorsalFile], source_info: dict | None = None):
        """
        Args:
            files: A list of objects that inherit from _DorsalFile.
            source_info: Metadata about how the collection was created.
        """
        self.files: Sequence[_DorsalFile] = files
        self.source_info: dict = source_info or {}
        self._is_populated: bool = False

    def __len__(self) -> int:
        """Returns the number of files in the collection."""
        return len(self.files)

    def __iter__(self) -> Iterator[_DorsalFile]:
        """Returns an iterator over the files in the collection."""
        return iter(self.files)

    def __getitem__(self, index: int) -> _DorsalFile | list[_DorsalFile]:
        """Allows accessing files by index."""
        return self.files[index]

    def __repr__(self) -> str:
        """Provides a developer-friendly string representation of the collection."""
        source_type = self.source_info.get("type", "generic")

        if source_type == "local":
            path = self.source_info.get("path", "from list")
            display_path = f"...{path[-22:]}" if len(path) > 25 else path
        elif source_type == "remote":
            collection_id = self.source_info.get("collection_id")
            display_path = f"remote id: {collection_id}"
        else:
            display_path = "from list"

        return f"<{self.__class__.__name__} [{display_path}] ({len(self)})>"

    def info(self) -> dict:
        """
        Provides a summary of the file collection.
        """
        if not self._is_populated:
            raise TypeError(
                "The 'stats' method can only be called on a fully populated collection. "
                "Please call the .populate() method first."
            )

        if not self.files:
            return {
                "overall": {
                    "total_files": 0,
                    "total_size": 0,
                    "avg_size": 0,
                    "largest_file": None,
                    "smallest_file": None,
                    "newest_file": None,
                    "oldest_file": None,
                },
                "by_type": [],
            }

        total_size = 0
        smallest: _StatInfo = {"size": float("inf"), "path": ""}
        largest: _StatInfo = {"size": float("-inf"), "path": ""}
        oldest: _DateStatInfo = {
            "date": datetime.datetime.now().astimezone(),
            "path": "",
        }
        newest: _DateStatInfo = {
            "date": datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc),
            "path": "",
        }
        type_stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "total_size": 0})
        source_stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "total_size": 0})

        for f in self.files:
            mod_time = f.date_modified
            total_size += f.size

            if f.size < smallest["size"]:
                smallest["size"] = f.size
                smallest["path"] = f.name
            if f.size > largest["size"]:
                largest["size"] = f.size
                largest["path"] = f.name
            if mod_time < oldest["date"]:
                oldest["date"] = mod_time
                oldest["path"] = f.name
            if mod_time > newest["date"]:
                newest["date"] = mod_time
                newest["path"] = f.name

            media_type = f.media_type or "unknown"
            type_stats[media_type]["count"] += 1
            type_stats[media_type]["total_size"] += f.size

            source = f._source
            source_stats[source]["count"] += 1
            source_stats[source]["total_size"] += f.size

        type_breakdown = [
            {
                "media_type": mt,
                "count": data["count"],
                "total_size": data["total_size"],
                "percentage_of_total": ((data["total_size"] / total_size) * 100 if total_size > 0 else 0),
            }
            for mt, data in type_stats.items()
        ]
        type_breakdown.sort(key=lambda x: cast(int, x["total_size"]), reverse=True)

        source_breakdown = [
            {
                "source": source,
                "count": data["count"],
                "total_size": data["total_size"],
                "percentage_of_total": ((data["total_size"] / total_size) * 100 if total_size > 0 else 0),
            }
            for source, data in source_stats.items()
        ]
        source_breakdown.sort(key=lambda x: cast(int, x["total_size"]), reverse=True)

        return {
            "overall": {
                "total_files": len(self.files),
                "total_size": total_size,
                "avg_size": total_size / len(self.files) if self.files else 0,
                "largest_file": largest,
                "smallest_file": smallest,
                "newest_file": newest,
                "oldest_file": oldest,
            },
            "by_type": type_breakdown,
            "by_source": source_breakdown,
        }

    def find_duplicates(
        self,
        min_size_bytes: int = 0,
        max_size_bytes: int | None = None,
        console: "Console | None" = None,
        palette: dict | None = None,
    ) -> dict:
        """
        Finds sets of files with identical content hashes in the collection.

        Args:
            min_size_bytes (int): Minimum file size to include in the search.
            max_size_bytes (int | None): Maximum file size to include.
            console (Console | None): Rich Console object for progress display.
            palette (dict | None): Color palette for styling the progress bar.
        """
        if not self._is_populated:
            raise TypeError(
                "The 'find_duplicates' method can only be called on a fully populated collection. "
                "Please call the .populate() method first."
            )
        if not self.files:
            return {}

        rich_progress = None
        files_to_check = [
            f for f in self.files if f.size > min_size_bytes and (max_size_bytes is None or f.size <= max_size_bytes)
        ]

        iterator: Iterable[_DorsalFile]
        if is_jupyter_environment():
            from tqdm import tqdm

            iterator = tqdm(files_to_check, desc="Hashing files")
        elif console:
            from rich.progress import (
                Progress,
                BarColumn,
                TaskProgressColumn,
                MofNCompleteColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )
            from dorsal.cli.themes.palettes import DEFAULT_PALETTE

            active_palette = palette if palette is not None else DEFAULT_PALETTE
            progress_columns = (
                TextColumn(
                    "[progress.description]{task.description}",
                    style=active_palette.get("progress_description", "default"),
                ),
                BarColumn(bar_width=None, style=active_palette.get("progress_bar", "default")),
                TaskProgressColumn(style=active_palette.get("progress_percentage", "default")),
                MofNCompleteColumn(),
                TextColumn("•", style="dim"),
                TimeElapsedColumn(),
                TextColumn("•", style="dim"),
                TimeRemainingColumn(),
            )
            rich_progress = Progress(
                *progress_columns,
                console=console,
                redirect_stdout=True,
                redirect_stderr=True,
            )
            task_id = rich_progress.add_task("Finding duplicates...", total=len(files_to_check))
            iterator = files_to_check
        else:
            iterator = files_to_check

        hash_map = defaultdict(list)
        with rich_progress if rich_progress else open(os.devnull, "w"):
            for file in iterator:
                hash_map[file.hash].append(file)
                if rich_progress:
                    rich_progress.update(task_id, advance=1)

        duplicate_sets_raw: list[list[_DorsalFile]] = [files for files in hash_map.values() if len(files) > 1]
        if not duplicate_sets_raw:
            return {}

        total_wasted_space = 0
        duplicate_sets_formatted = []
        for files in duplicate_sets_raw:
            first_file = files[0]
            count = len(files)
            size_each = first_file.size
            wasted_for_set = size_each * (count - 1)
            total_wasted_space += wasted_for_set

            paths = [getattr(f, "_file_path", f.name) for f in files]

            duplicate_sets_formatted.append(
                {
                    "hash": first_file.hash,
                    "count": count,
                    "file_size": human_filesize(size_each),
                    "file_size_bytes": size_each,
                    "wasted_space": human_filesize(wasted_for_set),
                    "wasted_space_bytes": wasted_for_set,
                    "paths": paths,
                }
            )

        duplicate_sets_formatted.sort(key=lambda x: cast(int, x["wasted_space_bytes"]), reverse=True)

        return {
            "total_sets": len(duplicate_sets_formatted),
            "total_wasted_space": human_filesize(total_wasted_space),
            "total_wasted_space_bytes": total_wasted_space,
            "duplicate_sets": duplicate_sets_formatted,
        }

    def filter(self, **kwargs: Any):
        """
        Filters the collection based on file attributes using flexible criteria.
        ...
        """
        if not kwargs:
            return self.__class__(files=list(self.files), source_info=self.source_info)

        filtered_files = [f for f in self.files if _check_file_for_filter(f, kwargs)]

        return self.__class__(files=filtered_files, source_info=self.source_info)

    def _get_flattened_data(self) -> tuple[list[str], list[dict]]:
        """
        Flattens the collection's data for tabular export formats.
        ...
        """
        header_set = set()
        rows = []
        for file in self.files:
            row = {
                "source_path": self.source_info.get("path"),
                "hash": file.hash,
                "file_path": getattr(file, "_file_path", None),
            }
            dumped_model = file.to_dict()
            annotations: dict[str, Any] = dumped_model.get("annotations", {})

            if not annotations:
                rows.append(row)
                continue

            for key, annotation_data in annotations.items():
                if annotation_data and isinstance(annotation_data, dict) and annotation_data.get("record"):
                    record: dict[str, Any] = annotation_data["record"]
                    prefix = key.replace("/", "_")
                    for field, value in record.items():
                        if isinstance(value, (str, int, float, bool)) or value is None:
                            col_name = f"{prefix}__{field}"
                            header_set.add(col_name)
                            row[col_name] = value
            rows.append(row)
        header = ["hash", "file_path", "source_path"] + sorted(list(header_set))
        return header, rows

    def to_csv(self, file_path: str) -> None:
        """Exports the collection's metadata to a CSV file."""
        if not self.files:
            return
        headers, rows = self._get_flattened_data()
        if not rows:
            return
        with open(file=file_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Successfully exported {len(rows)} records to {file_path}")

    def to_dataframe(self):  # pragma: no cover
        """Exports the collection's metadata to a pandas DataFrame."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as err:
            raise ImportError("To use the `to_dataframe` method you must install pandas: `pip install pandas`") from err

        headers, rows = self._get_flattened_data()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(data=rows, columns=headers)

    def to_dict(
        self,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
    ) -> dict:
        """
        Serializes the collection to a dictionary.
        ...
        """
        collection_info = self.info()

        scan_metadata = {
            **self.source_info,
            "total_files_in_collection": len(self),
            "dorsal_version": __version__,
            "overall": collection_info.get("overall", {}),
            "by_type": collection_info.get("by_type", []),
            "by_source": collection_info.get("by_source", []),
        }

        return {
            "scan_metadata": scan_metadata,
            "results": [
                f.to_dict(
                    mode="json",
                    by_alias=by_alias,
                    exclude_none=exclude_none,
                    exclude=exclude,
                )
                for f in self.files
            ],
        }

    def to_json(
        self,
        filepath: str | None = None,
        indent: int | None = 2,
        by_alias: bool = True,
        exclude_none: bool = True,
        exclude: dict | set | None = None,
    ) -> str | None:
        """Saves the collection data to a structured JSON file or returns it as a string."""
        output_data = self.to_dict(by_alias=by_alias, exclude_none=exclude_none, exclude=exclude)

        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=indent, default=str)
            logger.info(f"Successfully exported {len(self)} records to {filepath}")
            return None
        else:
            return json.dumps(output_data, indent=indent, default=str)

    def to_sqlite(self, db_path: str, table_name: str = "files") -> None:
        """Exports the collection's data to a table in an SQLite database."""
        if not self.files:
            logger.debug("FileCollection is empty, skipping SQLite export.")
            return

        headers, rows = self._get_flattened_data()
        if not rows:
            logger.debug("No data to export to SQLite.")
            return

        sanitized_headers = [h.replace("-", "_") for h in headers]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cols_with_types = ", ".join(f'"{col}" TEXT' for col in sanitized_headers)
            create_table_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols_with_types})'
            cursor.execute(create_table_sql)

            placeholders = ", ".join(["?"] * len(sanitized_headers))
            insert_sql = (
                f'INSERT INTO "{table_name}" ({", ".join(f"{h}" for h in sanitized_headers)}) VALUES ({placeholders})'
            )

            rows_to_insert = [tuple(row.get(h) for h in headers) for row in rows]

            cursor.executemany(insert_sql, rows_to_insert)
            conn.commit()
            logger.info(f"Successfully exported {len(rows)} records to table '{table_name}' in {db_path}")

        except sqlite3.Error as err:
            logger.exception(f"An error occurred during SQLite export to {db_path}")
            raise err
        finally:
            if conn:
                conn.close()
