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

import sys
import platform
from pathlib import Path


def initialize_mediainfo():
    """Checks for MediaInfo availability and returns the library and its path if needed."""
    try:
        from pymediainfo import MediaInfo  # type: ignore

        library_path = None
        # On macos, `homebrew` may install to a non-standard path that pymediainfo may not search by default
        # See: https://docs.brew.sh/Installation#alternative-installs
        # See: https://github.com/sbraz/pymediainfo/issues/151
        if sys.platform == "darwin" and platform.machine() == "arm64":
            homebrew_path = Path("/opt/homebrew/lib/libmediainfo.dylib")
            if homebrew_path.is_file():
                library_path = str(homebrew_path)

        MediaInfo._get_library(library_file=library_path)

        return MediaInfo, library_path

    except (ImportError, OSError) as e:
        if "failed to load library" in str(e).lower() or isinstance(e, ImportError):
            if sys.platform == "darwin":
                message = (
                    "The 'mediainfo' library is not installed or could not be found. "
                    "On macOS, it can be installed with Homebrew:\n\n"
                    "    brew install mediainfo\n"
                )
            elif sys.platform.startswith("linux"):
                message = (
                    "The 'mediainfo' library is not installed. "
                    "Please install it using your system's package manager, for example:\n\n"
                    "    On Debian/Ubuntu: sudo apt-get install mediainfo\n"
                    "    On Fedora/CentOS: sudo dnf install mediainfo\n"
                )
            else:
                message = f"The 'mediainfo' library could not be found on your system ({sys.platform}). Please install it to continue."

            raise ImportError(message) from e
        else:
            raise


def initialize_magic():
    """
    Checks for python-magic availability and returns the library and Exception class.
    """
    try:
        import magic
        from magic import MagicException

        return magic, MagicException
    except ImportError as err:
        if "failed to find libmagic" in str(err).lower() or "magic library not found" in str(err).lower():
            if sys.platform == "darwin":
                message = (
                    "The 'libmagic' library is not installed. "
                    "Please install it using Homebrew:\n\n"
                    "    brew install libmagic\n"
                )
            elif sys.platform.startswith("linux"):
                message = (
                    "The 'libmagic' library is not installed. "
                    "Please install it using your system's package manager, for example:\n\n"
                    "    On Debian/Ubuntu: sudo apt-get install libmagic1\n"
                    "    On Fedora/CentOS: sudo dnf install file-libs\n"
                )
            else:
                message = f"The 'libmagic' library could not be found on your system ({sys.platform}). Please install it to continue."
            raise ImportError(message) from err
        else:
            raise err
