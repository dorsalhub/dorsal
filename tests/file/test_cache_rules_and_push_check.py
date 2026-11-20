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

import json
import math
import multiprocessing
import os
import re
import sqlite3
import warnings
from pathlib import Path
from typing import Any

import oatschema
import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from dorsal.api.file import index_file
from dorsal.client import DorsalClient
from dorsal.common import constants
from dorsal.common.constants import BASE_URL as DORSAL_API_URL
from dorsal.common.exceptions import AnnotationValidationError, RejectedAnnotationError
from dorsal.common.model import AnnotationModel
from dorsal.common.validators.json_schema import JsonSchemaValidator
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.file_annotator import FILE_ANNOTATOR
from dorsal.file.index.dorsal_index import DorsalIndex
from dorsal.file.integrity import check_record_schema_versions
from dorsal.file.metadata_reader import MetadataReader
from dorsal.file.model_runner import ModelRunner
from dorsal.file.sharding import build_annotation_or_annotationgroup, reassemble_record
from dorsal.file.validators.file_record import Annotation, AnnotationGroup

BASE_URL = "https://api.example.com"
HUB_OK = {"total": 1, "success": 1, "error": 0, "unauthorized": 0, "results": []}
SOURCE = {"type": "Model", "id": "acme/hand", "version": "1.0", "execution_id": "23456781-1234-5678-1234-567812345678"}
BAD = {"bad": 2**60, "neg": -0.0, "good": 1}
OUTSIDE = "… is outside ±9007199254740991"

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class GenericBad(AnnotationModel):
    id = "acme/generic"
    version = "1.0"

    def main(self):
        return {"data": dict(BAD)}


class GenericClean(AnnotationModel):
    id = "acme/clean"
    version = "1.0"

    def main(self):
        return {"data": {"good": 1}}


class Output(AnnotationModel):
    id = "acme/output"
    version = "1.0"
    output: Any = None

    def main(self):
        return Output.output


class GenericPydantic(BaseModel):
    data: dict[str, Any]


def _step(model: str, schema_id: str = "generic", **extra: Any) -> dict[str, Any]:
    return {
        "annotation_model": {"module": __name__, "name": model},
        "validation_model": {
            "module": "dorsal.file.validators.open_schema",
            "name": f"{schema_id.replace('-', '_')}_validator",
        },
        "schema_id": schema_id,
        **extra,
    }


PIPELINE = [_step("GenericBad")]
OLD_COLUMNS = (
    "abspath TEXT PRIMARY KEY, modified_time REAL NOT NULL, record BLOB, is_compressed INTEGER DEFAULT 0, "
    "name TEXT, size INTEGER, extension TEXT, media_type TEXT, hash_sha256 TEXT, hash_blake3 TEXT, hash_md5 TEXT, "
    "hash_sha1 TEXT, hash_dorsal TEXT, hash_quick TEXT, hash_tlsh TEXT, local_record_id TEXT"
)
INSERT_0_13 = """
    INSERT OR REPLACE INTO cached_files (
        abspath, modified_time, record, is_compressed, name, size,
        extension, media_type, hash_sha256, hash_blake3,
        hash_md5, hash_sha1, hash_dorsal, hash_quick, hash_tlsh, local_record_id
    ) VALUES (
        :abspath, :modified_time, :record, :is_compressed, :name, :size,
        :extension, :media_type, :hash_sha256, :hash_blake3,
        :hash_md5, :hash_sha1, :hash_dorsal, :hash_quick, :hash_tlsh, :local_record_id
    )
"""


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "a.txt").write_text("a")
    (directory / "b.txt").write_text("b")
    return directory


@pytest.fixture
def target(data_dir):
    return str(data_dir / "a.txt")


@pytest.fixture
def cache_path() -> Path:
    return Path.home() / ".dorsal" / "cache.db"


@pytest.fixture
def client() -> DorsalClient:
    return DorsalClient(api_key="x" * 40, base_url=BASE_URL)


