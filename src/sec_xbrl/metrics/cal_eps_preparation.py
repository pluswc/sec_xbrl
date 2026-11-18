"""Offline preparation of a current EPS extension beside accepted quarter evidence."""

from __future__ import annotations

import zipfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from lxml import html

from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.metrics.cal_eps import (
    CAL_EPS_RULE,
    FilingInputs,
    QualificationError,
    reconstruct_window,
)
from sec_xbrl.metrics.cal_eps_source import SCHEMA as FILING_SCHEMA
from sec_xbrl.metrics.market_inputs import identity
from sec_xbrl.metrics.q4_eps_reconstruction import (
    MODE,
    RULE,
    SOURCE_KIND,
    _accepted_projection,
    _aware,
    _basis_bridge,
    _days,
    _json,
    _now,
    _select,
    _selection_index,
    _source_keys,
    _source_namespace,
    _text,
    _verify_once,
    _verify_projection_closure,
    _visible,
    _xpath,
    verify_q4_eps,
)

RUN_SCHEMA = "common-q4-eps-cal-run-v1"
ARTIFACT_SCHEMA = "governed-common-q4-eps-v2"


def _original_end(filing: dict) -> str:
    return (date.fromisoformat(filing["report_date"]) + timedelta(days=1)).isoformat()


class _AccessionSources:
    def __init__(self, proposal: dict, catalog: dict) -> None:
        self.filings = defaultdict(list)
        self.pins = {}
        self.snapshots = {(s["snapshot_id"].split(":")[1], s["snapshot_id"].split(":")[2]): s
                          for s in proposal["snapshots"]}
        self.raw_filings = {}
        for filing in proposal["source_filings"]:
            key = (filing["cik"], filing["accession"])
            self.raw_filings[key] = filing
            if filing["form"] in {"10-K", "10-Q"} and filing["report_date"]:
                self.filings[(filing["cik"], _original_end(filing))].append(filing)
        for entry in catalog["filings"]:
            key = (entry["cik"], entry["accession"])
            if key in self.pins or key not in self.raw_filings:
                raise ValueError("CAL EPS catalog must have unique accession keys in the registered projection")
            self.pins[key] = entry["projection"]
        self.used = {}

    def load(self, filing: dict) -> FilingInputs:
        key = (filing["cik"], filing["accession"])
        pin = self.pins.get(key)
        if pin is None:
            raise QualificationError("ORIGINAL_ACCESSION_CAL_SOURCE_NOT_PREPARED")
        projection = _json(pin)
        snapshot = self.snapshots.get((key[0], key[1].replace("-", "")))
        raw_filing = {k: v for k, v in filing.items() if k != "ticker"}
        if (projection.get("schema_version") != FILING_SCHEMA
            or projection["filing"] != raw_filing or projection["snapshot"] != snapshot
            or projection["package"]["sha256"] != raw_filing["package_hash"]):
            raise ValueError("CAL EPS projection does not bind to registered immutable Raw")
        self.used[key] = pin
        return FilingInputs(projection, source_labels=_SourceRowLabels(projection))

    def original(self, cik: str, end: str, form: str, latest: str) -> dict | None:
        found = [f for f in self.filings[cik, end] if f["form"] == form and f["filed_date"] <= latest]
        if len(found) > 1:
            raise QualificationError("ORIGINAL_CURRENT_FOCUS_ACCESSION_AMBIGUOUS")
        return found[0] if found else None

    def validate_used(self) -> None:
        for pin in self.used.values():
            projection = _json(pin)
            _verify_once(projection["package"])
            snapshot = projection["snapshot"]
            _verify_once(snapshot["manifest"])
            parent = Path(snapshot["manifest"]["path"]).parent
            for table, sha in snapshot["table_sha256"].items():
                _verify_once({"path": str(parent / (table + ".parquet")), "sha256": sha})


