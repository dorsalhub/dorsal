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

import os
import logging
from typing import Literal, cast

from dorsal.common import constants
from dorsal.common.config import load_config, resolve_setting

logger = logging.getLogger(__name__)


def _get_index_enabled_from_env() -> bool | None:
    """Reads the DORSAL_INDEX_ENABLED environment variable."""
    env_var = os.getenv(constants.ENV_DORSAL_INDEX_ENABLED)
    if env_var is None:
        return None
    return env_var.lower() not in ("false", "0", "no")


def _get_index_enabled_from_config() -> bool | None:
    """Reads the 'enabled' flag from the [index] section of dorsal.toml."""
    config, _ = load_config()
    config_val = config.get(constants.CONFIG_SECTION_INDEX, {}).get(constants.CONFIG_OPTION_ENABLED)

    if not isinstance(config_val, bool):
        if config_val is not None:
            logger.warning("Invalid value '%s' for enabled flag in config. Ignoring.", config_val)
        return None

    return config_val


def get_index_enabled(use_index: bool | None = None) -> bool:
    """Resolves whether the index is enabled with standard precedence."""
    return resolve_setting(
        setting_name="index_enabled",
        explicit_value=use_index,
        env_getter=_get_index_enabled_from_env,
        config_getter=_get_index_enabled_from_config,
        default_value=True,
    )


def _get_index_compression_from_env() -> bool | None:
    """Reads the DORSAL_INDEX_COMPRESSION environment variable."""
    env_var = os.getenv(constants.ENV_DORSAL_INDEX_COMPRESSION)
    if env_var is None:
        return None
    return env_var.lower() not in ("false", "0", "no")


def _get_index_compression_from_config() -> bool | None:
    """Reads the 'compression' flag from the [index] section of dorsal.toml."""
    config, _ = load_config()
    config_val = config.get(constants.CONFIG_SECTION_INDEX, {}).get(constants.CONFIG_OPTION_COMPRESSION)

    if not isinstance(config_val, bool):
        if config_val is not None:
            logger.warning(
                "Invalid value '%s' for compression flag in config. Ignoring.",
                config_val,
            )
        return None

    return config_val


def get_index_compression(compress: bool | None = None) -> bool:
    """Resolves whether index compression is enabled with standard precedence."""
    return resolve_setting(
        setting_name="index_compression",
        explicit_value=compress,
        env_getter=_get_index_compression_from_env,
        config_getter=_get_index_compression_from_config,
        default_value=True,
    )


def get_index_compression_mode() -> Literal["zlib", "zstd"]:
    """Resolves the target compression mode for the search index."""
    merged_config, _ = load_config()

    config_val = merged_config.get(constants.CONFIG_SECTION_INDEX, {}).get(constants.CONFIG_OPTION_COMPRESSION_MODE)

    mode = resolve_setting(
        setting_name="Index Compression Algorithm",
        explicit_value=None,
        env_getter=lambda: os.getenv(constants.ENV_DORSAL_INDEX_COMPRESSION_MODE),
        config_getter=lambda: config_val,
        default_value="zlib",
    ).lower()

    if mode not in ("zlib", "zstd"):
        logger.warning(f"Invalid index compression algorithm '{mode}'. Falling back to 'zlib'.")
        return "zlib"

    return cast(Literal["zlib", "zstd"], mode)


def get_index_compression_level(compression_mode: Literal["zlib", "zstd"] | None = None) -> int:
    """Resolves the compression level. If no level is specified in the config,"""
    merged_config, _ = load_config()

    if compression_mode is None:
        compression_mode = get_index_compression_mode()

    default_level = 3 if compression_mode == "zstd" else 6

    config_val = merged_config.get(constants.CONFIG_SECTION_INDEX, {}).get(constants.CONFIG_OPTION_COMPRESSION_LEVEL)

    level_str = resolve_setting(
        setting_name="Index Compression Level",
        explicit_value=None,
        env_getter=lambda: os.getenv(constants.ENV_DORSAL_INDEX_COMPRESSION_LEVEL),
        config_getter=lambda: config_val,
        default_value=str(default_level),
    )

    try:
        return int(level_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid compression level '{level_str}'. Falling back to {default_level}.")
        return default_level
