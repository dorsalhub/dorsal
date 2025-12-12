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

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from dorsal.client.dorsal_client import DorsalClient
from dorsal.common.auth import is_offline_mode
from dorsal.common.exceptions import DorsalOfflineError
from dorsal.file.cache.dorsal_cache import DorsalCache
from dorsal.file.cache.config import get_cache_compression, get_cache_enabled

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dorsal.file.metadata_reader import MetadataReader

_DORSAL_CLIENT: DorsalClient | None = None
_DORSAL_CACHE: DorsalCache | None = None
_METADATA_READER: MetadataReader | None = None


def get_shared_dorsal_client(api_key: str | None = None) -> DorsalClient:
    """Retrieve or create a global `DorsalClient` instance.

    Used by default if no specific `DorsalClient` is provided by the user.

    Note: when passed, 'api_key' only used if shared client instance does not already exist. so if
          overriding API Key is the goal, pass it directly to the DorsalClient method as well.

    """
    if is_offline_mode():
        raise DorsalOfflineError(
            "Cannot retrieve shared DorsalClient: DORSAL_OFFLINE is active. "
            "Communication with DorsalHub API is blocked."
        )
    global _DORSAL_CLIENT
    if _DORSAL_CLIENT is None:
        logger.debug("Initializing shared DorsalClient instance")
        _DORSAL_CLIENT = DorsalClient(api_key=api_key)
    elif api_key is not None and _DORSAL_CLIENT.api_key != api_key:
        logger.warning("Shared DorsalClient already exists. The provided api_key will be ignored.")
    return _DORSAL_CLIENT


def set_shared_dorsal_client(client: DorsalClient) -> None:
    """Sets the global `DorsalClient` instance.

    Allows users to provide their own pre-configured client instance
    to be used as the default by the library.
    """
    global _DORSAL_CLIENT
    logger.debug("Setting shared DorsalClient instance")
    _DORSAL_CLIENT = client


def clear_shared_dorsal_client() -> None:
    """Clears the global `DorsalClient` instance."""
    global _DORSAL_CLIENT
    _DORSAL_CLIENT = None
    logger.debug("Cleared shared DorsalClient instance")


def set_shared_cache(cache: DorsalCache) -> None:
    """Sets the global `DorsalCache` instance."""
    global _DORSAL_CACHE
    logger.debug("Setting shared DorsalCache instance")
    _DORSAL_CACHE = cache


def get_shared_cache() -> DorsalCache:
    global _DORSAL_CACHE
    if _DORSAL_CACHE is None:
        _DORSAL_CACHE = DorsalCache(use_compression=get_cache_compression())
    return _DORSAL_CACHE


def clear_shared_cache() -> None:
    """Clears the global DorsalCache instance."""
    global _DORSAL_CACHE
    if _DORSAL_CACHE is not None:
        try:
            _DORSAL_CACHE.close()
        except Exception as e:
            logger.warning(f"Error closing shared cache: {e}")

    _DORSAL_CACHE = None
    logger.debug("Cleared shared DorsalCache instance")


def get_metadata_reader() -> MetadataReader:
    """Get or create a shared global `MetadataReader` instance.

    This instance is initialized with default settings, including API key
    resolution from environment variables if not explicitly configured.
    It's used by high-level API functions when no specific `api_key`
    is provided to them.

    Returns:
        MetadataReader: The shared `MetadataReader` instance.
    """
    from dorsal.file.metadata_reader import MetadataReader

    global _METADATA_READER
    if _METADATA_READER is None:
        logger.debug("Initializing shared MetadataReader instance for dorsal.api.file module.")
        _METADATA_READER = MetadataReader()
    return _METADATA_READER
