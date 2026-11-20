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
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup, FileRecordStrict

UNUSABLE_SCHEMA_VERSIONS = frozenset({"latest", "published"})
REASON_DISPLAY_LIMIT = 200

_PUSH_CHECKED: ContextVar[dict[int, Any] | None] = ContextVar("_PUSH_CHECKED", default=None)


def is_usable_schema_version(schema_version: object) -> bool:
    """Return True if `schema_version` is an exact version: not empty, `latest` or `published`."""
    if not isinstance(schema_version, str):
        return False
    version = schema_version.strip().lower()
    return bool(version) and version not in UNUSABLE_SCHEMA_VERSIONS


def _oats_schema_name(schema_id: str | None) -> str | None:
    from dorsal.file.schemas import OATS_SCHEMA_PREFIX, OPEN_SCHEMA_PREFIX, open_schema_name

    if not isinstance(schema_id, str):
        return None
    normalized = schema_id.strip().lower()
    for prefix in (OATS_SCHEMA_PREFIX, OPEN_SCHEMA_PREFIX):
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return open_schema_name(normalized)


def _unversioned_problems(schema_id: str | None, item: Any, file_label: str) -> list[dict[str, str | None]]:
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup

    if isinstance(item, list):
        return [problem for entry in item for problem in _unversioned_problems(schema_id, entry, file_label)]
    if isinstance(item, AnnotationGroup):
        return _unversioned_problems(schema_id, item.annotations, file_label)
    if not isinstance(item, Annotation):
        return []

    schema_name = _oats_schema_name(schema_id) or _oats_schema_name(item.schema_id)
    if schema_name is None or is_usable_schema_version(item.schema_version):
        return []
    return [
        {
            "file": file_label,
            "schema": schema_name,
            "model": str(getattr(item.source, "id", None) or "unknown"),
            "schema_version": item.schema_version,
        }
    ]


