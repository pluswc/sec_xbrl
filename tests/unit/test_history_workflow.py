from __future__ import annotations

import gc
import json
import weakref
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from sec_xbrl import history
from sec_xbrl.analytics import FiscalTimeSeriesQuery
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.longitudinal import MAPPING_VERSION, Layer1SnapshotInput, Layer2Run


def test_history_run_uses_active_mapping_policy_in_its_fingerprint() -> None:
    rules = history._history_layer2_rule_versions()
    layer1 = Layer1SnapshotInput(
        cik="0000320193",
        accession="0000320193-26-000020",
        form="10-Q",
        filed_date="2026-05-01",
        report_date="2026-03-28",
        snapshot_id="0000320193/000032019326000020",
        manifest_sha256="a" * 64,
        parser_version="m2-layer1-v5",
    )
    current = Layer2Run("history-v4", "history-corpus", (layer1,), rules)
    legacy = Layer2Run(
        "history-v4",
        "history-corpus",
        (layer1,),
        replace(rules, mapping_version="mapping-custom-network-v3"),
    )

    assert current.rules.mapping_version == MAPPING_VERSION == "l2-m2-company-canonical-v4"
    assert current.fingerprint != legacy.fingerprint


def _history_reuse_fixture(tmp_path: Path) -> tuple[Path, Layer2Run, dict]:
    filing = {
        "cik": "0000320193",
        "accession": "0000320193-26-000020",
        "form": "10-Q",
        "filed_date": "2026-05-01",
        "report_date": "2026-03-28",
    }
    plan = {
        "companies": [{"ticker": "AAPL", "cik": filing["cik"], "filings": [filing]}]
    }
    intake = {
        "complete": True,
        "plan": plan,
        "filings": [
            {
                "ticker": "AAPL",
                "filing": filing,
                "source_run": str(tmp_path / "source"),
                "status": "REUSED",
            }
        ],
    }
    intake_path = tmp_path / "intake.json"
    history._write_json(intake_path, intake)
    layer1 = Layer1SnapshotInput(
        cik=filing["cik"],
        accession=filing["accession"],
        form=filing["form"],
        filed_date=filing["filed_date"],
        report_date=filing["report_date"],
        snapshot_id="0000320193/000032019326000020",
        manifest_sha256="a" * 64,
    )
    run = Layer2Run("AAPL", "AAPL", (layer1,), history._history_layer2_rule_versions())
    return intake_path, run, plan


def test_completed_history_reuse_rejects_old_mapping_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sec_xbrl import longitudinal

    intake_path, run, plan = _history_reuse_fixture(tmp_path)
    output = tmp_path / "history" / "AAPL"
    (output / "reported-panels").mkdir(parents=True)
    old_fingerprint = replace(
        run, rules=replace(run.rules, mapping_version="mapping-custom-network-v3")
    ).fingerprint
    fake_release = SimpleNamespace(layer2_run=run, snapshots=())
    monkeypatch.setattr(
        longitudinal,
        "CohortReleaseAdapter",
        lambda: SimpleNamespace(load=lambda *args, **kwargs: fake_release),
    )
    monkeypatch.setattr(
        history,
        "HistoryPublicationReader",
        lambda root: SimpleNamespace(
            manifest={
                "plan": plan,
                "views": ["AS_FILED", "LATEST_REPORTED"],
                "input_fingerprint": old_fingerprint,
            },
            verify_all=lambda: None,
        ),
    )
    before = sorted(path.relative_to(output) for path in output.rglob("*"))

    with pytest.raises(ValueError, match="different inputs or active rules"):
        history.build_history(intake_manifest=intake_path, output_root=output)

    assert sorted(path.relative_to(output) for path in output.rglob("*")) == before


def test_partial_history_reuse_rejects_old_mapping_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sec_xbrl import longitudinal

    intake_path, run, _plan = _history_reuse_fixture(tmp_path)
    output = tmp_path / "history" / "AAPL"
    (output / "t1" / "AAPL").mkdir(parents=True)
    fake_release = SimpleNamespace(layer2_run=run, snapshots=())
    monkeypatch.setattr(
        longitudinal,
        "CohortReleaseAdapter",
        lambda: SimpleNamespace(load=lambda *args, **kwargs: fake_release),
    )
    monkeypatch.setattr(
        longitudinal,
        "Layer2PublicationReader",
        lambda: SimpleNamespace(
            load=lambda root: SimpleNamespace(
                identity={"layer2_run_fingerprint": "legacy-fingerprint"}
            )
        ),
    )
    before = sorted(path.relative_to(output) for path in output.rglob("*"))

    with pytest.raises(ValueError, match="different inputs or active rules"):
        history.build_history(intake_manifest=intake_path, output_root=output)

    assert sorted(path.relative_to(output) for path in output.rglob("*")) == before


