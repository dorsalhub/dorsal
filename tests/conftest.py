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

"""
This file contains shared fixtures and configuration for the pytest suite, specifically the CLI.

Problem:

`logging.basicConfig()`sets up a logging handler that attaches to the buffer for the *first test*.
In subsequent CLI tests, this handler still exists in memory but its buffer is now closed.
This causes a `ValueError: I/O operation on closed file` when a log message is emitted in a later test.

**Note:** This is a `CliRunner`I/O redirection issue and does not affect the CLI when run normally.

The `clean_logging` fixture (defined below with `autouse=True`) solves this testing issue.
It runs before every test and clears all existing handlers from the root logger.
This forces the CLI to re-initialize logging correctly for each new test's unique I/O buffer.

- To test command logic, arguments, and `print()` output, use the `CliRunner` and the `mock_rich_console` fixture.
- To test messages from `logging` use the `caplog` fixture.

"""

import pytest
import os
import logging
from unittest.mock import MagicMock
from rich.console import Console

from dorsal.common import constants
from dorsal.common import cli as common_cli
from dorsal.session import clear_shared_cache


@pytest.fixture(scope="session", autouse=True)
def global_disable_cache():
    """
    Sets the env var to disable cache for the entire test session.
    This prevents accidental SQLite file creation/locking.
    """
    os.environ[constants.ENV_DORSAL_CACHE_ENABLED] = "false"
    yield


@pytest.fixture(autouse=True)
def reset_dorsal_singletons():
    """
    Ensures every test starts with a clean slate.
    Closes any open cache connections from previous tests.
    """
    clear_shared_cache()
    yield
    clear_shared_cache()


@pytest.fixture(autouse=True)
def clean_logging():
    """
    (Auto-used) Clears all logging handlers before each test.
    """
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    yield


@pytest.fixture
def mock_rich_console(mocker):
    """
    Mocks the `get_rich_console` utility by directly patching its
    internal singleton cache, making it robust against test startup race conditions.
    """
    mock_console = mocker.MagicMock(spec=Console)

    mocker.patch.object(common_cli, "_console_instance", mock_console)
    return mock_console


@pytest.fixture
def mock_auth_app(mocker):
    """
    Mocks all backend dependencies for the `dorsal auth` commands.

    This isolates the CLI layer for focused testing of command logic, argument
    parsing, and user output.
    """
    mocker.patch("dorsal.session.get_shared_dorsal_client")
    mocker.patch("dorsal.common.config.load_config")
    mocker.patch("dorsal.session.clear_shared_dorsal_client")
    mocker.patch("dorsal.common.auth.write_auth_config")
    mocker.patch("dorsal.common.auth.remove_api_key")
    mocker.patch("dorsal.common.auth.get_api_key_from_env", return_value=None)
    mocker.patch("dorsal.client.DorsalClient")
