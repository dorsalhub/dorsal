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

from dorsal.file.dorsal_file import DorsalFile, LocalFile
from dorsal.file.collection.local import LocalFileCollection
from dorsal.file.collection.remote import DorsalFileCollection
from dorsal.file.metadata_reader import MetadataReader
from dorsal.file.model_runner import ModelRunner
from dorsal.client import DorsalClient
from dorsal.common.model import AnnotationModel
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
