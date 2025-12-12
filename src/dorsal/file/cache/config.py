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
import logging

from dorsal.common import constants
from dorsal.common.config import load_config, resolve_setting

logger = logging.getLogger(__name__)


def _get_cache_enabled_from_env() -> bool | None:
    """Reads the DORSAL_CACHE_ENABLED environment variable."""
    env_var = os.getenv(constants.ENV_DORSAL_CACHE_ENABLED)
    if env_var is None:
        return None
    return env_var.lower() not in ("false", "0", "no")


def _get_cache_enabled_from_config() -> bool | None:
    """Reads the 'enabled' flag from the [cache] section of dorsal.toml."""
    config, _ = load_config()
    config_val = config.get(constants.CONFIG_SECTION_CACHE, {}).get(constants.CONFIG_OPTION_ENABLED)

    if not isinstance(config_val, bool):
        if config_val is not None:
            logger.warning("Invalid value '%s' for enabled flag in config. Ignoring.", config_val)
        return None

    return config_val


def get_cache_enabled(use_cache: bool | None = None) -> bool:
    """Resolves whether the cache is enabled with standard precedence."""
    return resolve_setting(
        setting_name="cache_enabled",
        explicit_value=use_cache,
        env_getter=_get_cache_enabled_from_env,
        config_getter=_get_cache_enabled_from_config,
        default_value=True,
    )


def _get_cache_compression_from_env() -> bool | None:
    """Reads the DORSAL_CACHE_COMPRESSION environment variable."""
    env_var = os.getenv(constants.ENV_DORSAL_CACHE_COMPRESSION)
    if env_var is None:
        return None
    return env_var.lower() not in ("false", "0", "no")


def _get_cache_compression_from_config() -> bool | None:
    """Reads the 'compression' flag from the [cache] section of dorsal.toml."""
    config, _ = load_config()
    config_val = config.get(constants.CONFIG_SECTION_CACHE, {}).get(constants.CONFIG_OPTION_COMPRESSION)

    if not isinstance(config_val, bool):
        if config_val is not None:
            logger.warning(
                "Invalid value '%s' for compression flag in config. Ignoring.",
                config_val,
            )
        return None

    return config_val


def get_cache_compression(compress: bool | None = None) -> bool:
    """Resolves whether cache compression is enabled with standard precedence."""
    return resolve_setting(
        setting_name="cache_compression",
        explicit_value=compress,
        env_getter=_get_cache_compression_from_env,
        config_getter=_get_cache_compression_from_config,
        default_value=True,
    )
