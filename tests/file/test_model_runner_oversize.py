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

from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.model import AnnotationModel
from dorsal.common.validators import get_json_schema_validator
from dorsal.file.chunking import chunk_record, over_list_limit
from dorsal.file.integrity import check_annotation_schema_version
from dorsal.file.model_runner import ModelRunner
from dorsal.file.sharding import build_annotation_or_annotationgroup
from dorsal.file.validators.open_schema import OpenSchemaValidator, get_open_schema_validator

LIMIT = 100_000
SOURCE = {"type": "Model", "id": "test/model", "version": "1.0", "execution_id": "23456781-1234-5678-1234-567812345678"}


def _document(n_blocks: int) -> dict:
    return {
        "producer": "test",
        "blocks": [{"block_type": "text", "text": f"b{i}", "page_number": 1 + i // 1000} for i in range(n_blocks)],
    }


class _DocumentModel(AnnotationModel):
    id = "test/document"
    version = "1.0"
    output: dict = {}

    def __init__(self, file_path: str):
        pass

    def main(self, **kwargs):
        return copy.deepcopy(type(self).output)


def _run(mocker, record: dict):
    mocker.patch.object(_DocumentModel, "output", record)
    validator = get_open_schema_validator("document-extraction", OPEN_VALIDATION_SCHEMAS_VER)
    checked = mocker.spy(OpenSchemaValidator, "first_error")
    results = ModelRunner().run_single_model(
        annotation_model=_DocumentModel,
        validation_model=validator,
        file_path="/fake/path",
        schema_id="document-extraction",
        schema_version=OPEN_VALIDATION_SCHEMAS_VER,
    )
    sizes = [len(call.args[1]["blocks"]) for call in checked.call_args_list]
    return results, sizes


def test_oversize_record_is_split_and_each_part_validated_without_whole_validation(mocker):
    record = _document(2 * LIMIT + 5)
    expected_parts = chunk_record(copy.deepcopy(record), "document-extraction", OPEN_VALIDATION_SCHEMAS_VER)

    results, sizes = _run(mocker, record)

    assert sizes == [LIMIT, LIMIT, 5]
    assert [r.error for r in results] == [None, None, None]
    assert [r.records for r in results] == [[part] for part in expected_parts]
    assert [(r.source.execution_part, r.source.execution_total_parts) for r in results] == [(1, 3), (2, 3), (3, 3)]
    validator = get_open_schema_validator("document-extraction", OPEN_VALIDATION_SCHEMAS_VER)
    for result in results:
        assert result.schema_version == OPEN_VALIDATION_SCHEMAS_VER
        assert validator.first_error(result.records[0]) is None
        annotation = build_annotation_or_annotationgroup(
            schema_id="document-extraction",
            record_data=result.records[0],
            source=SOURCE,
            schema_version=result.schema_version,
        )
        check_annotation_schema_version(schema_id="document-extraction", annotation=annotation, file_label="f")


def test_oversize_record_with_an_invalid_block_reports_the_parts_error(mocker):
    record = _document(LIMIT + 10)
    del record["blocks"][LIMIT + 3]["block_type"]

    results, sizes = _run(mocker, record)

    assert sizes == [LIMIT, 10]
    assert len(results) == 1
    assert results[0].records is None
    assert "block_type" in results[0].error


def test_record_at_the_limit_is_validated_whole(mocker):
    results, sizes = _run(mocker, _document(LIMIT))

    assert sizes == [LIMIT]
    assert len(results) == 1
    assert results[0].error is None
    assert len(results[0].records[0]["blocks"]) == LIMIT
    assert results[0].schema_version == OPEN_VALIDATION_SCHEMAS_VER


SCHEMA = {"type": "object", "properties": {"blocks": {"type": "array", "maxItems": 2}}}


@pytest.mark.parametrize(
    "records, schema_id, schema, expected",
    [
        ({"blocks": [1, 2, 3]}, "document-extraction", SCHEMA, True),
        ({"blocks": [1, 2]}, "document-extraction", SCHEMA, False),
        ([{"blocks": [1]}, {"blocks": [1, 2, 3]}], "open/document-extraction", SCHEMA, True),
        ({"blocks": "abc"}, "document-extraction", SCHEMA, False),
        ({"blocks": [1, 2, 3]}, "document-extraction", {"properties": {"blocks": {"type": "array"}}}, False),
        ({"blocks": [1, 2, 3]}, "document-extraction", {"properties": {"blocks": {"maxItems": True}}}, False),
        ({"blocks": [1, 2, 3]}, "document-extraction", {"$ref": "#/defs/x"}, False),
        ({"data": {"a": 1, "b": 2, "c": 3}}, "generic", {"properties": {"data": {"maxItems": 2}}}, False),
        ({"labels": [1, 2, 3]}, "classification", {"properties": {"labels": {"maxItems": 2}}}, True),
        ({"blocks": [1, 2, 3]}, "acme/custom", SCHEMA, False),
    ],
)
def test_over_list_limit(records, schema_id, schema, expected):
    assert over_list_limit(records, schema_id, schema) is expected


def test_oversize_record_that_cannot_be_split_reports_the_whole_record_error(mocker):
    schema = {
        "type": "object",
        "properties": {"blocks": {"type": "array", "maxItems": 2}},
        "required": ["blocks"],
    }
    mocker.patch.object(_DocumentModel, "output", {"blocks": [{"block_type": "text"}] * 3})

    results = ModelRunner().run_single_model(
        annotation_model=_DocumentModel,
        validation_model=get_json_schema_validator(schema),
        file_path="/fake/path",
        schema_id="document-extraction",
    )

    assert len(results) == 1
    assert results[0].records is None
    assert "maxItems" in results[0].error
    assert "blocks" in results[0].error
