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

import dorsal
import dorsal.file


def test_dorsal_init_lazy_load_branches():
    """Forces execution of every branch in dorsal.__init__.__getattr__"""

    expected_attributes = [
        "LocalFile",
        "DorsalFile",
        "LocalFileCollection",
        "DorsalFileCollection",
        "MetadataReader",
        "ModelRunner",
        "DorsalClient",
        "AnnotationModel",
    ]

    # Hit every successful if/elif branch directly
    for attr in expected_attributes:
        loaded_obj = dorsal.__getattr__(attr)
        assert loaded_obj is not None
        assert loaded_obj.__name__ == attr

    # Hit the AttributeError fallback
    with pytest.raises(AttributeError, match="has no attribute 'this_definitely_does_not_exist'"):
        dorsal.__getattr__("this_definitely_does_not_exist")

    # Cover the __dir__ block
    assert "LocalFile" in dorsal.__dir__()


def test_dorsal_file_init_lazy_load_branches():
    """Forces execution of every branch in dorsal.file.__init__.__getattr__"""

    expected_attributes = [
        "ModelRunner",
        "MetadataReader",
        "DorsalFile",
        "LocalFile",
        "get_blake3_hash",
        "get_quick_hash",
        "get_sha256_hash",
        "scan_file",
        "scan_directory",
        "index_file",
        "index_directory",
        "generate_html_file_report",
    ]

    # Hit every successful if/elif branch directly
    for attr in expected_attributes:
        loaded_obj = dorsal.file.__getattr__(attr)
        assert loaded_obj is not None
        assert loaded_obj.__name__ == attr

    # Hit the AttributeError fallback
    with pytest.raises(AttributeError, match="has no attribute 'this_definitely_does_not_exist'"):
        dorsal.file.__getattr__("this_definitely_does_not_exist")

    # Cover the __dir__ block
    assert "scan_file" in dorsal.file.__dir__()
