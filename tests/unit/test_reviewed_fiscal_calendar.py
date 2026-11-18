from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from sec_xbrl.analytics.history_quarters import derive_quarter
from sec_xbrl.analytics.revenue_quarters import derive_revenue_q4
from sec_xbrl.periods.reviewed_calendar import FiscalCalendarRegistry, digest
from tests.unit.test_history_quarters import _cell
from tests.unit.test_revenue_quarters import _observation


def calendar_input(tmp_path: Path, *, weeks=None, change=None):
    weeks = weeks or [12, 12, 12, 16]
    start = date(2024, 9, 2)
    ends, current = [], start
    for week in weeks:
        current += timedelta(weeks=week)
        ends.append(current.isoformat())
    source = tmp_path / "source.txt"
    source.write_text("Reviewed filing: first three quarters12 weeks, Q4 16/17 weeks")
    entry = {"calendar_id": "fixture-calendar", "cik": "0000000001", "fiscal_year": 2025,
        "financial_as_of": "2026-10-25", "start_date": start.isoformat(), "quarter_end_dates": ends,
        "quarter_weeks": weeks, "source_pins": [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "evidence": [{"source_index": 0, "locator": "Note1", "assertion": "Explicit week calendar"}]}
    if change:
        entry.update(change)
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"schema_version": "root-fiscal-calendar-approval-v1", "authority": "ROOT", "status": "APPROVED", "calendar_sha256": digest(entry)}))
    entry["approval"] = {"path": str(approval), "sha256": hashlib.sha256(approval.read_bytes()).hexdigest()}
    artifact = tmp_path / "calendar.json"
    artifact.write_text(json.dumps({"schema_version": "reviewed-fiscal-calendar-v1", "financial_as_of": "2026-10-25", "calendars": [entry]}))
    return artifact, hashlib.sha256(artifact.read_bytes()).hexdigest()


def observations(calendar):
    result = [_observation("FY", "100"), _observation("YTD_9M", "70")]
    for row, end in zip(result, (calendar.boundaries[4], calendar.boundaries[3]), strict=True):
        row.update(context_start_date=calendar.boundaries[0], context_end_date=end,
                   context_duration_days=(date.fromisoformat(end) - date.fromisoformat(calendar.boundaries[0])).days)
    return result


@pytest.mark.parametrize("weeks", [[12, 12, 12, 16], [12, 12, 12, 17]])
def test_reviewed_calendar_admits_exact_112_or_119_only_and_preserves_sources(tmp_path, weeks):
    artifact, sha = calendar_input(tmp_path, weeks=weeks)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).get("0000000001", 2025)
    rows = observations(calendar)
    original = deepcopy(rows)
    assert not derive_revenue_q4(rows, cutoff=calendar.financial_as_of)[0]
    derived, held = derive_revenue_q4(rows, cutoff=calendar.financial_as_of, calendar=calendar)
    assert not held
    assert derived[0]["value_numeric"] == "30"
    assert derived[0]["fiscal_calendar_proof"]["calendar_sha256"] == calendar.calendar_sha256
    assert "reviewed-calendar-v1" in derived[0]["derivation_rule_version"]
    assert rows == original
    # Core statement adapter still requires the original additive policy.
    cells = [_cell("FY", "100", calendar.boundaries[4]), _cell("YTD_9M", "70", calendar.boundaries[3])]
    for cell, row in zip(cells, rows, strict=True):
        cell["value_lineage"].update({k: row[k] for k in ("cik", "fiscal_year", "filed_date", "context_start_date", "context_end_date", "context_duration_days")})
        cell["value_lineage"]["selection_as_of_date"] = calendar.financial_as_of
    assert derive_quarter(*cells, quarter=4) is None
    assert derive_quarter(*cells, quarter=4, calendar=calendar)["value_numeric"] == "30"
    cells[0]["value_lineage"]["raw_concept_qname"] = "us-gaap:EarningsPerShareBasic"
    assert derive_quarter(*cells, quarter=4, calendar=calendar) is None


@pytest.mark.parametrize("change", [
    {"cik": "0000000002"}, {"fiscal_year": 2026}, {"basis_version": "other"},
    {"context_start_date": "2024-09-03"}, {"context_end_date": "2025-05-13"},
    {"mapping_review_required": True}, {"recast_review_required": True},
    {"unit_numerator_measures": '["iso4217:EUR"]'}, {"filed_date": "2027-01-01"},
])
def test_calendar_is_not_mapping_scope_basis_period_or_cutoff_permission(tmp_path, change):
    artifact, sha = calendar_input(tmp_path)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).calendars[0]
    rows = observations(calendar)
    rows[1].update(change)
    assert not derive_revenue_q4(rows, cutoff=calendar.financial_as_of, calendar=calendar)[0]


