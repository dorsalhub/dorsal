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

import hashlib
import pytest
import os
import logging
from pathlib import Path
import time

import blake3
from rich.console import Console

from dorsal.common import constants
from dorsal.common import cli as common_cli
from dorsal.file.index.dorsal_index import DorsalIndex
from dorsal.file.validators.file_record import FileRecordStrict
from dorsal.session import clear_shared_index


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
    clear_shared_index()
    yield
    clear_shared_index()


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
    mock_console = mocker.MagicMock(spec=Console)

    mock_console.time = 0.0

    mock_console.is_terminal = False
    mock_console.is_interactive = False

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


@pytest.fixture
def make_mock_record():
    """Factory to create bulletproof FileRecordStrict objects for testing."""

    def _make(
        abspath: str, ext: str = ".pdf", size: int = 1024, tags: dict = None, arxiv_title: str = None
    ) -> FileRecordStrict:

        dummy_sha256 = hashlib.sha256(abspath.encode("utf-8")).hexdigest()
        dummy_blake3 = blake3.blake3(abspath.encode("utf-8")).hexdigest()

        annotations = {
            "file/base": {
                "record": {
                    "hash": dummy_sha256,
                    "name": Path(abspath).name,
                    "extension": ext,
                    "size": size,
                    "media_type": f"application/{ext.strip('.')}",
                    "all_hash_ids": {"SHA-256": dummy_sha256, "BLAKE3": dummy_blake3},
                },
                "schema_id": "file/base",
                "source": {"type": "Model", "id": "test_mock", "version": "1.0"},
            }
        }

        if arxiv_title:
            annotations["dorsal/arxiv"] = {
                "record": {
                    "title": arxiv_title,
                    "authors": ["John Doe", "Jane Smith"],
                    "categories": ["astro-ph"],
                    "arxiv_id": "1234.5678",
                },
                "schema_id": "dorsal/arxiv",
                "source": {"type": "Model", "id": "test_mock", "version": "1.0"},
            }

        tag_list = []
        if tags:
            tag_list = [
                {"name": k, "value": v, "hidden": False, "upvotes": 0, "downvotes": 0, "origin": "dorsal.LocalFile"}
                for k, v in tags.items()
            ]

        record_dict = {
            "hash": dummy_sha256,
            "validation_hash": dummy_blake3,
            "annotations": annotations,
            "tags": tag_list,
            "urls": [],
            "source": "disk",
        }

        return FileRecordStrict.model_validate(record_dict)

    return _make


@pytest.fixture
def test_index(tmp_path, make_mock_record) -> DorsalIndex:
    """
    Spins up a temporary SQLite database, populates it with 3 distinct
    file records, and yields the index for testing.
    """
    db_path = tmp_path / "test_cache.db"
    index = DorsalIndex(db_path=db_path, use_compression=False)

    rec1 = make_mock_record("/tmp/report.pdf", ext=".pdf", size=5000000, tags={"status": "draft"})
    index.upsert_record(path="/tmp/report.pdf", modified_time=time.time(), record=rec1)

    rec2 = make_mock_record("/tmp/video.mp4", ext=".mp4", size=2000000000, tags={"project": "alpha"})
    index.upsert_record(path="/tmp/video.mp4", modified_time=time.time(), record=rec2)

    rec3 = make_mock_record(
        "/tmp/paper.pdf", ext=".pdf", size=1500000, arxiv_title="Machine Learning for Dark Matter Detection"
    )
    index.upsert_record(path="/tmp/paper.pdf", modified_time=time.time(), record=rec3)

    yield index

    index.close()
