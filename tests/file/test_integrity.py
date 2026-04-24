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

import uuid
import pytest

from dorsal.file.integrity import normalize_record_privacy
from dorsal.file.validators.file_record import FileRecordStrict

_DUMMY_SHA256 = "a" * 64
_DUMMY_BLAKE3 = "b" * 64
_GROUP_ID = uuid.uuid4()
_EXECUTION_ID = str(uuid.uuid4())


def _build_base_record(
    tag_private: bool | None = None,
    url_private: bool | None = None,
    ann_private: bool | None = None,
    group_private: bool | None = None,
) -> FileRecordStrict:
    """Helper to cleanly build a real FileRecordStrict with varying privacy states."""
    return FileRecordStrict(
        hash=_DUMMY_SHA256,
        validation_hash=_DUMMY_BLAKE3,
        source="disk",
        tags=[
            {
                "name": "test_tag",
                "value": "tag_val",
                "private": tag_private,
                "hidden": False,
                "upvotes": 0,
                "downvotes": 0,
            }
        ],
        urls=[
            {"url": "https://example.com", "source": {"agent": "test_agent"}, "status": "alive", "private": url_private}
        ],
        annotations={
            "file/base": {
                "record": {
                    "hash": _DUMMY_SHA256,
                    "name": "test.txt",
                    "size": 100,
                    "media_type": "text/plain",
                    "all_hashes": [{"id": "SHA-256", "value": _DUMMY_SHA256}, {"id": "BLAKE3", "value": _DUMMY_BLAKE3}],
                },
                "source": {"type": "Model", "id": "file/base"},
            },
            "custom/schema": {
                "record": {"custom_data": 123},
                "private": ann_private,
                "source": {"type": "Model", "id": "custom"},
            },
            "custom/sharded": {
                "annotations": [
                    {
                        "record": {"part": 1},
                        "private": group_private,
                        "source": {"type": "Model", "id": "custom_group", "execution_id": _EXECUTION_ID},
                        "group": {"id": _GROUP_ID, "index": 0, "total": 2},
                    },
                    {
                        "record": {"part": 2},
                        "private": group_private,
                        "source": {"type": "Model", "id": "custom_group", "execution_id": _EXECUTION_ID},
                        "group": {"id": _GROUP_ID, "index": 1, "total": 2},
                    },
                ]
            },
        },
    )


@pytest.fixture
def clean_record() -> FileRecordStrict:
    """A record where all privacy fields are completely undefined (None)."""
    return _build_base_record(tag_private=None, url_private=None, ann_private=None, group_private=None)


@pytest.fixture
def public_record() -> FileRecordStrict:
    """A record where all privacy fields are explicitly False."""
    return _build_base_record(tag_private=False, url_private=False, ann_private=False, group_private=False)


@pytest.fixture
def private_record() -> FileRecordStrict:
    """A record where all privacy fields are explicitly True."""
    return _build_base_record(tag_private=True, url_private=True, ann_private=True, group_private=True)


def test_normalize_privacy_overwrite_to_true(clean_record: FileRecordStrict):
    """Test standard overwrite setting all neutral fields to True."""
    result = normalize_record_privacy(clean_record, target_private=True, strict=False)

    assert result is clean_record

    assert result.tags[0].private is True
    assert result.urls[0].private is True
    assert getattr(result.annotations, "custom/schema").private is True

    group = getattr(result.annotations, "custom/sharded")
    assert group.annotations[0].private is True
    assert group.annotations[1].private is True


def test_normalize_privacy_overwrite_to_false(clean_record: FileRecordStrict):
    """Test standard overwrite setting all neutral fields to False."""
    result = normalize_record_privacy(clean_record, target_private=False, strict=False)

    assert result.tags[0].private is False
    assert result.urls[0].private is False
    assert getattr(result.annotations, "custom/schema").private is False
    assert getattr(result.annotations, "custom/sharded").annotations[0].private is False


def test_normalize_privacy_neutralize(private_record: FileRecordStrict):
    """Test passing target_private=None neutralizes (sets to None) existing True/False values."""
    result = normalize_record_privacy(private_record, target_private=None, strict=False)

    assert result.tags[0].private is None
    assert result.urls[0].private is None
    assert getattr(result.annotations, "custom/schema").private is None
    assert getattr(result.annotations, "custom/sharded").annotations[0].private is None


def test_normalize_privacy_strict_success_on_neutral_record(clean_record: FileRecordStrict):
    """Test strict mode succeeds and sets to True when all fields are currently None (no conflicts)."""
    result = normalize_record_privacy(clean_record, target_private=True, strict=True)

    assert result.tags[0].private is True
    assert result.urls[0].private is True
    assert getattr(result.annotations, "custom/schema").private is True


def test_normalize_privacy_strict_conflict_raises_on_tag():
    """Test strict mode raises ValueError when targeting Private but a Tag is explicitly Public."""
    record = _build_base_record(tag_private=False, url_private=None, ann_private=None, group_private=None)

    with pytest.raises(ValueError, match="Privacy Mismatch in Tag index 0"):
        normalize_record_privacy(record, target_private=True, strict=True)


def test_normalize_privacy_strict_conflict_raises_on_url():
    """Test strict mode raises ValueError when targeting Public but a URL is explicitly Private."""
    record = _build_base_record(tag_private=None, url_private=True, ann_private=None, group_private=None)

    with pytest.raises(ValueError, match="Privacy Mismatch in URL index 0"):
        normalize_record_privacy(record, target_private=False, strict=True)


def test_normalize_privacy_strict_conflict_raises_on_annotation():
    """Test strict mode raises ValueError when targeting Public but an Annotation is explicitly Private."""
    record = _build_base_record(tag_private=None, url_private=None, ann_private=True, group_private=None)

    with pytest.raises(ValueError, match="Privacy Mismatch in Annotation 'custom/schema'"):
        normalize_record_privacy(record, target_private=False, strict=True)


def test_normalize_privacy_strict_conflict_raises_on_nested_group():
    """Test strict mode raises ValueError when targeting Private but a Group chunk is explicitly Public."""
    record = _build_base_record(tag_private=None, url_private=None, ann_private=None, group_private=False)

    with pytest.raises(ValueError, match="Privacy Mismatch in Annotation 'custom/sharded' -> Group Index 0"):
        normalize_record_privacy(record, target_private=True, strict=True)


def test_normalize_privacy_non_strict_overwrites_conflicts():
    """Test non-strict mode effortlessly overwrites conflicting states without raising."""
    record = _build_base_record(tag_private=False, url_private=True, ann_private=False, group_private=True)

    result = normalize_record_privacy(record, target_private=False, strict=False)

    assert result.tags[0].private is False
    assert result.urls[0].private is False
    assert getattr(result.annotations, "custom/schema").private is False
    assert getattr(result.annotations, "custom/sharded").annotations[0].private is False
