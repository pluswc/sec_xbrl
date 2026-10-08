"""Source-attested, explicitly reviewed dimensional Q4 companion.

This producer never promotes the broad mechanical-Q4 publication.  It starts
from exact FY/YTD pairs copied from one immutable history publication and emits
a value only when a caller-supplied review decision still matches every source
identity and measurement-scope field.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.history import _write_records, open_history_publication
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot

VERSION = "reviewed-dimensional-q4-v1"
RULE_VERSION = "reviewed-exact-fy-ytd9m-residual-v1"
APPROVAL = "APPROVE_EXACT_Q4_SOURCE_PAIR"


@dataclass(frozen=True, slots=True)
class ReviewedQ4Build:
    """Validated records ready for one immutable reviewed-Q4 publication."""

    candidates: tuple[dict[str, Any], ...]
    exclusions: tuple[dict[str, Any], ...]
    reviews: tuple[dict[str, Any], ...]
    derived: tuple[dict[str, Any], ...]
    source_snapshots: tuple[dict[str, str], ...]


def generate_reviewed_q4(
    *, history_publication: Path, source_evidence: Path, review_ledger: Path
) -> ReviewedQ4Build:
    """Re-attest candidate pairs and exact review decisions without writing output."""
    history_publication = Path(history_publication)
    source_evidence = Path(source_evidence)
    review_ledger = Path(review_ledger)
    parent_manifest = history_publication / "history_manifest.json"
    parent_sha = _sha256(parent_manifest)
    evidence_sha = _sha256(source_evidence)
    evidence = _read_json(source_evidence)
    ledger = _read_json(review_ledger)
    if evidence.get("history_manifest_sha256") != parent_sha:
        raise ValueError("source evidence does not match parent history manifest")
    if Path(evidence.get("history_publication", "")).resolve() != history_publication.resolve():
        raise ValueError("source evidence names a different parent history publication")
    if ledger.get("source_evidence_sha256") != evidence_sha:
        raise ValueError("review ledger does not match exact source evidence")
    if ledger.get("history_manifest_sha256") != parent_sha:
        raise ValueError("review ledger does not match parent history manifest")
    if Path(ledger.get("history_publication", "")).resolve() != history_publication.resolve():
        raise ValueError("review ledger names a different parent history publication")

    reader = open_history_publication(history_publication)
    reader.verify_all()
    tables = evidence.get("tables")
    pairs = evidence.get("pairs")
    approvals = ledger.get("approvals")
    if not isinstance(tables, list) or not isinstance(pairs, list) or not isinstance(approvals, list):
        raise TypeError("reviewed-Q4 inputs require tables, pairs, and approvals lists")
    if ledger.get("approval_count") != len(approvals):
        raise ValueError("review ledger approval count mismatch")
    if len({row.get("decision_id") for row in approvals}) != len(approvals):
        raise ValueError("review ledger decision identities must be unique")
    economic_approvals = {
        (row.get("scope", {}).get("fiscal_year"), row.get("scope", {}).get("member_qname"),
         row.get("approved_expected_value"))
        for row in approvals
    }
    if ledger.get("distinct_product_period_values") != len(economic_approvals):
        raise ValueError("review ledger distinct product-period count mismatch")
    table_index = _unique_index(tables, lambda row: (row.get("accession"), row.get("fact_id")), "evidence table")
    approval_index = _unique_index(approvals, _approval_key, "approval scope")

    panel_cache: dict[tuple[str, str, str], Any] = {}
    snapshot_cache: dict[Path, Any] = {}
    snapshots: dict[Path, dict[str, str]] = {}
    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    matched_approvals: set[tuple[Any, ...]] = set()

    for pair in pairs:
        candidate, problem = _candidate(
            pair, reader=reader, panel_cache=panel_cache, snapshot_cache=snapshot_cache,
            snapshots=snapshots, table_index=table_index
        )
        if candidate["candidate_id"] in seen_candidate_ids:
            raise ValueError("duplicate reviewed-Q4 candidate identity")
        seen_candidate_ids.add(candidate["candidate_id"])
        candidates.append(candidate)
        key = _candidate_approval_key(candidate)
        approval = approval_index.get(key)
        if problem is not None:
            exclusions.append(_exclusion(candidate, problem))
            if approval is not None:
                raise ValueError(f"approved reviewed-Q4 source pair is invalid: {problem}")
            continue
        if approval is None:
            exclusions.append(_exclusion(candidate, "EXACT_SOURCE_PAIR_REVIEW_REQUIRED"))
            continue
        review = _validate_approval(approval, candidate, table_index)
        matched_approvals.add(key)
        reviews.append(review)
        derived.append(_derived(candidate, review))

    extra = set(approval_index) - matched_approvals
    if extra:
        raise ValueError("review ledger contains approvals outside exact source candidates")
    for note in ledger.get("excluded_scope_notes", []):
        if not isinstance(note, str) or not note:
            raise ValueError("excluded scope note must be non-empty text")
        exclusions.append({
            "exclusion_id": _id("policy-exclusion", note),
            "candidate_id": None,
            "ticker": None,
            "selection_view": None,
            "selection_as_of_date": None,
            "fiscal_year": None,
            "fiscal_quarter": None,
            "mapping_epoch": None,
            "member_qname": None,
            "reason": "LEAD_SCOPE_NOT_APPROVED",
            "detail": note,
            "value_numeric": None,
        })
    if len(derived) != len(reviews):
        raise AssertionError("every accepted review must have exactly one derived record")
    return ReviewedQ4Build(
        tuple(candidates), tuple(exclusions), tuple(reviews), tuple(derived),
        tuple(sorted(snapshots.values(), key=lambda row: row["path"])),
    )


def publish_reviewed_q4(
    *, history_publication: Path, source_evidence: Path, review_ledger: Path,
    destination: Path
) -> Path:
    """Publish a new immutable reviewed-Q4 companion after complete validation."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("reviewed-Q4 publication requires a new destination")
    history_publication = Path(history_publication)
    source_evidence = Path(source_evidence)
    review_ledger = Path(review_ledger)
    build = generate_reviewed_q4(
        history_publication=history_publication,
        source_evidence=source_evidence,
        review_ledger=review_ledger,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".reviewed-q4.partial-", dir=destination.parent))
    datasets = {
        "candidate": build.candidates,
        "exclusion": build.exclusions,
        "review": build.reviews,
        "derived": build.derived,
    }
    files = {}
    for name, records in datasets.items():
        relative = f"reviewed_q4_{name}.parquet"
        files[name] = {"path": relative, **_write_records(staging / relative, records)}
    manifest = {
        "version": VERSION,
        "rule_version": RULE_VERSION,
        "publication_id": _id(
            "publication", _sha256(source_evidence), _sha256(review_ledger),
            _sha256(history_publication / "history_manifest.json")
        ),
        "history_publication": str(history_publication.resolve()),
        "history_manifest_sha256": _sha256(history_publication / "history_manifest.json"),
        "source_evidence_path": str(source_evidence.resolve()),
        "source_evidence_sha256": _sha256(source_evidence),
        "review_ledger_path": str(review_ledger.resolve()),
        "review_ledger_sha256": _sha256(review_ledger),
        "source_snapshots": list(build.source_snapshots),
        "files": files,
        "counts": {name: len(records) for name, records in datasets.items()},
        "selection_as_of_dates": sorted({row["selection_as_of_date"] for row in build.candidates}),
        "views": sorted({row["selection_view"] for row in build.candidates}),
    }
    (staging / "reviewed_q4_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ReviewedQ4Reader(staging, allow_staging=True).verify_all()
    staging.rename(destination)
    return destination


class ReviewedQ4Reader:
    """Integrity-check and read one immutable reviewed-Q4 companion."""

    def __init__(self, root: Path, *, allow_staging: bool = False) -> None:
        self.root = Path(root)
        if self.root.is_symlink() or (self.root.name.startswith(".reviewed-q4.partial-") and not allow_staging):
            raise ValueError("partial or symlink reviewed-Q4 publication is not consumable")
        self.manifest = _read_json(self.root / "reviewed_q4_manifest.json")
        if self.manifest.get("version") != VERSION:
            raise ValueError("unsupported reviewed-Q4 publication")

    def records(self, name: str) -> tuple[dict[str, Any], ...]:
        if name not in {"candidate", "exclusion", "review", "derived"}:
            raise ValueError("unknown reviewed-Q4 dataset")
        return self._records(self.manifest["files"][name])

    def verify_all(self) -> None:
        parent = Path(self.manifest["history_publication"])
        if _sha256(parent / "history_manifest.json") != self.manifest["history_manifest_sha256"]:
            raise ValueError("reviewed-Q4 parent history identity changed")
        open_history_publication(parent).verify_all()
        for field in ("source_evidence", "review_ledger"):
            if _sha256(Path(self.manifest[f"{field}_path"])) != self.manifest[f"{field}_sha256"]:
                raise ValueError(f"reviewed-Q4 {field.replace('_', ' ')} changed")
        for source in self.manifest["source_snapshots"]:
            snapshot_path = Path(source["path"])
            snapshot_manifest = _read_json(snapshot_path / "layer1_manifest.json")
            if _sha256(snapshot_path / "layer1_manifest.json") != source["manifest_sha256"]:
                raise ValueError("reviewed-Q4 source snapshot manifest changed")
            snapshot = _load_declared_cohort_snapshot(
                snapshot_path, snapshot_manifest["cik"], snapshot_manifest["accession"]
            )
            if snapshot.input.snapshot_id != source["snapshot_id"]:
                raise ValueError("reviewed-Q4 source snapshot identity changed")
        for name in ("candidate", "exclusion", "review", "derived"):
            if len(self.records(name)) != self.manifest["counts"][name]:
                raise ValueError("reviewed-Q4 dataset count mismatch")

    def _records(self, info: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        import polars as pl

        relative = Path(info["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe reviewed-Q4 dataset path")
        path = self.root / relative
        if path.is_symlink() or _sha256(path) != info["sha256"]:
            raise ValueError("reviewed-Q4 dataset integrity mismatch")
        records = pl.read_parquet(path).to_dicts()
        if len(records) != info["count"]:
            raise ValueError("reviewed-Q4 dataset row count mismatch")
        return tuple({
            key: json.loads(value) if key in info["json_fields"] and value is not None else value
            for key, value in row.items()
        } for row in records)


def _candidate(
    pair: dict[str, Any], *, reader: Any, panel_cache: dict[tuple[str, str, str], Any],
    snapshot_cache: dict[Path, Any], snapshots: dict[Path, dict[str, str]],
    table_index: dict[tuple[Any, ...], dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    fy_cell = pair.get("fy_cell")
    ytd_cell = pair.get("ytd_cell")
    if not isinstance(fy_cell, dict) or not isinstance(ytd_cell, dict):
        raise TypeError("candidate needs exact FY and YTD cells")
    fy = fy_cell.get("value_lineage") or {}
    ytd = ytd_cell.get("value_lineage") or {}
    definition = fy_cell.get("definition") or {}
    ytd_definition = ytd_cell.get("definition") or {}
    ticker = _ticker(reader, definition.get("company_cik"))
    view = pair.get("selection_view")
    year = pair.get("fiscal_year")
    epoch = pair.get("mapping_epoch")
    if view not in {"AS_FILED", "LATEST_REPORTED"} or not isinstance(year, int) or not epoch:
        raise ValueError("candidate has invalid view, fiscal year, or mapping epoch")
    if fy_cell.get("fiscal_time_series_row_id") != epoch or ytd_cell.get("fiscal_time_series_row_id") != epoch:
        raise ValueError("candidate mapping epoch differs from exact source cells")
    if any(source.get("label") != pair.get("member_qname") for source in (definition, ytd_definition)):
        raise ValueError("candidate member identity differs from source row")
    _attest_parent_cell(reader, panel_cache, ticker, view, "FY", fy_cell)
    _attest_parent_cell(reader, panel_cache, ticker, view, "YTD_9M", ytd_cell)
    for source, lineage in ((pair.get("fy"), fy), (pair.get("ytd_9m"), ytd)):
        if not isinstance(source, dict) or source.get("value_lineage") != lineage:
            raise ValueError("candidate source record differs from exact history cell")
        _attest_snapshot(source, lineage, snapshot_cache, snapshots)
    evidence_ids = [pair["fy"].get("table_textblock_fact_id"), pair["ytd_9m"].get("table_textblock_fact_id")]
    evidence_tables = []
    sources = (pair["fy"], pair["ytd_9m"])
    for position, (accession, fact_id) in enumerate(
        zip((fy.get("accession"), ytd.get("accession")), evidence_ids, strict=True)
    ):
        table = table_index.get((accession, fact_id))
        if table is None:
            raise ValueError("candidate source table evidence is missing")
        snapshot = snapshot_cache[Path(sources[position]["snapshot_path"])]
        table_matches = [row for row in snapshot.records("fact") if row.get("fact_id") == fact_id]
        if len(table_matches) != 1 or table_matches[0] != table.get("raw_fact"):
            raise ValueError("candidate source table Fact differs from source snapshot")
        evidence_tables.append({
            "accession": accession,
            "fact_id": fact_id,
            "text_sha256": _text_sha256(table.get("text")),
            "raw_fact_sha256": _canonical_sha256(table.get("raw_fact")),
        })

    key = [view, pair.get("selection_as_of_date"), year, epoch, pair.get("member_qname"),
           fy.get("selected_source_fact_id"), ytd.get("selected_source_fact_id")]
    candidate = {
        "candidate_id": _id("candidate", key),
        "ticker": ticker,
        "cik": definition.get("company_cik"),
        "selection_view": view,
        "selection_as_of_date": pair.get("selection_as_of_date"),
        "fiscal_year": year,
        "fiscal_quarter": 4,
        "period_class": "QTD_3M",
        "mapping_epoch": epoch,
        "frozen_report_node_id": pair.get("frozen_report_node_id"),
        "member_qname": pair.get("member_qname"),
        "company_canonical_concept_id": fy.get("company_canonical_concept_id"),
        "canonical_dimension_signature": fy.get("canonical_dimension_signature"),
        "unit_numerator_measures": _json_list(fy.get("unit_numerator_measures")),
        "unit_denominator_measures": _json_list(fy.get("unit_denominator_measures")),
        "actual_start_date": ytd.get("context_end_date"),
        "actual_end_date": fy.get("context_end_date"),
        "value_numeric": None,
        "formula": "FY - YTD_9M",
        "derivation_rule_version": RULE_VERSION,
        "source_fact_ids": [fy.get("selected_source_fact_id"), ytd.get("selected_source_fact_id")],
        "source_filing_ids": [fy.get("source_filing_id"), ytd.get("source_filing_id")],
        "source_accessions": [fy.get("accession"), ytd.get("accession")],
        "source_snapshot_ids": [fy.get("source_snapshot_id"), ytd.get("source_snapshot_id")],
        "source_snapshot_manifest_sha256s": [
            pair["fy"].get("snapshot_manifest_sha256"),
            pair["ytd_9m"].get("snapshot_manifest_sha256"),
        ],
        "source_cell_ids": [fy_cell.get("fiscal_time_series_cell_id"), ytd_cell.get("fiscal_time_series_cell_id")],
        "source_inputs": [fy, ytd],
        "source_table_evidence": evidence_tables,
        "status": "STRUCTURAL_CANDIDATE_REVIEW_REQUIRED",
        "reported_or_derived": "CANDIDATE",
        "old_mechanical_candidate_id": None,
    }
    problem = _structural_problem(candidate, fy_cell, ytd_cell, fy, ytd)
    if problem is None:
        try:
            value = Decimal(str(fy["value_numeric"])) - Decimal(str(ytd["value_numeric"]))
        except (KeyError, TypeError, InvalidOperation):
            problem = "NON_NUMERIC_SOURCE_VALUE"
        else:
            if not value.is_finite():
                problem = "NON_FINITE_SOURCE_VALUE"
            else:
                candidate["value_numeric"] = str(value)
                if pair.get("candidate_value") != candidate["value_numeric"]:
                    raise ValueError("source evidence candidate value differs from exact residual")
    if problem is None and _q4_materialized(reader, panel_cache, ticker, view, year, epoch):
        problem = "Q4_COORDINATE_ALREADY_MATERIALIZED"
    return candidate, problem


def _structural_problem(
    candidate: dict[str, Any], fy_cell: dict[str, Any], ytd_cell: dict[str, Any],
    fy: dict[str, Any], ytd: dict[str, Any]
) -> str | None:
    if (fy.get("period_class"), ytd.get("period_class")) != ("FY", "YTD_9M"):
        return "PERIOD_CLASS_MISMATCH"
    if any(cell.get("value_status") != "REPORTED" for cell in (fy_cell, ytd_cell)):
        return "SOURCE_CELL_NOT_REPORTED"
    if any(row.get("source_type") != "REPORTED" or row.get("comparative_type") != "CURRENT_FOCUS" for row in (fy, ytd)):
        return "SOURCE_NOT_CURRENT_FOCUS_REPORTED"
    if any(row.get("mapping_review_required") is not False for row in (fy, ytd)):
        return "MAPPING_REVIEW_REQUIRED"
    if fy.get("context_start_date") != ytd.get("context_start_date"):
        return "ACTUAL_START_DATE_MISMATCH"
    if candidate["selection_as_of_date"] != fy.get("selection_as_of_date") or candidate["selection_as_of_date"] != ytd.get("selection_as_of_date"):
        return "SELECTION_AS_OF_MISMATCH"
    if candidate["selection_view"] != fy.get("selection_view") or candidate["selection_view"] != ytd.get("selection_view"):
        return "SELECTION_VIEW_MISMATCH"
    if any(row.get("filed_date") > candidate["selection_as_of_date"] for row in (fy, ytd)):
        return "SOURCE_FILED_AFTER_SELECTION_AS_OF"
    for field in ("company_canonical_concept_id", "canonical_dimension_signature"):
        if fy.get(field) != ytd.get(field):
            return "INCOMPATIBLE_" + field.upper()
    for field in ("basis_version", "structural_version", "recast_version"):
        if fy.get(field) != ytd.get(field):
            return "INCOMPATIBLE_" + field.upper()
    if candidate["unit_numerator_measures"] != _json_list(ytd.get("unit_numerator_measures")):
        return "INCOMPATIBLE_UNIT_NUMERATOR"
    if candidate["unit_denominator_measures"] != _json_list(ytd.get("unit_denominator_measures")):
        return "INCOMPATIBLE_UNIT_DENOMINATOR"
    if len(candidate["unit_numerator_measures"]) != 1 or not str(candidate["unit_numerator_measures"][0]).startswith("iso4217:"):
        return "MONETARY_NUMERATOR_REQUIRED"
    if candidate["unit_denominator_measures"]:
        return "DENOMINATOR_UNIT_NOT_ADDITIVE"
    if not candidate["canonical_dimension_signature"]:
        return "DIMENSIONED_SCOPE_REQUIRED"
    try:
        days = (date.fromisoformat(fy["context_end_date"]) - date.fromisoformat(ytd["context_end_date"])).days
    except (TypeError, ValueError):
        return "INVALID_ACTUAL_PERIOD_BOUNDARY"
    if not 75 <= days <= 105:
        return "Q4_DURATION_OUT_OF_RANGE"
    return None


def _validate_approval(
    approval: dict[str, Any], candidate: dict[str, Any],
    table_index: dict[tuple[Any, ...], dict[str, Any]],
) -> dict[str, Any]:
    required = ("decision_id", "reviewer", "known_at", "purpose", "policy_version", "additivity", "basis_compatibility")
    if approval.get("decision") != APPROVAL or any(not approval.get(field) for field in required):
        raise ValueError("review decision lacks required approval fields")
    if approval.get("approved_expected_value") != candidate["value_numeric"]:
        raise ValueError("reviewed expected value differs from exact residual")
    if approval.get("fy_accession") != candidate["source_accessions"][0] or approval.get("ytd_accession") != candidate["source_accessions"][1]:
        raise ValueError("review decision accession differs from source pair")
    for prefix, position in (("fy", 0), ("ytd", 1)):
        if approval.get(f"{prefix}_snapshot_manifest_sha256") != candidate["source_snapshot_manifest_sha256s"][position]:
            raise ValueError("review decision snapshot differs from source pair")
        evidence_id = approval.get(f"{prefix}_evidence_fact_id")
        if evidence_id != candidate["source_table_evidence"][position]["fact_id"]:
            raise ValueError("review decision evidence table differs from source pair")
        table = table_index[(candidate["source_accessions"][position], evidence_id)]
        optional_hashes = {
            f"{prefix}_evidence_text_sha256": _text_sha256(table.get("text")),
            f"{prefix}_evidence_raw_fact_sha256": _canonical_sha256(table.get("raw_fact")),
        }
        for field, expected in optional_hashes.items():
            if field in approval and approval[field] != expected:
                raise ValueError("review decision bounded table evidence hash mismatch")
    return {
        **approval,
        "candidate_id": candidate["candidate_id"],
        "source_table_evidence": candidate["source_table_evidence"],
        "formula": candidate["formula"],
        "derivation_rule_version": candidate["derivation_rule_version"],
        "canonical_dimension_signature": candidate["canonical_dimension_signature"],
        "unit_numerator_measures": candidate["unit_numerator_measures"],
        "unit_denominator_measures": candidate["unit_denominator_measures"],
        "actual_start_date": candidate["actual_start_date"],
        "actual_end_date": candidate["actual_end_date"],
    }


def _derived(candidate: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "derived_cell_id": _id("derived", candidate["candidate_id"], review["decision_id"]),
        "review_id": review["decision_id"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["known_at"],
        "review_purpose": review["purpose"],
        "review_policy_version": review["policy_version"],
        "additivity": review["additivity"],
        "basis_compatibility": review["basis_compatibility"],
        "status": "DERIVED",
        "reported_or_derived": "DERIVED",
        "semantic_review_state": "REVIEWED_EXACT_SOURCE_PAIR",
    }


def _exclusion(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "exclusion_id": _id("exclusion", candidate["candidate_id"], reason),
        "candidate_id": candidate["candidate_id"],
        "ticker": candidate["ticker"],
        "selection_view": candidate["selection_view"],
        "selection_as_of_date": candidate["selection_as_of_date"],
        "fiscal_year": candidate["fiscal_year"],
        "fiscal_quarter": 4,
        "mapping_epoch": candidate["mapping_epoch"],
        "member_qname": candidate["member_qname"],
        "reason": reason,
        "detail": None,
        "value_numeric": None,
    }


def _attest_parent_cell(reader: Any, cache: dict[tuple[str, str, str], Any], ticker: str,
                        view: str, period_class: str, expected: dict[str, Any]) -> None:
    key = (ticker, view, period_class)
    if key not in cache:
        cache[key] = reader.load(ticker=ticker, period_class=period_class, view=view)
    matches = [row for row in cache[key].cells
               if row.get("fiscal_time_series_cell_id") == expected.get("fiscal_time_series_cell_id")]
    if len(matches) != 1 or matches[0] != expected:
        raise ValueError("source evidence cell differs from parent history publication")


def _q4_materialized(reader: Any, cache: dict[tuple[str, str, str], Any], ticker: str,
                     view: str, year: int, epoch: str) -> bool:
    key = (ticker, view, "QTD_3M")
    if key not in cache:
        cache[key] = reader.load(ticker=ticker, period_class="QTD_3M", view=view)
    panel = cache[key]
    columns = {row["fiscal_time_series_column_id"] for row in panel.columns
               if row["fiscal_year"] == year and row["fiscal_quarter"] == 4}
    return any(row["fiscal_time_series_row_id"] == epoch
               and row["fiscal_time_series_column_id"] in columns for row in panel.cells)


def _attest_snapshot(source: dict[str, Any], lineage: dict[str, Any], cache: dict[Path, Any],
                     snapshots: dict[Path, dict[str, str]]) -> None:
    path = Path(source.get("snapshot_path", ""))
    accession = source.get("accession")
    cik = str(lineage.get("source_snapshot_id", "")).split(":")[1]
    expected_sha = source.get("snapshot_manifest_sha256")
    if _sha256(path / "layer1_manifest.json") != expected_sha:
        raise ValueError("candidate source snapshot manifest mismatch")
    if path not in cache:
        cache[path] = _load_declared_cohort_snapshot(path, cik, accession)
    snapshot = cache[path]
    if snapshot.input.snapshot_id != lineage.get("source_snapshot_id"):
        raise ValueError("candidate source snapshot identity mismatch")
    raw_fact = source.get("raw_fact")
    matches = [row for row in snapshot.records("fact") if row.get("fact_id") == lineage.get("selected_source_fact_id")]
    if len(matches) != 1 or matches[0] != raw_fact:
        raise ValueError("candidate raw Fact differs from source snapshot")
    snapshots[path] = {"path": str(path.resolve()), "manifest_sha256": expected_sha,
                       "snapshot_id": snapshot.input.snapshot_id}


def _ticker(reader: Any, cik: str | None) -> str:
    names = {table["ticker"] for table in reader.manifest["tables"] if table.get("cik") == cik}
    if len(names) != 1:
        raise ValueError("candidate CIK does not identify one parent company")
    return names.pop()


def _approval_key(row: dict[str, Any]) -> tuple[Any, ...]:
    scope = row.get("scope") or {}
    return (scope.get("selection_view"), scope.get("selection_as_of_date"), scope.get("fiscal_year"),
            scope.get("mapping_epoch"), scope.get("member_qname"), scope.get("fy_fact_id"), scope.get("ytd_fact_id"))


def _candidate_approval_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["selection_view"], row["selection_as_of_date"], row["fiscal_year"], row["mapping_epoch"],
            row["member_qname"], *row["source_fact_ids"])


def _unique_index(rows: list[dict[str, Any]], key: Any, label: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result:
            raise ValueError(f"duplicate {label}")
        result[identity] = row
    return result


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        raise TypeError("measurement scope must be a JSON list")
    return parsed


def _id(kind: str, *parts: Any) -> str:
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"reviewed-q4:{kind}:{digest}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text_sha256(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source table evidence text is missing")
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    if not isinstance(value, dict):
        raise TypeError("source table raw Fact is missing")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe JSON input: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"JSON input must be an object: {path}")
    return value
