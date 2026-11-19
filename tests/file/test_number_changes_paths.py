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
import re
import warnings
from typing import Any

import oatschema
import pytest
from typer.testing import CliRunner

from dorsal.api.file import index_file, scan_directory, scan_file
from dorsal.client import DorsalClient
from dorsal.common import constants
from dorsal.common.constants import BASE_URL as DORSAL_API_URL
from dorsal.common.exceptions import RejectedAnnotationError, UnversionedAnnotationError
from dorsal.common.model import AnnotationModel
from dorsal.file.collection.local import LocalFileCollection
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.index.dorsal_index import DorsalIndex
from dorsal.file.integrity import check_record_schema_versions, is_numbers_checked
from dorsal.file.metadata_reader import MetadataReader
from dorsal.file.sharding import build_annotation_or_annotationgroup
from dorsal.file.validators.file_record import AnnotationGroup
import dorsal.testing

BASE_URL = "https://api.example.com"
HUB_OK = {"total": 1, "success": 1, "error": 0, "unauthorized": 0, "results": []}
LLM_BAD = {"model": "m", "response_data": "hi", "score": 7.0, "generation_params": {"temperature": -0.0}}
GENERIC_BAD = {"data": {"bad": 2**60, "neg": -0.0, "good": 1}}
SOURCE = {"type": "Model", "id": "acme/hand", "version": "1.0", "execution_id": "23456781-1234-5678-1234-567812345678"}

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class LlmBad(AnnotationModel):
    id = "acme/llm"
    version = "1.0"

    def main(self):
        return dict(LLM_BAD, generation_params=dict(LLM_BAD["generation_params"]))


class GenericBad(AnnotationModel):
    id = "acme/generic"
    version = "1.0"

    def main(self):
        return {"data": dict(GENERIC_BAD["data"])}


def _step(model: str, schema_id: str) -> dict[str, Any]:
    return {
        "annotation_model": {"module": __name__, "name": model},
        "validation_model": {
            "module": "dorsal.file.validators.open_schema",
            "name": f"{schema_id.replace('-', '_')}_validator",
        },
        "schema_id": schema_id,
    }


PIPELINE = [_step("LlmBad", "llm-output"), _step("GenericBad", "generic")]


def _changes(local_file) -> list[tuple[Any, ...]]:
    return [
        (
            change.schema_id,
            change.source_id,
            [item.path for item in change.dropped],
            [item.path for item in change.converted],
            change.rejected is not None,
        )
        for change in local_file.number_changes
    ]


DROP_CHANGES = [
    ("open/llm-output", "acme/llm", [["score"]], [["generation_params", "temperature"]], False),
    ("open/generic", "acme/generic", [["data", "bad"]], [["data", "neg"]], False),
]
RAISE_CHANGES = [
    ("open/llm-output", "acme/llm", [], [], True),
    ("open/generic", "acme/generic", [], [], True),
]


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
def pipeline_config(mocker, data_dir):
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": PIPELINE}, data_dir))


def _oats(local_file) -> set[str]:
    return {key for key in local_file.model.annotations.__pydantic_extra__ if key.startswith("open/")}


def test_upgrade_keeps_strict_mode_from_a_reader(data_dir):
    reader = MetadataReader(model_config=PIPELINE, offline=True, on_bad_number="raise")
    local_file = next(f for f in reader.scan_directory(str(data_dir), calculate_hashes=False, skip_cache=True))
    assert local_file.on_bad_number == "raise"

    local_file.upgrade_file_record()

    assert _oats(local_file) == set()
    assert _changes(local_file) == RAISE_CHANGES


@pytest.mark.parametrize("mode, expected", [("drop", DROP_CHANGES), ("raise", RAISE_CHANGES)])
def test_upgrade_lists_each_change_once(target, mode, expected):
    local_file = LocalFile(
        target, model_runner_pipeline=PIPELINE, use_cache=False, calculate_hashes=False, on_bad_number=mode
    )
    assert _changes(local_file) == expected

    local_file.upgrade_file_record()

    assert _changes(local_file) == expected


def test_overwrite_forgets_the_replaced_annotations_changes(target):
    local_file = LocalFile(target, model_runner_pipeline=PIPELINE, use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 2**60}}, source="me")
    assert [change.source_id for change in local_file.number_changes] == ["acme/llm", "acme/generic", "me"]

    local_file.add_annotation("generic", {"data": {"x": 3}}, source="me", overwrite=True)

    assert [change.source_id for change in local_file.number_changes] == ["acme/llm", "acme/generic"]