class _SourceRowLabels:
    def __init__(self, projection: dict) -> None:
        self.projection = projection
        self.documents = {}
        self.concepts = {c["raw_concept_id"]: c for c in projection["concepts"]}

    def __call__(self, fact: dict) -> list[dict]:
        table = fact.get("source_table") or {}
        inline_id = table.get("inline_id")
        if not inline_id:
            return []
        package = self.projection["package"]
        document_name = fact["source_document"]
        if document_name not in self.documents:
            _verify_once(package)
            with zipfile.ZipFile(package["path"]) as archive:
                names = [n for n in archive.namelist() if Path(n).name == document_name]
                if len(names) != 1:
                    return []
                self.documents[document_name] = html.fromstring(archive.read(names[0]))
        document = self.documents[document_name]
        nodes = document.xpath("//*[@id=$id]", id=inline_id)
        if len(nodes) != 1:
            return []
        node = nodes[0]
        name = node.get("name", "").split(":")
        concept = self.concepts[fact["raw_concept_id"]]
        filing_id = self.projection["filing"]["filing_id"]
        context_id = _stable_id("context", filing_id, node.get("contextref"))
        if (str(node.tag).split(":")[-1].lower() != "nonfraction" or len(name) != 2
            or name[1] != concept["local_name"] or _source_namespace(node, name[0]) != concept["namespace_uri"]
            or fact["context_id"] != context_id or not _visible(node)):
            return []
        rows = node.xpath("ancestor::tr[1]")
        if not rows:
            return []
        row = rows[0]
        cells = row.xpath("./td|./th")
        fact_cell = next((c for c in node.iterancestors() if c.getparent() is row), None)
        if fact_cell not in cells:
            return []
        # Row label and the applicable nearby header cover both table
        # orientations without interpreting any numeric cell or fitting values.
        labels = [c for c in cells[:cells.index(fact_cell)] if not c.xpath(".//*[@contextref]")]
        offset = sum(int(c.get("colspan", "1")) for c in cells[:cells.index(fact_cell)])
        for header_row in list(row.itersiblings(preceding=True))[:4]:
            position = 0
            for cell in header_row.xpath("./td|./th"):
                width = int(cell.get("colspan", "1"))
                if position <= offset < position + width and not cell.xpath(".//*[@contextref]"):
                    labels.append(cell)
                position += width
        return [{"source_document": document_name, "source_inline_id": inline_id, "source_xpath": _xpath(label),
                 "text": _text(label)} for label in labels if _text(label) and _visible(label)]


def _preceding(sources: _AccessionSources, annual: dict, nine: dict, start: str, end: str) -> list:
    cik = annual["cik"]
    interims = sorted(
        [f for (company, day), filings in sources.filings.items() if company == cik and start < day < end
         for f in filings if f["form"] == "10-Q" and f["filed_date"] <= nine["filed_date"]],
        key=_original_end,
    ) + [nine]
    quarters = []
    for filing in interims:
        stop = _original_end(filing)
        if not 75 <= _days(start, stop) <= 105:
            raise QualificationError("PRECEDING_FISCAL_QUARTER_BOUNDARIES_INCOMPATIBLE")
        quarters.append((sources.load(filing), start, stop))
        start = stop
    return quarters


def _current_window_candidates(proposal: dict, grants: dict) -> list[dict]:
    # Proposals inventory dates only. Accession-local selections are rebuilt
    # from original current-focus filings, independent of comparative picks.
    return [
        c for c in proposal["candidates"] if not c["dimensions"] and c["cik"] in grants
        and 0 <= _days(c["fy_end"], grants[c["cik"]]["financial_anchor"]) <= 300
    ]


def _reported_reference(index: dict, candidate: dict) -> dict | None:
    selected = _select(index, candidate["cik"], candidate["q4_start"], candidate["fy_end"],
                       candidate["flavor"] + "_eps", [])
    if selected["status"] == "HOLD":
        raise QualificationError("DIRECT_Q4_EPS:" + selected["reason"])
    if selected["status"] == "MISSING":
        return None
    return {"value": selected["value"], "interval": selected["interval"],
            "fact_keys": _source_keys({"reference": selected})}


