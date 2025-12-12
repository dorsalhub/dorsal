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

import os
from dorsal.file.utils.files import get_file_paths


def test_get_file_paths_flat(tmp_path):
    """Test non-recursive file listing."""
    # Setup: Create some files and a subdirectory
    f1 = tmp_path / "file1.txt"
    f1.write_text("content")
    f2 = tmp_path / "file2.txt"
    f2.write_text("content")

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    f3 = subdir / "file3.txt"
    f3.write_text("content")

    # Execute: recursive=False
    paths = get_file_paths(str(tmp_path), recursive=False)

    # Assert: Should only find top-level files
    assert len(paths) == 2
    assert str(f1) in paths
    assert str(f2) in paths
    assert str(f3) not in paths


def test_get_file_paths_recursive(tmp_path):
    """Test recursive file listing."""
    # Setup: Deep structure
    (tmp_path / "root_file.txt").write_text("x")

    level1 = tmp_path / "level1"
    level1.mkdir()
    (level1 / "l1_file.txt").write_text("x")

    level2 = level1 / "level2"
    level2.mkdir()
    (level2 / "l2_file.txt").write_text("x")

    # Execute: recursive=True
    paths = get_file_paths(str(tmp_path), recursive=True)

    # Assert: Should find all 3 files
    assert len(paths) == 3
    assert str(tmp_path / "root_file.txt") in paths
    assert str(level1 / "l1_file.txt") in paths
    assert str(level2 / "l2_file.txt") in paths


def test_get_file_paths_empty(tmp_path):
    """Test behavior on empty directory."""
    paths = get_file_paths(str(tmp_path))
    assert paths == []


def test_get_file_paths_ignore_dirs(tmp_path):
    """Ensure directories themselves are not returned in the list, only files."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    # recursive=False
    paths = get_file_paths(str(tmp_path), recursive=False)
    assert paths == []

    # recursive=True
    paths_rec = get_file_paths(str(tmp_path), recursive=True)
    assert paths_rec == []