def test_remove_annotation_forgets_its_changes(target):
    local_file = LocalFile(target, model_runner_pipeline=PIPELINE, use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 2**60}}, source="me")

    local_file.remove_annotation("generic", source_id="me")
    assert [change.source_id for change in local_file.number_changes] == ["acme/llm", "acme/generic"]

    local_file.remove_annotation("llm-output")
    assert [change.source_id for change in local_file.number_changes] == ["acme/generic"]


def test_a_cache_hit_reports_the_changes_made_when_the_record_was_cached(target):
    first = LocalFile(target, model_runner_pipeline=PIPELINE)
    assert first._source == "disk"

    again = LocalFile(target, model_runner_pipeline=PIPELINE)

    assert again._source == "cache"
    assert _changes(again) == DROP_CHANGES
    assert again.model.annotations.__pydantic_extra__["open/generic"][0].record.model_dump() == {
        "data": {"neg": 0.0, "good": 1}
    }


def test_strict_mode_does_not_take_a_record_cached_with_drops(target):
    LocalFile(target, model_runner_pipeline=PIPELINE)

    strict = LocalFile(target, model_runner_pipeline=PIPELINE, on_bad_number="raise")

    assert strict._source == "disk"
    assert _oats(strict) == set()
    assert _changes(strict) == RAISE_CHANGES
    assert LocalFile(target, model_runner_pipeline=PIPELINE, on_bad_number="raise")._source == "cache"


def test_drop_mode_reuses_a_record_cached_in_strict_mode_with_no_rejection(target, mocker):
    mocker.patch.object(GenericBad, "main", return_value={"data": {"good": 1, "neg": -0.0}})
    clean = [_step("GenericBad", "generic")]
    LocalFile(target, model_runner_pipeline=clean, on_bad_number="raise")

    lenient = LocalFile(target, model_runner_pipeline=clean)

    assert lenient._source == "cache"
    assert [change.converted[0].path for change in lenient.number_changes] == [["data", "neg"]]


def test_drop_mode_does_not_take_a_record_cached_in_strict_mode(target):
    LocalFile(target, model_runner_pipeline=PIPELINE, on_bad_number="raise")

    lenient = LocalFile(target, model_runner_pipeline=PIPELINE)

    assert lenient._source == "disk"
    assert _oats(lenient) == {"open/llm-output", "open/generic"}
    assert _changes(lenient) == DROP_CHANGES


def test_strict_mode_reuses_a_clean_cached_record(target, mocker):
    mocker.patch.object(GenericBad, "main", return_value={"data": {"good": 1}})
    clean = [_step("GenericBad", "generic")]
    LocalFile(target, model_runner_pipeline=clean)

    assert LocalFile(target, model_runner_pipeline=clean, on_bad_number="raise")._source == "cache"


def test_a_cache_entry_without_number_changes_is_served_and_trusted(target, mocker):
    mocker.patch.object(GenericBad, "main", return_value={"data": {"good": 1}})
    clean = [_step("GenericBad", "generic")]
    made = LocalFile(target, model_runner_pipeline=clean, use_cache=False)
    index = DorsalIndex()
    index.upsert_record(path=target, modified_time=__import__("os").path.getmtime(target), record=made.model)

    cached = LocalFile(target, model_runner_pipeline=clean)

    assert cached._source == "cache"
    assert cached.number_changes == []
    assert all(is_numbers_checked(item) for item in cached.model.annotations.__pydantic_extra__["open/generic"])


def test_a_cached_record_is_trusted_at_push(target):
    LocalFile(target, model_runner_pipeline=PIPELINE)
    cached = LocalFile(target, model_runner_pipeline=PIPELINE)

    assert all(is_numbers_checked(item) for item in cached.model.annotations.__pydantic_extra__["open/generic"])


@pytest.mark.parametrize("make", ["scan_file", "scan_directory", "collection"])
def test_python_entry_points_take_strict_mode(data_dir, target, make, pipeline_config):
    if make == "scan_file":
        files = [scan_file(target, use_cache=False, on_bad_number="raise")]
    elif make == "scan_directory":
        files = scan_directory(str(data_dir), use_cache=False, on_bad_number="raise")
    else:
        files = list(LocalFileCollection(str(data_dir), use_cache=False, offline=True, on_bad_number="raise"))

    assert files
    for local_file in files:
        assert local_file.on_bad_number == "raise"
        assert _oats(local_file) == set()
        assert _changes(local_file) == RAISE_CHANGES


@pytest.mark.parametrize("make", ["scan_file", "scan_directory"])
def test_python_entry_points_default_to_drop(data_dir, target, make, pipeline_config):
    files = (
        [scan_file(target, use_cache=False)] if make == "scan_file" else scan_directory(str(data_dir), use_cache=False)
    )

    for local_file in files:
        assert _changes(local_file) == DROP_CHANGES


