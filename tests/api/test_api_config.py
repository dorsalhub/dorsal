# Copyright 2025 Dorsal Hub LTD
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
from unittest.mock import MagicMock, patch, ANY
from dorsal.api import config
from dorsal.common.auth import APIKeySource


@pytest.fixture
def mock_pipeline_config():
    with patch("dorsal.api.config.PipelineConfig") as mock:
        yield mock


@pytest.fixture
def mock_auth_details():
    with patch("dorsal.api.config.get_api_key_details") as mock:
        mock.return_value = {"path": "/tmp/dorsal/dorsal.toml", "source": APIKeySource.PROJECT}
        yield mock


def test_get_config_summary(mock_auth_details):
    """Tests the summary dictionary generation."""
    with (
        patch("dorsal.api.config.load_config", return_value=(None, "/tmp/conf")),
        patch("dorsal.api.config.get_email_from_config", return_value="user@test.com"),
        patch("dorsal.api.config.get_theme_from_config", return_value="dark"),
        patch("dorsal.api.config.get_global_config_path", return_value="/global/conf"),
        patch("dorsal.common.constants.BASE_URL", "http://api.test"),
        patch("dorsal.common.constants.LOCAL_DORSAL_DIR", "/local/dir"),
    ):
        summary = config.get_config_summary()

        assert summary["logged_in_user"] == "user@test.com"
        with patch.dict("os.environ", {"DORSAL_THEME": "sunset"}):
            summary_env = config.get_config_summary()
            assert summary_env["current_theme"] == "sunset"


def test_pipeline_wrappers(mock_pipeline_config):
    """Tests simple wrapper functions."""
    config.get_model_pipeline(scope="global")
    mock_pipeline_config.get_steps.assert_called_with(scope="global")

    config.remove_model_by_index(1)
    mock_pipeline_config.remove_step_by_index.assert_called_with(index=1, scope="project")

    config.activate_model_by_name("foo")
    mock_pipeline_config.set_step_status_by_name.assert_called_with(name="foo", active=True, scope="project")


def test_show_model_pipeline(mock_pipeline_config):
    """Tests formatting of the pipeline summary."""
    step1 = MagicMock()
    step1.annotation_model.name = "ModelA"
    step1.annotation_model.module = "mod.a"
    step1.dependencies = []
    step1.deactivated = False

    step2 = MagicMock()
    step2.annotation_model.name = "ModelB"
    step2.dependencies = [MagicMock(type="audio")]
    step2.deactivated = True

    mock_pipeline_config.get_steps.return_value = [step1, step2]

    summary = config.show_model_pipeline()
    assert len(summary) == 2
    assert summary[0]["status"] == "Base (Locked)"
    assert summary[1]["status"] == "Deactivated"


class DummyModel:
    pass


def test_register_model_basic(mock_pipeline_config):
    """Happy path for registering a model."""
    with patch("dorsal.api.config.ModelRunnerPipelineStep") as step_mock:
        step_mock.model_validate.return_value.model_dump.return_value = {"valid": "data"}

        config.register_model(DummyModel, schema_id="custom/schema")

        mock_pipeline_config.upsert_step.assert_called_once()

        # Verify validation was called
        assert step_mock.model_validate.called
        call_args = step_mock.model_validate.call_args[0][0]
        assert call_args["annotation_model"] == (DummyModel.__module__, "DummyModel")


def test_register_model_invalid_scope():
    with pytest.raises(ValueError, match="Invalid scope"):
        config.register_model(DummyModel, schema_id="test/schema", scope="bad_scope")


def test_register_model_validator_types(mock_pipeline_config):
    """Tests dictionary, class, and instance validators."""
    with patch("dorsal.api.config.ModelRunnerPipelineStep"):
        # 1. Inert Dict (missing keywords)
        with pytest.raises(ValueError, match="appears to be inert"):
            config.register_model(DummyModel, schema_id="test/schema", validation_model={"foo": "bar"})

        # 2. Valid Dict (has keywords)
        config.register_model(DummyModel, schema_id="test/schema", validation_model={"type": "object"})

        # 3. Pydantic Class (Mocked check)
        with patch("dorsal.common.model.is_pydantic_model_class", return_value=True):
            config.register_model(DummyModel, schema_id="test/schema", validation_model=DummyModel)

        # 4. Invalid Type
        with patch("dorsal.common.model.is_pydantic_model_class", return_value=False):
            with pytest.raises(TypeError, match="Invalid 'validation_model' type"):
                config.register_model(DummyModel, schema_id="test/schema", validation_model="im_a_string")


def test_register_model_dependencies(mock_pipeline_config):
    """Tests dependency list processing."""
    mock_dep = MagicMock()
    # Use a valid tag just in case
    mock_dep.model_dump.return_value = {"type": "media_type", "value": "video/mp4"}

    with (
        patch("dorsal.api.config.ModelRunnerPipelineStep"),
        patch("dorsal.common.model.is_pydantic_model_instance") as is_inst,
    ):
        # 1. Valid dependency
        is_inst.return_value = True
        config.register_model(DummyModel, schema_id="test/schema", dependencies=[mock_dep])

        # 2. Invalid dependency (Dict)
        is_inst.return_value = False
        with pytest.raises(TypeError, match="is a dict"):
            config.register_model(DummyModel, schema_id="test/schema", dependencies=[{"type": "media_type"}])
