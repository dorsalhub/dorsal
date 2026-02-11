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

import pytest
from unittest.mock import MagicMock, patch
from dorsal.testing import run_model
from dorsal.common.model import AnnotationModel
from dorsal.file.model_runner import ModelRunner


class DummyModel(AnnotationModel):
    id = "dummy/model"
    version = "1.0"

    def main(self):
        pass


@pytest.fixture
def mock_runner():
    # Patch ModelRunner in the module where it is instantiated
    with patch("dorsal.file.model_runner.ModelRunner") as MockRunnerCls:
        runner_instance = MockRunnerCls.return_value

        base_result = MagicMock()
        base_result.error = None
        base_result.record = {"hash": "123", "media_type": "text/plain", "size": 100, "name": "f.txt"}

        # Setup a successful pipeline model result
        pipeline_result = MagicMock()
        pipeline_result.error = None

        # configure run_single_model to return base then pipeline
        runner_instance.run_single_model.side_effect = [base_result, pipeline_result]

        yield runner_instance


def test_test_model_success(mock_runner):
    run_model(DummyModel, "/tmp/fake.txt")

    assert mock_runner.run_single_model.call_count == 2
    call_args = mock_runner.run_single_model.call_args_list[0]

    assert call_args.kwargs["options"]["calculate_similarity_hash"] is False


def test_test_model_base_failure(mock_runner):
    failure = MagicMock()
    failure.error = "Base failed"
    mock_runner.run_single_model.side_effect = [failure]

    result = run_model(DummyModel, "/tmp/fake.txt")
    assert result.error == "Base failed"
    assert mock_runner.run_single_model.call_count == 1


def test_test_model_dependency_check():
    from dorsal.file.dependencies import make_file_extension_dependency

    deps = make_file_extension_dependency(extensions=[".pdf"])

    base_result = MagicMock()
    base_result.error = None
    base_result.record = {"name": "f.txt", "extension": ".txt", "media_type": "text/plain"}

    with patch.object(ModelRunner, "run_single_model", side_effect=[base_result]) as mock_run:
        result = run_model(DummyModel, "/f.txt", dependencies=deps)
        assert "Dependency not met" in str(result.error)
        assert mock_run.call_count == 1


def test_ambiguous_config_error(mock_runner):
    with pytest.raises(ValueError, match="Ambiguous configuration"):
        run_model(DummyModel, "/f.txt", schema_id="open/generic", validation_model=MagicMock())


def test_open_schema_resolution(mock_runner):
    with patch("dorsal.file.validators.open_schema.get_open_schema_validator") as mock_get_val:
        mock_get_val.return_value = MagicMock()

        run_model(DummyModel, "/f.txt", schema_id="open/generic")

        call_args = mock_runner.run_single_model.call_args_list[1]
        assert call_args.kwargs["validation_model"] == mock_get_val.return_value