def test_testing_run_model_takes_strict_mode(target):
    [result] = dorsal.testing.run_model(LlmBad, target, schema_id="llm-output", on_bad_number="raise")

    assert result.records is None
    assert result.rejected == "… is outside the bounds of this field at /score"
    assert result.error and "outside the bounds" in result.error

    [result] = dorsal.testing.run_model(LlmBad, target, schema_id="llm-output")
    assert [item.path for item in result.dropped] == [["score"]]
    assert result.rejected is None


def test_a_bad_number_in_a_list_is_reported_as_a_rejection_in_drop_mode(target, mocker):
    mocker.patch.object(GenericBad, "main", return_value={"data": {"values": [1, float("nan")]}})

    local_file = LocalFile(target, model_runner_pipeline=[_step("GenericBad", "generic")], use_cache=False)

    [change] = local_file.number_changes
    assert change.rejected == "… is not a finite number at /data/values/1"
    assert _oats(local_file) == set()


def test_a_schema_error_is_not_reported_as_a_rejection(target, mocker):
    mocker.patch.object(GenericBad, "main", return_value={"data": 5})

    local_file = LocalFile(target, model_runner_pipeline=[_step("GenericBad", "generic")], use_cache=False)

    assert local_file.number_changes == []


@pytest.fixture
def client() -> DorsalClient:
    return DorsalClient(api_key="x" * 40, base_url=BASE_URL)


@pytest.fixture
def hub(requests_mock):
    requests_mock.post(f"{BASE_URL}/v1/files/private", json=HUB_OK, status_code=201)
    requests_mock.post(f"{BASE_URL}/v1/files/public", json=HUB_OK, status_code=201)
    return requests_mock


def test_push_returns_the_number_changes(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=PIPELINE, use_cache=False)

    response = local_file.push()

    assert [(c.schema_id, c.source_id) for c in response.number_changes] == [
        ("open/llm-output", "acme/llm"),
        ("open/generic", "acme/generic"),
    ]
    assert "number_changes" not in response.model_dump()
    assert len(hub.request_history) == 1


def test_api_index_file_returns_the_number_changes(target, client, hub, mocker, pipeline_config):
    mocker.patch("dorsal.file.dorsal_file.get_shared_dorsal_client", return_value=client)

    response = index_file(target, use_cache=False)

    assert [(c.schema_id, c.source_id) for c in response.number_changes] == [
        ("open/llm-output", "acme/llm"),
        ("open/generic", "acme/generic"),
    ]


def test_api_index_file_takes_strict_mode(target, client, hub, mocker, pipeline_config):
    mocker.patch("dorsal.file.dorsal_file.get_shared_dorsal_client", return_value=client)

    response = index_file(target, use_cache=False, on_bad_number="raise")

    assert [change.rejected is not None for change in response.number_changes] == [True, True]
    sent = hub.request_history[0].json()
    assert not any(key.startswith("open/") for key in sent[0]["annotations"])


@pytest.mark.parametrize("use_cache", [False, True])
def test_reader_index_file_returns_the_number_changes(target, client, hub, use_cache):
    reader = MetadataReader(client=client, model_config=PIPELINE)
    if use_cache:
        reader.index_file(target)

    response = reader.index_file(target, skip_cache=not use_cache)

    assert [(c.schema_id, c.source_id) for c in response.number_changes] == [
        ("open/llm-output", "acme/llm"),
        ("open/generic", "acme/generic"),
    ]


def test_push_checks_a_record_loaded_from_json(target, client, hub, tmp_path):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 1}}, source="me")
    data = json.loads(local_file.to_json())
    data["annotations"]["open/generic"][0]["record"] = {"data": {"x": 2**60}}
    saved = tmp_path / "record.json"
    saved.write_text(json.dumps(data))

    loaded = LocalFile.from_json(saved)
    loaded._client = client

    with pytest.raises(RejectedAnnotationError) as err:
        loaded.push()
    assert err.value.problems[0]["schema"] == "generic"
    assert err.value.problems[0]["reason"] == "… is outside ±9007199254740991"
    assert hub.request_history == []


def test_push_accepts_a_clean_record_loaded_from_json(target, client, hub, tmp_path):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 1}}, source="me")
    saved = tmp_path / "record.json"
    saved.write_text(local_file.to_json())

    loaded = LocalFile.from_json(saved)
    loaded._client = client
    loaded.push()

    assert len(hub.request_history) == 1
    assert all(is_numbers_checked(item) for item in loaded.model.annotations.__pydantic_extra__["open/generic"])


