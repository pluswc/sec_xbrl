"""Immutable, provenance-first extraction of Arelle facts into Layer 1 tables.

This module deliberately does not infer canonical identities, relationships, or
period/comparative classes.  It records the filing as it was filed; later
layers may add interpretations without replacing these records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.contracts import FilingRef


class Layer1ExtractionError(RuntimeError):
    """Raised when a loaded model cannot supply the required raw provenance."""


@dataclass(frozen=True, slots=True)
class FactCorpus:
    """The complete top-level Fact corpus exposed by an Arelle model.

    Inline XBRL models can expose a small ``factsInInstance`` subset while
    ``model.facts`` contains every inline fact.  Layer 1 must use the latter
    when available; otherwise a partial subset could be mistaken for a filing
    snapshot.
    """

    facts: tuple[Any, ...]
    source: str
    source_count: int


@dataclass(frozen=True, slots=True)
class Layer1Tables:
    """Rows ready for immutable Layer 1 Parquet materialization."""

    filing: tuple[dict[str, Any], ...]
    concepts: tuple[dict[str, Any], ...]
    contexts: tuple[dict[str, Any], ...]
    units: tuple[dict[str, Any], ...]
    facts: tuple[dict[str, Any], ...]
    dimension_facts: tuple[dict[str, Any], ...]

    def write_parquet(self, destination: Path) -> None:
        """Write one Parquet file per raw table without rewriting the source model."""
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - project dependency.
            raise Layer1ExtractionError("polars is required to materialize Layer 1 Parquet") from exc
        tables = (
            ("filing", self.filing),
            ("concept", self.concepts),
            ("context", self.contexts),
            ("unit", self.units),
            ("fact", self.facts),
            ("dimension_fact", self.dimension_facts),
        )
        paths = tuple(destination / f"{name}.parquet" for name, _ in tables)
        if any(path.exists() for path in paths):
            raise Layer1ExtractionError(f"Layer 1 snapshot already exists: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for name, rows in tables:
            pl.DataFrame(list(rows), schema=_polars_schema(pl, name), strict=False).write_parquet(
                destination / f"{name}.parquet"
            )


_PARQUET_SCHEMAS: dict[str, dict[str, Any]] = {
    "filing": {
        "filing_id": "string", "cik": "string", "accession": "string", "accession_nodash": "string",
        "form": "string", "filed_date": "string", "report_date": "string", "primary_document": "string",
        "document_fiscal_year_focus": "string", "document_fiscal_period_focus": "string",
        "fiscal_year_end": "string", "is_amendment": "bool", "amends_accession": "string",
        "source_url": "string", "package_hash": "string", "parser_version": "string",
    },
    "concept": {
        "raw_concept_id": "string", "filing_id": "string", "qname": "string", "namespace_uri": "string",
        "namespace_prefix": "string", "local_name": "string", "taxonomy_family": "string",
        "taxonomy_version": "string", "is_standard": "bool", "is_custom": "bool", "data_type": "string",
        "period_type": "string", "balance": "string", "abstract": "bool", "nillable": "bool",
        "label": "string", "documentation": "string",
    },
    "context": {
        "context_id": "string", "filing_id": "string", "entity_identifier": "string", "period_kind": "string",
        "start_date": "string", "end_date": "string", "instant_date": "string", "duration_days": "int64",
        "dimension_count": "int64", "context_xml": "string", "context_hash": "string",
    },
    "unit": {
        "unit_id": "string", "filing_id": "string", "numerator_measures": "string",
        "denominator_measures": "string", "raw_representation": "string",
    },
    "fact": {
        "fact_id": "string", "filing_id": "string", "raw_concept_id": "string", "context_id": "string",
        "unit_id": "string", "value_numeric": "string", "value_text": "string", "decimals": "string",
        "precision": "string", "is_nil": "bool", "source_document": "string", "source_locator": "string",
        "reported_or_derived": "string", "period_class": "string", "comparative_type": "string", "raw_value": "string",
    },
    "dimension_fact": {
        "fact_id": "string", "axis_raw_concept_id": "string", "member_raw_concept_id": "string",
        "typed_member": "string", "dimension_type": "string", "is_default_member": "bool",
    },
}


def _polars_schema(pl: Any, table: str) -> dict[str, Any]:
    """Translate the contract's explicit primitive types to Polars dtypes."""
    dtypes = {"string": pl.String, "bool": pl.Boolean, "int64": pl.Int64}
    return {column: dtypes[dtype] for column, dtype in _PARQUET_SCHEMAS[table].items()}


