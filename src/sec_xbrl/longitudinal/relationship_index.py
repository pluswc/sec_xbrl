"""Filing-versioned Layer 2 index over immutable Layer 1 XBRL relationships.

The index is deliberately additive: it makes relationship edges easy to find
across a company's filings without collapsing PRE, CAL, and DEF into a common
meaning or replacing the raw base-set identity with a canonical concept.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sec_xbrl.longitudinal.canonical import CompanyCanonicalizer
from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import (
    Layer2Publication,
    OperationalLayer2Publisher,
    VerifiedLayer2Publication,
    _read_publication_manifest,
    _run_from_manifest,
    _validate_filing_relationship_edge,
    _validate_operational_manifest_shape,
)

RELATIONSHIP_INDEX_RULE_VERSION = "l2-t2-filing-relationship-index-v1"
_DIRECTION = Literal["INCOMING", "OUTGOING", "BOTH"]


class FilingRelationshipIndexError(RuntimeError):
    """Raised when immutable relationship lineage cannot safely be indexed."""


@dataclass(frozen=True, slots=True)
class FilingRelationshipIndexResult:
    publication: Layer2Publication
    edge_count: int


class FilingRelationshipIndexPipeline:
    """Publish every Layer 1 PRE/CAL/DEF edge with filing and map lineage."""

    def publish(
        self, release: CorpusRelease, *, output_root: Path
    ) -> FilingRelationshipIndexResult:
        if not isinstance(release, CorpusRelease):
            raise FilingRelationshipIndexError("T2 requires an explicit CorpusRelease")
        filings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        concepts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dimensions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
        roles_by_filing: dict[str, dict[str, dict[str, Any]]] = {}
        snapshot_id_by_filing: dict[str, str] = {}

        for snapshot in release.snapshots:
            filing_rows = snapshot.records("filing")
            if len(filing_rows) != 1:
                raise FilingRelationshipIndexError(
                    "admitted snapshot must have exactly one filing row"
                )
            filing = filing_rows[0]
            cik = snapshot.input.cik
            filing_id = str(filing.get("filing_id") or "")
            if not filing_id or str(filing.get("cik") or "") != cik:
                raise FilingRelationshipIndexError(
                    "snapshot filing identity disagrees with CorpusRelease"
                )
            if filing_id in snapshot_id_by_filing:
                raise FilingRelationshipIndexError("duplicate filing_id in CorpusRelease")
            filings[cik].append(filing)
            concepts[cik].extend(snapshot.records("concept"))
            dimensions[cik].extend(snapshot.records("dimension_fact"))
            relationships[cik].extend(snapshot.records("relationship"))
            roles_by_filing[filing_id] = {
                str(row.get("role_id") or ""): row for row in snapshot.records("role")
            }
            snapshot_id_by_filing[filing_id] = snapshot.input.snapshot_id

        datasets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        edge_count = 0
        for cik in release.ciks:
            mappings = CompanyCanonicalizer().build(
                filings=filings[cik],
                concepts=concepts[cik],
                dimension_facts=dimensions[cik],
                relationships=relationships[cik],
            )
            # Mapping records are embedded as endpoint lineage on each edge.
            # T2 does not republish the full maps, which are independently
            # published by T1 and would otherwise be a duplicate large table.
            concept_by_id = {
                (str(row.get("filing_id") or ""), str(row.get("raw_concept_id") or "")): row
                for row in concepts[cik]
            }
            concept_map = _map_index(mappings.company_concept_map)
            for relationship in relationships[cik]:
                row = _edge_row(
                    cik=cik,
                    relationship=relationship,
                    filing_by_id={str(item["filing_id"]): item for item in filings[cik]},
                    roles_by_filing=roles_by_filing,
                    concepts_by_id=concept_by_id,
                    concept_map=concept_map,
                    snapshot_id_by_filing=snapshot_id_by_filing,
                )
                datasets["filing_relationship_edge"].append(row)
                edge_count += 1
        publication = OperationalLayer2Publisher(Path(output_root)).publish(
            release.layer2_run, {name: tuple(rows) for name, rows in datasets.items()}
        )
        return FilingRelationshipIndexResult(publication, edge_count)


class FilingRelationshipIndexReader:
    """Read exact edges without flattening filing, role, or network identity."""

    dataset = "filing_relationship_edge"

    def query_parquet(
        self,
        run_root: Path,
        *,
        cik: str,
        accession: str | None = None,
        raw_concept_id: str | None = None,
        company_canonical_concept_id: str | None = None,
        direction: _DIRECTION = "BOTH",
        network_type: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read one CIK Parquet partition, never the complete filing corpus.

        The small manifest and run declaration are validated before the
        partition is opened.  Each returned edge is validated against that
        declaration, so this fast path does not turn a partition lookup into
        an unverified raw file read.  A full publication reader remains
        available for consumers that need all Layer 2 datasets atomically.
        """
        if bool(raw_concept_id) and bool(company_canonical_concept_id):
            raise FilingRelationshipIndexError(
                "provide at most one raw or canonical concept identity"
            )
        if direction not in {"INCOMING", "OUTGOING", "BOTH"}:
            raise FilingRelationshipIndexError("direction must be INCOMING, OUTGOING, or BOTH")
        if network_type is not None and network_type not in {"PRE", "CAL", "DEF"}:
            raise FilingRelationshipIndexError("network_type must be PRE, CAL, or DEF")
        root = Path(run_root)
        manifest = _read_publication_manifest(root / "layer2_run_manifest.json")
        if manifest.get("storage_format") != "parquet-operational-v1":
            raise FilingRelationshipIndexError(
                "relationship fast query requires operational Parquet"
            )
        try:
            _validate_operational_manifest_shape(manifest)
            run = _run_from_manifest(manifest)
        except Exception as exc:
            raise FilingRelationshipIndexError(
                "relationship publication manifest is invalid"
            ) from exc
        if root.name != run.run_version or manifest.get("run_fingerprint") != run.fingerprint:
            raise FilingRelationshipIndexError("relationship publication declaration is invalid")
        if self.dataset not in manifest["output_counts"]:
            raise FilingRelationshipIndexError("publication has no filing relationship index")
        if cik not in {item.cik for item in run.inputs}:
            raise FilingRelationshipIndexError("requested CIK is outside the declared publication")
        if accession is not None:
            paths = (root / cik / self.dataset / f"{accession}.parquet",)
        else:
            partition = root / cik / self.dataset
            if not partition.is_dir() or partition.is_symlink():
                raise FilingRelationshipIndexError("requested CIK has no relationship index partition")
            paths = tuple(sorted(partition.glob("*.parquet")))
        if not paths or any(not path.is_file() or path.is_symlink() for path in paths):
            raise FilingRelationshipIndexError("requested relationship index partition is invalid")
        try:
            import polars as pl

            rows = [row for path in paths for row in pl.read_parquet(path).to_dicts()]
        except Exception as exc:
            raise FilingRelationshipIndexError(
                "cannot read relationship index Parquet partition"
            ) from exc
        for row in rows:
            if str(row.get("cik") or "") != cik:
                raise FilingRelationshipIndexError(
                    "relationship index row CIK disagrees with partition"
                )
            try:
                _validate_filing_relationship_edge(row, run)
            except Exception as exc:
                raise FilingRelationshipIndexError(
                    "relationship index row violates its contract"
                ) from exc
        selected = (
            row
            for row in rows
            if (accession is None or row.get("accession") == accession)
            and (network_type is None or row.get("network_type") == network_type)
            and _matches_concept(row, raw_concept_id, company_canonical_concept_id, direction)
        )
        return self._sort(selected)

    def get_filing(
        self,
        publication: VerifiedLayer2Publication,
        *,
        cik: str,
        accession: str,
        network_type: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self._check(publication, cik)
        if network_type is not None and network_type not in {"PRE", "CAL", "DEF"}:
            raise FilingRelationshipIndexError("network_type must be PRE, CAL, or DEF")
        return self._sort(
            row
            for row in publication.records(self.dataset)
            if str(row.get("cik")) == cik
            and row.get("accession") == accession
            and (network_type is None or row.get("network_type") == network_type)
        )

    def edges_for_concept(
        self,
        publication: VerifiedLayer2Publication,
        *,
        cik: str,
        raw_concept_id: str | None = None,
        company_canonical_concept_id: str | None = None,
        direction: _DIRECTION = "BOTH",
        accession: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self._check(publication, cik)
        if bool(raw_concept_id) == bool(company_canonical_concept_id):
            raise FilingRelationshipIndexError(
                "provide exactly one raw or canonical concept identity"
            )
        if direction not in {"INCOMING", "OUTGOING", "BOTH"}:
            raise FilingRelationshipIndexError("direction must be INCOMING, OUTGOING, or BOTH")
        from_key = "from_raw_concept_id" if raw_concept_id else "from_company_canonical_concept_id"
        to_key = "to_raw_concept_id" if raw_concept_id else "to_company_canonical_concept_id"
        target = raw_concept_id or company_canonical_concept_id

        def matches(row: Mapping[str, Any]) -> bool:
            incoming = row.get(to_key) == target
            outgoing = row.get(from_key) == target
            return (
                str(row.get("cik")) == cik
                and (accession is None or row.get("accession") == accession)
                and (
                    (direction == "INCOMING" and incoming)
                    or (direction == "OUTGOING" and outgoing)
                    or (direction == "BOTH" and (incoming or outgoing))
                )
            )

        return self._sort(row for row in publication.records(self.dataset) if matches(row))

    @staticmethod
    def _check(publication: VerifiedLayer2Publication, cik: str) -> None:
        if not publication.is_reader_attested:
            raise FilingRelationshipIndexError(
                "relationship index must be loaded by Layer2PublicationReader"
            )
        if cik not in publication.input_ciks:
            raise FilingRelationshipIndexError("requested CIK is outside the verified publication")
        if FilingRelationshipIndexReader.dataset not in publication.datasets:
            raise FilingRelationshipIndexError("publication has no filing relationship index")

    @staticmethod
    def _sort(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        return tuple(
            sorted(
                (dict(row) for row in rows),
                key=lambda row: (
                    str(row.get("filed_date") or ""),
                    str(row.get("accession") or ""),
                    str(row.get("network_type") or ""),
                    str(row.get("role_uri") or ""),
                    str(row.get("link_qname") or ""),
                    str(row.get("arc_qname") or ""),
                    str(row.get("relationship_id") or ""),
                ),
            )
        )


def _map_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("source_filing_id") or ""), str(row.get("source_raw_id") or "")): dict(row)
        for row in rows
    }


