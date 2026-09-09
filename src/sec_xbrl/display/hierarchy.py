"""Static H2 consumer. No Raw readers, XBRL parser or financial policy imports."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from sec_xbrl.analysis import AnalysisClient
from sec_xbrl.consumer.export import (
    export_snapshot,
    prepare_axis_snapshot,
    prepare_overview_snapshot,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_hierarchy(client: AnalysisClient, *, destination: Path, source_commit: str | None = None) -> None:
    """Write one table UI and local prepared JS shards, usable offline via file://."""
    if destination.exists():
        raise ValueError("new immutable HTML destination required")
    destination.mkdir(parents=True)
    font = Path("/mnt/c/Windows/Fonts/malgun.ttf")
    if font.is_file():
        shutil.copyfile(font, destination / "korean.ttf")
    catalog = {}
    for ticker, info in client.manifest["companies"].items():
        source = client.statement_catalog(ticker)
        filings = []
        for fid, fi in info["hierarchy"]["filings"].items():
            tables = [t for t in source["tables"] if t["filing_id"] == fid]
            panels = {t["table_id"]: client.statement(ticker, t["table_id"]) for t in tables}
            pre = {t["table_id"]: client.pre_table(ticker, t["table_id"])["pre_rows"] for t in tables if t["section"] != "DISCLOSURE"}
            lenses = client.axes(ticker, fid)
            members = {}
            for lens in lenses["axes"]:
                for member in lens["members"]:
                    key = _json([lens["axis_id"], member["member_id"], member["typed_value"]])
                    result = client.member_metrics(ticker, fid, axis_id=lens["axis_id"], member_id=member["member_id"], typed_value=member["typed_value"])
                    members[key] = {k: v for k, v in result.items() if k != "member_paths"}
            paths = client._hierarchy_records(ticker, "member_paths", fid)
            data = {"filing": fi["filing"], "tables": tables, "panels": panels, "pre": pre,
                    "axes": lenses, "members": members, "member_paths": paths}
            relative = Path(ticker) / (fid + ".js")
            (destination / relative).parent.mkdir(exist_ok=True)
            (destination / relative).write_text("window.HIERARCHY_DATA=" + _json(data) + ";window.hierarchyLoaded();", encoding="utf-8")
            filings.append({"filing": fi["filing"], "path": str(relative)})
        filings.sort(key=lambda f: (f["filing"]["report_date"], f["filing"]["filed_date"], f["filing"]["accession"]), reverse=True)
        overview = client.overview(ticker, fiscal_start=min(info["years"]), fiscal_end=max(info["years"]))
        overview_snapshot = prepare_overview_snapshot(
            client, ticker, fiscal_start=min(info["years"]), fiscal_end=max(info["years"])
        )
        overview_exports = _exports(destination, ticker, "overview", overview_snapshot)
        overview_row_exports = {
            row["row_id"]: _exports(
                destination, ticker, f"overview-{row['row_id']}",
                prepare_overview_snapshot(
                    client, ticker, fiscal_start=min(info["years"]),
                    fiscal_end=max(info["years"]), row_ids=[row["row_id"]],
                ),
            )
            for row in overview["rows"]
        }
        traces = {c["cell_id"]: client.trace(c["cell_id"], context=overview["context"])["trace"]
                  for c in overview["cells"] if c["status"] in {"REPORTED", "DERIVED"}}
        axis_series = {}
        for row in overview["rows"]:
            for lens in client.list_breakdowns(row["row_id"], context=overview["context"])["groups"]:
                if lens["lens_type"] == "DIMENSIONAL_VIEW":
                    axis_series[lens["node_id"]] = client.axis_timeseries(ticker, lens["node_id"], context=overview["context"])
        axis_exports = {
            lens_id: _exports(
                destination, ticker, f"axis-{lens_id}",
                prepare_axis_snapshot(client, ticker, lens_id, context=overview["context"]),
            )
            for lens_id in axis_series
        }
        relative = Path(ticker) / "analytical.js"
        (destination / relative).write_text("window.AXIS_COMPANY=" + _json(ticker) + ";window.AXIS_DATA=" + _json(axis_series) + ";window.axisLoaded();", encoding="utf-8")
        catalog[ticker] = {"axis_path": str(relative), "axis_lenses": [
            {"node_id": a["lens"]["node_id"], "label": a["lens"]["label"], "anchor_row_id": a["lens"]["anchor_row_id"]} for a in axis_series.values()],"filings": filings, "warnings": source["warnings"], "as_of": info["as_of"],
                           "source_review_cutoff": info["review_cutoff"], "importance": client.importance_v2(ticker),
                           "overview": overview, "traces": traces,
                           "exports": {"overview": overview_exports,
                                       "overview_rows": overview_row_exports,
                                       "axes": axis_exports}}
    static = Path(__file__).parent
    for name in ("hierarchy.js", "hierarchy.css"):
        (destination / name).write_bytes((static / name).read_bytes())
    page = (static / "hierarchy.html").read_text().replace("__CATALOG__", _json(catalog)).replace("__PUBLICATION__", _json({"id": client.manifest["publication_id"], "renderer_source_commit": source_commit, "decision_cutoff": client.manifest["decision_cutoff"], "policy": client.manifest["importance_v2_policy"]}))
    (destination / "index.html").write_text(page, encoding="utf-8")


def _exports(destination: Path, ticker: str, name: str, snapshot: dict) -> dict[str, str]:
    safe_name = "".join(character if character.isalnum() or character in "-_" else "-" for character in name)
    paths = {}
    for extension in ("json", "csv", "html", "xlsx"):
        relative = Path("exports") / ticker / f"{safe_name}.{extension}"
        export_snapshot(snapshot, destination / relative)
        paths[extension] = str(relative)
    return paths
