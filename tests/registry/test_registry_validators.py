import sys
import subprocess
import pytest
from unittest.mock import MagicMock, patch

from dorsal.registry import uninstaller
from dorsal.common.exceptions import DorsalError

# --- FIXTURES ---


@pytest.fixture
def mock_resolve_target():
    """Mock resolution to always return a safe package name."""
    with patch("dorsal.registry.uninstaller.resolve_target") as mock:
        mock.return_value = ("package", "dorsal-test-model")
        yield mock


@pytest.fixture
def mock_unregister_model():
    """Mock the config modification."""
    with patch("dorsal.registry.uninstaller.unregister_model") as mock:
        yield mock


@pytest.fixture
def mock_subprocess():
    """Mock the pip subprocess."""
    with patch("subprocess.Popen") as mock_popen:
        process_mock = MagicMock()
        process_mock.stdout = []  # Default: empty stdout (success)
        process_mock.wait.return_value = 0  # Default: return code 0 (success)
        mock_popen.return_value = process_mock
        yield mock_popen


# --- TESTS ---


def test_uninstall_full_success(mock_resolve_target, mock_unregister_model, mock_subprocess):
    """
    Scenario: The model exists in config AND is installed in pip.
    Result: Success.
    """
    # Execution
    result = uninstaller.uninstall_model_target("test-model")

    # Verification
    assert result == "dorsal-test-model"
    mock_unregister_model.assert_called_with(package_name="dorsal-test-model", scope="project")

    # Verify pip was called
    expected_cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "dorsal-test-model"]
    mock_subprocess.assert_called_with(
        expected_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def test_uninstall_config_only(mock_resolve_target, mock_unregister_model, mock_subprocess):
    """
    Scenario: The model is in config, but pip says "Skipping (not installed)".
    Result: Success (Config was cleaned up).
    """
    # Setup Pip to report "Skipping"
    process_mock = mock_subprocess.return_value
    process_mock.stdout = ["Skipping dorsal-test-model as it is not installed\n"]

    # Execution
    result = uninstaller.uninstall_model_target("test-model")

    # Verification
    assert result == "dorsal-test-model"
    mock_unregister_model.assert_called_once()  # Config was touched


def test_uninstall_pip_only(mock_resolve_target, mock_unregister_model, mock_subprocess):
    """
    Scenario: The model is NOT in config, but IS installed in pip.
    Result: Success (Package was removed).
    """
    # Setup Config to raise KeyError (Not found)
    mock_unregister_model.side_effect = KeyError("Model not found")

    # Execution
    result = uninstaller.uninstall_model_target("test-model")

    # Verification
    assert result == "dorsal-test-model"
    # Ensure we didn't crash on the KeyError
    mock_unregister_model.assert_called_once()


def test_uninstall_noop_failure(mock_resolve_target, mock_unregister_model, mock_subprocess):
    """
    Scenario: Model NOT in config AND NOT installed in pip.
    Result: DorsalError (Nothing was done).
    """
    # Setup Config to raise KeyError
    mock_unregister_model.side_effect = KeyError("Model not found")

    # Setup Pip to report "Skipping"
    process_mock = mock_subprocess.return_value
    process_mock.stdout = ["Skipping dorsal-test-model as it is not installed\n"]

    # Execution & Assertion
    with pytest.raises(DorsalError) as exc:
        uninstaller.uninstall_model_target("test-model")

    assert "Could not find model" in str(exc.value)
    assert "resolved as package: 'dorsal-test-model'" in str(exc.value)


def test_uninstall_pip_error_passthrough(mock_resolve_target, mock_unregister_model, mock_subprocess):
    """
    Scenario: Pip subprocess fails with a non-zero exit code.
    Result: Since config also failed, raise Error.
    """
    mock_unregister_model.side_effect = KeyError("Model not found")

    # Setup Pip to fail
    process_mock = mock_subprocess.return_value
    process_mock.wait.return_value = 1  # Error Code
    process_mock.stdout = ["Permission denied\n"]

    with pytest.raises(DorsalError) as exc:
        uninstaller.uninstall_model_target("test-model")

    # It should hit the "nothing done" error, because _run_pip_uninstall_streaming returns False on error
    assert "Could not find model" in str(exc.value)


def test_pip_streaming_logs_on_error(mock_subprocess, capsys):
    """
    Verify internal helper prints logs to stderr when pip fails.
    """
    # Force quiet mode
    uninstaller.logger.setLevel(50)  # CRITICAL

    process_mock = mock_subprocess.return_value
    process_mock.wait.return_value = 1
    process_mock.stdout = ["Fatal Error in Uninstall\n"]

    success = uninstaller._run_pip_uninstall_streaming("bad-pkg")

    assert success is False
    captured = capsys.readouterr()
    assert "Pip Uninstall Log" in captured.err
    assert "Fatal Error" in captured.err
