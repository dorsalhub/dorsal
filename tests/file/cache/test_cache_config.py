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
from unittest.mock import patch
import os

from dorsal.file.cache import config as cache_config
from dorsal.common import constants


@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("any_other_string", True),
        ("false", False),
        ("0", False),
        ("no", False),
        (None, None),
    ],
)
def test_get_cache_enabled_from_env(env_value, expected):
    """Test parsing of the DORSAL_CACHE_ENABLED environment variable."""

    # Helper context manager to handle both setting and DELETING variables
    if env_value is None:
        # We must ensure the variable is absent, overriding the global fixture
        matcher = patch.dict(os.environ)
        matcher.start()
        os.environ.pop(constants.ENV_DORSAL_CACHE_ENABLED, None)
    else:
        matcher = patch.dict(os.environ, {constants.ENV_DORSAL_CACHE_ENABLED: env_value})
        matcher.start()

    try:
        assert cache_config._get_cache_enabled_from_env() is expected
    finally:
        matcher.stop()


@patch("dorsal.file.cache.config.load_config")
def test_get_cache_enabled_from_config(mock_load_config):
    """Test retrieving the 'enabled' boolean from the config file."""
    # Test when value is True
    mock_load_config.return_value = ({"cache": {"enabled": True}}, "/path")
    assert cache_config._get_cache_enabled_from_config() is True

    # Test when value is False
    mock_load_config.return_value = ({"cache": {"enabled": False}}, "/path")
    assert cache_config._get_cache_enabled_from_config() is False

    # Test when section/key is missing
    mock_load_config.return_value = ({}, "/path")
    assert cache_config._get_cache_enabled_from_config() is None

    # Test when value is not a boolean
    mock_load_config.return_value = ({"cache": {"enabled": "not_a_bool"}}, "/path")
    assert cache_config._get_cache_enabled_from_config() is None


@patch("dorsal.file.cache.config.resolve_setting")
def test_get_cache_enabled_orchestrator(mock_resolve_setting):
    """Test that get_cache_enabled correctly calls the resolver utility."""
    cache_config.get_cache_enabled(use_cache=True)

    mock_resolve_setting.assert_called_once_with(
        setting_name="cache_enabled",
        explicit_value=True,
        env_getter=cache_config._get_cache_enabled_from_env,
        config_getter=cache_config._get_cache_enabled_from_config,
        default_value=True,
    )


@patch("os.getenv")
def test_get_cache_compression_from_env(mock_getenv):
    """Test parsing of the DORSAL_CACHE_COMPRESSION environment variable."""
    mock_getenv.return_value = "false"
    assert cache_config._get_cache_compression_from_env() is False
    mock_getenv.assert_called_once_with(constants.ENV_DORSAL_CACHE_COMPRESSION)


@patch("dorsal.file.cache.config.load_config")
def test_get_cache_compression_from_config(mock_load_config):
    """Test retrieving the 'compression' boolean from the config file."""
    mock_load_config.return_value = ({"cache": {"compression": True}}, "/path")
    assert cache_config._get_cache_compression_from_config() is True


@patch("dorsal.file.cache.config.resolve_setting")
def test_get_cache_compression_orchestrator(mock_resolve_setting):
    """Test that get_cache_compression correctly calls the resolver utility."""
    cache_config.get_cache_compression(compress=False)

    mock_resolve_setting.assert_called_once_with(
        setting_name="cache_compression",
        explicit_value=False,
        env_getter=cache_config._get_cache_compression_from_env,
        config_getter=cache_config._get_cache_compression_from_config,
        default_value=True,
    )
