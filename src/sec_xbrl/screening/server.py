"""Loopback-only standard-library HTTP transport for screening."""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sec_xbrl.screening.common import require_string, safe_write_directory
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.ui import CSS, HTML, JS

MAX_BODY = 1024 * 1024
ID = r"[A-Za-z0-9_-]+"


def serve(
    service: ScreeningService,
    *,
    export_root: Path | str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve until interrupted; only loopback addresses are accepted."""
    address = ipaddress.ip_address(host)
    if not address.is_loopback:
        raise ValueError("screening service may bind only to a loopback address")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid HTTP port")
    root = safe_write_directory(Path(export_root), "screening export root")
    handler = _handler(service, root)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def create_server(
    service: ScreeningService,
    *,
    export_root: Path | str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a loopback server for controlled callers and offline tests."""
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("screening service may bind only to a loopback address")
    root = safe_write_directory(Path(export_root), "screening export root")
    return ThreadingHTTPServer((host, port), _handler(service, root))


def _handler(service: ScreeningService, export_root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SECXBRLScreening/1"

        def do_GET(self) -> None:
            try:
                self._get()
            except Exception as exc:  # noqa: BLE001 - transport converts application errors
                self._error(exc)

        def do_POST(self) -> None:
            try:
                self._check_origin()
                self._post()
            except Exception as exc:  # noqa: BLE001 - transport converts application errors
                self._error(exc)

        def do_PUT(self) -> None:
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

        do_DELETE = do_PUT
        do_PATCH = do_PUT

        def _get(self) -> None:
            parsed = urlparse(self.path)
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            if parsed.path == "/":
                self._text(HTML, "text/html; charset=utf-8")
            elif parsed.path == "/app.css":
                self._text(CSS, "text/css; charset=utf-8")
            elif parsed.path == "/app.js":
                self._text(JS, "text/javascript; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self._bytes(b"", "image/x-icon", HTTPStatus.NO_CONTENT)
            elif parsed.path == "/api/status":
                self._json(service.status())
            elif parsed.path == "/api/screens":
                self._json(service.store.list_screens())
            elif parsed.path == "/api/runs":
                self._json(service.store.list_runs(query.get("revision_id")))
            elif parsed.path == "/api/decisions":
                self._json(service.decisions(query.get("cik")))
            elif parsed.path == "/api/availability":
                self._json(service.metric_availability(query["dataset_id"], cik=query.get("cik")))
            elif parsed.path == "/api/metric-catalog":
                self._json(service.metric_catalog(query["dataset_id"]))
            elif parsed.path == "/api/explorer":
                self._json(service.company_explorer(
                    query["dataset_id"], fiscal_year=_optional_int(query.get("fiscal_year")),
                    query=query.get("query"), sort=query.get("sort", "company"),
                    direction=query.get("direction", "asc"),
                ))
            elif parsed.path == "/api/metric-library":
                self._json(service.metric_library(
                    query["dataset_id"], fiscal_year=_optional_int(query.get("fiscal_year")),
                    query=query.get("query"), category=query.get("category"),
                ))
            elif parsed.path == "/api/company-profile":
                self._json(service.company_profile(
                    query["dataset_id"], cik=query["cik"],
                    fiscal_year=_optional_int(query.get("fiscal_year")),
                ))
            elif parsed.path == "/api/company-comparison":
                self._json(service.company_comparison(
                    query["dataset_id"], ciks=query["ciks"].split(","),
                    metric_ids=query["metric_ids"].split(","),
                    fiscal_year=_optional_int(query.get("fiscal_year")),
                ))
            elif parsed.path == "/api/series":
                self._json(service.metric_series(query["dataset_id"], cik=query["cik"], metric_id=query["metric_id"]))
            elif parsed.path == "/api/metadata":
                prepared = None if "prepared" not in query else _bool(query["prepared"])
                self._json(service.metadata_inventory(
                    query["dataset_id"], query=query.get("query"), sic_code=query.get("sic_code"),
                    prepared=prepared, offset=int(query.get("offset", 0)), limit=int(query.get("limit", 100)),
                ))
            elif parsed.path == "/api/peers":
                self._json(service.peer_candidates(query["dataset_id"], cik=query["cik"]))
            elif parsed.path == "/api/run-comparison":
                self._json(service.compare_runs(query["old_run_id"], query["new_run_id"]))
            elif parsed.path == "/api/peer-comparison":
                self._json(service.compare_peers(
                    query["dataset_id"], ciks=query["ciks"].split(","),
                    metric_id=query["metric_id"], fiscal_year=int(query["fiscal_year"]),
                ))
            elif match := re.fullmatch(rf"/api/revisions/({ID})", parsed.path):
                self._json(service.store.revision(match.group(1)))
            elif match := re.fullmatch(rf"/api/runs/({ID})", parsed.path):
                self._json(service.run(match.group(1)))
            elif match := re.fullmatch(rf"/api/runs/({ID})/trace", parsed.path):
                self._json(service.trace(match.group(1), cik=query["cik"], metric_id=query["metric_id"]))
            elif parsed.path.startswith("/exports/"):
                name = parsed.path.removeprefix("/exports/")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    raise ValueError("unsafe export name")
                path = export_root / name
                if not path.is_file() or path.is_symlink() or path.resolve().parent != export_root.resolve():
                    raise ValueError("export does not exist")
                service.store.export_for_path(path)
                self._bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _post(self) -> None:
            parsed = urlparse(self.path)
            body = self._body()
            if parsed.path == "/api/screens":
                self._json(service.create_screen(body.get("name"), body.get("content")), HTTPStatus.CREATED)
            elif match := re.fullmatch(rf"/api/screens/({ID})/revisions", parsed.path):
                self._json(service.revise_screen(match.group(1), body.get("content")), HTTPStatus.CREATED)
            elif parsed.path == "/api/runs":
                self._json(service.execute(body.get("revision_id"), body.get("dataset_id")), HTTPStatus.CREATED)
            elif parsed.path == "/api/decisions":
                self._json(service.add_decision(
                    cik=body.get("cik"), state=body.get("state"), rationale=body.get("rationale"),
                    run_id=body.get("run_id"), actor=body.get("actor"), evidence_ids=body.get("evidence_ids"),
                ), HTTPStatus.CREATED)
            elif match := re.fullmatch(rf"/api/runs/({ID})/exports", parsed.path):
                run_id = match.group(1)
                selected_format = require_string(body.get("format"), "format").lower()
                scope = require_string(body.get("scope"), "scope").upper()
                name = (
                    f"{run_id}-{scope.lower()}-{selected_format}-"
                    f"{uuid.uuid4().hex}.{selected_format}"
                )
                result = service.export_run(
                    run_id, export_root / name, scope=scope,
                    selected_ciks=body.get("selected_ciks"), format=selected_format,
                )
                self._json({**result, "download_url": "/exports/" + name}, HTTPStatus.CREATED)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if not 0 < length <= MAX_BODY:
                raise ValueError("JSON body is empty or too large")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise TypeError("JSON body must be an object")
            return value

        def _check_origin(self) -> None:
            origin = self.headers.get("Origin")
            if origin is None:
                return
            parsed = urlparse(origin)
            try:
                address = ipaddress.ip_address(parsed.hostname or "")
            except ValueError as exc:
                raise PermissionError("state-changing request origin is not loopback") from exc
            if parsed.scheme != "http" or not address.is_loopback or parsed.netloc != self.headers.get("Host"):
                raise PermissionError("state-changing request origin differs from local service")

        def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._bytes(
                json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"),
                "application/json; charset=utf-8", status,
            )

        def _text(self, value: str, content_type: str) -> None:
            self._bytes(value.encode("utf-8"), content_type)

        def _bytes(
            self,
            value: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(value)

        def _error(self, exc: Exception) -> None:
            status = HTTPStatus.FORBIDDEN if isinstance(exc, PermissionError) else HTTPStatus.BAD_REQUEST
            self._json({"error": str(exc)}, status)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def _bool(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError("boolean query must be true or false")
    return value == "true"


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("query value must be an integer") from exc
