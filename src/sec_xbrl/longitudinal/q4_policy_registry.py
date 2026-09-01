"""C3-M5 reviewed, bounded policy registry for standard Q4 flow declarations.

The registry is a policy artifact: it may generate a declaration only from a
versioned allowlist and retained presentation evidence.  It cannot learn a
QName from a filing or accept an arbitrary caller-supplied QName.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication
from sec_xbrl.longitudinal.quarterly_policy import QuarterlySemanticDeclaration

Q4_POLICY_REGISTRY_VERSION = "l2-m7-dimensional-q4-policy-registry-v1"
INCOME_ALLOWLIST = frozenset({
    "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "CostOfRevenue",
    "CostOfGoodsAndServicesSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    "GrossProfit", "OperatingExpenses", "CostsAndExpenses", "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense", "SellingAndMarketingExpense", "GeneralAndAdministrativeExpense",
    "OperatingIncomeLoss", "NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense",
    "InvestmentIncomeInterest", "InterestExpense", "InterestExpenseNonoperating",
    "IncomeLossFromContinuingOperations",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeTaxExpenseBenefit", "NetIncomeLoss", "ProfitLoss",
})
CASH_FLOW_ALLOWLIST = frozenset({
    "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
    "Depreciation", "DepreciationDepletionAndAmortization",
})
_DATASETS = ("approved_q4_declaration", "q4_policy_coverage")


class Q4PolicyRegistryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Q4PolicyRegistryResult:
    declarations: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {"approved_q4_declaration": self.declarations, "q4_policy_coverage": self.coverage}

    def semantic_declarations(self) -> tuple[QuarterlySemanticDeclaration, ...]:
        return tuple(
            QuarterlySemanticDeclaration(
                row["company_canonical_concept_id"],
                "REVIEWED_ADDITIVE_AMOUNT",
                "ADDITIVE_AMOUNT",
                True,
                row["declaration_id"],
                Q4_POLICY_REGISTRY_VERSION,
                cik=str(row["cik"]),
                company_canonical_dimension_key=row.get("company_canonical_dimension_key"),
                basis_version=row.get("basis_version"),
                unit_semantics=row.get("unit_semantics"),
                scope_is_exact=True,
            )
            for row in self.declarations
        )


@dataclass(frozen=True, slots=True)
class Q4PolicyRegistryPublication:
    run_root: Path
    manifest_path: Path
    output_counts: Mapping[str, int]


class Q4PolicyRegistryMaterializer:
    """Create only policy-approved declarations with exact PRE evidence."""
    def materialize(self, publication: VerifiedLayer2Publication, *, release: CorpusRelease, effective_from: str, effective_to: str | None = None) -> Q4PolicyRegistryResult:
        if not isinstance(publication, VerifiedLayer2Publication) or not publication.is_reader_attested:
            raise Q4PolicyRegistryError("Q4 policy registry requires reader-attested C3-M1 publication")
        if publication.identity.get("layer2_run_fingerprint") != release.layer2_run.fingerprint or set(publication.input_ciks) != set(release.ciks):
            raise Q4PolicyRegistryError("Q4 policy registry input does not match CorpusRelease")
        if not effective_from or (effective_to is not None and effective_to < effective_from):
            raise Q4PolicyRegistryError("Q4 policy registry effective range is invalid")
        facts = [dict(x) for x in publication.records("analytical_fact") if x.get("view") == "AS_FILED" and x.get("source_type") == "REPORTED"]
        raw = {(str(x.get("filing_id")), str(x.get("fact_id"))): x for x in release.records("fact")}
        concepts = {(str(x.get("filing_id")), str(x.get("raw_concept_id"))): x for x in release.records("concept")}
        roles = {(str(x.get("filing_id")), str(x.get("role_id"))): x for x in release.records("role")}
        pre = defaultdict(list)
        for relation in release.records("relationship"):
            if relation.get("network_type") == "PRE" and relation.get("to_raw_concept_id"):
                pre[(str(relation.get("filing_id")), str(relation["to_raw_concept_id"]))].append(relation)
        evidence: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        rejected: dict[str, Counter[str]] = defaultdict(Counter)
        for fact in facts:
            if fact.get("period_class") not in {"FY", "YTD_9M"}:
                continue
            source = raw.get((str(fact.get("source_filing_id")), str(fact.get("selected_fact_id"))))
            if not source:
                rejected[str(fact.get("cik"))]["RAW_FACT_NOT_RETAINED"] += 1; continue
            concept = concepts.get((str(fact.get("source_filing_id")), str(source.get("raw_concept_id"))))
            if not concept or not _allowed(concept):
                rejected[str(fact.get("cik"))]["QNAME_NOT_IN_REVIEWED_ALLOWLIST"] += 1; continue
            links = pre.get((str(fact.get("source_filing_id")), str(source.get("raw_concept_id"))), ())
            matched = []
            for link in links:
                role = roles.get((str(link.get("filing_id")), str(link.get("role_id"))))
                category = _role_category(None if role is None else role.get("role_definition"))
                if category:
                    matched.append({"role_id": link.get("role_id"), "role_definition": role.get("role_definition") if role else None, "role_category": category, "relationship_id": link.get("relationship_id")})
            if not matched:
                rejected[str(fact.get("cik"))]["PRIMARY_CONSOLIDATED_PRE_ROLE_REQUIRED"] += 1; continue
            scope = _declaration_scope(fact)
            evidence[scope].append({"fact": fact, "concept": concept, "pre": matched})
        declarations = []
        for scope, rows in sorted(evidence.items(), key=repr):
            cik, concept_id, dimensions, basis, unit = scope
            roles_seen = sorted({json.dumps(item, sort_keys=True) for row in rows for item in row["pre"]})
            names = sorted({str(row["concept"].get("local_name")) for row in rows})
            declaration_id = _id("q4-policy", (scope, names, roles_seen, effective_from, effective_to))
            declarations.append({"declaration_id": declaration_id, "registry_version": Q4_POLICY_REGISTRY_VERSION, "cik": cik, "company_canonical_concept_id": concept_id, "company_canonical_dimension_key": dimensions, "basis_version": basis, "unit_semantics": unit, "semantic_review_state": "REVIEWED_ADDITIVE_AMOUNT", "value_kind": "ADDITIVE_AMOUNT", "is_additive": True, "effective_from": effective_from, "effective_to": effective_to, "allowlisted_local_names": names, "pre_evidence": [json.loads(value) for value in roles_seen], "approved_analytical_fact_ids": sorted(str(row["fact"]["analytical_fact_id"]) for row in rows), "policy_provenance": "CONTROLLED_STANDARD_STATEMENT_ALLOWLIST"})
        coverage = []
        for cik in release.ciks:
            coverage.append({"cik": cik, "approved_declaration_count": sum(row["cik"] == cik for row in declarations), "rejected_fact_counts": dict(sorted(rejected[cik].items())), "registry_version": Q4_POLICY_REGISTRY_VERSION})
        return Q4PolicyRegistryResult(tuple(declarations), tuple(coverage))


class Q4PolicyRegistryPublisher:
    manifest_name = "q4_policy_registry_manifest.json"
    def publish(self, result: Q4PolicyRegistryResult, *, output_root: Path, run_version: str, upstream: VerifiedLayer2Publication, release: CorpusRelease) -> Q4PolicyRegistryPublication:
        if not upstream.is_reader_attested or upstream.identity.get("layer2_run_fingerprint") != release.layer2_run.fingerprint:
            raise Q4PolicyRegistryError("Q4 policy registry publisher requires matching reader-attested inputs")
        if not run_version or "/" in run_version or "\\" in run_version: raise Q4PolicyRegistryError("registry run_version must be a non-path identifier")
        rows = {k: tuple(sorted((dict(x) for x in v), key=_json)) for k, v in result.as_datasets().items()}; counts = {k: len(v) for k, v in rows.items()}; hashes = {k: _hash(v) for k, v in rows.items()}
        manifest = {"contract_version": Q4_POLICY_REGISTRY_VERSION, "run_version": run_version, "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"], "upstream_layer2_manifest_sha256": upstream.identity["layer2_manifest_sha256"], "corpus_release_fingerprint": release.layer2_run.fingerprint, "output_counts": counts, "output_content_sha256": hashes}
        root, target = Path(output_root), Path(output_root)/run_version; root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            path = target/self.manifest_name
            if not path.is_file() or json.loads(path.read_text()) != manifest: raise Q4PolicyRegistryError("registry run_version already exists with different content")
            return Q4PolicyRegistryPublication(target,path,counts)
        staging=Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-",dir=root))
        try:
            for name, values in rows.items(): (staging/f"{name}.jsonl").write_text("".join(_json(x)+"\n" for x in values))
            (staging/self.manifest_name).write_text(_json(manifest)+"\n"); os.replace(staging,target)
        except Exception: shutil.rmtree(staging,ignore_errors=True); raise
        return Q4PolicyRegistryPublication(target,target/self.manifest_name,counts)


class Q4PolicyRegistryReader:
    """Hash-attest the controlled registry before M2-v2 may consume it."""
    def load(self, run_root: Path, *, upstream: VerifiedLayer2Publication, release: CorpusRelease) -> Q4PolicyRegistryResult:
        if not isinstance(upstream, VerifiedLayer2Publication) or not upstream.is_reader_attested:
            raise Q4PolicyRegistryError("registry reader requires reader-attested upstream")
        root=Path(run_root); path=root/Q4PolicyRegistryPublisher.manifest_name
        if not root.is_dir() or root.is_symlink() or not path.is_file() or path.is_symlink(): raise Q4PolicyRegistryError("registry is missing or unsafe")
        try: manifest=json.loads(path.read_text())
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: raise Q4PolicyRegistryError("registry manifest is invalid") from exc
        required={"contract_version","run_version","upstream_layer2_run_fingerprint","upstream_layer2_manifest_sha256","corpus_release_fingerprint","output_counts","output_content_sha256"}
        if set(manifest)!=required or manifest.get("contract_version")!=Q4_POLICY_REGISTRY_VERSION: raise Q4PolicyRegistryError("registry manifest has unsupported contract")
        if manifest.get("upstream_layer2_run_fingerprint")!=upstream.identity.get("layer2_run_fingerprint") or manifest.get("upstream_layer2_manifest_sha256")!=upstream.identity.get("layer2_manifest_sha256") or manifest.get("corpus_release_fingerprint")!=release.layer2_run.fingerprint: raise Q4PolicyRegistryError("registry does not match verified inputs")
        expected={self_name for self_name in [Q4PolicyRegistryPublisher.manifest_name,*(f"{x}.jsonl" for x in _DATASETS)]}; actual={x.name for x in root.iterdir() if x.is_file() and not x.is_symlink()}
        if actual!=expected or any(x.is_dir() or x.is_symlink() for x in root.iterdir()): raise Q4PolicyRegistryError("registry layout is incomplete or unexpected")
        rows={}
        for name in _DATASETS:
            try: values=tuple(json.loads(x) for x in (root/f"{name}.jsonl").read_text().splitlines())
            except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc: raise Q4PolicyRegistryError("registry dataset is invalid") from exc
            if any(not isinstance(x,dict) for x in values) or len(values)!=manifest["output_counts"].get(name) or _hash(values)!=manifest["output_content_sha256"].get(name): raise Q4PolicyRegistryError("registry content verification failed")
            rows[name]=tuple(dict(x) for x in values)
        return Q4PolicyRegistryResult(rows["approved_q4_declaration"],rows["q4_policy_coverage"])


def _allowed(concept: Mapping[str, Any]) -> bool:
    namespace, name = str(concept.get("namespace_uri") or ""), str(concept.get("local_name") or "")
    return "us-gaap" in namespace and name in INCOME_ALLOWLIST | CASH_FLOW_ALLOWLIST

def _role_category(value: object) -> str | None:
    text = str(value or "").lower()
    if "cash flows" in text and ("consolidated" in text or "statements of cash" in text): return "CASH_FLOWS"
    if ("operations" in text or "income" in text) and ("consolidated" in text or "statements of" in text): return "INCOME_OPERATIONS"
    return None
def _id(prefix: str, value: Any) -> str: return prefix+":"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=repr).encode()).hexdigest()[:24]
def _json(value: Mapping[str, Any]) -> str: return json.dumps(value,sort_keys=True,separators=(",",":"),default=list)
def _hash(rows: Iterable[Mapping[str, Any]]) -> str: return hashlib.sha256("".join(_json(x)+"\n" for x in rows).encode()).hexdigest()

def _declaration_scope(fact: Mapping[str, Any]) -> tuple[Any, ...]:
    """Complete scope: no concept-only authorization can cross a boundary."""
    return (str(fact.get("cik")), str(fact.get("company_canonical_concept_id")),
            _freeze(fact.get("company_canonical_dimension_key")), _freeze(fact.get("basis_version")),
            _freeze(fact.get("unit_semantics")))

def _freeze(value: Any) -> Any:
    if isinstance(value, list): return tuple(_freeze(x) for x in value)
    if isinstance(value, tuple): return tuple(_freeze(x) for x in value)
    if isinstance(value, dict): return tuple(sorted((k,_freeze(v)) for k,v in value.items()))
    return value
