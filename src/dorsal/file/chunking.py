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

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Follows open-validation-schemas
SPLIT_LIMIT_DEFAULT = 100_000  # Max items for arrays (blocks, segments, objects, etc.)
SPLIT_LIMIT_STRING = 262_144  # Max length for "long" strings (llm prompts, transcription text)
SPLIT_LIMIT_GENERIC = 128  # Max properties for the 'data' dictionary in open/generic


@runtime_checkable
class MergeStrategy(Protocol):
    """Protocol for reassembling multiple semantic chunks back into a single record."""

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]: ...


@runtime_checkable
class SplitStrategy(Protocol):
    """Protocol for safely chunking a bloated record to enforce schema limits."""

    def split(self, record: dict[str, Any], limit: int) -> list[dict[str, Any]]: ...


class GenericListStrategy:
    """Handles arrays like 'objects', 'entities', 'labels', and 'points'."""

    def __init__(self, list_field: str):
        self.list_field = list_field

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        unified[self.list_field] = list(unified.get(self.list_field, []))
        for chunk in records[1:]:
            unified[self.list_field].extend(chunk.get(self.list_field, []))
        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_DEFAULT) -> list[dict[str, Any]]:
        items = record.get(self.list_field, [])
        if len(items) <= limit:
            return [record]

        chunks = []
        for i in range(0, len(items), limit):
            chunk = record.copy()
            chunk[self.list_field] = items[i : i + limit]
            chunks.append(chunk)
        return chunks


class StringStrategy:
    """Handles "long" strings like 'response_data' in LLM outputs."""

    def __init__(self, text_field: str):
        self.text_field = text_field

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        unified[self.text_field] = str(unified.get(self.text_field, ""))
        for chunk in records[1:]:
            if self.text_field in chunk:
                unified[self.text_field] += str(chunk.get(self.text_field, ""))
        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_STRING) -> list[dict[str, Any]]:
        text = str(record.get(self.text_field, ""))
        if len(text) <= limit:
            return [record]

        chunks = []
        for i in range(0, len(text), limit):
            chunk = record.copy()
            chunk[self.text_field] = text[i : i + limit]

            if i > 0 and "prompt" in chunk:
                del chunk["prompt"]
            chunks.append(chunk)
        return chunks


class DictUpdateStrategy:
    """Handles Key-Value maps like 'data' in the generic schema to respect maxProperties."""

    def __init__(self, dict_field: str):
        self.dict_field = dict_field

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        unified[self.dict_field] = dict(unified.get(self.dict_field, {}))
        for chunk in records[1:]:
            if self.dict_field in chunk and isinstance(chunk[self.dict_field], dict):
                unified[self.dict_field].update(chunk[self.dict_field])
        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_GENERIC) -> list[dict[str, Any]]:
        data = record.get(self.dict_field, {})
        if not isinstance(data, dict) or len(data) <= limit:
            return [record]

        items = list(data.items())
        chunks = []
        for i in range(0, len(items), limit):
            chunk = record.copy()
            chunk[self.dict_field] = dict(items[i : i + limit])
            chunks.append(chunk)
        return chunks


