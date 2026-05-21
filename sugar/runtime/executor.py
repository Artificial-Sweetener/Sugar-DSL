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
"""ComfyUI HTTP execution and output retrieval adapters."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any, cast

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "127.0.0.1:8188"
DEFAULT_TIMEOUT_SECONDS = 30.0
_SERVER_FORBIDDEN_CHARS = frozenset("/?#")


class ComfyUIRequestError(RuntimeError):
    """Raised when ComfyUI HTTP communication fails."""


def queue_prompt(
    prompt: dict[str, Any],
    client_id: str | None = None,
    *,
    server: str = DEFAULT_SERVER,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Queue one prompt with ComfyUI and return the decoded response."""

    normalized_server = _normalize_server(server)
    context: dict[str, Any] = {
        "operation": "queue_prompt",
        "server": normalized_server,
        "has_client_id": client_id is not None,
    }
    if isinstance(prompt.get("prompt"), dict):
        actual_prompt = prompt["prompt"]
    else:
        actual_prompt = prompt

    payload: dict[str, Any] = {"prompt": actual_prompt}
    if client_id:
        payload["client_id"] = client_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://{normalized_server}/prompt", data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        detail = _read_http_error_body(exc)
        message = f"Failed to send prompt via HTTP: HTTP {exc.code} {exc.reason}: {detail or exc}"
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc
    except OSError as exc:
        message = f"Failed to send prompt via HTTP: {exc}"
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc

    return _decode_json_object(
        response_body,
        operation="send prompt",
        message_prefix="prompt response",
        context=context,
    )


def fetch_history(
    prompt_id: str,
    server: str = DEFAULT_SERVER,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch prompt history/results from ComfyUI."""

    normalized_server = _normalize_server(server)
    quoted_prompt_id = urllib.parse.quote(prompt_id, safe="")
    url = f"http://{normalized_server}/history/{quoted_prompt_id}"
    context: dict[str, Any] = {
        "operation": "fetch_history",
        "prompt_id": prompt_id,
        "server": normalized_server,
    }
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        detail = _read_http_error_body(exc)
        message = (
            f"Failed to fetch history for prompt '{prompt_id}' from '{normalized_server}': "
            f"HTTP {exc.code} {exc.reason}: {detail or exc}"
        )
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc
    except OSError as exc:
        message = (
            f"Failed to fetch history for prompt '{prompt_id}' from '{normalized_server}': {exc}"
        )
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc
    return _decode_json_object(
        response_body,
        operation="fetch history",
        message_prefix=f"history response for prompt '{prompt_id}'",
        context=context,
    )


def download_image(
    filename: str,
    subfolder: str,
    folder_type: str,
    server: str = DEFAULT_SERVER,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """Download one image produced by ComfyUI."""

    normalized_server = _normalize_server(server)
    context: dict[str, Any] = {
        "operation": "download_image",
        "image_filename": filename,
        "subfolder": subfolder,
        "folder_type": folder_type,
        "server": normalized_server,
    }
    params = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": folder_type}
    )
    url = f"http://{normalized_server}/view?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return cast(bytes, response.read())
    except urllib.error.HTTPError as exc:
        detail = _read_http_error_body(exc)
        message = (
            f"Failed to download image '{filename}' from '{normalized_server}': "
            f"HTTP {exc.code} {exc.reason}: {detail or exc}"
        )
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc
    except OSError as exc:
        message = f"Failed to download image '{filename}' from '{normalized_server}': {exc}"
        logger.error(message, extra={**context, "error": str(exc)})
        raise ComfyUIRequestError(message) from exc


def poll_for_images(
    prompt_id: str,
    interval: float = 1.0,
    server: str = DEFAULT_SERVER,
    timeout: float = 60.0,
    *,
    request_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[list[dict[str, Any]]]:
    """Poll ComfyUI for output images until images appear or timeout expires."""

    start = time.time()
    while True:
        try:
            history = fetch_history(prompt_id, server, timeout=request_timeout)
            outputs = history.get(prompt_id, {}).get("outputs", {})
            found = False
            if isinstance(outputs, dict):
                for node_output in outputs.values():
                    if not isinstance(node_output, dict):
                        continue
                    images = node_output.get("images")
                    if isinstance(images, list) and images:
                        yield images
                        found = True
            if found:
                break
        except ComfyUIRequestError as exc:
            logger.debug(
                "Prompt image polling attempt failed.",
                extra={"prompt_id": prompt_id, "error": str(exc)},
            )
        if time.time() - start > timeout:
            break
        time.sleep(interval)


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    """Return a decoded HTTP error body if one is available."""

    try:
        return error.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _normalize_server(server: str) -> str:
    """Return a host[:port] server value suitable for ComfyUI HTTP URLs."""

    normalized = server.strip()
    if not normalized:
        raise ComfyUIRequestError("ComfyUI server must not be empty.")
    if normalized != server or any(ch.isspace() for ch in normalized):
        raise ComfyUIRequestError("ComfyUI server must not contain whitespace.")
    if "://" in normalized or any(ch in normalized for ch in _SERVER_FORBIDDEN_CHARS):
        raise ComfyUIRequestError(
            "ComfyUI server must be a host[:port] value without scheme, path, query, or fragment."
        )
    return normalized


def _decode_json_object(
    response_body: bytes,
    *,
    operation: str,
    message_prefix: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decode an HTTP response body into the JSON object expected by ComfyUI."""

    log_context = context or {}
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        message = f"Could not decode {message_prefix}: {exc}"
        logger.error(
            message,
            extra={
                **log_context,
                "operation": operation,
                "response_body_length": len(response_body),
            },
        )
        raise ComfyUIRequestError(message) from exc
    if not isinstance(result, dict):
        message = f"Unexpected {message_prefix} format: {result}"
        logger.error(message, extra={**log_context, "operation": operation})
        raise ComfyUIRequestError(message)
    return result
