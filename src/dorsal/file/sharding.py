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

import logging
import copy
import json
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

from dorsal.common.constants import ANNOTATION_MAX_SIZE_BYTES
from dorsal.common.exceptions import PydanticValidationError
from dorsal.file.utils.size import human_filesize, check_record_size


if TYPE_CHECKING:
    from dorsal.file.validators.file_record import AnnotationGroup, ShardedAnnotation

logger = logging.getLogger(__name__)


@runtime_checkable
class ShardingStrategy(Protocol):
    fields_to_drop: list[str]

    def split(self, record: dict[str, Any]) -> list[dict[str, Any]]: ...


class ListBasedStrategy:
    """
    Splits a record by distributing a high-cardinality list field across multiple chunks.
    Optimized for O(N) performance using running byte counts.
    """

    def __init__(self, list_field: str, fields_to_drop_in_successors: list[str] | None = None):
        self.list_field = list_field
        self.fields_to_drop = fields_to_drop_in_successors or []

    def split(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        items = record.get(self.list_field)

        if not isinstance(items, list) or not items:
            return [record]

        template_0 = copy.deepcopy(record)
        template_0[self.list_field] = []

        template_n = copy.deepcopy(template_0)
        for field in self.fields_to_drop:
            if field in template_n:
                del template_n[field]

        size_template_0 = check_record_size(template_0)
        size_template_n = check_record_size(template_n)

        if size_template_0 > ANNOTATION_MAX_SIZE_BYTES:
            raise ValueError(f"Metadata header is too large ({size_template_0} bytes) to allow sharding.")

        chunks: list[dict[str, Any]] = []

        current_items: list[Any] = []
        current_chunk_size = size_template_0
        is_first_chunk = True

        for item in items:
            item_size = check_record_size(item)
            addition_cost = item_size if not current_items else (item_size + 1)

            if (current_chunk_size + addition_cost) > ANNOTATION_MAX_SIZE_BYTES:
                if not current_items:
                    raise ValueError(
                        f"A single item in '{self.list_field}' exceeds the {human_filesize(ANNOTATION_MAX_SIZE_BYTES)} limit. Cannot shard."
                    )

                base = template_0 if is_first_chunk else template_n
                chunk = base.copy()

                chunk[self.list_field] = current_items
                chunks.append(chunk)

                is_first_chunk = False
                current_items = []
                current_chunk_size = size_template_n
                addition_cost = item_size

                if (current_chunk_size + addition_cost) > ANNOTATION_MAX_SIZE_BYTES:
                    raise ValueError(
                        f"A single item in '{self.list_field}' exceeds the {human_filesize(ANNOTATION_MAX_SIZE_BYTES)} limit. Cannot shard."
                    )

            current_items.append(item)
            current_chunk_size += addition_cost

        if current_items:
            base = template_0 if is_first_chunk else template_n
            chunk = base.copy()
            chunk[self.list_field] = current_items
            chunks.append(chunk)

        return chunks


class StringShardingStrategy:
    """
    Splits a record by chunking a massive string field (e.g. LLM response text).
    Handles UTF-8 boundaries and JSON escaping overhead.
    """

    def __init__(self, text_field: str, fields_to_drop_in_successors: list[str] | None = None):
        self.text_field = text_field
        self.fields_to_drop = fields_to_drop_in_successors or []

    def split(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        text = record.get(self.text_field, "")
        if not text or not isinstance(text, str):
            return [record]

        base_template = copy.deepcopy(record)
        base_template[self.text_field] = ""

        skeleton_size = check_record_size(base_template)

        safety_buffer = 4096

        capacity = ANNOTATION_MAX_SIZE_BYTES - skeleton_size - safety_buffer

        if capacity < 1024:
            raise ValueError(
                f"Metadata header is too large ({skeleton_size} bytes). "
                "Not enough room left to shard text content safely."
            )

        chunks: list[dict[str, Any]] = []

        text_bytes = text.encode("utf-8")
        total_bytes = len(text_bytes)
        offset = 0

        while offset < total_bytes:
            end = min(offset + capacity, total_bytes)
            while end > offset and end < total_bytes and (text_bytes[end] & 0xC0) == 0x80:
                end -= 1

            if end == offset:
                raise ValueError("Unable to split text: single character exceeds chunk capacity.")

            chunk_str = text_bytes[offset:end].decode("utf-8")
            chunk_record = copy.deepcopy(base_template)
            chunk_record[self.text_field] = chunk_str

            if offset > 0:
                for f in self.fields_to_drop:
                    chunk_record.pop(f, None)

            if check_record_size(chunk_record) > ANNOTATION_MAX_SIZE_BYTES:
                logger.debug("Chunk exceeded limit due to escaping overhead. Shrinking and retrying.")
                capacity = int(capacity * 0.9)
                if capacity < 100:
                    raise ValueError("Cannot shrink chunk further; text contains extremely high-overhead characters.")
                continue

            chunks.append(chunk_record)
            offset = end

        return chunks


SHARDING_REGISTRY: dict[str, ShardingStrategy] = {
    "open/document-extraction": ListBasedStrategy(list_field="blocks"),
    "open/object-detection": ListBasedStrategy(list_field="objects"),
    "open/entity-extraction": ListBasedStrategy(list_field="entities"),
    "open/classification": ListBasedStrategy(list_field="labels"),
    "open/audio-transcription": ListBasedStrategy(list_field="segments", fields_to_drop_in_successors=["text"]),
    "open/regression": ListBasedStrategy(list_field="points"),
    "open/llm-output": StringShardingStrategy(
        text_field="response_data", fields_to_drop_in_successors=["prompt", "generation_params"]
    ),
    # Unsupported
    # "open/geolocation" - no appropriate sharding strategy yet
    # "open/generic" - never breaches 1MiB
    # "open/embedding" - never breaches 1MiB
}


def process_record_for_sharding(schema_id: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Checks if a record exceeds the global size limit and shards it if a strategy exists.
    """
    size = check_record_size(record)

    if size <= ANNOTATION_MAX_SIZE_BYTES:
        return [record]

    strategy = SHARDING_REGISTRY.get(schema_id)

    if not strategy:
        raise ValueError(
            f"Record for '{schema_id}' exceeds limit ({human_filesize(size)}) and this schema "
            "does not support sharding. Please reduce the record size."
        )

    logger.info(
        "Record for '%s' exceeds limit (%s). Attempting sharding strategy: %s...",
        schema_id,
        human_filesize(size),
        strategy.__class__.__name__,
    )

    chunks = strategy.split(record)

    logger.info("Successfully sharded record into %d chunks.", len(chunks))
    return chunks


def reassemble_record(group: AnnotationGroup) -> tuple[str, dict[str, Any]]:
    """
    Reassembles a sharded AnnotationGroup into a single atomic record.
    Returns: (schema_id, record_dict)
    """
    from dorsal.file.validators.file_record import ShardedAnnotation

    try:
        chunks = [ShardedAnnotation.model_validate(ann, from_attributes=True) for ann in group.annotations]
    except PydanticValidationError as e:
        raise ValueError(f"Sharding integrity error: Chunk missing required fields. Details: {e}") from e

    sorted_chunks = sorted(chunks, key=lambda x: x.group.index)
    head = sorted_chunks[0]
    total = head.group.total

    if len(sorted_chunks) != total:
        raise ValueError(f"Incomplete group: Expected {total} chunks, got {len(sorted_chunks)}")

    head_record = head.record.model_dump()
    strategy: ShardingStrategy | None = None
    matched_schema_id: str | None = None

    for schema_id, strat in SHARDING_REGISTRY.items():
        if isinstance(strat, ListBasedStrategy):
            if strat.list_field in head_record and isinstance(head_record[strat.list_field], list):
                strategy = strat
                matched_schema_id = schema_id
                break
        elif isinstance(strat, StringShardingStrategy):
            if strat.text_field in head_record and isinstance(head_record[strat.text_field], str):
                strategy = strat
                matched_schema_id = schema_id
                break

    if not strategy or matched_schema_id is None:
        raise ValueError("Could not detect sharding strategy from record structure.")

    reassembled_record = copy.deepcopy(head_record)

    if isinstance(strategy, ListBasedStrategy):
        master_list = reassembled_record[strategy.list_field]
        for chunk in sorted_chunks[1:]:
            chunk_data = chunk.record.model_dump()
            items = chunk_data.get(strategy.list_field, [])
            master_list.extend(items)

    elif isinstance(strategy, StringShardingStrategy):
        text_parts = [reassembled_record[strategy.text_field]]
        for chunk in sorted_chunks[1:]:
            chunk_data = chunk.record.model_dump()
            part = chunk_data.get(strategy.text_field, "")
            text_parts.append(part)

        reassembled_record[strategy.text_field] = "".join(text_parts)

    return matched_schema_id, reassembled_record
