# Copyright 2026 Dorsal Hub LTD
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

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dorsal.client import DorsalClient, LoggingRetry
from dorsal.common.exceptions import APIError, NotFoundError, RateLimitError


class _Server:
    def __init__(self, responses: list[tuple[int, dict[str, str], dict]]):
        self.responses = list(responses)
        self.requests = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests += 1
                status, headers, body = server.responses.pop(0) if len(server.responses) > 1 else server.responses[0]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def online(monkeypatch):
    monkeypatch.delenv("DORSAL_OFFLINE", raising=False)
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def _client(url: str) -> DorsalClient:
    return DorsalClient(api_key="test-key", base_url=url, timeout=5)


def test_long_retry_after_fails_fast_with_rate_limit_error(online):
    with _Server([(429, {"Retry-After": "36000"}, {"detail": "Daily limit reached"})]) as server:
        started = time.monotonic()
        with pytest.raises(RateLimitError) as exc:
            _client(server.url).get_dataset("test/data")

    assert time.monotonic() - started < 10
    assert server.requests == 1
    assert exc.value.retry_after == "36000"


def test_short_retry_after_is_still_retried(online):
    responses = [(429, {"Retry-After": "1"}, {"detail": "Slow down"}), (404, {}, {"detail": "No such dataset"})]
    with _Server(responses) as server:
        with pytest.raises(NotFoundError):
            _client(server.url).get_dataset("test/data")

    assert server.requests == 2


def test_exhausted_retries_raise_the_final_api_error(online):
    with _Server([(503, {}, {"detail": "Unavailable"})]) as server:
        with pytest.raises(APIError) as exc:
            _client(server.url).get_dataset("test/data")

    assert server.requests == 4
    assert exc.value.status_code == 503


def test_max_retry_after_defaults_to_sixty_seconds():
    assert LoggingRetry.max_retry_after == 60


def test_long_retry_after_on_503_fails_fast(online):
    with _Server([(503, {"Retry-After": "3600"}, {"detail": "Maintenance"})]) as server:
        with pytest.raises(APIError) as exc:
            _client(server.url).get_dataset("test/data")

    assert server.requests == 1
    assert exc.value.status_code == 503


def test_malformed_retry_after_is_ignored(online):
    responses = [(429, {"Retry-After": "soon"}, {"detail": "Slow down"}), (404, {}, {"detail": "No such dataset"})]
    with _Server(responses) as server:
        with pytest.raises(NotFoundError):
            _client(server.url).get_dataset("test/data")

    assert server.requests == 2
