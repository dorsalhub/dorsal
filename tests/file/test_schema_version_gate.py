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

import json
import warnings
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

from dorsal.client import DorsalClient
from dorsal.file import schemas
from dorsal.file.validators import open_schema
from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.exceptions import UnversionedAnnotationError
from dorsal.common.model import AnnotationModel
from dorsal.file.collection.local import LocalFileCollection
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.file_annotator import FILE_ANNOTATOR
from dorsal.file.integrity import check_annotation_schema_version, check_record_schema_versions
from dorsal.file.metadata_reader import MetadataReader
from dorsal.file.model_runner import ModelRunner, run_model
from dorsal.file.sharding import build_annotation_or_annotationgroup
from dorsal.file.validators.file_record import Annotation, AnnotationGroup
from dorsal.file.validators.open_schema import get_open_schema_validator

BASE_URL = "https://api.example.com"
VALID_RECORD = {"labels": [{"label": "a"}]}
INVALID_RECORD = {"not_oats": 1}
VERSION = OPEN_VALIDATION_SCHEMAS_VER
SOURCE = {
    "type": "Model",
    "id": "acme/classifier",
    "version": "1.0.0",
    "execution_id": "23456781-1234-5678-1234-567812345678",
}
LARGE_RECORD = {"blocks": [{"text": "word " * 20_000, "block_type": "text"} for _ in range(30)], "producer": "x"}
HUB_OK = {"total": 1, "success": 1, "error": 0, "unauthorized": 0, "results": []}


class ValidModel(AnnotationModel):
    id = "acme/valid"
    version = "1.0.0"

    def main(self) -> dict[str, Any]:
        return VALID_RECORD


class InvalidModel(AnnotationModel):
    id = "acme/invalid"
    version = "1.0.0"

    def main(self) -> dict[str, Any]:
        return INVALID_RECORD


class LargeModel(AnnotationModel):
    id = "acme/large"
    version = "1.0.0"

    def main(self) -> dict[str, Any]:
        return LARGE_RECORD


class AnyRecord(BaseModel):
    model_config = ConfigDict(extra="allow")


def _path(name: str) -> dict[str, str]:
    return {"module": __name__, "name": name}


BUILT_IN = {"module": "dorsal.file.validators.open_schema", "name": "classification_validator"}


def _step(model: str = "ValidModel", **overrides: Any) -> dict[str, Any]:
    return {"annotation_model": _path(model), "schema_id": "classification", **overrides}


@pytest.fixture
def client() -> DorsalClient:
    return DorsalClient(api_key="x" * 40, base_url=BASE_URL)


@pytest.fixture
def hub(requests_mock):
    requests_mock.post(f"{BASE_URL}/v1/files/private", json=HUB_OK, status_code=201)
    requests_mock.post(f"{BASE_URL}/v1/files/public", json=HUB_OK, status_code=201)
    return requests_mock


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("hello")
    return path


def _local_file(target, client, *steps) -> LocalFile:
    return LocalFile(str(target), client=client, model_runner_pipeline=list(steps), use_cache=False)


def _oats_annotations(local_file: LocalFile, schema_id: str = "open/classification") -> list[Annotation]:
    return local_file.model.annotations.__pydantic_extra__[schema_id]


def _record_with(local_file: LocalFile, schema_version: str | None, schema_id: str = "open/classification"):
    record = local_file.model.model_copy(deep=True)
    extra = record.annotations.__pydantic_extra__
    extra[schema_id] = [
        Annotation(record=VALID_RECORD, source=SOURCE, schema_id=schema_id, schema_version=schema_version)
    ]
    return record


@pytest.fixture
def bare_record(target, client):
    return _local_file(target, client).model


@pytest.mark.parametrize("schema_version", [None, "", " ", "latest", "published", "LATEST", "Published"])
@pytest.mark.parametrize("schema_id", ["classification", "oats/classification", "open/classification"])
def test_gate_refuses_unusable_versions_for_every_id_form(bare_record, schema_id, schema_version):
    record = bare_record.model_copy(deep=True)
    annotation = Annotation(record=VALID_RECORD, source=SOURCE, schema_id=schema_id, schema_version=schema_version)
    record.annotations.__pydantic_extra__[schema_id] = [annotation]

    with pytest.raises(UnversionedAnnotationError) as err:
        check_record_schema_versions([record])

    assert err.value.problems[0]["schema"] == "classification"
    with pytest.raises(UnversionedAnnotationError):
        check_annotation_schema_version(schema_id=schema_id, annotation=annotation, file_label="f")


