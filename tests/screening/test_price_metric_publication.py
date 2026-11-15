from __future__ import annotations

import copy
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_price_related_metrics import financial, prices, sessions

from examples.screening.prepare_price_metrics import bind_bundle
from sec_xbrl.metrics.market_inputs import encoded, identity
from sec_xbrl.metrics.price_batch import canonical_price_batch
from sec_xbrl.metrics.price_financial_inputs import bind_financial_inputs
from sec_xbrl.screening.price_metric_publication import PriceMetricReader, publish_price_metrics
from sec_xbrl.screening.price_metric_service import PriceMetricService


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


def publication(tmp_path: Path, tag="a", close="100"):
    proof = pin(tmp_path / f"proof-{tag}.json", {"fixture": "approved"})
    calendar = sessions(331)
    assert calendar["sessions"][-1] == "2026-10-23"
    calendar["source_pins"] = [proof]
    source = prices(calendar)
    for p in source:
        p["as_traded_close"] = close
        p["currency"] = "USD"
        p["ready_on"] = None
    p, observations, grant = financial()
    grant["evidence_pins"] = [proof]
    b = pin(tmp_path / f"batch-{tag}.json", {"schema_version": "price-metric-canonical-batch-v1",
        "price_batch_calls": 1, "prices": source, "companies": [{"cik": "0000000001", "ticker": "TEST", "security_id": "US:TEST"}],
        "query": {"start_date": calendar["sessions"][0], "end_date": "2026-10-23"}, "volume_basis": "TRUE_SPLIT_COMPATIBLE"})
    f = pin(tmp_path / f"financial-{tag}.json", {"schema_version": "price-financial-input-bundle-v1",
        "financial_as_of": "2026-10-25", "observations": observations, "compatibility_grants": [grant],
        "financial_anchors": [{"cik": "0000000001", "known_on": "2026-10-01", "period_end": "2026-10-01"}]})
    c = {"schema_version": "screening-price-metrics-config-v1", "price_batch": b,
        "sessions": pin(tmp_path / f"sessions-{tag}.json", calendar), "financial_inputs": f,
        "requested_as_of": "2026-11-16", "price_as_of": "2026-10-23", "session_selection_policy": "EXPLICIT_COMPLETED_SESSION",
        "historical_readiness_policy": "READY_ONLY", "series_start": "2026-10-01", "historical_start": "2026-10-01",
        "dataset_scope": {"dataset_id": "fixture", "dataset_publication_id": "source", "financial_as_of": "2026-10-25", "dataset_manifest_sha256": "a"*64},
        "ev_policy": {"version": "ev-finance-lease-ex-operating-v1", "approved": True, "evidence_pins": [proof]},
        "fixed_multiples": {"per": ["10"], "pbr": ["2"]}}
    config = pin(tmp_path / f"config-{tag}.json", c)
    result = publish_price_metrics(config, tmp_path / f"published-{tag}")
    return PriceMetricReader({k: result[k] for k in ("path", "sha256")}), c, config


def test_query_screen_compare_series_and_bands_are_prepared_values(tmp_path):
    reader, _, config = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "price.sqlite")
    assert reader.query(ciks=["0000000001"], metric_ids=["per"])["rows"][0]["value"] == "50"
    result = reader.screen([{"metric_id": "per", "operator": "lte", "value": "50"}])
    assert result["results"][0]["status"] == "PASS"
    assert reader.screen([{"metric_id": "per", "operator": "lt", "value": "50"}])["results"][0]["status"] == "FAIL"
    assert reader.query(mode="series", metric_ids=["price_return_1s"])["rows"]
    bands = service.execute("bands", {"cik": "0000000001", "multiples": {"per": ["10", "20"], "pbr": ["2"]}})
    assert [row["value"] for row in bands["rows"]] == ["20", "40", "40"]
    assert reader.query()["staleness_calendar_days"] == 24
    assert "input_lineage" not in reader.query()["rows"][0]
    with pytest.raises(FileExistsError):
        publish_price_metrics(config, reader.root)


