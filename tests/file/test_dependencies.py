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
import re
from dorsal.file.dependencies import (
    make_media_type_dependency,
    make_file_extension_dependency,
    make_file_size_dependency,
    make_file_name_dependency,
)
from dorsal.file.configs.model_runner import (
    MediaTypeDependencyConfig,
    FileExtensionDependencyConfig,
    FileSizeDependencyConfig,
    FilenameDependencyConfig,
)


def test_make_media_type_success():
    dep = make_media_type_dependency(include=["application/pdf"], exclude=["text/plain"])
    assert isinstance(dep, MediaTypeDependencyConfig)
    assert dep.include == {"application/pdf"}
    assert dep.exclude == {"text/plain"}


def test_make_media_type_fail_str_input():
    with pytest.raises(TypeError) as exc:
        make_media_type_dependency(include="application/pdf")
    assert "Did you mean: include=" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        make_media_type_dependency(exclude="text/plain")
    assert "Did you mean: exclude=" in str(exc.value)


def test_make_media_type_fail_no_args():
    with pytest.raises(ValueError) as exc:
        make_media_type_dependency()
    assert "must have at least one rule" in str(exc.value)


def test_make_extension_success():
    # Test normalization (adding dot, lowering case)
    dep = make_file_extension_dependency(extensions=["PDF", ".txt"])
    assert isinstance(dep, FileExtensionDependencyConfig)
    assert ".pdf" in dep.extensions
    assert ".txt" in dep.extensions


def test_make_extension_fail_str_input():
    with pytest.raises(TypeError) as exc:
        make_file_extension_dependency(extensions=".pdf")
    assert "must be a sequence" in str(exc.value)


def test_make_extension_fail_empty():
    with pytest.raises(ValueError) as exc:
        make_file_extension_dependency(extensions=[])
    assert "must have at least one extension" in str(exc.value)


# --- File Size Dependency Tests ---


def test_make_size_success():
    dep = make_file_size_dependency(min_size="1KB", max_size=2000)
    assert isinstance(dep, FileSizeDependencyConfig)
    assert dep.min_size == 1000
    assert dep.max_size == 2000


def test_make_size_fail_no_args():
    with pytest.raises(ValueError) as exc:
        make_file_size_dependency()
    assert "must have at least one" in str(exc.value)


# --- File Name Dependency Tests ---


def test_make_filename_success():
    dep = make_file_name_dependency(pattern=r"^data_.*")
    assert isinstance(dep, FilenameDependencyConfig)
    assert dep.pattern == r"^data_.*"


def test_make_filename_fail_empty():
    with pytest.raises(ValueError):
        make_file_name_dependency(pattern="")
