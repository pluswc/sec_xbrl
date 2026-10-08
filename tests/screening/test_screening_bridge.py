from __future__ import annotations

import base64
import io
import json
from typing import ClassVar

import pytest

from sec_xbrl.screening.bridge import MAX_REQUEST_BODY, relay_request, run_relay


class _Response:
    status = 206

    def read(self, _limit: int) -> bytes:
        return b"PK\x03\x04\x00binary"

    def getheaders(self) -> list[tuple[str, str]]:
        return [
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", 'attachment; filename="run.xlsx"'),
            ("X-Private", "must-not-cross"),
        ]


class _Connection:
    instances: ClassVar[list[_Connection]] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.request_args = None
        self.closed = False
        self.instances.append(self)

    def request(self, *args, **kwargs) -> None:
        self.request_args = (args, kwargs)

    def getresponse(self) -> _Response:
        return _Response()

    def close(self) -> None:
        self.closed = True


def test_relay_rewrites_local_origin_and_preserves_binary_response() -> None:
    _Connection.instances.clear()
    result = relay_request(
        {
            "id": "request-7",
            "method": "POST",
            "path": "/api/runs/run-1/exports",
            "headers": {"content-type": "application/json", "accept": "application/json"},
            "body_base64": base64.b64encode(b'{"scope":"FULL"}').decode(),
        },
        backend_port=8765,
        connection_factory=_Connection,
    )
    connection = _Connection.instances[0]
    assert (connection.host, connection.port, connection.timeout) == ("127.0.0.1", 8765, 30)
    args, kwargs = connection.request_args
    assert args[:2] == ("POST", "/api/runs/run-1/exports")
    assert kwargs["headers"]["Host"] == "127.0.0.1:8765"
    assert kwargs["headers"]["Origin"] == "http://127.0.0.1:8765"
    assert kwargs["body"] == b'{"scope":"FULL"}'
    assert result["status"] == 206
    assert base64.b64decode(result["body_base64"]) == b"PK\x03\x04\x00binary"
    assert result["headers"]["content-disposition"] == 'attachment; filename="run.xlsx"'
    assert "x-private" not in result["headers"]
    assert connection.closed is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"method": "DELETE"}, "method"),
        ({"path": "http://example.com/api/status"}, "path"),
        ({"path": "/../private"}, "path"),
        ({"path": "/exports/../../private"}, "path"),
        ({"body_base64": "%%%"}, "base64"),
        ({"headers": {"content-type": "text/plain"}}, "application/json"),
    ],
)
def test_relay_rejects_unbounded_or_external_requests(change: dict, message: str) -> None:
    request = {
        "id": "safe-id",
        "method": "POST",
        "path": "/api/screens",
        "headers": {"content-type": "application/json"},
        "body_base64": base64.b64encode(b"{}").decode(),
    }
    request.update(change)
    with pytest.raises((TypeError, ValueError), match=message):
        relay_request(request, backend_port=8765, connection_factory=_Connection)


def test_relay_rejects_body_limit_and_invalid_identity_before_connect() -> None:
    _Connection.instances.clear()
    with pytest.raises(ValueError, match="exceeds"):
        relay_request(
            {
                "id": "request-1",
                "method": "POST",
                "path": "/api/screens",
                "headers": {"content-type": "application/json"},
                "body_base64": base64.b64encode(b"x" * (MAX_REQUEST_BODY + 1)).decode(),
            },
            backend_port=8765,
            connection_factory=_Connection,
        )
    with pytest.raises(ValueError, match="ID"):
        relay_request({"id": "../bad", "method": "GET", "path": "/", "headers": {}}, backend_port=8765)
    assert _Connection.instances == []


def test_json_line_relay_correlates_success_and_bounded_error() -> None:
    valid = {
        "id": "a1",
        "method": "GET",
        "path": "/api/status?detail=1",
        "headers": {},
        "body_base64": "",
    }
    input_stream = io.StringIO(json.dumps(valid) + "\n" + "not-json\n")
    output_stream = io.StringIO()
    assert run_relay(
        8765,
        input_stream=input_stream,
        output_stream=output_stream,
        connection_factory=_Connection,
    ) == 0
    lines = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert lines[0]["id"] == "a1" and lines[0]["status"] == 206
    assert lines[1]["id"] is None and lines[1]["relay_error"] == "JSONDecodeError"
    assert len(lines[1]["message"]) <= 512
