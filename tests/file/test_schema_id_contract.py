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
import warnings
from typing import Any
from unittest.mock import MagicMock, patch

import oatschema
import pytest

from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.model import AnnotationModel
from dorsal.file.schemas import (
    deprecated_schema_id_message,
    get_open_schema,
    is_deprecated_schema_id,
    normalize_schema_id,
    open_schema_name,
    resolve_schema_id,
)

GENERIC_RECORD = {"data": {"pages": 3, "title": "Hello"}}


class GenericModel(AnnotationModel):
    id = "test/generic"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        return dict(GENERIC_RECORD)


class TrackIdModel(AnnotationModel):
    id = "test/track-id"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        return {"text": "hi", "language": "eng", "track_id": 1}


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("hello world", encoding="utf-8")
    return str(path)


@pytest.fixture
def no_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


def _deprecated(schema_name: str):
    return pytest.warns(DeprecationWarning, match=f"'open/{schema_name}' is deprecated.*use '{schema_name}'")


def test_default_version_is_an_explicit_0_8_0():
    assert OPEN_VALIDATION_SCHEMAS_VER == "0.8.0"
    assert OPEN_VALIDATION_SCHEMAS_VER in oatschema.available_versions()


@pytest.mark.parametrize(
    "schema_id, name, deprecated, normalized",
    [
        ("generic", "generic", False, "open/generic"),
        ("open/generic", "generic", True, "open/generic"),
        ("open/arxiv", None, False, "open/arxiv"),
        ("dorsal/arxiv", None, False, "dorsal/arxiv"),
        ("file/pdf", None, False, "file/pdf"),
        ("temporal-segmentation", "temporal-segmentation", False, "open/temporal-segmentation"),
    ],
)
def test_schema_id_helpers(schema_id, name, deprecated, normalized):
    assert open_schema_name(schema_id) == name
    assert is_deprecated_schema_id(schema_id) is deprecated
    assert normalize_schema_id(schema_id) == normalized


def _public_function(schema_id: str) -> str:
    return resolve_schema_id(schema_id)


def test_resolve_schema_id_warns_only_for_the_deprecated_form(no_warnings):
    assert _public_function("generic") == "open/generic"
    assert _public_function("my-org/books") == "my-org/books"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _public_function("open/generic") == "open/generic"
    assert [str(w.message) for w in caught] == [deprecated_schema_id_message("open/generic")]
    assert caught[0].filename == __file__


def test_get_open_schema_accepts_both_forms():
    with _deprecated("ranking"):
        prefixed = get_open_schema("open/ranking")
    assert prefixed == get_open_schema("ranking")


@pytest.mark.parametrize("runner", ["dorsal.file.model_runner", "dorsal.testing"])
def test_run_model_bare_and_prefixed_are_identical(runner, text_file):
    import importlib

    run_model = importlib.import_module(runner).run_model

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bare = run_model(GenericModel, text_file, schema_id="generic")[-1]
    with _deprecated("generic"):
        prefixed = run_model(GenericModel, text_file, schema_id="open/generic")[-1]

    assert bare.error is None, bare.error
    volatile = {"time_taken": True, "source": {"execution_id"}}
    assert bare.model_dump(exclude=volatile) == prefixed.model_dump(exclude=volatile)
    assert bare.schema_id == "open/generic"
    assert bare.schema_version == OPEN_VALIDATION_SCHEMAS_VER


def test_run_model_validates_at_the_default_version(text_file):
    result = run_model_last(TrackIdModel, text_file, schema_id="audio-transcription")

    assert result.schema_version == "0.8.0"
    assert result.error is not None and "track_id" in result.error


def test_run_model_validates_at_the_callers_version(text_file):
    result = run_model_last(TrackIdModel, text_file, schema_id="audio-transcription", schema_version="0.5.0")

    assert result.error is None, result.error
    assert result.schema_version == "0.5.0"
    assert result.records == [{"text": "hi", "language": "eng", "track_id": 1}]


def run_model_last(model, path, **kwargs):
    from dorsal.file.model_runner import run_model

    return run_model(model, path, **kwargs)[-1]


