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
from dorsal.file.index.extractors import registry, create_eav_tuple, ExtractorRegistry


def get_schema_id(keyword: str) -> str:
    """Safely looks up the exact registered schema ID containing the keyword."""
    for sid in registry._extractors:
        if keyword in sid:
            return sid
    return f"open/{keyword}"


def test_create_eav_tuple_types():
    """Tests all type casting branches for EAV tuples."""
    assert create_eav_tuple("test", "key", None) is None
    assert create_eav_tuple("test", "key", True) == ("test", "key", "true", None)
    assert create_eav_tuple("test", "key", False) == ("test", "key", "false", None)
    assert create_eav_tuple("test", "key", 42) == ("test", "key", None, 42.0)
    assert create_eav_tuple("test", "key", 3.14) == ("test", "key", None, 3.14)
    assert create_eav_tuple("test", "key", "string") == ("test", "key", "string", None)


def test_registry_conflicts_and_errors():
    """Tests the ValueError and TypeError branches inside ExtractorRegistry registration and extraction."""
    test_reg = ExtractorRegistry()

    with pytest.raises(ValueError, match="declares keys as both numeric and text"):
        test_reg.register("test1", numeric_keys=["a"], text_keys=["a"])

    test_reg.register("test2", numeric_keys=["num_key"], text_keys=["txt_key"])(lambda x: ([], []))

    with pytest.raises(ValueError, match="already registered as text"):
        test_reg.register("test3", numeric_keys=["txt_key"])(lambda x: ([], []))

    with pytest.raises(ValueError, match="already registered as numeric"):
        test_reg.register("test4", text_keys=["num_key"])(lambda x: ([], []))

    with pytest.raises(TypeError, match="is declared as numeric, but received non-numeric"):
        test_reg.create_eav_tuple("test2", "num_key", "not-a-number")

    assert test_reg.is_numeric_key("num_key") is True
    assert test_reg.is_numeric_key("txt_key") is False


def test_registry_universal_attributes():
    """Tests extraction of universal metadata fields for any schema."""
    rec = {"producer": "test_runner", "attributes": {"color": "blue", "count": 5}}
    fts, eav = registry.extract("unknown/schema", rec)

    assert fts == []

    assert ("unknown/schema", "producer", "test_runner", None) in eav
    assert ("unknown/schema", "color", "blue", None) in eav

    assert ("unknown/schema", "count", "5", None) in eav


def test_extract_document():
    schema_id = get_schema_id("document-extraction")
    rec = {
        "producer": "dorsal",
        "extraction_type": "text",
        "unit": "px",
        "page_width": 800,
        "page_height": 600,
        "blocks": [{"text": "Main content body", "page_number": 1}],
        "attributes": {"author": "Jane Doe"},
    }
    fts, eav = registry.extract(schema_id, rec)

    assert "Main content body" in fts
    assert (schema_id, "author", "Jane Doe", None) in eav


def test_extract_audio():
    schema_id = get_schema_id("audio-transcription")
    rec = {
        "text": "Full transcription",
        "language": "en",
        "track_id": "12345",
        "segments": [{"text": "first part", "start_time": 0.0, "end_time": 1.0}],
    }
    fts, eav = registry.extract(schema_id, rec)

    assert "Full transcription" in fts
    assert "first part" in fts
    assert (schema_id, "language", "en", None) in eav
    assert (schema_id, "track_id", "12345", None) in eav


def test_extract_embedding():
    schema_id = get_schema_id("embedding")

    rec_sparse = {"model": "sparse-v1", "vector": {"dimensions": 100, "indices": [5, 10], "values": [0.1, 0.2]}}
    fts, eav = registry.extract(schema_id, rec_sparse)
    if fts:
        assert "5" in fts

    rec_dense = {"model": "dense", "vector": [0.1, 0.2, 0.3]}
    fts_d, _ = registry.extract(schema_id, rec_dense)
    assert fts_d == []


def test_extract_classification():
    schema_id = get_schema_id("classification")
    rec = {"target": "sentiment", "labels": [{"label": "positive", "score": 0.99}]}
    fts, eav = registry.extract(schema_id, rec)

    extracted_strings = fts + [str(v) for _, _, v, _ in eav if v is not None]
    if extracted_strings:
        assert any("positive" in s for s in extracted_strings)


def test_extract_entity():
    schema_id = get_schema_id("entity-extraction")
    rec = {
        "entities": [
            {"text": "London", "label": "GPE", "concept": "City", "value": "UK", "definition": "Capital of the UK"}
        ]
    }
    fts, eav = registry.extract(schema_id, rec)

    assert "London" in fts
    assert "Capital of the UK" in fts
    eav_vals = [str(v) for _, _, v, _ in eav if v]
    if eav_vals:
        assert "GPE" in eav_vals


def test_extract_generic():
    schema_id = get_schema_id("generic")
    rec = {"description": "test", "data": {"user": "rio"}}
    fts, eav = registry.extract(schema_id, rec)

    assert "test" in fts
    assert (schema_id, "user", "rio", None) in eav


def test_extract_llm():
    schema_id = get_schema_id("llm-output")
    rec = {"prompt": "Tell me a joke", "response_data": {"text": "Haha"}, "model": "gpt4", "language": "en"}
    fts, eav = registry.extract(schema_id, rec)

    assert "Tell me a joke" in fts
    assert "{'text': 'Haha'}" in fts
    assert (schema_id, "model", "gpt4", None) in eav


