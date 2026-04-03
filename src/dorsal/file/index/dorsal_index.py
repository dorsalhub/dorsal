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

from __future__ import annotations
import functools
import gzip
import json
import sqlite3
import os
import logging
import weakref
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING, Callable
import zlib

from pydantic import BaseModel, Field

from dorsal.file.index.extractors import registry, create_eav_tuple
from dorsal.file.index.config import get_index_compression, get_index_compression_level, get_index_compression_mode

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import FileRecordStrict

logger = logging.getLogger(__name__)


class CachedFileRecord(BaseModel):
    """Pydantic model representing a single record in the local index database."""

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


class DorsalIndex:
    """
    Manages the Dorsal SQLite Search Index.
    """

    def __init__(self, db_path: Path | None = None, use_compression: bool = True, compression_mode: Literal["zlib", "zstd"] = "zlib",
        compression_level: int | None = None,):
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = Path.home() / ".dorsal" / "cache.db"

        self.use_compression = use_compression
        self.compression_mode = compression_mode.lower()
        self.compression_level = compression_level
        self.conn: sqlite3.Connection | None = None
        self._ensure_db_directory_exists()
        self._finalizer = weakref.finalize(self, self._finalize_connection, self.conn)
        logger.debug(f"LocalIndex initialized for path: {self.db_path} with compression={self.use_compression}")

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
            logger.debug(f"Creating database directory at: {self.db_path.parent}")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        """Establishes a connection to the SQLite database and initializes the schema."""
        if self.conn is None:
            logger.debug(f"Connecting to database: {self.db_path}")
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
        """Creates/updates the core tables and search indexes."""
        conn = self._ensure_connection()
        cursor = conn.cursor()

        logger.debug("Initializing database schema...")

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

        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS dorsal_fts USING fts5(
                abspath UNINDEXED, 
                content
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS file_attributes (
                abspath TEXT,
                schema_id TEXT,
                key TEXT,
                value_text TEXT,
                value_num REAL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        
        cursor.execute(
            """
            INSERT OR IGNORE INTO index_meta (key, value) 
            VALUES ('created_at', datetime('now'))
            """
        )

        logger.debug("Ensuring all indexes exist...")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_sha256 ON cached_files (hash_sha256);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_blake3 ON cached_files (hash_blake3);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_quick ON cached_files (hash_quick);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash_tlsh ON cached_files (hash_tlsh);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON cached_files (name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extension ON cached_files (extension);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_type ON cached_files (media_type);")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attr_schema ON file_attributes (schema_id, abspath);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attr_exact_text ON file_attributes (key, value_text, abspath);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attr_exact_num ON file_attributes (key, value_num, abspath);")

        conn.commit()
        logger.debug("Schema initialization complete.")

    def _extract_search_data(self, record: "FileRecordStrict") -> tuple[list[str], list[tuple]]:
        """Extracts searchable data by delegating to the ExtractorRegistry."""
        fts_texts: list[str] = []
        eav_attributes: list[tuple] = []

        if record.annotations and record.annotations.file_base:
            base = record.annotations.file_base.record
            if base and base.name:
                fts_texts.append(base.name)
            if base and base.extension:
                fts_texts.append(base.extension)

        if hasattr(record, "tags"):
            for tag in record.tags:
                tup = create_eav_tuple("tag", tag.name, tag.value)
                if tup:
                    eav_attributes.append(tup)

        if not record.annotations:
            return fts_texts, eav_attributes

        annotations_dict = record.annotations.model_dump(by_alias=True, exclude_none=True)

        for schema_id, annotation_data in annotations_dict.items():
            if annotation_data is None:
                continue

            ann_list = annotation_data if isinstance(annotation_data, list) else [annotation_data]

            for ann in ann_list:
                rec_dict = ann.get("record", {}) if isinstance(ann, dict) else getattr(ann, "record", {})

                if hasattr(rec_dict, "model_dump"):
                    rec_dict = rec_dict.model_dump(exclude_none=True)
                elif not isinstance(rec_dict, dict):
                    continue

                schema_fts, schema_eav = registry.extract(schema_id, rec_dict)
                fts_texts.extend(schema_fts)
                eav_attributes.extend(schema_eav)

        return fts_texts, eav_attributes

    def upsert_record(self, *, path: str, modified_time: float, record: "FileRecordStrict"):
        """Inserts or replaces a record, updating search indexes and respecting compression."""
        conn = self._ensure_connection()
        logger.debug(f"Upserting record and search indexes for path: {path}")
        base_annotation = record.annotations.file_base.record
        all_hashes = base_annotation.all_hash_ids or {}

        record_json_str = record.model_dump_json(by_alias=True, exclude_none=True)
        
        if self.use_compression:
            compress_fn, is_compressed_flag = self._get_compressor(
                self.compression_mode, self.compression_level
            )
            logger.debug(f"Compressing record for path: {path} with {self.compression_mode}")
            record_data = compress_fn(record_json_str.encode("utf-8"))
        else:
            record_data = record_json_str.encode("utf-8")
            is_compressed_flag = 0

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

        fts_texts, eav_attributes = self._extract_search_data(record)

        full_fts_text = " ".join([str(t) for t in fts_texts if t]).strip()

        eav_inserts = [(path, attr[0], attr[1], attr[2], attr[3]) for attr in eav_attributes]

        cursor = conn.cursor()

        cursor.execute("DELETE FROM dorsal_fts WHERE abspath = ?", (path,))
        cursor.execute("DELETE FROM file_attributes WHERE abspath = ?", (path,))

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

        if full_fts_text:
            cursor.execute("INSERT INTO dorsal_fts (abspath, content) VALUES (?, ?)", (path, full_fts_text))

        if eav_inserts:
            cursor.executemany(
                "INSERT INTO file_attributes (abspath, schema_id, key, value_text, value_num) VALUES (?, ?, ?, ?, ?)",
                eav_inserts,
            )

        conn.commit()
        logger.debug(f"Successfully upserted record and search indexes for path: {path}")

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

        decompress_fn = self._get_decompressor(is_compressed_flag)
        
        try:
            record_json_str = decompress_fn(record_data).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to decompress record for {path}: {e}")
            return None

        row_dict["record"] = record_json_str
        return CachedFileRecord.model_validate(row_dict)

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

                cursor.execute("DELETE FROM dorsal_fts WHERE abspath = ?", (path,))
                cursor.execute("DELETE FROM file_attributes WHERE abspath = ?", (path,))

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
            current_mod_time = os.lstat(path).st_mtime
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
        logger.debug(f"Clearing index by deleting database file: {self.db_path}")
        self.close()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.debug("Database file successfully removed.")
        except OSError as e:
            logger.error(f"Error removing file at {self.db_path}: {e}")

    def close(self):
        """Commit any pending changes and close the connection."""
        if self.conn:
            logger.debug("Closing database connection.")
            self.conn.commit()
            self.conn.close()
            self.conn = None

    def summary(self, verbose: bool = False, limit: int = 10) -> dict:
        """Provides a summary of the index's current state."""
        limit = int(limit)
        conn = self._ensure_connection()
        logger.debug(f"Generating index summary (verbose={verbose})...")
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM cached_files")
        record_count = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM cached_files WHERE record IS NOT NULL")
        full_records = cursor.fetchone()[0] or 0
        hash_only_records = record_count - full_records

        try:
            stat = os.stat(self.db_path)
            db_size_bytes = stat.st_size
            db_modified_time = stat.st_mtime
            fallback_created_time = stat.st_ctime
        except FileNotFoundError:
            db_size_bytes = 0
            db_modified_time = 0
            fallback_created_time = 0

        try:
            cursor.execute("SELECT value FROM index_meta WHERE key = 'created_at'")
            meta_row = cursor.fetchone()
            if meta_row and meta_row[0]:
                import datetime
                dt = datetime.datetime.strptime(meta_row[0], "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=datetime.timezone.utc)
                db_created_time = dt.timestamp()
            else:
                db_created_time = fallback_created_time
        except sqlite3.OperationalError:
            db_created_time = fallback_created_time

        summary_data = {
            "database_path": str(self.db_path),
            "total_records": record_count,
            "full_records": full_records,
            "hash_only_records": hash_only_records,
            "database_size_bytes": db_size_bytes,
            "created_time": db_created_time,
            "modified_time": db_modified_time,
        }

        if verbose:
            cursor.execute("SELECT COUNT(*) FROM dorsal_fts")
            summary_data["fts_indexed_records"] = cursor.fetchone()[0] or 0

            cursor.execute("SELECT SUM(size) FROM cached_files")
            summary_data["total_tracked_file_bytes"] = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM cached_files WHERE is_compressed > 0")
            compressed_count = cursor.fetchone()[0] or 0
            summary_data["compressed_records"] = compressed_count

            cursor.execute("SELECT COUNT(*) FROM file_attributes")
            summary_data["indexed_attributes"] = cursor.fetchone()[0] or 0

            # --- NEW: Storage Breakdown ---
            cursor.execute("SELECT MAX(LENGTH(record)), AVG(LENGTH(record)) FROM cached_files WHERE record IS NOT NULL")
            record_stats = cursor.fetchone()
            if record_stats:
                summary_data["max_record_size_bytes"] = record_stats[0] or 0
                summary_data["avg_record_size_bytes"] = int(record_stats[1] or 0)
            
            # --- NEW: Deduplication Insights ---
            cursor.execute("SELECT COUNT(DISTINCT hash_blake3) FROM cached_files WHERE hash_blake3 IS NOT NULL")
            unique_hashes = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(*) FROM cached_files WHERE hash_blake3 IS NOT NULL")
            total_hashed = cursor.fetchone()[0] or 0
            
            summary_data["unique_files_by_hash"] = unique_hashes
            summary_data["duplicate_files_detected"] = max(0, total_hashed - unique_hashes)
            
            # --- NEW: Data Freshness ---
            cursor.execute("SELECT MIN(modified_time), MAX(modified_time) FROM cached_files")
            time_stats = cursor.fetchone()
            if time_stats:
                summary_data["oldest_record_timestamp"] = time_stats[0]
                summary_data["newest_record_timestamp"] = time_stats[1]

            # --- NEW: Deep Taxonomy ---
            cursor.execute(f"""
                SELECT key, COUNT(*) as count 
                FROM file_attributes 
                WHERE key IS NOT NULL
                GROUP BY key 
                ORDER BY count DESC LIMIT {limit}
            """)
            summary_data["top_attribute_keys"] = {row["key"]: row["count"] for row in cursor.fetchall()}

            if compressed_count > 0:
                cursor.execute("SELECT is_compressed, record FROM cached_files WHERE is_compressed > 0 LIMIT 100")
                sample_rows = cursor.fetchall()
                total_uncompressed = 0
                total_compressed = 0
                for r in sample_rows:
                    comp_data = r["record"]
                    comp_flag = r["is_compressed"]
                    if comp_data:
                        total_compressed += len(comp_data)
                        try:
                            decompress_fn = self._get_decompressor(comp_flag)
                            total_uncompressed += len(decompress_fn(comp_data))
                        except Exception:
                            pass
                if total_compressed > 0 and total_uncompressed > 0:
                    summary_data["compression_ratio_sample"] = total_uncompressed / total_compressed

            compression_mode = get_index_compression_mode()
            summary_data["compression_mode"] = compression_mode
            summary_data["compression_level"] = get_index_compression_level(compression_mode=compression_mode)

            cursor.execute("""
                SELECT extension, COUNT(*) as count 
                FROM cached_files 
                WHERE extension IS NOT NULL 
                GROUP BY extension 
                ORDER BY count DESC LIMIT ?
            """, (limit,))
            summary_data["top_extensions"] = {row["extension"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("""
                SELECT media_type, COUNT(*) as count 
                FROM cached_files 
                WHERE media_type IS NOT NULL 
                GROUP BY media_type 
                ORDER BY count DESC LIMIT ?
            """, (limit,))
            summary_data["top_media_types"] = {row["media_type"]: row["count"] for row in cursor.fetchall()}

            cursor.execute(f"""
                SELECT schema_id, COUNT(DISTINCT abspath) as count 
                FROM file_attributes 
                WHERE schema_id != 'file/base'
                GROUP BY schema_id 
                ORDER BY count DESC LIMIT ?
            """, (limit,))
            summary_data["top_schemas"] = {row["schema_id"]: row["count"] for row in cursor.fetchall()}

        logger.debug(f"Index summary generated: {summary_data}")
        return summary_data

    def prune(self) -> tuple[int, int]:
        """Prunes the index by removing stale records."""
        conn = self._ensure_connection()
        logger.debug("Starting index prune operation...")
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
                current_mod_time = os.lstat(path).st_mtime
                if current_mod_time != cached_mod_time:
                    logger.debug(f"Marking stale (mtime mismatch): {path}")
                    stale_paths.append(path)
            except FileNotFoundError:
                logger.debug(f"Marking stale (path disappeared during check): {path}")
                stale_paths.append(path)

        if not stale_paths:
            logger.debug("Prune complete. No stale records found.")
            return (0, total_records)

        logger.debug(f"Removing {len(stale_paths)} stale records and their indexes...")
        cursor.executemany(
            "DELETE FROM cached_files WHERE abspath = ?",
            [(path,) for path in stale_paths],
        )
        cursor.executemany(
            "DELETE FROM dorsal_fts WHERE abspath = ?",
            [(path,) for path in stale_paths],
        )
        cursor.executemany(
            "DELETE FROM file_attributes WHERE abspath = ?",
            [(path,) for path in stale_paths],
        )
        conn.commit()

        logger.debug(f"Prune complete. Removed {len(stale_paths)} of {total_records} records.")
        return (len(stale_paths), total_records)

    def vacuum(self) -> None:
        """Rebuilds the database file, reclaiming free space."""
        conn = self._ensure_connection()
        logger.debug("Starting vacuum...")
        conn.execute("VACUUM")
        conn.commit()
        logger.debug("Vacuum complete.")

    def optimize(self, force_recompression: bool = False) -> dict:
        """Runs a full maintenance routine on the index."""
        self._ensure_connection()
        logger.debug(f"Starting full index optimization (Force recompression: {force_recompression})...")
        
        size_before = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        pruned_count, _ = self.prune()
        
        rewritten_count = self.convert_compression(
            self.compression_mode if self.use_compression else "none", 
            self.compression_level,
            force=force_recompression
        )
        
        self.vacuum()
        size_after = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        result = {
            "stale_records_removed": pruned_count,
            "records_rewritten_for_compression": rewritten_count,
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "size_reclaimed_bytes": size_before - size_after,
        }
        logger.debug(f"Index optimization complete: {result}")
        return result

    def rebuild(self, batch_size: int = 100, progress_callback: Callable[[int, int], None] | None = None) -> int:
        """Rebuilds the FTS and EAV search indexes from the compressed cache."""
        from dorsal.file.validators.file_record import FileRecordStrict
        
        conn = self._ensure_connection()
        logger.info("Starting full search index rebuild...")

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cached_files WHERE record IS NOT NULL")
        total_records = cursor.fetchone()[0]

        if progress_callback:
            progress_callback(0, total_records)

        cursor.execute("DELETE FROM dorsal_fts")
        cursor.execute("DELETE FROM file_attributes")
        
        read_cursor = conn.cursor()
        read_cursor.execute("SELECT abspath, record, is_compressed FROM cached_files WHERE record IS NOT NULL")

        count = 0
        batch_fts = []
        batch_eav = []

        for row in read_cursor:
            path = row["abspath"]
            record_data = row["record"]
            is_compressed_flag = row["is_compressed"]

            try:
                decompress_fn = self._get_decompressor(is_compressed_flag)
                record_json_str = decompress_fn(record_data).decode("utf-8")
                record_obj = FileRecordStrict.model_validate_json(record_json_str)
                
                fts_texts, eav_attributes = self._extract_search_data(record_obj)
                
                full_fts_text = " ".join([str(t) for t in fts_texts if t]).strip()
                if full_fts_text:
                    batch_fts.append((path, full_fts_text))
                    
                for attr in eav_attributes:
                    batch_eav.append((path, attr[0], attr[1], attr[2], attr[3]))

            except Exception as e:
                logger.warning(f"Failed to reindex record {path}: {e}")

            count += 1

            if count % batch_size == 0:
                if batch_fts:
                    cursor.executemany("INSERT INTO dorsal_fts (abspath, content) VALUES (?, ?)", batch_fts)
                if batch_eav:
                    cursor.executemany(
                        "INSERT INTO file_attributes (abspath, schema_id, key, value_text, value_num) VALUES (?, ?, ?, ?, ?)",
                        batch_eav
                    )
                batch_fts.clear()
                batch_eav.clear()
                
                if progress_callback:
                    progress_callback(count, total_records)

        if batch_fts:
            cursor.executemany("INSERT INTO dorsal_fts (abspath, content) VALUES (?, ?)", batch_fts)
        if batch_eav:
            cursor.executemany(
                "INSERT INTO file_attributes (abspath, schema_id, key, value_text, value_num) VALUES (?, ?, ?, ?, ?)",
                batch_eav
            )

        conn.commit()
        if progress_callback:
            progress_callback(count, total_records)

        logger.info(f"Successfully reindexed {count} records.")
        return count

    @functools.lru_cache(maxsize=4)
    def _get_compressor(self, mode: str, level: int | None) -> tuple[Callable[[bytes], bytes], int]:
        """
        Returns a cached tuple of (compression_function, is_compressed_flag).
        """
        if mode == "zlib":
            lvl = level if level is not None else 6
            return (lambda data: zlib.compress(data, level=lvl)), 1
            
        elif mode == "zstd":
            lvl = level if level is not None else 3
            try:
                # Python 3.14+ Native
                import compression.zstd as zstd
                return (lambda data: zstd.compress(data, level=lvl)), 2
            except ImportError:
                try:
                    # PyPI Fallback
                    import zstandard
                    cctx = zstandard.ZstdCompressor(level=lvl)
                    return cctx.compress, 2
                except ImportError:
                    raise RuntimeError(
                        "zstd compression is enabled, but neither the Python 3.14+ "
                        "'compression.zstd' module nor the PyPI 'zstandard' package is available. "
                        "Run `pip install zstandard` or switch config back to 'zlib'."
                    )
        raise ValueError(f"Unsupported compression mode: {mode}")

    @functools.lru_cache(maxsize=4)
    def _get_decompressor(self, flag: int) -> Callable[[bytes], bytes]:
        """
        Returns a cached decompression function based on the database flag.
        """
        if flag == 0:
            return lambda data: data
        elif flag == 1:
            return zlib.decompress
        elif flag == 2:
            try:
                import compression.zstd as zstd
                return zstd.decompress
            except ImportError:
                try:
                    import zstandard
                    dctx = zstandard.ZstdDecompressor()
                    return dctx.decompress
                except ImportError:
                    raise RuntimeError(
                        "Failed to read cache. This index contains 'zstd' compressed records, "
                        "but your current environment does not support it. "
                        "Please upgrade to Python 3.14+, `pip install zstandard`, or clear the cache."
                    )
        raise ValueError(f"Unknown compression flag in database: {flag}")

    def convert_compression(
        self, 
        target_mode: Literal["zlib", "zstd", "none"], 
        target_level: int | None = None,
        force: bool = False
    ) -> int:
        """
        Converts the entire database to a target compression algorithm.
        Returns the number of records rewritten.
        """
        conn = self._ensure_connection()
        logger.info(f"Starting bulk compression conversion to: {target_mode} (Force: {force})")

        if target_mode == "none":
            target_flag = 0
            compress_fn = lambda d: d
        else:
            compress_fn, target_flag = self._get_compressor(target_mode, target_level)

        read_cursor = conn.cursor()
        write_cursor = conn.cursor()
        
        read_cursor.execute(
            "SELECT abspath, record, is_compressed FROM cached_files WHERE record IS NOT NULL"
        )

        rewritten_count = 0
        for row in read_cursor:
            path = row["abspath"]
            data = row["record"]
            current_flag = row["is_compressed"]

            if current_flag == target_flag and not force:
                continue

            try:
                decompress_fn = self._get_decompressor(current_flag)
                raw_bytes = decompress_fn(data)
                new_data = compress_fn(raw_bytes)

                write_cursor.execute(
                    "UPDATE cached_files SET record = ?, is_compressed = ? WHERE abspath = ?",
                    (new_data, target_flag, path),
                )
                rewritten_count += 1
            except Exception as e:
                logger.error(f"Failed to convert compression for {path}: {e}")

        if rewritten_count > 0:
            conn.commit()
            logger.info(f"Successfully converted {rewritten_count} records. Vacuuming database...")
            self.vacuum()
        else:
            logger.debug("All records already match the target compression state.")

        return rewritten_count

    def export(
        self,
        output_path: Path,
        format: Literal["json", "json.gz"] = "json.gz",
        include_records: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
        batch_size: int = 100,
    ) -> int:
        """
        Exports the contents of the index to a file using memory-efficient, chunked writes.
        """
        logger.debug(f"Starting export to '{output_path}' in '{format}' format (Batch size: {batch_size}).")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except (IOError, OSError) as err:
            logger.error(f"Output path '{output_path}' is not writable: {err}")
            raise IOError(f"Output path '{output_path}' is not writable.") from err

        conn = self._ensure_connection()
        cursor = conn.cursor()

        # Get total count
        cursor.execute("SELECT COUNT(*) FROM cached_files")
        total_records = cursor.fetchone()[0]

        # 1. Instantly inform the UI of the total so it doesn't pulse blindly
        if progress_callback:
            progress_callback(0, total_records)

        columns = [
            "abspath", "modified_time", "name", "size", "extension", 
            "media_type", "hash_sha256", "hash_blake3", "hash_quick", "hash_tlsh"
        ]
        if include_records:
            columns.extend(["record", "is_compressed"])

        query = f"SELECT {', '.join(columns)} FROM cached_files"
        cursor.execute(query)

        count = 0

        try:
            if format == "json.gz":
                import gzip
                f = gzip.open(output_path, "wt", encoding="utf-8")
            else:
                f = open(output_path, "wt", encoding="utf-8")
                
            with f:
                f.write("[\n")
                first_batch = True

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break

                    batch_strings = []
                    for row in rows:
                        row_dict = dict(row)
                        record_json_str = "null"
                        
                        if include_records and row_dict.get("record"):
                            record_data: bytes = row_dict["record"]
                            is_compressed_flag = row_dict["is_compressed"]
                            try:
                                decompress_fn = self._get_decompressor(is_compressed_flag)
                                record_json_str = decompress_fn(record_data).decode("utf-8")
                            except Exception as e:
                                logger.warning(f"Could not decode record for {row_dict['abspath']}: {e}")
                                record_json_str = '{"error": "Could not decode record"}'

                        # 3. The JSON Splice: Avoid round-tripping the giant record string through loads() and dumps()
                        row_dict.pop("record", None)
                        row_dict.pop("is_compressed", None)
                        
                        # Dump the tiny metadata dict
                        meta_json = json.dumps(row_dict, default=str)
                        
                        if include_records:
                            # Slice off the closing '}' and manually append the pre-formatted record JSON string
                            final_row_json = f'{meta_json[:-1]}, "record": {record_json_str}}}'
                        else:
                            final_row_json = meta_json

                        batch_strings.append(final_row_json)

                    if batch_strings:
                        if not first_batch:
                            f.write(",\n")
                        f.write(",\n".join(batch_strings))
                        first_batch = False

                    # 4. Sync the UI
                    count += len(rows)
                    if progress_callback:
                        progress_callback(count, total_records)

                f.write("\n]")

            logger.info(f"Successfully exported {count} records to {output_path}")
            return count

        except (IOError, ValueError):
            logger.exception(f"Failed to write export to '{output_path}'.")
            raise
