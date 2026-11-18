"""Source-qualified weighted EPS using period-local effective CAL evidence."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sec_xbrl.metrics.cal_eps_source import (
    EPS_NUMERATOR_ADJUSTMENT_NAMES,
    FASB_NAMESPACE,
    is_participating_adjustment,
)
from sec_xbrl.metrics.market_inputs import finite
from sec_xbrl.metrics.q4_eps_reconstruction import _div, _interval, _mul, _sub, _weights
from sec_xbrl.relationships.layer1 import CALCULATION_ARCROLES

CAL_EPS_RULE = "common-q4-eps-effective-cal-v1"
_NET = ("NetIncomeLoss",)
_COMMON = {
    "basic": ("NetIncomeLossAvailableToCommonStockholdersBasic",),
    "diluted": ("NetIncomeLossAvailableToCommonStockholdersDiluted",),
}
_EPS = {
    "basic": ("EarningsPerShareBasic",),
    "diluted": ("EarningsPerShareDiluted",),
}
_WEIGHTED = {
    "basic": ("WeightedAverageNumberOfSharesOutstandingBasic",),
    "diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                "WeightedAverageNumberOfSharesOutstandingDiluted"),
}
_CONTROL = ("IncomeLossFromContinuingOperations", "IncomeLossFromContinuingOperationsAttributableToParent")
_PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
_PRETAX_EXCLUDING_EQUITY = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
_AFTER_TAX_EXCLUDING_EQUITY = "IncomeLossFromContinuingOperationsBeforeIncomeLossFromEquityMethodInvestments"
_TAX = "IncomeTaxExpenseBenefit"
_EQUITY_METHOD = "IncomeLossFromEquityMethodInvestments"
_NCI = frozenset({
    "NetIncomeLossAttributableToNoncontrollingInterest",
    "NetIncomeLossAttributableToNonredeemableNoncontrollingInterest",
})
_STOCK_AWARD_SHARES = "IncrementalCommonSharesAttributableToShareBasedPaymentArrangements"
_GENERIC_INCREMENTAL_SHARES = "WeightedAverageNumberDilutedSharesOutstandingAdjustment"
_STOCK_RELATED_CHILDREN = frozenset({
    _STOCK_AWARD_SHARES,
    "EffectOfEmployeeRestrictedStockSharesOnWeightedAverageNumberOfDilutedSharesOutstanding",
    "IncrementalCommonSharesAttributableToNonvestedSharesWithForfeitableDividends",
})
_AMBIGUOUS_SHARE_CHILDREN = frozenset({
    _GENERIC_INCREMENTAL_SHARES,
    "IncrementalCommonSharesAttributableToCallOptionsAndWarrants",
})
_STOCK_AWARD_TERMS = re.compile(
    r"\b(?:[a-z]+[- ]based (?:awards?|payments?|compensation)|stock options?|equity awards?|"
    r"restrict(?:ed)? stock|rsus?|employee(?:s['’]?)? (?:stock purchase|options?))\b",
    re.IGNORECASE,
)
_UNSUPPORTED_SHARE_TERMS = re.compile(
    r"\b(?:if[- ]converted|convertible|conversion|contingent\w*|two[- ]class|cash[- ]settl\w*)\b",
    re.IGNORECASE,
)
_TREASURY_STOCK = re.compile(r"\btreasury[- ]stock method\b", re.IGNORECASE)
_NONAFFIRMATIVE_METHOD = re.compile(
    r"\b(?:no|not|never|neither|cannot|without|exclud\w*|anti[- ]?dilutive|"
    r"(?:do|does|is|are|can|could|would|will)n['’]t)\b", re.IGNORECASE,
)
_METHOD_NAME = r"(?:the\s+)?treasury[- ]stock method\b"
_CURRENT_METHOD_APPLICATION = re.compile(
    r"\b(?:(?:(?:is|are|was|were)\s+(?:calculated|computed|determined|measured|based)"
    r"|we\s+(?:calculate|compute|determine|measure)"
    r"|(?:the|our)\s+company\s+(?:calculates|computes|determines|measures)"
    r"|includes?|(?:is|are|was|were)\s+included)\b.{0,700}?\b"
    r"(?:using|under|with|by applying|in accordance with)\s+" + _METHOD_NAME
    + r"|(?:use|uses|apply|applies)\s+" + _METHOD_NAME
    + r"|treasury[- ]stock method\s+(?:is|was)\s+(?:used|applied)\b)",
    re.IGNORECASE,
)
_NONCURRENT_APPLICATION_PREFIX = re.compile(
    r"\b(?:would|could|might|may|will|shall|should|to)\s+(?:\w+\s+){0,4}$", re.IGNORECASE,
)
_WARRANTS = re.compile(r"\bwarrants?\b", re.IGNORECASE)
_COMMON_STOCK = re.compile(r"\bcommon (?:stock|shares)\b", re.IGNORECASE)
_PREFERRED_CASH = "DividendsPreferredStockCash"
_CURRENCY = ["http://www.xbrl.org/2003/iso4217", "USD"]
_SHARES = ["http://www.xbrl.org/2003/instance", "shares"]
_MONEY_UNIT = [[_CURRENCY], []]
_SHARES_UNIT = [[_SHARES], []]
_EPS_UNIT = [[_CURRENCY], [_SHARES]]
_NETWORK_FIELDS = ("filing_id", "role_id", "arcrole", "link_qname", "arc_qname")


class QualificationError(ValueError):
    """An exact source coordinate could not support an EPS component."""

    def __init__(self, reason: str, *, fail: bool = False, evidence: dict | None = None) -> None:
        super().__init__(reason)
        self.status = "FAIL" if fail else "HOLD"
        self.evidence = evidence


@dataclass(frozen=True)
class Reported:
    value: Decimal
    interval: list[Decimal]
    source: dict
    duplicates: tuple[dict, ...]

    def evidence(self) -> dict:
        return {
            "value": str(self.value), "interval": [str(v) for v in self.interval],
            "selected_fact_id": self.source["fact_id"], "facts": list(self.duplicates),
        }


def _overlap(a: list[Decimal], b: list[Decimal]) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1])


def _duplicates(rows: list[dict]) -> Reported:
    if len({(r["raw_concept_id"], r["context_key"]) for r in rows}) != 1:
        raise QualificationError("AMBIGUOUS_COMPONENT_QNAME_OR_CONTEXT")
    intervals = [_interval(r["value_numeric"], r["decimals"]) for r in rows]
    if any(i is None for i in intervals):
        raise QualificationError("SOURCE_ROUNDING_PRECISION_UNKNOWN")
    lo, hi = max(i[0] for i in intervals), min(i[1] for i in intervals)
    if lo > hi:
        raise QualificationError("CONFLICTING_REPORTED_DUPLICATES")
    ordered = sorted(zip(rows, intervals, strict=True), key=lambda x: (x[1][1] - x[1][0], x[0]["fact_id"]))
    chosen = ordered[0][0]
    value = Decimal(chosen["value_numeric"])
    if not lo <= value <= hi:
        raise QualificationError("DUPLICATE_POINT_OUTSIDE_PRECISION_INTERSECTION")
    return Reported(value, [lo, hi], chosen, tuple(r for r, _ in ordered))


class FilingInputs:
    """Index a pinned accession without combining effective network identities."""

    def __init__(self, projection: dict, *, source_labels: Callable[[dict], list[dict]] | None = None) -> None:
        self.projection = projection
        self.source_labels = source_labels
        self.concepts = {c["raw_concept_id"]: c for c in projection["concepts"]}
        self.by_name = defaultdict(set)
        for key, c in self.concepts.items():
            if FASB_NAMESPACE.fullmatch(c["namespace_uri"]) and c["is_standard"] is True:
                self.by_name[c["local_name"]].add(key)
        self.by_period = defaultdict(list)
        for fact in projection["facts"]:
            self.by_period[(fact["start"], fact["end"])].append(fact)
        self.networks = defaultdict(lambda: defaultdict(list))
        for arc in projection["relationships"]:
            if arc["arcrole"] not in CALCULATION_ARCROLES or any(not arc[k] for k in _NETWORK_FIELDS):
                raise ValueError("CAL EPS projection has an incomplete effective base-set identity")
            self.networks[tuple(arc[k] for k in _NETWORK_FIELDS)][arc["from_raw_concept_id"]].append(arc)

    def select(self, names: tuple[str, ...], start: str, end: str, unit: list,
               *, context_key: str | None = None) -> Reported | None:
        keys = set().union(*(self.by_name[n] for n in names))
        return self._select(keys, start, end, unit, context_key=context_key)

    def _select(self, keys: set[str], start: str, end: str, unit: list,
                *, context_key: str | None = None) -> Reported | None:
        relevant = [f for f in self.by_period[start, end] if f["raw_concept_id"] in keys
                    and (context_key is None and not f["dimensions"] or f["context_key"] == context_key)]
        if not relevant:
            return None
        valid = [f for f in relevant if f["unit"] == unit]
        if not valid:
            raise QualificationError("COMPONENT_UNIT_MISMATCH")
        cik = self.projection["filing"]["cik"]
        if any(not re.fullmatch(r"https?://www\.sec\.gov/CIK:\d{1,10}", f["entity_identifier"] or "")
               or f["entity_identifier"].rsplit(":", 1)[-1].zfill(10) != cik for f in valid):
            raise QualificationError("COMPONENT_CONTEXT_ENTITY_MISMATCH")
        if any(f["is_nil"] or finite(f["value_numeric"]) is None for f in valid):
            raise QualificationError("REPORTED_COMPONENT_NIL_OR_NONNUMERIC")
        return _duplicates(valid)

    def calculations(self, parent: Reported) -> list[dict]:
        """Validate a complete immediate signed equation in each applicable base set."""
        fact = parent.source
        key = fact["raw_concept_id"]
        results = []
        for network, outgoing in self.networks.items():
            if key not in outgoing:
                continue
            arcs = outgoing[key]
            if _cycle(outgoing, key):
                results.append({"reason": "CALCULATION_NETWORK_CYCLE"})
                continue
            weighted, children, seen = [Decimal(0), Decimal(0)], [], set()
            try:
                for arc in arcs:
                    child = arc["to_raw_concept_id"]
                    weight = finite(arc.get("weight"))
                    if child in seen or weight in {None, Decimal(0)} or arc.get("target_role_uri"):
                        raise QualificationError("CALCULATION_CHILD_IDENTITY_OR_WEIGHT_UNSUPPORTED")
                    seen.add(child)
                    selected = self._select({child}, fact["start"], fact["end"], fact["unit"],
                                            context_key=fact["context_key"])
                    if selected is None:
                        raise QualificationError("CALCULATION_CHILD_FACT_MISSING_IN_EQUIVALENT_CONTEXT")
                    piece = _mul(selected.interval, weight)
                    weighted = [weighted[i] + piece[i] for i in range(2)]
                    concept = self.concepts[child]
                    children.append({
                        "relationship": arc, "component": selected.evidence(),
                        "concept": [concept["namespace_uri"], concept["local_name"]],
                        "standard": FASB_NAMESPACE.fullmatch(concept["namespace_uri"]) is not None
                                    and concept["is_standard"] is True,
                        "weight": str(weight),
                    })
                if not _overlap(parent.interval, weighted):
                    raise QualificationError("CALCULATION_ROUNDING_MISMATCH", fail=True)
            except QualificationError as exc:
                results.append({"reason": str(exc), "status": exc.status, "network": dict(zip(_NETWORK_FIELDS, network, strict=True)),
                                "relationships": arcs})
            else:
                results.append({"status": "VERIFIED", "network": dict(zip(_NETWORK_FIELDS, network, strict=True)),
                                "parent": parent.evidence(), "children": children,
                                "weighted_interval": [str(v) for v in weighted]})
        return results


def _cycle(outgoing: dict, root: str) -> bool:
    """Iterative DFS so proof terminates on cycles and deeply nested CAL."""
    active, finished = {root}, set()
    frontier = [(root, iter(outgoing.get(root, ())))]
    while frontier:
        parent, arcs = frontier[-1]
        arc = next(arcs, None)
        if arc is None:
            frontier.pop()
            active.remove(parent)
            finished.add(parent)
            continue
        child = arc["to_raw_concept_id"]
        if child in active:
            return True
        if child not in finished and child in outgoing:
            active.add(child)
            frontier.append((child, iter(outgoing[child])))
    return False


def _resolved(calculations: list[dict], predicate: Callable[[list[dict]], bool], reason: str) -> list[dict]:
    proven = [r for r in calculations if r.get("status") == "VERIFIED" and predicate(r["children"])]
    if any(r.get("status") == "VERIFIED" and not predicate(r["children"]) for r in calculations):
        raise QualificationError(reason)
    if not proven:
        if len(calculations) == 1 and calculations[0].get("reason"):
            exc = calculations[0]
            raise QualificationError(exc["reason"], fail=exc.get("status") == "FAIL")
        raise QualificationError(reason)
    memberships = {tuple(sorted((tuple(c["concept"]), Decimal(c["weight"])) for c in p["children"]))
                   for p in proven}
    if len(memberships) != 1:
        raise QualificationError("CONFLICTING_EFFECTIVE_CALCULATION_NETWORKS")
    return proven


def _required(source: FilingInputs, names: tuple[str, ...], start: str, end: str, unit: list,
              *, context_key: str | None = None) -> Reported:
    selected = source.select(names, start, end, unit, context_key=context_key)
    if selected is None:
        raise QualificationError("REPORTED_COMPONENT_MISSING:" + names[0])
    return selected


def _check_eps(numerator: Reported, shares: Reported, eps: Reported) -> None:
    interval = _div(numerator.interval, shares.interval) if shares.interval[0] > 0 else None
    if interval is None:
        raise QualificationError("WEIGHTED_AVERAGE_SHARE_DENOMINATOR_NONPOSITIVE_OR_UNCERTAIN")
    if not _overlap(interval, eps.interval):
        raise QualificationError("CUMULATIVE_REPORTED_EPS_MISMATCH", fail=True)


def _eps_table_binding(*facts: Reported) -> dict | None:
    # The three reported amounts must occur in one visible source block in the
    # same XBRL coordinate. Tag identity identifies the EPS and share rows.
    by_fact = [
        {(f["source_document"], f["source_table"]["table_xpath"]): f for f in selection.duplicates
         if f["source_table"]}
        for selection in facts
    ]
    for document, table in sorted(set.intersection(*(set(i) for i in by_fact))):
        rows = [i[document, table] for i in by_fact]
        if len({f["source_table"]["row_xpath"] for f in rows}) == len(rows):
            return {"source_document": document, "table_xpath": table, "facts": rows}
    return None


def _numerator(source: FilingInputs, flavor: str, shares: Reported, eps: Reported) -> tuple[Reported, dict]:
    start, end, context = (eps.source[k] for k in ("start", "end", "context_key"))
    selected = source.select(_COMMON[flavor], start, end, _MONEY_UNIT, context_key=context)
    if selected is not None:
        calculations = source.calculations(selected)
        if calculations and not any(c.get("status") == "VERIFIED" for c in calculations):
            raise QualificationError("EXPLICIT_COMMON_NUMERATOR_CALCULATION_NOT_VERIFIED")
        return selected, {"basis": "REPORTED_FLAVOR_SPECIFIC_COMMON_NUMERATOR", "calculations": calculations}
    basic_eps = _required(source, _EPS["basic"], start, end, _EPS_UNIT, context_key=context)
    basic_shares = _required(source, _WEIGHTED["basic"], start, end, _SHARES_UNIT, context_key=context)
    if flavor == "diluted":
        basic = source.select(_COMMON["basic"], start, end, _MONEY_UNIT, context_key=context)
        if basic is not None:
            _check_eps(basic, basic_shares, basic_eps)
            proved = _resolved(
                source.calculations(basic), _explicit_common_numerator_bridge,
                "DISTINCT_COMMON_ATTRIBUTION_BLOCKS_PARENT_NET_INCOME_FALLBACK",
            )
            return basic, {"basis": "SAME_COMMON_ATTRIBUTION_VIA_PARENT_CAL_AND_NORMAL_DILUTION",
                           "calculations": proved, "basic_eps": basic_eps.evidence(),
                           "basic_shares": basic_shares.evidence()}
    parent = _required(source, _NET, start, end, _MONEY_UNIT, context_key=context)
    binding = _eps_table_binding(parent, shares, eps, basic_shares, basic_eps) if flavor == "diluted" else _eps_table_binding(parent, shares, eps)
    if binding is None:
        raise QualificationError("PARENT_NET_INCOME_NOT_BOUND_TO_REPORTED_EPS_TABLE")
    adjustment_evidence = _parent_numerator_adjustments(source, flavor, start, end, context)
    _check_eps(parent, basic_shares, basic_eps)
    return parent, {"basis": "REPORTED_PARENT_NET_INCOME_EPS_SOURCE_BLOCK", "table_binding": binding,
                    "basic_eps": basic_eps.evidence(), "basic_shares": basic_shares.evidence(),
                    "reported_adjustment_evidence": adjustment_evidence}


def _parent_numerator_adjustments(source: FilingInputs, flavor: str, start: str, end: str, context: str) -> list[dict]:
    evidence = []
    for name in sorted(EPS_NUMERATOR_ADJUSTMENT_NAMES):
        if flavor == "basic" and name == "InterestOnConvertibleDebtNetOfTax":
            continue
        reported = source.select((name,), start, end, _MONEY_UNIT, context_key=context)
        if reported is None:
            continue
        item = {"concept": name, "component": reported.evidence()}
        if reported.interval != [Decimal(0), Decimal(0)]:
            raise QualificationError("PARENT_NET_INCOME_EPS_ADJUSTMENT_NONZERO_OR_UNCERTAIN", evidence=item)
        evidence.append(item)
    return evidence


def _explicit_common_numerator_bridge(children: list[dict]) -> bool:
    names = {(c["concept"][1], Decimal(c["weight"])) for c in children}
    parent = {(_NET[0], Decimal(1))}
    return (all(c["standard"] for c in children)
            and names in (parent, parent | {(_PREFERRED_CASH, Decimal(-1))}))


def _affirmative_treasury_stock_policy(source: FilingInputs) -> list[dict]:
    result = []
    for occurrence in source.projection.get("eps_treasury_stock_policy", []):
        for clause in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", occurrence["snippet"]):
            if (not _TREASURY_STOCK.search(clause) or _UNSUPPORTED_SHARE_TERMS.search(clause)
                or _NONAFFIRMATIVE_METHOD.search(clause)):
                continue
            if not _STOCK_AWARD_TERMS.search(clause) and not _WARRANTS.search(clause):
                continue
            if _WARRANTS.search(clause) and not _COMMON_STOCK.search(clause):
                continue
            if not any(not _NONCURRENT_APPLICATION_PREFIX.search(clause[:match.start()])
                       for match in _CURRENT_METHOD_APPLICATION.finditer(clause)):
                continue
            result.append({**occurrence, "affirmative_method_clause": clause})
    return result


def _normal_dilution(source: FilingInputs, shares: Reported) -> list[dict]:
    def supports(children: list[dict]) -> bool:
        return (sum(c["concept"][1] in _WEIGHTED["basic"] for c in children) == 1
                and all(c["standard"] and Decimal(c["weight"]) == 1
                        and Decimal(c["component"]["value"]) >= 0
                        and Decimal(c["component"]["interval"][1]) >= 0
                        and _share_category(c) for c in children))

    def _share_category(child: dict) -> str | None:
        name = child["concept"][1]
        if name in _WEIGHTED["basic"]:
            return "BASIC"
        if name in _STOCK_RELATED_CHILDREN:
            return "STOCK_AWARD"
        if name not in _AMBIGUOUS_SHARE_CHILDREN:
            return None
        if "source_category" in child:
            return child["source_category"]
        labels = [label for fact in child["component"]["facts"] for label in
                  (source.source_labels(fact) if source.source_labels else [])]
        if any(_UNSUPPORTED_SHARE_TERMS.search(label["text"]) for label in labels):
            return None
        exact_labels = [label for label in labels if _STOCK_AWARD_TERMS.search(label["text"])
                        and not _WARRANTS.search(label["text"])]
        if exact_labels:
            child["source_category"] = "STOCK_AWARD"
            child["stock_award_source_labels"] = exact_labels
            return "STOCK_AWARD"
        policies = _affirmative_treasury_stock_policy(source)
        if policies:
            child["source_category"] = "STOCK_AWARD"
            child["treasury_stock_policy"] = policies
            return "STOCK_AWARD"
        child["source_category"] = None
        return None

    return _resolved(source.calculations(shares), supports, "COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN")


def _continuing_control(source: FilingInputs, start: str, end: str, context_key: str | None = None) -> tuple[Reported, dict]:
    control = source.select(_CONTROL, start, end, _MONEY_UNIT, context_key=context_key)
    if control is not None:
        return control, {"basis": "REPORTED_CONTINUING_OPERATIONS"}
    parent = _required(source, _NET, start, end, _MONEY_UNIT, context_key=context_key)
    context = parent.source["context_key"]

    def signed_components(children: list[dict]) -> frozenset:
        if not all(c["standard"] for c in children):
            return frozenset()
        return frozenset((c["concept"][1], Decimal(c["weight"])) for c in children)

    positive, negative = Decimal(1), Decimal(-1)
    approved = {
        frozenset({(_PRETAX, positive), (_TAX, negative)}),
        frozenset({(_PRETAX_EXCLUDING_EQUITY, positive), (_TAX, negative)}),
        frozenset({(_PRETAX_EXCLUDING_EQUITY, positive), (_EQUITY_METHOD, positive), (_TAX, negative)}),
        frozenset({(_AFTER_TAX_EXCLUDING_EQUITY, positive), (_EQUITY_METHOD, positive)}),
    }
    proof = []
    for equation in source.calculations(parent):
        if equation.get("status") != "VERIFIED":
            continue
        components = signed_components(equation["children"])
        if components in approved:
            proof.append(equation)
            continue
        if components not in {frozenset({("ProfitLoss", positive), (nci, negative)}) for nci in _NCI}:
            continue
        profit = _required(source, ("ProfitLoss",), start, end, _MONEY_UNIT, context_key=context)
        pre_tax = [e for e in source.calculations(profit) if e.get("status") == "VERIFIED"
                   and e["network"] == equation["network"] and signed_components(e["children"]) in approved]
        if pre_tax:
            proof.append({**equation, "profit_loss_continuing_equations": pre_tax})
    if not proof:
        raise QualificationError("CONTINUING_OPERATIONS_CONTROL_NOT_PROVEN")
    return parent, {"basis": "CONTINUING_PRETAX_LESS_INCOME_TAX_WITH_REPORTED_ADJUSTMENTS", "calculations": proof}


def _has_participating(source: FilingInputs, start: str, end: str, context: str) -> bool:
    return any(
        f["context_key"] == context
        and is_participating_adjustment(source.concepts[f["raw_concept_id"]]["local_name"])
        and _interval(f["value_numeric"], f["decimals"]) != [Decimal(0), Decimal(0)]
        for f in source.by_period[start, end]
    )


def _common_reported_attribution(
    diluted: Reported, basic: Reported, diluted_calculations: list[dict], basic_calculations: list[dict],
) -> dict | None:
    if not _overlap(diluted.interval, basic.interval):
        return None
    def scope(fact: dict) -> tuple[str, str, str]:
        table = fact["source_table"]
        return fact["source_document"], table["table_xpath"], table["row_xpath"]

    common_rows = {scope(f) for f in diluted.duplicates if f["source_table"]} & {
        scope(f) for f in basic.duplicates if f["source_table"]
    }
    if common_rows:
        return {"basis": "BOTH_FLAVOR_FACTS_IN_ONE_DISCLOSED_NUMERATOR_ROW",
                "shared_source_rows": [list(r) for r in sorted(common_rows)]}

    def composition(calculation: dict) -> frozenset:
        return frozenset(
            (tuple(c["concept"]), Decimal(c["weight"]), c["component"]["selected_fact_id"])
            for c in calculation["children"]
        )

    pairs = [(a, b) for a in diluted_calculations for b in basic_calculations
             if a.get("status") == b.get("status") == "VERIFIED" and composition(a) == composition(b)]
    if len({composition(a) for a, _ in pairs}) == 1:
        return {"basis": "EQUIVALENT_COMPLETE_CAL_NUMERATOR_COMPOSITION",
                "basic_calculations": [b for _, b in pairs],
                "diluted_calculations": [a for a, _ in pairs]}
    return None


def _period_components(source: FilingInputs, flavor: str, start: str, end: str) -> dict:
    eps = _required(source, _EPS[flavor], start, end, _EPS_UNIT)
    context = eps.source["context_key"]
    shares = _required(source, _WEIGHTED[flavor], start, end, _SHARES_UNIT, context_key=context)
    numerator, numerator_proof = _numerator(source, flavor, shares, eps)
    _check_eps(numerator, shares, eps)
    if _has_participating(source, start, end, context):
        raise QualificationError("TWO_CLASS_ALLOCATION_ADDITIVITY_NOT_PROVEN", evidence=numerator_proof)
    result = {"eps": eps, "shares": shares, "numerator": numerator, "numerator_proof": numerator_proof}
    if flavor == "diluted":
        result["share_calculations"] = _normal_dilution(source, shares)
        basic_shares = _required(source, _WEIGHTED["basic"], start, end, _SHARES_UNIT, context_key=context)
        result["basic_shares"] = basic_shares
        basic_numerator = source.select(_COMMON["basic"], start, end, _MONEY_UNIT, context_key=context)
        proof_of_unadjusted_diluted_numerator = numerator_proof["basis"] == "SAME_COMMON_ATTRIBUTION_VIA_PARENT_CAL_AND_NORMAL_DILUTION"
        if basic_numerator is not None and not proof_of_unadjusted_diluted_numerator:
            basic_eps = _required(source, _EPS["basic"], start, end, _EPS_UNIT, context_key=context)
            _check_eps(basic_numerator, basic_shares, basic_eps)
            attribution = _common_reported_attribution(
                numerator, basic_numerator, numerator_proof.get("calculations", []), source.calculations(basic_numerator),
            )
            if attribution is None:
                raise QualificationError("DILUTED_NUMERATOR_ADJUSTMENT_BASIS_NOT_PROVEN", evidence=numerator_proof)
            result["common_attribution"] = attribution
        if basic_numerator is None and numerator_proof["basis"] != "REPORTED_PARENT_NET_INCOME_EPS_SOURCE_BLOCK":
            # Exact diluted common attribution is admissible, but without a
            # bridge to parent and basic it does not prove zero adjustment.
            parent = source.select(_NET, start, end, _MONEY_UNIT, context_key=context)
            if parent is None or not any(
                c.get("status") == "VERIFIED" and len(c["children"]) == 1
                and c["children"][0]["component"]["selected_fact_id"] == parent.source["fact_id"]
                and Decimal(c["children"][0]["weight"]) == 1
                for c in numerator_proof["calculations"]
            ):
                raise QualificationError("DILUTED_NUMERATOR_ADJUSTMENT_BASIS_NOT_PROVEN")
        result["control"], result["control_proof"] = _continuing_control(source, start, end, context)
    return result


def _period_evidence(period: dict) -> dict:
    return {key: value.evidence() if isinstance(value, Reported) else value for key, value in period.items()}


def reconstruct_window(*, fy: FilingInputs, nine_month: FilingInputs, preceding: list[tuple[FilingInputs, str, str]],
                       flavor: str, start: str, q4_start: str, end: str, direct_eps: dict | None = None) -> dict:
    """Validate the normal CAL-supported cumulative route for one fiscal window."""
    annual = _period_components(fy, flavor, start, end)
    nine = _period_components(nine_month, flavor, start, q4_start)
    # A positive quarterly numerator prevents a loss-period share population
    # from entering the normal dilution route.
    control_quarters = []
    if flavor == "diluted":
        controls = (annual["control"].interval, nine["control"].interval)
        if any(x[0] <= 0 for x in (*controls, _sub(*controls))):
            raise QualificationError("CONTINUING_OPERATIONS_CONTROL_NONPOSITIVE_OR_UNCERTAIN")
        if len(preceding) != 3:
            raise QualificationError("PRECEDING_QUARTER_CONTINUING_CONTROL_NOT_PROVEN")
        for source, quarter_start, quarter_end in preceding:
            control, proof = _continuing_control(source, quarter_start, quarter_end)
            if control.interval[0] <= 0:
                raise QualificationError("PRECEDING_QUARTER_CONTINUING_CONTROL_NONPOSITIVE_OR_UNCERTAIN")
            control_quarters.append({"accession": source.projection["filing"]["accession"], "control": control.evidence(), "proof": proof})
    a, b, c = _weights({"fy_start": start, "q4_start": q4_start, "fy_end": end}, "DAY")
    ni = _sub(annual["numerator"].interval, nine["numerator"].interval)
    wi = _mul(_sub(_mul(annual["shares"].interval, a), _mul(nine["shares"].interval, b)), Decimal(1) / c)
    n = annual["numerator"].value - nine["numerator"].value
    w = (annual["shares"].value * a - nine["shares"].value * b) / c
    if w <= 0 or wi[0] <= 0:
        raise QualificationError("WEIGHTED_AVERAGE_SHARE_DENOMINATOR_NONPOSITIVE_OR_UNCERTAIN")
    if flavor == "diluted":
        if ni[0] <= 0:
            raise QualificationError("Q4_COMMON_NUMERATOR_NONPOSITIVE_OR_UNCERTAIN")
        basic_q4 = _mul(_sub(_mul(annual["basic_shares"].interval, a), _mul(nine["basic_shares"].interval, b)), Decimal(1) / c)
        if basic_q4[0] <= 0 or wi[1] < basic_q4[0]:
            raise QualificationError("Q4_DILUTED_SHARES_BELOW_BASIC_OR_BASIC_NONPOSITIVE", fail=True)
    iv, point = _div(ni, wi), n / w
    comparison = {"status": "REFERENCE_UNAVAILABLE"}
    value, selected_interval, source_type = str(point), [str(x) for x in iv], "DERIVED_Q4_EPS"
    if direct_eps is not None:
        if not _overlap(iv, [Decimal(v) for v in direct_eps["interval"]]):
            raise QualificationError("DIRECT_Q4_EPS_ROUNDING_MISMATCH", fail=True)
        comparison = {"status": "ROUNDING_COMPATIBLE", "reported_interval": direct_eps["interval"],
                      "derived_interval": [str(v) for v in iv], "reference_fact_keys": direct_eps["fact_keys"]}
        value, selected_interval, source_type = direct_eps["value"], direct_eps["interval"], "REPORTED_Q4_EPS"
    return {"value": value, "reconstructed_value": str(point), "selected_eps_interval": selected_interval,
            "eps_interval": [str(v) for v in iv], "numerator": str(n), "numerator_interval": [str(v) for v in ni],
            "weighted_shares": str(w), "weighted_shares_interval": [str(v) for v in wi],
            "weight_method": "DAY", "weights": [str(a), str(b), str(c)], "direct_comparison": comparison,
            "selected_source_type": source_type, "rounding_status": "SOURCE_DECIMALS_INTERVAL_PROPAGATED",
            "source_calculation_evidence": {"FY": _period_evidence(annual), "9M": _period_evidence(nine),
                                            "preceding_quarter_controls": control_quarters},
            "formula": "(FY_COMMON_NUMERATOR - 9M_COMMON_NUMERATOR) / ((FY_WAVG * FY_DAYS - 9M_WAVG * 9M_DAYS) / Q4_DAYS)"}