def test_source_and_approval_tamper_rejected_at_batch_boundary(tmp_path):
    artifact, sha = calendar_input(tmp_path)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).calendars[0]
    (tmp_path / "source.txt").write_text("tampered")
    with pytest.raises(ValueError, match="pin mismatch"):
        derive_revenue_q4(observations(calendar), cutoff=calendar.financial_as_of, calendar=calendar)
    with pytest.raises(ValueError, match="pin mismatch"):
        FiscalCalendarRegistry.load(artifact, expected_sha256=sha)


@pytest.mark.parametrize("change", [
    {"quarter_weeks": [12, 12, 12, 15]}, {"quarter_end_dates": ["2024-11-25"]},
    {"evidence": []}, {"financial_as_of": "2026-10-26"},
])
def test_even_reviewed_unsupported_partial_or_wrong_cutoff_calendar_fails(tmp_path, change):
    artifact, sha = calendar_input(tmp_path, change=change)
    with pytest.raises(ValueError):
        FiscalCalendarRegistry.load(artifact, expected_sha256=sha)


def test_duplicate_inputs_still_hold_with_reviewed_calendar(tmp_path):
    artifact, sha = calendar_input(tmp_path)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).calendars[0]
    rows = observations(calendar)
    assert not derive_revenue_q4([*rows, deepcopy(rows[0])], cutoff=calendar.financial_as_of, calendar=calendar)[0]


def test_calendar_period_classification_and_exact_companion_output(tmp_path):
    import polars as pl

    from examples.screening.prepare_reviewed_calendar_q4 import prepare
    from sec_xbrl.periods.logic import PeriodClassifier

    artifact, sha = calendar_input(tmp_path)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).calendars[0]
    facts = PeriodClassifier().classify(
        filing={"cik": calendar.cik, "document_fiscal_year_focus": "2025", "report_date": "2025-08-31", "filed_date": "2025-10-01", "form": "10-K", "document_fiscal_period_focus": "FY"},
        concepts=[{"raw_concept_id": "r", "period_type": "duration"}],
        contexts=[{"context_id": "q4", "period_kind": "DURATION", "start_date": calendar.boundaries[3], "end_date": calendar.boundaries[4], "duration_days": 112}],
        facts=[{"raw_concept_id": "r", "context_id": "q4"}], calendar=calendar)
    assert facts[0]["period_class"] == "QTD_3M"
    assert facts[0]["period_classification_version"] == "reviewed-fiscal-calendar-classification-v1"
    rows = observations(calendar)
    rows[0]["value_numeric"] = "10000000000000000000000000000000.00000001"
    source = tmp_path / "observations.parquet"
    pl.DataFrame(rows).write_parquet(source)
    output = tmp_path / "new-companion.json"
    summary = prepare(source, observations_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), calendars=artifact, calendars_sha256=sha, output=output)
    assert summary["derived_count"] == 1
    content = json.loads(output.read_text())
    assert content["derived_metrics"][0]["value_numeric"] == "9999999999999999999999999999930.00000001"
    assert content["ratio_policy"].startswith("UNPREPARED")
    with pytest.raises(FileExistsError):
        prepare(source, observations_sha256="bad", calendars=artifact, calendars_sha256=sha, output=output)


def test_calendar_does_not_replace_continuity_endpoint_or_mapping_review(tmp_path):
    from sec_xbrl.analytics.revenue_q4_continuity import derive_reviewed_q4, review_endpoint
    from tests.unit.test_revenue_q4_continuity import inputs, link

    artifact, sha = calendar_input(tmp_path)
    calendar = FiscalCalendarRegistry.load(artifact, expected_sha256=sha).calendars[0]
    rows = inputs()
    rows[0].update(context_start_date=calendar.boundaries[0], context_end_date=calendar.boundaries[4], context_duration_days=364)
    rows[1].update(context_start_date=calendar.boundaries[0], context_end_date=calendar.boundaries[3], context_duration_days=252)
    # Fixture observation identity is company1/FY2025; review endpoint is separate permission.
    approved = link(rows)
    approved["period"].update(period_start=calendar.boundaries[3], period_end=calendar.boundaries[4])
    assert not derive_reviewed_q4(rows, [approved], cutoff=calendar.financial_as_of)[0]
    derived, held = derive_reviewed_q4(rows, [approved], cutoff=calendar.financial_as_of, calendar=calendar)
    assert not held
    assert derived[0]["fiscal_calendar_proof"]["calendar_id"] == calendar.calendar_id
    assert "reviewed-calendar-v1" in derived[0]["derivation_rule_version"]
    rows[1]["basis_version"] = "different"
    approved["ytd9"] = review_endpoint(rows[1])
    assert not derive_reviewed_q4(rows, [approved], cutoff=calendar.financial_as_of, calendar=calendar)[0]
