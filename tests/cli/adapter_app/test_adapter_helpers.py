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
from dorsal.cli.adapter_app.helpers import extract_records


def test_extract_batch_various_packaging_styles():
    """
    Tests batch processing where items inside the 'results' list are
    packaged in different structural formats.
    """
    json_data = {
        "results": [
            {"file_path": "/test/1", "schema_id": "SchemaA", "record": {"text": "Alpha"}},
            {"file_path": "/test/2", "record": {"schema_id": "SchemaB", "text": "Beta"}},
            {"file_path": "/test/3", "schema_id": "SchemaC", "text": "Gamma"},
        ]
    }

    result = extract_records(json_data)

    assert len(result) == 3

    assert result[0] == ("SchemaA", {"text": "Alpha"}, "/test/1", None)

    assert result[1] == ("SchemaB", {"schema_id": "SchemaB", "text": "Beta"}, "/test/2", None)

    assert result[2] == ("SchemaC", {"file_path": "/test/3", "schema_id": "SchemaC", "text": "Gamma"}, "/test/3", None)


def test_extract_batch_missing_schema():
    """Tests that a batch item missing a schema_id throws a ValueError."""
    json_data = {"results": [{"file_path": "test.txt", "record": {"data": "missing schema"}}]}

    with pytest.raises(ValueError, match="Missing 'schema_id' in JSON wrapper"):
        extract_records(json_data)


def test_extract_batch_with_schema_override():
    """Tests that a schema_override applies to batch items."""
    json_data = {"results": [{"file_path": "test.txt", "record": {"data": "stuff"}}]}

    result = extract_records(json_data, schema_override="OverrideSchema")

    assert len(result) == 1
    assert result[0] == ("OverrideSchema", {"data": "stuff"}, "test.txt", None)


def test_extract_single_standard_wrapper():
    """Tests a single JSON object properly wrapped with schema_id and record."""
    json_data = {"schema_id": "SingleSchema", "record": {"data": "single value"}, "file_path": "single.txt"}

    result = extract_records(json_data)

    assert len(result) == 1
    assert result[0] == ("SingleSchema", {"data": "single value"}, "single.txt", None)


def test_extract_single_raw_missing_override():
    """Tests that a raw, unwrapped single record without an override throws a ValueError."""
    json_data = {"data": "raw data", "file_path": "raw.txt"}

    with pytest.raises(ValueError, match="Raw record detected without a schema wrapper"):
        extract_records(json_data)


def test_extract_single_raw_with_override():
    """Tests a raw, unwrapped single record paired with an explicit schema_override."""
    json_data = {"data": "raw data", "file_path": "raw.txt"}

    result = extract_records(json_data, schema_override="ForcedSchema")

    assert len(result) == 1

    assert result[0] == ("ForcedSchema", json_data, "raw.txt", None)


def test_extract_batch_skips_non_dict_items():
    """Tests that non-dictionary items in the 'results' list are safely ignored."""
    json_data = {
        "results": [
            "this is a string, not a dict",
            42,
            {"file_path": "valid.txt", "schema_id": "ValidSchema", "record": {"data": "ok"}},
        ]
    }

    result = extract_records(json_data)

    assert len(result) == 1
    assert result[0] == ("ValidSchema", {"data": "ok"}, "valid.txt", None)


def test_extract_batch_with_chunked_records():
    """Tests batch processing where an item uses the 'records' array for chunked outputs."""
    json_data = {
        "results": [
            {
                "file_path": "/test/chunked",
                "schema_id": "ChunkSchema",
                "records": [{"part": 1}, "invalid_string_chunk", {"part": 2}],
            }
        ]
    }

    result = extract_records(json_data)

    assert len(result) == 2
    assert result[0] == ("ChunkSchema", {"part": 1}, "/test/chunked", None)
    assert result[1] == ("ChunkSchema", {"part": 2}, "/test/chunked", None)


def test_extract_single_with_chunked_records():
    """Tests extracting the 'records' array from a single payload wrapper."""
    json_data = {
        "schema_id": "SingleChunkSchema",
        "file_path": "single_chunked.txt",
        "records": [{"chunk": "A"}, ["invalid list chunk"], {"chunk": "B"}],
    }

    result = extract_records(json_data)

    assert len(result) == 2
    assert result[0] == ("SingleChunkSchema", {"chunk": "A"}, "single_chunked.txt", None)
    assert result[1] == ("SingleChunkSchema", {"chunk": "B"}, "single_chunked.txt", None)


def test_extract_records_reads_schema_versions():
    json_data = {
        "results": [
            {"file_path": "a", "schema_id": "audio-transcription", "schema_version": "0.5.0", "record": {"text": "A"}},
            {"file_path": "b", "schema_id": "audio-transcription", "records": [{"text": "B"}]},
        ]
    }

    result = extract_records(json_data)

    assert [version for *_, version in result] == ["0.5.0", None]


def test_extract_records_single_wrapper_version():
    json_data = {
        "schema_id": "audio-transcription",
        "schema_version": "0.7.0",
        "records": [{"text": "A"}, {"text": "B"}],
    }

    assert [version for *_, version in extract_records(json_data)] == ["0.7.0", "0.7.0"]


def test_extract_records_version_override_wins():
    json_data = {"schema_id": "audio-transcription", "schema_version": "0.7.0", "record": {"text": "A"}}

    assert extract_records(json_data, version_override="0.8.0")[0][3] == "0.8.0"
    assert (
        extract_records({"text": "A"}, schema_override="audio-transcription", version_override="0.6.0")[0][3] == "0.6.0"
    )


HUB_ANNOTATION = {
    "annotation_id": "abc",
    "file_hash": "a" * 64,
    "schema_id": "open/audio-transcription",
    "schema_version": None,
    "record": {"text": "A"},
    "user_id": 1,
}


def test_extract_records_reads_an_unversioned_hub_annotation_as_0_5_0():
    assert extract_records(HUB_ANNOTATION)[0][3] == "0.5.0"
    assert extract_records({**HUB_ANNOTATION, "schema_version": "0.8.0"})[0][3] == "0.8.0"
    assert extract_records(HUB_ANNOTATION, version_override="0.8.0")[0][3] == "0.8.0"
    assert extract_records({"results": [HUB_ANNOTATION]})[0][3] == "0.5.0"


def test_extract_records_unversioned_local_and_non_oats_records_keep_none():
    local = {"schema_id": "open/audio-transcription", "schema_version": None, "record": {"text": "A"}}
    assert extract_records(local)[0][3] is None
    assert extract_records({**HUB_ANNOTATION, "schema_id": "dorsal/arxiv"})[0][3] is None