@pytest.mark.parametrize("schema_id", ["acme/own-dataset", "dorsal/arxiv", "file/custom"])
@pytest.mark.parametrize("schema_version", [None, "latest"])
def test_gate_leaves_other_schemas_alone(bare_record, schema_id, schema_version):
    record = bare_record.model_copy(deep=True)
    annotation = Annotation(record=VALID_RECORD, source=SOURCE, schema_id=schema_id, schema_version=schema_version)
    record.annotations.__pydantic_extra__[schema_id] = [annotation]

    check_record_schema_versions([record])
    check_annotation_schema_version(schema_id=schema_id, annotation=annotation, file_label="f")


def test_gate_accepts_an_exact_version(bare_record):
    record = bare_record.model_copy(deep=True)
    record.annotations.__pydantic_extra__["open/classification"] = [
        Annotation(record=VALID_RECORD, source=SOURCE, schema_id="open/classification", schema_version=VERSION)
    ]
    check_record_schema_versions([record])


def test_gate_uses_the_annotation_schema_id_when_the_key_is_not_oats(bare_record):
    record = bare_record.model_copy(deep=True)
    record.annotations.__pydantic_extra__["acme/own-dataset"] = [
        Annotation(record=VALID_RECORD, source=SOURCE, schema_id="classification", schema_version=None)
    ]
    with pytest.raises(UnversionedAnnotationError):
        check_record_schema_versions([record])


def test_gate_refuses_a_sharded_group_once(bare_record):
    record = bare_record.model_copy(deep=True)
    group = build_annotation_or_annotationgroup(
        schema_id="document-extraction",
        record_data=LARGE_RECORD,
        source=SOURCE,
        schema_version=None,
    )
    assert isinstance(group, AnnotationGroup)
    record.annotations.__pydantic_extra__["open/document-extraction"] = [group]

    with pytest.raises(UnversionedAnnotationError) as err:
        check_record_schema_versions([record])
    assert len(err.value.problems) == 1

    stamped = group.model_copy(deep=True)
    for chunk in stamped.annotations:
        chunk.schema_version = VERSION
    record.annotations.__pydantic_extra__["open/document-extraction"] = [stamped]
    check_record_schema_versions([record])


def test_pipeline_output_that_shards_is_refused(target, client, hub):
    step = _step(model="LargeModel", schema_id="document-extraction", validation_model=_path("AnyRecord"))
    local_file = _local_file(target, client, step)
    assert isinstance(_oats_annotations(local_file, "open/document-extraction")[0], AnnotationGroup)

    with pytest.raises(UnversionedAnnotationError) as err:
        local_file.push()
    assert len(err.value.problems) == 1
    assert hub.request_history == []


def test_error_names_schema_model_file_and_fix(target, client):
    local_file = _local_file(target, client, _step(validation_model=_path("AnyRecord")))
    with pytest.raises(UnversionedAnnotationError) as err:
        local_file.push()

    message = str(err.value)
    assert "Nothing was pushed" in message
    assert "'classification'" in message
    assert "'acme/valid'" in message
    assert str(target) in message
    assert "schema_version: missing" in message
    assert f'"{VERSION}"' in message
    assert "model_config.toml" in message
    assert "--overwrite-cache" in message
    assert isinstance(err.value, ValueError)


def test_error_bounds_its_listing_and_keeps_every_problem():
    problems = [
        {"file": f"f{i}", "schema": "generic", "model": "m", "schema_version": None}
        for i in range(UnversionedAnnotationError.MAX_LISTED + 5)
    ]
    err = UnversionedAnnotationError(problems)
    assert "and 5 more" in str(err)
    assert "f14" not in str(err)
    assert len(err.problems) == len(problems)


