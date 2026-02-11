import pytest
from unittest.mock import patch, MagicMock
from importlib.metadata import PackageNotFoundError

from dorsal.registry import resolution
from dorsal.common.exceptions import DorsalError, AuthError

# --- FIXTURES ---


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


# --- TESTS: resolve_target ---


def test_resolve_registry_id_success(mock_dorsal_client):
    """
    If the target looks like a Registry ID (user/repo), we should fetch it.
    """
    # Setup
    target = "dorsalhub/whisper"
    mock_dorsal_client.get_registry_model.return_value.package_name = "dorsal-whisper-pkg"

    # Execute
    strategy, pkg_name = resolution.resolve_target(target)

    # Verify
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
    # Setup
    target = "MyCoolModel"
    mock_find_package.return_value = "dorsal-my-cool-model"

    # Execute
    strategy, pkg_name = resolution.resolve_target(target)

    # Verify
    mock_find_package.assert_called_with(target)
    # Note: Based on your code logic, finding it in config sets strategy="package"
    assert strategy == "package"
    assert pkg_name == "dorsal-my-cool-model"


def test_resolve_fallthrough_to_class_name(mock_find_package):
    """
    If it's not a registry ID and not in the config, assume it's a raw class name/package reference.
    """
    target = "UnknownIdentifier"
    mock_find_package.return_value = None  # Not found in config

    strategy, pkg_name = resolution.resolve_target(target)

    assert strategy == "class_name"
    # It should canonical
