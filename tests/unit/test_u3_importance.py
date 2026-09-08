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
    parents = [row for row in parents if row["fiscal_year"] == 2026]
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
