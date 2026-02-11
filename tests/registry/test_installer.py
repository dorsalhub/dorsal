import sys
import subprocess
import logging
from unittest.mock import MagicMock, patch, ANY
import pytest
import pathlib
import tomllib

# We need the real base class for the Pydantic validation to pass
from dorsal import AnnotationModel
from dorsal.registry import installer
from dorsal.common.exceptions import DorsalError

# --- FIXTURES ---


@pytest.fixture
def mock_dorsal_client():
    """Mock the registry client to avoid network calls."""
    with patch("dorsal.registry.installer.get_shared_dorsal_client") as mock:
        client_instance = mock.return_value
        yield client_instance


@pytest.fixture
def mock_subprocess():
    """Capture pip execution to prevent actual installation."""
    with patch("subprocess.Popen") as mock_popen:
        process_mock = MagicMock()
        process_mock.stdout = []  # Simulate no output
        process_mock.wait.return_value = 0  # Simulate success
        mock_popen.return_value = process_mock
        yield mock_popen


@pytest.fixture
def mock_register_model():
    """Mock the final step to verify what WOULD have been saved to config."""
    with patch("dorsal.registry.installer.register_model") as mock:
        yield mock


# --- TESTS ---


def test_get_local_pyproject_name(tmp_path):
    """Verify we can parse a name from a real TOML file."""
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "dorsal-super-model"\nversion = "0.1.0"', encoding="utf-8")

    name = installer._get_local_pyproject_name(tmp_path)
    assert name == "dorsal-super-model"


def test_get_local_pyproject_name_missing(tmp_path):
    """Verify it returns None if file is missing."""
    assert installer._get_local_pyproject_name(tmp_path) is None


def test_install_registry_target_success(mock_dorsal_client, mock_subprocess):
    """
    Full flow: Registry ID -> Resolve URL -> Run Pip -> Register
    """
    # 1. Setup Registry Response
    # FIX: Use a valid 40-character SHA-1 hash to pass the regex validator
    valid_sha = "a" * 40
    mock_dorsal_client.get_registry_model.return_value.install_url = (
        f"git+https://github.com/dorsalhub/whisper.git@{valid_sha}"
    )
    mock_dorsal_client.get_registry_model.return_value.package_name = "dorsal-whisper"

    # 2. Mock 'install_model_from_package'
    with patch("dorsal.registry.installer.install_model_from_package") as mock_install_pkg:
        installer.install_model_target("dorsalhub/whisper")

        # Verify Registry Lookup
        mock_dorsal_client.get_registry_model.assert_called_with("dorsalhub/whisper")

        # Verify Pip Execution
        expected_pip = [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"git+https://github.com/dorsalhub/whisper.git@{valid_sha}",
        ]
        mock_subprocess.assert_called_with(
            expected_pip,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        # Verify Registration
        mock_install_pkg.assert_called_with("dorsal-whisper", scope="project")


def test_install_local_target_success(tmp_path, mock_subprocess):
    """
    Full flow: Local Path -> Read Pyproject -> Run Pip -> Register
    """
    project_dir = tmp_path / "my-model"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text('[project]\nname = "my-local-model"')

    with patch("dorsal.registry.installer.install_model_from_package") as mock_install_pkg:
        installer.install_model_target(str(project_dir))

        # Verify Pip used the local path
        args, _ = mock_subprocess.call_args
        cmd = args[0]
        assert str(project_dir) in cmd[-1]

        # Verify Package Name Resolution
        mock_install_pkg.assert_called_with("my-local-model", scope="project")


def test_pip_failure_logs_error(mock_subprocess, capsys):
    """Ensure we catch pip errors and print the log."""
    # Force logger to WARNING so 'is_verbose' becomes False in the code.
    # This forces the error log to be written to stderr.
    installer.logger.setLevel(logging.WARNING)

    process_mock = mock_subprocess.return_value
    process_mock.wait.return_value = 1
    process_mock.stdout = ["Some error line 1\n", "fatal: repository not found\n"]

    with pytest.raises(DorsalError) as exc:
        installer._run_pip_install_streaming(["pip", "install", "foo"], "foo")

    assert "could not be found" in str(exc.value)

    captured = capsys.readouterr()
    assert "Pip Installation Log" in captured.err
    assert "fatal: repository not found" in captured.err


def test_install_model_from_package_logic(mock_register_model):
    """
    Test the complex logic of extracting config from an installed package.
    Uses 'patch' to simulate installed entry points.
    """

    # 1. Prepare the Mock Entry Point
    mock_ep = MagicMock()
    mock_ep.name = "dorsal-fake"
    mock_ep.dist.name = "dorsal-fake"
    mock_ep.module = "dorsal_fake_module"

    # 2. Prepare the Module
    mock_module = MagicMock()

    # We must inherit from AnnotationModel
    class FakeModel(AnnotationModel):
        id = "fake/model"
        version = "0.0.1"

        def main(self):
            pass

    mock_module.MyModelClass = FakeModel
    mock_ep.load.return_value = mock_module

    # 3. Prepare the Fake Config
    fake_config = {
        "model_class": "MyModelClass",
        "schema_id": "open/specific",
        "dependencies": [{"type": "media_type", "include": ["image/png"]}],
    }

    # 4. Patch 'entry_points' AND '_load_packaged_model_config'
    with (
        patch("importlib.metadata.entry_points", return_value=[mock_ep]),
        patch("dorsal.registry.installer._load_packaged_model_config", return_value=fake_config),
    ):
        installer.install_model_from_package("dorsal-fake")

        # 5. Verify Registration
        mock_register_model.assert_called_once()
        call_kwargs = mock_register_model.call_args.kwargs

        assert call_kwargs["annotation_model"] == FakeModel
        assert call_kwargs["schema_id"] == "open/specific"

        # FIX: Check the attributes of the converted Pydantic objects
        deps = call_kwargs["dependencies"]
        assert len(deps) == 1
        assert deps[0].type == "media_type"
        assert deps[0].include == {"image/png"}


def test_install_from_package_missing_entry_point():
    """If the package installs but doesn't expose an entry point, fail."""
    with patch("importlib.metadata.entry_points", return_value=[]):
        with pytest.raises(DorsalError) as exc:
            installer.install_model_from_package("ghost-package")

        assert "does not expose a 'dorsal.models' entry point" in str(exc.value)
