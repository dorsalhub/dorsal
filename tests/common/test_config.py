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
import os
from unittest.mock import MagicMock, patch
import pathlib

import pytest
import tomllib
import tomlkit

from dorsal.common import config
from dorsal.common import constants


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """Fixture to automatically clear the lru_cache on load_config before each test."""
    config.load_config.cache_clear()
    yield
    config.load_config.cache_clear()


def test_find_project_config_path_in_current_dir(fs):
    """Test finding a config file in the current directory."""
    # Use os.path.join to create platform-agnostic paths
    project_path_str = os.path.join("my", "project")
    config_file_str = os.path.join(project_path_str, "dorsal.toml")

    fs.create_file(config_file_str)

    with patch("pathlib.Path.cwd", return_value=pathlib.Path(project_path_str)):
        found_path = config.find_project_config_path()

    assert str(found_path) == config_file_str


def test_find_project_config_path_in_parent_dir(fs):
    """Test finding a config file by walking up from a subdirectory."""
    project_path_str = os.path.join("my", "project")
    subdir_path_str = os.path.join(project_path_str, "subdir", "deep")
    config_file_str = os.path.join(project_path_str, "dorsal.toml")

    fs.create_file(config_file_str)
    fs.create_dir(subdir_path_str)

    with patch("pathlib.Path.cwd", return_value=pathlib.Path(subdir_path_str)):
        found_path = config.find_project_config_path()

    assert str(found_path) == config_file_str


def test_find_project_config_path_not_found(fs):
    """Test that None is returned when no config file is in the tree."""
    fs.create_dir("/not/a/project/subdir")

    with patch("pathlib.Path.cwd", return_value=pathlib.Path("/not/a/project/subdir")):
        found_path = config.find_project_config_path()

    assert found_path is None


@patch("dorsal.common.config._create_default_global_config_if_not_exists")
def test_load_config_merges_project_over_global(mock_get_global, fs):
    """Test that project config settings correctly override global settings."""

    mock_get_global.return_value = {
        "auth": {"api_key": "global_key"},
    }

    project_path = "/my/project"
    project_config = {"auth": {"api_key": "project_key"}, "ui": {"theme": "dark"}}
    fs.create_file(f"{project_path}/dorsal.toml", contents=tomlkit.dumps(project_config))

    with patch("pathlib.Path.cwd", return_value=pathlib.Path(project_path)):
        final_config, _ = config.load_config()

    assert final_config["auth"]["api_key"] == "project_key"  # Overwritten by project
    assert final_config["ui"]["theme"] == "dark"  # Added by project


def test_set_config_value_creates_new_file(fs):
    """Test that set_config_value creates a new dorsal.toml if none is found."""
    project_path = "/my/new_project"
    fs.create_dir(project_path)

    with patch("pathlib.Path.cwd", return_value=pathlib.Path(project_path)):
        config.set_config_value(section="auth", option="api_key", value="my_new_key")

    config_file = pathlib.Path(project_path) / "dorsal.toml"
    assert config_file.exists()

    with open(config_file, "rb") as f:
        data = tomllib.load(f)
    assert data["auth"]["api_key"] == "my_new_key"


def test_remove_config_value_success(fs):
    """Test that a value can be successfully removed from a project config."""
    project_path = "/my/project"
    initial_config = {"auth": {"api_key": "key_to_delete", "email": "keep@me.com"}}
    fs.create_file(f"{project_path}/dorsal.toml", contents=tomlkit.dumps(initial_config))

    with patch("pathlib.Path.cwd", return_value=pathlib.Path(project_path)):
        was_removed = config.remove_config_value(section="auth", option="api_key")

    assert was_removed is True

    with open(f"{project_path}/dorsal.toml", "rb") as f:
        data = tomllib.load(f)
    assert "api_key" not in data["auth"]
    assert "email" in data["auth"]  # Ensure other keys remain


def test_remove_config_value_no_file_returns_false(fs):
    """Test that remove returns False if no project config exists."""
    fs.create_dir("/my/project")
    with patch("pathlib.Path.cwd", return_value=pathlib.Path("/my/project")):
        was_removed = config.remove_config_value(section="auth", option="api_key")
    assert was_removed is False


# --- Tests for resolve_setting ---


def test_resolve_setting_precedence():
    """Test the explicit > env > config > default precedence of resolve_setting."""
    setting_name = "test_setting"
    default = "default_value"

    env_getter = MagicMock(return_value="env_value")
    config_getter = MagicMock(return_value="config_value")

    result = config.resolve_setting(
        setting_name=setting_name,
        explicit_value="explicit_value",
        env_getter=env_getter,
        config_getter=config_getter,
        default_value=default,
    )
    assert result == "explicit_value"
    env_getter.assert_not_called()
    config_getter.assert_not_called()

    result = config.resolve_setting(
        setting_name=setting_name,
        explicit_value=None,
        env_getter=env_getter,
        config_getter=config_getter,
        default_value=default,
    )
    assert result == "env_value"
    env_getter.assert_called_once()
    config_getter.assert_not_called()
    env_getter.reset_mock()

    env_getter.return_value = None
    result = config.resolve_setting(
        setting_name=setting_name,
        explicit_value=None,
        env_getter=env_getter,
        config_getter=config_getter,
        default_value=default,
    )
    assert result == "config_value"
    env_getter.assert_called_once()
    config_getter.assert_called_once()

    config_getter.return_value = None
    result = config.resolve_setting(
        setting_name=setting_name,
        explicit_value=None,
        env_getter=env_getter,
        config_getter=config_getter,
        default_value=default,
    )
    assert result == default
