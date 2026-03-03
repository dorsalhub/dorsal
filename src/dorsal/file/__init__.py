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

from typing import TYPE_CHECKING

__all__ = [
    "DorsalFile",
    "FileAnnotationStub",
    "LocalFile",
    "ModelRunner",
    "MetadataReader",
    "scan_file",
    "scan_directory",
    "index_file",
    "index_directory",
    "generate_html_file_report",
    "get_blake3_hash",
    "get_quick_hash",
    "get_sha256_hash",
]

if TYPE_CHECKING:
    from dorsal.file.model_runner import ModelRunner
    from dorsal.file.metadata_reader import MetadataReader
    from dorsal.file.dorsal_file import DorsalFile, FileAnnotationStub, LocalFile
    from dorsal.file.utils import get_blake3_hash, get_quick_hash, get_sha256_hash
    from dorsal.api.file import scan_file, scan_directory, index_file, index_directory, generate_html_file_report


def __getattr__(name: str):
    """
    Lazily import heavy file processing classes and API functions to prevent
    'fat init' overhead when simply traversing the dorsal.file namespace.
    """
    if name == "ModelRunner":
        from dorsal.file.model_runner import ModelRunner

        return ModelRunner

    elif name == "MetadataReader":
        from dorsal.file.metadata_reader import MetadataReader

        return MetadataReader

    elif name == "DorsalFile":
        from dorsal.file.dorsal_file import DorsalFile

        return DorsalFile

    elif name == "LocalFile":
        from dorsal.file.dorsal_file import LocalFile

        return LocalFile

    elif name == "FileAnnotationStub":
        from dorsal.file.dorsal_file import FileAnnotationStub

        return FileAnnotationStub

    elif name in {"get_blake3_hash", "get_quick_hash", "get_sha256_hash"}:
        from dorsal.file.utils import get_blake3_hash, get_quick_hash, get_sha256_hash

        return locals()[name]

    elif name in {"scan_file", "scan_directory", "index_file", "index_directory", "generate_html_file_report"}:
        from dorsal.api.file import scan_file, scan_directory, index_file, index_directory, generate_html_file_report

        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return __all__
