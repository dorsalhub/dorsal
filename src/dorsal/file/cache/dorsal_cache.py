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
import gzip
import json
import sqlite3
import os
import logging
import weakref
from pathlib import Path
from typing import Literal, TYPE_CHECKING
import zlib

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import FileRecordStrict

logger = logging.getLogger(__name__)


class CachedFileRecord(BaseModel):
    """Pydantic model representing a single record in the cache database."""

    abspath: str
    modified_time: float
    record_json: str = Field(alias="record")
    name: str | None = None
    size: int | None = None
    extension: str | None = None
    media_type: str | None = None
    hash_sha256: str
    hash_blake3: str | None = None
    hash_quick: str | None = None
    hash_tlsh: str | None = None


class DorsalCache:
    """
    Manages the local SQLite cache for file metadata.
    """

    def __init__(self, db_path: Path | None = None, use_compression: bool = True):
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = Path.home() / ".dorsal" / "cache.db"

        self.use_compression = use_compression
        self.conn: sqlite3.Connection | None = None
        self._ensure_db_directory_exists()
        self._finalizer = weakref.finalize(self, self._finalize_connection, self.conn)
        logger.debug(f"DorsalCache initialized for path: {self.db_path} with compression={self.use_compression}")

    @staticmethod
    def _finalize_connection(conn):
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def _ensure_db_directory_exists(self):
        """Ensures the parent directory for the database file exists."""
        if not self.db_path.parent.exists():
            logger.debug(f"Creating cache directory at: {self.db_path.parent}")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        """Establishes a connection to the SQLite database and initializes the schema."""
        if self.conn is None:
            logger.debug(f"Connecting to cache database: {self.db_path}")
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self._finalizer = weakref.finalize(self, self._finalize_connection, self.conn)
            self._initialize_schema()

    def _ensure_connection(self) -> sqlite3.Connection:
        """Ensures the database connection is active, returning the connection object."""
        if self.conn is None:
            self.connect()
        if self.conn is None:
            raise RuntimeError("Database connection could not be established.")
        return self.conn

    def _initialize_schema(self):
        """Creates/updates the `cached_files` table and its indexes."""
        conn = self._ensure_connection()
        cursor = conn.cursor()

        logger.debug("Initializing cache schema...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cached_files (
                abspath TEXT PRIMARY KEY,
                modified_time REAL NOT NULL,
                record BLOB,
                is_compressed INTEGER DEFAULT 0,
                name TEXT,
                size INTEGER,
                extension TEXT,
                media_type TEXT,
                hash_sha256 TEXT,
                hash_blake3 TEXT,
                hash_quick TEXT,
                hash_tlsh TEXT
            );
            """
        )

        logger.debug("Ensuring all cache indexes exist...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_sha256 ON cached_files (hash_sha256);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_blake3 ON cached_files (hash_blake3);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_quick ON cached_files (hash_quick);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_tlsh ON cached_files (hash_tlsh);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON cached_files (name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extension ON cached_files (extension);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_type ON cached_files (media_type);")

        conn.commit()
        logger.debug("Schema initialization complete.")

    def get_record(self, *, path: str) -> CachedFileRecord | None:
        """Retrieves a record, decompressing it if necessary."""
        conn = self._ensure_connection()
        logger.debug(f"Attempting to get record for path: {path}")
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT abspath, modified_time, record, is_compressed, name, size,
                   extension, media_type, hash_sha256, hash_blake3,
                   hash_quick, hash_tlsh
            FROM cached_files WHERE abspath = ?
            """,
            (path,),
        )
        row = cursor.fetchone()

        if not row:
            logger.debug(f"Cache miss for path: {path}")
            return None

        logger.debug(f"Cache hit for path: {path}")
        row_dict = dict(row)
        record_data: bytes | None = row_dict["record"]
        is_compressed_flag = row_dict["is_compressed"]

        if record_data is None:
            logger.debug(f"Cache entry for path '{path}' has NULL data. Treating as a cache miss.")
            return None

        if is_compressed_flag:
            logger.debug(f"Decompressing record for path: {path}")
            record_json_str = zlib.decompress(record_data).decode("utf-8")
        else:
            record_json_str = record_data.decode("utf-8")

        row_dict["record"] = record_json_str
        return CachedFileRecord.model_validate(row_dict)

    def upsert_record(self, *, path: str, modified_time: float, record: "FileRecordStrict"):
        """Inserts or replaces a record, respecting the compression setting."""
        conn = self._ensure_connection()
        logger.debug(f"Upserting record for path: {path}")
        base_annotation = record.annotations.file_base.record
        all_hashes = base_annotation.all_hash_ids or {}

        record_json_str = record.model_dump_json()
        is_compressed_flag = 0

        if self.use_compression:
            logger.debug(f"Compressing record for path: {path}")
            record_data = zlib.compress(record_json_str.encode("utf-8"))
            is_compressed_flag = 1
        else:
            record_data = record_json_str.encode("utf-8")

        sql_data = {
            "abspath": path,
            "modified_time": modified_time,
            "record": record_data,
            "is_compressed": is_compressed_flag,
            "name": base_annotation.name,
            "size": base_annotation.size,
            "extension": base_annotation.extension,
            "media_type": base_annotation.media_type,
            "hash_sha256": all_hashes.get("SHA-256"),
            "hash_blake3": all_hashes.get("BLAKE3"),
            "hash_quick": all_hashes.get("QUICK"),
            "hash_tlsh": all_hashes.get("TLSH"),
        }

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO cached_files (
                abspath, modified_time, record, is_compressed, name, size,
                extension, media_type, hash_sha256, hash_blake3,
                hash_quick, hash_tlsh
            ) VALUES (
                :abspath, :modified_time, :record, :is_compressed, :name, :size,
                :extension, :media_type, :hash_sha256, :hash_blake3,
                :hash_quick, :hash_tlsh
            )
            """,
            sql_data,
        )
        conn.commit()
        logger.debug(f"Successfully upserted record for path: {path}")

    def upsert_hash(self, *, path: str, modified_time: float, hash_function: str, hash_value: str):
        """
        Inserts or updates a single hash, correctly handling and invalidating
        existing full records if they are stale.
        """
        conn = self._ensure_connection()
        field_map = {
            "SHA-256": "hash_sha256",
            "BLAKE3": "hash_blake3",
            "QUICK": "hash_quick",
            "TLSH": "hash_tlsh",
        }
        column_name = field_map.get(hash_function.upper())
        if not column_name:
            raise ValueError(f"Unsupported hash function '{hash_function}'.")

        cursor = conn.cursor()
        cursor.execute("SELECT record IS NOT NULL FROM cached_files WHERE abspath = ?", (path,))
        result = cursor.fetchone()
        if result and result[0]:
            stale_check_sql = "SELECT modified_time FROM cached_files WHERE abspath = ?"
            cursor.execute(stale_check_sql, (path,))
            cached_mod_time = cursor.fetchone()[0]
            if cached_mod_time != modified_time:
                logger.debug(f"Stale full record found for '{path}'. Deleting before upserting new hash.")
                cursor.execute("DELETE FROM cached_files WHERE abspath = ?", (path,))

        sql = f"""
            INSERT INTO cached_files (abspath, modified_time, {column_name})
            VALUES (?, ?, ?)
            ON CONFLICT(abspath) DO UPDATE SET
                modified_time = excluded.modified_time,
                {column_name} = excluded.{column_name};
        """
        cursor.execute(sql, (path, modified_time, hash_value))
        conn.commit()

    def get_hash(self, *, path: str, hash_function: str = "SHA-256") -> str | None:
        """
        Efficiently retrieves a specific hash for a cached file if the cache is valid.
        """
        conn = self._ensure_connection()
        field_map = {
            "SHA-256": "hash_sha256",
            "BLAKE3": "hash_blake3",
            "QUICK": "hash_quick",
            "TLSH": "hash_tlsh",
        }
        column_name = field_map.get(hash_function.upper())
        if not column_name:
            raise ValueError(f"Unsupported hash function '{hash_function}'. Supported: {list(field_map.keys())}")

        logger.debug(f"Checking cache for '{hash_function}' hash for path: {path}")
        cursor = conn.cursor()

        sql_query = f"SELECT modified_time, {column_name} FROM cached_files WHERE abspath = ?"
        cursor.execute(sql_query, (path,))
        row = cursor.fetchone()

        if not row:
            logger.debug(f"Cache miss: No record found for path: {path}")
            return None

        cached_mod_time = row["modified_time"]
        try:
            current_mod_time = os.path.getmtime(path)
        except FileNotFoundError:
            logger.debug(f"Cache stale: File not found on disk at path: {path}")
            return None

        if cached_mod_time != current_mod_time:
            logger.debug(f"Cache miss: Record is stale for path: {path} (mtime mismatch)")
            return None

        hash_value = row[column_name]
        if hash_value:
            logger.debug(f"Cache hit: Found valid '{hash_function}' hash for path: {path}")
            return hash_value
        else:
            logger.debug(f"Cache miss: Record found but missing '{hash_function}' hash for path: {path}")
            return None

    def clear(self):
        """Close the connection and deletes the entire database file."""
        logger.debug(f"Clearing cache by deleting database file: {self.db_path}")
        self.close()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.debug("Cache database file successfully removed.")
        except OSError as e:
            logger.error(f"Error removing cache file at {self.db_path}: {e}")

    def close(self):
        """Commit any pending changes and close the connection."""
        if self.conn:
            logger.debug("Closing cache database connection.")
            self.conn.commit()
            self.conn.close()
            self.conn = None

    def summary(self) -> dict:
        """Provides a summary of the cache's current state."""
        conn = self._ensure_connection()
        logger.debug("Generating cache summary...")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cached_files")
        record_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM cached_files WHERE record IS NOT NULL")
        full_records = cursor.fetchone()[0]

        hash_only_records = record_count - full_records

        try:
            db_size_bytes = os.path.getsize(self.db_path)
        except FileNotFoundError:
            db_size_bytes = 0

        summary_data = {
            "database_path": str(self.db_path),
            "total_records": record_count,
            "full_records": full_records,
            "hash_only_records": hash_only_records,
            "database_size_bytes": db_size_bytes,
        }
        logger.debug(f"Cache summary generated: {summary_data}")
        return summary_data

    def prune(self) -> tuple[int, int]:
        """Prunes the cache by removing stale records."""
        conn = self._ensure_connection()
        logger.debug("Starting cache prune operation...")
        cursor = conn.cursor()
        cursor.execute("SELECT abspath, modified_time FROM cached_files")
        records = list(cursor.fetchall())
        total_records = len(records)
        logger.debug(f"Scanning {total_records} records for staleness...")

        stale_paths = []
        for record in records:
            path, cached_mod_time = record["abspath"], record["modified_time"]

            if not os.path.exists(path):
                logger.debug(f"Marking stale (path not found): {path}")
                stale_paths.append(path)
                continue

            try:
                current_mod_time = os.path.getmtime(path)
                if current_mod_time != cached_mod_time:
                    logger.debug(f"Marking stale (mtime mismatch): {path}")
                    stale_paths.append(path)
            except FileNotFoundError:
                logger.debug(f"Marking stale (path disappeared during check): {path}")
                stale_paths.append(path)

        if not stale_paths:
            logger.debug("Prune complete. No stale records found.")
            return (0, total_records)

        logger.debug(f"Removing {len(stale_paths)} stale records...")
        cursor.executemany(
            "DELETE FROM cached_files WHERE abspath = ?",
            [(path,) for path in stale_paths],
        )
        conn.commit()

        logger.debug(f"Prune complete. Removed {len(stale_paths)} of {total_records} records.")
        return (len(stale_paths), total_records)

    def vacuum(self) -> None:
        """Rebuilds the database file, reclaiming free space."""
        conn = self._ensure_connection()
        logger.debug("Starting cache vacuum...")
        conn.execute("VACUUM")
        conn.commit()
        logger.debug("Cache vacuum complete.")

    def optimize(self) -> dict:
        """Runs a full maintenance routine on the cache."""
        self._ensure_connection()
        logger.debug("Starting full cache optimization...")
        size_before = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        pruned_count, _ = self.prune()
        rewritten_count = self._sync_compression()
        self.vacuum()
        size_after = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        result = {
            "stale_records_removed": pruned_count,
            "records_rewritten_for_compression": rewritten_count,
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "size_reclaimed_bytes": size_before - size_after,
        }
        logger.debug(f"Cache optimization complete: {result}")
        return result

    def _sync_compression(self) -> int:
        """Internal helper to re-compress/de-compress records in a memory-efficient way."""
        conn = self._ensure_connection()
        logger.debug("Starting compression sync...")
        read_cursor = conn.cursor()
        write_cursor = conn.cursor()
        read_cursor.execute("SELECT abspath, record, is_compressed FROM cached_files")

        rewritten_count = 0
        for row in read_cursor:
            path, data, is_compressed = (
                row["abspath"],
                row["record"],
                row["is_compressed"],
            )

            if data is None:
                continue

            new_data = None
            if self.use_compression and not is_compressed:
                logger.debug(f"Compressing record during sync: {path}")
                new_data = zlib.compress(data)
                is_compressed_flag = 1
            elif not self.use_compression and is_compressed:
                logger.debug(f"Decompressing record during sync: {path}")
                new_data = zlib.decompress(data)
                is_compressed_flag = 0

            if new_data is not None:
                write_cursor.execute(
                    "UPDATE cached_files SET record = ?, is_compressed = ? WHERE abspath = ?",
                    (new_data, is_compressed_flag, path),
                )
                rewritten_count += 1

        if rewritten_count > 0:
            conn.commit()
            logger.debug(f"Synced compression state for {rewritten_count} records.")
        else:
            logger.debug("All records already match the current compression setting.")

        return rewritten_count

    def export(
        self,
        output_path: Path,
        format: Literal["json", "json.gz"] = "json.gz",
        include_records: bool = True,
    ) -> int:
        """
        Exports the contents of the cache to a file.

        Args:
            output_path: The path to save the exported file.
            format: The desired output format. Defaults to "json.gz".
            include_records: Whether to include the full metadata records.
                             Defaults to True.

        Returns:
            The total number of records exported.
        """
        logger.debug(f"Starting cache export to '{output_path}' in '{format}' format.")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except (IOError, OSError) as err:
            logger.error(f"Output path '{output_path}' is not writable: {err}")
            raise IOError(f"Output path '{output_path}' is not writable.") from err

        conn = self._ensure_connection()
        cursor = conn.cursor()

        columns = [
            "abspath",
            "modified_time",
            "name",
            "size",
            "extension",
            "media_type",
            "hash_sha256",
            "hash_blake3",
            "hash_quick",
            "hash_tlsh",
        ]
        if include_records:
            columns.extend(["record", "is_compressed"])

        query = f"SELECT {', '.join(columns)} FROM cached_files"
        cursor.execute(query)

        rows = cursor.fetchall()
        total_records = len(rows)
        logger.debug(f"Fetched {total_records} records from the cache database.")

        data_to_export = []
        for row in rows:
            row_dict = dict(row)
            if include_records and row_dict.get("record"):
                record_data: bytes = row_dict["record"]
                is_compressed = row_dict["is_compressed"]
                try:
                    if is_compressed:
                        record_json_str = zlib.decompress(record_data).decode("utf-8")
                    else:
                        record_json_str = record_data.decode("utf-8")
                    row_dict["record"] = json.loads(record_json_str)
                except (zlib.error, json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning(f"Could not decode record for {row_dict['abspath']}: {e}")
                    row_dict["record"] = {"error": "Could not decode record"}
            data_to_export.append(row_dict)

        try:
            if format == "json.gz":
                with gzip.open(output_path, "wt", encoding="utf-8") as f:
                    json.dump(data_to_export, f, indent=2, default=str)
            elif format == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data_to_export, f, indent=2, default=str)
            else:
                raise ValueError(f"Unsupported export format: {format}")

            logger.info(f"Successfully exported {total_records} records to {output_path}")
            return total_records

        except (IOError, ValueError):
            logger.exception(f"Failed to write cache export to '{output_path}'.")
            raise