def _selected_proof_rows(result: dict, annual: FilingInputs, nine: FilingInputs) -> set[str]:
    keys = set(result["direct_comparison"].get("reference_fact_keys", ()))
    for name, filing in (("FY", annual), ("9M", nine)):
        snapshot = filing.projection["snapshot"]["snapshot_id"]
        evidence = result["source_calculation_evidence"][name]
        keys.update(snapshot + ":" + r["fact_id"] for k in ("eps", "numerator", "shares") for r in evidence[k]["facts"])
    return keys


def _quarter_result(candidate: dict, sources: _AccessionSources, selection: dict) -> dict:
    result = {k: candidate[k] for k in ("cik", "ticker", "flavor", "fy_start", "q4_start", "fy_end", "dimensions")}
    result.update(candidate_id="cal-q4-eps-candidate-" + identity(result), status="HOLD", value=None,
                  reason=None, source_fact_keys=[], reported_or_derived="DERIVED",
                  rule_version=RULE, source_validation_rule_version=CAL_EPS_RULE,
                  route="CUMULATIVE_COMPONENT_RECONSTRUCTION")
    cik, start, mid, end = (result[k] for k in ("cik", "fy_start", "q4_start", "fy_end"))
    try:
        annual = sources.original(cik, end, "10-K", "9999-12-31")
        nine = sources.original(cik, mid, "10-Q", annual["filed_date"]) if annual else None
        if not (annual and nine and annual["document_fiscal_period_focus"] == "FY"
                and nine["document_fiscal_period_focus"] == "Q3" and nine["filed_date"] < annual["filed_date"]):
            raise QualificationError("COHERENT_ORIGINAL_FY_AND_Q3_VINTAGE_NOT_AVAILABLE")
        source_fy, source_9m = sources.load(annual), sources.load(nine)
        preceding = _preceding(sources, annual, nine, start, mid) if result["flavor"] == "diluted" else []
        reconstructed = reconstruct_window(
            fy=source_fy, nine_month=source_9m, preceding=preceding, flavor=result["flavor"],
            start=start, q4_start=mid, end=end, direct_eps=_reported_reference(selection, candidate),
        )
    except QualificationError as exc:
        return dict(result, status=exc.status, reason=str(exc),
                    **({"source_calculation_diagnostic": exc.evidence} if exc.evidence else {}))
    return dict(result, **reconstructed, status="QUALIFIED", reason=None,
                source_fact_keys=sorted(_selected_proof_rows(reconstructed, source_fy, source_9m)),
                source_accessions={"FY": annual["accession"], "9M": nine["accession"]},
                source_equation_status="VERIFIED", component_validation_status="VALIDATED",
                known_on=annual["filed_date"])


def _exact_ttm(proposal: dict, row: dict, anchor: str, filings: _AccessionSources,
               selection: dict, rows_for_company: list[dict]) -> list[dict]:
    if row["fy_end"] > anchor:
        return []
    q4 = {"start": row["q4_start"], "end": row["fy_end"], "value": row["value"],
          "interval": row["selected_eps_interval"], "source_type": row["selected_source_type"],
          "candidate_id": row["candidate_id"], "source_fact_keys": row["source_fact_keys"]}
    older, newer = [], []
    start, end = row["q4_start"], row["fy_end"]
    for _ in range(3):
        forward = end < anchor
        period = sorted({(r["start"], r["end"]) for r in rows_for_company if r["role"] == "diluted_eps"
                        and not r["dimensions"] and r["form"] == "10-Q"
                        and (r["start"] == end and r["end"] <= anchor if forward else r["end"] == start)
                        and 75 <= _days(r["start"], r["end"]) <= 105 and r["end"] == _original_end(r)})
        if len(period) != 1:
            return []
        a, b = period[0]
        filing = filings.original(row["cik"], b, "10-Q", proposal["public_cutoff"])
        if filing is None:
            return []
        items = selection.get((row["cik"], a, b, "diluted_eps", b"[]"), [])
        selected = _select([p for p in items if p["accession"] == filing["accession"]],
                           row["cik"], a, b, "diluted_eps", [])
        if selected["status"] != "AVAILABLE":
            return []
        entry = {"start": a, "end": b, "value": selected["value"], "interval": selected["interval"],
                 "source_type": "REPORTED_QTD_EPS", "source_fact_keys": _source_keys({"eps": selected})}
        if forward:
            newer.append(entry)
            end = b
        else:
            older.insert(0, entry)
            start = a
    return [*older, q4, *newer] if end == anchor and 350 <= _days(start, end) <= 378 else []


