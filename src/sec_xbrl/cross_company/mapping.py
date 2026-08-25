"""Additive Layer 3 mappings; analytical similarity is never equivalence.

Layer 3 consumes company-canonical IDs produced by Layer 2.  It deliberately
does not infer a cross-company mapping from labels, values, or similar names:
the caller must supply the reviewed analytical relation and its evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CROSS_COMPANY_MAPPING_VERSION = "m8-cross-company-v1"


class CrossCompanyRelation(StrEnum):
    """Controlled relation from a company ID to an analytical category."""

    EQUIVALENT = "EQUIVALENT"
    SUBCATEGORY_OF = "SUBCATEGORY_OF"
    SUPERSET_OF = "SUPERSET_OF"
    ANALYTICALLY_SIMILAR = "ANALYTICALLY_SIMILAR"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class CrossCompanyMappingTables:
    """Versioned, separately materializable Layer 3 tables."""

    cross_company_concept_map: tuple[dict[str, Any], ...]
    cross_company_axis_map: tuple[dict[str, Any], ...]
    cross_company_member_map: tuple[dict[str, Any], ...]


class CrossCompanyMapper:
    """Validate explicit mappings on top of immutable company canonical IDs."""

    def build(
        self,
        *,
        concept_mappings: Iterable[Mapping[str, Any]] = (),
        axis_mappings: Iterable[Mapping[str, Any]] = (),
        member_mappings: Iterable[Mapping[str, Any]] = (),
        standard_concept_observations: Iterable[Mapping[str, Any]] = (),
    ) -> CrossCompanyMappingTables:
        """Build additive explicit maps plus safe standard-taxonomy equivalences.

        Explicit inputs need ``company_canonical_id``, ``relation``,
        ``confidence``, ``evidence``, ``method``, and a mapping version. A
        target analytical ID is mandatory for comparable relations, but
        deliberately absent for ``NOT_COMPARABLE`` and ``UNRESOLVED``.

        ``standard_concept_observations`` is deliberately narrow: it can only
        create an ``EQUIVALENT`` relation when two or more companies report the
        exact same standard QName with compatible non-empty type and period
        semantics.  It never attempts to infer a relation from a label.
        """
        concept_rows = tuple(_mapping_row("concept", row) for row in concept_mappings)
        generated_standard_rows = self.standard_concept_mappings(standard_concept_observations)
        combined_concept_rows = concept_rows + generated_standard_rows
        _assert_unique_mapping_keys(combined_concept_rows)
        axis_rows = tuple(_mapping_row("axis", row) for row in axis_mappings)
        member_rows = tuple(_mapping_row("member", row) for row in member_mappings)
        _assert_unique_mapping_keys(axis_rows)
        _assert_unique_mapping_keys(member_rows)
        return CrossCompanyMappingTables(
            cross_company_concept_map=combined_concept_rows,
            cross_company_axis_map=axis_rows,
            cross_company_member_map=member_rows,
        )

    def standard_concept_mappings(
        self, observations: Iterable[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], ...]:
        """Map only exact, cross-company standard concepts to equivalence.

        A caller supplies Layer 2 concept observations enriched with their
        Layer 1 concept metadata.  Rows with missing or incompatible semantic
        fields simply remain unmapped; this function is intentionally not a
        name/label similarity engine.
        """
        groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for source in observations:
            row = dict(source)
            qname = str(row.get("qname") or "")
            taxonomy_family = str(row.get("taxonomy_family") or "")
            data_type = str(row.get("data_type") or "")
            period_type = str(row.get("period_type") or "")
            company_id = _company_id(row, "concept")
            cik = str(row.get("cik") or "")
            if not (
                row.get("is_standard") is True
                and qname
                and taxonomy_family in {"us-gaap", "dei", "srt"}
                and data_type
                and period_type
                and company_id
                and cik
            ):
                continue
            groups.setdefault((qname, taxonomy_family, data_type, period_type), []).append(row)

        mappings: list[dict[str, Any]] = []
        for (qname, taxonomy_family, data_type, period_type), rows in sorted(groups.items()):
            ciks = {str(row["cik"]) for row in rows}
            if len(ciks) < 2:
                continue
            company_ids = sorted({_company_id(row, "concept") for row in rows})
            evidence = {
                "standard_qname": qname,
                "taxonomy_family": taxonomy_family,
                "data_type": data_type,
                "period_type": period_type,
                "compatible_company_canonical_ids": company_ids,
                "source_filings": sorted(
                    {str(row.get("filing_id") or row.get("source_filing_id") or "") for row in rows}
                    - {""}
                ),
            }
            for row in sorted(
                rows,
                key=lambda item: (_company_id(item, "concept"), _source_raw_id(item, "concept")),
            ):
                mappings.append(
                    _mapping_row(
                        "concept",
                        {
                            "company_canonical_id": _company_id(row, "concept"),
                            "analytical_id": f"analytical:standard:{qname}",
                            "relation": CrossCompanyRelation.EQUIVALENT,
                            "confidence": 1.0,
                            "evidence": evidence,
                            "method": "EXACT_STANDARD_TAXONOMY_IDENTITY",
                            "mapping_version": CROSS_COMPANY_MAPPING_VERSION,
                            "review_required": False,
                        },
                    )
                )
        return tuple(mappings)


class ComparisonPanelBuilder:
    """Attach Layer 3 semantics while retaining as-filed and Layer 2 identity."""

    def build(
        self,
        *,
        observations: Iterable[Mapping[str, Any]],
        mappings: CrossCompanyMappingTables | Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        """Return one visible comparison row per observation.

        Unmapped observations are represented as explicit ``UNRESOLVED`` rows;
        neither unresolved nor low-confidence mappings are filtered or promoted.
        """
        indexed = {
            (str(row["entity_type"]), str(row["company_canonical_id"])): dict(row)
            for row in _mapping_rows(mappings)
        }
        result: list[dict[str, Any]] = []
        for observation in observations:
            source = dict(observation)
            entity_type = str(source.get("entity_type") or "concept")
            if entity_type not in {"concept", "axis", "member"}:
                raise ValueError("observation entity_type must be concept, axis, or member")
            raw_id = _source_raw_id(source, entity_type)
            company_id = _company_id(source, entity_type)
            filing_id = str(source.get("filing_id") or source.get("source_filing_id") or "")
            source_period = _source_period(source)
            if not raw_id or not company_id or not filing_id or source_period is None:
                raise ValueError(
                    "observations require raw ID, company canonical ID, filing_id, and source period"
                )
            mapping = indexed.get((entity_type, company_id))
            if mapping is None:
                mapping = _unresolved_mapping(entity_type, company_id)
            result.append(
                {
                    **source,
                    "entity_type": entity_type,
                    "source_raw_id": raw_id,
                    "company_canonical_id": company_id,
                    "source_filing_id": filing_id,
                    "source_period": source_period,
                    "analytical_id": mapping["analytical_id"],
                    "mapping_relation": mapping["relation"],
                    "mapping_confidence": mapping["confidence"],
                    "mapping_evidence": dict(mapping["evidence"]),
                    "mapping_method": mapping["method"],
                    "mapping_version": mapping["mapping_version"],
                    "mapping_review_required": bool(mapping["review_required"]),
                }
            )
        return tuple(result)


def _mapping_row(entity_type: str, source: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(source)
    company_id = str(row.get("company_canonical_id") or "")
    if not company_id:
        raise ValueError("cross-company mapping requires company_canonical_id")
    try:
        relation = CrossCompanyRelation(str(row.get("relation") or ""))
    except ValueError as exc:
        raise ValueError("cross-company mapping has an unsupported relation") from exc
    confidence = row.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise TypeError("cross-company mapping confidence must be numeric")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("cross-company mapping confidence must be between 0 and 1")
    evidence = row.get("evidence")
    if not isinstance(evidence, Mapping):
        raise TypeError("cross-company mapping requires an evidence payload")
    method = str(row.get("method") or "")
    if not method:
        raise ValueError("cross-company mapping requires a method")
    version = str(row.get("mapping_version") or CROSS_COMPANY_MAPPING_VERSION)
    analytical_id = row.get("analytical_id")
    if relation in {CrossCompanyRelation.NOT_COMPARABLE, CrossCompanyRelation.UNRESOLVED}:
        if analytical_id is not None:
            raise ValueError("NOT_COMPARABLE and UNRESOLVED mappings cannot have analytical_id")
    elif not str(analytical_id or ""):
        raise ValueError("comparable cross-company mapping requires analytical_id")
    return {
        "mapping_id": str(
            row.get("mapping_id")
            or "cross-company-map:"
            + _digest(entity_type, company_id, str(analytical_id or ""), relation.value, version)
        ),
        "entity_type": entity_type,
        "company_canonical_id": company_id,
        "analytical_id": str(analytical_id) if analytical_id is not None else None,
        "relation": relation.value,
        "confidence": confidence,
        "evidence": dict(evidence),
        "method": method,
        "mapping_version": version,
        "review_required": bool(row.get("review_required", False))
        or relation == CrossCompanyRelation.UNRESOLVED
        or confidence < 1.0,
    }


def _mapping_rows(
    mappings: CrossCompanyMappingTables | Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(mappings, CrossCompanyMappingTables):
        return (
            mappings.cross_company_concept_map
            + mappings.cross_company_axis_map
            + mappings.cross_company_member_map
        )
    return tuple(mappings)


def _assert_unique_mapping_keys(rows: Iterable[Mapping[str, Any]]) -> None:
    keys: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["entity_type"]), str(row["company_canonical_id"]))
        if key in keys:
            raise ValueError(
                "cross-company mappings cannot duplicate an entity/company canonical ID"
            )
        keys.add(key)


def _source_raw_id(row: Mapping[str, Any], entity_type: str) -> str:
    return str(
        row.get("source_raw_id")
        or row.get(f"raw_{entity_type}_id")
        or (row.get("raw_concept_id") if entity_type == "concept" else "")
        or ""
    )


def _company_id(row: Mapping[str, Any], entity_type: str) -> str:
    return str(
        row.get("company_canonical_id")
        or row.get(f"company_canonical_{entity_type}_id")
        or (row.get("company_canonical_concept_id") if entity_type == "concept" else "")
        or ""
    )


def _source_period(row: Mapping[str, Any]) -> Any:
    for key in ("source_period", "report_period", "period_end", "period_class"):
        if row.get(key) is not None:
            return row[key]
    return None


def _unresolved_mapping(entity_type: str, company_id: str) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "company_canonical_id": company_id,
        "analytical_id": None,
        "relation": CrossCompanyRelation.UNRESOLVED.value,
        "confidence": 0.0,
        "evidence": {"reason": "no_cross_company_mapping"},
        "method": "NO_CROSS_COMPANY_MAPPING",
        "mapping_version": CROSS_COMPANY_MAPPING_VERSION,
        "review_required": True,
    }


def _digest(*parts: str) -> str:
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()[:24]
