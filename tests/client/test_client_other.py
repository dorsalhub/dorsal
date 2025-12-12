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
from unittest.mock import MagicMock, patch
import sys
from dorsal.client import DorsalClient
from dorsal.common.exceptions import ApiDataValidationError, DorsalClientError, SchemaFormatError
from dorsal.client.validators import FileAnnotationResponse, AnnotationIndexResult
from dorsal.file.validators.file_record import (
    Annotation,
    AnnotationGroup,
    GenericFileAnnotation,
    AnnotationGroupInfo,
    FileRecordStrict,
)

# Constants
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64
# Valid UUID
_DUMMY_ANNOTATION_ID = "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


def test_get_file_annotation_sharded_reassembly(client, requests_mock):
    """
    Critical Test: Verifies that the client detects a 'group' response,
    calls the reassembly logic, and returns a unified FileAnnotationResponse.
    """
    # 1. Mock the Server Response
    # We provide fields matching the client-side FileAnnotationResponse model exactly.
    mock_group_response = {
        "annotation_id": _DUMMY_ANNOTATION_ID,
        "file_hash": _DUMMY_SHA256,
        # Client Model Fields (Strictly required by FileAnnotationResponse)
        "schema_id": "open/transcription",
        "user_id": 1,
        "private": True,
        # Server-side legacy fields (optional, but realistic to include)
        "dataset_id": "open/transcription",
        "user_no": 1,
        "visibility": "u:1",
        "schema_version": "1.0",
        "date_created": "2025-01-01T12:00:00Z",
        "date_modified": "2025-01-01T12:00:00Z",
        "source": {"type": "Model", "id": "test"},
        "group": {
            "annotations": [
                {
                    "record": {"text": "Part 1"},
                    "private": True,
                    "source": {"type": "Model", "id": "test"},
                    "group": {"id": _DUMMY_ANNOTATION_ID, "index": 0, "total": 2},
                },
                {
                    "record": {"text": "Part 2"},
                    "private": True,
                    "source": {"type": "Model", "id": "test"},
                    "group": {"id": _DUMMY_ANNOTATION_ID, "index": 1, "total": 2},
                },
            ]
        },
    }

    url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.get(url, json=mock_group_response, status_code=200)

    # 2. Mock the Lazy Imports & Reassembly Logic
    with patch.dict("sys.modules", {"dorsal.file.sharding": MagicMock()}):
        mock_sharding = sys.modules["dorsal.file.sharding"]
        # Mock reassembly to return a merged record
        mock_sharding.reassemble_record.return_value = ("open/transcription", {"text": "Part 1Part 2"})

        # 3. Execute
        result = client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)

        # 4. Verify
        assert isinstance(result, FileAnnotationResponse)
        assert result.record == {"text": "Part 1Part 2"}
        assert result.annotation_id == _DUMMY_ANNOTATION_ID
        assert result.schema_id == "open/transcription"

        mock_sharding.reassemble_record.assert_called_once()


def test_get_file_annotation_reassembly_failure(client, requests_mock):
    """Test that failures during reassembly are caught and wrapped."""
    mock_response = {
        "group": {
            "annotations": [
                {
                    "record": {},
                    "source": {"type": "Model", "id": "test_mock"},
                    "private": True,
                    "group": {"id": "12345678-1234-5678-1234-567812345678", "index": 0, "total": 2},
                    # Include other required fields if your Annotation model forces them
                }
            ]
        },
        "annotation_id": _DUMMY_ANNOTATION_ID,
        "file_hash": _DUMMY_SHA256,
        # Provide required fields to pass initial validation steps if any
        "schema_id": "open/test",
        "user_id": 1,
        "private": True,
        "source": {"type": "Model", "id": "t"},
        "date_created": "2024-01-01T00:00:00Z",
        "date_modified": "2024-01-01T00:00:00Z",
        "record": {},  # Stub record
    }
    url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.get(url, json=mock_response)

    with patch.dict("sys.modules", {"dorsal.file.sharding": MagicMock()}):
        mock_sharding = sys.modules["dorsal.file.sharding"]
        mock_sharding.reassemble_record.side_effect = Exception("Reassembly Boom")

        with pytest.raises(ApiDataValidationError, match="Failed to reassemble"):
            client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)


# --- 2. Sharded Write Path Tests ---


def test_add_file_annotation_group(client, requests_mock):
    """Verify passing an AnnotationGroup works and serializes correctly."""
    group = AnnotationGroup(
        annotations=[
            Annotation(
                record=GenericFileAnnotation(a=1),
                private=True,
                source={"type": "Model", "id": "m"},
                group=AnnotationGroupInfo(id=_DUMMY_ANNOTATION_ID, index=0, total=2),
            ),
            Annotation(
                record=GenericFileAnnotation(a=2),
                private=True,
                source={"type": "Model", "id": "m"},
                group=AnnotationGroupInfo(id=_DUMMY_ANNOTATION_ID, index=1, total=2),
            ),
        ]
    )
    schema_id = "org/dataset"
    url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/org/dataset"

    requests_mock.post(
        url, json={"total": 1, "success": 1, "error": 0, "dataset_id": schema_id, "results": []}, status_code=200
    )

    result = client.add_file_annotation(file_hash=_DUMMY_SHA256, schema_id=schema_id, annotation=group)

    assert isinstance(result, AnnotationIndexResult)
    assert requests_mock.last_request.json()["annotations"][0]["record"]["a"] == 1


def test_index_file_records_integrity_failure(client):
    """Test that a failure in privacy alignment halts the upload."""
    valid_record = FileRecordStrict(
        hash=_DUMMY_SHA256,
        validation_hash="b" * 64,
        source="disk",
        annotations={
            "file/base": {
                "record": {
                    "hash": _DUMMY_SHA256,
                    "name": "test.txt",
                    "size": 100,
                    "media_type": "text/plain",
                    "all_hashes": [{"id": "SHA-256", "value": _DUMMY_SHA256}, {"id": "BLAKE3", "value": "b" * 64}],
                },
                "source": {"type": "Model", "id": "dorsal/file-core", "version": "1.0"},
            }
        },
    )

    with patch(
        "dorsal.client.dorsal_client.align_core_annotation_privacy", side_effect=Exception("Privacy Check Failed")
    ):
        with pytest.raises(DorsalClientError, match="Internal error preparing record"):
            client.index_private_file_records([valid_record])


# --- 4. Schema Validator Tests ---


def test_make_schema_validator_format_error(client, requests_mock):
    """Test handling of invalid JSON Schema logic (SchemaFormatError)."""
    # Namespace "org" is valid (3 chars)
    dataset_id = "org/bad-schema"
    url = f"{_DUMMY_BASE_URL}/v1/namespaces/org/datasets/bad-schema/schema"

    # A schema that is valid JSON but invalid JSON Schema (e.g. invalid type)
    requests_mock.get(url, json={"type": "invalid_type_name"}, status_code=200)

    with pytest.raises(ApiDataValidationError) as exc:
        client.make_schema_validator(dataset_id)

    assert "schema for dataset 'org/bad-schema' is invalid" in str(exc.value)
