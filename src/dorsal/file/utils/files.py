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

import os
from typing import Iterator, List, Union


def get_file_paths(dir_path: str, recursive: bool = False, lazy: bool = False) -> Union[List[str], Iterator[str]]:
    """
    Retrieves file paths from a directory.

    Args:
        dir_path: The directory to scan.
        recursive: If True, scans subdirectories recursively.
        lazy: If True, yields paths, else returns a list after scanning is complete.

    Returns:
        List[str] | Iterator[str]: A list of file paths or an iterator yielding them.
    """

    def _scanner() -> Iterator[str]:
        if recursive:
            for root, _, files in os.walk(dir_path):
                for file in files:
                    yield os.path.join(root, file)
        else:
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_file():
                            yield entry.path
            except OSError:
                return

    if lazy:
        return _scanner()

    return list(_scanner())
