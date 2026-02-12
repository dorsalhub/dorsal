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
from unittest.mock import patch, MagicMock
from importlib.metadata import PackageNotFoundError

from dorsal.registry import resolution
from dorsal.common.exceptions import DorsalError, AuthError


@pytest.fixture
def mock_dorsal_client():
    """Mock the registry client to avoid network calls."""
    with patch("dorsal.registry.resolution.get_shared_dorsal_client") as mock:
        yield mock.return_value


@pytest.fixture
def mock_find_package():
    """Mock the local config lookup."""
    with patch("dorsal.registry.resolution.find_package_name_by_class") as mock:
        yield mock


def test_resolve_registry_id_success(mock_dorsal_client):
    """
    If the target looks like a Registry ID (user/repo), we should fetch it.
    """

    target = "dorsalhub/whisper"
    mock_dorsal_client.get_registry_model.return_value.package_name = "dorsal-whisper-pkg"

    strategy, pkg_name = resolution.resolve_target(target)

    mock_dorsal_client.get_registry_model.assert_called_with(target)
    assert strategy == "registry_id"
    assert pkg_name == "dorsal-whisper-pkg"


def test_resolve_registry_id_auth_error(mock_dorsal_client):
    """
    If the registry returns an AuthError (401/403), it should bubble up
    so the CLI can prompt the user to login.
    """
    target = "private/secret-model"
    mock_dorsal_client.get_registry_model.side_effect = AuthError("Unauthorized")

    with pytest.raises(AuthError):
        resolution.resolve_target(target)


def test_resolve_registry_id_general_error(mock_dorsal_client):
    """
    General network/api errors should be wrapped in DorsalError.
    """
    target = "broken/model"
    mock_dorsal_client.get_registry_model.side_effect = Exception("500 Server Error")

    with pytest.raises(DorsalError) as exc:
        resolution.resolve_target(target)

    assert "Failed to resolve model" in str(exc.value)


def test_resolve_class_name_from_config(mock_find_package):
    """
    If the target is NOT a registry ID, checks if it maps to a known class in config.
    """

    target = "MyCoolModel"
    mock_find_package.return_value = "dorsal-my-cool-model"

    strategy, pkg_name = resolution.resolve_target(target)

    mock_find_package.assert_called_with(target)

    assert strategy == "package"
    assert pkg_name == "dorsal-my-cool-model"


def test_resolve_fallthrough_to_class_name(mock_find_package):
    """
    If it's not a registry ID and not in the config, assume it's a raw class name/package reference.
    """
    target = "UnknownIdentifier"
    mock_find_package.return_value = None

    strategy, pkg_name = resolution.resolve_target(target)

    assert strategy == "class_name"