def test_completed_history_reuse_accepts_exact_active_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sec_xbrl import longitudinal

    intake_path, run, plan = _history_reuse_fixture(tmp_path)
    output = tmp_path / "history" / "AAPL"
    roots = {name: output / name / "AAPL" for name in ("t1", "t2", "t3", "t4")}
    for root in roots.values():
        root.mkdir(parents=True)
    (output / "reported-panels").mkdir()
    (output / "panels").mkdir()
    fake_release = SimpleNamespace(layer2_run=run, snapshots=())
    monkeypatch.setattr(
        longitudinal,
        "CohortReleaseAdapter",
        lambda: SimpleNamespace(load=lambda *args, **kwargs: fake_release),
    )
    monkeypatch.setattr(
        longitudinal,
        "Layer2PublicationReader",
        lambda: SimpleNamespace(
            load=lambda root: SimpleNamespace(
                identity={"layer2_run_fingerprint": run.fingerprint}
            )
        ),
    )
    manifest = {
        "plan": plan,
        "views": ["AS_FILED", "LATEST_REPORTED"],
        "input_fingerprint": run.fingerprint,
        "operational_roots": {name: str(root.resolve()) for name, root in roots.items()},
    }
    monkeypatch.setattr(
        history,
        "HistoryPublicationReader",
        lambda root: SimpleNamespace(manifest=manifest, verify_all=lambda: None),
    )

    assert history.build_history(intake_manifest=intake_path, output_root=output) == output / "panels"


def test_completed_history_releases_raw_cohort_before_quarter_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sec_xbrl import longitudinal
    from sec_xbrl.analytics import history_quarters

    intake_path, run, plan = _history_reuse_fixture(tmp_path)
    output = tmp_path / "history" / "AAPL"
    roots = {name: output / name / "AAPL" for name in ("t1", "t2", "t3", "t4")}
    for root in roots.values():
        root.mkdir(parents=True)
    (output / "reported-panels").mkdir()
    filing = plan["companies"][0]["filings"][0]

    class TrackedSnapshot:
        def __init__(self) -> None:
            self.input = SimpleNamespace(cik=filing["cik"], accession=filing["accession"])

        def records(self, table: str) -> tuple[dict, ...]:
            assert table == "filing"
            return (filing,)

    class TrackedRelease:
        def __init__(self, snapshot: TrackedSnapshot) -> None:
            self.layer2_run = run
            self.snapshots = (snapshot,)

    snapshot = TrackedSnapshot()
    release = TrackedRelease(snapshot)
    release_ref = weakref.ref(release)
    snapshot_ref = weakref.ref(snapshot)
    holder = {"release": release}
    del release, snapshot

    monkeypatch.setattr(
        longitudinal,
        "CohortReleaseAdapter",
        lambda: SimpleNamespace(load=lambda *args, **kwargs: holder.pop("release")),
    )
    monkeypatch.setattr(
        longitudinal,
        "Layer2PublicationReader",
        lambda: SimpleNamespace(
            load=lambda root: SimpleNamespace(
                identity={"layer2_run_fingerprint": run.fingerprint}
            )
        ),
    )
    manifest = {
        "plan": plan,
        "views": ["AS_FILED", "LATEST_REPORTED"],
        "input_fingerprint": run.fingerprint,
        "operational_roots": {name: str(root.resolve()) for name, root in roots.items()},
    }
    monkeypatch.setattr(
        history,
        "HistoryPublicationReader",
        lambda root: SimpleNamespace(manifest=manifest, verify_all=lambda: None),
    )

    def publish(**kwargs):
        gc.collect()
        assert release_ref() is None
        assert snapshot_ref() is None
        assert kwargs["reuse_roots"] is True
        return output / "panels"

    monkeypatch.setattr(history_quarters, "publish_quarter_history", publish)

    assert history.build_history(intake_manifest=intake_path, output_root=output) == output / "panels"


