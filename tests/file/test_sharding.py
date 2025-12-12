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

import copy
import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dorsal.file import sharding
from dorsal.file.sharding import (
    ListBasedStrategy,
    StringShardingStrategy,
    ANNOTATION_MAX_SIZE_BYTES,
    check_record_size,
    process_record_for_sharding,
    reassemble_record,
)
from dorsal.file.validators.file_record import GenericFileAnnotation


class MockAnnotation:
    """Mocks Annotation inside a group."""

    def __init__(self, data: dict, index: int, total: int):
        self.record = GenericFileAnnotation(**data)

        self.group = MagicMock()
        self.group.index = index
        self.group.total = total

        self.source = {"type": "Model", "id": "test_mock"}
        self.group.id = "00000000-0000-0000-0000-000000000000"
        self.private = True


class MockAnnotationGroup:
    """Mocks the AnnotationGroup container."""

    def __init__(self, annotations: list[MockAnnotation]):
        self.annotations = annotations


@pytest.fixture
def large_payload_generator():
    """Generates a list of items that definitely exceeds 1MiB."""

    def _gen(count: int = 2000, item_size: int = 1000) -> list[dict]:
        # 2000 items * 1000 bytes = ~2MB
        return [{"id": i, "val": "x" * item_size} for i in range(count)]

    return _gen


@pytest.fixture
def detection_schema_id():
    return "open/object-detection"


@pytest.fixture
def detection_strategy():
    return sharding.SHARDING_REGISTRY["open/object-detection"]


