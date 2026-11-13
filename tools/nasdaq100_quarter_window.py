"""Pinned single-company quarter-window correction using an unchanged producer."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

VERSION = "nasdaq100-quarter-window-v1"
SOURCE_COMMIT = "401be11b04fd203f6e74eda7b34e44ca0e7bc406"


def pin_file(pin: dict) -> Path:
    """Resolve only explicit immutable, non-alias input files."""
    if set(pin) != {"path", "sha256"} or not isinstance(pin["path"], str):
        raise ValueError("expected an explicit file pin")
    path = Path(pin["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("pinned path must be absolute without aliases")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("pinned file changed")
    return path


def quarter_bounds(columns: list[dict]) -> tuple[int, int]:
    """Use actual available QTD years, never completed annual-year inference."""
    years = sorted({row["fiscal_year"] for row in columns
                    if row.get("column_status") == "AVAILABLE"
                    and row.get("period_class") == "QTD_3M"})[-5:]
    if not years or any(type(year) is not int for year in years):
        raise ValueError("no valid available QTD fiscal years")
    if years != list(range(years[0], years[-1] + 1)):
        raise ValueError("nonconsecutive QTD years require explicit review")
    return years[0], years[-1]


def prepare_company(plan_path: Path, expected_sha: str, ticker: str, result: Path) -> dict:
    """Run one new publication; orchestration/resource ownership stays external."""
    import polars as pl

    from sec_xbrl import analysis
    from tools import universe50_t3v2_ops as resource_ops

    resource_ops.install_parent_death_guard()
    plan = json.loads(pin_file({"path": str(plan_path), "sha256": expected_sha}).read_bytes())
    source = Path(plan["source_root"])
    if plan["schema_version"] != VERSION or plan["source_commit"] != SOURCE_COMMIT:
        raise ValueError("unsupported correction source or plan")
    if not source.is_absolute() or source.resolve() != source:
        raise ValueError("source root must be absolute without aliases")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "src"], cwd=source, text=True)
    if actual != SOURCE_COMMIT or dirty or Path(analysis.__file__).resolve() != source / "src/sec_xbrl/analysis.py":
        raise ValueError("worker must import unchanged frozen401 producer")
    rows = [row for row in plan["companies"] if row["ticker"] == ticker]
    if len(rows) != 1:
        raise ValueError("ticker must occur exactly once in the pinned plan")
    row = rows[0]
    paths = {key: pin_file(row[key]) for key in ("history_manifest", "annual_manifest", "quarterly_manifest")}
    history = json.loads(paths["history_manifest"].read_bytes())
    tables = [t for t in history["tables"] if t["ticker"] == ticker and t["cik"] == row["cik"]
              and t["period_class"] == "QTD_3M" and t["view"] == "LATEST_REPORTED"]
    if len(tables) != 1:
        raise ValueError("expected exactly one company QTD header table")
    table = tables[0]
    declaration = table["files"]["columns"]
    relative = Path(declaration["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid History header path")
    header = pin_file({"path": str(paths["history_manifest"].parent / relative), "sha256": declaration["sha256"]})
    start, end = quarter_bounds(pl.read_parquet(header).to_dicts())
    if (row["fiscal_start"], row["fiscal_end"]) != (start, end):
        raise ValueError("planned bounds differ from actual QTD headers")
    for key in ("annual_manifest", "quarterly_manifest"):
        manifest = json.loads(paths[key].read_bytes())
        scope = manifest["companies"][ticker]
        if (Path(scope["source_publication"]) != paths["history_manifest"].parent
                or manifest["source_manifest_hashes"]["history_manifest_sha256"] != row["history_manifest"]["sha256"]
                or scope["as_of"] != table["scope"]["selection_as_of_date"]):
            raise ValueError("analysis parents differ from the pinned History/cutoff")
    destination = Path(row["destination"])
    if not destination.is_absolute() or any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("destination must be absolute without aliases")
    if not result.is_absolute() or any(p.is_symlink() for p in (result, *result.parents)):
        raise ValueError("result must be absolute without aliases")
    if destination.exists() or result.exists():
        raise ValueError("existing output requires verified driver receipt; never overwrite")
    analysis.prepare_analysis(
        publication=paths["history_manifest"].parent, destination=destination,
        tickers=(ticker,), fiscal_years=5, fiscal_start=start, fiscal_end=end,
        configuration=None, period_mode="QUARTERLY", include_year_end_balances=False,
        include_quarter_source_evidence=True,
    )
    output = destination / "analysis_manifest.json"
    payload = {"schema_version": VERSION, "status": "PASS", "ticker": ticker,
               "plan": {"path": str(plan_path), "sha256": expected_sha},
               "fiscal_start": start, "fiscal_end": end,
               "manifest": {"path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}}
    result.parent.mkdir(parents=True, exist_ok=True)
    with result.open("x") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    prepare_company(args.plan, args.plan_sha256, args.ticker, args.result)


if __name__ == "__main__":
    main()
