"""41-metric producer → verified reader → saved screening synthetic acceptance."""
from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from sec_xbrl.metrics import quarterly_screening as producer
from sec_xbrl.metrics.screening import digest_value, sha256_file, write_json
from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader
from tests.screening.test_quarterly_screening_producer import (
    AS_OF,
    CIK,
    _prepared_input,
    _profile_rows,
)
from tests.screening.test_screening_quarterly_consumer import _quarter_service


def _inputs():
    columns, cells, traces = [], [], []
    definitions = producer.REPORTED_DEFINITIONS
    for index in range(15):  # 2023Q1 through 2026Q3; earlier inputs are not displayed.
        year, q0 = divmod(2023 * 4 + index, 4)
        start = date(year, q0 * 3 + 1, 1)
        end = date(year + 1, 1, 1) if q0 == 3 else date(year, q0 * 3 + 4, 1)
        key = f"{year}-Q{q0 + 1}"
        accession = f"0000000001-{str(year)[-2:]}-{index + 1:06}"
        for period in ("QTD_3M", "INSTANT"):
            columns.append({"fiscal_time_series_column_id": period + key,
                            "actual_end_date": end.isoformat() if period == "QTD_3M" else None,
                            "actual_instant_date": end.isoformat() if period == "INSTANT" else None})
        for definition in definitions:
            row_id = definition["source_row_id"]
            period = definition["observation_basis"]
            # Unequal revenues and margins distinguish ratio-of-sums from mean percentages.
            revenue = 100 * (q0 + 1)
            values = {"revenue": revenue, "gross_profit": 10 * (q0 + 1)**2,
                      "operating_income": -5 if q0 == 0 else 20,
                      "net_income": 10, "cfo": 40, "capex": 10,
                      "current_assets": 60, "current_liabilities": 30,
                      "liabilities": 120, "assets": 300, "equity": 180,
                      "debt": 90, "cash": 40}
            cell, trace = _prepared_input(
                row_id=row_id, value=str(values.get(row_id, 7)),
                start=start.isoformat() if period == "QTD_3M" else None,
                end=end.isoformat(), period_class=period, fiscal_year=year,
                fiscal_quarter=q0 + 1, suffix=row_id + key,
            )
            cell.update(column_id=period + key, basis_version="stable-basis",
                        source_filing_ids=[key])
            lineage = trace["value_lineage"]
            lineage.update(source_filing_id=key, accession=accession,
                           source_snapshot_id=f"l1:{CIK}:{accession.replace('-', '')}:snapshot",
                           basis_version="stable-basis", filed_date=(end + timedelta(days=4)).isoformat(),
                           report_date=(end - timedelta(days=1)).isoformat())
            if row_id == "debt":
                lineage.update(raw_concept_qname="us-gaap:DebtLongtermAndShorttermCombinedAmount",
                               raw_concept_is_standard=True,
                               raw_concept_data_type="xbrli:monetaryItemType", raw_concept_period_type="instant")
            statement = producer._statement_type(row_id)
            for evidence in (cell["primary_statement_evidence"], lineage["primary_statement_evidence"]):
                evidence[0].update(source_filing_id=key, accession=accession, statement_types=[statement])
            cells.append(cell)
            traces.append(trace)
    return columns, cells, traces


def _records(inputs=None):
    columns, cells, traces = inputs or _inputs()
    return producer.build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=producer._quarter_spine(AS_OF))


def _row(rows, metric, year=2026, quarter=3):
    return next(row for row in rows if (row["metric_id"], row["calendar_year"], row["calendar_quarter"])
                == (metric, year, quarter))


