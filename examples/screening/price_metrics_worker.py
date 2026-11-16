"""Optional loopback worker for prepared price metrics and separate explicit saves."""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
from pathlib import Path

from sec_xbrl.metrics.market_inputs import encoded
from sec_xbrl.screening.price_metric_publication import PriceMetricReader
from sec_xbrl.screening.price_metric_service import PriceMetricService


def dispatch(service: PriceMetricService, message: dict) -> tuple[int, dict]:
    raw = base64.b64decode(message.get("body_base64", ""), validate=True)
    if len(raw) > 1024*1024:
        raise ValueError("price request exceeds limit")
    request = json.loads(raw) if raw else {}
    method, path = message["method"], message["path"]
    base = "/api/price-metrics"
    if method == "GET" and path == base:
        return 200, service.capability()
    if method == "GET" and path == base + "/saves":
        return 200, {"saves": service.saves()}
    if method == "GET" and path.startswith(base + "/saves/"):
        return 200, service.reopen(path.removeprefix(base + "/saves/"))
    if method == "POST" and path == base + "/saves":
        return 201, service.save(**request)
    if method == "POST" and path in {base + "/query", base + "/screen", base + "/bands", base + "/timeline", base + "/evidence"}:
        return 200, service.execute(path.rsplit("/", 1)[1], request)
    return 404, {"error": "unknown price metric route"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    service = PriceMetricService(PriceMetricReader({"path": args.manifest, "sha256": args.sha256}), args.journal)
    for line in sys.stdin.buffer:
        if len(line) > 2*1024*1024:
            return
        key = None
        try:
            message = json.loads(line)
            key = message["id"]
            if not isinstance(key, str):
                raise TypeError("request id required")
            status, payload = dispatch(service, message)
        except (ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            status, payload = 400, {"error": str(exc)}
        data = encoded(payload)
        if len(data) > 32*1024*1024:
            status, data = 413, b'{"error":"price response exceeds limit"}'
        print(json.dumps({"id": key, "status": status, "body_base64": base64.b64encode(data).decode(),
                          "headers": {"content-type": "application/json; charset=utf-8"}}), flush=True)


if __name__ == "__main__":
    main()
