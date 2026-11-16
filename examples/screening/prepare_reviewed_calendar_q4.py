"""New-path revenue companion from exact observations and an approved calendar.

No collector, existing publication, canonical mapping or source approval is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import polars as pl

from sec_xbrl.analytics.revenue_quarters import derive_revenue_q4
from sec_xbrl.periods.reviewed_calendar import FiscalCalendarRegistry, pinned


def prepare(observations: Path, *, observations_sha256: str, calendars: Path,
            calendars_sha256: str, output: Path) -> dict:
    """Publish one immutable companion; caller owns full input provenance review."""
    if output.exists():
        raise FileExistsError(output)
    source_pin = {"path": str(observations), "sha256": observations_sha256}
    pinned(source_pin)
    registry = FiscalCalendarRegistry.load(calendars, expected_sha256=calendars_sha256)
    rows = pl.read_parquet(observations).to_dicts()
    # T1 encodes nested evidence as JSON strings in physical Parquet.
    for row in rows:
        for key in ("raw_dimension_signature", "canonical_dimension_signature", "dimension_mapping_ids"):
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
    metrics, exclusions, coverage = [], [], []
    for calendar in registry.calendars:
        scoped = [row for row in rows if (row.get("cik"), row.get("fiscal_year")) == (calendar.cik, calendar.fiscal_year)]
        derived, held = derive_revenue_q4(scoped, cutoff=calendar.financial_as_of, calendar=calendar)
        metrics.extend(derived)
        exclusions.extend(held)
        coverage.append({"calendar_id": calendar.calendar_id, "cik": calendar.cik,
            "fiscal_year": calendar.fiscal_year, "input_count": len(scoped),
            "derived_count": len(derived), "exclusion_count": len(held),
            "reason": None if scoped else "CALENDAR_SCOPE_INPUT_NOT_PREPARED"})
    payload = {"schema_version": "reviewed-fiscal-calendar-revenue-q4-companion-v1",
        "observation_pin": source_pin, "calendar_artifact_sha256": calendars_sha256,
        "derived_metrics": metrics, "exclusions": exclusions, "coverage": coverage,
        "ratio_policy": "UNPREPARED_SEPARATE_PARENT_AND_PRIOR_COMPATIBILITY_REVIEW_REQUIRED"}
    pinned(source_pin)
    for calendar in registry.calendars:
        calendar.verify()
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".calendar-q4-", dir=output.parent)
    stage = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.link(stage, output)  # Atomic install; an existing destination is never replaced.
    finally:
        stage.unlink(missing_ok=True)
    return {"path": str(output), "sha256": hashlib.sha256(content).hexdigest(),
        "derived_count": len(metrics), "exclusion_count": len(exclusions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--observations-sha256", required=True)
    parser.add_argument("--calendars", required=True, type=Path)
    parser.add_argument("--calendars-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.observations, observations_sha256=args.observations_sha256,
        calendars=args.calendars, calendars_sha256=args.calendars_sha256, output=args.output)))


if __name__ == "__main__":
    main()
