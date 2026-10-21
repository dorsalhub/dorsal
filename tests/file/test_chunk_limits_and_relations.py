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

import copy

import pytest

from dorsal.file.chunking import chunk_record, list_limit, merge_chunked_records
from dorsal.file.sharding import (
    ANNOTATION_MAX_SIZE_BYTES,
    EntityShardingStrategy,
    build_annotation_or_annotationgroup,
    check_record_size,
    reassemble_record,
)
from dorsal.file.validators.file_record import AnnotationGroup
from dorsal.file.validators.open_schema import get_open_schema_validator

SOURCE = {"type": "Model", "id": "test/model", "version": "1.0", "execution_id": "23456781-1234-5678-1234-567812345678"}


def _assert_valid(records, name, version):
    validator = get_open_schema_validator(name, version)
    for record in records:
        assert validator.first_error(record) is None


def _classification(n):
    return {"labels": [{"label": f"label-{i}", "score": 0.5} for i in range(n)]}


def _regression(n):
    return {"points": [{"value": float(i)} for i in range(n)]}


def _ranking(n, text=""):
    return {"query": "q", "results": [{"rank": i + 1, "id": f"doc-{i}", "text": text} for i in range(n)]}


def _temporal(n, title=""):
    return {
        "producer": "test",
        "segments": [{"label": "scene", "start_time": i, "end_time": i + 1, "title": title} for i in range(n)],
    }


def _entities(n_entities, n_relations, text="x"):
    return {
        "entities": [{"id": f"e{i}", "label": "thing", "text": text} for i in range(n_entities)],
        "relations": [
            {"label": "next_to", "subject_id": f"e{i % n_entities}", "object_id": f"e{(i + 1) % n_entities}"}
            for i in range(n_relations)
        ],
    }


@pytest.mark.parametrize(
    "schema_id, field, version, expected",
    [
        ("open/classification", "labels", "0.5.0", 10_000),
        ("open/classification", "labels", "0.8.0", 10_000),
        ("open/regression", "points", "0.4.0", 10_000),
        ("open/regression", "points", None, 10_000),
        ("open/ranking", "results", "0.8.0", 10_000),
        ("open/ranking", "results", None, 10_000),
        ("open/temporal-segmentation", "segments", "0.7.0", 100_000),
        ("open/document-extraction", "blocks", "0.5.0", 100_000),
        ("open/entity-extraction", "relations", "0.8.0", 100_000),
    ],
)
def test_list_limits_come_from_the_schema(schema_id, field, version, expected):
    assert list_limit(schema_id, field, version) == expected


@pytest.mark.parametrize("version", ["0.4.0", "0.5.0", "0.8.0"])
@pytest.mark.parametrize(
    "schema_id, build, field",
    [("open/classification", _classification, "labels"), ("open/regression", _regression, "points")],
)
def test_classification_and_regression_split_at_ten_thousand(schema_id, build, field, version):
    record = build(15_000)
    name = schema_id.removeprefix("open/")
    assert get_open_schema_validator(name, version).first_error(record) is not None

    chunks = chunk_record(record, schema_id, schema_version=version)

    assert [len(c[field]) for c in chunks] == [10_000, 5_000]
    _assert_valid(chunks, name, version)
    assert merge_chunked_records(chunks, schema_id) == record


@pytest.mark.parametrize(
    "schema_id, version, record, sizes",
    [
        ("open/ranking", "0.8.0", _ranking(25_000), [10_000, 10_000, 5_000]),
        ("open/temporal-segmentation", "0.7.0", _temporal(150_000), [100_000, 50_000]),
        ("open/temporal-segmentation", "0.8.0", _temporal(150_000), [100_000, 50_000]),
    ],
)
def test_ranking_and_temporal_segmentation_chunk_into_valid_records(schema_id, version, record, sizes):
    name = schema_id.removeprefix("open/")
    field = "results" if name == "ranking" else "segments"
    assert get_open_schema_validator(name, version).first_error(record) is not None

    chunks = chunk_record(record, schema_id, schema_version=version)

    assert [len(c[field]) for c in chunks] == sizes
    _assert_valid(chunks, name, version)
    assert merge_chunked_records(chunks, schema_id) == record


