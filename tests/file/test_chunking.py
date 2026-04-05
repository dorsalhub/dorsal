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
from unittest.mock import patch
import logging

from dorsal.file.chunking import (
    GenericListStrategy,
    DictUpdateStrategy,
    StringStrategy,
    DocumentExtractionStrategy,
    AudioTranscriptionStrategy,
    EmbeddingStrategy,
    chunk_record,
    merge_chunked_records,
)


class TestGenericListStrategy:
    def setup_method(self):
        self.strategy = GenericListStrategy(list_field="items")

    def test_split_missing_field(self):
        record = {"other_field": "data"}
        assert self.strategy.split(record, limit=2) == [record]

    def test_split_under_limit(self):
        record = {"items": [1, 2]}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_over_limit(self):
        record = {"meta": "preserved", "items": [1, 2, 3, 4, 5]}
        chunks = self.strategy.split(record, limit=2)

        assert len(chunks) == 3
        assert chunks[0] == {"meta": "preserved", "items": [1, 2]}
        assert chunks[1] == {"meta": "preserved", "items": [3, 4]}
        assert chunks[2] == {"meta": "preserved", "items": [5]}

    def test_merge(self):
        records = [
            {"meta": "preserved", "items": [1, 2]},
            {"meta": "preserved", "items": [3, 4]},
        ]
        merged = self.strategy.merge(records)
        assert merged == {"meta": "preserved", "items": [1, 2, 3, 4]}


class TestDictUpdateStrategy:
    def setup_method(self):
        self.strategy = DictUpdateStrategy(dict_field="data")

    def test_split_missing_or_invalid_field(self):
        record = {"other": "value"}
        assert self.strategy.split(record, limit=2) == [record]

        record_invalid = {"data": ["not", "a", "dict"]}
        assert self.strategy.split(record_invalid, limit=2) == [record_invalid]

    def test_split_under_limit(self):
        record = {"data": {"a": 1, "b": 2}}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_over_limit(self):
        record = {"meta": "info", "data": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}}
        chunks = self.strategy.split(record, limit=2)

        assert len(chunks) == 3
        assert chunks[0] == {"meta": "info", "data": {"a": 1, "b": 2}}
        assert chunks[2] == {"meta": "info", "data": {"e": 5}}

    def test_merge(self):
        records = [
            {"meta": "info", "data": {"a": 1, "b": 2}},
            {"meta": "info", "data": {"c": 3, "d": 4}},
        ]
        merged = self.strategy.merge(records)
        assert merged == {"meta": "info", "data": {"a": 1, "b": 2, "c": 3, "d": 4}}


class TestStringStrategy:
    def setup_method(self):
        self.strategy = StringStrategy(text_field="text")

    def test_split_missing_field(self):
        record = {"other": "value"}
        assert self.strategy.split(record, limit=2) == [record]

    def test_split_under_limit(self):
        record = {"text": "ab"}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_over_limit(self):
        record = {"prompt": "remove me", "meta": "tag", "text": "abcde"}
        chunks = self.strategy.split(record, limit=2)

        assert len(chunks) == 3
        assert chunks[0] == {"prompt": "remove me", "meta": "tag", "text": "ab"}
        assert chunks[1] == {"meta": "tag", "text": "cd"}
        assert "prompt" not in chunks[1]
        assert chunks[2] == {"meta": "tag", "text": "e"}

    def test_merge(self):
        records = [
            {"meta": "tag", "text": "ab"},
            {"meta": "tag", "text": "cd"},
        ]
        merged = self.strategy.merge(records)
        assert merged == {"meta": "tag", "text": "abcd"}


