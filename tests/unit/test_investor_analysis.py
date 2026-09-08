"""No network or Layer1 access is needed by consumer queries."""
import copy
import json

import pytest

from sec_xbrl.analysis import (
    VERSION,
    _apply_lens_preferences,
    _definition_graph,
    open_analysis,
    stable,
)
from sec_xbrl.analytics.investor_metrics import ratio
from sec_xbrl.history import _write_records


@pytest.fixture
def bundle(tmp_path):
    files = {}
    cell = {"cell_id": "fact", "node_id": "value", "row_id": "revenue", "fiscal_year": 2025,
            "fiscal_quarter": 1, "value": "100", "period_class": "QTD_3M"}
    datasets = {"columns": [{"fiscal_year": 2025, "fiscal_quarter": 1, "period_class": "QTD_3M"}], "core_rows": [{"row_id": "revenue"}],
                "core_cells": [cell], "cells": [cell], "metrics": [],
                "nodes": [{"node_id": "lens", "kind": "LENS", "anchor_row_id": "revenue"},
                          {"node_id": "value", "kind": "VALUE", "value_node_id": None}],
                "edges": [{"parent_id": "lens", "child_id": "value", "periods": [[2025, 1]]}],
                "importance": [{"policy_id": "important-financial-items", "policy_version": "u3-important-items-v1",
                                "parent_id": "lens", "child_id": "value", "fiscal_year": 2025, "fiscal_quarter": 1,
                                "present": True, "amount_rank": 1, "reasons": ["TOP_AMOUNT"], "warnings": [],
                                "presentation_excluded": False, "share_status": "UNAVAILABLE",
                                "share_reason": "NO_REVIEWED_ECONOMIC_DECOMPOSITION"}],
                "trace_" + stable("fact")[0]: [{"cell_id": "fact", "fiscal_year": 2025, "fiscal_quarter": 1, "source_fact_id": "raw"}]}
    for name, records in datasets.items():
        files[name] = {"path": name + ".parquet", **_write_records(tmp_path / (name + ".parquet"), tuple(records))}
    info = {"as_of": "2026-09-06", "review_cutoff": "2026-09-07T12:00:00+00:00", "source_publication": "/not-readable",
            "views": {view: {"files": files} for view in ("AS_FILED", "LATEST_REPORTED")}}
    (tmp_path / "analysis_manifest.json").write_text(json.dumps({"version": VERSION, "publication_id": "p", "companies": {"TEST": info}}))
    return open_analysis(tmp_path)


def test_query_values_null_proxy_trace_and_copy(bundle, monkeypatch):
    import sec_xbrl.analysis as module
    monkeypatch.setattr(module, "_raw_material", lambda *a: pytest.fail("raw query"))
    d = bundle.overview("TEST", fiscal_start=2025, fiscal_end=2025)
    result = bundle.children("lens", context=d["context"])
    assert result["cells"][0]["value"] == "100"
    assert bundle.trace("fact", context=d["context"])["trace"]["source_fact_id"] == "raw"
    result["cells"][0]["value"] = "999"
    assert bundle.children("lens", context=d["context"])["cells"][0]["value"] == "100"


def test_importance_all_cursor_scope_and_status(bundle):
    context = bundle.overview("TEST")["context"]
    result = bundle.children("lens", context=context, selection="important", reference_period=(2025, 1))
    assert result["children"][0]["importance_reasons"] == ["TOP_AMOUNT"]
    assert result["importance_policy"]["legacy_fallback"] is False
    assert bundle.children("lens", context=context, selection="all")["children"]
    assert bundle.target_status("TEST")["status"] == "READY"
    with pytest.raises(ValueError, match="malformed cursor"):
        bundle.children("lens", context=context, cursor="not-json")
    with pytest.raises(ValueError, match="reference period"):
        bundle.children("lens", context=context, reference_period=(2024, 1))


