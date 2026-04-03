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

        assert step_mock.model_validate.called
        call_args = step_mock.model_validate.call_args[0][0]
        assert call_args["annotation_model"] == (DummyModel.__module__, "DummyModel")


def test_register_model_invalid_scope():
    with pytest.raises(ValueError, match="Invalid scope"):
        config.register_model(DummyModel, schema_id="test/schema", scope="bad_scope")


def test_register_model_validator_types(mock_pipeline_config):
    """Tests dictionary, class, and instance validators."""
    with patch("dorsal.api.config.ModelRunnerPipelineStep"):
        with pytest.raises(ValueError, match="is inert"):
            config.register_model(DummyModel, schema_id="test/schema", validation_model={"foo": "bar"})

        config.register_model(DummyModel, schema_id="test/schema", validation_model={"type": "object"})

        with patch("dorsal.common.model.is_pydantic_model_class", return_value=True):
            config.register_model(DummyModel, schema_id="test/schema", validation_model=DummyModel)

        with patch("dorsal.common.model.is_pydantic_model_class", return_value=False):
            with pytest.raises(TypeError, match="Invalid 'validation_model' type"):
                config.register_model(DummyModel, schema_id="test/schema", validation_model="im_a_string")


def test_register_model_dependencies(mock_pipeline_config):
    """Tests dependency list processing."""
    mock_dep = MagicMock()

    mock_dep.model_dump.return_value = {"type": "media_type", "value": "video/mp4"}

    with (
        patch("dorsal.api.config.ModelRunnerPipelineStep"),
        patch("dorsal.common.model.is_pydantic_model_instance") as is_inst,
    ):
        is_inst.return_value = True
        config.register_model(DummyModel, schema_id="test/schema", dependencies=[mock_dep])

        is_inst.return_value = False
        with pytest.raises(TypeError, match="is a dict"):
            config.register_model(DummyModel, schema_id="test/schema", dependencies=[{"type": "media_type"}])


def test_find_package_name_by_class(mock_pipeline_config):
    """Tests resolving a class name to its package name."""
    step_with_pkg = MagicMock()
    step_with_pkg.annotation_model.name = "FasterWhisperTranscriber"
    step_with_pkg.package_name = "dorsal-whisper"

    step_no_pkg = MagicMock()
    step_no_pkg.annotation_model.name = "LocalModel"
    step_no_pkg.package_name = None

    mock_pipeline_config.get_steps.return_value = [step_with_pkg, step_no_pkg]

    assert config.find_package_name_by_class("FasterWhisperTranscriber") == "dorsal-whisper"

    assert config.find_package_name_by_class("LocalModel") is None

    assert config.find_package_name_by_class("NonExistentModel") is None


def test_unregister_model_success(mock_pipeline_config):
    """Tests successful removal of a model by package/module name."""
    step = MagicMock()

    step.annotation_model.module = "dorsal_whisper.model"
    mock_pipeline_config.get_steps.return_value = [step]

    config.unregister_model("dorsal-whisper", scope="project")

    mock_pipeline_config.remove_step_by_index.assert_called_once_with(index=0, scope="project")


def test_unregister_model_not_found(mock_pipeline_config):
    """Tests that unregister_model raises KeyError when no match is found."""
    step = MagicMock()
    step.annotation_model.module = "dorsal.other_plugin"
    mock_pipeline_config.get_steps.return_value = [step]

    with pytest.raises(KeyError, match="Could not find model for 'missing-plugin'"):
        config.unregister_model("missing-plugin")


def test_unregister_model_invalid_scope():
    """Tests unregister_model validation for the scope argument."""
    with pytest.raises(ValueError, match="Invalid scope"):
        config.unregister_model("any-pkg", scope="invalid_scope")


def test_unregister_model_empty_pipeline(mock_pipeline_config):
    """Tests unregister_model behavior when the pipeline is empty."""
    mock_pipeline_config.get_steps.return_value = []

    with pytest.raises(KeyError, match="Could not find model for 'any-pkg'"):
        config.unregister_model("any-pkg")