def test_operational_preflight_does_not_retain_last_partial_root(
    tmp_path: Path,
) -> None:
    references: list[weakref.ReferenceType] = []

    class Publication:
        def __init__(self) -> None:
            self.identity = {"layer2_run_fingerprint": "active"}

    class Reader:
        @staticmethod
        def load(_root: Path) -> Publication:
            publication = Publication()
            references.append(weakref.ref(publication))
            return publication

    roots = {name: tmp_path / name for name in ("t1", "t2", "t3")}
    for root in roots.values():
        root.mkdir()
    history._validate_existing_operational_roots(Reader(), roots, "active")
    gc.collect()
    assert references and all(reference() is None for reference in references)


def test_active_root_validation_does_not_retain_loop_alias() -> None:
    references: list[weakref.ReferenceType] = []

    class Publication:
        def __init__(self) -> None:
            self.identity = {"layer2_run_fingerprint": "active"}

    def validate() -> None:
        publications = tuple(Publication() for _ in range(4))
        references.extend(weakref.ref(publication) for publication in publications)
        history._validate_active_publications(publications, "active")

    validate()
    gc.collect()
    assert all(reference() is None for reference in references)


def test_observation_and_ledger_inputs_release_after_complete_small_copies() -> None:
    class Publication:
        is_reader_attested = True

        def __init__(self, datasets: dict, ciks: tuple[str, ...]) -> None:
            self.datasets = MappingProxyType(
                {
                    name: tuple(MappingProxyType(dict(row)) for row in rows)
                    for name, rows in datasets.items()
                }
            )
            self.input_ciks = ciks

        def records(self, dataset: str) -> tuple[dict, ...]:
            return tuple(dict(row) for row in self.datasets[dataset])

    observations = Publication(
        {
            "reported_period_observation": (
                {
                    "cik": "1",
                    "fiscal_year": 2025,
                    "fiscal_quarter": None,
                    "period_class": "FY",
                    "comparative_type": "CURRENT_FOCUS",
                    "evidence": {"sources": ["fact-current"]},
                },
                {
                    "cik": "1",
                    "fiscal_year": 2024,
                    "fiscal_quarter": None,
                    "period_class": "FY",
                    "comparative_type": "PRIOR_COMPARATIVE",
                },
                {
                    "cik": "2",
                    "fiscal_year": 2025,
                    "fiscal_quarter": 1,
                    "period_class": "QTD_3M",
                    "comparative_type": "CURRENT_FOCUS",
                },
            )
        },
        ("1", "2"),
    )
    observation_reference = weakref.ref(observations)
    periods, comparative_counts = history._partition_current_observations(observations)
    del observations
    gc.collect()
    assert observation_reference() is None
    assert comparative_counts == {"1": 1}
    assert set(periods) == {("1", 2025, None, "FY"), ("2", 2025, 1, "QTD_3M")}
    assert periods[("1", 2025, None, "FY")][0]["evidence"] == {
        "sources": ["fact-current"]
    }

    ledger_publication = Publication(
        {
            "accession_version_ledger": (
                {"cik": "1", "filed_date": "2025-01-01", "accession": "a"},
                {"cik": "2", "filed_date": "2025-01-02", "accession": "b"},
            )
        },
        ("1", "2"),
    )
    ledger_reference = weakref.ref(ledger_publication)
    ledgers = history._company_ledgers(ledger_publication, ("1", "2"))
    del ledger_publication
    gc.collect()
    assert ledger_reference() is None
    assert [row["accession"] for row in ledgers["1"]] == ["a"]
    assert [row["accession"] for row in ledgers["2"]] == ["b"]


def test_report_window_and_as_of_are_independent() -> None:
    original = FilingRef("0000000001", "0000000001-24-000001", "10-Q", date(2024, 5, 1), date(2024, 3, 31))
    amendment = FilingRef("0000000001", "0000000001-24-000002", "10-Q/A", date(2024, 6, 1), date(2024, 3, 31))
    args = {"report_start": date(2024, 1, 1), "report_end": date(2024, 3, 31)}
    assert history.select_history_filings((original, amendment), as_of=date(2024, 5, 31), **args) == (original,)
    assert history.select_history_filings((original, amendment), as_of=date(2024, 6, 1), **args) == (original, amendment)
    with pytest.raises(ValueError, match="exclusively"):
        history.select_history_filings((original,), as_of=date(2024, 6, 1), recent_fiscal_years=3, **args)
    with pytest.raises(ValueError, match="exclusively"):
        history.select_history_filings((original,), as_of=date(2024, 6, 1), recent_fiscal_years=3, report_start=date(2024, 1, 1))


