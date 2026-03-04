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

import pytest
from unittest.mock import MagicMock, patch
import sys
from dorsal.client import DorsalClient
from dorsal.common.exceptions import ApiDataValidationError, AuthError, DorsalClientError, SchemaFormatError
from dorsal.client.validators import FileAnnotationResponse, AnnotationIndexResult, RegistryModelResponse
from dorsal.file.validators.file_record import (
    Annotation,
    AnnotationGroup,
    GenericFileAnnotation,
    AnnotationGroupInfo,
    FileRecordStrict,
)


_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64

_DUMMY_ANNOTATION_ID = "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


def test_get_file_annotation_sharded_reassembly(client, requests_mock):
    """
    Critical Test: Verifies that the client detects a 'group' response,
    calls the reassembly logic, and returns a unified FileAnnotationResponse.
    """

    mock_group_response = {
        "annotation_id": _DUMMY_ANNOTATION_ID,
        "file_hash": _DUMMY_SHA256,
        "schema_id": "open/transcription",
        "user_id": 1,
        "private": True,
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

    with patch.dict("sys.modules", {"dorsal.file.sharding": MagicMock()}):
        mock_sharding = sys.modules["dorsal.file.sharding"]

        mock_sharding.reassemble_record.return_value = ("open/transcription", {"text": "Part 1Part 2"})

        result = client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)

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
                }
            ]
        },
        "annotation_id": _DUMMY_ANNOTATION_ID,
        "file_hash": _DUMMY_SHA256,
        "schema_id": "open/test",
        "user_id": 1,
        "private": True,
        "source": {"type": "Model", "id": "t"},
        "date_created": "2024-01-01T00:00:00Z",
        "date_modified": "2024-01-01T00:00:00Z",
        "record": {},
    }
    url = f"{_DUMMY_BASE_URL}/v1/files/{_DUMMY_SHA256}/annotations/{_DUMMY_ANNOTATION_ID}"
    requests_mock.get(url, json=mock_response)

    with patch.dict("sys.modules", {"dorsal.file.sharding": MagicMock()}):
        mock_sharding = sys.modules["dorsal.file.sharding"]
        mock_sharding.reassemble_record.side_effect = Exception("Reassembly Boom")

        with pytest.raises(ApiDataValidationError, match="Failed to reassemble"):
            client.get_file_annotation(file_hash=_DUMMY_SHA256, annotation_id=_DUMMY_ANNOTATION_ID)


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

    with patch("dorsal.client.dorsal_client.normalize_record_privacy", side_effect=Exception("Privacy Check Failed")):
        with pytest.raises(DorsalClientError, match="Internal error preparing record"):
            client.index_private_file_records([valid_record])


def test_make_schema_validator_format_error(client, requests_mock):
    """Test handling of invalid JSON Schema logic (SchemaFormatError)."""

    dataset_id = "org/bad-schema"
    url = f"{_DUMMY_BASE_URL}/v1/namespaces/org/datasets/bad-schema/schema"

    requests_mock.get(url, json={"type": "invalid_type_name"}, status_code=200)

    with pytest.raises(ApiDataValidationError) as exc:
        client.make_schema_validator(dataset_id)

    assert "schema for dataset 'org/bad-schema' is invalid" in str(exc.value)


def test_user_id_fetch_from_api(client, requests_mock):
    """
    Test that accessing .user_id fetches from the API if not in config,
    caches the result, and writes it to the auth config.
    """

    with (
        patch("dorsal.client.dorsal_client.get_user_id_from_config", return_value=None),
        patch("dorsal.client.dorsal_client.write_auth_config") as mock_write_config,
    ):
        requests_mock.get(f"{_DUMMY_BASE_URL}/v1/users/me", json={"user_id": 42}, status_code=200)

        assert client.user_id == 42

        mock_write_config.assert_called_once_with(api_key=_DUMMY_API_KEY, user_id=42)

        assert client._user_id == 42
        assert client.user_id == 42


def test_user_id_fetch_from_config(client):
    """Test that .user_id prefers the local config if available."""
    with (
        patch("dorsal.client.dorsal_client.get_user_id_from_config", return_value=99),
        patch("dorsal.client.dorsal_client.write_auth_config") as mock_write,
    ):
        assert client.user_id == 99

        mock_write.assert_not_called()


def test_user_id_failure(client, requests_mock):
    """Test that AuthError is raised if config is empty and API fails."""
    with patch("dorsal.client.dorsal_client.get_user_id_from_config", return_value=None):
        requests_mock.get(f"{_DUMMY_BASE_URL}/v1/users/me", status_code=401)

        with pytest.raises(AuthError):
            _ = client.user_id


def test_get_registry_model_success(client, requests_mock):
    """Test retrieving a valid registry model."""
    identifier = "dorsal/whisper"
    namespace, name = identifier.split("/")

    mock_registry_response = {
        "namespace": namespace,
        "name": name,
        "version": "1.0.0",
        "install_url": "https://dorsal.hub/pkg/whisper.whl",
        "schema_id": "model/speech-to-text",
        "package_name": "dorsal-whisper",
        "description": "A test model",
        "is_official": True,
        "is_verified": True,
    }

    url = f"{_DUMMY_BASE_URL}/v1/registry/models/{namespace}/{name}"
    requests_mock.get(url, json=mock_registry_response, status_code=200)

    result = client.get_registry_model(identifier)

    assert isinstance(result, RegistryModelResponse)
    assert result.name == "whisper"
    assert result.namespace == "dorsal"
    assert result.version == "1.0.0"
    assert result.package_name == "dorsal-whisper"


def test_get_registry_model_invalid_format(client):
    """Test that a non-namespaced ID raises a client error."""
    with pytest.raises(DorsalClientError, match="Invalid registry ID"):
        client.get_registry_model("whisper")


@patch("dorsal.client.dorsal_client.read_api_key", return_value=None)
def test_unauthenticated_client_can_get_registry_model(mock_read_key, requests_mock):
    """Test that a client without an API key can successfully hit the public registry."""
    unauth_client = DorsalClient(api_key=None, base_url=_DUMMY_BASE_URL)

    mock_registry_response = {
        "namespace": "dorsal",
        "name": "whisper",
        "version": "1.0.0",
        "install_url": "https://test.url",
        "schema_id": "model/test",
        "package_name": "test-pkg",
        "description": "test",
        "is_official": True,
        "is_verified": True,
    }

    url = f"{_DUMMY_BASE_URL}/v1/registry/models/dorsal/whisper"
    requests_mock.get(url, json=mock_registry_response, status_code=200)

    result = unauth_client.get_registry_model("dorsal/whisper")

    assert result.name == "whisper"
    assert "Authorization" not in requests_mock.last_request.headers


@patch("dorsal.client.dorsal_client.read_api_key", return_value=None)
def test_unauthenticated_client_blocks_auth_endpoints(mock_read_key, requests_mock):
    """Test that standard endpoints still strictly enforce local API key checks."""
    unauth_client = DorsalClient(api_key=None, base_url=_DUMMY_BASE_URL)

    with pytest.raises(AuthError, match="API Key is missing"):
        unauth_client.check_files_indexed([_DUMMY_SHA256])

    assert not requests_mock.called
