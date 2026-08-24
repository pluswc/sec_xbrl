"""Run the AMD, MSFT, and META P1 package and Layer 1 presence QA.

The runner deliberately writes only to a caller-selected cache root.  It never
materializes Layer 1 tables: extraction is used solely to establish that raw
facts, contexts, dimensions, and relationship networks are present in an
offline-loaded as-filed model.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from sec_xbrl.facts.layer1 import Layer1Extractor
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndexCache, FilingPackageResolver
from sec_xbrl.filing.package_cache import AccessionPackageCache, ArchiveFetcher, SECArchiveClient

PILOT_ID = "amd-msft-meta"
MANIFEST_SCHEMA_VERSION = 1
_REQUIRED_RECORD_FIELDS = frozenset(
    {
        "company",
        "ticker",
        "cik",
        "accession",
        "form",
        "filed_date",
        "report_date",
        "selection_role",
        "filing_url",
    }
)
_DOCUMENT_BLOCK_RE = re.compile(r"<DOCUMENT>(.*?)(?:</DOCUMENT>|\Z)", re.DOTALL | re.IGNORECASE)
_TAG_VALUE_RE = re.compile(r"<(?P<tag>TYPE|FILENAME)>\s*(?P<value>[^\r\n<]+)", re.IGNORECASE)
_NETWORK_TYPES = {
    "http://www.xbrl.org/2003/arcrole/parent-child": "PRE",
    "http://www.xbrl.org/2003/arcrole/summation-item": "CAL",
}


class PilotManifestError(ValueError):
    """Raised when a P0 pilot manifest is not a safe P1 input."""


@dataclass(frozen=True, slots=True)
class PilotFiling:
    company: str
    ticker: str
    selection_role: str
    filing_url: str
    filing: FilingRef


@dataclass(frozen=True, slots=True)
class PilotQaRow:
    company: str
    ticker: str
    cik: str
    accession: str
    form: str
    selection_role: str
    run_timestamp_utc: str
    package_result: str
    entrypoint: str | None
    arelle_outcome: str | None
    fact_count: int | None
    context_count: int | None
    dimension_fact_count: int | None
    pre_relationship_count: int | None
    cal_relationship_count: int | None
    def_relationship_count: int | None
    stage: str | None
    failure: str | None
    package_manifest_sha256: str | None


def load_pilot_manifest(path: Path) -> tuple[PilotFiling, ...]:
    """Load the committed P0 metadata manifest without treating it as raw SEC data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotManifestError(f"invalid pilot manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise PilotManifestError("unsupported pilot manifest schema version")
    if payload.get("pilot_id") != PILOT_ID:
        raise PilotManifestError("unexpected pilot id")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise PilotManifestError("pilot manifest has no records")
    return tuple(_pilot_filing(record) for record in records)


def _pilot_filing(record: object) -> PilotFiling:
    if not isinstance(record, dict) or set(record) != _REQUIRED_RECORD_FIELDS:
        raise PilotManifestError("pilot manifest record fields do not match the P0 contract")
    try:
        filing = FilingRef(
            cik=str(record["cik"]),
            accession=str(record["accession"]),
            form=str(record["form"]),
            filed_date=date.fromisoformat(str(record["filed_date"])),
            report_date=date.fromisoformat(str(record["report_date"])),
            source="pilot_p0_manifest",
        )
    except (TypeError, ValueError) as exc:
        raise PilotManifestError("pilot manifest record has invalid filing identity") from exc
    filing_url = str(record["filing_url"])
    expected_path = (
        f"/Archives/edgar/data/{int(filing.cik)}/{filing.accession.replace('-', '')}/"
    )
    parsed = urlparse(filing_url)
    if parsed.scheme != "https" or parsed.netloc != "www.sec.gov" or parsed.path != expected_path:
        raise PilotManifestError(f"pilot filing URL does not match filing identity: {filing.accession}")
    if filing.form not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
        raise PilotManifestError(f"unsupported pilot filing form: {filing.form}")
    return PilotFiling(
        company=str(record["company"]),
        ticker=str(record["ticker"]),
        selection_role=str(record["selection_role"]),
        filing_url=filing_url,
        filing=filing,
    )


class PilotP1Runner:
    """Resolve and inspect filings using an immutable package cache outside Git."""

    def __init__(
        self,
        *,
        cache_root: Path,
        fetcher: ArchiveFetcher,
        model_loader: ArelleFilingLoader | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cache_root = cache_root
        self.fetcher = fetcher
        self.model_loader = model_loader or ArelleFilingLoader()
        self.now = now
        self.resolver = FilingPackageResolver(
            AccessionPackageCache(cache_root / "packages"),
            FilingIndexCache(cache_root / "filing-indexes"),
        )

    def run(self, filings: Iterable[PilotFiling]) -> tuple[PilotQaRow, ...]:
        """Return one non-mutating Layer 1 QA row per manifest filing."""
        timestamp = self.now().astimezone(UTC).isoformat().replace("+00:00", "Z")
        return tuple(self._run_one(pilot_filing, timestamp) for pilot_filing in filings)

    def _run_one(self, pilot_filing: PilotFiling, timestamp: str) -> PilotQaRow:
        filing = pilot_filing.filing
        base = _row_base(pilot_filing, timestamp)
        try:
            package_manifest = self.resolver.package_cache.ensure(filing, self.fetcher)
        except Exception as exc:  # noqa: BLE001 - QA records every accession-level failure.
            return PilotQaRow(**base, package_result="FAIL", entrypoint=None, arelle_outcome=None,
                              fact_count=None, context_count=None, dimension_fact_count=None,
                              pre_relationship_count=None, cal_relationship_count=None,
                              def_relationship_count=None, stage="PACKAGE_RESOLUTION",
                              failure=_exact_failure(exc), package_manifest_sha256=None)
        package_hash = hashlib.sha256(package_manifest.to_json().encode("utf-8")).hexdigest()
        try:
            filing = _with_primary_document(filing, self.resolver.package_cache.package_dir(filing))
            resolved = self.resolver.resolve(filing, self.fetcher)
        except Exception as exc:  # noqa: BLE001 - QA records every accession-level failure.
            return PilotQaRow(**base, package_result="PASS", entrypoint=None, arelle_outcome=None,
                              fact_count=None, context_count=None, dimension_fact_count=None,
                              pre_relationship_count=None, cal_relationship_count=None,
                              def_relationship_count=None, stage="PACKAGE_RESOLUTION",
                              failure=_exact_failure(exc), package_manifest_sha256=package_hash)
        work_parent = self.cache_root / "arelle-work"
        work_parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=f"{filing.accession}-", dir=work_parent) as temporary:
                model = self.model_loader.load(resolved, Path(temporary))
                facts = Layer1Extractor().extract(
                    model, filing, source_url=resolved.index.source_url, package_hash=package_hash
                )
                counts = _relationship_presence_counts(model)
        except Exception as exc:  # noqa: BLE001 - QA records every accession-level failure.
            stage = "ARELLE_LOAD" if "model" not in locals() else "LAYER1_EXTRACT"
            return PilotQaRow(**base, package_result="PASS", entrypoint=resolved.entrypoint_name,
                              arelle_outcome="FAIL" if stage == "ARELLE_LOAD" else "PASS", fact_count=None, context_count=None,
                              dimension_fact_count=None, pre_relationship_count=None,
                              cal_relationship_count=None, def_relationship_count=None,
                              stage=stage, failure=_exact_failure(exc),
                              package_manifest_sha256=package_hash)
        return PilotQaRow(**base, package_result="PASS", entrypoint=resolved.entrypoint_name,
                          arelle_outcome="PASS", fact_count=len(facts.facts),
                          context_count=len(facts.contexts), dimension_fact_count=len(facts.dimension_facts),
                          pre_relationship_count=counts["PRE"], cal_relationship_count=counts["CAL"],
                          def_relationship_count=counts["DEF"], stage=None, failure=None,
                          package_manifest_sha256=package_hash)


def write_qa_report(rows: Iterable[PilotQaRow], path: Path) -> None:
    """Write a compact JSON result outside the repository's raw-data boundary."""
    payload = {"schema_version": 1, "pilot_id": PILOT_ID, "rows": [asdict(row) for row in rows]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _row_base(pilot_filing: PilotFiling, timestamp: str) -> dict[str, str]:
    filing = pilot_filing.filing
    return {
        "company": pilot_filing.company,
        "ticker": pilot_filing.ticker,
        "cik": filing.cik,
        "accession": filing.accession,
        "form": filing.form,
        "selection_role": pilot_filing.selection_role,
        "run_timestamp_utc": timestamp,
    }


def _exact_failure(exc: Exception) -> str:
    """Keep the failure text intact while recording its concrete exception class."""
    return f"{type(exc).__name__}: {exc}"


def _with_primary_document(filing: FilingRef, package_dir: Path) -> FilingRef:
    """Enrich P0 metadata from the validated SEC index-header artifact.

    SEC directory ``index.json`` does not consistently label the primary filing
    document.  The index-header is part of the immutable package contract and
    records the filing's exact ``TYPE``/``FILENAME`` pair, so this is an
    evidence-based enrichment rather than a filename heuristic.
    """
    header = package_dir / f"{filing.accession}-index-headers.html"
    try:
        content = html.unescape(header.read_text(encoding="utf-8", errors="strict"))
    except OSError as exc:
        raise PilotManifestError(f"missing cached index headers: {header}") from exc
    candidates: list[str] = []
    for block in _DOCUMENT_BLOCK_RE.findall(content):
        values = {match.group("tag").upper(): match.group("value").strip() for match in _TAG_VALUE_RE.finditer(block)}
        if values.get("TYPE") == filing.form and values.get("FILENAME"):
            candidates.append(values["FILENAME"])
    if len(candidates) != 1:
        raise PilotManifestError(
            f"index headers cannot determine a unique primary document for {filing.accession}"
        )
    return replace(filing, primary_document=candidates[0])


def _relationship_presence_counts(model: object) -> dict[str, int]:
    """Count the three as-filed networks without constructing a derived graph.

    Arelle exposes the same role through several base-set key variants.  A key
    with both link and arc QName is the fully scoped network; the other variants
    are indexes, so including them would multiply the QA count.
    """
    counts = {kind: 0 for kind in ("PRE", "CAL", "DEF")}
    base_sets = getattr(model, "baseSets", {}) or {}
    relationship_set = getattr(model, "relationshipSet", None)
    if not callable(relationship_set):
        raise TypeError("loaded model does not expose relationshipSet")
    for key in base_sets:
        if not isinstance(key, tuple) or len(key) < 4:
            continue
        arcrole, role_uri, link_qname, arc_qname = key[:4]
        if not isinstance(arcrole, str) or not isinstance(role_uri, str):
            continue
        if link_qname is None or arc_qname is None:
            continue
        network_type = _NETWORK_TYPES.get(arcrole)
        if network_type is None:
            network_type = "DEF" if arcrole.startswith("http://xbrl.org/int/dim/arcrole/") else None
        if network_type is None:
            continue
        relationships = relationship_set(arcrole, role_uri, link_qname, arc_qname)
        counts[network_type] += len(getattr(relationships, "modelRelationships", ()) or ())
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--user-agent", required=True, help="SEC-compliant identifying User-Agent")
    args = parser.parse_args(argv)
    if not args.user_agent.strip():
        parser.error("--user-agent must not be blank")
    rows = PilotP1Runner(
        cache_root=args.cache_root,
        fetcher=SECArchiveClient(user_agent=args.user_agent),
    ).run(load_pilot_manifest(args.manifest))
    write_qa_report(rows, args.report)
    return 0 if all(row.stage is None for row in rows) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