@pytest.fixture
def hub(requests_mock):
    requests_mock.post(f"{BASE_URL}/v1/files/private", json=HUB_OK, status_code=201)
    requests_mock.post(f"{BASE_URL}/v1/files/public", json=HUB_OK, status_code=201)
    requests_mock.post(
        re.compile(f"{BASE_URL}/v1/files/[0-9a-f]+/.*"),
        json={"total": 1, "success": 1, "error": 0, "dataset_id": "open/generic", "results": []},
        status_code=201,
    )
    return requests_mock


def _generic(local_file) -> list[Any]:
    return local_file.model.annotations.__pydantic_extra__.get("open/generic", [])


def _bad_record_json(local_file) -> str:
    data = json.loads(local_file.model.model_dump_json(by_alias=True, exclude_none=True))
    data["annotations"]["open/generic"][0]["record"] = {"data": dict(BAD)}
    return json.dumps(data)


def _write_row_as_0_13(path: Path, abspath: str, record_json: str) -> None:
    record = json.loads(record_json)
    conn = sqlite3.connect(path)
    conn.execute(
        INSERT_0_13,
        {
            "abspath": abspath,
            "modified_time": os.path.getmtime(abspath),
            "record": record_json.encode("utf-8"),
            "is_compressed": 0,
            "name": None,
            "size": None,
            "extension": None,
            "media_type": None,
            "hash_sha256": record.get("hash"),
            "hash_blake3": None,
            "hash_md5": None,
            "hash_sha1": None,
            "hash_dorsal": None,
            "hash_quick": None,
            "hash_tlsh": None,
            "local_record_id": None,
        },
    )
    conn.commit()
    conn.close()


def _row(path: Path, abspath: str) -> dict[str, Any]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT rules, on_bad_number FROM cached_files WHERE abspath = ?", (abspath,)).fetchone()
    conn.close()
    return dict(row)


def _write_tampered_row(abspath: str, made: LocalFile, runner: ModelRunner) -> None:
    from dorsal.file.validators.file_record import FileRecordStrict

    DorsalIndex().upsert_record(
        path=abspath,
        modified_time=os.path.getmtime(abspath),
        record=FileRecordStrict.model_validate_json(_bad_record_json(made)),
        on_bad_number="drop",
        rules=runner.cache_rules,
    )


@pytest.mark.parametrize("mode", ["drop", "raise"])
def test_a_row_dorsal_0_13_writes_after_the_upgrade_is_a_miss(target, cache_path, mode):
    made = LocalFile(target, model_runner_pipeline=PIPELINE)
    assert _row(cache_path, target)["rules"] is not None
    _write_row_as_0_13(cache_path, target, _bad_record_json(made))
    assert _row(cache_path, target) == {"rules": None, "on_bad_number": None}

    rescanned = LocalFile(target, model_runner_pipeline=PIPELINE, on_bad_number=mode)

    assert rescanned._source == "disk"
    [change] = rescanned.number_changes
    if mode == "drop":
        assert [record.record.data for record in _generic(rescanned)] == [{"neg": 0.0, "good": 1}]
        assert [item.path for item in change.dropped] == [["data", "bad"]]
    else:
        assert _generic(rescanned) == []
        assert change.rejected is not None
    assert _row(cache_path, target) == {
        "rules": ModelRunner(pipeline_config=PIPELINE).cache_rules,
        "on_bad_number": mode,
    }


def test_a_cache_written_only_by_dorsal_0_13_is_a_miss(target, cache_path):
    made = LocalFile(target, model_runner_pipeline=PIPELINE, use_cache=False)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_path)
    conn.execute(f"CREATE TABLE cached_files ({OLD_COLUMNS})")
    conn.commit()
    conn.close()
    _write_row_as_0_13(cache_path, target, _bad_record_json(made))

    rescanned = LocalFile(target, model_runner_pipeline=PIPELINE)

    assert rescanned._source == "disk"
    assert [record.record.data for record in _generic(rescanned)] == [{"neg": 0.0, "good": 1}]
    assert len(rescanned.number_changes) == 1


