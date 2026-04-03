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
from dorsal.file.index.extractors import registry, create_eav_tuple


def test_create_eav_tuple_types():
    """Tests all type casting branches for EAV tuples."""
    assert create_eav_tuple("test", "key", None) is None
    assert create_eav_tuple("test", "key", True) == ("test", "key", "true", None)
    assert create_eav_tuple("test", "key", False) == ("test", "key", "false", None)
    assert create_eav_tuple("test", "key", 42) == ("test", "key", None, 42.0)
    assert create_eav_tuple("test", "key", 3.14) == ("test", "key", None, 3.14)
    assert create_eav_tuple("test", "key", "string") == ("test", "key", "string", None)


def test_registry_universal_attributes():
    """Tests that producer and generic attributes are extracted regardless of schema."""
    rec = {"producer": "test_runner", "attributes": {"color": "blue", "count": 5}}
    fts, eav = registry.extract("unknown/schema", rec)

    assert fts == []
    assert ("unknown/schema", "producer", "test_runner", None) in eav
    assert ("unknown/schema", "color", "blue", None) in eav
    assert ("unknown/schema", "count", "5", None) in eav


def test_extract_audio():
    rec = {"text": "hello", "segments": [{"text": "world"}], "language": "eng", "track_id": "1"}
    fts, eav = registry.extract("open/audio-transcription", rec)
    assert fts == ["hello", "world"]
    assert ("open/audio-transcription", "language", "eng", None) in eav
    assert ("open/audio-transcription", "track_id", "1", None) in eav


def test_extract_classification():
    rec = {"target": "sentiment", "labels": [{"label": "positive"}]}
    fts, eav = registry.extract("open/classification", rec)
    assert ("open/classification", "target", "sentiment", None) in eav
    assert ("open/classification", "label", "positive", None) in eav


def test_extract_document():
    rec = {"blocks": [{"text": "header"}]}
    fts, eav = registry.extract("open/document-extraction", rec)
    assert fts == ["header"]


def test_extract_entity():
    rec = {"entities": [{"text": "Apple", "definition": "Company", "label": "ORG", "concept": "CORP", "value": "AAPL"}]}
    fts, eav = registry.extract("open/entity-extraction", rec)
    assert "Apple" in fts
    assert "Company" in fts
    assert ("open/entity-extraction", "label", "ORG", None) in eav
    assert ("open/entity-extraction", "concept", "CORP", None) in eav
    assert ("open/entity-extraction", "value", "AAPL", None) in eav


def test_extract_generic():
    rec = {"description": "test", "data": {"key1": "val1"}}
    fts, eav = registry.extract("open/generic", rec)
    assert fts == ["test"]
    assert ("open/generic", "key1", "val1", None) in eav


def test_extract_geolocation():
    rec = {"properties": {"camera_make": "Canon", "camera_model": "EOS"}}
    fts, eav = registry.extract("open/geolocation", rec)
    assert ("open/geolocation", "camera_make", "Canon", None) in eav
    assert ("open/geolocation", "camera_model", "EOS", None) in eav


def test_extract_llm():
    rec = {"prompt": "hi", "response_data": {"nested": "json"}, "model": "gpt4", "language": "eng"}
    fts, eav = registry.extract("open/llm-output", rec)
    assert "hi" in fts
    assert "{'nested': 'json'}" in fts
    assert ("open/llm-output", "model", "gpt4", None) in eav
    assert ("open/llm-output", "language", "eng", None) in eav


def test_extract_object():
    rec = {"objects": [{"label": "cat"}]}
    fts, eav = registry.extract("open/object-detection", rec)
    assert ("open/object-detection", "label", "cat", None) in eav


def test_extract_regression():
    rec = {"target": "price", "unit": "usd", "points": [{"value": 100.5}]}
    fts, eav = registry.extract("open/regression", rec)
    assert ("open/regression", "target", "price", None) in eav
    assert ("open/regression", "unit", "usd", None) in eav
    assert ("open/regression", "regression_value", None, 100.5) in eav


def test_extract_arxiv():
    rec = {
        "title": "T",
        "abstract": "A",
        "authors": ["John"],
        "categories": ["CS"],
        "arxiv_id": "1",
        "doi": "2",
        "journal_ref": "3",
    }
    fts, eav = registry.extract("dorsal/arxiv", rec)
    assert fts == ["T", "A", "John"]
    assert ("dorsal/arxiv", "author", "John", None) in eav
    assert ("dorsal/arxiv", "category", "CS", None) in eav
    assert ("dorsal/arxiv", "arxiv_id", "1", None) in eav
    assert ("dorsal/arxiv", "doi", "2", None) in eav
    assert ("dorsal/arxiv", "journal_ref", "3", None) in eav