def _matches_concept(
    row: Mapping[str, Any],
    raw_concept_id: str | None,
    company_canonical_concept_id: str | None,
    direction: _DIRECTION,
) -> bool:
    if raw_concept_id is None and company_canonical_concept_id is None:
        return True
    key = "raw_concept_id" if raw_concept_id is not None else "company_canonical_concept_id"
    target = raw_concept_id or company_canonical_concept_id
    incoming, outgoing = row.get(f"to_{key}") == target, row.get(f"from_{key}") == target
    return (
        (direction == "INCOMING" and incoming)
        or (direction == "OUTGOING" and outgoing)
        or (direction == "BOTH" and (incoming or outgoing))
    )


def _edge_row(
    *,
    cik: str,
    relationship: Mapping[str, Any],
    filing_by_id: Mapping[str, Mapping[str, Any]],
    roles_by_filing: Mapping[str, Mapping[str, Mapping[str, Any]]],
    concepts_by_id: Mapping[tuple[str, str], Mapping[str, Any]],
    concept_map: Mapping[tuple[str, str], Mapping[str, Any]],
    snapshot_id_by_filing: Mapping[str, str],
) -> dict[str, Any]:
    filing_id = str(relationship.get("filing_id") or "")
    relationship_id = str(relationship.get("relationship_id") or "")
    from_id = str(relationship.get("from_raw_concept_id") or "")
    to_id = str(relationship.get("to_raw_concept_id") or "")
    filing = filing_by_id.get(filing_id)
    role = roles_by_filing.get(filing_id, {}).get(str(relationship.get("role_id") or ""))
    source = concepts_by_id.get((filing_id, from_id))
    target = concepts_by_id.get((filing_id, to_id))
    if not filing or not relationship_id or not role or not source or not target:
        raise FilingRelationshipIndexError(
            "relationship cannot resolve filing, role, and raw endpoints"
        )
    if relationship.get("network_type") not in {"PRE", "CAL", "DEF"}:
        raise FilingRelationshipIndexError("Layer 1 relationship has unrecognized network_type")
    source_map = concept_map.get((filing_id, from_id))
    target_map = concept_map.get((filing_id, to_id))
    return {
        "cik": cik,
        "filing_relationship_edge_id": _id(snapshot_id_by_filing[filing_id], relationship_id),
        "relationship_id": relationship_id,
        "source_filing_id": filing_id,
        "source_snapshot_id": snapshot_id_by_filing[filing_id],
        "accession": filing.get("accession"),
        "form": filing.get("form"),
        "filed_date": filing.get("filed_date"),
        "report_date": filing.get("report_date"),
        "source_is_amendment": bool(filing.get("is_amendment"))
        or str(filing.get("form") or "").endswith("/A"),
        "source_amends_accession": filing.get("amends_accession"),
        "network_type": relationship.get("network_type"),
        "role_id": relationship.get("role_id"),
        "role_uri": role.get("role_uri"),
        "role_definition": role.get("role_definition"),
        "role_category": role.get("role_category"),
        "arcrole": relationship.get("arcrole"),
        "link_qname": relationship.get("link_qname"),
        "arc_qname": relationship.get("arc_qname"),
        "from_raw_concept_id": from_id,
        "to_raw_concept_id": to_id,
        **_endpoint("from", source, source_map),
        **_endpoint("to", target, target_map),
        "order": relationship.get("order"),
        "weight": relationship.get("weight"),
        "preferred_label": relationship.get("preferred_label"),
        "target_role_uri": relationship.get("target_role_uri"),
        "usable": relationship.get("usable"),
        "closed": relationship.get("closed"),
        "context_element": relationship.get("context_element"),
        "relationship_index_rule_version": RELATIONSHIP_INDEX_RULE_VERSION,
    }