def test_client_index_refuses_before_network(target, client, hub):
    local_file = _local_file(target, client)
    record = _record_with(local_file, None)

    for call in (client.index_private_file_records, client.index_public_file_records):
        with pytest.raises(UnversionedAnnotationError):
            call([record])
        with pytest.raises(UnversionedAnnotationError):
            call([record.model_dump(mode="json", by_alias=True, exclude_none=True)])

    assert hub.request_history == []
    client.index_private_file_records([_record_with(local_file, VERSION)])
    assert len(hub.request_history) == 1


@pytest.mark.parametrize("schema_id", ["classification", "oats/classification"])
def test_client_add_file_annotation_refuses_before_network(client, requests_mock, schema_id):
    single = Annotation(record=VALID_RECORD, source=SOURCE, schema_id=schema_id)
    group = AnnotationGroup(annotations=[single])

    for annotation in (single, group):
        with pytest.raises(UnversionedAnnotationError):
            client.add_file_annotation(file_hash="a" * 64, schema_id=schema_id, annotation=annotation)
    assert requests_mock.request_history == []


def test_local_file_push_refuses_before_network(target, client, hub):
    local_file = _local_file(target, client, _step())
    assert _oats_annotations(local_file)[0].schema_version is None

    for public in (False, True):
        with pytest.raises(UnversionedAnnotationError):
            local_file.push(public=public)
    assert hub.request_history == []


def test_heavy_push_refuses_before_the_lite_record_is_sent(target, client, hub, mocker):
    local_file = _local_file(target, client, _step())
    mocker.patch("dorsal.common.constants.API_MAX_RECORD_SIZE_BYTES", 1)
    heavy = mocker.spy(local_file, "_push_heavy")

    with pytest.raises(UnversionedAnnotationError):
        local_file.push()

    heavy.assert_not_called()
    assert hub.request_history == []


@pytest.mark.parametrize("fail_fast", [True, False])
def test_upload_records_refuses_the_whole_batch_and_lists_every_file(target, client, hub, fail_fast):
    good = _local_file(target, client, _step(validation_model=BUILT_IN))
    bad_a = _local_file(target, client, _step())
    other = target.with_name("other.txt")
    other.write_text("other")
    bad_b = _local_file(other, client, _step(model="ValidModel", validation_model=_path("AnyRecord")))
    reader = MetadataReader(client=client, model_config=[])

    with pytest.raises(UnversionedAnnotationError) as err:
        reader.upload_records(
            [good.model, bad_a.model, bad_b.model],
            fail_fast=fail_fast,
            hash_to_path_map={bad_a.model.hash: str(target), bad_b.model.hash: str(other)},
            show_progress=False,
        )

    assert {problem["file"] for problem in err.value.problems} == {str(target), str(other)}
    assert hub.request_history == []


def test_reader_index_file_refuses_before_network(target, client, hub):
    reader = MetadataReader(client=client, model_config=[_step()])
    with pytest.raises(UnversionedAnnotationError) as err:
        reader.index_file(str(target), skip_cache=True)
    assert err.value.problems[0]["file"] == str(target)
    assert hub.request_history == []


def test_reader_index_directory_refuses_before_network(target, client, hub):
    reader = MetadataReader(client=client, model_config=[_step()])
    with pytest.raises(UnversionedAnnotationError):
        reader.index_directory(str(target.parent), skip_cache=True, show_progress=False)
    assert hub.request_history == []


def test_collection_push_and_publish_refuse_before_network(target, client, hub):
    local_file = _local_file(target, client, _step())
    collection = LocalFileCollection(source=[local_file], client=client, use_cache=False)

    with pytest.raises(UnversionedAnnotationError):
        collection.push()
    with pytest.raises(UnversionedAnnotationError):
        collection.create_remote_collection(name="c", public=False)
    assert hub.request_history == []


def test_api_index_file_refuses_before_network(target, client, hub, mocker):
    from dorsal.api.file import index_file

    pipeline_file = LocalFile.__init__

    def patched(self, file_path, **kwargs):
        pipeline_file(self, file_path, client=client, model_runner_pipeline=[_step()], use_cache=False)

    mocker.patch.object(LocalFile, "__init__", patched)
    with pytest.raises(UnversionedAnnotationError):
        index_file(str(target))
    assert hub.request_history == []