def _publication(tmp_path, *, legacy=False, mutate=None):
    rows, inventory = _records()
    definitions = copy.deepcopy(list(producer.LEGACY_DEFINITIONS if legacy else producer.METRIC_DEFINITIONS))
    ids = {row["metric_id"] for row in definitions}
    rows = [row for row in rows if row["metric_id"] in ids]
    if mutate:
        mutate(rows)
    support = producer._support_rows([{"cik": CIK, "ticker": "TEST"}], rows, definitions=definitions)
    membership = producer._membership_hash([CIK])
    manifest = {"schema_version": producer.VERSION, "fixture_kind": "SYNTHETIC_QUARTERLY_41",
                "financial_as_of": AS_OF, "global_quarter_spine": producer._quarter_spine(AS_OF),
                "universe": {"ciks": [CIK], "company_count": 1, "company_membership_sha256": membership},
                "annual_parent": {"company_membership_sha256": membership}, "config": {},
                "governance_parents": [], "files": {}, "counts": {}}
    if not legacy:
        manifest["catalog_version"] = producer.CATALOG_VERSION
    names = ("definitions", "support", "observations", "period_inventory")
    for filename, name, records in zip(producer.FILES, names, (definitions, support, rows, inventory)):
        path = tmp_path / filename
        write_json(path, {"fixture_kind": manifest["fixture_kind"], "records": records})
        manifest["files"][filename] = {"sha256": sha256_file(path), "size": path.stat().st_size,
                                        "record_count": len(records)}
        manifest["counts"][name] = len(records)
    identity = {"config": {}, "annual_parent": manifest["annual_parent"], "definitions": definitions,
                "support": support, "observations": rows, "period_inventory": inventory, "sources": []}
    manifest["publication_id"] = "quarterly-screening-metrics-" + digest_value(identity)[:24]
    write_json(tmp_path / producer.MANIFEST, manifest)
    return tmp_path


def test_all_41_and_ratio_of_sums_use_prior_inputs_without_summing_balances(tmp_path):
    root = _publication(tmp_path)
    reader = QuarterlyScreeningMetricReader(root)
    producer.QuarterlyMetricReader(root)
    rows = reader.observations
    assert len(reader.definitions) == 41
    assert len(rows) == 41 * 8
    assert all(row["availability_status"] == "AVAILABLE" for row in rows)
    expected = {"quarter_net_margin": "3.333333333333333333333333333333333",
                "quarter_standardized_fcf": "30", "quarter_current_ratio": "200",
                "quarter_liabilities_to_equity": "66.66666666666666666666666666666667",
                "quarter_liabilities_to_assets": "40", "quarter_net_debt": "50",
                "ttm_revenue": "1000", "ttm_operating_income": "55", "ttm_net_income": "40",
                "ttm_cfo": "160", "ttm_standardized_fcf": "120", "ttm_gross_margin": "30",
                "ttm_operating_margin": "5.5", "ttm_net_margin": "4", "ttm_fcf_margin": "12"}
    for metric, value in expected.items():
        assert _row(rows, metric)["value"] == value, metric
    assert _row(rows, "quarter_cash")["value"] == "40"
    earliest = _row(rows, "ttm_fcf_margin", 2024, 4)
    assert earliest["period_start"] == "2024-01-01"
    assert earliest["source_lineage"]["derivation_inputs"][0]["calendar_quarter"] == 1
    assert _row(rows, "quarter_revenue_yoy", 2024, 4)["value"] == "0"
    # Quarterly margins are 10,20,30,40%; their mean is 25%, not the published 30%.
    assert Decimal(_row(rows, "ttm_gross_margin")["value"]) != Decimal(25)


def test_legacy_17_catalog_is_unchanged_and_both_readers_still_open_it(tmp_path):
    root = _publication(tmp_path, legacy=True)
    assert len(producer.QuarterlyMetricReader(root).definitions) == 17
    assert len(QuarterlyScreeningMetricReader(root).definitions) == 17
    # Frozen from main 669489b5c76b0ee4c419e82c48c6a61289f160cc, not recomputed from this module.
    assert digest_value(list(producer.LEGACY_DEFINITIONS)) == "e684c85ea4dea2b183584ef3e62e9663628290ae899246bcf643fab4e38e575d"
    old = {row["metric_id"]: row for row in producer.LEGACY_DEFINITIONS}
    assert all(old.get(row["metric_id"], row) == row for row in producer.METRIC_DEFINITIONS)


