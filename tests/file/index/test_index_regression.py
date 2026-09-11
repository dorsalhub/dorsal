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
from pathlib import Path

from dorsal.file.index.dorsal_index import DorsalIndex
from dorsal.file.index.query import QueryParser, QueryCompiler


@pytest.fixture
def populated_index(tmp_path: Path, make_mock_record, mocker) -> DorsalIndex:
    """
    Creates an in-memory or temp-file SQLite index pre-populated with a specific
    'golden dataset' designed to test query boundary limits, EAV extraction, and deep/shallow states.
    """
    mocker.patch("dorsal.file.index.dorsal_index.make_local_record_id", return_value="mock_local_id")

    db_path = tmp_path / "regression_search.db"
    index = DorsalIndex(db_path=db_path, use_compression=False)
    index.connect()

    def add_file(
        path: str,
        ext: str,
        size: int,
        media_type: str = None,
        is_deep: bool = True,
        creator: str = None,
        title: str = None,
    ):
        """Helper to inject specific scenarios into the mock records."""
        rec = make_mock_record(path, ext=ext, size=size)
        rec_dict = rec.model_dump(by_alias=True)

        if media_type:
            rec_dict["annotations"]["file/base"]["record"]["media_type"] = media_type

        if creator:
            rec_dict["annotations"]["file/pdf"] = {
                "schema_id": "file/pdf",
                "source": {"type": "Model", "id": "pdf", "version": "1.0"},
                "record": {"creator": creator},
            }
        if title:
            rec_dict["annotations"]["file/ebook"] = {
                "schema_id": "file/ebook",
                "source": {"type": "Model", "id": "ebook", "version": "1.0"},
                "record": {"title": title},
            }

        if not is_deep:
            rec_dict["hash"] = None
            rec_dict["validation_hash"] = None
            rec_dict["annotations"]["file/base"]["record"]["hash"] = None
            rec_dict["annotations"]["file/base"]["record"]["all_hash_ids"] = None

        from dorsal.file.validators.file_record import FileRecord

        valid_rec = FileRecord.model_validate(rec_dict)
        index.upsert_record(path=path, modified_time=100.0, record=valid_rec)

    add_file("/bill.pdf", ".pdf", 81920)

    add_file("/desktop-latest.msi", ".msi", 22020096, media_type="application/x-msi")

    add_file("/2405.06604v1.pdf", ".pdf", 15728640, is_deep=False)

    add_file("/big_buck_bunny_1080p_h264.mov", ".mov", 725614592, media_type="video/quicktime")

    add_file("/Things fall apart.epub", ".epub", 175104, title="Things Fall Apart")

    add_file("/Design Patterns.pdf", ".pdf", 17825792, creator="Acrobat 5.0 Paper Capture Plug-in for Windows")

    yield index
    index.close()


def execute_search(index: DorsalIndex, query_str: str, or_logic: bool = False, deep: bool = False) -> list[str]:
    """Helper to run the query string through the full DB pipeline and return paths."""
    parsed = QueryParser.parse(query_str)
    sql, params = QueryCompiler.compile(parsed, or_logic=or_logic, deep=deep)

    cursor = index.conn.cursor()
    cursor.execute(sql, params)
    return [row["abspath"] for row in cursor.fetchall()]


def test_search_regression_chaining_and_logic(populated_index):
    """Proves that un-flagged queries strictly enforce AND logic."""
    results = execute_search(populated_index, "ext:pdf size>20MiB")

    assert len(results) == 0


def test_search_regression_chaining_or_logic(populated_index):
    """Proves that --or correctly brackets the user query and evaluates matches broadly."""
    results = execute_search(populated_index, "ext:pdf size>20MiB", or_logic=True)

    assert "/bill.pdf" in results
    assert "/desktop-latest.msi" in results
    assert "/big_buck_bunny_1080p_h264.mov" in results
    assert "/2405.06604v1.pdf" in results
    assert "/Design Patterns.pdf" in results
    assert len(results) == 5


def test_search_regression_eav_exact_phrases(populated_index):
    """Proves that quotes preserve spaces in both FTS texts and EAV value lookups."""
    results = execute_search(
        populated_index, '"Design Patterns" creator:"Acrobat 5.0 Paper Capture Plug-in for Windows"'
    )

    assert len(results) == 1
    assert results[0] == "/Design Patterns.pdf"


def test_search_regression_wildcard_presence(populated_index):
    """Proves that 'key:*' maps to an IS NOT NULL presence check."""
    results = execute_search(populated_index, "title:* size<1MB")

    assert len(results) == 1
    assert results[0] == "/Things fall apart.epub"


def test_search_regression_wildcard_like(populated_index):
    """Proves that trailing wildcards compile to LIKE clauses for base columns."""
    results = execute_search(populated_index, "media_type:video/* *bunny*")

    assert len(results) == 1
    assert results[0] == "/big_buck_bunny_1080p_h264.mov"


def test_search_regression_deep_flag(populated_index):
    """
    Proves the bug fix where shallow records (missing hashes) are successfully filtered
    out by the compiler's deep=True database requirement.
    """

    standard_results = execute_search(populated_index, "ext:pdf")
    assert "/2405.06604v1.pdf" in standard_results
    assert len(standard_results) == 3

    deep_results = execute_search(populated_index, "ext:pdf", deep=True)
    assert "/2405.06604v1.pdf" not in deep_results
    assert "/bill.pdf" in deep_results
    assert len(deep_results) == 2


def test_search_regression_hash_router(populated_index):
    """Proves that providing a raw hash intelligently routes to the hash SQL blocks."""
    import hashlib

    dummy_md5 = hashlib.md5("/bill.pdf".encode("utf-8")).hexdigest()

    results = execute_search(populated_index, dummy_md5)

    assert len(results) == 1
    assert results[0] == "/bill.pdf"
