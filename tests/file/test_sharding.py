# Copyright 2025-2026 Dorsal Hub LTD
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
    build_annotation_or_annotationgroup,
    check_record_size,
    process_record_for_sharding,
    reassemble_record,
)
from dorsal.file.validators.file_record import GenericFileAnnotation
from dorsal.common.exceptions import AnnotationExecutionError


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
        objects = large_payload_generator(count=1500, item_size=1000)
        record = {"unit": "px", "objects": objects}

        chunks = detection_strategy.split(record)

        assert len(chunks) > 1

        for i, chunk in enumerate(chunks):
            size = check_record_size(chunk)
            assert size <= ANNOTATION_MAX_SIZE_BYTES, f"Chunk {i} size {size} exceeds limit {ANNOTATION_MAX_SIZE_BYTES}"
            assert "objects" in chunk
            assert len(chunk["objects"]) > 0

        total_items = sum(len(c["objects"]) for c in chunks)
        assert total_items == 1500

    def test_split_template_switching(self):
        """Verify that 'fields_to_drop' are removed from subsequent chunks."""
        strategy = ListBasedStrategy(list_field="segments", fields_to_drop_in_successors=["text"])

        items = [{"s": i, "d": "x" * 500000} for i in range(3)]

        record = {"text": "Full transcription text header", "segments": items, "meta": "keep_me"}

        chunks = strategy.split(record)

        assert len(chunks) >= 2

        assert "text" in chunks[0]
        assert chunks[0]["text"] == "Full transcription text header"
        assert chunks[0]["meta"] == "keep_me"

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
        record = {"other_field": 123}
        chunks = detection_strategy.split(record)
        assert len(chunks) == 1
        assert chunks[0] == record


class TestStringShardingStrategySplit:
    def test_split_simple_string(self):
        """Test splitting a simple ASCII string."""
        strategy = StringShardingStrategy(text_field="response_data")

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            long_string = "a" * 12000
            record = {"model": "gpt-4", "response_data": long_string}

            chunks = strategy.split(record)

            assert len(chunks) > 1
            full_text = "".join(c["response_data"] for c in chunks)
            assert full_text == long_string

            for chunk in chunks:
                assert check_record_size(chunk) <= 10000

    def test_split_utf8_boundaries(self):
        """Verify that we do not slice in the middle of a multi-byte character."""
        strategy = StringShardingStrategy(text_field="text")

        emojis = "🐻" * 3000

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            record = {"text": emojis}
            chunks = strategy.split(record)

            assert len(chunks) > 1

            recombined = "".join(c["text"] for c in chunks)
            assert recombined == emojis

            for chunk in chunks:
                json_str = json.dumps(chunk)
                assert "\ufffd" not in json_str

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

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
            tricky_text = "\n" * 5500

            record = {"text": tricky_text}

            chunks = strategy.split(record)

            for chunk in chunks:
                assert check_record_size(chunk) <= 10000

            recombined = "".join(c["text"] for c in chunks)
            assert recombined == tricky_text


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

        assert result[0]["target"] == "stock_price"

    def test_process_llm_sharding(self):
        """Test open/llm-output uses StringShardingStrategy correctly."""

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

        with patch("dorsal.file.sharding.ANNOTATION_MAX_SIZE_BYTES", 10000):
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


