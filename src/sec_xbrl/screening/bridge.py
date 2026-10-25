"""Bounded JSON-line relay for a Windows loopback to WSL loopback bridge.

The relay carries HTTP bytes to an already running screening service. It does
not open screening publications, stores, or financial data itself.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import http.client
import json
import re
import sys
from collections.abc import Callable
from typing import Any, TextIO
from urllib.parse import urlsplit

MAX_REQUEST_BODY = 1024 * 1024
MAX_RESPONSE_BODY = 32 * 1024 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EXPORT_PATH = re.compile(r"^/exports/[A-Za-z0-9_.-]+$")
API_PATH = re.compile(r"^/api(?:/[A-Za-z0-9_.-]+)*$")
RESPONSE_HEADERS = {
    "cache-control",
    "content-disposition",
    "content-length",
    "content-security-policy",
    "content-type",
    "referrer-policy",
    "x-content-type-options",
}


def relay_request(
    message: Any,
    *,
    backend_port: int,
    connection_factory: Callable[..., http.client.HTTPConnection] = http.client.HTTPConnection,
) -> dict[str, Any]:
    """Validate and relay one request to the fixed 127.0.0.1 backend."""
    port = _port(backend_port, "backend port")
    if not isinstance(message, dict):
        raise TypeError("bridge message must be an object")
    request_id = message.get("id")
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ValueError("bridge request ID is invalid")
    method = message.get("method")
    if method not in {"GET", "POST"}:
        raise ValueError("bridge method is not allowed")
    path = _path(message.get("path"))
    body = _body(message.get("body_base64", ""))
    if method == "GET" and body:
        raise ValueError("GET bridge request cannot carry a body")
    headers = message.get("headers", {})
    if not isinstance(headers, dict):
        raise TypeError("bridge headers must be an object")
    content_type = headers.get("content-type")
    if method == "POST" and content_type != "application/json":
        raise ValueError("POST bridge request must be application/json")
    outgoing = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
    }
    if content_type is not None:
        outgoing["Content-Type"] = content_type
    accept = headers.get("accept")
    if isinstance(accept, str) and 0 < len(accept) <= 256 and "\r" not in accept and "\n" not in accept:
        outgoing["Accept"] = accept

    connection = connection_factory("127.0.0.1", port, timeout=30)
    try:
        connection.request(method, path, body=body or None, headers=outgoing)
        response = connection.getresponse()
        response_body = response.read(MAX_RESPONSE_BODY + 1)
        if len(response_body) > MAX_RESPONSE_BODY:
            raise ValueError("backend response exceeds bridge limit")
        response_headers = {
            key.lower(): value
            for key, value in response.getheaders()
            if key.lower() in RESPONSE_HEADERS and "\r" not in value and "\n" not in value
        }
        return {
            "id": request_id,
            "status": int(response.status),
            "headers": response_headers,
            "body_base64": base64.b64encode(response_body).decode("ascii"),
        }
    finally:
        connection.close()


def run_relay(
    backend_port: int,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    connection_factory: Callable[..., http.client.HTTPConnection] = http.client.HTTPConnection,
) -> int:
    """Process newline-delimited relay messages until stdin closes."""
    port = _port(backend_port, "backend port")
    for raw_line in input_stream:
        request_id: str | None = None
        try:
            if len(raw_line) > (MAX_REQUEST_BODY * 2) + 4096:
                raise ValueError("bridge message exceeds limit")
            message = json.loads(raw_line)
            if isinstance(message, dict) and isinstance(message.get("id"), str):
                request_id = message["id"]
            result = relay_request(
                message, backend_port=port, connection_factory=connection_factory
            )
        except Exception as exc:  # noqa: BLE001 - line protocol returns bounded errors
            result = {
                "id": request_id,
                "relay_error": type(exc).__name__,
                "message": str(exc)[:512],
            }
        output_stream.write(json.dumps(result, separators=(",", ":")) + "\n")
        output_stream.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sec_xbrl.screening.bridge")
    parser.add_argument("--backend-port", type=int, required=True)
    args = parser.parse_args(argv)
    return run_relay(args.backend_port)


def _port(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError(f"{label} is invalid")
    return value


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096:
        raise ValueError("bridge path is invalid")
    if "\r" in value or "\n" in value or "\\" in value:
        raise ValueError("bridge path contains unsafe characters")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("bridge path must be local")
    if parsed.path not in {"/", "/app.css", "/app.js", "/favicon.ico"} and not (
        API_PATH.fullmatch(parsed.path) or EXPORT_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("bridge path is not allowed")
    return value


def _body(value: Any) -> bytes:
    if not isinstance(value, str):
        raise TypeError("bridge body must be base64 text")
    try:
        body = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("bridge body is not valid base64") from exc
    if len(body) > MAX_REQUEST_BODY:
        raise ValueError("bridge request body exceeds limit")
    return body


if __name__ == "__main__":
    raise SystemExit(main())