def _basis(proposal: dict, row: dict, grant: dict, selected_raw_rows: list[dict]) -> dict:
    names = ("stock_class_id", "split_basis_id", "financial_scope_id")
    reviewed = {n: grant[n] for n in names}
    reviewed["claims"] = [{"claim": "SOURCE_REPORTING_BASIS_REVIEW_SUPPORTED"}]
    return _basis_bridge(proposal, dict(row, accounting_evidence=reviewed), grant,
                         selected_raw_rows, proposal["public_cutoff"])


def _ttm_output(*, row: dict, quarters: list[dict], grant: dict, sources: list[dict],
                run: dict, basis: dict, prepared: str) -> dict:
    value = sum(Decimal(q["value"]) for q in quarters)
    interval = [str(sum(Decimal(q["interval"][i]) for q in quarters)) for i in range(2)]
    output = {"role": "diluted_eps_12m", "cik": row["cik"], "ticker": row["ticker"],
              "currency": grant["currency"], "scope_id": grant["financial_scope_id"],
              "stock_class_id": grant["stock_class_id"], "split_basis_id": grant["split_basis_id"],
              "known_on": max(s["filed_date"] for s in sources), "period_start": quarters[0]["start"],
              "period_end": quarters[-1]["end"], "period_class": "TTM", "end_convention": "EXCLUSIVE",
              "value": str(value), "eps_interval": interval, "unit_kind": "currency/share",
              "status": "AVAILABLE", "reason": None, "source_kind": SOURCE_KIND, "reported_or_derived": "DERIVED",
              "definition_version": RULE, "formula_id": RULE,
              "source_validation_rule_version": CAL_EPS_RULE,
              "formula": "SUM(FOUR_COMPATIBLE_QTD_EPS_WITH_VERIFIED_Q4_COMPONENTS)",
              "source_refs": quarters, "evidence_pins": [run["policy"], run["filing_catalog"]],
              "q4_candidate_id": row["candidate_id"], "basis_bridge": basis, "historical_ready": False,
              "ready_at": prepared, "ready_on": _aware(prepared).date().isoformat()}
    return dict(output, observation_id="price-financial-input-" + identity(output))


def _coordinate(row: dict) -> tuple:
    return tuple(row[k] for k in ("cik", "flavor", "fy_start", "q4_start", "fy_end"))


def _current_grants(base: dict, cutoff: str) -> dict:
    anchors = defaultdict(list)
    matches = defaultdict(list)
    for anchor in base["financial_anchors"]:
        if anchor["known_on"] <= cutoff:
            anchors[anchor["cik"]].append(anchor["period_end"])
    for grant in base["compatibility_grants"]:
        cik = grant["cik"]
        if anchors[cik] and grant["financial_anchor"] == max(anchors[cik]):
            matches[cik].append(grant)
    return {cik: groups[0] for cik, groups in matches.items() if len(groups) == 1}