def _strip_schema_ids(group: AnnotationGroup) -> AnnotationGroup:
    stripped = group.model_copy(deep=True)
    for annotation in stripped.annotations:
        annotation.schema_id = None
    return stripped


@pytest.mark.parametrize(
    "schema_id, record",
    [
        ("open/ranking", _ranking(4_000, text="t" * 400)),
        ("open/temporal-segmentation", _temporal(8_000, title="t" * 120)),
    ],
)
def test_ranking_and_temporal_segmentation_shard_and_reassemble(schema_id, record):
    assert check_record_size(record) > ANNOTATION_MAX_SIZE_BYTES

    group = build_annotation_or_annotationgroup(
        schema_id=schema_id, record_data=copy.deepcopy(record), source=SOURCE, schema_version="0.8.0"
    )

    assert isinstance(group, AnnotationGroup)
    assert len(group.annotations) > 1
    _assert_valid([a.record.model_dump() for a in group.annotations], schema_id.removeprefix("open/"), "0.8.0")
    assert reassemble_record(group) == (schema_id, record)
    assert reassemble_record(_strip_schema_ids(group)) == (schema_id, record)


def test_audio_transcription_groups_are_still_detected_without_schema_ids():
    record = {
        "text": "hello",
        "segments": [{"text": "t" * 200, "start_time": i, "end_time": i + 1} for i in range(8_000)],
    }
    group = build_annotation_or_annotationgroup(
        schema_id="open/audio-transcription", record_data=copy.deepcopy(record), source=SOURCE
    )

    assert isinstance(group, AnnotationGroup)
    assert reassemble_record(_strip_schema_ids(group)) == ("open/audio-transcription", record)


def test_entity_relations_are_not_copied_into_every_shard():
    record = _entities(8_000, 2_000, text="t" * 300)
    assert check_record_size(record) > ANNOTATION_MAX_SIZE_BYTES

    group = build_annotation_or_annotationgroup(
        schema_id="open/entity-extraction", record_data=copy.deepcopy(record), source=SOURCE, schema_version="0.8.0"
    )

    assert isinstance(group, AnnotationGroup)
    shards = [a.record.model_dump() for a in group.annotations]
    assert len(shards) > 1
    assert sum(len(s["relations"]) for s in shards) == 2_000
    for shard in shards:
        ids = {e["id"] for e in shard["entities"]}
        assert all(r["subject_id"] in ids for r in shard["relations"])
    _assert_valid(shards, "entity-extraction", "0.8.0")
    assert reassemble_record(group) == ("open/entity-extraction", record)
    assert reassemble_record(_strip_schema_ids(group)) == ("open/entity-extraction", record)


def test_relations_spill_into_later_shards_when_one_entity_has_too_many():
    record = {
        "entities": [{"id": "hub", "label": "thing"}] + [{"id": f"e{i}", "label": "thing"} for i in range(10)],
        "relations": [
            {"label": "linked_to", "subject_id": "hub", "object_id": f"e{i % 10}", "text": "r" * 200}
            for i in range(8_000)
        ],
    }
    assert check_record_size(record) > ANNOTATION_MAX_SIZE_BYTES

    shards = EntityShardingStrategy().split(copy.deepcopy(record))

    assert len(shards) > 1
    assert all(check_record_size(s) <= ANNOTATION_MAX_SIZE_BYTES for s in shards)
    assert shards[0]["entities"][0]["id"] == "hub"
    assert [e for s in shards for e in s["entities"]] == record["entities"]
    assert [r for s in shards for r in s["relations"]] == record["relations"]
    _assert_valid(shards, "entity-extraction", "0.8.0")


