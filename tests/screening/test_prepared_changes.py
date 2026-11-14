"""Registration reuses governed comparisons, never predicate-side arithmetic."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from examples.screening import prepare_financial_growth as v1
from examples.screening.prepare_screening_changes import (
    MONEY,
    RATIOS,
    VERSION,
    compare_rows,
    definitions,
)
from sec_xbrl.screening.service import _evaluate_predicate
from tests.screening.test_financial_comparison_v2 import ratio_pair
from tests.screening.test_financial_growth import CUTOFF, annual, quarter


def parent():
    return SimpleNamespace(manifest={"financial_as_of": CUTOFF})


@pytest.mark.parametrize(("prior", "current", "expected", "state"), [
    ("10", "15", "50", "RATE_AVAILABLE"), ("10", "0", "-100", "ZERO_REACHED"),
    ("10", "-5", None, "NEGATIVE_TURN"), ("0", "5", None, "ZERO_BASE"),
    ("0", "0", None, "ZERO_UNCHANGED"), ("0", "-5", None, "ZERO_BASE"),
    ("-10", "5", None, "POSITIVE_TURN"), ("-10", "0", None, "ZERO_REACHED"),
    ("-10", "-4", None, "NEGATIVE_MAGNITUDE_REDUCED"),
])
def test_registered_sign_policy_and_exact_predicate_threshold(prior, current, expected, state):
    before, after = {**annual(2023), "value": prior}, {**annual(2024), "value": current}
    rows = compare_rows([before, after], quarterly=False, parent=parent(), by_id={}, catalog={})
    row = rows[-1]
    assert row["value"] == expected and row["comparison_status"] == state
    assert row["comparison_evidence"] == v1.compare_periods(after, before, "FY", CUTOFF, {})
    predicate = {"metric_id": "operating_income_yoy", "definition_version": VERSION, "operator": "GTE", "threshold": "50.0000000000000000001"}
    assert _evaluate_predicate(predicate, row)["result"] == ("FAIL" if expected is not None else "UNDETERMINED")
    assert row["input_observation_ids"] == ["FY2024", "FY2023"]


def test_missing_prior_and_duplicate_fiscal_period_fail_closed():
    row = compare_rows([annual(2024)], quarterly=False, parent=parent(), by_id={}, catalog={})[0]
    assert row["unavailable_reason"] == "PRIOR_NOT_PREPARED"
    rows = compare_rows([annual(2023), {**annual(2023), "metric_observation_id": "other"}, annual(2024)],
                        quarterly=False, parent=parent(), by_id={}, catalog={})
    assert rows[-1]["unavailable_reason"] == "AMBIGUOUS_FISCAL_PERIOD"


def test_quarter_uses_prior_same_fiscal_quarter_not_adjacent_period():
    before, other, after = quarter(2023, 2, "quarter_operating_income"), quarter(2024, 1, "quarter_operating_income"), quarter(2024, 2, "quarter_operating_income")
    after["value"] = "125"
    result = compare_rows([before, other, after], quarterly=True, parent=parent(), by_id={}, catalog={})[-1]
    assert result["value"] == "25"
    assert result["input_observation_ids"] == [after["observation_id"], before["observation_id"]]


def test_27_definitions_are_explicit_and_do_not_rederive_growth_rate_changes():
    entries = [{"metric_id": metric, "label": metric, "definition_version": "v1", "unit": "PERCENT" if metric in RATIOS else "USD",
                "category": "PROFITABILITY", "period_class": "TTM" if metric.startswith("ttm_") else "QTD_3M" if metric.startswith("quarter_") else "FY"}
               for metric in MONEY + RATIOS]
    annual, quarterly = definitions(SimpleNamespace(metric_definitions=entries[:0] + [row for row in entries if not row["metric_id"].startswith(("quarter_", "ttm_"))],
        quarter_definitions=[row for row in entries if row["metric_id"].startswith(("quarter_", "ttm_"))]))
    assert len(annual) == 10 and len(quarterly) == 17
    assert len({row["metric_id"] for row in annual + quarterly}) == 27
    assert not any("revenue_yoy" in row["comparison_of"] or "qoq" in row["comparison_of"] for row in annual + quarterly)
    assert {row["unit"] for row in annual + quarterly if row["comparison_kind"] == "PERCENTAGE_POINT"} == {"PERCENTAGE_POINT"}


@pytest.mark.parametrize("instant", [False, True])
def test_registered_percentage_points_keep_exact_unit_inputs_and_period(instant):
    current, prior, by_id, catalog = ratio_pair(instant)
    result = compare_rows([prior, current], quarterly=False, parent=parent(), by_id=by_id, catalog=catalog)[-1]
    assert result["value"] == "0.000000000000000000000000000001"
    assert result["unit"] == "PERCENTAGE_POINT" and result["metric_id"] == "gross_margin_yoy_pp"
    assert result["period_start"] == current["period_start"]
    assert _evaluate_predicate({"metric_id": result["metric_id"], "definition_version": VERSION,
        "threshold": "0.000000000000000000000000000001", "operator": "EQ"}, result)["result"] == "PASS"
    changed = deepcopy(prior)
    changed["basis_version"] = "different"
    assert compare_rows([changed, current], quarterly=False, parent=parent(), by_id=by_id, catalog=catalog)[-1]["value"] is None


def test_new_publication_registers_queries_saves_reopens_and_exports_without_mutating_parent(tmp_path):
    from examples.screening.prepare_screening_changes import publish
    from sec_xbrl.metrics.quarterly_screening import METRIC_DEFINITIONS as QUARTER
    from sec_xbrl.metrics.screening import METRIC_DEFINITIONS as ANNUAL
    from sec_xbrl.screening.common import sha256_file
    from sec_xbrl.screening.read_snapshot import ScreeningReadSnapshot
    from sec_xbrl.screening.service import ScreeningService
    from tests.screening.test_read_snapshot import approve, exporter

    company = {"cik": "0000000001", "ticker": "TEST", "name": "Example", "sic_code": None}
    annual_definitions = [deepcopy(row) for row in ANNUAL]
    next(row for row in annual_definitions if row["metric_id"] == "operating_income")["definition_version"] = "v1"
    rows = [{**annual(2023), "ticker": "TEST"}, {**annual(2024), "ticker": "TEST", "value": "150"}]
    original = SimpleNamespace(companies=[company], company=lambda cik: deepcopy(company),
        manifest={"dataset_id": "parent", "publication_id": "parent-publication", "financial_as_of": CUTOFF,
                  "fixture_kind": "SYNTHETIC_ERROR_FIXTURE", "sources": {"metadata": {"publication_id": "metadata"}}, "versions": {"old": "preserved"}},
        _manifest_sha256="a" * 64, metric_definitions=annual_definitions, quarter_definitions=list(QUARTER),
        observations=rows, quarter_observations=[], metric_support=[], quarter_support=[], metadata=[],
        quarter_period_inventory=[], quarterly=SimpleNamespace(manifest={"global_quarter_spine": []}),
        verify_all=lambda: {"dataset_id": "parent", "publication_id": "parent-publication", "quarter_observation_count": 0})
    parent_root = tmp_path / "parent"
    exporter.export_reader(original, parent_root, {"source_revision": "synthetic"})
    parent_declaration = approve(parent_root)
    before = {path.name: sha256_file(path) for path in parent_root.iterdir()}
    config = tmp_path / "config.json"
    config.write_bytes(exporter.encoded({"parent_root": str(parent_root), "parent": parent_declaration, "dataset_id": "new"}))
    destination = tmp_path / "new"
    publish({"path": str(config), "sha256": sha256_file(config)}, destination)
    declaration = approve(destination)
    reader = ScreeningReadSnapshot(destination, declaration)
    assert len(reader.metric_definitions) == len(ANNUAL) + 10
    assert len(reader.quarter_definitions) == len(QUARTER) + 17
    assert reader.rows(metric_id="operating_income") == ScreeningReadSnapshot(parent_root, parent_declaration).rows(metric_id="operating_income")
    assert {path.name: sha256_file(path) for path in parent_root.iterdir()} == before
    store = tmp_path / "private.sqlite"
    service = ScreeningService({"new": destination}, store, read_snapshots={"new": declaration})
    registered = next(row for row in service.metric_catalog("new") if row["metric_id"] == "operating_income_yoy")
    assert registered["comparison_of"] == "operating_income" and registered["coverage"]["periods_available"] == 1
    assert service.company_profile("new", cik=company["cik"], fiscal_year=2024)["series"]["operating_income_yoy"][-1]["value"] == "50"
    content = {"universe": {"mode": "ALL_PREPARED"}, "period_policy": {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": 2024},
               "predicates": [{"metric_id": "operating_income_yoy", "definition_version": VERSION, "operator": "GTE", "threshold": "50.0000000000000000001"}],
               "columns": ["ticker", "aggregate"], "sort": {"column": "metric:operating_income_yoy", "direction": "DESC"}}
    preview = service.preview(content, "new")
    assert preview["rows"][0]["aggregate"] == "FAIL"
    result = service.save_result(name="new comparison", content=content, dataset_id="new", preview_hash=preview["preview_hash"])
    reopened = ScreeningService({"new": destination}, store, read_snapshots={"new": declaration})
    saved = reopened.run(result["run_id"])
    assert saved["rows"] == result["rows"]
    assert reopened.trace(saved["run_id"], cik=company["cik"], metric_id="operating_income_yoy")["trace"]["comparison"]["yoy"] == "50"
    with pytest.raises(ValueError, match="new nonsymlink destination"):
        publish({"path": str(config), "sha256": sha256_file(config)}, destination)


def test_monetary_registration_requires_its_catalog_definition_version():
    with pytest.raises(ValueError, match="definition differs"):
        compare_rows([annual(2024)], quarterly=False, parent=parent(), by_id={},
                     catalog={"operating_income": {"definition_version": "other"}})


@pytest.mark.parametrize("quarterly", [False, True])
def test_latest_only_comparison_enables_condition_without_expanding_fixed_view(tmp_path, quarterly):
    from examples.screening.prepare_screening_changes import publish
    from sec_xbrl.metrics.quarterly_screening import METRIC_DEFINITIONS as QUARTER
    from sec_xbrl.metrics.screening import METRIC_DEFINITIONS as ANNUAL
    from sec_xbrl.screening.common import sha256_file
    from sec_xbrl.screening.service import ScreeningService
    from tests.screening.test_read_snapshot import approve, exporter

    company = {"cik": "0000000001", "ticker": "TEST", "name": "Example", "sic_code": None}
    annual_definitions, quarter_definitions = deepcopy(list(ANNUAL)), deepcopy(list(QUARTER))
    metric = "quarter_operating_income" if quarterly else "operating_income"
    next(row for row in (quarter_definitions if quarterly else annual_definitions) if row["metric_id"] == metric)["definition_version"] = "v1"
    before = quarter(2023, 2, metric) if quarterly else annual(2023)
    after = {**(quarter(2024, 2, metric) if quarterly else annual(2024)), "value": "150"}
    if quarterly:
        for row in (before, after):
            row.update(calendar_year=row["fiscal_year"], calendar_quarter=2)
    def period(row):
        return {key: row[key] for key in ("cik", "fiscal_year", "fiscal_quarter", "calendar_year", "calendar_quarter", "period_start", "period_end", "end_convention") if key in row} | {"bucket_status": "PERIOD_AVAILABLE"}
    original = SimpleNamespace(companies=[company], company=lambda cik: deepcopy(company),
        manifest={"dataset_id": "parent", "publication_id": "parent-pub", "financial_as_of": CUTOFF,
            "fixture_kind": "SYNTHETIC_ERROR_FIXTURE", "sources": {"metadata": {"publication_id": "metadata"}}},
        _manifest_sha256="a" * 64, metric_definitions=annual_definitions, quarter_definitions=quarter_definitions,
        observations=[] if quarterly else [before], quarter_observations=[before] if quarterly else [],
        metric_support=[], quarter_support=[], metadata=[], quarter_period_inventory=[period(before)] if quarterly else [],
        latest_quarter_periods={company["cik"]: period(after)} if quarterly else {},
        quarterly=SimpleNamespace(manifest={"global_quarter_spine": [{"calendar_year": 2023, "calendar_quarter": 2}]}),
        latest_rows=lambda **selection: deepcopy([before, after] if selection["quarterly"] == quarterly else []),
        verify_all=lambda: {"dataset_id": "parent", "publication_id": "parent-pub", "quarter_observation_count": int(quarterly)})
    parent_root = tmp_path / "parent"
    exporter.export_reader(original, parent_root, {"source_revision": "synthetic"})
    config = tmp_path / "config.json"
    config.write_bytes(exporter.encoded({"parent_root": str(parent_root), "parent": approve(parent_root), "dataset_id": "new"}))
    destination = tmp_path / "new"
    publish({"path": str(config), "sha256": sha256_file(config)}, destination)
    service = ScreeningService({"new": destination}, tmp_path / "private.sqlite", read_snapshots={"new": approve(destination)})
    reader = service.datasets["new"]
    support_rows = reader.quarter_support if quarterly else reader.metric_support
    registered = next(row for row in support_rows if row["metric_id"] == metric + "_yoy")
    assert registered["execution_supported"] is True
    assert registered["available_periods"] == 1 and registered["observed_periods"] == 2
    assert registered["view_support"]["fixed"]["available_periods"] == 0
    assert registered["view_support"]["latest"]["available_periods"] == 1
    assert len(reader.rows(quarterly=quarterly, metric_id=metric + "_yoy")) == 1
    assert len(reader.latest_rows(quarterly=quarterly, metric_id=metric + "_yoy")) == 2
    content = {"universe": {"mode": "ALL_PREPARED"},
        "period_policy": {"mode": "LATEST_COMPANY_QUARTER_V1" if quarterly else "LATEST_COMPANY_ANNUAL_V1",
                          "availability": service.batch_availability(mode="PREPARED_SIMULATION", dataset_id="new")},
        "predicates": [{"metric_id": metric + "_yoy", "definition_version": VERSION, "operator": "EQ", "threshold": "50"}],
        "columns": ["ticker", "aggregate"], "sort": {"column": "ticker", "direction": "ASC"}}
    service.create_screen("latest-only", content, dataset_id="new")
    evaluated = service.preview(content, "new")["rows"][0]
    assert evaluated["predicates"][0]["reason"] == "PREDICATE_MATCHED"
    assert evaluated["aggregate"] == "PASS", evaluated
    fixed = deepcopy(content)
    fixed["period_policy"] = ({"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2023, "calendar_quarter": 2}
                              if quarterly else {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": 2023})
    assert service.preview(fixed, "new")["rows"][0]["aggregate"] == "UNDETERMINED"


def test_support_deduplicates_shared_fixed_and_latest_periods():
    from examples.screening.prepare_screening_changes import support
    row = {"cik": "0000000001", "metric_id": "operating_income_yoy", "fiscal_year": 2024,
           "period_class": "FY", "period_start": "2024-01-01", "period_end": "2025-01-01",
           "availability_status": "AVAILABLE", "unavailable_reason": None}
    result = support({"cik": row["cik"], "ticker": "TEST"}, [{"metric_id": row["metric_id"]}], [row], [deepcopy(row)])[0]
    assert result["available_periods"] == result["observed_periods"] == 1
    assert result["view_support"]["fixed"]["available_periods"] == result["view_support"]["latest"]["available_periods"] == 1



def test_legacy_annual_reader_without_latest_rows_keeps_anchor_fallback():
    from sec_xbrl.screening.explorer import latest_company_period
    reader = SimpleNamespace(observations=[annual(2023), annual(2024)])
    assert latest_company_period(reader, "0000000001", quarterly=False)["fiscal_year"] == 2024