class Layer1Extractor:
    """Extract reported Arelle facts while retaining their as-filed identity."""

    parser_version = "m2-layer1-v1"

    def extract(
        self,
        model: Any,
        filing: FilingRef,
        *,
        source_url: str | None = None,
        package_hash: str | None = None,
    ) -> Layer1Tables:
        """Return raw records for one already-loaded filing.

        ``model`` is intentionally duck-typed to keep Arelle isolated at this
        boundary and to permit small, network-free fixtures in unit tests.
        """
        filing_id = _stable_id("filing", canonicalize_cik(filing.cik), filing.accession)
        corpus = select_fact_corpus(model)
        facts = corpus.facts
        concept_rows: dict[str, dict[str, Any]] = {}
        context_rows: dict[str, dict[str, Any]] = {}
        unit_rows: dict[str, dict[str, Any]] = {}
        fact_rows: list[dict[str, Any]] = []
        dimension_rows: list[dict[str, Any]] = []

        for ordinal, fact in enumerate(facts):
            if getattr(fact, "isTuple", False):
                continue
            concept = getattr(fact, "concept", None)
            qname = getattr(fact, "qname", None) or getattr(concept, "qname", None)
            if qname is None:
                raise Layer1ExtractionError("fact has no QName")
            concept_row = _concept_row(filing_id, qname, concept)
            concept_rows.setdefault(concept_row["raw_concept_id"], concept_row)

            context = getattr(fact, "context", None)
            context_id: str | None = None
            if context is not None:
                context_row, dimensions = _context_row(filing_id, context)
                context_id = context_row["context_id"]
                context_rows.setdefault(context_id, context_row)
                for dimension in dimensions:
                    axis_row = _concept_row(filing_id, dimension["axis_qname"], None)
                    concept_rows.setdefault(axis_row["raw_concept_id"], axis_row)
                    member_id: str | None = None
                    if dimension["member_qname"] is not None:
                        member_row = _concept_row(filing_id, dimension["member_qname"], None)
                        concept_rows.setdefault(member_row["raw_concept_id"], member_row)
                        member_id = member_row["raw_concept_id"]
                    # A dimension is a context property but is emitted per fact as
                    # required by the dimension_fact contract.
                    dimension_rows.append(
                        {
                            "fact_id": _fact_id(filing_id, fact, ordinal),
                            "axis_raw_concept_id": axis_row["raw_concept_id"],
                            "member_raw_concept_id": member_id,
                            "typed_member": dimension["typed_member"],
                            "dimension_type": dimension["dimension_type"],
                            "is_default_member": False,
                        }
                    )

            unit = getattr(fact, "unit", None)
            unit_id: str | None = None
            if unit is not None:
                unit_row = _unit_row(filing_id, unit)
                unit_id = unit_row["unit_id"]
                unit_rows.setdefault(unit_id, unit_row)

            lexical = getattr(fact, "value", None)
            is_nil = bool(getattr(fact, "isNil", False))
            numeric = _numeric_value(lexical) if bool(getattr(fact, "isNumeric", False)) and not is_nil else None
            fact_rows.append(
                {
                    "fact_id": _fact_id(filing_id, fact, ordinal),
                    "filing_id": filing_id,
                    "raw_concept_id": concept_row["raw_concept_id"],
                    "context_id": context_id,
                    "unit_id": unit_id,
                    "value_numeric": numeric,
                    "value_text": None if is_nil or getattr(fact, "isNumeric", False) else _text(lexical),
                    "decimals": _text(getattr(fact, "decimals", None)),
                    "precision": _text(getattr(fact, "precision", None)),
                    "is_nil": is_nil,
                    "source_document": _source_document(fact),
                    "source_locator": _source_locator(fact),
                    "reported_or_derived": "REPORTED",
                    # M6 owns semantic period/comparative classification.  Keeping
                    # them null prevents this raw layer from making a false claim.
                    "period_class": None,
                    "comparative_type": None,
                    "raw_value": None if is_nil else _text(lexical),
                }
            )

        filing_row = {
            "filing_id": filing_id,
            "cik": canonicalize_cik(filing.cik),
            "accession": filing.accession,
            "accession_nodash": filing.accession.replace("-", ""),
            "form": filing.form,
            "filed_date": filing.filed_date.isoformat(),
            "report_date": filing.report_date.isoformat() if filing.report_date else None,
            "primary_document": filing.primary_document,
            "document_fiscal_year_focus": None,
            "document_fiscal_period_focus": None,
            "fiscal_year_end": None,
            "is_amendment": filing.form.endswith("/A"),
            "amends_accession": None,
            "source_url": source_url,
            "package_hash": package_hash,
            "parser_version": self.parser_version,
        }
        return Layer1Tables(
            filing=(filing_row,),
            concepts=tuple(concept_rows.values()),
            contexts=tuple(context_rows.values()),
            units=tuple(unit_rows.values()),
            facts=tuple(fact_rows),
            dimension_facts=tuple(dimension_rows),
        )