def test_groups_from_0_12_0_with_relations_in_every_shard_reassemble_once(monkeypatch):
    from dorsal.file import sharding

    record = _entities(8_000, 2_000, text="t" * 300)
    monkeypatch.setitem(sharding.SHARDING_REGISTRY, "open/entity-extraction", sharding.ListBasedStrategy("entities"))
    old_style = build_annotation_or_annotationgroup(
        schema_id="open/entity-extraction", record_data=copy.deepcopy(record), source=SOURCE, schema_version="0.8.0"
    )
    monkeypatch.undo()

    assert isinstance(old_style, AnnotationGroup)
    assert all(a.record.model_dump()["relations"] == record["relations"] for a in old_style.annotations)
    assert reassemble_record(old_style) == ("open/entity-extraction", record)
    assert reassemble_record(_strip_schema_ids(old_style)) == ("open/entity-extraction", record)


def test_entity_chunks_keep_relations_with_their_subject(monkeypatch):
    monkeypatch.setattr("dorsal.file.chunking.SPLIT_LIMIT_DEFAULT", 4)
    record = {
        "entities": [{"id": f"e{i}", "label": "thing"} for i in range(10)],
        "relations": [
            {"label": "r", "subject_id": "e9", "object_id": "e0"},
            {"label": "r", "subject_id": "e1", "object_id": "e8"},
            {"label": "r", "subject_id": "missing", "object_id": "e5"},
            {"label": "r", "subject_id": "missing", "object_id": "missing"},
        ],
    }

    chunks = chunk_record(record, "open/entity-extraction", schema_version="0.8.0")

    assert [[e["id"] for e in c["entities"]] for c in chunks] == [
        ["e0", "e1", "e2", "e3"],
        ["e4", "e5", "e6", "e7"],
        ["e8", "e9"],
    ]
    assert [[r["subject_id"] for r in c["relations"]] for c in chunks] == [["e1", "missing"], ["missing"], ["e9"]]
    assert chunks[1]["relations"][0]["object_id"] == "e5"
    _assert_valid(chunks, "entity-extraction", "0.8.0")

    merged = merge_chunked_records(chunks, "open/entity-extraction")
    assert merged["entities"] == record["entities"]
    assert sorted(map(str, merged["relations"])) == sorted(map(str, record["relations"]))


def test_entity_relations_over_the_limit_get_their_own_chunks(monkeypatch):
    monkeypatch.setattr("dorsal.file.chunking.SPLIT_LIMIT_DEFAULT", 3)
    record = {
        "entities": [{"id": "a", "label": "thing"}, {"id": "b", "label": "thing"}],
        "relations": [{"label": "r", "subject_id": "a", "object_id": "b"} for _ in range(7)],
    }

    chunks = chunk_record(record, "open/entity-extraction", schema_version="0.8.0")

    assert [len(c["entities"]) for c in chunks] == [2, 0, 0]
    assert [len(c["relations"]) for c in chunks] == [3, 3, 1]
    _assert_valid(chunks, "entity-extraction", "0.8.0")
    assert merge_chunked_records(chunks, "open/entity-extraction") == record


def test_audio_transcription_text_overflow_chunks_are_valid_at_0_8_0(monkeypatch):
    monkeypatch.setattr("dorsal.file.chunking.SPLIT_LIMIT_DEFAULT", 2)
    record = {
        "text": "x" * 600_000,
        "segments": [{"text": "a", "start_time": 0, "end_time": 1}, {"text": "b", "start_time": 1, "end_time": 2}],
    }

    chunks = chunk_record(record, "open/audio-transcription", schema_version="0.8.0")

    assert len(chunks) == 3
    assert "segments" not in chunks[1] and "segments" not in chunks[2]
    _assert_valid(chunks, "audio-transcription", "0.8.0")