def test_expected_quarters_do_not_fabricate_future_history() -> None:
    keys = [("1", 2024, None, "FY"), ("1", 2024, 3, "YTD_9M"), ("1", 2025, 2, "QTD_3M")]
    periods = history._expected_quarters(keys)
    assert [(p.fiscal_year, p.fiscal_quarter) for p in periods] == [(2024, 1), (2024, 2), (2024, 3), (2024, 4), (2025, 1), (2025, 2)]


def test_incomplete_intake_cannot_be_published() -> None:
    with pytest.raises(ValueError, match="all planned"):
        history._validate_intake({"plan": {"companies": [{"cik": "1", "filings": [{"accession": "a"}]}]}, "filings": [], "complete": False})


def test_parquet_publication_reload_retains_nested_lineage_and_detects_corruption(tmp_path: Path) -> None:
    records = {"columns": ({"fiscal_time_series_column_id": "c", "column_status": "UNAVAILABLE", "column_reason": "DERIVATION_NOT_MATERIALIZED"},),
               "rows": ({"fiscal_time_series_row_id": "r", "evidence": {"sources": ["raw-fact"]}},), "cells": ()}
    files = {}
    for name, rows in records.items():
        path = tmp_path / f"{name}.parquet"
        files[name] = {**history._write_records(path, rows), "path": path.name}
    history._write_json(tmp_path / "history_manifest.json", {"version": history.HISTORY_VERSION, "tables": [{"ticker": "TEST", "period_class": "QTD_3M", "view": "LATEST_REPORTED", "scope": {}, "files": files}]})
    reader = history.HistoryPublicationReader(tmp_path)
    reader.verify_all()
    result = reader.load(ticker="test")
    assert result.rows[0]["evidence"] == {"sources": ["raw-fact"]}
    assert FiscalTimeSeriesQuery(result).matrix()[0]["cells"][0]["value_status"] == "UNAVAILABLE"
    (tmp_path / "rows.parquet").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="integrity"):
        reader.load(ticker="TEST")


def test_bounded_record_writer_matches_legacy_global_schema_and_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    records = tuple(
        {
            "id": index,
            "all_null": None,
            "bool_value": index % 2 == 0,
            "decimal_value": Decimal("1.20") if index == 0 else index,
            **({"json_mixed": "null"} if index == 0 else {}),
            **({"missing_early": "present"} if index == 1 else {}),
            **(
                {
                    "json_mixed": {
                        "candidate_lineage": [
                            {
                                "fact": "late",
                                "paths": [["root", "child"], ["root", "other"]],
                            }
                        ]
                    },
                    "late_column": 2**100,
                }
                if index == history._RECORD_WRITE_BATCH_SIZE
                else {}
            ),
            **(
                {"json_mixed": [True, None, Decimal("3.40")]}
                if index == history._RECORD_WRITE_BATCH_SIZE + 1
                else {}
            ),
        }
        for index in range(history._RECORD_WRITE_BATCH_SIZE + 2)
    )
    legacy_path = tmp_path / "legacy.parquet"
    legacy_json_fields = sorted(
        {
            key
            for row in records
            for key, value in row.items()
            if isinstance(value, (dict, list, tuple))
        }
    )
    legacy_encoded = [
        {
            key: json.dumps(value, sort_keys=True, default=str)
            if key in legacy_json_fields and value is not None
            else value
            for key, value in row.items()
        }
        for row in records
    ]
    pl.from_dicts(legacy_encoded, infer_schema_length=None).write_parquet(legacy_path)

    original_from_dicts = pl.from_dicts
    observed_batch_sizes: list[int] = []

    def observed_from_dicts(rows, *args, **kwargs):
        observed_batch_sizes.append(len(rows))
        return original_from_dicts(rows, *args, **kwargs)

    monkeypatch.setattr(pl, "from_dicts", observed_from_dicts)
    bounded_path = tmp_path / "bounded.parquet"
    info = history._write_records(bounded_path, records)
    legacy_frame = pl.read_parquet(legacy_path)
    bounded_frame = pl.read_parquet(bounded_path)

    assert info["json_fields"] == legacy_json_fields == ["json_mixed"]
    assert bounded_frame.schema == legacy_frame.schema
    assert bounded_frame.to_dicts() == legacy_frame.to_dicts()
    assert len(observed_batch_sizes) == 4
    assert max(observed_batch_sizes) == history._RECORD_WRITE_BATCH_SIZE
    decoded = tuple(
        {
            key: json.loads(value)
            if key in info["json_fields"] and value is not None
            else value
            for key, value in row.items()
        }
        for row in bounded_frame.to_dicts()
    )
    assert decoded[0]["json_mixed"] == "null"
    assert decoded[history._RECORD_WRITE_BATCH_SIZE]["late_column"] == 2**100
    assert decoded[history._RECORD_WRITE_BATCH_SIZE]["json_mixed"][
        "candidate_lineage"
    ][0]["paths"] == [["root", "child"], ["root", "other"]]
    assert decoded[-1]["json_mixed"] == [True, None, "3.40"]


