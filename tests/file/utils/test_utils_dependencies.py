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
import sys
from pathlib import Path
from dorsal.file.utils.dependencies import initialize_mediainfo, initialize_magic


def test_mediainfo_success(mocker):
    """Test successful initialization when library is present."""
    # Mock pymediainfo import and behavior
    mock_pkg = mocker.MagicMock()
    mocker.patch.dict(sys.modules, {"pymediainfo": mock_pkg})

    # Ensure _get_library returns successfully
    mock_pkg.MediaInfo._get_library.return_value = None

    mi, path = initialize_mediainfo()
    assert mi == mock_pkg.MediaInfo


def test_mediainfo_macos_arm64_path(mocker):
    """Test special path handling for Apple Silicon."""
    mocker.patch("sys.platform", "darwin")
    mocker.patch("platform.machine", return_value="arm64")

    mocker.patch("pathlib.Path.is_file", return_value=True)

    mock_pkg = mocker.MagicMock()
    mocker.patch.dict(sys.modules, {"pymediainfo": mock_pkg})

    expected_path = str(Path("/opt/homebrew/lib/libmediainfo.dylib"))
    initialize_mediainfo()

    # Verify custom library path was passed
    mock_pkg.MediaInfo._get_library.assert_called_with(library_file=expected_path)


def test_mediainfo_missing_linux(mocker):
    """Test error message on Linux when mediainfo is missing."""
    mocker.patch("sys.platform", "linux")

    # Mocking library not found (the internal OSError path)
    mock_pkg = mocker.MagicMock()
    mock_pkg.MediaInfo._get_library.side_effect = OSError("failed to load library")
    mocker.patch.dict(sys.modules, {"pymediainfo": mock_pkg})

    with pytest.raises(ImportError) as exc:
        initialize_mediainfo()

    assert "sudo apt-get install mediainfo" in str(exc.value)


def test_mediainfo_missing_macos(mocker):
    """Test error message on macOS."""
    mocker.patch("sys.platform", "darwin")
    mock_pkg = mocker.MagicMock()
    mock_pkg.MediaInfo._get_library.side_effect = OSError("failed to load library")
    mocker.patch.dict(sys.modules, {"pymediainfo": mock_pkg})

    with pytest.raises(ImportError) as exc:
        initialize_mediainfo()
    assert "brew install mediainfo" in str(exc.value)


# --- initialize_magic Tests ---


def test_magic_success(mocker):
    mock_magic = mocker.MagicMock()
    mocker.patch.dict(sys.modules, {"magic": mock_magic})

    mod, exc = initialize_magic()
    assert mod == mock_magic


def test_magic_missing_linux(mocker):
    mocker.patch("sys.platform", "linux")
    # Simulate import error. Since 'magic' might be installed, we patch standard import
    # or just raise it manually if we can't unimport.
    # The easiest way for a specific function scope import test is often simply
    # raising the error from a mock if we can intercept it, or unmasking it.
    # Here we will rely on `builtins.__import__` patching for the specific module name.

    original_import = __import__

    def import_mock(name, *args, **kwargs):
        if name == "magic":
            raise ImportError("failed to find libmagic")
        return original_import(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=import_mock)

    with pytest.raises(ImportError) as exc:
        initialize_magic()
    assert "sudo apt-get install libmagic1" in str(exc.value)


def test_magic_unexpected_error(mocker):
    """Ensure generic ImportErrors are re-raised as-is."""
    original_import = __import__

    def import_mock(name, *args, **kwargs):
        if name == "magic":
            raise ImportError("Something random")
        return original_import(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=import_mock)

    with pytest.raises(ImportError) as exc:
        initialize_magic()
    assert "Something random" in str(exc.value)
    # Should NOT contain the helper text
    assert "sudo apt-get" not in str(exc.value)
