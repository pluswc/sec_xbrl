import hashlib
from copy import deepcopy

from sec_xbrl.analytics.importance import POLICY_VERSION, materialize_importance

UNIT = ['["iso4217:USD"]', '[]']


def cell(node, value, year, *, cell_id=None, dimensions=None, status="REPORTED", unit=UNIT):
    return {
        "cell_id": cell_id or f"{node}-{year}", "node_id": node, "row_id": "revenue",
        "column_id": f"q-{year}", "fiscal_year": year, "fiscal_quarter": 3,
        "period_class": "QTD_3M", "value": value, "unit": unit,
        "dimensions": dimensions or [], "basis_version": "basis", "selection_view": "LATEST_REPORTED",
        "as_of": "2026-09-08", "ticker": "TEST", "semantic_id": "revenue", "monetary": True,
        "status": status, "start": f"{year}-01-01", "end": f"{year}-03-31",
        "comparison_scope": "reviewed", "reason": None,
    }


def graph():
    nodes = [{"node_id": "lens", "kind": "LENS", "anchor_row_id": "revenue"}]
    nodes += [{"node_id": f"c{i}", "kind": "VALUE"} for i in range(1, 7)]
    edges = [{"parent_id": "lens", "child_id": f"c{i}", "periods": [[2025, 3], [2026, 3]]} for i in range(1, 7)]
    children = [cell(f"c{i}", str(700 - i * 100), year) for year in (2025, 2026) for i in range(1, 7)]
    parents = [cell("parent", "2100", year, cell_id=f"parent-{year}") for year in (2025, 2026)]
    return nodes, edges, children, parents


def test_amount_rank_is_prepared_and_never_mixes_unit_or_inactive_edge():
    nodes, edges, cells, parents = graph()
    next(row for row in cells if row["node_id"] == "c5" and row["fiscal_year"] == 2026)["unit"] = ['["iso4217:EUR"]', '[]']
    edges[-1]["periods"] = [[2025, 3]]
    rows = materialize_importance(nodes=nodes, edges=edges, cells=cells, core_cells=parents)
    current = {row["child_id"]: row for row in rows if row["fiscal_year"] == 2026}
    assert [current[f"c{i}"]["amount_rank"] for i in range(1, 5)] == [1, 2, 3, 4]
    assert current["c5"]["amount_rank"] is None
    assert current["c6"]["present"] is False
    assert current["c6"]["amount_rank"] is None
    assert current["c5"]["amount_change_rank"] is None
    assert "ABRUPT_RATE_AND_MATERIAL_CHANGE" not in current["c5"]["reasons"]
    assert current["c1"]["policy_version"] == POLICY_VERSION
    assert current["c1"]["share_reason"] == "NO_REVIEWED_ECONOMIC_DECOMPOSITION"