def prepare_cal_eps_run(run_pin: dict, *, recorded_at: str | None = None) -> dict:
    """Apply approved global source semantics and prepare an additive current artifact."""
    run = _json(run_pin)
    if run.get("schema_version") != RUN_SCHEMA:
        raise ValueError("unsupported CAL EPS run schema")
    proposal = _json(run["proposal"])
    _accepted_projection(run["proposal"], run["source_projection_acceptance"], proposal)
    base, policy, decision, catalog = (_json(run[k]) for k in
        ("base_financial_bundle", "policy", "evaluation_decision", "filing_catalog"))
    if (policy.get("schema_version"), policy.get("rule_version"), policy.get("reviewer"), policy.get("status")) != (
        "common-q4-eps-cal-policy-v1", CAL_EPS_RULE, "ROOT", "APPROVED_GLOBAL_RULE"
    ) or policy.get("filing_catalog") != run["filing_catalog"] or catalog.get("schema_version") != "cal-eps-filing-catalog-v1":
        raise ValueError("approved global CAL EPS policy and exact source catalog are required")
    cutoff = proposal["public_cutoff"]
    if (decision.get("reviewer"), decision.get("status"), decision.get("mode"),
        decision.get("public_financial_information_cutoff"), decision.get("quote_session")) != (
        "ROOT", "APPROVED_FOR_BOUNDED_IMPLEMENTATION", MODE, cutoff, cutoff
    ):
        raise ValueError("CAL EPS requires an exact current-only evaluation decision")
    prepared = recorded_at or _now().isoformat()
    ready = _aware(prepared)
    if not max(_aware(policy["approved_at"]), _aware(decision["decided_at"])) <= ready <= _now() or (
        ready.astimezone(ZoneInfo(decision.get("evaluation_timezone", "UTC"))).date().isoformat() != decision["evaluation_as_of"]
    ):
        raise ValueError("CAL EPS preparation timestamp is outside the approved current evaluation")
    prior_pin = base.get("q4_component_derivation")
    prior = verify_q4_eps(prior_pin) if prior_pin else {
        "public_cutoff": cutoff, "quarter_results": [], "observations": [], "source_rows": [], "holds": [],
    }
    if prior["public_cutoff"] != cutoff:
        raise ValueError("CAL EPS extension must preserve the prior public cutoff")
    existing = {o["observation_id"]: o for o in base["observations"]}
    if any(existing.get(o["observation_id"]) != o for o in prior["observations"]):
        raise ValueError("CAL EPS base differs from accepted prior Q4 observations")
    existing_quarters = {_coordinate(r) for r in prior["quarter_results"] if r["status"] == "QUALIFIED"}
    originals = _AccessionSources(proposal, catalog)
    source_index = {r["fact_key"]: r for r in proposal["source_rows"]}
    selection = _selection_index(proposal["source_rows"])
    by_cik = defaultdict(list)
    for item in proposal["source_rows"]:
        by_cik[item["cik"]].append(item)
    grants = _current_grants(base, cutoff)
    quarter_results, new_observations, holds, verified_keys = [], [], [], set()
    with localcontext() as ctx:
        ctx.prec = 80
        for candidate in _current_window_candidates(proposal, grants):
            if _coordinate(candidate) in existing_quarters:
                continue
            row = _quarter_result(candidate, originals, selection)
            quarter_results.append(row)
            if row["status"] != "QUALIFIED":
                continue
            local_rows = [source_index[key] for key in row["source_fact_keys"]]
            row["known_on"] = max(source["filed_date"] for source in local_rows)
            verified_keys.update(row["source_fact_keys"])
            grant = grants[row["cik"]]
            local_basis = _basis(proposal, row, grant, local_rows)
            row.update(local_source_basis=local_basis, source_basis_status=local_basis["status"])
            if local_basis["status"] != "VERIFIED":
                row.update(status="HOLD", reason=local_basis["reason"], value=None)
                continue
            if row["flavor"] != "diluted" or grant["input_ids"].get("diluted_eps_12m"):
                continue
            try:
                quarters = _exact_ttm(proposal, row, grant["financial_anchor"], originals, selection, by_cik[row["cik"]])
            except QualificationError:
                quarters = []
            if not quarters:
                holds.append({"cik": row["cik"], "candidate_id": row["candidate_id"],
                              "reason": "EXACT_CURRENT_FOUR_QUARTER_WINDOW_NOT_AVAILABLE"})
                continue
            keys = {key for q in quarters for key in q["source_fact_keys"]}
            verified_keys.update(keys)
            ttm_rows = [source_index[key] for key in sorted(keys)]
            basis = _basis(proposal, row, grant, ttm_rows)
            if basis["status"] != "VERIFIED":
                holds.append({"cik": row["cik"], "candidate_id": row["candidate_id"],
                              "reason": basis["reason"], "basis_bridge": basis})
                continue
            new_observations.append(_ttm_output(row=row, quarters=quarters, grant=grant, sources=ttm_rows,
                                               run=run, basis=basis, prepared=prepared))
    conflicts = defaultdict(list)
    for obs in new_observations:
        conflicts[obs["cik"]].append(obs)
    for cik, records in conflicts.items():
        if len(records) != 1:
            holds.extend({"cik": cik, "candidate_id": o["q4_candidate_id"],
                          "reason": "AMBIGUOUS_CURRENT_Q4_TTM_SOURCE"} for o in records)
    new_observations = [o for o in new_observations if len(conflicts[o["cik"]]) == 1]
    originals.validate_used()
    _verify_projection_closure(proposal, verified_keys)
    replaced = {_coordinate(r) for r in quarter_results}
    prior_quarters = [r for r in prior["quarter_results"] if r["dimensions"] or _coordinate(r) not in replaced]
    combined_sources = {r["fact_key"]: r for r in prior["source_rows"]}
    combined_sources.update({k: source_index[k] for k in verified_keys})
    return {"schema_version": ARTIFACT_SCHEMA, "rule_version": RULE, "cal_rule_version": CAL_EPS_RULE,
            "config": run_pin, "source_projection": run["proposal"], "prior_derivation": prior_pin,
            "filing_projection_inventory": [p for _, p in sorted(originals.used.items())],
            "verified_source_fact_keys": sorted(verified_keys),
            "prepared_at": prepared, "public_cutoff": cutoff, "evaluation_decision": run["evaluation_decision"],
            "base_financial_bundle": run["base_financial_bundle"], "quarter_results": prior_quarters + quarter_results,
            "observations": prior["observations"] + new_observations,
            "source_rows": [r for _, r in sorted(combined_sources.items())], "holds": prior["holds"] + holds}


