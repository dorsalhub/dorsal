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

import pytest
from unittest.mock import patch

from dorsal.common import constants
from dorsal.file.index import config


class TestIndexConfig:
    @patch("os.getenv")
    def test_get_index_enabled_from_env_none(self, mock_getenv):
        """Hits the `if env_var is None: return None` condition."""
        mock_getenv.return_value = None
        assert config._get_index_enabled_from_env() is None

    @pytest.mark.parametrize(
        "env_val, expected",
        [
            ("false", False),
            ("0", False),
            ("no", False),
            ("NO", False),
            ("true", True),
            ("1", True),
            ("yes", True),
            ("anything_else", True),
        ],
    )
    @patch("os.getenv")
    def test_get_index_enabled_from_env_values(self, mock_getenv, env_val, expected):
        """Tests the boolean resolution of the environment variable."""
        mock_getenv.return_value = env_val
        assert config._get_index_enabled_from_env() is expected

    @patch("dorsal.file.index.config.load_config")
    def test_get_index_enabled_from_config_bool(self, mock_load_config):
        """Tests a valid boolean configuration."""
        mock_config = {constants.CONFIG_SECTION_INDEX: {constants.CONFIG_OPTION_ENABLED: False}}
        mock_load_config.return_value = (mock_config, None)
        assert config._get_index_enabled_from_config() is False

    @patch("dorsal.file.index.config.load_config")
    def test_get_index_enabled_from_config_none(self, mock_load_config):
        """Tests when the configuration is missing or None."""
        mock_load_config.return_value = ({}, None)
        assert config._get_index_enabled_from_config() is None

    @patch("dorsal.file.index.config.logger.warning")
    @patch("dorsal.file.index.config.load_config")
    def test_get_index_enabled_from_config_invalid_type(self, mock_load_config, mock_warning):
        """Hits the `logger.warning` and `return None` fallback for invalid types."""
        mock_config = {constants.CONFIG_SECTION_INDEX: {constants.CONFIG_OPTION_ENABLED: "not_a_boolean"}}
        mock_load_config.return_value = (mock_config, None)

        assert config._get_index_enabled_from_config() is None
        mock_warning.assert_called_once()
        assert "Invalid value" in mock_warning.call_args[0][0]

    @patch("os.getenv")
    def test_get_index_compression_from_env_none(self, mock_getenv):
        """Hits the `if env_var is None: return None` condition for compression."""
        mock_getenv.return_value = None
        assert config._get_index_compression_from_env() is None

    @pytest.mark.parametrize(
        "env_val, expected",
        [
            ("false", False),
            ("0", False),
            ("no", False),
            ("true", True),
            ("1", True),
        ],
    )
    @patch("os.getenv")
    def test_get_index_compression_from_env_values(self, mock_getenv, env_val, expected):
        """Tests the boolean resolution of the compression environment variable."""
        mock_getenv.return_value = env_val
        assert config._get_index_compression_from_env() is expected

    @patch("dorsal.file.index.config.load_config")
    def test_get_index_compression_from_config_bool(self, mock_load_config):
        """Tests a valid boolean configuration for compression."""
        mock_config = {constants.CONFIG_SECTION_INDEX: {constants.CONFIG_OPTION_COMPRESSION: True}}
        mock_load_config.return_value = (mock_config, None)
        assert config._get_index_compression_from_config() is True

    @patch("dorsal.file.index.config.load_config")
    def test_get_index_compression_from_config_none(self, mock_load_config):
        """Tests when the compression configuration is missing or None."""
        mock_load_config.return_value = ({}, None)
        assert config._get_index_compression_from_config() is None

    @patch("dorsal.file.index.config.logger.warning")
    @patch("dorsal.file.index.config.load_config")
    def test_get_index_compression_from_config_invalid_type(self, mock_load_config, mock_warning):
        """Hits the `logger.warning` and `return None` fallback for invalid compression types."""
        mock_config = {constants.CONFIG_SECTION_INDEX: {constants.CONFIG_OPTION_COMPRESSION: 12345}}
        mock_load_config.return_value = (mock_config, None)

        assert config._get_index_compression_from_config() is None
        mock_warning.assert_called_once()
        assert "Invalid value" in mock_warning.call_args[0][0]

    @patch("dorsal.file.index.config.resolve_setting")
    def test_get_index_enabled(self, mock_resolve):
        """Ensures the wrapper passes the correct callables to resolve_setting."""
        mock_resolve.return_value = True

        result = config.get_index_enabled(use_index=False)

        assert result is True
        mock_resolve.assert_called_once_with(
            setting_name="index_enabled",
            explicit_value=False,
            env_getter=config._get_index_enabled_from_env,
            config_getter=config._get_index_enabled_from_config,
            default_value=True,
        )

    @patch("dorsal.file.index.config.resolve_setting")
    def test_get_index_compression(self, mock_resolve):
        """Ensures the wrapper passes the correct callables to resolve_setting."""
        mock_resolve.return_value = False

        result = config.get_index_compression(compress=True)

        assert result is False
        mock_resolve.assert_called_once_with(
            setting_name="index_compression",
            explicit_value=True,
            env_getter=config._get_index_compression_from_env,
            config_getter=config._get_index_compression_from_config,
            default_value=True,
        )