class TestDocumentExtractionStrategy:
    def setup_method(self):
        self.strategy = DocumentExtractionStrategy()

    def test_merge(self):
        records = [
            {
                "blocks": [{"page_number": 1}],
                "page_width": 800,
                "page_height": 600,
                "attributes": {"start_page": 1, "end_page": 1},
            },
            {
                "blocks": [{"page_number": 2}],
                "page_width": 800,
                "page_height": 600,
                "attributes": {"start_page": 2, "end_page": 2},
            },
        ]
        merged = self.strategy.merge(records)
        assert len(merged["blocks"]) == 2

        assert merged["page_width"] == 800
        assert merged["page_height"] == 600

        assert merged["attributes"]["end_page"] == 2

    def test_split_under_limit(self):
        record = {"blocks": [{"id": 1}]}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_over_limit_with_const_dims(self):
        record = {
            "blocks": [{"page_number": 1}, {"page_number": 2}, {"page_number": 3}],
            "page_width": 100,
            "page_height": 200,
            "attributes": {"start_page": 1, "end_page": 3},
        }
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 2
        assert len(chunks[0]["blocks"]) == 2
        assert chunks[0]["attributes"]["start_page"] == 1
        assert chunks[0]["attributes"]["end_page"] == 2
        assert chunks[0]["page_width"] == 100

        assert len(chunks[1]["blocks"]) == 1
        assert chunks[1]["attributes"]["start_page"] == 3
        assert chunks[1]["attributes"]["end_page"] == 3

    def test_split_over_limit_with_mapped_dims(self):
        record = {
            "blocks": [{"page_number": 1}, {"page_number": 2}],
            "page_width": [{"value": 100, "pages": [1, 2]}],
            "page_height": [{"value": 500, "pages": [9]}],
        }
        chunks = self.strategy.split(record, limit=1)
        assert len(chunks) == 2
        assert chunks[0]["page_width"] == [{"value": 100, "pages": [1]}]
        assert chunks[1]["page_width"] == [{"value": 100, "pages": [2]}]

        assert "page_height" not in chunks[0]
        assert "page_height" not in chunks[1]

    def test_split_no_page_numbers(self):
        record = {"blocks": [{"text": "A"}, {"text": "B"}]}
        chunks = self.strategy.split(record, limit=1)
        assert len(chunks) == 2
        assert "attributes" not in chunks[0]

    def test_merge_missing_dimensions(self):
        """Covers lines 137->138: 'if not vals:' branch."""
        records = [
            {"page_width": None, "blocks": [{"page_number": 1}]},
            {"blocks": [{"page_number": 2}]},
        ]
        merged = self.strategy.merge(records)

        assert "page_width" not in merged
        assert "page_height" not in merged

    def test_merge_complex_dimensions(self):
        """Covers lines 141->144: the 'else' branch for differing or list-based dimensions."""
        records = [
            {
                "blocks": [{"page_number": 1}],
                "page_width": 800,
                "page_height": 600,
            },
            {
                "blocks": [{"page_number": 2}],
                "page_width": 1000,
                "page_height": [{"value": 1200, "pages": [2]}],
            },
        ]
        merged = self.strategy.merge(records)

        assert merged["page_width"] == [
            {"value": 800, "pages": [1]},
            {"value": 1000, "pages": [2]},
        ]

        assert merged["page_height"] == [
            {"value": 600, "pages": [1]},
            {"value": 1200, "pages": [2]},
        ]

    def test_merge_complex_dimensions_empty_fallback(self):
        """Covers the inner 'else: unified.pop(dim_key, None)' if grouping fails due to missing page numbers."""
        records = [
            {
                "blocks": [{"text": "no page number here"}],
                "page_width": 800,
            },
            {
                "blocks": [{"text": "also no page number"}],
                "page_width": 1000,
            },
        ]
        merged = self.strategy.merge(records)

        assert "page_width" not in merged


class TestAudioTranscriptionStrategy:
    def setup_method(self):
        self.strategy = AudioTranscriptionStrategy()

    def test_merge(self):
        records = [{"text": "Hello", "segments": [{"id": 1}]}, {"text": "World", "segments": [{"id": 2}]}]
        merged = self.strategy.merge(records)
        assert merged["text"] == "Hello\nWorld"
        assert len(merged["segments"]) == 2

    @patch("dorsal.file.chunking.SPLIT_LIMIT_STRING", 5)
    def test_split_over_limit(self):
        record = {"text": "HelloWorld!", "segments": [1, 2, 3, 4]}
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 3
        assert chunks[0]["text"] == "Hello"
        assert chunks[0]["segments"] == [1, 2]

        assert chunks[1]["text"] == "World"
        assert chunks[1]["segments"] == [3, 4]

        assert chunks[2]["text"] == "!"
        assert chunks[2]["segments"] == []

    @patch("dorsal.file.chunking.SPLIT_LIMIT_STRING", 50)
    def test_split_segments_longer_than_text(self):
        record = {"text": "Hi", "segments": [1, 2, 3]}
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 2
        assert chunks[0]["text"] == "Hi"
        assert chunks[0]["segments"] == [1, 2]
        assert chunks[1]["text"] == ""
        assert chunks[1]["segments"] == [3]

    @patch("dorsal.file.chunking.SPLIT_LIMIT_STRING", 2)
    def test_split_missing_keys(self):

        record = {"other": "value", "text": "abc"}
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 2
        assert "segments" not in chunks[0]
        assert chunks[0]["text"] == "ab"
        assert chunks[1]["text"] == "c"

        record2 = {"other": "value", "segments": [1, 2, 3]}
        chunks2 = self.strategy.split(record2, limit=2)
        assert len(chunks2) == 2
        assert "text" not in chunks2[0]
        assert chunks2[0]["segments"] == [1, 2]
        assert chunks2[1]["segments"] == [3]

    def test_split_under_limit(self):
        """Hits the early exit branch when both text and segments are under their limits."""
        record = {"text": "Short text", "segments": [{"id": 1}, {"id": 2}]}

        chunks = self.strategy.split(record, limit=5)

        assert len(chunks) == 1
        assert chunks == [record]


