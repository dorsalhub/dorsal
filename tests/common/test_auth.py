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
from pathlib import Path
from unittest.mock import patch, call
import os
from importlib import reload

from dorsal.common import auth, constants
from dorsal.common.exceptions import AuthError


@patch("os.getenv")
def test_get_api_key_from_env(mock_getenv):
    """Test retrieving the API key from environment variables."""
    mock_getenv.return_value = "env_key_123"
    assert auth.get_api_key_from_env() == "env_key_123"
    mock_getenv.assert_called_once_with(constants.ENV_DORSAL_API_KEY_STR)


@patch("dorsal.common.auth.load_config")
def test_get_api_key_from_config(mock_load_config):
    """Test retrieving the API key from the config file."""

    mock_load_config.return_value = (
        {constants.CONFIG_SECTION_AUTH: {constants.CONFIG_OPTION_API_KEY: "config_key_456"}},
        "/fake/path/dorsal.toml",
    )
    assert auth.get_api_key_from_config() == "config_key_456"


@patch("dorsal.common.auth.load_config")
def test_get_email_from_config(mock_load_config):
    """Test retrieving the email from the config file."""
    mock_load_config.return_value = (
        {constants.CONFIG_SECTION_AUTH: {constants.CONFIG_OPTION_EMAIL: "user@example.com"}},
        "/fake/path/dorsal.toml",
    )
    assert auth.get_email_from_config() == "user@example.com"


@patch("dorsal.common.auth.get_global_config_path")
@patch("dorsal.common.auth.load_config")
@patch("dorsal.common.auth.get_project_level_config")
@patch("dorsal.common.auth.get_api_key_from_env")
def test_get_api_key_details(mock_from_env, mock_from_project, mock_from_global, mock_global_path):
    """Test the logic for determining the source of the API key."""

    mock_from_env.return_value = "env_key"
    details = auth.get_api_key_details()
    assert details["source"] == auth.APIKeySource.ENV
    assert details["value"] == "env_key"

    mock_from_env.return_value = None
    proj_path = str(Path("/proj/dorsal.toml"))
    mock_from_project.return_value = ({"auth": {"api_key": "project_key"}}, proj_path)

    details = auth.get_api_key_details()
    assert details["source"] == auth.APIKeySource.PROJECT
    assert details["value"] == "project_key"
    assert details["path"] == proj_path

    mock_from_project.return_value = ({}, None)

    global_path = str(Path("/global/dorsal.toml"))
    mock_from_global.return_value = ({"auth": {"api_key": "global_key"}}, global_path)
    mock_global_path.return_value = global_path

    details = auth.get_api_key_details()
    assert details["source"] == auth.APIKeySource.GLOBAL
    assert details["value"] == "global_key"


@patch("dorsal.common.auth.get_api_key_from_env")
@patch("dorsal.common.auth.get_project_level_config")
@patch("dorsal.common.auth.load_config")
def test_read_api_key_precedence(mock_load_config, mock_project_config, mock_from_env):
    """Test the order of precedence for reading the API key."""

    assert auth.read_api_key(api_key="arg_key") == "arg_key"

    mock_from_env.return_value = "env_key"
    assert auth.read_api_key() == "env_key"

    mock_from_env.return_value = None
    mock_project_config.return_value = ({}, None)
    mock_load_config.return_value = (
        {"auth": {"api_key": "config_key"}},
        "/fake/path/dorsal.toml",
    )
    assert auth.read_api_key() == "config_key"


def test_read_api_key_not_found():
    """Test that None is returned if no key is found."""
    with patch.dict(os.environ, {}):
        with patch("dorsal.common.auth.get_api_key_details", return_value={"value": None}):
            assert auth.read_api_key() is None


@patch("dorsal.common.auth.set_config_value")
def test_write_auth_config(mock_set_config):
    """Test writing both api_key and email to config."""
    auth.write_auth_config(api_key="new_key", email="new@email.com")

    expected_calls = [
        call(section="auth", option="api_key", value="new_key", scope="global"),
        call(section="auth", option="email", value="new@email.com", scope="global"),
    ]
    mock_set_config.assert_has_calls(expected_calls, any_order=True)

    mock_set_config.reset_mock()

    auth.write_auth_config(api_key="global_key", email="global@email.com", scope="global")
    expected_global_calls = [
        call(section="auth", option="api_key", value="global_key", scope="global"),
        call(section="auth", option="email", value="global@email.com", scope="global"),
    ]
    mock_set_config.assert_has_calls(expected_global_calls, any_order=True)


@patch("dorsal.common.auth.remove_config_value")
def test_remove_api_key(mock_remove_config):
    """Test removing the api_key from a specified config scope."""

    auth.remove_api_key(scope=auth.APIKeySource.PROJECT)
    mock_remove_config.assert_called_with(
        section=constants.CONFIG_SECTION_AUTH, option=constants.CONFIG_OPTION_API_KEY, scope="project"
    )

    auth.remove_api_key(scope=auth.APIKeySource.GLOBAL)
    mock_remove_config.assert_called_with(
        section=constants.CONFIG_SECTION_AUTH, option=constants.CONFIG_OPTION_API_KEY, scope="global"
    )


@patch("dorsal.common.auth.set_config_value")
def test_write_ui_config(mock_set_config):
    """Test writing ui preferences to the config."""

    # Test writing multiple values
    auth.write_ui_config(theme="dorsal_dark", icons="ascii", borders="none", scope="project")

    expected_calls = [
        call(
            section=constants.CONFIG_SECTION_UI,
            option=constants.CONFIG_OPTION_THEME,
            value="dorsal_dark",
            scope="project",
        ),
        call(section=constants.CONFIG_SECTION_UI, option=constants.CONFIG_OPTION_ICONS, value="ascii", scope="project"),
        call(
            section=constants.CONFIG_SECTION_UI, option=constants.CONFIG_OPTION_BORDERS, value="none", scope="project"
        ),
    ]
    mock_set_config.assert_has_calls(expected_calls, any_order=True)

    mock_set_config.reset_mock()

    # Test writing a single value
    auth.write_ui_config(borders="ascii", scope="global")
    mock_set_config.assert_called_once_with(
        section=constants.CONFIG_SECTION_UI, option=constants.CONFIG_OPTION_BORDERS, value="ascii", scope="global"
    )