def test_explicit_result_condition_and_note_reopen_original_after_switch(tmp_path):
    a, _, _ = publication(tmp_path, "a", "100")
    journal = tmp_path / "price.sqlite"
    service = PriceMetricService(a, journal)
    assert service.saves() == []
    request = {"conditions": [{"metric_id": "per", "operator": "lte", "value": "75"}]}
    condition = service.save(kind="CONDITION", operation="screen", request=request, title="original", note="research note")
    result = service.save(kind="RESULT", operation="screen", request=request, title="result", note="exact source")
    assert len(service.saves()) == 2
    b, _, _ = publication(tmp_path, "b", "200")
    switched = PriceMetricService(b, journal)
    assert switched.execute("screen", request)["results"][0]["status"] == "FAIL"
    old = switched.reopen(condition["id"])
    assert old["original_condition_preview"]["results"][0]["conditions"][0]["value_observed"] == "50"
    assert old["original_context_readonly"] is True and old["result"] is None
    reopened = switched.reopen(result["id"])
    assert reopened["result"] == result["result"] and reopened["note"] == "exact source"
    assert reopened["publication_id"] != b.manifest["publication_id"]


def test_result_row_source_and_journal_tampering_are_detected(tmp_path):
    reader, config, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "price.sqlite")
    saved = service.save(kind="RESULT", operation="query", request={"metric_ids": ["per"]}, title="saved")
    file = reader.root / reader.manifest["files"]["0000000001"]["latest"]["path"]
    original = file.read_bytes()
    file.write_bytes(original + b"x")
    with pytest.raises(ValueError, match="artifact hash"):
        reader.query()
    with pytest.raises(ValueError, match="artifact hash"):
        service.reopen(saved["id"])
    file.write_bytes(original)
    Path(config["financial_inputs"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        service.reopen(saved["id"])
    with sqlite3.connect(service.path) as con:
        con.execute("UPDATE price_metric_saves SET payload='{}'")
    with pytest.raises(ValueError, match="content hash"):
        service.saves()


def test_price_journal_refuses_legacy_screening_database(tmp_path):
    reader, _, _ = publication(tmp_path)
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE old_screening (id TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="separate"):
        PriceMetricService(reader, path)
    assert path.read_bytes() == before


def test_single_official_batch_scan_and_adoption_verification(tmp_path):
    delivery = pin(tmp_path / "delivery.json", {"artifacts": {"price.parquet": {"sha256": "p"}, "security.parquet": {"sha256": "s"}}})
    calls = {"verify": 0, "price": 0}
    securities = [{"cik": "0000000001", "ticker": "TEST", "security_id": "US:TEST"},
                  {"cik": "0000000001", "ticker": "OTHER", "security_id": "US:OTHER"}]
    def verify(path):
        calls["verify"] += 1
        return {"status": "verified"}
    def history(ids, start, end):
        calls["price"] += 1
        assert ids == ["US:TEST"]
        return SimpleNamespace(to_dicts=lambda: [{"security_id": "US:TEST", "trade_date": "2026-10-23", "as_traded_close": 10}])
    query = SimpleNamespace(get_securities=lambda: SimpleNamespace(to_dicts=lambda: securities),
        get_price_history=history, price_lineage=lambda: {"sha256": "p", "security_sha256": "s"})
    result = canonical_price_batch(query, verify, delivery_pin=delivery,
        companies=[{"cik": "0000000001", "ticker": "TEST"}], start="2026-01-01", end="2026-10-23")
    assert calls == {"verify": 1, "price": 1}
    assert result["prices"][0]["currency"] is None and result["prices"][0]["ready_on"] is None


def binding_fixture(tmp_path):
    evidence = pin(tmp_path / "evidence.json", {"approved": True})
    candidate = {"observation_id": "candidate", "cik": "0000000001", "value": "10", "status": "AVAILABLE_REPORTED",
        "filed_date": "2026-10-01", "unit_kind": "shares", "start": None, "end": "2026-10-01", "period_class": "INSTANT", "dimensions": []}
    declaration = {"role": "common_shares", "formula": "DIRECT", "cik": "0000000001", "currency": "USD", "scope_id": "common", "stock_class_id": "common-class",
        "split_basis_id": "same", "known_on": "2026-10-01", "ready_on": None, "period_end": "2026-10-01", "period_start": None,
        "period_class": "INSTANT", "candidate_ids": ["candidate"], "share_measure": "OUTSTANDING_COMMON_EX_TREASURY"}
    proposal = pin(tmp_path / "proposal.json", {"schema_version": "price-financial-binding-proposal-v1", "declarations": [declaration], "grant_constraints": {"price_split_factor": "1"}})
    receipt = pin(tmp_path / "receipt.json", {"schema_version": "price-metrics-root-binding-acceptance-v1", "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_TYPED_BINDING", "proposal": proposal, "security_id": "US:TEST"})
    grant = {"cik": "0000000001", "currency": "USD", "financial_scope_id": "common", "stock_class_id": "common-class", "split_basis_id": "same",
        "known_on": "2026-10-01", "financial_anchor": "2026-10-01", "ready_on": None, "common_valuation_scope": "EXACT_COMMON_CLASS_OR_APPROVED_ISSUER_AGGREGATION",
        "invalid_after_newer_financial_anchor": True, "required_price_split_factor": "1", "valid_until": None, "security_id": "US:TEST"}
    config = {"schema_version": "price-financial-binding-config-v1", "financial_as_of": "2026-10-25",
        "candidate_pins": [pin(tmp_path / "candidates.json", [candidate])], "financial_anchors": pin(tmp_path / "anchors.json", []),
        "bindings": [{"declarations": [declaration], "approval": receipt, "proposal": proposal, "compatibility_grant": grant}]}
    return config, declaration, candidate, evidence


@pytest.mark.parametrize("field,value", [("candidate_ids", ["other"]), ("known_on", "2020-01-01"), ("period_end", "2026-09-30")])
def test_reusing_receipt_cannot_change_exact_approved_declaration(tmp_path, field, value):
    config, _, _, _ = binding_fixture(tmp_path)
    assert bind_bundle(pin(tmp_path / "config-good.json", config))["observations"]
    config = copy.deepcopy(config)
    config["bindings"][0]["declarations"][0][field] = value
    with pytest.raises(ValueError, match="exact approved"):
        bind_bundle(pin(tmp_path / "config-bad.json", config))


def test_reusing_receipt_cannot_widen_scope_or_mix_dimensions_and_period(tmp_path):
    config, d, candidate, evidence = binding_fixture(tmp_path)
    config["bindings"][0]["compatibility_grant"]["financial_scope_id"] = "another-issuer-scope"
    with pytest.raises(ValueError, match="widens"):
        bind_bundle(pin(tmp_path / "config.json", config))
    d["evidence_pins"] = [evidence]
    candidate["dimensions"] = [["axis", "other-class"]]
    with pytest.raises(ValueError, match="dimension"):
        bind_financial_inputs([candidate], [d])
    candidate["dimensions"] = []
    candidate["period_class"] = "FY"
    with pytest.raises(ValueError, match="period class"):
        bind_financial_inputs([candidate], [d])


def test_same_metric_bounded_range_is_ordered_and_saved_exactly(tmp_path):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "price.sqlite")
    conditions = [{"metric_id": "per", "operator": "gte", "value": "50"},
                  {"metric_id": "per", "operator": "lte", "value": "50"}]
    result = reader.screen(conditions)
    assert result["results"][0]["status"] == "PASS"
    assert len(result["results"][0]["conditions"]) == 2
    saved = service.save(kind="CONDITION", operation="screen", request={"conditions": conditions}, title="range")
    assert service.reopen(saved["id"])["request"]["conditions"] == conditions
    conditions[-1]["value"] = "49.999999999999999999999"
    assert reader.screen(conditions)["results"][0]["status"] == "FAIL"
    row = reader.query(metric_ids=["per"])["rows"][0]
    assert len(reader.evidence("0000000001", row["observation_id"])["financial_inputs"]) == 1


def test_diagnostic_mode_requires_separate_policy_approval(tmp_path):
    _, config, _ = publication(tmp_path)
    config["historical_readiness_policy"] = "DIAGNOSTIC_FILED_DAY"
    changed = pin(tmp_path / "diagnostic-config.json", config)
    with pytest.raises(ValueError, match="policy approval"):
        publish_price_metrics(changed, tmp_path / "diagnostic-published")


def test_historical_distribution_is_not_implicitly_screened_as_current_multiple(tmp_path):
    reader, _, _ = publication(tmp_path)
    with pytest.raises(ValueError, match="not screening scalars"):
        reader.screen([{"metric_id": "historical_per_percentiles_3y", "operator": "lte", "value": "30"}])


def test_custom_backend_bands_resolve_exact_scenario_and_quote_evidence(tmp_path):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "price.sqlite")
    result = service.execute("bands", {"cik": "0000000001", "multiples": {"per": ["11.25"], "pbr": ["2.25"]}})
    assert [row["value"] for row in result["rows"]] == ["22.50", "45.00"]
    assert set(result["definitions"]) == {"fixed_per_band", "fixed_pbr_band"}
    expected = {"fixed_per_band": "diluted_eps_12m", "fixed_pbr_band": "book_value_per_common_share"}
    for row in result["rows"]:
        request = {"cik": row["cik"], "observation_id": row["observation_id"], "evidence_context": result["evidence_context"]}
        evidence = service.execute("evidence", request)
        assert evidence["row"] == row
        assert evidence["row"]["user_multiple"] in {"11.25", "2.25"}
        assert evidence["publication_pin"] == reader.pin
        assert evidence["financial_inputs"][0]["role"] == expected[row["metric_id"]]
        assert len(evidence["price_inputs"]) == 1
        assert evidence["price_inputs"][0]["as_traded_close"] == "100"
        assert evidence["price_inputs"][0]["trade_date"] == "2026-10-23"
        row["value"] = "999999"  # Caller mutations cannot alter trusted scenario evidence.
        assert service.execute("evidence", request)["row"]["value"] != "999999"
        with pytest.raises(ValueError, match="only a verified result"):
            service.execute("evidence", {**request, "value": "999999"})
        with pytest.raises(ValueError, match="context expired"):
            service.execute("evidence", {**request, "evidence_context": "unknown-token"})


