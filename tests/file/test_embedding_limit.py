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
import logging
from typing import Any

import oatschema
import pytest
from pydantic import ValidationError

from dorsal.common.constants import DENSE_EMBEDDING_MAX_VALUES
from dorsal.common.model import AnnotationModel
from dorsal.file.schemas import open_schema_versions

LIMIT_MESSAGE = "16,385 values, more than the limit of 16,384"


class OversizeEmbeddingModel(AnnotationModel):
    id = "test/oversize-embedding"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        return {"model": "m", "vector": [0.0] * (DENSE_EMBEDDING_MAX_VALUES + 1)}


class SparseEmbeddingModel(AnnotationModel):
    id = "test/sparse-embedding"
    version = "1.0.0"

    def main(self, **kwargs) -> dict[str, Any]:
        size = DENSE_EMBEDDING_MAX_VALUES + 1
        return {"vector": {"dimensions": size, "indices": list(range(size)), "values": [1.0] * size}}


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("hello world", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("version", open_schema_versions("embedding"))
def test_limit_matches_every_bundled_schema_version(version):
    schema = json.loads(oatschema.get_schema("embedding", version, mode="json"))
    dense = next(option for option in schema["properties"]["vector"]["oneOf"] if option.get("type") == "array")

    assert dense["maxItems"] == DENSE_EMBEDDING_MAX_VALUES


@pytest.mark.parametrize("runner", ["dorsal.file.model_runner", "dorsal.testing"])
def test_run_model_rejects_dense_embedding_with_the_limit(runner, text_file, caplog):
    import importlib

    with caplog.at_level(logging.ERROR):
        result = importlib.import_module(runner).run_model(OversizeEmbeddingModel, text_file, schema_id="embedding")[-1]

    assert result.records is None
    assert LIMIT_MESSAGE in result.error
    assert not any("Unexpected error" in rec.getMessage() for rec in caplog.records)


def test_pipeline_rejects_dense_embedding_with_the_limit(text_file, mocker, caplog):
    from dorsal.common.validators import import_callable
    from dorsal.file.model_runner import ModelRunner

    mocker.patch(
        "dorsal.file.model_runner.import_callable",
        side_effect=lambda path: globals()[path.name] if path.module == __name__ else import_callable(path),
    )
    step = {
        "annotation_model": {"module": __name__, "name": "OversizeEmbeddingModel"},
        "validation_model": {"module": "dorsal.file.validators.open_schema", "name": "embedding_validator"},
        "schema_id": "embedding",
    }
    runner = ModelRunner(pipeline_config=[step])

    with caplog.at_level(logging.WARNING, logger="dorsal.file.model_runner"):
        record = runner.run(text_file)

    assert "open/embedding" not in record.annotations.model_dump(exclude_none=True)
    assert any(
        "completed with error" in rec.getMessage() and LIMIT_MESSAGE in rec.getMessage() for rec in caplog.records
    )


def test_run_model_sparse_embedding_is_not_rejected(text_file):
    from dorsal.file.model_runner import run_model

    result = run_model(SparseEmbeddingModel, text_file, schema_id="embedding")[-1]

    assert result.error is None, result.error
    assert result.records


@pytest.mark.parametrize("schema_id", ["embedding", "open/embedding"])
def test_annotation_model_rejects_dense_embedding(schema_id):
    from dorsal.file.validators.file_record import Annotation, AnnotationXL

    data = {
        "record": {"vector": [0.0] * (DENSE_EMBEDDING_MAX_VALUES + 1)},
        "source": {"type": "Model", "id": "x"},
        "schema_id": schema_id,
    }

    with pytest.raises(ValidationError, match=LIMIT_MESSAGE):
        Annotation.model_validate(data)
    assert AnnotationXL.model_validate(data).record is not None


def test_annotation_model_accepts_other_schemas_and_sizes():
    from dorsal.file.validators.file_record import Annotation

    source = {"type": "Model", "id": "x"}
    Annotation.model_validate({"record": {"vector": [0.0] * 20_000}, "source": source, "schema_id": "my-org/vectors"})
    Annotation.model_validate(
        {"record": {"vector": [0.0] * DENSE_EMBEDDING_MAX_VALUES}, "source": source, "schema_id": "open/embedding"}
    )