def test_saved_record_without_a_version_is_refused_and_not_read_as_old_default(target, client, hub, tmp_path):
    local_file = _local_file(target, client, _step())
    saved = tmp_path / "saved.json"
    local_file.save(str(saved))

    restored = LocalFile.from_json(saved)
    restored._client = client
    with pytest.raises(UnversionedAnnotationError):
        restored.push()
    assert hub.request_history == []
    assert _oats_annotations(restored)[0].schema_version is None


def test_dorsal_toml_pipeline_is_gated(target, client, hub, mocker):
    pipeline = [
        {
            "annotation_model": {"module": __name__, "name": "ValidModel"},
            "schema_id": "classification",
        }
    ]
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": pipeline}, target))
    local_file = LocalFile(str(target), client=client, use_cache=False)
    assert _oats_annotations(local_file)[0].schema_version is None

    with pytest.raises(UnversionedAnnotationError):
        local_file.push()
    assert hub.request_history == []


@pytest.mark.parametrize(
    "step, expected",
    [
        pytest.param({}, None, id="no-validator-no-pin"),
        pytest.param({"validation_model": _path("AnyRecord")}, None, id="pydantic-no-pin"),
        pytest.param({"validation_model": BUILT_IN}, VERSION, id="json-schema-no-pin"),
        pytest.param({"validation_model": BUILT_IN, "schema_version": "0.5.0"}, "0.5.0", id="json-schema-pinned"),
        pytest.param({"schema_version": VERSION}, VERSION, id="no-validator-pinned"),
        pytest.param(
            {"validation_model": _path("AnyRecord"), "schema_version": VERSION}, VERSION, id="pydantic-pinned"
        ),
    ],
)
def test_each_kind_of_validator_with_a_valid_record(target, client, hub, step, expected):
    local_file = _local_file(target, client, _step(**step))
    assert _oats_annotations(local_file)[0].schema_version == expected

    if expected is None:
        with pytest.raises(UnversionedAnnotationError):
            local_file.push()
        assert hub.request_history == []
    else:
        local_file.push()
        body = hub.request_history[0].json()[0]["annotations"]["open/classification"][0]
        assert body["schema_version"] == expected


@pytest.mark.parametrize(
    "step",
    [
        pytest.param({"schema_version": VERSION}, id="no-validator"),
        pytest.param({"validation_model": _path("AnyRecord"), "schema_version": VERSION}, id="pydantic"),
        pytest.param({"validation_model": _path("AnyRecord"), "schema_version": "latest"}, id="pydantic-latest"),
        pytest.param({"schema_version": "9.9.9"}, id="unknown-version"),
    ],
)
def test_pin_is_not_stamped_on_a_record_it_did_not_validate(target, client, hub, step):
    local_file = _local_file(target, client, _step(model="InvalidModel", **step))
    annotation = _oats_annotations(local_file)[0]

    assert annotation.schema_version is None
    assert annotation.record.model_dump() == INVALID_RECORD
    with pytest.raises(UnversionedAnnotationError):
        local_file.push()
    assert hub.request_history == []


@pytest.mark.parametrize(
    "model, declared, pin, expected",
    [
        pytest.param("ValidModel", VERSION, None, VERSION, id="declares-a-version-it-holds"),
        pytest.param("InvalidModel", VERSION, None, None, id="declares-a-version-the-record-fails"),
        pytest.param("ValidModel", "3.1.0", None, None, id="declares-a-version-that-does-not-exist"),
        pytest.param("ValidModel", None, VERSION, VERSION, id="no-declared-version-uses-the-pin"),
        pytest.param("InvalidModel", None, VERSION, None, id="no-declared-version-pin-fails"),
    ],
)
def test_custom_json_schema_validator_on_an_oats_id(target, client, model, declared, pin, expected):
    schema: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    if declared:
        schema["x-version"] = declared
    step = _step(model=model, validation_model=schema)
    if pin:
        step["schema_version"] = pin
    local_file = _local_file(target, client, step)
    assert _oats_annotations(local_file)[0].schema_version == expected


def test_custom_json_schema_validator_on_another_schema_keeps_its_version(target, client):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "x-version": "3.1.0"}
    step = _step(schema_id="acme/own-dataset", validation_model=schema, schema_version="9.0.0")
    local_file = _local_file(target, client, step)
    assert _oats_annotations(local_file, "acme/own-dataset")[0].schema_version == "3.1.0"