@pytest.mark.parametrize("defect", ["missing", "basis", "quality", "gap", "capex_sign", "filing", "debt_qname", "debt_type"])
def test_incompatible_new_inputs_remain_unavailable(defect):
    columns, cells, traces = _inputs()
    target = next(trace for trace in traces if trace["cell_id"] == "cell-capex2026-Q2")
    cell = next(cell for cell in cells if cell["cell_id"] == target["cell_id"])
    lineage = target["value_lineage"]
    if defect == "missing":
        cells.remove(cell)
        traces.remove(target)
    elif defect == "basis":
        cell["basis_version"] = lineage["basis_version"] = "other-basis"
    elif defect == "quality":
        lineage["quality_blocking"] = True
    elif defect == "gap":
        cell["start"] = lineage["context_start_date"] = "2026-04-02"
    elif defect == "capex_sign":
        cell["value"] = lineage["value_numeric"] = "-10"
    elif defect == "filing":
        cell["source_filing_ids"] = ["different"]
        lineage["source_filing_id"] = "different"
        for evidence in (cell["primary_statement_evidence"], lineage["primary_statement_evidence"]):
            evidence[0]["source_filing_id"] = "different"
    else:
        lineage = next(trace["value_lineage"] for trace in traces if trace["cell_id"] == "cell-debt2026-Q3")
        lineage["raw_concept_qname" if defect == "debt_qname" else "raw_concept_data_type"] = "unsupported"
    rows, _ = _records((columns, cells, traces))
    metric = "quarter_net_debt" if defect.startswith("debt") else "ttm_fcf_margin"
    assert _row(rows, metric)["availability_status"] == "UNAVAILABLE"


@pytest.mark.parametrize("defect", ["cycle", "nested_metric", "basis", "unit", "period", "mapping", "quality"])
def test_consumer_rejects_rehashed_ttm_fcf_lineage_corruption(tmp_path, defect):
    def mutate(rows):
        row = _row(rows, "ttm_fcf_margin")
        item = row["source_lineage"]["derivation_inputs"][0]
        if defect == "cycle":
            item["observation_id"] = row["observation_id"]
        elif defect == "nested_metric":
            item["metric_id"] = "ttm_revenue"
        elif defect == "basis":
            item["basis_version"] = "different"
        elif defect == "unit":
            item["unit"] = "EUR"
        elif defect == "period":
            item["period_start"] = "2025-01-02"
        else:
            leaf = item["source_lineage"]["derivation_inputs"][1]
            leaf["source_lineage"]["quality_blocking" if defect == "quality" else "mapping_review_required"] = True
    root = _publication(tmp_path, mutate=mutate)
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(root)


def test_expanded_catalog_saved_conditions_trace_and_eight_quarter_trend(tmp_path):
    publication = tmp_path / "publication"
    publication.mkdir()
    wire = QuarterlyScreeningMetricReader(_publication(publication))
    service = _quarter_service(tmp_path)
    dataset = service.datasets["synthetic-v3"]
    dataset.companies = dataset.companies[:1]
    dataset.quarterly = wire
    dataset.quarter_definitions = wire.definitions
    dataset.quarter_support = wire.support
    dataset.quarter_observations = wire.observations
    dataset.quarter_period_inventory = wire.period_inventory
    definitions = {row["metric_id"]: row for row in wire.definitions}
    content = {"universe": {"mode": "ALL_PREPARED"}, "predicates": [
        {"metric_id": metric, "operator": "GTE", "threshold": "0",
         "definition_version": definitions[metric]["definition_version"]}
        for metric in ("quarter_current_ratio", "quarter_revenue_yoy", "ttm_fcf_margin")],
        "period_policy": {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2026, "calendar_quarter": 3},
        "columns": ["company", "aggregate", "predicates"], "sort": {"column": "ticker", "direction": "ASC"}}
    revision = service.create_screen("확장", content)
    run = service.execute(revision["revision_id"], "synthetic-v3")
    assert len(service.quarter_metric_catalog("synthetic-v3")) == 41
    assert run["rows"][0]["predicates"][2]["observation"]["value"] == "12"
    trace = service.trace(run["run_id"], cik=CIK, metric_id="ttm_fcf_margin")
    assert len(trace["trace"]["derivation_inputs"]) == 8
    series = service.quarter_series("synthetic-v3", cik=CIK, metric_id="ttm_fcf_margin")
    assert len(series["observations"]) == 8
    # Reopen the exact saved revision and dataset; no catalog/runtime mutation.
    reopened = service.execute(revision["revision_id"], "synthetic-v3")
    assert reopened["rows"] == run["rows"]


