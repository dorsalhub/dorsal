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

from dorsal.version import __version__

__all__ = [
    "AnnotationModel",
    "DorsalFile",
    "DorsalFileCollection",
    "LocalFile",
    "LocalFileCollection",
    "MetadataReader",
    "ModelRunner",
    "DorsalClient",
    "__version__",
]

if TYPE_CHECKING:
    from dorsal.file.dorsal_file import LocalFile, DorsalFile
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.collection.remote import DorsalFileCollection
    from dorsal.file.metadata_reader import MetadataReader
    from dorsal.file.model_runner import ModelRunner
    from dorsal.client import DorsalClient
    from dorsal.common.model import AnnotationModel


def __getattr__(name: str):
    if name == "LocalFile":
        from dorsal.file.dorsal_file import LocalFile

        return LocalFile
    elif name == "DorsalFile":
        from dorsal.file.dorsal_file import DorsalFile

        return DorsalFile
    elif name == "LocalFileCollection":
        from dorsal.file.collection.local import LocalFileCollection

        return LocalFileCollection
    elif name == "DorsalFileCollection":
        from dorsal.file.collection.remote import DorsalFileCollection

        return DorsalFileCollection
    elif name == "MetadataReader":
        from dorsal.file.metadata_reader import MetadataReader

        return MetadataReader
    elif name == "ModelRunner":
        from dorsal.file.model_runner import ModelRunner

        return ModelRunner
    elif name == "DorsalClient":
        from dorsal.client import DorsalClient

        return DorsalClient
    elif name == "AnnotationModel":
        from dorsal.common.model import AnnotationModel

        return AnnotationModel

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return __all__