def test_schema_dir_override_does_not_stamp_a_version_it_does_not_hold(target, client, tmp_path, monkeypatch):
    from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR
    from dorsal.file.schemas import get_open_schema

    override = tmp_path / "schemas"
    override.mkdir()
    (override / "classification.json").write_text(json.dumps(get_open_schema("classification", VERSION)))
    monkeypatch.setenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR, str(override))
    open_schema._build_and_cache_validator.cache_clear()
    schemas._load_schema_from_package.cache_clear()
    try:
        assert open_schema.verified_open_schema_version("classification", "9.9.9", VALID_RECORD) is None
    finally:
        monkeypatch.delenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR)
        open_schema._build_and_cache_validator.cache_clear()
        schemas._load_schema_from_package.cache_clear()


@pytest.mark.parametrize(
    "schema_id", ["open/not-yet-known", "oats/not-yet-known", "OPEN/classification", "open/Classification"]
)
def test_gate_catches_oats_prefixed_ids_this_dorsal_does_not_know(bare_record, schema_id):
    record = bare_record.model_copy(deep=True)
    record.annotations.__pydantic_extra__[schema_id] = [
        Annotation(record=VALID_RECORD, source=SOURCE, schema_id=schema_id, schema_version=None)
    ]
    with pytest.raises(UnversionedAnnotationError):
        check_record_schema_versions([record])


def test_custom_json_schema_validator_with_no_version_is_refused(target, client, hub):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    local_file = _local_file(target, client, _step(validation_model=schema))
    with pytest.raises(UnversionedAnnotationError):
        local_file.push()
    assert hub.request_history == []


def test_oats_validation_at_the_pin_runs_only_without_a_json_schema_validator(target, client, mocker):
    spy = mocker.spy(open_schema, "verified_open_schema_version")
    _local_file(target, client, _step(validation_model=BUILT_IN, schema_version=VERSION))
    assert not [call for call in spy.call_args_list if call.args[0] == "open/classification"]


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        pytest.param({"force": True}, None, id="force-no-version"),
        pytest.param({"force": True, "schema_version": VERSION}, VERSION, id="force-valid"),
    ],
)
def test_add_annotation_force_with_a_valid_record(target, client, hub, kwargs, expected):
    local_file = _local_file(target, client)
    local_file.add_annotation("classification", VALID_RECORD, **kwargs)
    assert _oats_annotations(local_file)[0].schema_version == expected


def test_add_annotation_force_does_not_stamp_an_invalid_record(target, client, hub):
    local_file = _local_file(target, client)
    local_file.add_annotation("classification", INVALID_RECORD, schema_version=VERSION, force=True)

    assert _oats_annotations(local_file)[0].schema_version is None
    with pytest.raises(UnversionedAnnotationError):
        local_file.push()
    assert hub.request_history == []


def test_add_annotation_without_force_pushes_the_validated_version(target, client, hub):
    local_file = _local_file(target, client)
    local_file.add_annotation("classification", VALID_RECORD, schema_version="0.5.0")
    assert _oats_annotations(local_file)[0].schema_version == "0.5.0"
    local_file.push()
    assert len(hub.request_history) == 1


def test_manual_annotation_with_an_explicit_validator_uses_the_validator_version():
    annotations = FILE_ANNOTATOR.make_manual_annotation(
        annotation=VALID_RECORD,
        schema_id="classification",
        schema_version="0.5.0",
        source_id="s",
        validator=get_open_schema_validator("classification", VERSION),
        private=None,
    )
    assert annotations[0].schema_version == VERSION


@pytest.mark.parametrize(
    "validator, requested, expected",
    [
        pytest.param(get_open_schema_validator("classification", VERSION), None, VERSION, id="json-schema"),
        pytest.param(AnyRecord, None, None, id="pydantic"),
        pytest.param(AnyRecord, VERSION, VERSION, id="pydantic-requested"),
        pytest.param(None, None, None, id="none"),
        pytest.param(None, VERSION, VERSION, id="none-requested"),
    ],
)
def test_annotator_records_the_version_validated_against(target, validator, requested, expected):
    annotations = FILE_ANNOTATOR.annotate_file_using_model_and_validator(
        file_path=str(target),
        model_runner=ModelRunner(pipeline_config=[]),
        annotation_model_cls=ValidModel,
        schema_id="classification",
        schema_version=requested,
        private=None,
        validation_model=validator,
    )
    assert annotations[0].schema_version == expected