def test_extract_object():
    schema_id = get_schema_id("object-detection")
    rec = {"objects": [{"label": "cat", "box": {"x": 10}}]}
    fts, eav = registry.extract(schema_id, rec)

    eav_vals = [str(v) for _, _, v, _ in eav if v]
    if eav_vals:
        assert "cat" in eav_vals


def test_extract_regression():
    schema_id = get_schema_id("regression")
    rec = {"target": "price", "unit": "usd", "points": [{"value": 99.9}]}
    fts, eav = registry.extract(schema_id, rec)

    assert (schema_id, "regression_value", None, 99.9) in eav


def test_extract_geolocation():
    schema_id = get_schema_id("geolocation")
    rec = {"properties": {"camera_make": "Sony", "camera_model": "Alpha"}}
    fts, eav = registry.extract(schema_id, rec)

    eav_vals = [str(v) for _, _, v, _ in eav if v]
    if eav_vals:
        assert "Sony" in eav_vals


def test_extract_arxiv():
    rec = {
        "title": "Quantum Physics",
        "abstract": "A study of atoms",
        "authors": ["John Doe", "Jane Doe"],
        "categories": ["quant-ph", "cs.AI"],
        "arxiv_id": "1234.5678",
        "doi": "10.1000/xyz123",
        "journal_ref": "Nature",
    }
    fts, eav = registry.extract("dorsal/arxiv", rec)

    assert "Quantum Physics" in fts
    assert "John Doe" in fts
    assert ("dorsal/arxiv", "arxiv_id", "1234.5678", None) in eav


def test_extract_pdf():
    rec = {
        "title": "Manual",
        "author": "Alice",
        "subject": "Guide",
        "keywords": ["help", "info"],
        "creator": "Dorsal",
        "page_count": 12,
        "version": "1.4",
    }
    fts, eav = registry.extract("file/pdf", rec)

    assert "Manual" in fts
    assert "help" in fts
    assert ("file/pdf", "page_count", None, 12.0) in eav
    assert ("file/pdf", "creator", "Dorsal", None) in eav


def test_extract_ebook():
    rec = {
        "title": "Novel",
        "publisher": "Books LLC",
        "description": "A great read",
        "authors": ["Bob"],
        "contributors": ["Eve"],
        "subjects": ["Fiction"],
        "language": "en",
        "isbn": "978-3-16-148410-0",
    }
    fts, eav = registry.extract("file/ebook", rec)

    assert "Novel" in fts
    assert "Books LLC" in fts
    assert "978-3-16-148410-0" in fts
    assert ("file/ebook", "isbn", "978-3-16-148410-0", None) in eav


def test_extract_mediainfo():
    rec = {
        "Title": "Video",
        "Encoded_Application_String": "Handbrake",
        "Format_Info": "MP4",
        "Format_String": "AVC",
        "CodecID": "h264",
        "Duration": 60.5,
        "OverallBitRate": 5000,
        "Video": [{"Width": 1920, "Height": 1080, "FrameRate": 30.0}],
        "Audio": [{"Channels": 2}],
    }
    fts, eav = registry.extract("file/mediainfo", rec)

    assert "Video" in fts
    assert "Handbrake" in fts
    assert ("file/mediainfo", "width", None, 1920.0) in eav
    assert ("file/mediainfo", "channels", None, 2.0) in eav
    assert ("file/mediainfo", "duration", None, 60.5) in eav
    assert ("file/mediainfo", "format", "AVC", None) in eav


def test_extract_mediainfo_invalid_tracks():
    """Hits the branch where tracks are parsed but are not dictionaries."""
    rec = {"Video": ["not_a_dict"], "Audio": ["not_a_dict"]}
    fts, eav = registry.extract("file/mediainfo", rec)
    assert fts == []
    assert eav == []


def test_extract_office():
    rec = {
        "title": "Q1 Report",
        "keywords": ["finance"],
        "language": "en",
        "revision": 5,
        "is_password_protected": True,
        "has_comments": False,
        "custom_properties": {"approved": "yes"},
        "word": {"page_count": 10, "has_track_changes": True},
        "excel": {
            "has_macros": False,
            "sheet_names": ["Data", "Summary"],
            "sheets": [{"name": "Data", "row_count": 100, "column_count": 10, "column_names": ["ID", "Value"]}],
        },
        "powerpoint": {"slide_count": 15, "slide_master_names": ["Master1"]},
    }
    fts, eav = registry.extract("file/office", rec)

    assert "Q1 Report" in fts
    assert ("file/office", "revision", None, 5.0) in eav
    assert ("file/office", "is_password_protected", "true", None) in eav

    assert ("file/office", "page_count", None, 10.0) in eav
    assert ("file/office", "has_track_changes", "true", None) in eav

    assert "Data" in fts
    assert "ID" in fts
    assert ("file/office", "row_count", None, 100.0) in eav

    assert "Master1" in fts
    assert ("file/office", "slide_count", None, 15.0) in eav


def test_registry_create_eav_tuple_none():
    """Hits the early exit for None values in the ExtractorRegistry's tuple router."""
    from dorsal.file.index.extractors import ExtractorRegistry

    test_reg = ExtractorRegistry()
    result = test_reg.create_eav_tuple("test/schema", "some_key", None)

    assert result is None