def test_amount_change_rank_alone_does_not_enter_default(bundle):
    row = bundle._records("TEST", "LATEST_REPORTED", "importance")[0]
    row.update(amount_rank=None, amount_change_rank=1, reasons=["TOP_AMOUNT_CHANGE"])
    context = bundle.overview("TEST")["context"]
    assert bundle.children("lens", context=context)["children"] == []
    assert bundle.children("lens", context=context, selection="all")["children"][0]["importance_reasons"] == ["TOP_AMOUNT_CHANGE"]


def test_legacy_bundle_fallback_is_explicit(bundle):
    del bundle.manifest["companies"]["TEST"]["views"]["LATEST_REPORTED"]["files"]["importance"]
    result = bundle.children("lens", context=bundle.overview("TEST")["context"])
    assert result["importance_policy"]["legacy_fallback"] is True
    assert result["children"][0]["importance"] is None


def test_missing_reference_uses_latest_historical_rank_without_zero_fill(bundle):
    view = "LATEST_REPORTED"
    bundle._records("TEST", view, "columns").append({"fiscal_year": 2024, "fiscal_quarter": 1, "period_class": "QTD_3M"})
    bundle._records("TEST", view, "nodes").append({"node_id": "former", "kind": "VALUE", "label": "Former major"})
    bundle._records("TEST", view, "edges").append({"parent_id": "lens", "child_id": "former", "periods": [[2024, 1]]})
    bundle._records("TEST", view, "cells").append({"cell_id": "former-cell", "node_id": "former", "row_id": "revenue",
                                                     "fiscal_year": 2024, "fiscal_quarter": 1, "period_class": "QTD_3M", "value": "900"})
    bundle._records("TEST", view, "importance").append({
        "policy_id": "important-financial-items", "policy_version": "u3-important-items-v1", "parent_id": "lens",
        "child_id": "former", "fiscal_year": 2024, "fiscal_quarter": 1, "present": True, "amount_rank": 1,
        "current_cell_id": "former-cell", "reasons": ["TOP_AMOUNT", "USER_PINNED"], "warnings": [], "pinned": True, "presentation_excluded": True,
        "share_status": "UNAVAILABLE", "share_reason": "NO_REVIEWED_ECONOMIC_DECOMPOSITION",
    })
    context = bundle.overview("TEST")["context"]
    result = bundle.children("lens", context=context)
    former = next(row for row in result["children"] if row["node_id"] == "former")
    assert former["importance_reasons"] == ["REFERENCE_PERIOD_UNAVAILABLE_FORMER_TOP_AMOUNT", "USER_PINNED"]
    assert former["importance"]["reference_period_status"] == "UNAVAILABLE"
    assert former["importance"]["ordering_reference_period"] == [2024, 1]
    assert not [cell for cell in result["cells"] if cell["node_id"] == "former" and cell["fiscal_year"] == 2025]


@pytest.mark.parametrize("kwargs", [{"as_of": "2025-01-01"}, {"review_cutoff": "2026-09-06"}, {"fiscal_start": 2023, "fiscal_end": 2025}, {"profile": "unknown"}])
def test_scope_rejected(bundle, kwargs):
    with pytest.raises(ValueError):
        bundle.overview("TEST", **kwargs)


def test_context_cycle_and_edge_period(bundle):
    context = bundle.overview("TEST")["context"]
    with pytest.raises(ValueError):
        bundle.children("lens", context=context, path=("lens",))
    stale = copy.deepcopy(context)
    stale["periods"] = [[2024, 1]]
    with pytest.raises(ValueError):
        bundle.children("lens", context=stale)
    bundle._records("TEST", "LATEST_REPORTED", "edges")[0]["periods"] = [[2024, 1]]
    assert not bundle.children("lens", context=context)["cells"]


def metric_pair():
    current = {"row_id": "revenue", "column_id": "q", "cell_id": "a", "fiscal_year": 2025, "fiscal_quarter": 1,
               "period_class": "QTD_3M", "status": "REPORTED", "value": "120", "unit": ['["iso4217:USD"]', '[]'],
               "monetary": True, "comparison_scope": "REPORTED_ARITHMETIC_ONLY_V1:revenue", "basis_version": None,
               "dimensions": [], "selection_view": "LATEST_REPORTED", "as_of": "2026-09-06", "ticker": "TEST",
               "semantic_id": "revenue", "start": "2025-01-01", "end": "2025-04-01"}
    prior = {**current, "cell_id": "b", "value": "100", "fiscal_year": 2024, "start": "2024-01-01", "end": "2024-04-01"}
    return current, prior