def test_reviewed_share_requires_hash_exact_bindings_scope_and_source_pairs(tmp_path):
    nodes, edges, cells, parents = graph()
    nodes = nodes[:3]
    edges = edges[:2]
    cells = [row for row in cells if row["node_id"] in {"c1", "c2"} and row["fiscal_year"] == 2026]
    parents = [{**row, "value": "1100"} for row in parents if row["fiscal_year"] == 2026]
    evidence = tmp_path / "review.txt"
    evidence.write_text("reviewed complete decomposition")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    traces = [{"cell_id": row["cell_id"], "value_lineage": {"source_filing_id": "filing", "context_start_date": row["start"], "context_end_date": row["end"]}} for row in [*cells, *parents]]
    child_ids = {row["node_id"]: row["cell_id"] for row in cells}
    child_dims = {row["node_id"]: row["dimensions"] for row in cells}
    child_pairs = {row["node_id"]: [["filing", row["start"], row["end"]]] for row in cells}
    binding = {
        "fiscal_year": 2026, "fiscal_quarter": 3, "parent_cell_id": "parent-2026",
        "child_cell_ids": child_ids, "parent_dimensions": [], "child_dimensions": child_dims,
        "parent_source_period_pairs": [["filing", "2026-01-01", "2026-03-31"]],
        "child_source_period_pairs": child_pairs, "actual_start": "2026-01-01", "actual_end": "2026-03-31",
        "period_class": "QTD_3M", "classification_basis": "products",
    }
    rule = {"parent_node_id": "lens", "review_id": "r1", "reviewer": "admin", "reviewed_at": "2026-09-07T00:00:00+00:00",
            "evidence_path": str(evidence), "evidence_sha256": digest, "classification_basis": "products",
            "complete_mutually_exclusive": True, "bindings": [binding]}
    rows = materialize_importance(nodes=nodes, edges=edges, cells=cells, core_cells=parents,
                                  configuration={"economic_decompositions": [rule]}, traces=traces,
                                  review_cutoff="2026-09-08T00:00:00+00:00")
    current = [row for row in rows if row["fiscal_year"] == 2026]
    assert {row["share_status"] for row in current} == {"AVAILABLE"}
    assert {row["decomposition_evidence_sha256"] for row in current} == {digest}
    broken = deepcopy(rule)
    broken["bindings"][0]["child_source_period_pairs"]["c1"] = [["other", "2026-01-01", "2026-03-31"]]
    rows = materialize_importance(nodes=nodes, edges=edges, cells=cells, core_cells=parents,
                                  configuration={"economic_decompositions": [broken]}, traces=traces,
                                  review_cutoff="2026-09-08T00:00:00+00:00")
    assert {row["share_reason"] for row in rows if row["fiscal_year"] == 2026} == {"SOURCE_PERIOD_PAIR_MISMATCH"}

    def reasons(*, changed_cells=cells, changed_parents=parents, rules=(rule,), cutoff="2026-09-08T00:00:00+00:00"):
        produced = materialize_importance(nodes=nodes, edges=edges, cells=changed_cells, core_cells=changed_parents,
                                          configuration={"economic_decompositions": list(rules)}, traces=traces,
                                          review_cutoff=cutoff)
        return {row["share_reason"] for row in produced if row["fiscal_year"] == 2026}

    assert reasons(changed_parents=[{**parents[0], "value": "0"}]) == {"ZERO_OR_NEGATIVE_PARENT"}
    assert reasons(changed_cells=[cells[0], {**cells[1], "value": "-1"}]) == {"OFFSET_CHILD"}
    assert reasons(changed_cells=[cells[0], {**cells[1], "unit": ['["iso4217:EUR"]', '[]']}]) == {"UNIT_MISMATCH"}
    assert reasons(changed_cells=[{**cells[0], "status": "DERIVED"}, cells[1]]) == {"SOURCE_PERIOD_PAIR_MISMATCH"}
    assert reasons(rules=(rule, deepcopy(rule))) == {"DUPLICATE_DECOMPOSITION_REVIEW"}
    assert reasons(cutoff="2026-09-06T00:00:00+00:00") == {"INVALID_REVIEW_EVIDENCE"}

    instant_cells = [{**row, "period_class": "INSTANT", "start": None} for row in cells]
    instant_parents = [{**row, "period_class": "INSTANT", "start": None} for row in parents]
    instant_traces = [{"cell_id": row["cell_id"], "value_lineage": {"source_filing_id": "filing",
                       "context_start_date": None, "context_instant_date": row["end"]}}
                      for row in [*instant_cells, *instant_parents]]
    instant_rule = deepcopy(rule)
    instant_binding = instant_rule["bindings"][0]
    instant_binding.update(actual_start=None, period_class="INSTANT",
                           parent_source_period_pairs=[["filing", None, "2026-03-31"]],
                           child_source_period_pairs={child: [["filing", None, "2026-03-31"]] for child in child_ids})
    instant_rows = materialize_importance(nodes=nodes, edges=edges, cells=instant_cells, core_cells=instant_parents,
                                          configuration={"economic_decompositions": [instant_rule]}, traces=instant_traces,
                                          review_cutoff="2026-09-08T00:00:00+00:00")
    assert {row["share_status"] for row in instant_rows if row["fiscal_year"] == 2026} == {"AVAILABLE"}


def test_change_basis_break_is_critical_and_unknown_basis_is_only_warning():
    nodes, edges, cells, parents = graph()
    changed = next(row for row in cells if row["node_id"] == "c6" and row["fiscal_year"] == 2026)
    changed["comparison_scope"] = "new-basis"
    rows = materialize_importance(nodes=nodes, edges=edges, cells=cells, core_cells=parents)
    current = next(row for row in rows if row["child_id"] == "c6" and row["fiscal_year"] == 2026)
    assert current["change_reason"] == "INCOMPATIBLE_COMPARISON_SCOPE"
    assert "BASIS_WARNING" in current["reasons"]


