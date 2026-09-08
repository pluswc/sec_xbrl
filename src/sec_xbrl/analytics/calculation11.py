"""Additive Arelle evidence for Calculation 1.1 absent from old Raw snapshots.

This does not implement interval/rounding validation of the specification. The
prepared arithmetic checker reports exact Decimal differences without claiming
full XBRL Calculation 1.1 conformance.
"""
from __future__ import annotations

import hashlib
import zipfile
from datetime import date
from importlib.metadata import version
from pathlib import Path

from sec_xbrl.analytics.statement_structure import stable_id
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndex, ResolvedFiling
from sec_xbrl.relationships.layer1 import _raw_concept_id

ARCROLE = "https://xbrl.org/2023/arcrole/summation-item"


def supplement_calculation11(*, filing: dict, package: Path, concepts: dict, roles: dict,
                             taxonomy_cache: Path | None, destination: Path | None) -> list[dict]:
    """Only use effective, fully-qualified Arelle relationship sets."""
    if hashlib.sha256(package.read_bytes()).hexdigest() != filing["package_hash"]:
        raise ValueError("Calculation 1.1 package differs from attested Raw")
    with zipfile.ZipFile(package) as archive:
        members = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()
                   if n.endswith((".xml", ".xsd")) and ARCROLE.encode() in archive.read(n)}
    if not members:
        return []
    if taxonomy_cache is None or destination is None:
        raise ValueError("Calculation 1.1 source requires explicit offline taxonomy cache and supplemental workspace")
    ref = FilingRef(cik=filing["cik"], accession=filing["accession"], form=filing["form"],
                    filed_date=date.fromisoformat(filing["filed_date"]), primary_document=filing["primary_document"])
    resolved = ResolvedFiling(ref, FilingIndex(filing["cik"], filing["accession"], filing["source_url"], ()), package, filing["primary_document"])
    model = ArelleFilingLoader(taxonomy_cache=taxonomy_cache).load(resolved, destination)
    try:
        role_ids = {r["role_uri"]: r for r in roles.values()}
        result = []
        seen = set()
        for key in model.baseSets:
            if len(key) != 4 or key[0] != ARCROLE or not all(key[1:]):
                continue
            arcrole, role_uri, link, arc = key
            identity = (arcrole, role_uri, str(link), str(arc))
            if identity in seen:
                continue
            seen.add(identity)
            if role_uri not in role_ids:
                raise ValueError("supplemental CAL role not bound to attested Raw")
            for rel in model.relationshipSet(*key).modelRelationships:
                parent = _raw_concept_id(filing["filing_id"], rel.fromModelObject)
                child = _raw_concept_id(filing["filing_id"], rel.toModelObject)
                if parent not in concepts or child not in concepts:
                    raise ValueError("supplemental CAL endpoint not bound to attested Raw")
                row = {"filing_id": filing["filing_id"], "network_type": "CAL", "role_id": role_ids[role_uri]["role_id"],
                       "role_uri": role_uri, "role_definition": role_ids[role_uri]["role_definition"], "arcrole": arcrole,
                       "link_qname": str(link), "arc_qname": str(arc), "from_raw_concept_id": parent, "to_raw_concept_id": child,
                       "order": str(rel.order), "weight": str(rel.weight), "target_role_uri": None, "usable": None,
                       "preferred_label": None, "closed": None, "context_element": None,
                       "evidence_origin": "ADDITIVE_ARELLE_CALCULATION_1_1", "source_package_sha256": filing["package_hash"],
                       "parser_version": "arelle-release:" + version("arelle-release"),
                       "policy_version": "h1-supplemental-cal11-v1",
                       "source_document": Path(rel.arcElement.modelDocument.uri).name,
                       "source_document_sha256": members.get(Path(rel.arcElement.modelDocument.uri).name),
                       "source_members_sha256": members, "source_arc_line": rel.arcElement.sourceline,
                       "validation_scope": "EXACT_ARITHMETIC_ONLY_NOT_CALCULATION11_INTERVAL_VALIDATION"}
                if row["source_document_sha256"] is None:
                    raise ValueError("CAL1.1 source arc is not in the attested package members")
                row["relationship_id"] = "supplement-cal11:" + stable_id(row)
                result.append(row)
        if not result:
            raise ValueError("Calculation 1.1 source present but no effective Arelle relationships")
        return result
    finally:
        model.close()