def test_a_row_made_under_the_current_rules_is_a_hit(target):
    LocalFile(target, model_runner_pipeline=PIPELINE)

    cached = LocalFile(target, model_runner_pipeline=PIPELINE)

    assert cached._source == "cache"
    [change] = cached.number_changes
    assert [item.path for item in change.dropped] == [["data", "bad"]]


def test_a_row_without_its_on_bad_number_is_a_miss(target, cache_path):
    LocalFile(target, model_runner_pipeline=PIPELINE)
    conn = sqlite3.connect(cache_path)
    conn.execute("UPDATE cached_files SET on_bad_number = NULL")
    conn.commit()
    conn.close()

    assert LocalFile(target, model_runner_pipeline=PIPELINE)._source == "disk"


@pytest.mark.parametrize(
    "second",
    [
        [_step("GenericClean")],
        [_step("GenericBad"), _step("GenericClean")],
        [_step("GenericBad", options={"x": 1})],
        [_step("GenericBad", schema_version="0.9.0")],
        [_step("GenericBad", deactivated=True)],
    ],
    ids=["model", "added-step", "options", "schema-version", "deactivated"],
)
def test_a_row_made_with_another_pipeline_is_a_miss(target, second):
    LocalFile(target, model_runner_pipeline=PIPELINE)

    assert LocalFile(target, model_runner_pipeline=second)._source == "disk"
    assert LocalFile(target, model_runner_pipeline=second)._source == "cache"


@pytest.mark.parametrize("change", ["cache", "oatschema", "oats"])
def test_a_row_made_under_other_rules_is_a_miss(target, mocker, change):
    LocalFile(target, model_runner_pipeline=PIPELINE)
    if change == "cache":
        mocker.patch.object(constants, "CACHE_RULES_VERSION", constants.CACHE_RULES_VERSION + 1)
    elif change == "oatschema":
        mocker.patch("dorsal.file.model_runner._oatschema_version", return_value="0.9.0.99")
    else:
        mocker.patch.object(constants, "OPEN_VALIDATION_SCHEMAS_VER", "0.7.0")

    assert LocalFile(target, model_runner_pipeline=PIPELINE)._source == "disk"


def test_the_cache_rules_name_what_a_record_is_made_under(monkeypatch, tmp_path):
    runner = ModelRunner(pipeline_config=PIPELINE)
    rules = json.loads(runner.cache_rules)

    assert rules["cache"] == constants.CACHE_RULES_VERSION
    assert rules["oatschema"] == __import__("importlib.metadata").metadata.version("oatschema")
    assert rules["oats"] == constants.OPEN_VALIDATION_SCHEMAS_VER
    assert rules["schemas_dir"] is None
    assert runner.cache_rules == ModelRunner(pipeline_config=PIPELINE).cache_rules

    monkeypatch.setenv(constants.ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, str(tmp_path))
    assert json.loads(runner.cache_rules)["schemas_dir"] == str(tmp_path)


def _cli(*args: str):
    from dorsal.cli import app

    with warnings.catch_warnings():
        return CliRunner().invoke(app, list(args))


def test_cli_scan_does_not_serve_a_step_removed_from_the_pipeline(data_dir, mocker):
    config = mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": PIPELINE}, data_dir))
    target = str(data_dir / "a.txt")
    first = _cli("scan", target, "--json", "--use-cache")
    assert first.exit_code == 0, first.output
    assert "open/generic" in json.loads(first.stdout)["annotations"]

    config.return_value = ({"model_pipeline": []}, data_dir)
    second = _cli("scan", target, "--json", "--use-cache")

    assert second.exit_code == 0, second.output
    data = json.loads(second.stdout)
    assert data["source"] == "disk"
    assert "open/generic" not in data["annotations"]