def verify_cal_eps_run(pin: dict, artifact: dict) -> dict:
    """Replay the frozen projection and current calculation without loading a live model."""
    from copy import deepcopy

    from sec_xbrl.metrics.q4_eps_reconstruction import _VERIFIED_ARTIFACT_CACHE, _recheck_pins

    cached = _VERIFIED_ARTIFACT_CACHE.get(pin["sha256"])
    if cached is None:
        if prepare_cal_eps_run(artifact["config"], recorded_at=artifact["prepared_at"]) != artifact:
            raise ValueError("governed CAL EPS extension differs from replay")
        _VERIFIED_ARTIFACT_CACHE[pin["sha256"]] = deepcopy(artifact)
        while len(_VERIFIED_ARTIFACT_CACHE) > 4:
            _VERIFIED_ARTIFACT_CACHE.popitem(last=False)
    else:
        run = _json(artifact["config"])
        if artifact["prior_derivation"]:
            verify_q4_eps(artifact["prior_derivation"])
        _recheck_pins(run)
        _recheck_pins(artifact)
        proposal = _json(run["proposal"])
        accession_sources = _AccessionSources(proposal, _json(run["filing_catalog"]))
        accession_sources.used = dict(enumerate(artifact["filing_projection_inventory"]))
        accession_sources.validate_used()
        _verify_projection_closure(proposal, set(artifact["verified_source_fact_keys"]))
        if _aware(artifact["prepared_at"]) > _now():
            raise ValueError("CAL EPS ready time is future")
        _VERIFIED_ARTIFACT_CACHE.move_to_end(pin["sha256"])
    return deepcopy(artifact)
