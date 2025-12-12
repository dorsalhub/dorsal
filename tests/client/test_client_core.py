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
import requests
from unittest.mock import patch

from dorsal.client import DorsalClient
from dorsal.common.exceptions import (
    APIError,
    AuthError,
    BadRequestError,
    ConflictError,
    DorsalClientError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    NetworkError,
)

# Constants
_DUMMY_API_KEY = "abc123_test_key"
_DUMMY_BASE_URL = "http://dorsalhub.test"
_DUMMY_SHA256 = "a" * 64


@pytest.fixture
def client():
    return DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)


def test_init():
    """Test client initialization and default values."""
    client = DorsalClient(api_key=_DUMMY_API_KEY)
    assert client.api_key == _DUMMY_API_KEY
    # Fix: Correct default URL
    assert client.base_url == "https://api.dorsalhub.com"
    assert client._file_records_batch_insert_size == 10_000


def test_init_custom_base_url():
    """Test initialization with custom base URL."""
    client = DorsalClient(api_key=_DUMMY_API_KEY, base_url=_DUMMY_BASE_URL)
    assert client.base_url == _DUMMY_BASE_URL


def test_make_user_agent(client):
    """Test User-Agent dictionary creation."""
    ua = client._make_user_agent()
    assert isinstance(ua, dict)
    assert "client_version" in ua
    assert "platform" in ua


def test_make_request_headers(client):
    """Test header construction."""
    headers = client._make_request_headers()
    assert isinstance(headers, dict)
    assert headers["Content-Type"] == "application/json"
    assert f"Bearer {_DUMMY_API_KEY}" in headers["Authorization"]


def test_make_request_headers_missing_key(client):
    """Test that missing API key raises AuthError."""
    client.api_key = None

    with pytest.raises(AuthError):
        client._make_request_headers()


def test_build_requests_session(client):
    """Test session creation."""
    session = client._build_requests_session()
    assert isinstance(session, requests.Session)
    assert f"Bearer {_DUMMY_API_KEY}" in session.headers["Authorization"]


@pytest.mark.parametrize(
    "status_code, error_json, expected_exception",
    [
        (400, {"detail": "Bad request"}, BadRequestError),
        (401, {"detail": "Unauthorized"}, AuthError),
        (403, {"detail": "Forbidden"}, ForbiddenError),
        (404, {"detail": "Not Found"}, NotFoundError),
        (409, {"detail": "Conflict"}, ConflictError),
        (429, {"detail": "Rate limit exceeded"}, RateLimitError),
        (418, {"detail": "I'm a teapot"}, APIError),
        (500, {"detail": "Internal Server Error"}, APIError),
        (503, {"detail": "Service Unavailable"}, APIError),
    ],
)
def test_handle_api_error_json(client, status_code, error_json, expected_exception):
    """Test mapping of HTTP status codes to specific exceptions."""
    mock_response = requests.Response()
    mock_response.status_code = status_code
    mock_response.json = lambda: error_json
    mock_response._content = b'{"detail": "Error"}'
    mock_response.url = f"{_DUMMY_BASE_URL}/test"

    with pytest.raises(expected_exception) as excinfo:
        client._handle_api_error(mock_response, suppress_warning_log=True)

    assert error_json["detail"] in str(excinfo.value)


def test_handle_api_error_no_json(client):
    """Test error handling when response body is not JSON."""
    mock_response = requests.Response()
    mock_response.status_code = 400
    mock_response.url = f"{_DUMMY_BASE_URL}/test"
    mock_response._content = b"Raw text error message"

    with pytest.raises(BadRequestError) as excinfo:
        client._handle_api_error(mock_response, suppress_warning_log=True)

    assert "Raw text error message" in str(excinfo.value)


def test_parse_validate_file_hash(client):
    """Test hash string parsing validation."""
    h, algo = client._parse_validate_file_hash(_DUMMY_SHA256)
    assert h == _DUMMY_SHA256
    assert algo == "SHA-256"

    h, algo = client._parse_validate_file_hash(f"sha256:{_DUMMY_SHA256}")
    assert h == _DUMMY_SHA256
    assert algo == "SHA-256"


def test_parse_validate_file_hash_errors(client):
    """Test validation failures for hash strings."""
    # Fix: parse_validate_hash raises ValueError for unknown formats
    with pytest.raises(ValueError):
        client._parse_validate_file_hash("TLSH:123456")

    with pytest.raises(ValueError):
        client._parse_validate_file_hash("not-a-hash")

    with pytest.raises(ValueError):
        client._parse_validate_file_hash("a" * 63)


def test_split_dataset_id(client):
    """Test parsing of dataset IDs."""
    ns, name = client._split_dataset_or_schema_id("my-org/my-dataset")
    assert ns == "my-org"
    assert name == "my-dataset"


def test_split_dataset_id_error(client):
    """Test invalid dataset ID formats."""
    invalid_ids = ["no-slash", "too/many/slashes", "/missing-ns", "missing-name/"]
    for invalid_id in invalid_ids:
        with pytest.raises(DorsalClientError):
            client._split_dataset_or_schema_id(invalid_id)


def test_make_file_key(client):
    """Test internal key construction for API lookups."""
    assert client._make_file_key(_DUMMY_SHA256, "SHA-256") == _DUMMY_SHA256
    md5 = "a" * 32
    assert client._make_file_key(md5, "BLAKE3") == f"BLAKE3:{md5}"


def test_validate_sha256_hashes_success(client):
    """Test bulk hash list validation."""
    hashes = [_DUMMY_SHA256, "b" * 64]
    assert client._validate_sha256_hashes(hashes) == hashes


def test_validate_sha256_hashes_errors(client):
    """Test bulk hash list validation failures."""
    with pytest.raises(DorsalClientError):
        client._validate_sha256_hashes([])

    with pytest.raises(DorsalClientError):
        client._validate_sha256_hashes(["bad-hash"])


def test_verify_credentials_success(client, requests_mock):
    """Test successful credential verification."""
    mock_response = {"user_id": 1, "username": "test"}
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/users/me", json=mock_response, status_code=200)

    result = client.verify_credentials()
    assert result["username"] == "test"


def test_verify_credentials_failure(client, requests_mock):
    """Test failed credential verification."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/users/me", status_code=401)

    with pytest.raises(AuthError):
        client.verify_credentials()


def test_verify_credentials_network_error(client, requests_mock):
    """Test network error during verification."""
    requests_mock.get(f"{_DUMMY_BASE_URL}/v1/users/me", exc=requests.exceptions.ConnectionError)

    with pytest.raises(NetworkError):
        client.verify_credentials()