def test_arithmetic_does_not_promote_null_basis():
    a, b = metric_pair()
    value = ratio(a, b, metric="YOY", growth=True)
    assert value["value"] == "20.0"
    assert value["source_basis_version"] is None
    assert value["comparability"] == "REPORTED_VALUES_NOT_RECAST_VALIDATED"
    assert value["warning"] == "ACTUAL_DURATION_DIFFERS"


@pytest.mark.parametrize("field,value", [("monetary", False), ("unit", [None, None]), ("dimensions", [["extra", "member"]]),
                                          ("basis_version", "other"), ("fiscal_year", 2023), ("value", "0"), ("value", "-1"),
                                          ("start", None), ("end", "2024-12-31")])
def test_metric_unsafe_input_unavailable(field, value):
    a, b = metric_pair()
    b[field] = value
    assert ratio(a, b, metric="YOY", growth=True)["status"] == "UNAVAILABLE"


def test_margin_needs_exact_period_and_primary_role():
    a, b = metric_pair()
    b.update(fiscal_year=2025, start=a["start"], end=a["end"], semantic_id="revenue")
    a.update(row_id="gross_profit", semantic_id="gross")
    for c in (a, b):
        c.update(margin_scope="filing", statement_roles=["income-statement"])
    assert ratio(a, b, metric="GROSS_MARGIN", growth=False)["status"] == "AVAILABLE"
    b["end"] = "2025-04-02"
    assert ratio(a, b, metric="GROSS_MARGIN", growth=False)["reason"] == "INCOMPATIBLE_ACTUAL_PERIOD"


def test_def_target_role_deep_cycle_and_full_scope():
    dims = [["axis", "member", None, "EXPLICIT", "false"]]
    core = [{"node_id": "core", "cell_id": "core", "column_id": "q", "row_id": "revenue", "period_class": "QTD_3M"}]
    cells = [{"cell_id": "fact", "node_id": "value", "column_id": "q", "fiscal_year": 2025, "fiscal_quarter": 1}]
    traces = [{"cell_id": c, "value_lineage": {"source_filing_id": "filing", "raw_concept_id": "revenue", "raw_dimension_signature": d}}
              for c, d in (("core", []), ("fact", dims))]
    def rel(a, b, role, arc, target=None):
        return {"network_type": "DEF", "filing_id": "filing", "role_uri": role, "from_raw_concept_id": a,
                "to_raw_concept_id": b, "arcrole": "x/" + arc, "target_role_uri": target, "relationship_id": a + b}
    relationships = [rel("revenue", "cube", "A", "all", "B"), rel("cube", "axis", "B", "hypercube-dimension"),
                     rel("axis", "domain", "B", "dimension-domain"), rel("domain", "nested", "B", "domain-member"),
                     rel("nested", "member", "B", "domain-member"), rel("member", "domain", "B", "domain-member")]
    nodes, edges = {}, []
    _definition_graph(core, cells, traces, nodes, relationships, {}, lambda *a: edges.append(a), ticker="TEST", view="LATEST_REPORTED")
    assert len(edges) >= 6
    assert any(e[1] == "value" for e in edges)
    assert all(e[3] == [2025, 1] for e in edges)
    relationships[0]["arcrole"] = "x/notAll"
    edges.clear()
    _definition_graph(core, cells, traces, nodes, relationships, {}, lambda *a: edges.append(a), ticker="TEST", view="LATEST_REPORTED")
    assert not edges