def _unique_problems(problems: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    return list({tuple(problem.items()): problem for problem in problems}.values())


def _record_extras(record: Any) -> dict[str, Any]:
    extras = getattr(getattr(record, "annotations", None), "__pydantic_extra__", None)
    return extras if isinstance(extras, dict) else {}


def _annotation_items(item: Any) -> Iterable[Any]:
    if isinstance(item, list):
        for entry in item:
            yield from _annotation_items(entry)
    elif hasattr(item, "annotations") and hasattr(item, "hash"):
        for value in _record_extras(item).values():
            yield from _annotation_items(value)
    elif item is not None:
        yield item


@contextmanager
def sending_checked(*items: Any) -> Iterator[None]:
    """Let the uploads made inside the block send `items`, which this push has just checked, without checking them again."""
    held = dict(_PUSH_CHECKED.get() or {})
    for item in items:
        for annotation in _annotation_items(item):
            held[id(annotation)] = annotation
    token = _PUSH_CHECKED.set(held)
    try:
        yield
    finally:
        _PUSH_CHECKED.reset(token)


def _checked_in_this_push(item: Any) -> bool:
    return (_PUSH_CHECKED.get() or {}).get(id(item)) is item


def _rebuilt_group(group: AnnotationGroup, schema_name: str, record: dict[str, Any]) -> Annotation | AnnotationGroup:
    from dorsal.file.sharding import build_annotation_or_annotationgroup

    first = group.annotations[0]
    return build_annotation_or_annotationgroup(
        schema_id=first.schema_id or schema_name,
        record_data=record,
        source=first.source.model_dump(),
        schema_version=first.schema_version,
        private=first.private,
    )


def _checked_numbers(schema_id: str | None, item: Any, file_label: str) -> tuple[Any, list[dict[str, str | None]]]:
    import oatschema

    from dorsal.common.validators.json_schema import shorten_text
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup, GenericFileAnnotation

    if isinstance(item, list):
        problems: list[dict[str, str | None]] = []
        checked_items = []
        for entry in item:
            checked_entry, entry_problems = _checked_numbers(schema_id, entry, file_label)
            checked_items.append(checked_entry)
            problems.extend(entry_problems)
        changed = any(new is not old for new, old in zip(checked_items, item, strict=True))
        return (checked_items if changed else item), problems
    if not isinstance(item, (Annotation, AnnotationGroup)) or _checked_in_this_push(item):
        return item, []

    first = item.annotations[0] if isinstance(item, AnnotationGroup) else item
    schema_name = _oats_schema_name(schema_id) or _oats_schema_name(first.schema_id)
    version = item.schema_version
    if schema_name is None or not is_usable_schema_version(version):
        return item, []

    reason: str | None = None
    to_send: Any = item
    content: dict[str, Any] | None
    try:
        if isinstance(item, AnnotationGroup):
            from dorsal.file.sharding import reassemble_record

            _, content = reassemble_record(item)
        else:
            content = item.record.model_dump() if item.record is not None else None
        if content is not None:
            checked = oatschema.check_numbers(content, schema_name, version, on_bad_number="raise")  # type: ignore[arg-type]
            if checked.converted and isinstance(item, AnnotationGroup):
                to_send = _rebuilt_group(item, schema_name, checked.record)
            elif checked.converted:
                to_send = item.model_copy(update={"record": GenericFileAnnotation(**checked.record)})
    except oatschema.ValidationError as err:
        reason = str(err.message)
    except (LookupError, TypeError, ValueError) as err:
        reason = str(err)

    if reason is None:
        return to_send, []
    return item, [
        {
            "file": file_label,
            "schema": schema_name,
            "model": str(getattr(item.source, "id", None) or "unknown"),
            "schema_version": version,
            "reason": shorten_text(reason, REASON_DISPLAY_LIMIT),
        }
    ]


def _check_numbers_enabled() -> bool:
    from dorsal.common.constants import ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR

    return not os.getenv(ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR)


def _with_annotations(record: FileRecordStrict, replaced: dict[str, Any]) -> FileRecordStrict:
    annotations = record.annotations.model_copy()  # type: ignore[union-attr]
    annotations.__pydantic_extra__ = {**_record_extras(record), **replaced}
    return record.model_copy(update={"annotations": annotations})


def check_record_schema_versions(
    records: Iterable[FileRecordStrict], *, hash_to_path_map: dict[str, str] | None = None
) -> list[FileRecordStrict]:
    """
    Check the OATS annotations in file records about to be uploaded, and return the records to send.

    Every OATS annotation must have an exact `schema_version`, and is checked with
    `oatschema.check_numbers(..., on_bad_number="raise")` at that version, whatever happened to it before. A record
    whose numbers the check converts (such as `-0.0`) is returned as a copy holding the converted values; the
    records passed in are not changed. Numbers are not checked while `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` is set.

    Args:
        records: The records about to be uploaded.
        hash_to_path_map: Optional mapping of {hash: local_path}, used to name files in the error.

    Returns:
        The records to upload, in the same order.

    Raises:
        UnversionedAnnotationError: Listing every unversioned annotation across all of `records`.
        RejectedAnnotationError: Listing every annotation across all of `records` that fails its number check.
    """
    from dorsal.common.exceptions import RejectedAnnotationError, UnversionedAnnotationError

    records = list(records)
    problems: list[dict[str, str | None]] = []
    for record in records:
        label = (hash_to_path_map or {}).get(record.hash, record.hash)
        for schema_id, value in _record_extras(record).items():
            problems.extend(_unversioned_problems(schema_id, value, label))

    if problems:
        raise UnversionedAnnotationError(_unique_problems(problems))

    if not _check_numbers_enabled():
        return records
    to_send: list[FileRecordStrict] = []
    for record in records:
        label = (hash_to_path_map or {}).get(record.hash, record.hash)
        replaced: dict[str, Any] = {}
        for schema_id, value in _record_extras(record).items():
            checked_value, value_problems = _checked_numbers(schema_id, value, label)
            problems.extend(value_problems)
            if checked_value is not value:
                replaced[schema_id] = checked_value
        to_send.append(_with_annotations(record, replaced) if replaced else record)

    if problems:
        raise RejectedAnnotationError(_unique_problems(problems))
    return to_send


def check_annotation_schema_version(
    *, schema_id: str, annotation: Annotation | AnnotationGroup, file_label: str
) -> Annotation | AnnotationGroup:
    """
    Check a single OATS annotation about to be uploaded, as `check_record_schema_versions` does, and return what to send.

    Raises:
        UnversionedAnnotationError: If any annotation in `annotation` has no usable version.
        RejectedAnnotationError: If an annotation fails `check_numbers` at its version.
    """
    from dorsal.common.exceptions import RejectedAnnotationError, UnversionedAnnotationError

    problems = _unversioned_problems(schema_id, annotation, file_label)
    if problems:
        raise UnversionedAnnotationError(_unique_problems(problems))
    if not _check_numbers_enabled():
        return annotation
    to_send, problems = _checked_numbers(schema_id, annotation, file_label)
    if problems:
        raise RejectedAnnotationError(_unique_problems(problems))
    return to_send


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