def test_push_refuses_a_forced_record_with_a_bad_number(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 2**60}}, source="me", force=True)
    assert local_file.get_annotations("generic")[0].schema_version is None

    with pytest.raises(UnversionedAnnotationError):
        local_file.push()
    assert hub.request_history == []


def _hand_built(local_file, record: dict[str, Any], schema_id: str = "open/generic"):
    model = local_file.model.model_dump()
    model["annotations"][schema_id] = [
        {"record": record, "source": SOURCE, "schema_id": schema_id, "schema_version": "0.8.0"}
    ]
    return type(local_file.model).model_validate(model)


def test_push_refuses_a_forced_record_stamped_with_a_bad_number(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 2**60}}, source="me", force=True, schema_version="0.8.0")
    assert local_file.get_annotations("generic")[0].schema_version == "0.8.0"

    with pytest.raises(RejectedAnnotationError) as err:
        local_file.push()
    assert err.value.problems[0]["model"] == "me"
    assert hub.request_history == []


def test_push_sends_the_checked_form_of_a_record_loaded_from_json(target, client, hub, tmp_path):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.add_annotation("llm-output", {"model": "m", "response_data": "hi"}, source="me", schema_version="0.9.0")
    data = json.loads(local_file.to_json())
    data["annotations"]["open/llm-output"][0]["record"]["generation_params"] = {"seed": 5, "temperature": -0.0}
    saved = tmp_path / "record.json"
    saved.write_text(json.dumps(data))
    loaded = LocalFile.from_json(saved)
    loaded._client = client

    loaded.push()

    sent = hub.request_history[0].json()[0]["annotations"]["open/llm-output"][0]
    assert sent["schema_version"] == "0.9.0"
    assert sent["record"]["generation_params"] == {"seed": "5", "temperature": 0.0}


def test_a_heavy_push_does_not_check_numbers_again(target, client, hub, mocker):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    blocks = [{"text": "word " * 50, "block_type": "text"} for _ in range(200)]
    local_file.add_annotation("document-extraction", {"blocks": blocks, "producer": "x"}, source="me")
    hub.post(
        re.compile(f"{BASE_URL}/v1/files/[0-9a-f]+/.*"),
        json={"total": 1, "success": 1, "error": 0, "results": []},
        status_code=201,
    )
    mocker.patch.object(constants, "API_MAX_RECORD_SIZE_BYTES", 2000)
    mocker.patch.object(constants, "API_RECORD_HEADROOM_BYTES", 0)
    spy = mocker.spy(oatschema, "check_numbers")

    local_file.push()

    assert spy.call_count == 0
    assert len(hub.request_history) == 2


def test_push_does_not_check_numbers_dorsal_already_checked(target, client, hub, mocker):
    local_file = LocalFile(target, client=client, model_runner_pipeline=PIPELINE, use_cache=False)
    local_file.add_annotation("generic", {"data": {"x": 1}}, source="me")
    spy = mocker.spy(oatschema, "check_numbers")

    local_file.push()

    assert spy.call_count == 0
    assert len(hub.request_history) == 1


def test_client_refuses_a_hand_built_record(target, client, hub):
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    record = _hand_built(local_file, {"model": "m", "response_data": "hi", "score": 7.0}, "open/llm-output")

    with pytest.raises(RejectedAnnotationError):
        client.index_private_file_records(file_records=[record])
    assert hub.request_history == []


def test_client_refuses_a_hand_built_annotation(target, client, requests_mock):
    from dorsal.file.validators.file_record import Annotation

    annotation = Annotation(
        record={"data": {"x": 2**60}}, source=SOURCE, schema_id="open/generic", schema_version="0.8.0"
    )

    with pytest.raises(RejectedAnnotationError):
        client.add_file_annotation(file_hash="a" * 64, schema_id="generic", annotation=annotation)
    assert requests_mock.request_history == []


def test_push_checks_a_hand_built_sharded_group(target, client):
    blocks = [{"text": "word " * 800, "block_type": "text"} for _ in range(600)]
    blocks[0]["page_number"] = 2**60
    group = build_annotation_or_annotationgroup(
        schema_id="document-extraction",
        record_data={"blocks": blocks, "producer": "x"},
        source=SOURCE,
        schema_version="0.8.0",
    )
    assert isinstance(group, AnnotationGroup)
    local_file = LocalFile(target, client=client, model_runner_pipeline=[], use_cache=False)
    local_file.model.annotations.__pydantic_extra__["open/document-extraction"] = [group]

    with pytest.raises(RejectedAnnotationError) as err:
        check_record_schema_versions([local_file.model])
    assert err.value.problems[0]["reason"] == "… is outside ±9007199254740991"