def test_reader_scan_directory_rescans_rows_dorsal_0_13_wrote(data_dir, cache_path):
    reader = MetadataReader(model_config=PIPELINE, offline=True)
    made = reader.scan_directory(str(data_dir))
    for local_file in made:
        _write_row_as_0_13(cache_path, str(local_file.file_path), _bad_record_json(local_file))

    rescanned = MetadataReader(model_config=PIPELINE, offline=True).scan_directory(str(data_dir))

    assert sorted(f._source for f in rescanned) == ["disk", "disk"]
    assert all([r.record.data for r in _generic(f)] == [{"neg": 0.0, "good": 1}] for f in rescanned)


def test_push_refuses_an_annotation_edited_after_it_was_checked(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"good": 1}}, source="me")
    local_file.get_annotations("generic")[0].record.data["y"] = 2**60

    with pytest.raises(RejectedAnnotationError) as err:
        local_file.push()
    assert err.value.problems[0]["reason"] == OUTSIDE
    assert hub.request_history == []


def test_push_refuses_a_nan_added_after_the_check(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"good": 1}}, source="me")
    local_file.get_annotations("generic")[0].record.data["x"] = math.nan

    with pytest.raises(RejectedAnnotationError):
        local_file.push()
    assert hub.request_history == []


def test_push_checks_an_annotation_at_the_version_it_was_restamped_with(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    llm = {"model": "m", "response_data": "hi", "generation_params": {"seed": 5}}
    local_file.add_annotation("llm-output", llm, source="me", schema_version="0.8.0")
    annotation = local_file.get_annotations("llm-output")[0]
    annotation.schema_version = "0.9.0"

    local_file.push()

    sent = hub.request_history[0].json()[0]["annotations"]["open/llm-output"][0]
    assert sent["schema_version"] == "0.9.0"
    assert sent["record"]["generation_params"] == {"seed": "5"}
    assert annotation.record.model_dump()["generation_params"] == {"seed": 5}


def test_push_sends_an_edited_value_converted_and_leaves_the_file_as_it_was(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"good": 1}}, source="me")
    annotation = local_file.get_annotations("generic")[0]
    annotation.record.data["neg"] = -0.0

    local_file.push()

    sent = hub.request_history[0].json()[0]["annotations"]["open/generic"][0]["record"]["data"]
    assert sent == {"good": 1, "neg": 0.0}
    assert math.copysign(1.0, annotation.record.data["neg"]) == -1.0


def _heavy(mocker) -> None:
    mocker.patch.object(constants, "API_MAX_RECORD_SIZE_BYTES", 2000)
    mocker.patch.object(constants, "API_RECORD_HEADROOM_BYTES", 0)


def test_a_heavy_push_refuses_an_edited_annotation_before_sending_anything(target, client, hub, mocker):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    blocks = [{"text": "word " * 50, "block_type": "text"} for _ in range(200)]
    local_file.add_annotation("document-extraction", {"blocks": blocks, "producer": "x"}, source="me")
    local_file.get_annotations("document-extraction")[0].record.blocks[3]["page_number"] = 2**60
    _heavy(mocker)

    with pytest.raises(RejectedAnnotationError):
        local_file.push()
    assert hub.request_history == []


def test_a_heavy_push_sends_the_converted_annotation(target, client, hub, mocker):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    blocks = [{"text": "word " * 50, "block_type": "text"} for _ in range(200)]
    local_file.add_annotation("document-extraction", {"blocks": blocks, "producer": "x"}, source="me")
    local_file.get_annotations("document-extraction")[0].record.blocks[3]["score"] = -0.0
    _heavy(mocker)
    spy = mocker.spy(oatschema, "check_numbers")

    local_file.push()

    assert spy.call_count == 1
    sent = hub.request_history[1].json()["record"]["blocks"][3]
    assert math.copysign(1.0, sent["score"]) == 1.0