@pytest.mark.parametrize(
    ("leading", "expected"),
    (
        ((1, 1.5), ("1", "1.5")),
        ((True, 2), ("true", "2")),
        ((2**53 + 1, 1.5), ("9007199254740993", "1.5")),
    ),
)
def test_bounded_record_writer_uses_global_schema_before_scalar_coercion(
    tmp_path: Path, leading: tuple[object, object], expected: tuple[str, str]
) -> None:
    import polars as pl

    records = (
        ({"x": leading[0]}, {"x": leading[1]})
        + ({"x": None},) * (history._RECORD_WRITE_BATCH_SIZE - 2)
        + ({"x": "late"},)
    )
    legacy = pl.from_dicts(records, infer_schema_length=None)
    path = tmp_path / "bounded-scalar-promotion.parquet"
    history._write_records(path, records)
    bounded = pl.read_parquet(path)

    assert bounded.schema == legacy.schema
    assert bounded.to_dicts() == legacy.to_dicts()
    assert tuple(row["x"] for row in bounded.head(2).to_dicts()) == expected


def test_bounded_record_writer_matches_legacy_empty_and_all_null(
    tmp_path: Path,
) -> None:
    import polars as pl

    for name, records in (
        ("empty", ()),
        ("all-null", ({"field": None}, {"field": None})),
    ):
        legacy_path = tmp_path / f"legacy-{name}.parquet"
        bounded_path = tmp_path / f"bounded-{name}.parquet"
        legacy_frame = (
            pl.from_dicts(records, infer_schema_length=None)
            if records
            else pl.DataFrame()
        )
        legacy_frame.write_parquet(legacy_path)
        history._write_records(bounded_path, records)
        assert pl.read_parquet(bounded_path).schema == pl.read_parquet(
            legacy_path
        ).schema
        assert pl.read_parquet(bounded_path).to_dicts() == pl.read_parquet(
            legacy_path
        ).to_dicts()


def test_schema_inference_never_serializes_nested_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle: list[object] = []
    cycle.append(cycle)

    def reject_json_encoding(*args, **kwargs):
        raise AssertionError("schema inference must not JSON encode payloads")

    monkeypatch.setattr(history.json, "dumps", reject_json_encoding)
    batch = history._schema_record_batch(
        (
            {
                "candidate_lineage": cycle,
                "scalar_text": "large text" * 1_000,
                "amount": Decimal("1.20"),
                "missing": None,
            },
        ),
        ["candidate_lineage"],
    )

    assert batch == [
        {
            "candidate_lineage": "",
            "scalar_text": "",
            "amount": Decimal("1.20"),
            "missing": None,
        }
    ]


def test_final_encoding_bounds_rows_and_bytes_with_single_row_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(history, "_RECORD_WRITE_BATCH_SIZE", 3)
    monkeypatch.setattr(history, "_RECORD_WRITE_BATCH_BYTES", 140)
    records = (
        {"id": "one", "nested": {"payload": "a" * 30}},
        {"id": "two", "nested": {"payload": "b" * 30}},
        {"id": "oversized", "nested": {"payload": "c" * 150}},
        {"id": "four", "nested": {"payload": "d" * 30}},
    )

    batches = list(history._iter_encoded_record_batches(records, ["nested"]))

    assert [len(batch) for batch, _size in batches] == [2, 1, 1]
    assert all(
        size <= history._RECORD_WRITE_BATCH_BYTES or len(batch) == 1
        for batch, size in batches
    )
    assert max(len(batch) for batch, _size in batches) <= 3
    assert [row["id"] for batch, _size in batches for row in batch] == [
        "one",
        "two",
        "oversized",
        "four",
    ]