class DocumentExtractionStrategy:
    """Handles open/document-extraction."""

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        unified["blocks"] = list(unified.get("blocks", []))

        for chunk in records[1:]:
            unified["blocks"].extend(chunk.get("blocks", []))

        for dim_key in ["page_width", "page_height"]:
            vals = [r.get(dim_key) for r in records if r.get(dim_key) is not None]

            if not vals:
                unified.pop(dim_key, None)
                continue

            if all(isinstance(v, (int, float)) for v in vals) and len(set(vals)) == 1:
                unified[dim_key] = vals[0]
            else:
                complex_dims = []
                for r in records:
                    val = r.get(dim_key)
                    if isinstance(val, (int, float)):
                        pages = {b.get("page_number") for b in r.get("blocks", []) if b.get("page_number") is not None}
                        if pages:
                            complex_dims.append({"value": val, "pages": list(pages)})
                    elif isinstance(val, list):
                        complex_dims.extend(val)

                grouped: dict[int | float, set[int]] = {}
                for cd in complex_dims:
                    cd_val = cd.get("value")
                    cd_pages = cd.get("pages")

                    if isinstance(cd_val, (int, float)) and isinstance(cd_pages, list):
                        grouped.setdefault(cd_val, set()).update(cd_pages)

                if grouped:
                    unified[dim_key] = [{"value": k, "pages": sorted(list(v))} for k, v in grouped.items()]
                else:
                    unified.pop(dim_key, None)

        if "attributes" in unified and "attributes" in records[-1]:
            unified["attributes"] = unified["attributes"].copy()
            unified["attributes"]["end_page"] = records[-1]["attributes"].get(
                "end_page", unified["attributes"].get("end_page")
            )

        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_DEFAULT) -> list[dict[str, Any]]:
        all_blocks = record.get("blocks", [])
        if len(all_blocks) <= limit:
            return [record]

        def _get_dim_info(key):
            val = record.get(key)
            if isinstance(val, (int, float)):
                return val, None
            if isinstance(val, list):
                return None, {item["value"]: item["pages"] for item in val if "value" in item and "pages" in item}
            return None, None

        w_const, w_map = _get_dim_info("page_width")
        h_const, h_map = _get_dim_info("page_height")

        chunks = []
        for i in range(0, len(all_blocks), limit):
            chunk_blocks = all_blocks[i : i + limit]
            pages_in_chunk = {b.get("page_number") for b in chunk_blocks if b.get("page_number") is not None}

            chunk_record = record.copy()
            chunk_record["blocks"] = chunk_blocks

            if pages_in_chunk:
                chunk_record["attributes"] = record.get("attributes", {}).copy()
                chunk_record["attributes"]["start_page"] = min(pages_in_chunk)
                chunk_record["attributes"]["end_page"] = max(pages_in_chunk)

                for key, const, mapping in [("page_width", w_const, w_map), ("page_height", h_const, h_map)]:
                    if const:
                        chunk_record[key] = const
                    elif mapping:
                        filtered = [
                            {"value": v, "pages": [p for p in p_list if p in pages_in_chunk]}
                            for v, p_list in mapping.items()
                        ]
                        filtered = [item for item in filtered if item["pages"]]
                        if filtered:
                            chunk_record[key] = filtered
                        else:
                            chunk_record.pop(key, None)

            chunks.append(chunk_record)
        return chunks


class AudioTranscriptionStrategy:
    """Handles open/audio-transcription."""

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        unified["text"] = unified.get("text", "")
        unified["segments"] = list(unified.get("segments", []))

        for chunk in records[1:]:
            if "text" in chunk:
                unified["text"] += "\n" + str(chunk.get("text", ""))
            if "segments" in chunk:
                unified["segments"].extend(chunk.get("segments", []))
        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_DEFAULT) -> list[dict[str, Any]]:
        segments = record.get("segments", [])
        text = str(record.get("text", ""))

        if len(segments) <= limit and len(text) <= SPLIT_LIMIT_STRING:
            return [record]

        seg_chunks = [segments[i : i + limit] for i in range(0, max(1, len(segments)), limit)]
        text_chunks = [text[i : i + SPLIT_LIMIT_STRING] for i in range(0, max(1, len(text)), SPLIT_LIMIT_STRING)]

        chunks = []
        num_chunks = max(len(seg_chunks), len(text_chunks))

        for i in range(num_chunks):
            chunk = record.copy()
            if i < len(seg_chunks) and seg_chunks[i]:
                chunk["segments"] = seg_chunks[i]
            elif "segments" in chunk:
                chunk["segments"] = []

            if i < len(text_chunks) and text_chunks[i]:
                chunk["text"] = text_chunks[i]
            elif "text" in chunk:
                chunk["text"] = ""

            chunks.append(chunk)
        return chunks