@pytest.mark.parametrize("stale", [False, True, "new_accession"])
def test_refresh_preserves_decisions_or_registration(tmp_path, monkeypatch, stale):
    from datetime import date

    from sec_xbrl import company_reports as reports
    from sec_xbrl.longitudinal import disclosure_review as review
    old = tmp_path / "old"
    old.mkdir()
    (old / "review_manifest.json").write_text("{}")
    reports.register_company(tmp_path, ticker="AMD", publication=old)
    original = (tmp_path / "companies.csv").read_bytes()
    intake = tmp_path / "intake.json"
    intake.write_text(json.dumps({"filings": [{"ticker": "AMD", "filing": {"accession": "a"}}]}))
    monkeypatch.setattr(reports.history, "discover_history", lambda **k: tmp_path / "plan")
    monkeypatch.setattr(reports.history, "ingest_history", lambda **k: tmp_path / "intake")
    def build(**kwargs):
        target = kwargs["output_root"] / "panels"
        target.mkdir(parents=True)
        source = intake
        if stale == "new_accession":
            source = target / "new_intake.json"
            source.write_text(json.dumps({"filings": [{"ticker": "AMD", "filing": {"accession": a}} for a in ("a", "b")]}))
        (target / "history_manifest.json").write_text(json.dumps({"source_intake": str(source)}))
        return target
    monkeypatch.setattr(reports.history, "build_history", build)
    class Old:
        def __init__(self, root):
            assert root == old
            self.manifest = {"source_intake": str(intake)}
        def records(self, name):
            return [{"kept": name}]
    monkeypatch.setattr(review, "ReviewedPublicationReader", Old)
    def republish(**kwargs):
        assert stale != "new_accession", "new filing must not reach automatic review publication"
        assert kwargs["previous_publication"] == old
        assert kwargs["decisions"] == [{"kept": "decisions"}]
        assert kwargs["quality_decisions"] == [{"kept": "quality_decisions"}]
        if stale:
            raise ValueError("stale source candidate")
        return kwargs["destination"]
    monkeypatch.setattr(review, "publish_review", republish)
    monkeypatch.setattr(reports, "report", lambda *a, **k: tmp_path / "report")
    if stale:
        with pytest.raises(ValueError, match="previous registration preserved"):
            reports.refresh(tmp_path, workspace=tmp_path / "work", as_of=date(2026, 9, 8), review_as_of=date(2026, 9, 8))
        assert (tmp_path / "companies.csv").read_bytes() == original
        assert len(list((tmp_path / "work").rglob("review_refresh_required.json"))) == 1
        if stale == "new_accession":
            queue = json.loads(next((tmp_path / "work").rglob("review_refresh_required.json")).read_text())
            assert queue["new_accessions_requiring_review"] == ["b"]
    else:
        reports.refresh(tmp_path, workspace=tmp_path / "work", as_of=date(2026, 9, 8), review_as_of=date(2026, 9, 8))
        assert "reviewed" in (tmp_path / "companies.csv").read_text()


def test_refresh_returns_openable_bundle_boundary(tmp_path, monkeypatch):
    from datetime import date

    from sec_xbrl import analysis, company_reports
    calls = []
    monkeypatch.setattr(company_reports, "refresh", lambda *a, **k: calls.append("build"))
    monkeypatch.setattr(analysis, "prepare_catalog", lambda **k: (calls.append("prepare"), tmp_path / "bundle")[1])
    assert analysis.refresh_analysis(admin=tmp_path, workspace=tmp_path, as_of=date(2026, 9, 8), review_as_of=date(2026, 9, 8)) == tmp_path / "bundle"
    assert calls == ["build", "prepare"]


def test_catalog_bom_registration_and_query_pointer(bundle, tmp_path, monkeypatch):
    import shutil

    from sec_xbrl import analysis, company_reports
    catalog = tmp_path / "catalog"
    company_reports.register_company(catalog, ticker="TEST", publication=tmp_path / "source", fiscal_start=2025, fiscal_end=2025)
    def prepare(**kwargs):
        destination = kwargs["destination"]
        destination.mkdir(parents=True)
        for source in bundle.root.glob("*.parquet"):
            shutil.copyfile(source, destination / source.name)
        manifest = copy.deepcopy(bundle.manifest)
        manifest["source_manifest_hashes"] = {"history_manifest_sha256": "h"}
        (destination / "analysis_manifest.json").write_text(json.dumps(manifest))
        assert kwargs["fiscal_start"] == kwargs["fiscal_end"] == 2025
        return destination
    monkeypatch.setattr(analysis, "prepare_analysis", prepare)
    destination = tmp_path / "combined"
    analysis.prepare_catalog(catalog=catalog, destination=destination)
    assert analysis.open_analysis(catalog).overview("TEST")["cells"][0]["value"] == "100"
    assert company_reports.read_target_status(catalog, ticker="TEST")["status"] == "READY"