def test_the_override_dir_skips_the_push_check(target, tmp_path, monkeypatch):
    record = _hand_built(LocalFile(target, model_runner_pipeline=[], use_cache=False), {"data": {"x": 2**60}})
    with pytest.raises(RejectedAnnotationError):
        check_record_schema_versions([record])

    monkeypatch.setenv("DORSAL_OPEN_VALIDATION_SCHEMAS_DIR", str(tmp_path))
    check_record_schema_versions([record])


def _cli(*args: str):
    from dorsal.cli import app

    with warnings.catch_warnings():
        return CliRunner().invoke(app, list(args))


def _report_lines(stderr: str) -> list[str]:
    return [line.strip() for line in stderr.splitlines() if line.strip()]


@pytest.mark.parametrize("command", [["index", "build"], ["scan"], ["push", "--dry-run"]])
def test_cli_silences_the_raw_dropped_number_warning(data_dir, pipeline_config, recwarn, command):
    result = _cli(*command, str(data_dir), "--deep" if command[0] != "push" else "--skip-cache")

    assert result.exit_code == 0, result.output
    assert "dropped 7.0 at /score" in result.stderr
    assert not [w for w in recwarn if issubclass(w.category, oatschema.DroppedNumberWarning)]


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_cli_index_build_reports_every_change(data_dir, pipeline_config, json_flag):
    result = _cli("index", "build", str(data_dir), "--deep", *json_flag)

    assert result.exit_code == 0, result.output
    report = " ".join(_report_lines(result.stderr))
    for name in ("a.txt", "b.txt"):
        assert f"{data_dir / name}: open/generic from acme/generic" in report
    assert report.count("dropped 1152921504606846976 at /data/bad") == 2
    assert report.count("converted -0.0 to 0.0 at /generation_params/temperature") == 2
    if json_flag:
        data = json.loads(result.stdout)
        assert sorted(data["number_changes"]) == [str(data_dir / "a.txt"), str(data_dir / "b.txt")]


def test_cli_scan_reports_changes_from_the_index(data_dir, pipeline_config):
    _cli("index", "build", str(data_dir), "--deep")

    result = _cli("scan", str(data_dir / "b.txt"), "--deep", "--json", "--use-cache")

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source"] == "cache"
    assert [change["source_id"] for change in data["number_changes"]] == ["acme/llm", "acme/generic"]


@pytest.mark.parametrize("command", [["scan"], ["index", "build"]])
@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_cli_strict_mode_reports_rejections(data_dir, pipeline_config, command, json_flag):
    result = _cli(*command, str(data_dir), "--deep", "--on-bad-number", "raise", *json_flag)

    assert result.exit_code == 0, result.output
    report = " ".join(_report_lines(result.stderr))
    assert report.count("rejected the record: … is outside the bounds of this field at /score") == 2
    assert "dropped" not in report
    if json_flag:
        changes = json.loads(result.stdout)["number_changes"][str(data_dir / "a.txt")]
        assert [change["rejected"] is not None for change in changes] == [True, True]


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_cli_push_dry_run_shows_what_would_be_dropped(data_dir, pipeline_config, json_flag):
    result = _cli("push", str(data_dir), "--dry-run", "--skip-cache", *json_flag)

    assert result.exit_code == 0, result.output
    report = " ".join(_report_lines(result.stderr))
    assert report.count("dropped 7.0 at /score") == 2
    if json_flag:
        data = json.loads(result.stdout)
        assert data["dry_run"] is True and data["total_files"] == 2
        assert sorted(data["number_changes"]) == [str(data_dir / "a.txt"), str(data_dir / "b.txt")]
    else:
        assert "Would push 2 file(s)" in result.stdout


@pytest.fixture
def online_config(mocker, data_dir, monkeypatch, requests_mock):
    monkeypatch.setenv("DORSAL_API_KEY", "x" * 40)
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": PIPELINE}, data_dir))
    return requests_mock


def test_cli_push_strict_mode_sends_no_rejected_record(data_dir, online_config):
    online_config.post(f"{DORSAL_API_URL}/v1/files/private", json=HUB_OK, status_code=201)

    result = _cli("push", str(data_dir / "a.txt"), "--skip-cache", "--on-bad-number", "raise", "--json")

    assert result.exit_code == 0, result.output
    assert "rejected the record" in result.stderr
    [request] = online_config.request_history
    assert not any(key.startswith("open/") for key in request.json()[0]["annotations"])
    assert [change["rejected"] is not None for change in json.loads(result.stdout)["number_changes"]] == [True, True]