def select_fact_corpus(model: Any) -> FactCorpus:
    """Return the complete top-level corpus, refusing known partial subsets.

    Arelle's documented ``model.facts`` is the authoritative model-wide
    collection for Inline XBRL.  ``factsInInstance`` remains a compatibility
    fallback only for fixture/legacy models that do not expose ``facts``.  If
    both are present, the instance subset must be contained in the full
    collection; a disagreement is a load/validation failure, not a reason to
    silently choose the smaller collection.
    """
    all_facts_raw = getattr(model, "facts", None)
    instance_raw = getattr(model, "factsInInstance", None)
    all_facts = tuple(all_facts_raw or ())
    instance_facts = tuple(instance_raw or ())

    if all_facts:
        if instance_facts:
            all_ids = {id(fact) for fact in all_facts}
            missing = sum(id(fact) not in all_ids for fact in instance_facts)
            if missing:
                raise Layer1ExtractionError(
                    "factsInInstance is not a subset of model.facts; refusing ambiguous Fact corpus"
                )
        top_level = tuple(fact for fact in all_facts if not bool(getattr(fact, "isTuple", False)))
        if not top_level:
            raise Layer1ExtractionError("model.facts contains no top-level facts")
        return FactCorpus(facts=top_level, source="model.facts", source_count=len(top_level))

    if instance_facts:
        top_level = tuple(fact for fact in instance_facts if not bool(getattr(fact, "isTuple", False)))
        if not top_level:
            raise Layer1ExtractionError("factsInInstance contains no top-level facts")
        return FactCorpus(
            facts=top_level, source="factsInInstance-fallback", source_count=len(top_level)
        )
    raise Layer1ExtractionError("loaded model exposes no facts")


def _concept_row(filing_id: str, qname: Any, concept: Any) -> dict[str, Any]:
    namespace_uri, prefix, local_name = _qname_parts(qname)
    raw_concept_id = _stable_id("concept", filing_id, namespace_uri, local_name)
    family, version, is_standard = _taxonomy(namespace_uri)
    return {
        "raw_concept_id": raw_concept_id,
        "filing_id": filing_id,
        "qname": _qname_text(qname),
        "namespace_uri": namespace_uri,
        "namespace_prefix": prefix,
        "local_name": local_name,
        "taxonomy_family": family,
        "taxonomy_version": version,
        "is_standard": is_standard,
        "is_custom": not is_standard,
        "data_type": _qname_text(getattr(concept, "typeQname", None)),
        "period_type": getattr(concept, "periodType", None),
        "balance": getattr(concept, "balance", None),
        "abstract": bool(getattr(concept, "isAbstract", False)),
        "nillable": getattr(concept, "isNillable", None),
        "label": _label(concept),
        "documentation": _documentation(concept),
    }


