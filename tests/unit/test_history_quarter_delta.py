from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pytest
from test_history_quarters import _cell

from sec_xbrl.analytics import history_quarters as quarters


class _Sequence(list):
    pass


class _Spill:
    def sequence(self):
        return _Sequence()

    @staticmethod
    def resolve(locator):
        return locator["cell"], locator["column"], locator["row"]


def _locator(kind: str, amount: str, end: str, *, unchanged: bool) -> dict:
    cell = _cell(kind, amount, end)
    cell.update(
        fiscal_time_series_cell_id=f"cell:{kind}",
        fiscal_time_series_column_id=f"column:{kind}",
        fiscal_time_series_row_id="row",
        definition={"analysis_line_id": "line"},
    )
    return {
        "cell": cell,
        "column": {
            "fiscal_time_series_column_id": f"column:{kind}",
            "fiscal_year": 2025,
            "fiscal_quarter": {"QTD_3M": 1, "YTD_6M": 2}[kind],
            "fiscal_year_end_as_filed": "--12-31",
        },
        "row": {"fiscal_time_series_row_id": "row"},
        "inputs_unchanged": unchanged,
    }


def _target() -> dict:
    return {
        "table": {"cik": "0000000001"},
        "extra_columns": {},
        "extra_rows": {},
        "extra_cells": _Sequence(),
    }


def test_delta_typed_comparison_preserves_scalar_types_and_schema_padding() -> None:
    assert quarters._delta_typed_equal({"a": [1], "b": None}, {"a": (1,)})
    assert not quarters._delta_typed_equal({"a": True}, {"a": 1})
    assert not quarters._delta_typed_equal({"a": 1}, {"a": 1.0})
    assert not quarters._delta_typed_equal(
        {"candidate_lineage": [{"fact": "old"}]},
        {"candidate_lineage": [{"fact": "new"}]},
    )


def test_delta_inputs_require_private_current_publication_capability(tmp_path) -> None:
    roots = {name: tmp_path / name for name in ("t1", "t2", "t3", "t4")}
    capability = quarters._QuarterDeltaCapability(
        token=quarters._QUARTER_DELTA_TOKEN,
        publication=(tmp_path / "current").absolute(),
        publication_manifest_sha256="manifest",
        previous_history=Path("/previous/final"),
        previous_reported=Path("/previous/reported"),
        dirty_period_classes=frozenset({"QTD_3M"}),
        new_focus_keys=frozenset({("0000000001", 2025, 3, "QTD_3M")}),
        input_fingerprint="current-input",
        operational_roots=tuple(
            sorted((name, str(path.absolute())) for name, path in roots.items())
        ),
        producer_code_identity="code",
    )
    expected = (
        capability.previous_history,
        capability.previous_reported,
        capability.dirty_period_classes,
        capability.new_focus_keys,
    )
    assert quarters._quarter_delta_inputs(
        capability,
        publication=tmp_path / "current",
        publication_manifest_sha256="manifest",
        input_fingerprint="current-input",
        operational_roots=roots,
    ) == expected
    assert quarters._quarter_delta_inputs(
        None,
        publication=tmp_path / "current",
        publication_manifest_sha256="manifest",
        input_fingerprint="current-input",
        operational_roots=roots,
    ) is None
    payload = {
        "dirty_period_classes": ["QTD_3M"],
        "history_policy_unchanged": True,
        "t3_mode": "STAGE_PRESERVING_MERGE",
        "quarter_fast_input_proof": {
            "proven": True,
            "graph_scope_isolated": True,
        },
    }
    assert quarters._quarter_delta_scope_matches(payload, frozenset({"QTD_3M"}))
    assert not quarters._quarter_delta_scope_matches(
        payload, frozenset({"FY", "QTD_3M"})
    )
    assert not quarters._quarter_delta_scope_matches(
        {**payload, "history_policy_unchanged": False},
        frozenset({"QTD_3M"}),
    )
    assert quarters._quarter_delta_inputs(
        capability,
        publication=tmp_path / "current",
        publication_manifest_sha256="manifest",
        input_fingerprint="changed-t1-input",
        operational_roots=roots,
    ) is None