def test_saved_query_and_custom_bands_keep_original_evidence_after_restart_and_active_switch(tmp_path):
    a, _, _ = publication(tmp_path, "a", "100")
    journal = tmp_path / "price.sqlite"
    original = PriceMetricService(a, journal)
    query = original.save(kind="RESULT", operation="query", request={"metric_ids": ["per"]}, title="A query")
    bands = original.save(kind="RESULT", operation="bands", request={"cik": "0000000001", "multiples": {"per": ["11.25"], "pbr": ["2.25"]}}, title="A bands")
    assert "evidence_context" not in query["result"] and "evidence_context" not in bands["result"]
    old_context = original.reopen(query["id"])["evidence_context"]
    b, _, _ = publication(tmp_path, "b", "200")
    switched = PriceMetricService(b, journal)
    for saved in (query, bands):
        reopened = switched.reopen(saved["id"])
        assert reopened["result"] == saved["result"]
        assert reopened["evidence_context"] != old_context
        assert reopened["definition_context"] == a.manifest["definitions"]
        for row in reopened["result"]["rows"]:
            evidence = switched.execute("evidence", {"cik": row["cik"], "observation_id": row["observation_id"], "evidence_context": reopened["evidence_context"]})
            assert evidence["publication_pin"] == a.pin
            assert evidence["definitions"] == a.manifest["definitions"]
            assert evidence["row"]["value"] == row["value"]
            assert evidence["price_inputs"][0]["as_traded_close"] == "100"
            assert evidence["price_inputs"][0]["as_traded_close"] != "200"
    with pytest.raises(ValueError, match="context expired"):
        switched.execute("evidence", {"cik": "0000000001", "observation_id": query["result"]["rows"][0]["observation_id"], "evidence_context": old_context})


