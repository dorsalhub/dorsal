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
import math
from typing import Any

import oatschema
import pytest

from dorsal.api.adapters import export_record, parse_file
from dorsal.api.dataset import make_schema_validator
from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.exceptions import AnnotationValidationError, DorsalError, UnversionedAnnotationError
from dorsal.common.model import AnnotationModel
from dorsal.file.chunking import chunk_record
from dorsal.file.dorsal_file import LocalFile
from dorsal.file.integrity import check_record_schema_versions
from dorsal.file.model_runner import ModelRunner, run_model
from dorsal.file.sharding import build_annotation_or_annotationgroup, reassemble_record
from dorsal.file.validators.file_record import AnnotationGroup
from dorsal.file.validators.numbers import describe_number_changes, display_value
from dorsal.file.validators.open_schema import get_open_schema_validator

LIMIT = 100_000
SOURCE = {"type": "Model", "id": "test/model", "version": "1.0", "execution_id": "23456781-1234-5678-1234-567812345678"}
LLM = {"model": "m", "response_data": "hi", "generation_params": {"seed": 42, "temperature": 1.0}}
HOCR = """<html><body>
<div class="ocr_page" title="bbox 0 0 1000 1000; ppageno 0">
<span class="ocr_line" title="bbox 10 10 200 30; x_wconf 150">Hello world</span>
<span class="ocr_line" title="bbox 10 40 200 60; x_wconf 90">Second line</span>
</div></body></html>"""


class OutputModel(AnnotationModel):
    id = "test/numbers"
    version = "1.0"
    output: Any = None

    def main(self):
        return copy.deepcopy(type(self).output)


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("hello", encoding="utf-8")
    return str(path)


@pytest.fixture
def output(mocker):
    def _set(record):
        mocker.patch.object(OutputModel, "output", record)

    return _set


def _run(path, schema_id, **kwargs):
    results = run_model(OutputModel, path, schema_id=schema_id, **kwargs)
    return results[-1]


