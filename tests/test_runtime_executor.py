#    Compose human-readable ComfyUI workflows with SugarCubes
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Runtime executor behavior tests."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
import json
import logging
from typing import Any
from urllib.error import HTTPError

import pytest

from sugar.runtime.executor import (
    ComfyUIRequestError,
    download_image,
    fetch_history,
    poll_for_images,
    queue_prompt,
)


class _Response:
    """Minimal context-manager response for urlopen monkeypatches."""

    def __init__(self, body: bytes) -> None:
        """Store the bytes returned by `read`."""

        self._body = body

    def __enter__(self) -> "_Response":
        """Return the response for context-manager use."""

        return self

    def __exit__(self, *_args: object) -> None:
        """Close the test response context."""

        return None

    def read(self) -> bytes:
        """Return the configured response body."""

        return self._body


def test_queue_prompt_sends_raw_prompt_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw prompt mappings are sent as ComfyUI prompt payloads."""

    captured_payloads: list[dict[str, Any]] = []

    def _open(request: Any, timeout: float) -> _Response:
        """Capture the serialized prompt request."""

        captured_payloads.append(json.loads(request.data.decode("utf-8")))
        return _Response(b'{"prompt_id": "abc"}')

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    assert queue_prompt({"1": {"class_type": "KSampler", "inputs": {}}}) == {"prompt_id": "abc"}
    assert captured_payloads == [{"prompt": {"1": {"class_type": "KSampler", "inputs": {}}}}]


def test_queue_prompt_sends_wrapped_prompt_payload_with_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrapped prompt mappings keep only supported ComfyUI request fields."""

    captured_payloads: list[dict[str, Any]] = []

    def _open(request: Any, timeout: float) -> _Response:
        """Capture the serialized wrapped prompt request."""

        captured_payloads.append(json.loads(request.data.decode("utf-8")))
        return _Response(b'{"prompt_id": "abc"}')

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    queue_prompt(
        {
            "prompt": {"1": {"class_type": "KSampler", "inputs": {}}},
            "execute_outputs": ["1"],
        },
        client_id="client-1",
    )

    assert captured_payloads == [
        {
            "prompt": {"1": {"class_type": "KSampler", "inputs": {}}},
            "client_id": "client-1",
        }
    ]


def test_queue_prompt_raises_http_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP error bodies are preserved in raised runtime errors."""

    def _raise_http_error(request: Any, timeout: float) -> None:
        """Raise a ComfyUI-style HTTP error response."""

        raise HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=Message(),
            fp=BytesIO(b'{"error":"invalid prompt"}'),
        )

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _raise_http_error)

    with pytest.raises(ComfyUIRequestError, match="HTTP 400.*invalid prompt"):
        queue_prompt({"1": {"class_type": "KSampler", "inputs": {}}}, client_id="x")


def test_queue_prompt_rejects_invalid_json_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid ComfyUI JSON responses are surfaced as runtime errors."""

    secret_body = b"not-json-with-C:\\Users\\secret\\token"

    def _open(_request: Any, timeout: float) -> _Response:
        """Return a non-JSON prompt response body."""

        return _Response(secret_body)

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    caplog.set_level(logging.ERROR, logger="sugar.runtime.executor")
    with pytest.raises(ComfyUIRequestError, match="Could not decode prompt response"):
        queue_prompt({"1": {"class_type": "KSampler", "inputs": {}}})
    assert "secret" not in caplog.text
    assert "response_body_length" in caplog.records[0].__dict__


def test_fetch_history_returns_decoded_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History responses are decoded into dictionaries."""

    def _open(_url: str, timeout: float) -> _Response:
        """Return a valid history response body."""

        return _Response(b'{"abc": {"outputs": {}}}')

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    assert fetch_history("abc") == {"abc": {"outputs": {}}}


def test_fetch_history_raises_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History HTTP failures are wrapped with prompt context."""

    def _raise_http_error(_url: str, timeout: float) -> None:
        """Raise a ComfyUI history HTTP error response."""

        raise HTTPError(
            url="http://127.0.0.1:8188/history/abc",
            code=500,
            msg="Server Error",
            hdrs=Message(),
            fp=BytesIO(b"history unavailable"),
        )

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _raise_http_error)

    with pytest.raises(
        ComfyUIRequestError, match="Failed to fetch history.*abc.*history unavailable"
    ):
        fetch_history("abc")


def test_fetch_history_rejects_invalid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History JSON decode failures are wrapped in runtime errors."""

    def _open(_url: str, timeout: float) -> _Response:
        """Return a malformed history response body."""

        return _Response(b"not-json")

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    with pytest.raises(ComfyUIRequestError, match="Could not decode history response.*abc"):
        fetch_history("abc")


def test_download_image_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Image downloads return response bytes unchanged."""

    def _open(_url: str, timeout: float) -> _Response:
        """Return image response bytes."""

        return _Response(b"image-bytes")

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _open)

    assert download_image("image.png", "sub", "output") == b"image-bytes"


def test_download_image_raises_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image HTTP failures are wrapped with filename context."""

    def _raise_http_error(_url: str, timeout: float) -> None:
        """Raise a ComfyUI image HTTP error response."""

        raise HTTPError(
            url="http://127.0.0.1:8188/view",
            code=404,
            msg="Not Found",
            hdrs=Message(),
            fp=BytesIO(b"missing image"),
        )

    monkeypatch.setattr("sugar.runtime.executor.urllib.request.urlopen", _raise_http_error)

    with pytest.raises(
        ComfyUIRequestError, match="Failed to download image 'image.png'.*missing image"
    ):
        download_image("image.png", "sub", "output")


@pytest.mark.parametrize(
    "server",
    [
        "http://127.0.0.1:8188",
        "127.0.0.1:8188/path",
        "127.0.0.1:8188?x=1",
        "127.0.0.1:8188#frag",
        " 127.0.0.1:8188",
        "",
    ],
)
def test_runtime_calls_reject_invalid_server_values(server: str) -> None:
    """Runtime HTTP calls reject server strings that are not host[:port] values."""

    with pytest.raises(ComfyUIRequestError, match="ComfyUI server"):
        fetch_history("abc", server=server)


def test_poll_for_images_yields_images_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image polling tolerates transient runtime errors before success."""

    responses: list[dict[str, Any] | ComfyUIRequestError] = [
        ComfyUIRequestError("temporary"),
        {"abc": {"outputs": {"1": {"images": [{"filename": "image.png"}]}}}},
    ]

    def _fetch_history(
        prompt_id: str, server: str = "127.0.0.1:8188", *, timeout: float = 30.0
    ) -> dict[str, Any]:
        """Return the next queued polling response."""

        response = responses.pop(0)
        if isinstance(response, ComfyUIRequestError):
            raise response
        return response

    monkeypatch.setattr("sugar.runtime.executor.fetch_history", _fetch_history)

    assert list(poll_for_images("abc", interval=0, timeout=1.0)) == [[{"filename": "image.png"}]]


def test_poll_for_images_stops_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Image polling ends without yielding when no outputs appear before timeout."""

    def _fetch_history(
        prompt_id: str, server: str = "127.0.0.1:8188", *, timeout: float = 30.0
    ) -> dict[str, Any]:
        """Return an empty history response."""

        return {prompt_id: {"outputs": {}}}

    monkeypatch.setattr("sugar.runtime.executor.fetch_history", _fetch_history)

    assert list(poll_for_images("abc", interval=0, timeout=0.001)) == []