def share_case(tmp_path, *, quarter=None, start="2026-10-01", end="2027-01-01"):
    """An explicit reviewed decomposition over independently sourced amounts."""
    nodes, edges, cells, parents = graph()
    nodes, edges = nodes[:3], edges[:2]
    cells = [c for c in cells if c["fiscal_year"] == 2026 and c["node_id"] in {"c1", "c2"}]
    parents = [{**c, "value": "1100"} for c in parents if c["fiscal_year"] == 2026]
    traces = []
    for c in [*cells, *parents]:
        c.update(fiscal_quarter=quarter or 1, start=start, end=end, semantic_id=c["node_id"], as_of="2027-02-02")
        source = {'source_filing_id': "filing", 'selected_source_fact_id': c["cell_id"],
                      'company_canonical_concept_id': c["node_id"], 'canonical_dimension_signature': [],
                      'context_start_date': start, 'context_end_date': end, 'source_type': "REPORTED",
                      'unit_numerator_measures': UNIT[0], 'unit_denominator_measures': UNIT[1],
                      'period_class': "QTD_3M", 'value_numeric': c["value"]}
        source.update(cik="0000123456", ticker=c["ticker"], basis_version=c["basis_version"],
                      selection_view=c["selection_view"], selection_as_of_date=c["as_of"])
        if quarter:
            classes = {2: ("YTD_6M", "QTD_3M"), 3: ("YTD_9M", "YTD_6M"), 4: ("FY", "YTD_9M")}[quarter]
            later = {**source, "context_start_date": "2026-01-01", "period_class": classes[0],
                     "source_filing_id": "later", "value_numeric": str(int(c["value"]) + 1000)}
            earlier = {**source, "context_start_date": "2026-01-01", "context_end_date": start,
                       "period_class": classes[1], "source_filing_id": "earlier", "value_numeric": "1000",
                       "selected_source_fact_id": c["cell_id"] + "-earlier"}
            source.update(source_type="DERIVED_QUARTER", reported_or_derived="DERIVED",
                          derivation_rule_version="approved-core-cumulative-difference-v1",
                          semantic_review_state="REVIEWED_ADDITIVE_AMOUNT",
                          policy_registry="CONTROLLED_STANDARD_STATEMENT_ALLOWLIST",
                          formula=" - ".join(classes), source_inputs=[later, earlier])
            c["status"] = "DERIVED"
        traces.append({"cell_id": c["cell_id"], "value_lineage": source})
    for edge in edges:
        edge["periods"] = [[2026, quarter or 1]]
    pairs = sorted([[s["source_filing_id"], s["context_start_date"], s["context_end_date"]]
                    for s in traces[0]["value_lineage"].get("source_inputs", [traces[0]["value_lineage"]])], key=repr)
    binding = {'fiscal_year': 2026, 'fiscal_quarter': quarter or 1, 'parent_cell_id': parents[0]["cell_id"],
                   'child_cell_ids': {c["node_id"]: c["cell_id"] for c in cells}, 'parent_dimensions': [],
                   'child_dimensions': {c["node_id"]: [] for c in cells}, 'parent_source_period_pairs': pairs,
                   'child_source_period_pairs': {c["node_id"]: deepcopy(pairs) for c in cells},
                   'actual_start': start, 'actual_end': end, 'period_class': "QTD_3M", 'classification_basis': "products"}
    evidence = tmp_path / "review.txt"
    evidence.write_text("explicit complete mutually exclusive economic decomposition")
    rule = {'parent_node_id': "lens", 'review_id': "r", 'reviewer': "admin", 'reviewed_at': "2027-02-01T00:00:00Z",
                'evidence_path': str(evidence), 'evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                'classification_basis': "products", 'complete_mutually_exclusive': True, 'bindings': [binding]}
    return {'nodes': nodes, 'edges': edges, 'cells': cells, 'core_cells': parents, 'traces': traces,
                'configuration': {"economic_decompositions": [rule]}, 'review_cutoff': "2027-02-02T00:00:00Z"}


def test_aliases_and_duplicate_raw_scope_cannot_receive_shares(tmp_path):
    base = share_case(tmp_path)
    for kind in ("alias", "fact", "scope", "parent"):
        args = deepcopy(base)
        binding = args["configuration"]["economic_decompositions"][0]["bindings"][0]
        if kind == "alias":
            args["nodes"][2]["value_node_id"] = "c1"
            args["cells"] = args["cells"][:1]
            binding["child_cell_ids"]["c2"] = binding["child_cell_ids"]["c1"]
        elif kind == "parent":
            args["core_cells"].append({**args["core_cells"][0], "cell_id": "ambiguous", "value": "1"})
        elif kind == "fact":
            args["traces"][1]["value_lineage"]["selected_source_fact_id"] = args["traces"][0]["value_lineage"]["selected_source_fact_id"]
        else:
            args["traces"][1]["value_lineage"]["company_canonical_concept_id"] = "c1"
        assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args)), kind


