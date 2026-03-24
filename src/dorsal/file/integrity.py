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

from __future__ import annotations
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import FileRecordStrict


def normalize_record_privacy(
    record: FileRecordStrict, target_private: bool | None = None, strict: bool = False
) -> FileRecordStrict:
    """
    Mutates the record in-place to normalize the `private` field of tags/annotations/urls.

    Args:
        record: The record to mutate.
        target_private: The target state (True/False) or None to neutralize.
        strict: If True, raises ValueError on conflicts, else simply modifies the value.

    Raises:
        ValueError: If strict=True and a mismatch is found.
    """
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup, AnnotationsStrict

    def _apply_policy(item: Any, location_desc: str) -> None:
        if not hasattr(item, "private"):
            return

        current_val = item.private

        if target_private is None:
            item.private = None
            return

        if current_val is None:
            item.private = target_private
        elif current_val != target_private:
            if strict:
                required_state = "PRIVATE" if target_private else "PUBLIC"
                actual_state = "PRIVATE" if current_val else "PUBLIC"
                raise ValueError(
                    f"Privacy Mismatch in {location_desc}: Endpoint requires {required_state} records, "
                    f"but received an item explicitly marked {actual_state}."
                )
            else:
                # Overwrite
                item.private = target_private

    def _process_container(container: Any, path: str) -> None:
        """Recursive traverser for Lists, Groups, and Items."""
        if isinstance(container, AnnotationGroup):
            for i, ann in enumerate(container.annotations):
                _apply_policy(ann, f"{path} -> Group Index {i}")

        elif isinstance(container, list):
            for i, item in enumerate(container):
                _process_container(item, f"{path}[{i}]")

        elif isinstance(container, Annotation):
            _apply_policy(container, path)

        elif hasattr(container, "private"):
            _apply_policy(container, path)

    if record.tags:
        for i, tag in enumerate(record.tags):
            _apply_policy(tag, f"Tag index {i} ('{tag.name}')")

    if record.annotations:
        for field_name in AnnotationsStrict.model_fields:
            entry = getattr(record.annotations, field_name, None)
            if entry:
                _process_container(entry, f"Annotation '{field_name}'")

        if record.annotations.__pydantic_extra__:
            for key, value in record.annotations.__pydantic_extra__.items():
                _process_container(value, f"Annotation '{key}'")

    if record.urls:
        for i, url_record in enumerate(record.urls):
            _apply_policy(url_record, f"URL index {i} ('{url_record.url}')")

    return record