def test_push_rebuilds_a_sharded_group_the_check_converts(target):
    blocks = [{"text": "word " * 800, "block_type": "text"} for _ in range(600)]
    blocks[0]["score"] = -0.0
    group = build_annotation_or_annotationgroup(
        schema_id="document-extraction",
        record_data={"blocks": blocks, "producer": "x"},
        source=SOURCE,
        schema_version="0.8.0",
    )
    assert isinstance(group, AnnotationGroup)
    local_file = LocalFile(target, model_runner_pipeline=[], use_cache=False)
    local_file.model.annotations.__pydantic_extra__["open/document-extraction"] = [group]

    [sent] = check_record_schema_versions([local_file.model])

    [sent_group] = sent.annotations.__pydantic_extra__["open/document-extraction"]
    assert isinstance(sent_group, AnnotationGroup)
    assert sent_group.schema_version == "0.8.0" and sent_group.source == group.source
    _, record = reassemble_record(sent_group)
    assert math.copysign(1.0, record["blocks"][0]["score"]) == 1.0
    assert len(record["blocks"]) == 600
    assert local_file.model.annotations.__pydantic_extra__["open/document-extraction"] == [group]


@pytest.mark.parametrize("route", ["local_file", "reader", "api"])
def test_every_single_file_route_checks_a_cache_hit_at_push(target, client, hub, mocker, route):
    made = LocalFile(target, model_runner_pipeline=PIPELINE)
    _write_tampered_row(target, made, ModelRunner(pipeline_config=PIPELINE))
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": PIPELINE}, Path(target).parent))
    mocker.patch("dorsal.session.get_shared_dorsal_client", return_value=client)

    with pytest.raises(RejectedAnnotationError):
        if route == "local_file":
            cached = LocalFile(target, client=client, model_runner_pipeline=PIPELINE)
            assert cached._source == "cache"
            cached.push()
        elif route == "reader":
            MetadataReader(model_config=PIPELINE, client=client).index_file(target)
        else:
            index_file(target, use_cache=True)
    assert hub.request_history == []


def test_index_directory_refuses_every_file_when_one_cached_record_fails(data_dir, client, hub, mocker):
    reader = MetadataReader(model_config=PIPELINE, client=client)
    made = reader.scan_directory(str(data_dir))
    _write_tampered_row(str(made[0].file_path), made[0], reader._model_runner)

    with pytest.raises(RejectedAnnotationError):
        MetadataReader(model_config=PIPELINE, client=client).index_directory(str(data_dir))
    assert hub.request_history == []


def test_index_directory_checks_each_annotation_once(data_dir, client, hub, mocker):
    reader = MetadataReader(model_config=PIPELINE, client=client)
    reader.scan_directory(str(data_dir))
    spy = mocker.spy(oatschema, "check_numbers")

    MetadataReader(model_config=PIPELINE, client=client).index_directory(str(data_dir))

    assert spy.call_count == 2
    assert len(hub.request_history) == 1


def test_reader_index_file_checks_each_annotation_once(target, client, hub, mocker):
    LocalFile(target, model_runner_pipeline=PIPELINE)
    spy = mocker.spy(oatschema, "check_numbers")

    MetadataReader(model_config=PIPELINE, client=client).index_file(target)

    assert spy.call_count == 1
    assert len(hub.request_history) == 1


def test_client_checks_an_edited_record_and_annotation(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"good": 1}}, source="me")
    annotation = local_file.get_annotations("generic")[0]
    annotation.record.data["y"] = 2**60

    with pytest.raises(RejectedAnnotationError):
        client.index_private_file_records(file_records=[local_file.model])
    with pytest.raises(RejectedAnnotationError):
        client.add_file_annotation(file_hash=local_file.hash, schema_id="generic", annotation=annotation)
    assert hub.request_history == []


def test_cli_push_checks_a_cache_hit(data_dir, mocker, monkeypatch, requests_mock):
    monkeypatch.setenv("DORSAL_API_KEY", "x" * 40)
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": PIPELINE}, data_dir))
    requests_mock.post(f"{DORSAL_API_URL}/v1/files/private", json=HUB_OK, status_code=201)
    target = str(data_dir / "a.txt")
    reader = MetadataReader(offline=True)
    made = reader.scan_file(target, skip_cache=False)
    _write_tampered_row(target, made, reader._model_runner)

    result = _cli("push", target, "--use-cache")

    assert result.exit_code != 0
    assert requests_mock.request_history == []