def test_delta_derivation_reuses_exact_unchanged_cell_and_counts_removal(tmp_path) -> None:
    spill = _Spill()
    key = ("TEST", "AS_FILED", "QTD_3M")
    later = _locator("YTD_6M", "100", "2025-07-01", unchanged=False)
    earlier = _locator("QTD_3M", "70", "2025-04-01", unchanged=False)
    grouped = {
        ("TEST", "AS_FILED"): {
            (2025, "YTD_6M", quarters._scope(later["cell"]["value_lineage"])): [later],
            (2025, "QTD_3M", quarters._scope(earlier["cell"]["value_lineage"])): [earlier],
        }
    }
    first_target = _target()
    first_metrics = defaultdict(int)
    derived = quarters._derive_quarter_targets(
        {key: first_target},
        grouped,
        {key: set()},
        spill,
        delta_metrics=first_metrics,
    )
    prior_metric = deepcopy(derived[0])
    prior_cell = deepcopy(first_target["extra_cells"][0])
    metric_id = prior_metric["derived_metric_id"]
    assert first_metrics["derived_recomputed_cells"] == 1

    later["inputs_unchanged"] = True
    earlier["inputs_unchanged"] = True
    reused_target = _target()
    reused_metrics = defaultdict(int)
    reused = quarters._derive_quarter_targets(
        {key: reused_target},
        grouped,
        {key: set()},
        spill,
        prior_derived_cells={metric_id: prior_cell},
        prior_derived_metrics={metric_id: prior_metric},
        delta_metrics=reused_metrics,
    )
    assert tuple(reused) == (prior_metric,)
    assert tuple(reused_target["extra_cells"]) == (prior_cell,)
    assert reused_metrics["derived_reused_cells"] == 1
    assert reused_metrics["derived_recomputed_cells"] == 0
    assert reused_metrics["derived_removed_cells"] == 0

    removed_metrics = defaultdict(int)
    quarters._derive_quarter_targets(
        {key: _target()},
        {},
        {key: set()},
        spill,
        prior_derived_cells={metric_id: prior_cell},
        prior_derived_metrics={metric_id: prior_metric},
        delta_metrics=removed_metrics,
    )
    assert removed_metrics["derived_removed_cells"] == 1

    spill_root = tmp_path / "spill"
    spill_root.mkdir()
    actual_spill = quarters._QuarterSpill(spill_root)
    try:
        records = actual_spill.sequence()
        routed = {}
        for name, locator in (("later", later), ("earlier", earlier)):
            index = len(records)
            records.append(
                {
                    "cell": locator["cell"],
                    "column": locator["column"],
                    "row": locator["row"],
                    "inputs_unchanged": True,
                }
            )
            routed[name] = {
                "additive": records.mapping.bucket,
                "cell_key": index,
                "inputs_unchanged": True,
            }
        actual_grouped = {
            ("TEST", "AS_FILED"): {
                (2025, "YTD_6M", quarters._scope(later["cell"]["value_lineage"])): [
                    routed["later"]
                ],
                (2025, "QTD_3M", quarters._scope(earlier["cell"]["value_lineage"])): [
                    routed["earlier"]
                ],
            }
        }
        actual_target = _target()
        actual_metrics = defaultdict(int)
        quarters._derive_quarter_targets(
            {key: actual_target},
            actual_grouped,
            {key: set()},
            actual_spill,
            prior_derived_cells={metric_id: prior_cell},
            prior_derived_metrics={metric_id: prior_metric},
            delta_metrics=actual_metrics,
        )
        assert actual_metrics["derived_reused_cells"] == 1
        assert actual_metrics["derived_recomputed_cells"] == 0
    finally:
        actual_spill.close()

    corrupted = {**prior_cell, "fiscal_time_series_column_id": "foreign-column"}
    with pytest.raises(quarters._QuarterDeltaFallback, match="derived cell binding"):
        quarters._derive_quarter_targets(
            {key: _target()},
            grouped,
            {key: set()},
            spill,
            prior_derived_cells={metric_id: corrupted},
            prior_derived_metrics={metric_id: prior_metric},
            delta_metrics=defaultdict(int),
        )


def test_delta_native_reuse_filters_derived_and_rebinds_only_publication(tmp_path) -> None:
    root = tmp_path / "previous"
    source = root / "cells.parquet"
    direct = _cell("QTD_3M", "10", "2025-04-01")
    direct.update(
        fiscal_time_series_cell_id="reported",
        fiscal_time_series_row_id="row",
        fiscal_time_series_column_id="column",
        value_status="REPORTED",
        prior_candidate_publication="/old/publication",
    )
    derived = deepcopy(direct)
    derived.update(
        fiscal_time_series_cell_id="derived",
        value_status="DERIVED",
        prior_candidate_publication=None,
    )
    plan = quarters._stage_records(source, (direct, derived))
    try:
        info = {
            **quarters._finalize_staged_records(plan),
            "path": "cells.parquet",
        }
    finally:
        plan.cleanup()

    publication = tmp_path / "current"
    result = quarters._delta_stage_reused_cells(
        root,
        info,
        tmp_path / "owned" / "direct.parquet",
        publication=publication,
    )
    rows = tuple(
        quarters._iter_history_records(result["path"], result)
    )
    assert result["count"] == 1
    assert rows[0]["fiscal_time_series_cell_id"] == "reported"
    assert rows[0]["prior_candidate_publication"] == str(publication.absolute())
    assert rows[0]["value_lineage"] == direct["value_lineage"]

    with pytest.raises(quarters._QuarterDeltaFallback, match="declaration changed"):
        quarters._delta_stage_reused_cells(
            root,
            {**info, "count": 3},
            tmp_path / "owned" / "bad.parquet",
            publication=publication,
        )