def test_registered_target_status_is_explicit_before_preparation(tmp_path):
    from sec_xbrl import company_reports
    company_reports.register_company(tmp_path, ticker="NEW", fiscal_start=2024, fiscal_end=2025)
    assert company_reports.read_target_status(tmp_path, ticker="new") == {
        "ticker": "NEW", "status": "NOT_PREPARED", "reason": "REGISTERED_COLLECTION_TARGET", "evidence": None,
    }
    with pytest.raises(ValueError):
        company_reports.set_target_status(tmp_path, ticker="NEW", status="DISCLOSURE_MISSING", reason="missing")
    company_reports.set_target_status(tmp_path, ticker="NEW", status="DISCLOSURE_MISSING", reason="checked eligible range",
                                      evidence={"publication": "/immutable", "periods": [[2024, 1]]})
    assert company_reports.read_target_status(tmp_path, ticker="NEW")["status"] == "DISCLOSURE_MISSING"


def test_status_read_is_non_mutating_and_prepare_failure_is_persisted(tmp_path, monkeypatch):
    from sec_xbrl import analysis, company_reports
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        company_reports.read_target_status(empty, ticker="NONE")
    assert list(empty.iterdir()) == []
    catalog = tmp_path / "catalog"
    source = tmp_path / "source"
    source.mkdir()
    company_reports.register_company(catalog, ticker="FAIL", publication=source)
    assert company_reports.read_target_status(catalog, ticker="FAIL")["status"] == "NOT_PREPARED"
    monkeypatch.setattr(analysis, "prepare_analysis", lambda **kwargs: (_ for _ in ()).throw(ValueError("bad source")))
    with pytest.raises(ValueError, match="bad source"):
        analysis.prepare_catalog(catalog=catalog, destination=tmp_path / "bundle")
    outcome = company_reports.read_target_status(catalog, ticker="FAIL")
    assert outcome["status"] == "PREPARATION_FAILED"
    assert outcome["reason"] == "bad source"


def test_exact_axis_and_node_display_preferences_do_not_change_relationships():
    nodes = {name: {"node_id": name, "kind": "LENS", "lens_type": "DIMENSIONAL_VIEW", "label": name,
                    "dimensions": axes, "basis_version": None, "anchor_row_id": "revenue"}
             for name, axes in (("product", ["ProductAxis"]), ("region", ["GeographyAxis"]),
                                ("internal", ["ConsolidationAxis"]), ("combined", ["ProductAxis", "ConsolidationAxis"]))}
    before = copy.deepcopy(nodes)
    _apply_lens_preferences(nodes, [
        {"match": {"lens_type": "DIMENSIONAL_VIEW", "axis_signature": ["ProductAxis"]}, "display_order": 10, "label": "제품별"},
        {"match": {"node_id": "region"}, "display_order": 20, "label": "지역별"},
        {"match": {"axis_signature": ["ConsolidationAxis"]}, "display_order": 90},
    ])
    assert nodes["product"]["label"] == "제품별"
    assert nodes["region"]["label"] == "지역별"
    assert nodes["internal"]["display_order"] == 90
    assert nodes["combined"] == before["combined"]
    for key, node in nodes.items():
        assert {k: v for k, v in node.items() if k not in {"label", "display_order"}} == {k: v for k, v in before[key].items() if k != "label"}
    assert set(nodes) == set(before)


@pytest.mark.parametrize("signature", ["ProductAxis", ["ProductAxis", "ProductAxis"], [None]])
def test_malformed_axis_preferences_rejected(signature):
    with pytest.raises(ValueError, match="axis_signature"):
        _apply_lens_preferences({}, [{"match": {"axis_signature": signature}, "label": "bad"}])
