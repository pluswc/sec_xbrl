"""Filing-version ledger over immutable Layer 1 snapshots.

The ledger makes filing chronology and amendment evidence queryable.  It is
not an as-of selector and it never infers an amendment chain from changed fact
values or the numeric portions of an accession.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import (
    Layer2Publication,
    OperationalLayer2Publisher,
    VerifiedLayer2Publication,
    _read_publication_manifest,
    _run_from_manifest,
    _validate_accession_version_ledger,
    _validate_operational_manifest_shape,
)

ACCESSION_VERSION_LEDGER_RULE_VERSION = "l2-t4-accession-version-ledger-v1"
_ACCESSION_RE = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
_ORDINAL_RE = re.compile(
    r"\bamendment\s+(?:number|no\.?|#)\s*(\d+)\b", re.IGNORECASE
)


class AccessionVersionLedgerError(RuntimeError):
    """Raised when an immutable filing cannot be safely represented in the ledger."""


@dataclass(frozen=True, slots=True)
class AccessionVersionLedgerResult:
    publication: Layer2Publication
    filing_count: int


class AccessionVersionLedgerPipeline:
    """Publish one evidence-bearing version row per admitted Layer 1 filing."""

    dataset = "accession_version_ledger"

    def publish(self, release: CorpusRelease, *, output_root: Path) -> AccessionVersionLedgerResult:
        if not isinstance(release, CorpusRelease):
            raise AccessionVersionLedgerError("T4-A requires an explicit CorpusRelease")
        inputs_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for snapshot in release.snapshots:
            filing_rows = snapshot.records("filing")
            if len(filing_rows) != 1:
                raise AccessionVersionLedgerError("admitted snapshot must have exactly one filing row")
            filing = filing_rows[0]
            if str(filing.get("cik") or "") != snapshot.input.cik:
                raise AccessionVersionLedgerError("snapshot filing identity disagrees with CorpusRelease")
            if any(
                str(filing.get(key) or "") != str(getattr(snapshot.input, key) or "")
                for key in ("accession", "form", "filed_date", "report_date")
            ):
                raise AccessionVersionLedgerError("snapshot filing provenance disagrees with declared input")
            inputs_by_cik[snapshot.input.cik].append(
                {
                    "filing": filing,
                    "snapshot_id": snapshot.input.snapshot_id,
                    "amendment_evidence": _amendment_evidence(snapshot.records("concept"), snapshot.records("fact")),
                }
            )

        rows: list[dict[str, Any]] = []
        for cik in release.ciks:
            company_rows = inputs_by_cik[cik]
            rows.extend(_ledger_rows(cik, company_rows))
        publication = OperationalLayer2Publisher(Path(output_root)).publish(
            release.layer2_run, {self.dataset: tuple(rows)}
        )
        return AccessionVersionLedgerResult(publication, len(rows))


class AccessionVersionLedgerReader:
    """Read the chronology for exactly one company without selecting a value."""

    dataset = "accession_version_ledger"

    def query_parquet(self, run_root: Path, *, cik: str) -> tuple[dict[str, Any], ...]:
        root = Path(run_root)
        manifest = _read_publication_manifest(root / "layer2_run_manifest.json")
        if manifest.get("storage_format") != "parquet-operational-v1":
            raise AccessionVersionLedgerError("ledger fast query requires operational Parquet")
        try:
            _validate_operational_manifest_shape(manifest)
            run = _run_from_manifest(manifest)
        except Exception as exc:
            raise AccessionVersionLedgerError("ledger publication manifest is invalid") from exc
        if root.name != run.run_version or manifest.get("run_fingerprint") != run.fingerprint:
            raise AccessionVersionLedgerError("ledger publication declaration is invalid")
        if self.dataset not in manifest["output_counts"]:
            raise AccessionVersionLedgerError("publication has no accession version ledger")
        if cik not in {item.cik for item in run.inputs}:
            raise AccessionVersionLedgerError("requested CIK is outside the declared publication")
        path = root / cik / self.dataset / "ledger.parquet"
        if not path.is_file() or path.is_symlink():
            raise AccessionVersionLedgerError("requested CIK has no accession ledger partition")
        try:
            import polars as pl

            rows = pl.read_parquet(path).to_dicts()
        except Exception as exc:
            raise AccessionVersionLedgerError("cannot read accession ledger Parquet partition") from exc
        for row in rows:
            if str(row.get("cik") or "") != cik:
                raise AccessionVersionLedgerError("ledger row CIK disagrees with partition")
            try:
                _validate_accession_version_ledger(row, run)
            except Exception as exc:
                raise AccessionVersionLedgerError("ledger row violates its contract") from exc
        return self._sort(rows)

    def get_company(
        self, publication: VerifiedLayer2Publication, *, cik: str
    ) -> tuple[dict[str, Any], ...]:
        if not publication.is_reader_attested:
            raise AccessionVersionLedgerError("ledger must be loaded by Layer2PublicationReader")
        if cik not in publication.input_ciks:
            raise AccessionVersionLedgerError("requested CIK is outside the verified publication")
        if self.dataset not in publication.datasets:
            raise AccessionVersionLedgerError("publication has no accession version ledger")
        return self._sort(
            row for row in publication.records(self.dataset) if str(row.get("cik")) == cik
        )

    @staticmethod
    def _sort(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        # The accession is only a deterministic tie-breaker.  It is never an
        # amendment sequence or temporal substitute for the filed date.
        return tuple(
            sorted(
                (dict(row) for row in rows),
                key=lambda row: (str(row.get("filed_date") or ""), str(row.get("accession") or "")),
            )
        )


def _ledger_rows(cik: str, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filings_by_accession = {
        str(item["filing"].get("accession") or ""): item["filing"] for item in inputs
    }
    if "" in filings_by_accession or len(filings_by_accession) != len(inputs):
        raise AccessionVersionLedgerError("one CIK ledger requires unique non-empty accessions")
    output: list[dict[str, Any]] = []
    for item in inputs:
        filing = item["filing"]
        accession = str(filing["accession"])
        is_amendment = bool(filing.get("is_amendment")) or str(filing.get("form") or "").endswith("/A")
        evidence = item["amendment_evidence"]
        linkage = _linkage(filing, evidence, filings_by_accession, is_amendment)
        ordinal = _reported_ordinal(evidence["amendment_description"])
        row = {
            "cik": cik,
            "accession_version_ledger_id": _id(item["snapshot_id"], accession),
            "source_filing_id": filing.get("filing_id"),
            "source_snapshot_id": item["snapshot_id"],
            "accession": accession,
            "form": filing.get("form"),
            "filed_date": filing.get("filed_date"),
            "report_date": filing.get("report_date"),
            "is_amendment": is_amendment,
            "amendment_flag_state": evidence["amendment_flag_state"],
            "dei_amendment_flag_raw": evidence["amendment_flag_raw"],
            "dei_amendment_flag_fact_id": evidence["amendment_flag_fact_id"],
            "dei_amendment_description_raw": evidence["amendment_description"],
            "dei_amendment_description_fact_id": evidence["amendment_description_fact_id"],
            "amends_accession": linkage["target"],
            "amendment_linkage_state": linkage["state"],
            "amendment_linkage_method": linkage["method"],
            "amendment_linkage_review_status": linkage["review_status"],
            "amendment_linkage_evidence": linkage["evidence"],
            "reported_amendment_ordinal": ordinal,
            "reported_amendment_ordinal_state": "REPORTED" if ordinal is not None else "NOT_REPORTED",
            "amendment_ordinal_method": "DEI_DESCRIPTION_TEXT" if ordinal is not None else "NOT_INFERRED",
            "ledger_rule_version": ACCESSION_VERSION_LEDGER_RULE_VERSION,
        }
        output.append(row)
    return output


def _amendment_evidence(
    concepts: Iterable[Mapping[str, Any]], facts: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    local_by_concept = {
        str(row.get("raw_concept_id") or ""): str(row.get("local_name") or "")
        for row in concepts
    }
    flag: Mapping[str, Any] | None = None
    description: Mapping[str, Any] | None = None
    for fact in facts:
        local = local_by_concept.get(str(fact.get("raw_concept_id") or ""))
        if local == "AmendmentFlag" and flag is None:
            flag = fact
        elif local == "AmendmentDescription" and description is None:
            description = fact
    raw_flag = _raw_fact_text(flag)
    if raw_flag is None:
        state = "NOT_REPORTED"
    elif raw_flag.strip().lower() in {"true", "1"}:
        state = "REPORTED_TRUE"
    else:
        # Raw XML may contain a non-canonical lexical form.  It remains a
        # reported false state rather than being silently recast to true.
        state = "REPORTED_FALSE"
    return {
        "amendment_flag_state": state,
        "amendment_flag_raw": raw_flag,
        "amendment_flag_fact_id": flag.get("fact_id") if flag else None,
        "amendment_description": _raw_fact_text(description),
        "amendment_description_fact_id": description.get("fact_id") if description else None,
    }


def _raw_fact_text(fact: Mapping[str, Any] | None) -> str | None:
    if not fact or fact.get("is_nil"):
        return None
    value = fact.get("value_text")
    if value is None:
        value = fact.get("raw_value")
    return None if value is None else str(value)


def _linkage(
    filing: Mapping[str, Any], evidence: Mapping[str, Any], filings_by_accession: Mapping[str, Mapping[str, Any]], is_amendment: bool
) -> dict[str, Any]:
    if not is_amendment:
        return {"target": None, "state": "NOT_APPLICABLE", "method": "NOT_AN_AMENDMENT", "review_status": "NOT_REQUIRED", "evidence": {"reason": "not_an_amendment"}}
    direct = _optional_text(filing.get("amends_accession"))
    if direct:
        return {"target": direct, "state": "LINKED", "method": "RAW_FILING_AMENDS_ACCESSION", "review_status": "NOT_REQUIRED", "evidence": {"source_field": "filing.amends_accession"}}
    description = _optional_text(evidence.get("amendment_description"))
    described = sorted(set(_ACCESSION_RE.findall(description or "")))
    if len(described) == 1:
        return {"target": described[0], "state": "LINKED", "method": "DEI_DESCRIPTION_ACCESSION", "review_status": "NOT_REQUIRED", "evidence": {"source_fact_id": evidence.get("amendment_description_fact_id"), "matched_accession": described[0]}}
    candidates = _compatible_prior_filings(filing, filings_by_accession)
    if len(candidates) == 1:
        return {"target": candidates[0], "state": "CANDIDATE", "method": "FORM_REPORT_DATE_COMPATIBLE_CANDIDATE", "review_status": "REVIEW_REQUIRED", "evidence": {"candidate_accessions": candidates, "compatibility": "same_cik+base_form+report_date+earlier_filed_date"}}
    return {"target": None, "state": "UNKNOWN", "method": "UNKNOWN", "review_status": "UNKNOWN", "evidence": {"candidate_accessions": candidates, "reason": "no direct accession evidence"}}


def _compatible_prior_filings(filing: Mapping[str, Any], filings: Mapping[str, Mapping[str, Any]]) -> list[str]:
    base_form = str(filing.get("form") or "").removesuffix("/A")
    report_date = str(filing.get("report_date") or "")
    filed_date = str(filing.get("filed_date") or "")
    return sorted(
        str(accession)
        for accession, candidate in filings.items()
        if str(candidate.get("form") or "") == base_form
        and str(candidate.get("report_date") or "") == report_date
        and str(candidate.get("filed_date") or "") < filed_date
    )


def _reported_ordinal(description: str | None) -> str | None:
    if not description:
        return None
    match = _ORDINAL_RE.search(description)
    return match.group(1) if match else None


def _optional_text(value: Any) -> str | None:
    return None if value is None or str(value).strip() == "" else str(value)


def _id(*parts: object) -> str:
    encoded = "|".join("" if part is None else str(part) for part in parts)
    return "accession-ledger:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