def _document(n_blocks: int) -> dict:
    return {
        "producer": "test",
        "unit": "pt",
        "extraction_type": "text",
        "blocks": [{"block_type": "text", "text": f"b{i}", "page_number": 1 + i // 1000} for i in range(n_blocks)],
    }


def test_dorsal_default_differs_from_its_dependencies_defaults():
    assert OPEN_VALIDATION_SCHEMAS_VER == "0.8.0"
    assert oatschema.SCHEMA_VERSION == "0.9.0"


def test_run_model_stamps_the_default_version_and_keeps_an_integer_seed(text_file, output):
    output(LLM)

    result = _run(text_file, "llm-output")

    assert result.error is None, result.error
    assert result.schema_version == "0.8.0"
    assert result.records == [LLM]
    assert result.dropped == [] and result.converted == []


def test_run_model_at_0_9_0_converts_an_integer_seed_and_reports_it(text_file, output):
    output(LLM)

    result = _run(text_file, "llm-output", schema_version="0.9.0")

    assert result.error is None, result.error
    assert result.schema_version == "0.9.0"
    assert result.records[0]["generation_params"]["seed"] == "42"
    assert [(c.path, c.before, c.after) for c in result.converted] == [(["generation_params", "seed"], "42", "'42'")]
    assert result.dropped == []


@pytest.mark.parametrize("version", ["0.8.0", "0.9.0"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 2**60, -(2**53)])
def test_run_model_drops_a_bad_optional_number_and_stamps_the_rest(text_file, output, version, bad):
    output({"data": {"bad": bad, "good": 1}})

    result = _run(text_file, "generic", schema_version=version)

    assert result.error is None, result.error
    assert result.schema_version == version
    assert result.records == [{"data": {"good": 1}}]
    assert [d.path for d in result.dropped] == [["data", "bad"]]
    assert result.dropped[0].value == display_value(bad)


@pytest.mark.parametrize("version", ["0.8.0", "0.9.0"])
def test_run_model_rejects_a_bad_number_in_strict_mode(text_file, output, version):
    output({"data": {"bad": math.nan, "good": 1}})

    result = _run(text_file, "generic", schema_version=version, on_bad_number="raise")

    assert result.records is None
    assert result.error is not None and "bad" in result.error


def test_run_model_rejects_a_bad_number_in_a_list_even_when_dropping(text_file, output):
    output({"data": {"values": [1.0, math.nan]}})

    result = _run(text_file, "generic")

    assert result.records is None
    assert result.error is not None


def test_run_model_rejects_an_unknown_on_bad_number(text_file, output):
    output({"data": {}})

    with pytest.raises(ValueError, match="on_bad_number"):
        run_model(OutputModel, text_file, schema_id="generic", on_bad_number="round")  # type: ignore[arg-type]


def test_run_model_converts_negative_zero(text_file, output):
    output({"data": {"x": -0.0}})

    result = _run(text_file, "generic")

    assert result.records == [{"data": {"x": 0.0}}]
    assert math.copysign(1.0, result.records[0]["data"]["x"]) == 1.0
    assert [(c.path, c.before, c.after) for c in result.converted] == [(["data", "x"], "-0.0", "0.0")]


@pytest.mark.parametrize(
    "record, field",
    [
        ({"data": {"text": "a\ud800b"}}, "text"),
        ({"data": {"a\udc00": 1}}, "data"),
    ],
)
def test_run_model_rejects_an_unpaired_surrogate_at_0_8_0(text_file, output, record, field):
    output(record)

    result = _run(text_file, "generic")

    assert result.records is None
    assert result.error is not None and "surrogate" in result.error


@pytest.mark.parametrize("created, valid", [("2026-11-18T10:00:00Z", True), ("18/11/2026 10:00", False)])
def test_run_model_checks_date_time_formats_at_0_8_0(text_file, output, created, valid):
    output({**LLM, "generation_metadata": {"created": created}})

    result = _run(text_file, "llm-output")

    assert (result.error is None) is valid, result.error
    assert (result.schema_version == "0.8.0") and ((result.records is not None) is valid)


@pytest.mark.parametrize("version", ["0.8.0", "0.9.0"])
def test_split_record_parts_each_report_their_own_drops(version):
    record = _document(2 * LIMIT + 5)
    record["blocks"][LIMIT + 2]["score"] = math.nan
    OutputModel.output = record
    try:
        results = ModelRunner(pipeline_config=None, single_model_mode=True).run_single_model(
            annotation_model=OutputModel,
            validation_model=get_open_schema_validator("document-extraction", version),
            file_path="/fake/path",
            schema_id="document-extraction",
            schema_version=version,
        )
    finally:
        OutputModel.output = None

    assert [r.error for r in results] == [None, None, None]
    assert [r.schema_version for r in results] == [version] * 3
    assert [[d.path for d in r.dropped] for r in results] == [[], [["blocks", 2, "score"]], []]
    assert all(d.record == 0 for r in results for d in r.dropped)
    assert "score" not in results[1].records[0]["blocks"][2]


@pytest.mark.parametrize("version", ["0.8.0", "0.9.0"])
def test_joining_split_parts_by_execution_part_then_group_index_rebuilds_the_blocks(version):
    record = _document(2 * LIMIT + 5)
    original_blocks = copy.deepcopy(record["blocks"])
    OutputModel.output = record
    try:
        results = ModelRunner(pipeline_config=None, single_model_mode=True).run_single_model(
            annotation_model=OutputModel,
            validation_model=get_open_schema_validator("document-extraction", version),
            file_path="/fake/path",
            schema_id="document-extraction",
            schema_version=version,
        )
    finally:
        OutputModel.output = None

    stored = []
    for result in reversed(results):
        annotation = build_annotation_or_annotationgroup(
            schema_id="document-extraction",
            record_data=result.records[0],
            source={**SOURCE, **result.source.model_dump(include={"execution_part", "execution_total_parts"})},
            schema_version=result.schema_version,
        )
        stored.append(annotation)
    assert any(isinstance(item, AnnotationGroup) for item in stored)

    def part_number(item):
        source = item.annotations[0].source if isinstance(item, AnnotationGroup) else item.source
        return source.execution_part

    rebuilt = []
    for item in sorted(stored, key=part_number):
        if isinstance(item, AnnotationGroup):
            _, part_record = reassemble_record(item)
        else:
            part_record = item.record.model_dump()
        rebuilt.extend(part_record["blocks"])

    assert rebuilt == original_blocks


@pytest.mark.parametrize("version", ["0.8.0", "0.9.0"])
def test_list_limits_for_splitting_come_from_the_requested_version(version):
    parts = chunk_record(_document(LIMIT + 1), "document-extraction", schema_version=version)

    assert [len(part["blocks"]) for part in parts] == [LIMIT, 1]


def _pipeline_step(schema_id: str, schema_version: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {
        "annotation_model": {"module": __name__, "name": "OutputModel"},
        "validation_model": {
            "module": "dorsal.file.validators.open_schema",
            "name": f"{schema_id.replace('-', '_')}_validator",
        },
        "schema_id": schema_id,
    }
    if schema_version is not None:
        step["schema_version"] = schema_version
    return step


@pytest.mark.parametrize("version", [None, "0.9.0"])
def test_pipeline_records_drops_on_the_local_file(text_file, output, version):
    output({**LLM, "score": 7.0})

    lf = LocalFile(text_file, model_runner_pipeline=[_pipeline_step("llm-output", version)], use_cache=False)

    annotation = lf.get_annotations("llm-output")[0]
    expected_version = version or OPEN_VALIDATION_SCHEMAS_VER
    assert annotation.schema_version == expected_version
    assert "score" not in annotation.record.model_dump()
    [change] = lf.number_changes
    assert change.schema_id == "open/llm-output"
    assert change.schema_version == expected_version
    assert change.source_id == "test/numbers"
    assert [d.path for d in change.dropped] == [["score"]]
    expected_seed = 42 if version is None else "42"
    assert annotation.record.model_dump()["generation_params"]["seed"] == expected_seed
    assert len(change.converted) == (0 if version is None else 1)


def test_pipeline_in_strict_mode_keeps_no_record(text_file, output):
    output({**LLM, "score": 7.0})

    lf = LocalFile(
        text_file,
        model_runner_pipeline=[_pipeline_step("llm-output")],
        use_cache=False,
        on_bad_number="raise",
    )

    assert not lf.get_annotations("llm-output")
    [change] = lf.number_changes
    assert (change.schema_id, change.source_id, change.dropped, change.converted) == (
        "open/llm-output",
        "test/numbers",
        [],
        [],
    )
    assert change.rejected == "… is outside the bounds of this field at /score"


@pytest.fixture
def local_file(text_file):
    return LocalFile(text_file, model_runner_pipeline=[], use_cache=False)


@pytest.mark.parametrize("version", [None, "0.8.0", "0.9.0"])
def test_add_annotation_drops_and_reports(local_file, version):
    local_file.add_annotation(
        schema_id="generic", record={"data": {"bad": math.inf, "good": 1}}, schema_version=version
    )

    annotation = local_file.get_annotations("generic")[0]
    assert annotation.schema_version == (version or OPEN_VALIDATION_SCHEMAS_VER)
    assert annotation.record.model_dump() == {"data": {"good": 1}}
    [change] = local_file.number_changes
    assert [d.path for d in change.dropped] == [["data", "bad"]]
    assert change.schema_version == annotation.schema_version


def test_add_annotation_in_strict_mode_raises(local_file):
    with pytest.raises(AnnotationValidationError, match="bad"):
        local_file.add_annotation(schema_id="generic", record={"data": {"bad": math.inf}}, on_bad_number="raise")
    assert local_file.number_changes == []


def test_local_file_strict_mode_applies_to_add_helpers(text_file):
    lf = LocalFile(text_file, model_runner_pipeline=[], use_cache=False, on_bad_number="raise")

    with pytest.raises(AnnotationValidationError):
        lf.add_annotation(schema_id="generic", record={"data": {"bad": math.nan}})


@pytest.mark.parametrize("version, seed", [(None, 42), ("0.8.0", 42), ("0.9.0", "42")])
def test_add_llm_output_seed(local_file, version, seed):
    local_file.add_llm_output(model="m", response_data="hi", generation_params={"seed": 42}, schema_version=version)

    annotation = local_file.get_annotations("llm-output")[0]
    assert annotation.schema_version == (version or OPEN_VALIDATION_SCHEMAS_VER)
    assert annotation.record.model_dump()["generation_params"]["seed"] == seed
    converted = [c for change in local_file.number_changes for c in change.converted]
    assert len(converted) == (1 if version == "0.9.0" else 0)


def test_add_annotation_with_force_skips_the_check_and_is_never_stamped_or_pushed(local_file):
    local_file.add_annotation(schema_id="generic", record={"data": {"bad": math.nan}}, force=True)

    annotation = local_file.get_annotations("generic")[0]
    assert math.isnan(annotation.record.model_dump()["data"]["bad"])
    assert annotation.schema_version is None
    assert local_file.number_changes == []
    with pytest.raises(UnversionedAnnotationError):
        check_record_schema_versions([local_file.model])


@pytest.mark.parametrize("version", [None, "0.9.0"])
def test_dataset_validator_checks_numbers_at_its_version(version):
    validator = make_schema_validator("llm-output", schema_version=version)

    checked = validator.check_numbers([{**LLM, "score": math.nan}])

    assert validator.schema_version == (version or OPEN_VALIDATION_SCHEMAS_VER)
    assert [d.path for d in checked.dropped] == [["score"]]
    assert checked.records[0]["generation_params"]["seed"] == (42 if version is None else "42")


@pytest.mark.parametrize("version", [None, "0.8.0", "0.9.0"])
def test_parse_file_drops_and_reports(version):
    record = parse_file(HOCR, "document-extraction", "hocr", schema_version=version)

    assert [d.path for d in record.dropped] == [("blocks", 0, "score")]
    assert "score" not in record["blocks"][0]


def test_parse_file_in_strict_mode_raises():
    with pytest.raises(DorsalError, match="score"):
        parse_file(HOCR, "document-extraction", "hocr", on_bad_number="raise")


def test_parse_file_passes_dorsals_version_not_the_adapters_default(mocker):
    from oatschema_adapters import get_adapter

    adapter = get_adapter("document-extraction", "hocr")
    spy = mocker.spy(type(adapter), "parse")

    parse_file(HOCR, "document-extraction", "hocr")

    assert spy.call_args.kwargs["schema_version"] == OPEN_VALIDATION_SCHEMAS_VER
    assert spy.call_args.kwargs["on_bad_number"] == "drop"


def test_export_validates_at_dorsals_default_not_the_adapters():
    record = {**_document(1), "attributes": {"big": 2**60}}

    assert export_record(record, "document-extraction", "txt") == "b0"
    with pytest.raises(DorsalError):
        export_record(record, "document-extraction", "txt", schema_version="0.9.0")


def test_describe_number_changes_caps_its_lines():
    from dorsal.file.validators.numbers import DroppedValue

    dropped = [DroppedValue(path=["data", str(i)], value="nan", reason="not a finite number") for i in range(12)]

    lines = describe_number_changes(dropped, [])

    assert len(lines) == 11
    assert lines[0] == "dropped nan at /data/0 (not a finite number)"
    assert lines[-1] == "and 2 more"


def test_display_value_is_short_for_huge_integers():
    assert display_value(10**400) == "an integer of about 401 digits"
    assert display_value(-(10**400)) == "-an integer of about 401 digits"
    assert display_value(math.nan) == "nan"


def test_metadata_reader_passes_strict_mode_to_its_local_files(text_file, tmp_path):
    from dorsal.file.metadata_reader import MetadataReader

    reader = MetadataReader(model_config=[], offline=True, on_bad_number="raise")

    assert reader.scan_file(text_file, skip_cache=True).on_bad_number == "raise"
    files = reader.scan_directory(str(tmp_path), skip_cache=True)
    assert files and all(f.on_bad_number == "raise" for f in files)


def test_directory_processing_moves_changes_off_the_runner(output, tmp_path):
    from dorsal.file.metadata_reader import MetadataReader

    path = tmp_path / "file.txt"
    path.write_text("hello", encoding="utf-8")
    output({**LLM, "score": 7.0})
    reader = MetadataReader(model_config=[_pipeline_step("llm-output")], offline=True)

    reader.generate_processed_records_from_directory(str(tmp_path), skip_cache=True, show_progress=False)

    [change] = reader.last_number_changes[str(path)]
    assert [d.path for d in change.dropped] == [["score"]]
    assert reader._model_runner.number_changes == {}


def test_a_pipeline_run_replaces_the_previous_runs_changes(text_file, output):
    runner = ModelRunner(pipeline_config=[_pipeline_step("llm-output")])
    output({**LLM, "score": 7.0})
    runner.run(text_file)
    assert len(runner.number_changes[text_file]) == 1

    output(LLM)
    runner.run(text_file)

    assert text_file not in runner.number_changes


def _run_without_validator(record, **kwargs):
    OutputModel.output = record
    try:
        return ModelRunner(pipeline_config=None, single_model_mode=True).run_single_model(
            annotation_model=OutputModel,
            validation_model=None,
            file_path="/fake/path",
            schema_id="generic",
            schema_version="0.8.0",
            **kwargs,
        )[-1]
    finally:
        OutputModel.output = None


def test_without_a_validator_numbers_are_checked_before_stamping():
    result = _run_without_validator({"data": {"x": 2**60, "y": -0.0}})

    assert result.error is None
    assert result.schema_version == "0.8.0"
    assert result.records == [{"data": {"y": 0.0}}]
    assert [d.path for d in result.dropped] == [["data", "x"]]
    assert [c.path for c in result.converted] == [["data", "y"]]


def test_without_a_validator_a_rejected_record_is_unstamped_or_an_error_in_strict_mode():
    record = {"data": {"xs": [2**60]}}

    dropping = _run_without_validator(record)
    strict = _run_without_validator(record, on_bad_number="raise")

    assert dropping.error is None and dropping.schema_version is None
    assert strict.records is None and strict.schema_version is None
    assert strict.error is not None and "rejected" in strict.error


def test_file_annotator_checks_numbers_at_the_requested_version(text_file, output):
    from dorsal.file.file_annotator import FILE_ANNOTATOR

    output({"data": {"x": 2**60, "y": -0.0}})

    [annotation] = FILE_ANNOTATOR.annotate_file_using_model_and_validator(
        file_path=text_file,
        model_runner=ModelRunner(pipeline_config=None, single_model_mode=True),
        annotation_model_cls=OutputModel,
        schema_id="generic",
        schema_version="0.8.0",
        validation_model=None,
        private=None,
    )

    assert annotation.schema_version == "0.8.0"
    assert annotation.record.model_dump() == {"data": {"y": 0.0}}


@pytest.mark.parametrize("bad, version", [(math.nan, "0.8.0"), (math.inf, "0.8.0"), (2**60, "0.9.0")])
def test_force_never_stamps_a_record_that_does_not_validate(local_file, bad, version):
    local_file.add_annotation(schema_id="generic", record={"data": {"bad": bad}}, schema_version=version, force=True)

    assert local_file.get_annotations("generic")[0].schema_version is None
    assert local_file.number_changes == []


def test_force_keeps_a_large_integer_that_validates_at_0_8_0(local_file):
    local_file.add_annotation(schema_id="generic", record={"data": {"big": 2**60}}, schema_version="0.8.0", force=True)

    annotation = local_file.get_annotations("generic")[0]
    assert annotation.schema_version == "0.8.0"
    assert annotation.record.model_dump() == {"data": {"big": 2**60}}


def test_number_change_labels_are_not_read_as_markup(mock_error_console, rendered):
    from dorsal.cli.number_changes import print_number_changes
    from dorsal.cli.themes.palettes import DEFAULT_PALETTE
    from dorsal.file.validators.numbers import DroppedValue

    dropped = [DroppedValue(path=["a", str(i)], value="nan", reason="not a finite number") for i in range(2)]

    print_number_changes(
        mock_error_console, {"palette": DEFAULT_PALETTE, "borders": None}, "notes[/b].hocr", dropped, []
    )

    assert "notes[/b].hocr" in rendered(mock_error_console)