class EmbeddingStrategy:
    """Handles open/embedding."""

    def merge(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        unified = records[0].copy()
        if not unified.get("vector"):
            return unified

        if isinstance(unified["vector"], list):
            unified["vector"] = list(unified["vector"])
            for chunk in records[1:]:
                if isinstance(chunk.get("vector"), list):
                    unified["vector"].extend(chunk["vector"])
        else:
            unified["vector"] = dict(unified["vector"])
            unified["vector"]["indices"] = list(unified["vector"].get("indices", []))
            unified["vector"]["values"] = list(unified["vector"].get("values", []))
            for chunk in records[1:]:
                vec = chunk.get("vector", {})
                if isinstance(vec, dict):
                    unified["vector"]["indices"].extend(vec.get("indices", []))
                    unified["vector"]["values"].extend(vec.get("values", []))
        return unified

    def split(self, record: dict[str, Any], limit: int = SPLIT_LIMIT_DEFAULT) -> list[dict[str, Any]]:
        vec = record.get("vector")
        if not vec:
            return [record]

        if isinstance(vec, list):
            if len(vec) <= limit:
                return [record]
            return [{**record, "vector": vec[i : i + limit]} for i in range(0, len(vec), limit)]

        elif isinstance(vec, dict):
            indices = vec.get("indices", [])
            values = vec.get("values", [])
            if len(indices) <= limit:
                return [record]

            chunks = []
            for i in range(0, len(indices), limit):
                chunk = record.copy()
                chunk["vector"] = {
                    "dimensions": vec.get("dimensions"),
                    "indices": indices[i : i + limit],
                    "values": values[i : i + limit],
                }
                chunks.append(chunk)
            return chunks

        return [record]


_document_strategy = DocumentExtractionStrategy()
_audio_strategy = AudioTranscriptionStrategy()
_embedding_strategy = EmbeddingStrategy()

MERGE_STRATEGY_REGISTRY: dict[str, MergeStrategy] = {
    "open/document-extraction": _document_strategy,
    "open/audio-transcription": _audio_strategy,
    "open/embedding": _embedding_strategy,
    "open/object-detection": GenericListStrategy(list_field="objects"),
    "open/entity-extraction": GenericListStrategy(list_field="entities"),
    "open/classification": GenericListStrategy(list_field="labels"),
    "open/regression": GenericListStrategy(list_field="points"),
    "open/generic": DictUpdateStrategy(dict_field="data"),
    "open/llm-output": StringStrategy(text_field="response_data"),
}

SPLIT_STRATEGY_REGISTRY: dict[str, SplitStrategy] = {
    "open/document-extraction": _document_strategy,
    "open/audio-transcription": _audio_strategy,
    "open/embedding": _embedding_strategy,
    "open/object-detection": GenericListStrategy(list_field="objects"),
    "open/entity-extraction": GenericListStrategy(list_field="entities"),
    "open/classification": GenericListStrategy(list_field="labels"),
    "open/regression": GenericListStrategy(list_field="points"),
    "open/generic": DictUpdateStrategy(dict_field="data"),
    "open/llm-output": StringStrategy(text_field="response_data"),
}


def merge_chunked_records(records: list[dict[str, Any]], schema_id: str) -> dict[str, Any]:
    """Merges a list of schema-valid chunks into a single record."""
    if not records:
        return {}
    if len(records) == 1:
        return records[0]

    logger.debug("Merging %d records for schema '%s'", len(records), schema_id)
    strategy = MERGE_STRATEGY_REGISTRY.get(schema_id)

    if strategy:
        return strategy.merge(records)

    logger.warning("No merge strategy for schema '%s'. Returning first chunk.", schema_id)
    return records[0]


def chunk_record(record: dict[str, Any], schema_id: str) -> list[dict[str, Any]]:
    """Splits oversize record into valid chunks. Returns original if unsupported or small enough."""
    strategy = SPLIT_STRATEGY_REGISTRY.get(schema_id)

    if strategy:
        if schema_id == "open/generic":
            limit = SPLIT_LIMIT_GENERIC
        elif schema_id == "open/llm-output":
            limit = SPLIT_LIMIT_STRING
        else:
            limit = SPLIT_LIMIT_DEFAULT

        return strategy.split(record, limit=limit)

    return [record]