def test_review_schema_and_aware_cutoff_fail_closed(tmp_path):
    base = share_case(tmp_path)
    for key, invalid in (("complete_mutually_exclusive", "false"), ("complete_mutually_exclusive", 1),
                         ("reviewer", " "), ("reviewer", True), ("reviewed_at", "2027-02-01"),
                         ("reviewed_at", "2027-02-03T00:00:00Z"), ("bindings", [None])):
        args = deepcopy(base)
        args["configuration"]["economic_decompositions"][0][key] = invalid
        assert {r["share_reason"] for r in materialize_importance(**args)} == {"INVALID_REVIEW_EVIDENCE"}
    for cutoff in (None, "2027-02-02", "bad"):
        assert {r["share_reason"] for r in materialize_importance(**{**base, "review_cutoff": cutoff})} == {"INVALID_REVIEW_EVIDENCE"}


def test_complete_governed_quarters_and_53_week_q4_recalculate(tmp_path):
    from decimal import Decimal

    for quarter, start, end in ((2, "2026-04-01", "2026-07-01"), (3, "2026-07-01", "2026-10-01"),
                                (4, "2026-10-01", "2027-01-01"), (4, "2026-10-01", "2027-01-08")):
        args = share_case(tmp_path, quarter=quarter, start=start, end=end)
        rows = materialize_importance(**args)
        parent_inputs = args["traces"][-1]["value_lineage"]["source_inputs"]
        parent = Decimal(parent_inputs[0]["value_numeric"]) - Decimal(parent_inputs[1]["value_numeric"])
        for row, trace in zip(rows, args["traces"], strict=False):
            left, right = trace["value_lineage"]["source_inputs"]
            assert row["share_status"] == "AVAILABLE"
            assert Decimal(row["parent_share"]) == (Decimal(left["value_numeric"]) - Decimal(right["value_numeric"])) / parent * 100


def test_derived_share_rejects_invented_or_misaligned_derivations(tmp_path):
    base = share_case(tmp_path, quarter=4)
    for kind in ("display", "formula", "rule", "approval", "status", "order", "count", "fy_fy", "start", "amount", "unit", "dimensions"):
        args = deepcopy(base)
        for trace in args["traces"]:
            line = trace["value_lineage"]
            if kind == "formula": line["formula"] = "FY + YTD_9M"
            elif kind == "rule": line["derivation_rule_version"] = "mechanical-candidate"
            elif kind == "approval": line.pop("semantic_review_state")
            elif kind == "status": line["source_inputs"][0]["source_type"] = "UNAVAILABLE"
            elif kind == "order": line["source_inputs"].reverse()
            elif kind == "count": line["source_inputs"].append(deepcopy(line["source_inputs"][0]))
            elif kind == "fy_fy": line["source_inputs"][1]["period_class"] = "FY"
            elif kind == "start": line["source_inputs"][1]["context_start_date"] = "2026-02-01"
            elif kind == "amount": line["source_inputs"][0]["value_numeric"] = "9999"
            elif kind == "unit": line["source_inputs"][1]["unit_numerator_measures"] = '["iso4217:EUR"]'
            elif kind == "dimensions": line["source_inputs"][1]["canonical_dimension_signature"] = [["axis", "member"]]
        if kind == "display":
            for c in args["cells"] + args["core_cells"]:
                c.update(start="2026-01-01", end="2026-04-01")
            args["configuration"]["economic_decompositions"][0]["bindings"][0].update(actual_start="2026-01-01", actual_end="2026-04-01")
        assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args)), kind