def test_cyclic_json_payload_keeps_legacy_failure_class_and_no_output(
    tmp_path: Path,
) -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    path = tmp_path / "cyclic.parquet"

    with pytest.raises(ValueError, match="Circular reference detected"):
        history._write_records(path, ({"nested": cycle},))

    assert not path.exists()
    assert not list(tmp_path.glob(".cyclic.parquet.chunks-*"))


@pytest.mark.parametrize("invalid", ({1, 2}, object()))
def test_invalid_scalar_keeps_legacy_parquet_failure_class(
    tmp_path: Path, invalid: object
) -> None:
    import polars as pl

    legacy_path = tmp_path / "legacy-invalid.parquet"
    bounded_path = tmp_path / "bounded-invalid.parquet"
    with pytest.raises(pl.exceptions.ComputeError) as legacy_error:
        pl.from_dicts(({"invalid": invalid},), infer_schema_length=None).write_parquet(
            legacy_path
        )
    with pytest.raises(type(legacy_error.value)):
        history._write_records(bounded_path, ({"invalid": invalid},))


def test_fiscal_time_series_inputs_release_before_serialization() -> None:
    class PanelInput:
        pass

    class Builder:
        @staticmethod
        def build(*, inputs, expected_periods):
            assert len(inputs) == 1
            assert expected_periods == []
            return SimpleNamespace(columns=(), rows=(), cells=(), scope={})

    panel_input = PanelInput()
    reference = weakref.ref(panel_input)
    inputs = [panel_input]
    del panel_input
    result = history._build_fiscal_time_series(Builder(), inputs, [])
    gc.collect()

    assert inputs == []
    assert reference() is None
    assert result.cells == ()


def test_intake_bootstrap_is_after_offline_failure_with_unique_paths_and_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = FilingRef("0000000001", "0000000001-24-000001", "10-Q", date(2024, 5, 1), date(2024, 3, 31))
    plan = {"companies": [{"ticker": "TEST", "cik": ref.cik, "filings": [history._ref_record(ref)]}]}
    plan_path = tmp_path / "plan.json"
    history._write_json(plan_path, plan)
    output = tmp_path / "output"
    history._write_json(output / "history_intake.json", {"plan": plan, "complete": False, "filings": [{"old": "failure"}]})
    events = []
    class Loader:
        def __init__(self, **kwargs):
            pass

        @staticmethod
        def bootstrap_taxonomy_cache(resolved, destination, taxonomy_cache):
            events.append(("bootstrap", destination))
            return SimpleNamespace(close=lambda: events.append(("close", None)))

    class Ingestor:
        def __init__(self, root):
            pass

        def load_and_ingest(self, resolved, loader, destination):
            events.append(("offline", destination))
            if len(events) == 1:
                raise ValueError("missing taxonomy")

        def _validate_model(self, model):
            pass

        def snapshot_dir(self, resolved):
            return tmp_path

    monkeypatch.setenv("SEC_USER_AGENT", "unit-test-only")
    monkeypatch.setattr(history, "ArelleFilingLoader", Loader)
    monkeypatch.setattr(history, "Layer1Ingestor", Ingestor)
    monkeypatch.setattr(history, "FilingPackageResolver", lambda *args: SimpleNamespace(resolve=lambda *args: object()))
    monkeypatch.setattr(history, "_load_declared_cohort_snapshot", lambda *args: SimpleNamespace(records=lambda name: (history._ref_record(ref),)))
    path = history.ingest_history(plan_path=plan_path, source_runs=(), output_run=output,
                                 package_cache=tmp_path / "packages", index_cache=tmp_path / "index",
                                 taxonomy_cache=tmp_path / "taxonomy", bootstrap_taxonomy=True)
    assert json.loads(path.read_text())["complete"] is True
    assert [event[0] for event in events] == ["offline", "bootstrap", "close", "offline"]
    assert len({event[1] for event in events if event[1] is not None}) == 3
    audit = list((output / "history_attempts").glob("manifest-*.json"))
    assert json.loads(audit[0].read_text())["filings"] == [{"old": "failure"}]


def test_snapshot_metadata_must_match_plan() -> None:
    original = {"cik": "1", "accession": "a", "form": "10-Q", "filed_date": "2024-05-01", "report_date": "2024-03-31"}
    snapshot = SimpleNamespace(records=lambda name: (original,))
    history._validate_snapshot_plan(snapshot, original)
    with pytest.raises(ValueError, match="metadata"):
        history._validate_snapshot_plan(snapshot, {**original, "filed_date": "2024-04-01"})