def _pipeline_step(schema_id: str, schema_version: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {
        "annotation_model": {"module": __name__, "name": "GenericModel"},
        "validation_model": {"module": "dorsal.file.validators.open_schema", "name": "generic_validator"},
        "schema_id": schema_id,
    }
    if schema_version:
        step["schema_version"] = schema_version
    return step


def test_pipeline_step_accepts_bare_names_and_serializes_them():
    from dorsal.file.configs.model_runner import ModelRunnerPipelineStep

    bare = ModelRunnerPipelineStep.model_validate(_pipeline_step("generic"))
    prefixed = ModelRunnerPipelineStep.model_validate(_pipeline_step("open/generic"))

    assert bare == prefixed
    assert bare.schema_id == "open/generic"
    assert bare.model_dump(mode="json")["schema_id"] == "generic"
    assert ModelRunnerPipelineStep.model_validate(bare.model_dump(mode="json")) == bare


def test_pipeline_with_open_prefix_logs_one_warning(caplog):
    from dorsal.file import model_runner as model_runner_module
    from dorsal.file.model_runner import ModelRunner

    model_runner_module._warned_pipeline_schema_ids.clear()
    with caplog.at_level(logging.WARNING, logger="dorsal.file.model_runner"):
        ModelRunner(pipeline_config=[_pipeline_step("open/generic"), _pipeline_step("open/generic")])
        ModelRunner(pipeline_config=[_pipeline_step("generic")])

    messages = [rec.getMessage() for rec in caplog.records if "deprecated" in rec.getMessage()]
    assert len(messages) == 1
    assert "'open/generic' is deprecated" in messages[0] and "use 'generic'" in messages[0]


@pytest.mark.parametrize("schema_id", ["generic", "open/generic"])
def test_pipeline_runs_identically_for_both_forms(schema_id, text_file, mocker):
    from dorsal.common.validators import import_callable
    from dorsal.file.model_runner import ModelRunner

    def _import(path):
        return globals()[path.name] if path.module == __name__ else import_callable(path)

    mocker.patch("dorsal.file.model_runner.import_callable", side_effect=_import)
    record = ModelRunner(pipeline_config=[_pipeline_step(schema_id)]).run(text_file)

    annotation = record.annotations.model_dump()["open/generic"][0]
    assert annotation["record"] == GENERIC_RECORD
    assert annotation["schema_version"] == OPEN_VALIDATION_SCHEMAS_VER


def test_register_model_writes_bare_names(no_warnings):
    from dorsal.api.config import register_model
    from dorsal.common.config import get_writable_toml_doc
    from dorsal.file.pipeline_config import PipelineConfig

    register_model(GenericModel, schema_id="generic", scope="project")

    doc, _ = get_writable_toml_doc("project")
    written = [step["schema_id"] for step in doc["model_pipeline"]]
    assert written[-1] == "generic"
    assert PipelineConfig.get_steps(scope="project")[-1].schema_id == "open/generic"


def test_register_model_with_open_prefix_warns_and_writes_bare_name():
    from dorsal.api.config import register_model
    from dorsal.common.config import get_writable_toml_doc

    with _deprecated("generic"):
        register_model(GenericModel, schema_id="open/generic", scope="project")

    doc, _ = get_writable_toml_doc("project")
    assert doc["model_pipeline"][-1]["schema_id"] == "generic"


@pytest.mark.parametrize(
    "func, args",
    [
        ("dorsal.file.chunking.list_limit", ("{}", "labels")),
        ("dorsal.file.chunking.chunk_record", ({"labels": [{"label": "a"}]}, "{}")),
        ("dorsal.file.chunking.merge_chunked_records", ([{"labels": [1]}, {"labels": [2]}], "{}")),
        ("dorsal.file.sharding.process_record_for_sharding", ("{}", {"labels": [{"label": "a"}]})),
    ],
)
def test_record_helpers_bare_and_prefixed_are_identical(func, args):
    import importlib

    module_name, name = func.rsplit(".", 1)
    function = getattr(importlib.import_module(module_name), name)

    def call(schema_id):
        return function(*[schema_id if arg == "{}" else arg for arg in args])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bare = call("classification")
    with _deprecated("classification"):
        prefixed = call("open/classification")
    assert bare == prefixed


def test_merge_chunked_records_uses_the_strategy_for_bare_names():
    from dorsal.file.chunking import merge_chunked_records

    merged = merge_chunked_records([{"labels": [1]}, {"labels": [2]}], "classification")

    assert merged["labels"] == [1, 2]


def test_build_annotation_stores_the_dataset_id():
    from dorsal.file.sharding import build_annotation_or_annotationgroup

    source = {"type": "Model", "id": "test/generic", "version": "1.0.0"}
    bare = build_annotation_or_annotationgroup(schema_id="generic", record_data=GENERIC_RECORD, source=source)
    with _deprecated("generic"):
        prefixed = build_annotation_or_annotationgroup(
            schema_id="open/generic", record_data=GENERIC_RECORD, source=source
        )

    volatile = {"source": {"execution_id"}}
    assert bare.model_dump(exclude=volatile) == prefixed.model_dump(exclude=volatile)
    assert bare.schema_id == "open/generic"


@pytest.mark.parametrize("schema_name", ["classification", "ranking"])
def test_get_open_schema_validator_accepts_both_forms(schema_name):
    from dorsal.file.validators.open_schema import get_open_schema_validator

    with _deprecated(schema_name):
        prefixed = get_open_schema_validator(f"open/{schema_name}")
    assert prefixed is get_open_schema_validator(schema_name)


@pytest.mark.parametrize(
    "func, kwargs",
    [
        ("get_dataset", {}),
        ("get_dataset_schema", {}),
    ],
)
def test_dataset_api_sends_the_dataset_id(func, kwargs):
    import dorsal.api.dataset as dataset_api

    client = MagicMock()
    getattr(dataset_api, func)("classification", client=client, **kwargs)
    with _deprecated("classification"):
        getattr(dataset_api, func)("open/classification", client=client, **kwargs)

    calls = getattr(client, func).call_args_list
    assert [call.kwargs["dataset_id"] for call in calls] == ["open/classification", "open/classification"]


def test_validate_dataset_records_accepts_both_forms():
    import dorsal.api.dataset as dataset_api

    schema = oatschema.get_schema("classification")
    bare = dataset_api.validate_dataset_records("classification", [{"labels": []}], schema_dict=schema)
    with _deprecated("classification"):
        prefixed = dataset_api.validate_dataset_records("open/classification", [{"labels": []}], schema_dict=schema)
    assert bare == prefixed


@pytest.mark.parametrize("method", ["get_dataset", "get_dataset_schema", "get_dataset_type"])
def test_client_dataset_methods_request_the_same_url(method, requests_mock):
    from dorsal.client import DorsalClient

    client = DorsalClient(api_key="x" * 40, base_url="https://api.example.com")
    url = "https://api.example.com/v1/namespaces/open/datasets/classification"
    if method == "get_dataset_schema":
        url += "/schema"
    if method == "get_dataset_type":
        url += "/type"
    dataset = {
        "dataset_id": "open/classification",
        "type": "File",
        "key_field": "id",
        "version": "1",
        "schema": {"type": "object"},
        "date_created": "2026-01-01T00:00:00Z",
        "date_modified": "2026-01-01T00:00:00Z",
        "name": "Classification",
    }
    if method == "get_dataset_type":
        requests_mock.get(url, text="File")
    else:
        requests_mock.get(url, json=dataset if method == "get_dataset" else {"type": "object"})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        bare_result = getattr(client, method)("classification")
        prefixed_result = getattr(client, method)("open/classification")

    assert bare_result == prefixed_result
    assert [request.url for request in requests_mock.request_history] == [url, url]


def test_client_add_file_annotation_posts_to_the_same_url(requests_mock):
    from dorsal.client import DorsalClient
    from dorsal.file.validators.file_record import Annotation

    client = DorsalClient(api_key="x" * 40, base_url="https://api.example.com")
    url = f"https://api.example.com/v1/files/{'a' * 64}/annotations/open/classification"
    requests_mock.post(
        url, json={"total": 1, "success": 1, "error": 0, "dataset_id": "open/classification", "results": []}
    )
    annotation = Annotation.model_validate(
        {"record": {"labels": []}, "source": {"type": "Model", "id": "x"}, "schema_id": "open/classification"}
    )

    client.add_file_annotation(file_hash="a" * 64, schema_id="classification", annotation=annotation)
    with _deprecated("classification"):
        client.add_file_annotation(file_hash="a" * 64, schema_id="open/classification", annotation=annotation)

    assert [request.url.split("?")[0] for request in requests_mock.request_history] == [url, url]


@pytest.mark.parametrize("func", ["get_latest_file_annotation", "get_file_annotations_summary"])
def test_file_annotation_api_accepts_both_forms(func, mocker):
    import dorsal.api.file as file_api

    dorsal_file = mocker.patch("dorsal.file.dorsal_file.DorsalFile")
    mocker.patch("dorsal.session.get_shared_dorsal_client")
    instance = dorsal_file.return_value
    instance.get_latest_annotation.return_value = None
    instance.get_annotations.return_value = []

    for schema_id in ["classification", "open/classification"]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                getattr(file_api, func)("a" * 64, schema_id)
            except Exception:
                pass

    method = instance.get_latest_annotation if func == "get_latest_file_annotation" else instance.get_annotations
    assert [call.kwargs["schema_id"] for call in method.call_args_list] == ["open/classification"] * 2


def test_file_annotation_api_warns_for_open_prefix(mocker):
    import dorsal.api.file as file_api

    mocker.patch("dorsal.file.dorsal_file.DorsalFile").return_value.get_annotations.return_value = []
    mocker.patch("dorsal.session.get_shared_dorsal_client")

    with _deprecated("classification"):
        file_api.get_file_annotations_summary("a" * 64, "open/classification")


def test_internal_calls_do_not_warn(text_file, mocker, no_warnings):
    from dorsal.file.validators.file_record import Annotation

    annotation = Annotation.model_validate(
        {"record": GENERIC_RECORD, "source": {"type": "Model", "id": "x"}, "schema_id": "open/generic"}
    )
    assert annotation.schema_id == "open/generic"
    run_model_last(GenericModel, text_file, schema_id="generic")


def test_installing_a_model_declaring_open_prefix_writes_the_bare_name(no_warnings):
    from dorsal.common.config import get_writable_toml_doc
    from dorsal.registry import installer

    entry_point = MagicMock()
    entry_point.name = "dorsal-generic"
    entry_point.dist.name = "dorsal-generic"
    entry_point.module = __name__
    entry_point.load.return_value = MagicMock(GenericModel=GenericModel)
    config = {"model_class": "GenericModel", "schema_id": "open/generic", "schema_version": "0.8.0"}

    with (
        patch("importlib.metadata.entry_points", return_value=[entry_point]),
        patch("dorsal.registry.installer._load_packaged_model_config", return_value=config),
    ):
        installer.install_model_from_package("dorsal-generic")

    doc, _ = get_writable_toml_doc("project")
    step = doc["model_pipeline"][-1]
    assert step["schema_id"] == "generic"
    assert step["schema_version"] == "0.8.0"


@pytest.mark.parametrize("schema_id, version", [("ranking", "0.5.0"), ("generic", "9.9.9")])
def test_run_model_rejects_a_version_without_the_schema(schema_id, version, text_file):
    from dorsal.file.model_runner import run_model

    with pytest.raises(ValueError, match=f"'{schema_id}' is not available at version {version}"):
        run_model(GenericModel, text_file, schema_id=schema_id, schema_version=version)


def test_run_model_non_oats_open_dataset_runs_without_a_bundled_validator(text_file):
    from dorsal.file.model_runner import run_model

    result = run_model(GenericModel, text_file, schema_id="open/arxiv")[-1]

    assert result.error is None
    assert result.records == [GENERIC_RECORD]


def test_open_schema_versions_accepts_both_forms():
    from dorsal.file.schemas import open_schema_versions

    with _deprecated("generic"):
        prefixed = open_schema_versions("open/generic")
    assert prefixed == open_schema_versions("generic")
    assert "0.8.0" in prefixed


def test_apply_linter_accepts_both_forms():
    from dorsal.common.exceptions import DataQualityError
    from dorsal.file.linters import apply_linter

    record = {"labels": [{"label": "x"}], "vocabulary": ["y"]}
    with pytest.raises(DataQualityError):
        apply_linter("classification", record)
    with _deprecated("classification"), pytest.raises(DataQualityError):
        apply_linter("open/classification", record)


def test_run_single_model_warns_external_callers(text_file):
    from dorsal.file.model_runner import ModelRunner

    for debug in (False, True):
        runner = ModelRunner(pipeline_config=[], debug=debug)
        with _deprecated("generic"):
            result = runner.run_single_model(
                annotation_model=GenericModel, validation_model=None, file_path=text_file, schema_id="open/generic"
            )
        assert result[0].schema_id == "open/generic"


def test_file_annotator_accepts_bare_names():
    from dorsal.file.file_annotator import FILE_ANNOTATOR

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        annotations = FILE_ANNOTATOR.make_manual_annotation(
            annotation={"data": {"a": 1}},
            schema_id="generic",
            source_id="me",
            private=None,
        )
    assert annotations[0].schema_id == "open/generic"