def test_evidence_context_cannot_cross_observations_or_hide_source_tampering(tmp_path):
    reader, config, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "price.sqlite")
    result = service.execute("query", {"metric_ids": ["per"]})
    other = reader.query(metric_ids=["pbr"])["rows"][0]
    with pytest.raises(ValueError, match="outside its verified result"):
        service.execute("evidence", {"cik": other["cik"], "observation_id": other["observation_id"], "evidence_context": result["evidence_context"]})
    row = result["rows"][0]
    Path(config["price_batch"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        service.execute("evidence", {"cik": row["cik"], "observation_id": row["observation_id"], "evidence_context": result["evidence_context"]})


def test_saved_band_evidence_uses_original_definition_without_new_calculation(tmp_path, monkeypatch):
    from sec_xbrl.metrics.price_related import REGISTRY

    reader, _, _ = publication(tmp_path)
    journal = tmp_path / "price.sqlite"
    old = PriceMetricService(reader, journal)
    saved = old.save(kind="RESULT", operation="bands", request={"cik": "0000000001", "multiples": {"per": ["11.25"]}}, title="old definition")
    monkeypatch.setitem(REGISTRY["fixed_per_band"], "definition_version", "future-band-definition-v2")
    restarted = PriceMetricService(reader, journal)
    with pytest.raises(ValueError, match="compatible declared definition"):
        restarted.execute("bands", saved["request"])
    reopened = restarted.reopen(saved["id"])
    row = reopened["result"]["rows"][0]
    evidence = restarted.execute("evidence", {"cik": row["cik"], "observation_id": row["observation_id"], "evidence_context": reopened["evidence_context"]})
    assert evidence["row"]["value"] == "22.50"
    assert evidence["definitions"]["fixed_per_band"]["definition_version"] == row["definition_version"]
    assert evidence["definitions"]["fixed_per_band"]["definition_version"] != "future-band-definition-v2"