class TestEmbeddingStrategy:
    def setup_method(self):
        self.strategy = EmbeddingStrategy()

    def test_merge_dense(self):
        records = [{"vector": [1.0, 2.0]}, {"vector": [3.0, 4.0]}]
        merged = self.strategy.merge(records)
        assert merged["vector"] == [1.0, 2.0, 3.0, 4.0]

    def test_merge_sparse(self):
        records = [{"vector": {"indices": [1], "values": [0.5]}}, {"vector": {"indices": [2], "values": [0.8]}}]
        merged = self.strategy.merge(records)
        assert merged["vector"]["indices"] == [1, 2]
        assert merged["vector"]["values"] == [0.5, 0.8]

    def test_merge_empty_vector(self):
        records = [{"vector": None}, {"vector": []}]
        merged = self.strategy.merge(records)
        assert not merged.get("vector")

    def test_split_missing_vector(self):
        record = {"other": "data"}
        assert self.strategy.split(record, limit=2) == [record]

    def test_split_dense(self):
        record = {"vector": [1, 2, 3, 4, 5]}
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 3
        assert chunks[0]["vector"] == [1, 2]
        assert chunks[2]["vector"] == [5]

    def test_split_dense_under_limit(self):
        record = {"vector": [1, 2]}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_sparse(self):
        record = {"vector": {"dimensions": 100, "indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}}
        chunks = self.strategy.split(record, limit=2)
        assert len(chunks) == 2
        assert chunks[0]["vector"]["indices"] == [1, 2]
        assert chunks[0]["vector"]["dimensions"] == 100
        assert chunks[1]["vector"]["values"] == [0.3]

    def test_split_sparse_under_limit(self):
        record = {"vector": {"indices": [1], "values": [0.1]}}
        assert self.strategy.split(record, limit=5) == [record]

    def test_split_unsupported_vector_type(self):
        record = {"vector": "string_vector"}
        assert self.strategy.split(record, limit=2) == [record]


class TestChunkingMainFunctions:
    def test_merge_chunked_records_empty_and_single(self):
        assert merge_chunked_records([], "open/classification") == {}

        single_record = {"labels": ["A"]}
        assert merge_chunked_records([single_record], "open/classification") == single_record

    def test_merge_chunked_records_with_valid_strategy(self):
        records = [{"labels": ["A"]}, {"labels": ["B"]}]
        merged = merge_chunked_records(records, "open/classification")
        assert merged == {"labels": ["A", "B"]}

    def test_merge_chunked_records_no_strategy(self, caplog):
        records = [{"data": "A"}, {"data": "B"}]
        with caplog.at_level(logging.WARNING):
            merged = merge_chunked_records(records, "unknown/schema")

        assert merged == {"data": "A"}
        assert "No merge strategy for schema 'unknown/schema'" in caplog.text

    @patch("dorsal.file.chunking.SPLIT_LIMIT_DEFAULT", 2)
    @patch("dorsal.file.chunking.SPLIT_LIMIT_STRING", 2)
    @patch("dorsal.file.chunking.SPLIT_LIMIT_GENERIC", 2)
    def test_chunk_record_with_various_schemas(self):

        list_record = {"labels": ["A", "B", "C"]}
        chunks = chunk_record(list_record, "open/classification")
        assert len(chunks) == 2
        assert chunks[0]["labels"] == ["A", "B"]

        dict_record = {"data": {"k1": "v1", "k2": "v2", "k3": "v3"}}
        chunks = chunk_record(dict_record, "open/generic")
        assert len(chunks) == 2
        assert len(chunks[0]["data"]) == 2

        str_record = {"response_data": "12345"}
        chunks = chunk_record(str_record, "open/llm-output")
        assert len(chunks) == 3
        assert chunks[0]["response_data"] == "12"

    def test_chunk_record_no_strategy(self):
        record = {"key": "value"}
        chunks = chunk_record(record, "unknown/schema")
        assert chunks == [record]