def _endpoint(
    prefix: str, concept: Mapping[str, Any], mapping: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {
        f"{prefix}_raw_concept_qname": concept.get("qname"),
        f"{prefix}_namespace_uri": concept.get("namespace_uri"),
        f"{prefix}_taxonomy_family": concept.get("taxonomy_family") or "unknown",
        f"{prefix}_taxonomy_version": concept.get("taxonomy_version"),
        f"{prefix}_local_name": concept.get("local_name"),
        f"{prefix}_is_standard": concept.get("is_standard"),
        f"{prefix}_is_custom": concept.get("is_custom"),
        f"{prefix}_company_canonical_concept_id": None
        if mapping is None
        else mapping.get("company_canonical_id"),
        f"{prefix}_mapping_id": None if mapping is None else mapping.get("mapping_id"),
        f"{prefix}_mapping_version": None if mapping is None else mapping.get("mapping_version"),
        f"{prefix}_mapping_relation": None if mapping is None else mapping.get("relation"),
        f"{prefix}_mapping_method": None if mapping is None else mapping.get("method"),
        # Mapping evidence can legitimately have a different schema per
        # endpoint.  Preserve it as canonical JSON rather than forcing all
        # company-specific evidence into one Parquet struct schema.
        f"{prefix}_mapping_evidence": None if mapping is None else json.dumps(
            mapping.get("evidence"), sort_keys=True, separators=(",", ":")
        ),
        f"{prefix}_mapping_review_required": True
        if mapping is None
        else bool(mapping.get("review_required")),
    }


def _id(snapshot_id: str, relationship_id: str) -> str:
    digest = hashlib.sha256(
        f"{snapshot_id}|{relationship_id}|{RELATIONSHIP_INDEX_RULE_VERSION}".encode()
    ).hexdigest()[:24]
    return f"filing-relationship-edge:{digest}"