def test_reported_instant_and_reviewed_q4_positive_amounts(tmp_path):
    from decimal import Decimal

    for kind in ("reported", "instant", "reviewed_q4"):
        args = share_case(tmp_path, quarter=4 if kind == "reviewed_q4" else None)
        if kind == "instant":
            for c in args["cells"] + args["core_cells"]:
                c.update(start=None, period_class="INSTANT")
            for trace in args["traces"]:
                line = trace["value_lineage"]
                line.update(context_start_date=None, context_instant_date=line.pop("context_end_date"))
            binding = args["configuration"]["economic_decompositions"][0]["bindings"][0]
            binding.update(actual_start=None, period_class="INSTANT", parent_source_period_pairs=[["filing", None, "2027-01-01"]],
                           child_source_period_pairs={c: [["filing", None, "2027-01-01"]] for c in ("c1", "c2")})
        elif kind == "reviewed_q4":
            for trace in args["traces"]:
                trace["value_lineage"].update(derivation_rule_version="disclosure-review-v1", source_type="DERIVED_METRIC",
                                             value_status="DERIVED", metric_id="QUARTERLY_ADDITIVE_FLOW",
                                             calculation_decision_id="approved-decision", compatibility_result="COMPATIBLE_INPUTS")
        rows = materialize_importance(**args)
        assert [Decimal(r["parent_share"]) for r in rows] == [Decimal(600) / 1100 * 100, Decimal(500) / 1100 * 100]


def test_missing_malformed_or_unbound_source_period_is_unavailable(tmp_path):
    for invalid in ([], [None], "invalid", [{"source_filing_id": None}], [{"source_filing_id": ["bad"]}]):
        args = share_case(tmp_path, quarter=4)
        args["traces"][0]["value_lineage"]["source_inputs"] = invalid
        assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args))
    args = share_case(tmp_path)
    args["traces"][0]["value_lineage"]["context_end_date"] = "2027-02-01"
    binding = args["configuration"]["economic_decompositions"][0]["bindings"][0]
    binding["child_source_period_pairs"]["c1"][0][2] = "2027-02-01"
    assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args))


def test_derived_sources_must_bind_scope_to_lineage_and_compact_output(tmp_path):
    fields = {
        "basis_version": "different-basis", "selection_view": "AS_FILED",
        "selection_as_of_date": "2027-03-01", "company_canonical_concept_id": "different-concept",
        "cik": "9999999999", "ticker": "OTHER", "structural_version": "changed", "recast_version": "changed",
        "unit_numerator_measures": '["iso4217:EUR"]', "unit_denominator_measures": '["shares"]',
        "canonical_dimension_signature": [["axis", "member"]], "analytical_dimensions": [["axis", "member"]],
    }
    for kind in ("core", "reviewed"):
        base = share_case(tmp_path, quarter=4)
        if kind == "reviewed":
            for trace in base["traces"]:
                trace["value_lineage"].update(derivation_rule_version="disclosure-review-v1", source_type="DERIVED_METRIC",
                                             value_status="DERIVED", metric_id="QUARTERLY_ADDITIVE_FLOW",
                                             calculation_decision_id="approved-decision", compatibility_result="COMPATIBLE_INPUTS")
        assert all(r["share_status"] == "AVAILABLE" for r in materialize_importance(**base))
        for key, bad in fields.items():
            for target in ("inputs", "lineage"):
                args = deepcopy(base)
                for trace in args["traces"]:
                    line = trace["value_lineage"]
                    for row in line["source_inputs"] if target == "inputs" else [line]:
                        row[key] = bad
                assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args)), (kind, key, target)
        for key in ("semantic_id", "basis_version", "selection_view", "as_of", "ticker"):
            args = deepcopy(base)
            for c in args["cells"] + args["core_cells"]:
                c[key] = "wrong-output"
            assert all(r["share_status"] == "UNAVAILABLE" for r in materialize_importance(**args)), (kind, key)


def test_reconciliation_requires_exact_sum_and_retains_mismatch_inputs(tmp_path):
    for parent in ("1000", "2100"):
        args = share_case(tmp_path)
        args["core_cells"][0]["value"] = parent
        rows = materialize_importance(**args)
        assert {r["share_reason"] for r in rows} == {"NON_RECONCILING_DECOMPOSITION"}
        for row in rows:
            assert row["share_status"] == "UNAVAILABLE" and row["parent_share"] is None
            assert row["share_parent_value"] == parent
            assert row["share_child_total"] == "1100"
            assert row["share_total_difference"] == str(1100 - int(parent))
            assert row["share_reconciliation_inputs"] == {"c1-2026": "600", "c2-2026": "500"}
            assert row["share_input_cell_ids"][0] == "parent-2026"
        assert args["core_cells"][0]["value"] == parent
        assert [c["value"] for c in args["cells"]] == ["600", "500"]
    args = share_case(tmp_path)
    args["configuration"] = {}
    assert {r["share_reason"] for r in materialize_importance(**args)} == {"NO_REVIEWED_ECONOMIC_DECOMPOSITION"}
