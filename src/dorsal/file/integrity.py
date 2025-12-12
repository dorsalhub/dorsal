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

from typing import cast
from dorsal.file.validators.file_record import Annotation, FileRecordStrict, CORE_MODEL_ANNOTATION_WRAPPERS

CORE_ANNOTATION_ATTRIBUTES = [
    key.replace("/", "_").replace("-", "_") for key in CORE_MODEL_ANNOTATION_WRAPPERS if key != "file/base"
]


def align_core_annotation_privacy(record: FileRecordStrict, is_private: bool) -> FileRecordStrict:
    """Ensures core (file-type) annotations have the same privacy as the main record."""
    for attr_name in CORE_ANNOTATION_ATTRIBUTES:
        annotation_obj = cast(Annotation | None, getattr(record.annotations, attr_name, None))

        if annotation_obj:
            annotation_obj.private = is_private

    return record