def test_check_record_size():
    """Verify byte counting matches JSON serialization assumptions."""
    data = {"a": 1, "b": "test"}
    # {"a":1,"b":"test"} = 16 bytes
    expected_size = len(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    assert check_record_size(data) == expected_size


class TestListBasedStrategySplit:
    def test_split_no_op_small_record(self, detection_strategy):
        """If record is small, split should return it as a single chunk."""
        record = {"unit": "px", "objects": [{"id": 1}]}
        chunks = detection_strategy.split(record)
        assert len(chunks) == 1
        assert chunks[0] == record

    def test_split_large_record(self, detection_strategy, large_payload_generator):
        """Verify that a large record is actually split into multiple valid chunks."""
        objects = large_payload_generator(count=1500, item_size=1000)  # ~1.5MB
        record = {"unit": "px", "objects": objects}

        chunks = detection_strategy.split(record)

        assert len(chunks) > 1

        # Verify strict size limits
        for i, chunk in enumerate(chunks):
            size = check_record_size(chunk)
            assert size <= ANNOTATION_MAX_SIZE_BYTES, f"Chunk {i} size {size} exceeds limit {ANNOTATION_MAX_SIZE_BYTES}"
            assert "objects" in chunk
            assert len(chunk["objects"]) > 0

        # Verify data integrity (total items matches)
        total_items = sum(len(c["objects"]) for c in chunks)
        assert total_items == 1500

    def test_split_template_switching(self):
        """Verify that 'fields_to_drop' are removed from subsequent chunks."""
        strategy = ListBasedStrategy(list_field="segments", fields_to_drop_in_successors=["text"])

        items = [{"s": i, "d": "x" * 500000} for i in range(3)]

        record = {"text": "Full transcription text header", "segments": items, "meta": "keep_me"}

        chunks = strategy.split(record)

        assert len(chunks) >= 2

        # Chunk 0 should have the text
        assert "text" in chunks[0]
        assert chunks[0]["text"] == "Full transcription text header"
        assert chunks[0]["meta"] == "keep_me"

        # Chunk 1+ should NOT have the text
        assert "text" not in chunks[1]
        assert chunks[1]["meta"] == "keep_me"

    def test_split_single_item_too_large(self, detection_strategy):
        """Error if a single item in the list is larger than 1MB."""
        huge_item = {"id": 1, "data": "x" * (ANNOTATION_MAX_SIZE_BYTES + 100)}
        record = {"objects": [huge_item]}

        with pytest.raises(ValueError) as exc:
            detection_strategy.split(record)
        assert "exceeds the 1 MiB limit" in str(exc.value)

    def test_split_header_too_large(self, detection_strategy):
        """Error if the static fields (header) consume all available space."""
        record = {
            "objects": [{"id": 1}],
            "massive_metadata": "x" * (ANNOTATION_MAX_SIZE_BYTES + 100),
        }
        with pytest.raises(ValueError) as exc:
            detection_strategy.split(record)
        assert "Metadata header is too large" in str(exc.value)

    def test_split_missing_list_field(self, detection_strategy):
        """Should handle records missing the target list field gracefully (return as-is)."""
        record = {"other_field": 123}  # Missing 'objects'
        chunks = detection_strategy.split(record)
        assert len(chunks) == 1
        assert chunks[0] == record


class TestStringShardingStrategySplit:
    # NOTE: We use 10000 bytes as the patch limit.
    # Logic: 4096 (Safety Buffer) + 1024 (Min Capacity) = 5120 bytes required minimum.
    # 10000 gives us ~4800 bytes of capacity per chunk.

    def test_split_simple_string(self):
        """Test splitting a simple ASCII string."""
        strategy = StringShardingStrategy(text_field="response_data")

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            # Create string ~12000 chars (larger than 10k limit)
            long_string = "a" * 12000
            record = {"model": "gpt-4", "response_data": long_string}

            chunks = strategy.split(record)

            assert len(chunks) > 1
            full_text = "".join(c["response_data"] for c in chunks)
            assert full_text == long_string

            # Verify each chunk respects the limit
            for chunk in chunks:
                assert check_record_size(chunk) <= 10000

    def test_split_utf8_boundaries(self):
        """Verify that we do not slice in the middle of a multi-byte character."""
        strategy = StringShardingStrategy(text_field="text")

        # 4-byte character: 🐻
        # Create a string of emojis > 10k bytes
        # 3000 * 4 = 12,000 bytes
        emojis = "🐻" * 3000

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            record = {"text": emojis}
            chunks = strategy.split(record)

            assert len(chunks) > 1

            recombined = "".join(c["text"] for c in chunks)
            assert recombined == emojis

            # Verify valid JSON (ensures no corrupted bytes)
            for chunk in chunks:
                json_str = json.dumps(chunk)
                assert "\ufffd" not in json_str  # No replacement chars

    def test_split_context_dropping(self):
        """Verify that 'fields_to_drop' are removed from subsequent chunks."""
        strategy = StringShardingStrategy(text_field="data", fields_to_drop_in_successors=["prompt"])

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            record = {"prompt": "Keep me in chunk 0 only", "data": "x" * 12000}

            chunks = strategy.split(record)

            assert len(chunks) > 1
            assert "prompt" in chunks[0]
            assert "prompt" not in chunks[1]
            assert chunks[0]["prompt"] == "Keep me in chunk 0 only"

    def test_split_json_overhead_check(self):
        """
        Verify that the strategy handles cases where JSON escaping
        makes the payload significantly larger than the raw string length.
        """
        strategy = StringShardingStrategy(text_field="text")

        # Newline characters '\n' (1 byte) become '\\n' (2 bytes) in JSON.

        # Limit: 10000
        # Capacity: 10000 - 4096 ≈ 5900.
        # We need a payload P where P < 5900 but 2*P > 10000.
        # 5500 fits this criteria.

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            # 5500 newlines = 5500 raw bytes (fits in chunk capacity)
            # In JSON this becomes 11000 bytes + overhead -> Exceeds 10000 limit.
            tricky_text = "\n" * 5500

            record = {"text": tricky_text}

            # This forces the loop to detect the overflow and retry with a smaller window.
            chunks = strategy.split(record)

            for chunk in chunks:
                assert check_record_size(chunk) <= 10000

            recombined = "".join(c["text"] for c in chunks)
            assert recombined == tricky_text


# --- Processing Logic Tests ---


class TestProcessRecordForSharding:
    def test_process_atomic_record(self, detection_schema_id):
        """Small records should bypass splitting logic quickly."""
        record = {"objects": [{"id": 1}]}
        result = process_record_for_sharding(detection_schema_id, record)
        assert len(result) == 1
        assert result[0] == record

    def test_process_regression_sharding(self, large_payload_generator):
        """Test open/regression uses ListBasedStrategy correctly."""
        record = {"target": "stock_price", "points": large_payload_generator(2000)}
        result = process_record_for_sharding("open/regression", record)
        assert len(result) > 1
        assert "points" in result[0]
        # Verify header preservation
        assert result[0]["target"] == "stock_price"

    def test_process_llm_sharding(self):
        """Test open/llm-output uses StringShardingStrategy correctly."""
        # Force a split with a small limit patch
        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            record = {"model": "gpt-4", "response_data": "x" * 12000}
            result = process_record_for_sharding("open/llm-output", record)
            assert len(result) > 1
            assert "response_data" in result[0]

    def test_process_unsupported_schema(self, large_payload_generator):
        """Large records with no registered strategy should raise ValueError."""
        record = {"all_hashes": large_payload_generator(2000)}

        with pytest.raises(ValueError) as exc:
            process_record_for_sharding("file/base", record)
        assert "does not support sharding" in str(exc.value)


# --- Reassembly Tests ---


class TestReassembly:
    def test_reassemble_list_strategy(self, detection_strategy, large_payload_generator):
        """Verify standard list reassembly (Object Detection)."""
        original_objects = large_payload_generator(1500)
        original_record = {"unit": "px", "objects": original_objects, "meta": "header"}

        chunks_data = detection_strategy.split(original_record)

        mock_anns = [MockAnnotation(data=c, index=i, total=len(chunks_data)) for i, c in enumerate(chunks_data)]
        group = MockAnnotationGroup(annotations=list(reversed(mock_anns)))

        schema_id, result_record = reassemble_record(group)

        assert schema_id == "open/object-detection"
        assert result_record["meta"] == "header"
        assert len(result_record["objects"]) == 1500
        assert result_record["objects"][0] == original_objects[0]

    def test_reassemble_string_strategy(self):
        """Verify string concatenation reassembly (LLM Output)."""
        strategy = sharding.SHARDING_REGISTRY["open/llm-output"]

        # Patch limit for splitting
        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            # Create a string larger than 10k
            original_text = "start-" + ("middle-" * 2000) + "-end"
            original_record = {"model": "test-v1", "prompt": "prompt-header", "response_data": original_text}

            chunks = strategy.split(original_record)
            assert len(chunks) > 1

            mock_anns = [MockAnnotation(c, i, len(chunks)) for i, c in enumerate(chunks)]
            group = MockAnnotationGroup(mock_anns)

            schema_id, result = reassemble_record(group)

            assert schema_id == "open/llm-output"
            assert result["response_data"] == original_text
            assert result["model"] == "test-v1"
            assert result["prompt"] == "prompt-header"

    def test_reassemble_integrity_error(self):
        """Missing chunks should raise ValueError."""
        anns = [MockAnnotation({"objects": []}, index=0, total=3), MockAnnotation({"objects": []}, index=1, total=3)]
        group = MockAnnotationGroup(anns)

        with pytest.raises(ValueError) as exc:
            reassemble_record(group)
        assert "Incomplete group" in str(exc.value)

    def test_reassemble_unknown_strategy(self):
        """If the record structure doesn't match any registry entry, fail."""
        anns = [
            MockAnnotation({"weird_field": []}, index=0, total=2),
            MockAnnotation({"weird_field": []}, index=1, total=2),
        ]
        group = MockAnnotationGroup(anns)

        with pytest.raises(ValueError) as exc:
            reassemble_record(group)
        assert "Could not detect sharding strategy" in str(exc.value)