def test_annotator_pipeline_step_applies_the_pin_only_if_it_holds(target):
    def annotate(model: str) -> Annotation:
        return FILE_ANNOTATOR.annotate_file_using_pipeline_step(
            file_path=str(target),
            model_runner=ModelRunner(pipeline_config=[]),
            pipeline_step=_step(model=model, schema_version=VERSION),
            private=None,
        )[0]

    assert annotate("ValidModel").schema_version == VERSION
    assert annotate("InvalidModel").schema_version is None


def test_annotator_leaves_other_schemas_as_they_were(target):
    annotation = FILE_ANNOTATOR.annotate_file_using_model_and_validator(
        file_path=str(target),
        model_runner=ModelRunner(pipeline_config=[]),
        annotation_model_cls=ValidModel,
        schema_id="acme/own-dataset",
        schema_version="2.0.0",
        private=None,
    )[0]
    assert annotation.schema_version == "2.0.0"


def test_run_model_is_unchanged_with_no_push(target):
    default = run_model(ValidModel, str(target), schema_id="classification")[0]
    assert (default.error, default.schema_version, default.records) == (None, VERSION, [VALID_RECORD])

    pinned = run_model(ValidModel, str(target), schema_id="classification", schema_version="0.5.0")[0]
    assert (pinned.error, pinned.schema_version) == (None, "0.5.0")

    invalid = run_model(InvalidModel, str(target), schema_id="classification")[0]
    assert invalid.records is None
    assert invalid.error

    other = run_model(ValidModel, str(target), schema_id="acme/own", validation_model=AnyRecord)[0]
    assert (other.error, other.schema_version) == (None, VERSION)

    no_schema = run_model(ValidModel, str(target))[0]
    assert no_schema.records == [VALID_RECORD]


def test_export_record_is_unchanged():
    from dorsal.api.adapters import export_record

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        output = export_record({"text": "hi", "language": "eng"}, "audio-transcription", "txt", schema_version=VERSION)
    assert "hi" in output


def test_scan_without_push_keeps_running_with_no_version(target, client, hub):
    runner = ModelRunner(pipeline_config=[_step()])
    record = runner.run(str(target))
    annotation = record.annotations.__pydantic_extra__["open/classification"][0]
    assert annotation.record.model_dump() == VALID_RECORD
    assert annotation.schema_version is None
    assert hub.request_history == []


def _cli_app():
    from dorsal.cli import app

    return app


@pytest.fixture
def unpinned_config(target, requests_mock, mocker, monkeypatch):
    monkeypatch.setenv("DORSAL_API_KEY", "x" * 40)
    pipeline = [{"annotation_model": _path("ValidModel"), "schema_id": "classification"}]
    mocker.patch("dorsal.common.config.load_config", return_value=({"model_pipeline": pipeline}, target))
    return requests_mock


@pytest.mark.parametrize("extra", [[], ["--json"], ["--strict"]])
def test_cli_file_push_refuses_through_the_real_gate(target, unpinned_config, extra):
    result = CliRunner().invoke(_cli_app(), ["local", "push", str(target), "--skip-cache", *extra])

    assert result.exit_code == 1
    assert "Nothing was pushed" in result.stderr
    assert "acme/valid" in result.stderr
    assert "unexpected" not in result.stderr
    assert result.stdout == ""
    assert not any(ord(char) > 0x2FFF for char in result.stderr)
    assert unpinned_config.request_history == []


@pytest.mark.parametrize("extra", [[], ["--json"], ["--no-fail-fast"], ["--create-collection", "--name", "c"]])
def test_cli_directory_push_refuses_through_the_real_gate(target, unpinned_config, extra):
    result = CliRunner().invoke(_cli_app(), ["local", "push", str(target.parent), "--skip-cache", *extra])

    assert result.exit_code == 1
    assert "Nothing was pushed" in result.stderr
    assert "unexpected" not in result.stderr
    assert unpinned_config.request_history == []