def test_exact_debt_note_allowance_preserves_locator_and_requires_typed_cash():
    columns, cells, traces = _inputs()
    debt = next(row for row in cells if row["cell_id"] == "cell-debt2026-Q3")
    source = next(row["value_lineage"] for row in traces if row["cell_id"] == debt["cell_id"])
    debt["primary_statement_evidence"] = []
    source["primary_statement_evidence"] = []
    rows, _ = _records((columns, cells, traces))
    result = _row(rows, "quarter_net_debt")
    assert result["value"] == "50"
    assert result["source_lineage"]["debt_input_policy"] == "EXACT_STANDARD_COMBINED_DEBT_NOTE_ALLOWANCE"
    assert result["source_lineage"]["debt_note_locator"]["source_fact_id"] == source["selected_source_fact_id"]
    cash = next(row for row in cells if row["cell_id"] == "cell-cash2026-Q3")
    cash["primary_statement_evidence"] = []
    next(row["value_lineage"] for row in traces if row["cell_id"] == cash["cell_id"])["primary_statement_evidence"] = []
    rows, _ = _records((columns, cells, traces))
    assert _row(rows, "quarter_net_debt")["availability_status"] == "UNAVAILABLE"


@pytest.mark.parametrize("equity,reason", [("-1", "NEGATIVE_EQUITY"), ("0", "NON_POSITIVE_DENOMINATOR")])
def test_quarterly_negative_and_zero_equity_remain_business_unavailable(equity, reason):
    columns, cells, traces = _inputs()
    cell = next(row for row in cells if row["cell_id"] == "cell-equity2026-Q3")
    source = next(row["value_lineage"] for row in traces if row["cell_id"] == cell["cell_id"])
    cell["value"] = source["value_numeric"] = equity
    rows, _ = _records((columns, cells, traces))
    assert _row(rows, "quarter_liabilities_to_equity")["reason"] == reason


def test_reader_preserves_materialized_ttm_value_without_recalculating(tmp_path):
    def mutate(rows):
        _row(rows, "ttm_fcf_margin")["value"] = "12.00000000000000000000000000000001"
    wire = QuarterlyScreeningMetricReader(_publication(tmp_path, mutate=mutate))
    assert _row(wire.observations, "ttm_fcf_margin")["value"] == "12.00000000000000000000000000000001"


@pytest.mark.parametrize("catalog", [None, "unknown-catalog"])
def test_expanded_catalog_cannot_silently_downgrade_to_legacy(tmp_path, catalog):
    import json
    root = _publication(tmp_path)
    path = root / producer.MANIFEST
    manifest = json.loads(path.read_text())
    if catalog is None:
        manifest.pop("catalog_version")
    else:
        manifest["catalog_version"] = catalog
    write_json(path, manifest)
    with pytest.raises(ValueError, match="catalog"):
        QuarterlyScreeningMetricReader(root)


@pytest.mark.parametrize("short_history", [False, True])
def test_sparse_lookback_outside_display_stays_unavailable(short_history):
    columns, cells, traces = _inputs()
    cells = [cell for cell in cells if (
        cell["fiscal_year"] >= 2026 if short_history
        else not (cell["row_id"] == "cost" and cell["fiscal_year"] < 2025)
    )]
    ids = {cell["cell_id"] for cell in cells}
    traces = [trace for trace in traces if trace["cell_id"] in ids]
    observations, inventory = _records((columns, cells, traces))
    assert len(inventory) == 8
    assert len(observations) == 41 * 8
    if short_history:
        assert _row(observations, "ttm_revenue")["availability_status"] == "UNAVAILABLE"
    else:
        missing = _row(observations, "quarter_cost", 2024, 4)
        assert missing["availability_status"] == "UNAVAILABLE"
        assert missing["reason"] == "INPUT_NOT_REPORTED"
