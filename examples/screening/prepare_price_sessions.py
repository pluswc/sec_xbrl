"""Offline explicit XNYS sessions, with pinned producer/calendar review evidence.

Run in an environment containing exchange_calendars. Output is append-only.
The producer is an explicit calendar source, never inferred from price rows.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import date
from pathlib import Path


def build_sessions(start: str, end: str, evidence_pin: dict) -> dict:
    import exchange_calendars

    path = Path(evidence_pin["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("calendar evidence requires an absolute regular file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != evidence_pin["sha256"]:
        raise ValueError("calendar evidence hash differs")
    json.loads(data)
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("invalid calendar coverage")
    calendar = exchange_calendars.get_calendar("XNYS", start=start, end=end)
    days = [d.strftime("%Y-%m-%d") for d in calendar.sessions if start <= d.strftime("%Y-%m-%d") <= end]
    # Bounded known holiday/extraordinary-closure regression sentinels. They do
    # not replace the pinned complete source calendar and reviewed coverage.
    for closed in ("2025-01-01", "2025-01-09", "2025-12-25", "2026-01-01", "2026-07-03", "2026-12-25"):
        if start <= closed <= end and closed in days:
            raise ValueError("calendar failed a reviewed US closure sentinel")
    result = {"schema_version": "verified-us-sessions-v1", "market": "US_EQUITIES", "verified": True,
              "calendar": "XNYS", "coverage_start": start, "coverage_end": end, "sessions": days,
              "source_pins": [evidence_pin], "producer": {"package": "exchange_calendars",
              "version": importlib.metadata.version("exchange_calendars"),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "calendar_module_sha256": hashlib.sha256(Path(__import__("inspect").getfile(calendar.__class__)).read_bytes()).hexdigest()}}
    if not days or days != sorted(set(days)) or not start <= days[0] <= days[-1] <= end:
        raise ValueError("invalid explicit calendar range")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("start", "end", "evidence", "evidence-sha256", "output"):
        parser.add_argument("--" + arg, required=True)
    args = parser.parse_args()
    result = build_sessions(args.start, args.end, {"path": args.evidence, "sha256": args.evidence_sha256})
    data = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    with Path(args.output).open("xb") as stream:
        stream.write(data)
    print(json.dumps({"path": str(Path(args.output).absolute()), "sha256": hashlib.sha256(data).hexdigest(), "sessions": len(result["sessions"])}))


if __name__ == "__main__":
    main()
