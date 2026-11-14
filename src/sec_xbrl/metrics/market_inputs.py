"""Offline common financial inputs and a separate, evidence-bound market EPS rule.

Consumes selected Analysis cells. Does not select filings or derive quarterly EPS.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise
from pathlib import Path

from sec_xbrl.analysis import open_analysis, stable

REGISTRY = {
    "reported_eps_basic_and_diluted_total": (
        "us-gaap:EarningsPerShareBasicAndDiluted",
        "USD/share",
    ),
    "reported_eps_basic_total": ("us-gaap:EarningsPerShareBasic", "USD/share"),
    "reported_eps_diluted_total": ("us-gaap:EarningsPerShareDiluted", "USD/share"),
    "reported_eps_basic_continuing": (
        "us-gaap:IncomeLossFromContinuingOperationsPerBasicShare",
        "USD/share",
    ),
    "reported_eps_diluted_continuing": (
        "us-gaap:IncomeLossFromContinuingOperationsPerDilutedShare",
        "USD/share",
    ),
    "weighted_average_basic_shares": (
        "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
        "shares",
    ),
    "weighted_average_diluted_shares": (
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
        "shares",
    ),
    "outstanding_common_shares_balance": ("us-gaap:CommonStockSharesOutstanding", "shares"),
    "outstanding_common_shares_cover": ("dei:EntityCommonStockSharesOutstanding", "shares"),
}
TTM_RULE = "market_eps_diluted_ttm_direct_qtd_v1"


def encoded(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def identity(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def pinned_json(pin: dict) -> dict:
    path = Path(pin["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("source pin requires an absolute regular file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin.get("sha256"):
        raise ValueError("source hash mismatch")
    return json.loads(data)


def finite(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _unit(lineage: dict, unit_kind: str) -> bool:
    def parts(value):
        return json.loads(value) if isinstance(value, str) else value

    return parts(lineage.get("unit_numerator_measures")) == (
        ["iso4217:USD"] if unit_kind == "USD/share" else ["xbrli:shares"]
    ) and parts(lineage.get("unit_denominator_measures")) == (
        ["xbrli:shares"] if unit_kind == "USD/share" else []
    )


def project_financial_inputs(
    pin: dict, *, cik: str, ticker: str, financial_as_of: str
) -> list[dict]:
    """Batch selected VALUE cells, then read each necessary trace shard once."""
    manifest = pinned_json(pin)
    client = open_analysis(Path(pin["path"]).parent)
    if client.manifest != manifest:
        raise ValueError("analysis manifest changed during open")
    info = manifest["companies"][ticker]
    if info["as_of"] != financial_as_of:
        raise ValueError("analysis cutoff mismatch")
    nodes = {
        n["node_id"]: n
        for n in client._records(ticker, "LATEST_REPORTED", "nodes")
        if n.get("kind") == "VALUE" and n.get("concept") in {v[0] for v in REGISTRY.values()}
    }
    cells = [
        c for c in client._records(ticker, "LATEST_REPORTED", "cells") if c["node_id"] in nodes
    ]
    trace_ids = defaultdict(set)
    for cell in cells:
        trace_ids["trace_" + stable(cell["cell_id"])[0]].add(cell["cell_id"])
    traces = {
        t["cell_id"]: t
        for name, ids in trace_ids.items()
        for t in client._records(ticker, "LATEST_REPORTED", name)
        if t["cell_id"] in ids
    }
    output = []
    by_qname = {q: (name, kind) for name, (q, kind) in REGISTRY.items()}
    for cell in cells:
        node = nodes[cell["node_id"]]
        name, kind = by_qname[node["concept"]]
        trace = traces.get(cell["cell_id"], {})
        lineage = trace.get("value_lineage") or {}
        value = finite(cell.get("value"))
        reason = None
        if cell.get("status") not in {"REPORTED", "RECAST_REPORTED"} or lineage.get(
            "source_type"
        ) not in {"REPORTED", "RECAST_REPORTED"}:
            reason = "DIRECT_OBSERVATION_REQUIRED"
        elif cell.get("quality_blocking") or cell.get("quality_status") == "BLOCK":
            reason = "QUALITY_BLOCKED"
        elif not _unit(lineage, kind):
            reason = "UNIT_NOT_COMPATIBLE"
        elif value is None:
            reason = "SOURCE_VALUE_MISSING"
        elif (
            lineage.get("raw_concept_qname") != node["concept"]
            or not lineage.get("raw_concept_namespace_uri")
            or not lineage.get("raw_concept_id")
            or not lineage.get("context_id")
            or not lineage.get("source_snapshot_id")
            or not lineage.get("source_filing_id")
            or not cell.get("source_fact_id")
            or cell["source_fact_id"] != lineage.get("selected_source_fact_id")
            or not str(lineage.get("company_canonical_concept_id", "")).startswith(
                f"company:{cik}:"
            )
            or finite(lineage.get("value_numeric")) != value
        ):
            reason = "SOURCE_IDENTITY_NOT_CONFIRMED"
        elif not lineage.get("filed_date") or date.fromisoformat(
            lineage["filed_date"]
        ) > date.fromisoformat(financial_as_of):
            reason = "SOURCE_AFTER_CUTOFF"
        elif lineage.get("selection_as_of_date") != financial_as_of:
            reason = "SELECTION_CUTOFF_MISMATCH"
        if reason is None and (kind == "shares" and value < 0):
            reason = "INVALID_SHARE_COUNT"
        record = {
            "cik": cik,
            "ticker": ticker,
            "input_id": name,
            "unit_kind": kind,
            "period_class": cell["period_class"],
            "fiscal_year": cell["fiscal_year"],
            "fiscal_quarter": cell["fiscal_quarter"],
            "start": cell.get("start"),
            "end": cell.get("end"),
            "end_convention": "EXCLUSIVE",
            "dimensions": node.get("dimensions", []),
            "raw_dimensions": lineage.get("raw_dimension_signature"),
            "namespace": lineage.get("raw_concept_namespace_uri"),
            "qname": node["concept"],
            "unit": cell.get("unit"),
            "stock_class_id": None,
            "share_basis_id": None,
            "value": str(value) if reason is None else None,
            "source_value": cell.get("value"),
            "status": "AVAILABLE_REPORTED" if reason is None else "UNAVAILABLE",
            "reason": reason,
            "reported_or_derived": "REPORTED" if reason is None else None,
            "upstream_value_status": cell.get("status"),
            "upstream_source_type": lineage.get("source_type"),
            "filed_date": lineage.get("filed_date"),
            "filed_date_precision": "DAY",
            "selection_view": "LATEST_REPORTED",
            "financial_as_of": financial_as_of,
            "source": {
                "analysis_manifest": pin,
                "publication_id": manifest["publication_id"],
                "cell_id": cell["cell_id"],
                "node_id": cell["node_id"],
                "trace_shard": "trace_" + stable(cell["cell_id"])[0],
                **{
                    k: lineage.get(k)
                    for k in (
                        "selected_source_fact_id",
                        "source_snapshot_id",
                        "source_filing_id",
                        "accession",
                        "context_id",
                        "raw_concept_id",
                        "selection_rule_version",
                        "period_classification_reason",
                    )
                },
            },
        }
        record["observation_id"] = "market-input-" + identity(record)
        output.append(record)
    # Fail closed if a manifest was replaced while its tables were being read.
    pinned_json(pin)
    return sorted(output, key=lambda r: r["observation_id"])


def derive_market_eps_ttm(
    observations: list[dict], *, cik: str, financial_as_of: str, declaration: dict | None = None
) -> dict:
    """A declaration binds four existing input IDs; it cannot manufacture EPS."""
    result = {
        "cik": cik,
        "input_id": TTM_RULE,
        "definition_version": TTM_RULE,
        "reported_or_derived": "DERIVED",
        "unit_kind": "USD/share",
        "status": "UNAVAILABLE",
        "value": None,
        "reason": "SHARE_BASIS_UNKNOWN",
        "input_observation_ids": [],
    }
    if declaration is None:
        return result

    def reject(reason):
        return dict(result, reason=reason)

    if (
        declaration.get("cik") != cik
        or not declaration.get("stock_class_id")
        or not declaration.get("basis_id")
        or declaration.get("currency") != "USD"
        or not declaration.get("source_pins")
    ):
        return reject("CLASS_OR_BASIS_NOT_CONFIRMED")
    if not declaration.get("available_on") or date.fromisoformat(
        declaration["available_on"]
    ) > date.fromisoformat(financial_as_of):
        return reject("BASIS_EVIDENCE_AFTER_CUTOFF")
    ids = declaration.get("observation_ids", [])
    if len(ids) != 4 or len(set(ids)) != 4:
        return reject("FOUR_DIRECT_QUARTERS_REQUIRED")
    matches = [r for r in observations if r.get("observation_id") in ids]
    if len(matches) != 4 or {r["observation_id"] for r in matches} != set(ids):
        return reject("INPUT_IDENTITY_NOT_CONFIRMED")
    if any(
        r.get("cik") != cik
        or r.get("input_id") != "reported_eps_diluted_total"
        or r.get("period_class") != "QTD_3M"
        or r.get("status") != "AVAILABLE_REPORTED"
        or r.get("reported_or_derived") != "REPORTED"
        or r.get("unit_kind") != "USD/share"
        or not r.get("filed_date")
        or r["filed_date"] > financial_as_of
        or finite(r.get("value")) is None
        for r in matches
    ):
        return reject("FOUR_DIRECT_QUARTERS_REQUIRED")
    scopes = {
        encoded([r.get("dimensions"), r.get("raw_dimensions"), r.get("unit")]) for r in matches
    }
    if any(
        not _unit(
            {"unit_numerator_measures": r["unit"][0], "unit_denominator_measures": r["unit"][1]},
            "USD/share",
        )
        for r in matches
    ):
        return reject("SCOPE_OR_UNIT_NOT_COMPATIBLE")
    latest = max(
        (
            r.get("end") or ""
            for r in observations
            if r.get("cik") == cik
            and r.get("input_id") == "reported_eps_diluted_total"
            and r.get("period_class") == "QTD_3M"
        ),
        default="",
    )
    if max(r.get("end") or "" for r in matches) != latest:
        return reject("LATEST_DIRECT_QUARTERS_NOT_PREPARED")
    if len(scopes) != 1:
        return reject("SCOPE_OR_UNIT_NOT_COMPATIBLE")
    matches.sort(key=lambda r: (r.get("end") or "", r["observation_id"]))
    coords = [r["fiscal_year"] * 4 + r["fiscal_quarter"] - 1 for r in matches]
    if any(b != a + 1 for a, b in pairwise(coords)):
        return reject("QUARTER_GAP_OR_DUPLICATE")
    for i, row in enumerate(matches):
        if not row.get("start") or not row.get("end"):
            return reject("ACTUAL_PERIOD_NOT_CONFIRMED")
        days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
        if not 75 <= days <= 105 or row.get("end_convention") != "EXCLUSIVE":
            return reject("ACTUAL_PERIOD_NOT_CONFIRMED")
        if i and matches[i - 1]["end"] != row["start"]:
            return reject("QUARTER_GAP_OR_DUPLICATE")
        # Competing selected observations of the same actual period/scope are not a winner policy.
        competing = [
            r
            for r in observations
            if r.get("cik") == cik
            and r.get("input_id") == row["input_id"]
            and r.get("period_class") == "QTD_3M"
            and r.get("start") == row["start"]
            and r.get("end") == row["end"]
            and r.get("dimensions") == row.get("dimensions")
        ]
        if len({r["observation_id"] for r in competing}) != 1:
            return reject("AMBIGUOUS_DIRECT_QUARTER")
    values = [Decimal(r["value"]) for r in matches]
    exponent = min(v.as_tuple().exponent for v in values)
    with localcontext() as ctx:
        ctx.prec = (
            sum(len(v.as_tuple().digits) for v in values)
            + max(abs(v.adjusted() - exponent) for v in values)
            + 10
        )
        value = sum(values, Decimal(0))
    return {
        **result,
        "status": "AVAILABLE_DERIVED_SEPARATE",
        "reason": None,
        "value": format(value, "f"),
        "start": matches[0]["start"],
        "end": matches[-1]["end"],
        "end_convention": "EXCLUSIVE",
        "stock_class_id": declaration["stock_class_id"],
        "share_basis_id": declaration["basis_id"],
        "input_observation_ids": [r["observation_id"] for r in matches],
        "basis_evidence": declaration,
        "formula": "SUM(FOUR_DIRECT_QTD_DILUTED_EPS)",
    }


def deduplicate_financial_inputs(rows: list[dict]) -> list[dict]:
    """Same selected Raw fact may be referenced by several prepared role nodes."""
    grouped = {}
    for row in rows:
        source = row["source"]
        key = [
            row["cik"],
            row["input_id"],
            source.get("source_snapshot_id"),
            source.get("source_filing_id"),
            source.get("selected_source_fact_id"),
            row["period_class"],
            row["start"],
            row["end"],
            row["namespace"],
            row["qname"],
            row["unit"],
            row["raw_dimensions"],
        ]
        logical_id = "market-input-" + identity(key)
        copied = dict(row, observation_id=logical_id)
        refs = copied.pop("analysis_references", [source])
        if logical_id in grouped:
            prior = grouped[logical_id]
            if any(
                prior.get(k) != copied.get(k) for k in ("value", "source_value", "status", "reason")
            ):
                raise ValueError("same Raw observation has conflicting prepared values")
            for ref in refs:
                if ref not in prior["analysis_references"]:
                    prior["analysis_references"].append(ref)
        else:
            copied["analysis_references"] = refs
            grouped[logical_id] = copied
    return sorted(grouped.values(), key=lambda row: row["observation_id"])


def project_cover_shares(
    analysis_pin: dict,
    *,
    cik: str,
    ticker: str,
    financial_as_of: str,
    intake_pin: dict | None = None,
) -> list[dict]:
    """Retained Raw cover candidates only; no analytical selection/class inference."""
    import polars as pl

    manifest = pinned_json(analysis_pin)
    if intake_pin is None:
        history_path = (
            Path(manifest["companies"][ticker]["source_publication"]) / "history_manifest.json"
        )
        history_pin = {
            "path": str(history_path),
            "sha256": manifest["source_manifest_hashes"]["history_manifest_sha256"],
        }
        history = pinned_json(history_pin)
        intake_path = Path(history["source_intake"])
        intake_pin = {
            "path": str(intake_path),
            "sha256": hashlib.sha256(intake_path.read_bytes()).hexdigest(),
        }
    intake = pinned_json(intake_pin)
    entries = [
        e
        for e in intake["filings"]
        if e["ticker"] == ticker
        and e["filing"]["cik"] == cik
        and e["status"] in {"INGESTED", "REUSED"}
        and e["filing"]["filed_date"] <= financial_as_of
        and e["filing"]["form"] in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
    ]
    if not entries:
        return []
    latest = max(e["filing"]["filed_date"] for e in entries)
    # Preserve concurrent filings/candidates instead of inventing an accession winner.
    output = []
    for entry in entries:
        if entry["filing"]["filed_date"] != latest:
            continue
        filing = entry["filing"]
        root = Path(entry["source_run"]) / "snapshots" / cik / filing["accession"].replace("-", "")
        raw_manifest_path = root / "layer1_manifest.json"
        raw_pin = {
            "path": str(raw_manifest_path),
            "sha256": hashlib.sha256(raw_manifest_path.read_bytes()).hexdigest(),
        }
        raw_manifest = pinned_json(raw_pin)
        if raw_manifest["cik"] != cik or raw_manifest["accession"] != filing["accession"]:
            raise ValueError("Raw cover manifest identity mismatch")
        pins = {}

        def table(name, root=root, pins=pins):
            path = root / (name + ".parquet")
            if path.is_symlink() or not path.is_file():
                raise ValueError("unsafe Raw table")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = pl.read_parquet(path).to_dicts()
            if hashlib.sha256(path.read_bytes()).hexdigest() != before:
                raise ValueError("Raw table changed while projecting")
            pins[name] = {"path": str(path), "sha256": before}
            return result

        concepts = {r["raw_concept_id"]: r for r in table("concept")}
        wanted = {
            k
            for k, v in concepts.items()
            if v["qname"] == "dei:EntityCommonStockSharesOutstanding"
            and v["is_standard"] is True
            and v["period_type"] == "instant"
        }
        if not wanted:
            continue
        filings = table("filing")
        if len(filings) != 1 or any(
            filings[0].get(k) != filing.get(k) for k in ("cik", "accession", "filed_date", "form")
        ):
            raise ValueError("Raw cover filing identity mismatch")
        facts = [r for r in table("fact") if r["raw_concept_id"] in wanted]
        contexts = {r["context_id"]: r for r in table("context")}
        units = {r["unit_id"]: r for r in table("unit")}
        dims = defaultdict(list)
        for d in table("dimension_fact"):
            dims[d["fact_id"]].append(d)
        for fact in facts:
            context = contexts[fact["context_id"]]
            unit = units.get(fact["unit_id"], {})
            concept = concepts[fact["raw_concept_id"]]
            if (
                fact["filing_id"] != filings[0]["filing_id"]
                or context["filing_id"] != fact["filing_id"]
                or context["period_kind"] != "INSTANT"
                or not context["instant_date"]
            ):
                raise ValueError("Raw cover fact scope mismatch")
            number = finite(fact["value_numeric"])
            reason = None
            if fact["is_nil"] or number is None or number < 0:
                reason = "SOURCE_VALUE_MISSING"
            elif not _unit(
                {
                    "unit_numerator_measures": unit.get("numerator_measures"),
                    "unit_denominator_measures": unit.get("denominator_measures"),
                },
                "shares",
            ):
                reason = "UNIT_NOT_COMPATIBLE"
            elif (
                date.fromisoformat(context["instant_date"]) - date.fromisoformat(financial_as_of)
            ).days > 1:
                reason = "SOURCE_PERIOD_AFTER_CUTOFF"
            dimensions = sorted(dims[fact["fact_id"]], key=encoded)
            qdims = [
                {
                    **d,
                    "axis_qname": concepts.get(d["axis_raw_concept_id"], {}).get("qname"),
                    "member_qname": concepts.get(d["member_raw_concept_id"], {}).get("qname"),
                }
                for d in dimensions
            ]
            record = {
                "cik": cik,
                "ticker": ticker,
                "input_id": "outstanding_common_shares_cover",
                "unit_kind": "shares",
                "period_class": "INSTANT",
                "fiscal_year": None,
                "fiscal_quarter": None,
                "start": None,
                "end": context["instant_date"],
                "end_convention": "EXCLUSIVE",
                "dimensions": qdims,
                "raw_dimensions": dimensions,
                "namespace": concept["namespace_uri"],
                "qname": concept["qname"],
                "unit": [unit.get("numerator_measures"), unit.get("denominator_measures")],
                "stock_class_id": None,
                "share_basis_id": None,
                "value": str(number) if reason is None else None,
                "source_value": fact["value_numeric"],
                "status": "AVAILABLE_REPORTED" if reason is None else "UNAVAILABLE",
                "reason": reason,
                "reported_or_derived": "REPORTED",
                "filed_date": filing["filed_date"],
                "filed_date_precision": "DAY",
                "financial_as_of": financial_as_of,
                "selection_view": "RAW_AS_FILED_LATEST_ELIGIBLE_FILING_NO_CLASS_WINNER",
                "source": {
                    "intake": intake_pin,
                    "raw_manifest": raw_pin,
                    "raw_tables": pins,
                    "source_snapshot_id": str(root),
                    "selected_source_fact_id": fact["fact_id"],
                    "source_filing_id": fact["filing_id"],
                    "accession": filing["accession"],
                    "context_id": fact["context_id"],
                    "raw_concept_id": fact["raw_concept_id"],
                    "source_document": fact["source_document"],
                    "source_locator": fact["source_locator"],
                },
            }
            output.append(record)
    pinned_json(intake_pin)
    return output
