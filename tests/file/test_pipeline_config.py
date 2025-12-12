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
from unittest.mock import MagicMock, patch
import tomlkit
from dorsal.api import config as config_api
from dorsal.common.exceptions import DorsalError, DorsalConfigError
from dorsal.common.model import AnnotationModel
from dorsal.file.pipeline_config import PipelineConfig


class MockAnnotationModel(AnnotationModel):
    """A dummy model for registration tests."""

    id = "test/mock"
    version = "0.1.0"

    def main(self):
        return {}


MockAnnotationModel.__module__ = "dorsal.tests.dummy_model"
MockAnnotationModel.__name__ = "MockModel"


@pytest.fixture
def clean_config_environment(tmp_path):
    """
    Redirects config operations to a temporary directory.
    Forces the environment to look like a fresh project with NO config file initially.
    """
    fake_config_path = tmp_path / "dorsal.toml"

    with (
        patch("dorsal.common.config.find_project_config_path", return_value=fake_config_path),
        patch("dorsal.file.pipeline_config.config.find_project_config_path", return_value=fake_config_path),
    ):
        # Ensure we start with a clean slate for the cache
        from dorsal.common.config import load_config

        load_config.cache_clear()

        yield fake_config_path


def test_register_hydrates_defaults_into_empty_config(clean_config_environment):
    """
    Critical Fix Verification:
    Ensures that registering a model into an empty project config
    does NOT wipe out the default pipeline.
    """
    # 1. Register a new model into a non-existent dorsal.toml
    config_api.register_model(annotation_model=MockAnnotationModel, schema_id="test/schema", scope="project")

    # 2. Read the actual file from disk
    with open(clean_config_environment, "r") as f:
        doc = tomlkit.load(f)

    pipeline = doc["model_pipeline"]

    # 3. Assertions
    # We expect the defaults (~5 models) + our new model (1) = ~6 total
    # If the bug existed, len would be 1.
    assert len(pipeline) > 1, "Pipeline defaults were wiped out! Only the new model exists."

    # Verify our model is at the end
    last_step = pipeline[-1]
    assert last_step["annotation_model"] == ["dorsal.tests.dummy_model", "MockModel"]
    assert last_step["schema_id"] == "test/schema"


def test_register_prevents_duplicates(clean_config_environment):
    """Ensures we cannot accidentally add the exact same model twice."""
    # Register once
    config_api.register_model(annotation_model=MockAnnotationModel, schema_id="test/schema", scope="project")

    # Try to register again without overwrite
    with pytest.raises(DorsalConfigError) as exc:
        config_api.register_model(annotation_model=MockAnnotationModel, schema_id="test/schema", scope="project")
    assert "already exists" in str(exc.value)

    # Register with overwrite (should succeed and not increase length)
    config_api.register_model(
        annotation_model=MockAnnotationModel, schema_id="test/schema", overwrite=True, scope="project"
    )

    pipeline = config_api.get_model_pipeline(scope="project")
    # Count occurrences of our mock model
    matches = [s for s in pipeline if s.annotation_model.name == "MockModel"]
    assert len(matches) == 1


def test_base_model_safety(clean_config_environment):
    """Ensures the Base Model (Index 0) cannot be tampered with via API."""
    # Hydrate config first
    config_api.register_model(MockAnnotationModel, "test/schema")

    # 1. Try to Remove Index 0
    with pytest.raises(DorsalError) as exc:
        config_api.remove_model_by_index(0, scope="project")
    assert "Cannot remove the Base Model" in str(exc.value)

    # 2. Try to Deactivate Index 0
    with pytest.raises(DorsalError) as exc:
        config_api.deactivate_model_by_index(0, scope="project")
    assert "Cannot deactivate the Base Model" in str(exc.value)

    # 3. Try to Remove by Name (FileCoreAnnotationModel)
    with pytest.raises(DorsalError) as exc:
        config_api.remove_model_by_name("FileCoreAnnotationModel", scope="project")
    assert "Cannot remove the Base Model" in str(exc.value)


def test_ambiguity_check(clean_config_environment):
    """Ensures generic naming operations fail if names are duplicated."""
    # Manually create a "corrupt" config with duplicates
    # We add MockModel twice manually to bypass the upsert checks
    dup_step = {"annotation_model": ["dorsal.tests", "DuplicateModel"], "schema_id": "test/dup1"}

    # Use internal method to force append twice
    PipelineConfig.upsert_step(dup_step, scope="project")  # Add 1

    # Force add a second one by manually appending to the TOML file
    # (Since upsert_step prevents duplicates normally)
    with open(clean_config_environment, "r") as f:
        doc = tomlkit.load(f)
    doc["model_pipeline"].append(dup_step)
    with open(clean_config_environment, "w") as f:
        tomlkit.dump(doc, f)

    # Now try to act on it by name
    with pytest.raises(ValueError) as exc:
        config_api.activate_model_by_name("DuplicateModel", scope="project")

    assert "Ambiguous model name 'DuplicateModel'" in str(exc.value)
    assert "occurrences at indices" in str(exc.value)


def test_activation_toggles_flag(clean_config_environment):
    """Verifies that deactivate/activate correctly sets the TOML flag."""
    config_api.register_model(MockAnnotationModel, "test/schema")

    # 1. Deactivate
    config_api.deactivate_model_by_name("MockModel", scope="project")

    steps = config_api.get_model_pipeline(scope="project")
    target = next(s for s in steps if s.annotation_model.name == "MockModel")
    assert target.deactivated is True

    # 2. Activate
    config_api.activate_model_by_name("MockModel", scope="project")

    steps = config_api.get_model_pipeline(scope="project")
    target = next(s for s in steps if s.annotation_model.name == "MockModel")
    assert target.deactivated is False


def test_remove_works_with_negative_index(clean_config_environment):
    """Verifies that -1 works as expected."""
    config_api.register_model(MockAnnotationModel, "test/schema")

    # Get current count
    initial_len = len(config_api.get_model_pipeline(scope="project"))

    # Remove last
    config_api.remove_model_by_index(-1, scope="project")

    new_len = len(config_api.get_model_pipeline(scope="project"))
    assert new_len == initial_len - 1