class TestBuildAnnotationOrGroup:
    """Tests for the build_annotation_or_annotationgroup orchestration function."""

    @pytest.fixture
    def pydantic_error(self):
        """Generates a genuine Pydantic ValidationError to use in mock side_effects."""
        from pydantic import BaseModel, ValidationError

        class DummyErrorMaker(BaseModel):
            val: int

        try:
            DummyErrorMaker(val="not_an_int")
        except ValidationError as e:
            return e

    def test_atomic_happy_path(self, detection_schema_id):
        """Tests successful creation of a single Annotation object."""
        record = {"objects": [{"id": 1}]}
        source = {"type": "Model", "id": "test_mock"}

        result = build_annotation_or_annotationgroup(
            schema_id=detection_schema_id, record_data=record, source=source, schema_version="1.0", private=False
        )

        assert result.__class__.__name__ == "Annotation"
        assert result.schema_id == detection_schema_id
        assert result.schema_version == "1.0"
        assert result.private is False

    def test_sharded_happy_path(self, detection_schema_id, large_payload_generator):
        """Tests successful creation of an AnnotationGroup from a massive payload."""
        record = {"objects": large_payload_generator(2000)}
        source = {"type": "Model", "id": "test_mock", "execution_id": "23456781-1234-5678-1234-567812345678"}

        result = build_annotation_or_annotationgroup(
            schema_id=detection_schema_id, record_data=record, source=source, schema_version="2.0", private=True
        )

        assert result.__class__.__name__ == "AnnotationGroup"
        assert len(result.annotations) > 1
        assert result.annotations[0].group.total == len(result.annotations)
        assert result.annotations[0].private is True
        assert result.annotations[0].schema_version == "2.0"

    def test_sharding_failure_unsupported_schema(self, large_payload_generator):
        """Tests that a large payload with no sharding strategy raises the correct error."""
        record = {"massive_field": large_payload_generator(2000)}
        source = {"type": "Model", "id": "test_mock"}

        with pytest.raises(AnnotationExecutionError) as exc:
            build_annotation_or_annotationgroup(
                schema_id="file/base",
                record_data=record,
                source=source,
            )

        assert "Annotation processing failed" in str(exc.value)
        assert "does not support sharding" in str(exc.value.__cause__)

    def test_wrapper_validation_failure_atomic(self):
        """Tests atomic wrapper instantiation failure using an invalid source."""
        record = {"objects": [{"id": 1}]}

        bad_source = {"missing_required_fields": "yep"}

        with pytest.raises(AnnotationExecutionError) as exc:
            build_annotation_or_annotationgroup(
                schema_id="file/pdf",
                record_data=record,
                source=bad_source,
            )

        assert "Failed to create annotation wrapper for 'file/pdf'" in str(exc.value)

    @patch("dorsal.file.validators.file_record.GenericFileAnnotation")
    def test_generic_validation_failure_atomic(self, mock_generic, detection_schema_id, pydantic_error):
        """Tests failure at the GenericFileAnnotation baseline validation (atomic path)."""

        mock_generic.side_effect = pydantic_error

        record = {"objects": [{"id": 1}]}
        source = {"type": "Model", "id": "test_mock"}

        with pytest.raises(AnnotationExecutionError) as exc:
            build_annotation_or_annotationgroup(
                schema_id=detection_schema_id,
                record_data=record,
                source=source,
            )

        assert "incompatible with the base annotation structure" in str(exc.value)
        assert "Chunk" not in str(exc.value)

    def test_wrapper_validation_failure_sharded(self, detection_schema_id, large_payload_generator):
        """Tests wrapper instantiation failure during the chunk loop (sharded path) natively."""
        record = {"objects": large_payload_generator(2000)}
        bad_source = {"missing_required_fields": "yep"}

        with pytest.raises(AnnotationExecutionError) as exc:
            build_annotation_or_annotationgroup(
                schema_id=detection_schema_id,
                record_data=record,
                source=bad_source,
            )

        assert "Failed to create annotation wrapper for 'open/object-detection'" in str(exc.value)

    @patch("dorsal.file.validators.file_record.GenericFileAnnotation")
    def test_generic_validation_failure_sharded(
        self, mock_generic, detection_schema_id, large_payload_generator, pydantic_error
    ):
        """Tests failure at the GenericFileAnnotation baseline validation during the chunk loop."""
        mock_generic.side_effect = pydantic_error

        record = {"objects": large_payload_generator(2000)}
        source = {"type": "Model", "id": "test_mock"}

        with pytest.raises(AnnotationExecutionError) as exc:
            build_annotation_or_annotationgroup(
                schema_id=detection_schema_id,
                record_data=record,
                source=source,
            )

        assert "incompatible with the base annotation structure" in str(exc.value)
        assert "Chunk 0/" in str(exc.value)