def test_register_model_missing_schema_id_raises_error():
    """Tests that a ValueError is raised when schema_id is omitted and cannot be inferred."""
    with pytest.raises(ValueError, match="A 'schema_id' must be provided explicitly"):
        config.register_model(DummyModel, schema_id=None, validation_model=None)


def test_register_model_infers_schema_id_from_pydantic(mock_pipeline_config):
    """Tests that a schema_id is correctly inferred and formatted from a Pydantic class."""

    class MyAwesomeValidator:
        pass

    with (
        patch("dorsal.common.model.is_pydantic_model_class", return_value=True),
        patch("dorsal.api.config.ModelRunnerPipelineStep") as step_mock,
    ):
        step_mock.model_validate.return_value.model_dump.return_value = {"valid": "data"}

        config.register_model(DummyModel, schema_id=None, validation_model=MyAwesomeValidator)

        call_args = step_mock.model_validate.call_args[0][0]

        assert call_args["schema_id"] == "pydantic/my-awesome-validator"


def test_register_model_infers_open_schema_validator(mock_pipeline_config):
    """Tests that 'open/' schemas automatically map to the correct validation_model tuple."""
    with patch("dorsal.api.config.ModelRunnerPipelineStep") as step_mock:
        step_mock.model_validate.return_value.model_dump.return_value = {"valid": "data"}

        config.register_model(DummyModel, schema_id="open/my-test-schema", validation_model=None)

        call_args = step_mock.model_validate.call_args[0][0]

        assert call_args["validation_model"] == (
            "dorsal.file.validators.open_schema",
            "my_test_schema_validator",
        )


@pytest.fixture
def mock_set_config_value():
    with patch("dorsal.api.config.set_config_value") as mock:
        yield mock


def test_set_compression_valid_mode(mock_set_config_value):
    """Tests setting a valid compression mode."""
    from dorsal.common import constants

    config.set_compression(mode="zstd")
    mock_set_config_value.assert_called_once_with(
        constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_MODE, "zstd", scope="project"
    )


def test_set_compression_invalid_mode(mock_set_config_value):
    """Tests that an invalid compression mode raises a ValueError."""
    with pytest.raises(ValueError, match="Unsupported compression mode 'gzip'"):
        config.set_compression(mode="gzip")

    mock_set_config_value.assert_not_called()


def test_set_compression_valid_level(mock_set_config_value):
    """Tests setting a valid compression level."""
    from dorsal.common import constants

    config.set_compression(level=5)
    mock_set_config_value.assert_called_once_with(
        constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_LEVEL, 5, scope="project"
    )


def test_set_compression_invalid_level_type(mock_set_config_value):
    """Tests that a non-integer compression level raises a ValueError."""
    with pytest.raises(ValueError, match="Compression level must be an integer between 0 and 22."):
        config.set_compression(level="5")

    mock_set_config_value.assert_not_called()


def test_set_compression_invalid_level_range(mock_set_config_value):
    """Tests that out-of-bounds compression levels raise a ValueError."""
    with pytest.raises(ValueError, match="Compression level must be an integer between 0 and 22."):
        config.set_compression(level=-1)

    with pytest.raises(ValueError, match="Compression level must be an integer between 0 and 22."):
        config.set_compression(level=23)

    mock_set_config_value.assert_not_called()


def test_set_compression_both_valid_and_scope(mock_set_config_value):
    """Tests setting both mode and level simultaneously with a custom scope."""
    from dorsal.common import constants

    config.set_compression(mode="zlib", level=9, scope="global")

    assert mock_set_config_value.call_count == 2
    mock_set_config_value.assert_any_call(
        constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_MODE, "zlib", scope="global"
    )
    mock_set_config_value.assert_any_call(
        constants.CONFIG_SECTION_INDEX, constants.CONFIG_OPTION_COMPRESSION_LEVEL, 9, scope="global"
    )


def test_set_compression_no_args(mock_set_config_value):
    """Tests that calling without arguments does not write to config."""
    config.set_compression()
    mock_set_config_value.assert_not_called()
