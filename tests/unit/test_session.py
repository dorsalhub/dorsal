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
from dorsal.session import (
    get_shared_dorsal_client,
    set_shared_dorsal_client,
    clear_shared_dorsal_client,
    get_shared_cache,
    set_shared_cache,
    clear_shared_cache,
    get_metadata_reader,
)
from dorsal.client.dorsal_client import DorsalClient
from dorsal.file.cache.dorsal_cache import DorsalCache


@pytest.fixture(autouse=True)
def clean_globals():
    """Reset global state before and after each test."""
    clear_shared_dorsal_client()
    clear_shared_cache()
    # _METADATA_READER doesn't have a public clear method in the snippet,
    # but it's less stateful.
    yield
    clear_shared_dorsal_client()
    clear_shared_cache()


def test_get_shared_client_init():
    client = get_shared_dorsal_client(api_key="test_key")
    assert isinstance(client, DorsalClient)
    assert client.api_key == "test_key"

    # Second call returns same instance
    client2 = get_shared_dorsal_client()
    assert client2 is client


def test_set_shared_client(mocker):
    mock_client = mocker.MagicMock(spec=DorsalClient)
    set_shared_dorsal_client(mock_client)

    assert get_shared_dorsal_client() is mock_client


def test_get_shared_cache_init():
    cache = get_shared_cache()
    assert isinstance(cache, DorsalCache)

    cache2 = get_shared_cache()
    assert cache2 is cache


def test_set_shared_cache(mocker):
    mock_cache = mocker.MagicMock(spec=DorsalCache)
    set_shared_cache(mock_cache)
    assert get_shared_cache() is mock_cache


def test_clear_shared_cache(mocker):
    mock_cache = mocker.MagicMock(spec=DorsalCache)
    set_shared_cache(mock_cache)

    clear_shared_cache()
    mock_cache.close.assert_called_once()

    # Next get should create new one
    assert get_shared_cache() is not mock_cache


def test_get_metadata_reader():
    # Just verify it returns the object and singleton behavior
    reader = get_metadata_reader()
    assert reader is not None
    assert get_metadata_reader() is reader