def test_offline_arbitrary_ticker_discovery_reuses_immutable_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"cik": "1234", "tickers": ["EXAMPLE"], "name": "Offline Fixture Company", "filings": {"recent": {
        "accessionNumber": ["0000001234-24-000001"], "form": ["10-Q"],
        "filingDate": ["2024-05-01"], "reportDate": ["2024-03-31"],
        "primaryDocument": ["example.htm"], "isXBRL": [1], "isInlineXBRL": [1],
    }}}
    submissions = tmp_path / "submissions"
    history._write_json(submissions / "example.json", payload)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    kwargs = {"workspace": tmp_path / "workspace", "tickers": ("example",),
              "as_of": date(2024, 6, 1), "submissions_roots": (submissions,), "offline": True,
              "report_start": date(2024, 1, 1), "report_end": date(2024, 3, 31)}
    path = history.discover_history(**kwargs)
    before = path.read_bytes()
    assert json.loads(before)["companies"][0]["cik"] == "0000001234"
    assert json.loads(before)["companies"][0]["ticker"] == "EXAMPLE"
    assert history.discover_history(**kwargs).read_bytes() == before
    with pytest.raises(ValueError, match="different scope"):
        history.discover_history(**{**kwargs, "as_of": date(2024, 7, 1)})
    assert path.read_bytes() == before


def test_coverage_annual_completion_requires_annual_filing_focus() -> None:
    filings = ({"cik": "1", "form": "10-K", "document_fiscal_year_focus": "2025", "document_fiscal_period_focus": "FY"},
               {"cik": "1", "form": "10-Q", "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "Q2"},
               {"cik": "1", "form": "10-Q", "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "FY"})
    keys = history._filing_coverage_keys(filings, "1")
    assert [(p.fiscal_year, p.fiscal_quarter) for p in history._expected_quarters(keys)] == [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2)]


def test_coverage_repair_preserves_real_cells_and_rejects_plan_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "panels"
    record = {"cik": "1", "accession": "a", "form": "10-Q", "filed_date": "2026-08-01", "report_date": "2026-06-30"}
    plan = {"companies": [{"cik": "1", "filings": [record]}]}
    intake_path = tmp_path / "intake.json"
    history._write_json(intake_path, {"complete": True, "plan": plan, "filings": [{"filing": record, "source_run": str(tmp_path), "status": "REUSED"}]})
    columns = tuple({"fiscal_time_series_column_id": f"q{q}", "fiscal_year": 2026, "fiscal_quarter": q,
                     "column_status": "AVAILABLE" if q == 2 else "MISSING_HISTORY"} for q in (2, 3, 4))
    cells = ({"fiscal_time_series_column_id": "q2", "fiscal_time_series_row_id": "r", "value_numeric": "100"},)
    files = {}
    for name, rows in {"columns": columns, "cells": cells, "rows": ({"fiscal_time_series_row_id": "r"},)}.items():
        files[name] = {**history._write_records(root / f"{name}.parquet", rows), "path": f"{name}.parquet"}
    history._write_json(root / "history_manifest.json", {"version": history.HISTORY_VERSION, "plan": plan,
                        "source_intake": str(intake_path), "tables": [{"ticker": "TEST", "cik": "1", "view": "LATEST_REPORTED", "period_class": "QTD_3M", "scope": {}, "files": files}]})
    monkeypatch.setattr(history, "_load_declared_cohort_snapshot", lambda *args: SimpleNamespace(records=lambda name: ({**record, "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "Q2"},)))
    destination = history.repair_history_coverage(publication=root, destination=tmp_path / "repaired")
    repaired = history.HistoryPublicationReader(destination)
    assert repaired.load(ticker="TEST").cells == cells
    assert len(repaired.load(ticker="TEST").columns) == 1
    assert len(history.HistoryPublicationReader(root).load(ticker="TEST").columns) == 3
    assert repaired.manifest["source_manifest_sha256"]
    wrong = json.loads(intake_path.read_text())
    wrong["plan"]["extra"] = "tamper"
    history._write_json(intake_path, wrong)
    with pytest.raises(ValueError, match="disagrees"):
        history.repair_history_coverage(publication=root, destination=tmp_path / "rejected")