OLD_TABLE_DEV = OLD_COLUMNS + ", number_changes TEXT, on_bad_number TEXT"


def _open_together(path: str, barrier: Any, results: Any) -> None:
    from dorsal.file.index.dorsal_index import DorsalIndex

    barrier.wait()
    try:
        DorsalIndex(Path(path)).get_record(path="/nothing")
        results.put("ok")
    except Exception as err:
        results.put(repr(err))


def _columns(path: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    columns = [tuple(row) for row in conn.execute("PRAGMA table_info(cached_files)").fetchall()]
    conn.close()
    return columns


@pytest.mark.parametrize("old_columns", [OLD_COLUMNS, OLD_TABLE_DEV], ids=["0.13", "dev"])
def test_processes_opening_an_old_cache_together_all_upgrade_it(tmp_path, old_columns):
    context = multiprocessing.get_context("spawn")
    processes = 6
    for trial in range(3):
        path = tmp_path / f"cache-{trial}.db"
        conn = sqlite3.connect(path)
        conn.execute(f"CREATE TABLE cached_files ({old_columns})")
        conn.commit()
        conn.close()
        barrier = context.Barrier(processes)
        results = context.Queue()
        workers = [context.Process(target=_open_together, args=(str(path), barrier, results)) for _ in range(processes)]
        for worker in workers:
            worker.start()
        outcomes = [results.get(timeout=120) for _ in workers]
        for worker in workers:
            worker.join(timeout=120)

        assert outcomes == ["ok"] * processes
        fresh = tmp_path / f"fresh-{trial}.db"
        DorsalIndex(fresh).get_record(path="/nothing")
        assert _columns(path) == _columns(fresh)


def _run(validator: Any, record: Any, mode: str, **kwargs: Any):
    Output.output = record
    try:
        return ModelRunner(pipeline_config=None, single_model_mode=True).run_single_model(
            annotation_model=Output,
            validation_model=validator,
            file_path="/fake/path",
            on_bad_number=mode,
            **kwargs,
        )
    finally:
        Output.output = None


def _custom(name: str, version: str = "0.8.0") -> JsonSchemaValidator:
    return JsonSchemaValidator(oatschema.get_schema(name, version))


@pytest.mark.parametrize("mode", ["drop", "raise"])
def test_a_custom_validator_keeps_no_record_a_bad_number_rejects(mode):
    [result] = _run(_custom("embedding"), {"model": "m", "vector": [0.5, 2**60]}, mode, schema_id="embedding")

    assert result.records is None and result.schema_version is None
    assert result.error is not None and "rejected" in result.error
    assert result.rejected is not None and result.rejected.startswith(OUTSIDE)


@pytest.mark.parametrize("mode", ["drop", "raise"])
def test_a_pydantic_validator_keeps_no_record_a_bad_number_rejects(mode):
    [result] = _run(GenericPydantic, {"data": {"xs": [2**60]}}, mode, schema_id="generic", schema_version="0.8.0")

    assert result.records is None and result.schema_version is None
    assert result.rejected is not None and result.rejected.startswith(OUTSIDE)


def test_a_custom_validator_still_keeps_a_droppable_bad_number_dropped():
    [result] = _run(_custom("generic"), {"data": dict(BAD)}, "drop", schema_id="generic")

    assert result.schema_version == "0.8.0"
    assert result.records == [{"data": {"neg": 0.0, "good": 1}}]
    assert result.rejected is None


def _document(n_blocks: int) -> dict:
    return {
        "producer": "test",
        "unit": "pt",
        "extraction_type": "text",
        "blocks": [{"block_type": "text", "text": f"b{i}", "page_number": 1} for i in range(n_blocks)],
    }


@pytest.mark.parametrize("mode", ["drop", "raise"])
def test_a_split_record_a_bad_number_rejects_is_not_kept(mode):
    record = _document(200_005)
    record["blocks"][100_002]["polygon"] = [{"x": 0, "y": 0}, {"x": 2**60, "y": 1}, {"x": 2, "y": 2}]

    results = _run(_custom("document-extraction"), record, mode, schema_id="document-extraction")

    [result] = results
    assert result.records is None and result.schema_version is None
    assert result.rejected is not None and "/blocks/2/polygon/1/x" in result.rejected


def test_a_pipeline_lists_a_custom_validator_rejection_and_keeps_no_annotation(target):
    Output.output = {"model": "m", "vector": [0.5, 2**60]}
    try:
        step = {
            "annotation_model": {"module": __name__, "name": "Output"},
            "validation_model": {"module": __name__, "name": "EMBEDDING_0_8_0"},
            "schema_id": "embedding",
        }
        local_file = LocalFile(target, model_runner_pipeline=[step], use_cache=False)
    finally:
        Output.output = None

    assert "open/embedding" not in local_file.model.annotations.__pydantic_extra__
    [change] = local_file.number_changes
    assert change.schema_id == "open/embedding" and change.rejected is not None


EMBEDDING_0_8_0 = _custom("embedding")


def test_a_manual_annotation_with_a_custom_validator_is_refused_in_drop_mode():
    with pytest.raises(AnnotationValidationError):
        FILE_ANNOTATOR.make_checked_manual_annotation(
            annotation={"model": "m", "vector": [0.5, 2**60]},
            schema_id="embedding",
            source_id="me",
            validator=_custom("embedding"),
            private=None,
        )


def test_a_hand_built_annotation_passes_the_check_once_it_is_valid(target, client, hub):
    annotation = Annotation(record={"data": {"x": 1}}, source=SOURCE, schema_id="open/generic", schema_version="0.8.0")

    client.add_file_annotation(file_hash="a" * 64, schema_id="generic", annotation=annotation)

    assert len(hub.request_history) == 1


DEPENDENT_STEP = _step(
    "GenericBad",
    dependencies=[
        {"type": "media_type", "include": ["text", "audio", "video", "image", "application/pdf"]},
        {"type": "extension", "extensions": ["txt", "md", "csv", "pdf", "json", "xml"]},
    ],
)


def _in_a_new_process(code: str, hash_seed: int, home: Path) -> str:
    import subprocess
    import sys

    env = {**os.environ, "PYTHONHASHSEED": str(hash_seed), "HOME": str(home), "USERPROFILE": str(home)}
    env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).parent), env.get("PYTHONPATH", "")])
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip().splitlines()[-1]


def test_the_cache_rules_are_the_same_in_every_process(tmp_path):
    code = (
        "from dorsal.file.model_runner import ModelRunner\n"
        f"import {__name__} as tests\n"
        "print(ModelRunner([tests.DEPENDENT_STEP]).cache_rules + ModelRunner('default').cache_rules)\n"
    )

    assert len({_in_a_new_process(code, seed, tmp_path) for seed in (1, 2, 3, 4)}) == 1


def test_a_record_cached_by_one_process_is_a_hit_in_the_next(tmp_path, target):
    code = (
        "from dorsal.file.dorsal_file import LocalFile\n"
        f"import {__name__} as tests\n"
        f"print(LocalFile({target!r}, model_runner_pipeline=[tests.DEPENDENT_STEP])._source)\n"
    )

    assert [_in_a_new_process(code, seed, tmp_path) for seed in (1, 2)] == ["disk", "cache"]


def test_a_pipeline_with_option_values_json_cannot_hold_still_caches(target):
    step = _step("GenericBad", options={"pattern": re.compile("a+"), "fn": len, "kinds": {"b", "a"}})

    assert LocalFile(target, model_runner_pipeline=[step])._source == "disk"
    assert LocalFile(target, model_runner_pipeline=[step])._source == "cache"