def _context_row(filing_id: str, context: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context_key = getattr(context, "id", None) or _text(getattr(context, "xml", None)) or repr(context)
    context_id = _stable_id("context", filing_id, context_key)
    kind = "FOREVER" if bool(getattr(context, "isForeverPeriod", False)) else "INSTANT"
    if bool(getattr(context, "isStartEndPeriod", False)):
        kind = "DURATION"
    start = _date_text(getattr(context, "startDatetime", None)) if kind == "DURATION" else None
    end = _date_text(getattr(context, "endDatetime", None)) if kind == "DURATION" else None
    instant = _date_text(getattr(context, "instantDatetime", None)) if kind == "INSTANT" else None
    duration_days = None
    if start and end:
        duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    dimensions = _dimensions(context)
    entity = getattr(context, "entityIdentifier", None)
    entity_identifier = ":".join(map(str, entity)) if isinstance(entity, tuple) else _text(entity)
    return (
        {
            "context_id": context_id,
            "filing_id": filing_id,
            "entity_identifier": entity_identifier,
            "period_kind": kind,
            "start_date": start,
            "end_date": end,
            "instant_date": instant,
            "duration_days": duration_days,
            "dimension_count": len(dimensions),
            "context_xml": _text(getattr(context, "xml", None)),
            "context_hash": _stable_id("context-xml", _text(getattr(context, "xml", None)) or context_key),
        },
        dimensions,
    )


def _dimensions(context: Any) -> list[dict[str, Any]]:
    values = getattr(context, "qnameDims", {}) or {}
    result: list[dict[str, Any]] = []
    for axis_qname, value in values.items():
        axis = getattr(value, "dimensionQname", None) or axis_qname
        explicit = bool(getattr(value, "isExplicit", getattr(value, "memberQname", None) is not None))
        member = getattr(value, "memberQname", None) if explicit else None
        typed = None if explicit else _text(getattr(value, "typedMember", None))
        result.append(
            {
                "axis_qname": axis,
                "member_qname": member,
                "typed_member": typed,
                "dimension_type": "EXPLICIT" if explicit else "TYPED",
            }
        )
    return result


def _unit_row(filing_id: str, unit: Any) -> dict[str, Any]:
    measures = getattr(unit, "measures", ((), ()))
    numerator, denominator = measures if len(measures) == 2 else (measures, ())
    raw = _text(getattr(unit, "xml", None)) or _unit_text(numerator, denominator)
    return {
        "unit_id": _stable_id("unit", filing_id, raw),
        "filing_id": filing_id,
        "numerator_measures": json.dumps(sorted(_qname_text(x) for x in numerator)),
        "denominator_measures": json.dumps(sorted(_qname_text(x) for x in denominator)),
        "raw_representation": raw,
    }


def _qname_parts(qname: Any) -> tuple[str, str | None, str]:
    namespace = getattr(qname, "namespaceURI", None) or getattr(qname, "namespace_uri", None)
    local = getattr(qname, "localName", None) or getattr(qname, "localname", None)
    prefix = getattr(qname, "prefix", None)
    if not namespace or not local:
        raise Layer1ExtractionError(f"QName lacks namespace/local-name provenance: {qname!r}")
    return str(namespace), str(prefix) if prefix else None, str(local)


def _qname_text(qname: Any) -> str | None:
    if qname is None:
        return None
    namespace, prefix, local = _qname_parts(qname)
    return f"{prefix}:{local}" if prefix else f"{{{namespace}}}{local}"


def _taxonomy(namespace: str) -> tuple[str, str | None, bool]:
    for family in ("us-gaap", "dei", "srt", "us-roles", "xbrli"):
        if f"/{family}/" in namespace or namespace.endswith(f"/{family}"):
            return family, namespace.rstrip("/").rsplit("/", 1)[-1], True
    if "xbrl.sec.gov" in namespace:
        return "sec-standard", namespace.rstrip("/").rsplit("/", 1)[-1], True
    return "company-extension", namespace.rstrip("/").rsplit("/", 1)[-1], False


def _fact_id(filing_id: str, fact: Any, ordinal: int) -> str:
    return _stable_id("fact", filing_id, getattr(fact, "id", None) or "", _source_locator(fact) or "", ordinal)


def _stable_id(kind: str, *parts: Any) -> str:
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return f"{kind}_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _numeric_value(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, ValueError):
        return None


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _source_document(fact: Any) -> str | None:
    document = getattr(fact, "modelDocument", None)
    return _text(getattr(document, "basename", None) or getattr(document, "uri", None))


def _source_locator(fact: Any) -> str | None:
    line = getattr(fact, "sourceline", None)
    return f"line:{line}" if line is not None else None


def _label(concept: Any) -> str | None:
    if concept is None:
        return None
    method = getattr(concept, "label", None)
    return _text(method()) if callable(method) else None


def _documentation(concept: Any) -> str | None:
    if concept is None:
        return None
    method = getattr(concept, "label", None)
    if not callable(method):
        return None
    try:
        return _text(method("http://www.xbrl.org/2003/role/documentation"))
    except TypeError:
        return None


def _unit_text(numerator: Any, denominator: Any) -> str:
    top = " * ".join(_qname_text(item) or "" for item in numerator)
    bottom = " * ".join(_qname_text(item) or "" for item in denominator)
    return f"{top} / {bottom}" if bottom else top
