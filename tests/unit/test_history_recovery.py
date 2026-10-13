from __future__ import annotations

import gc
import hashlib
import json
import shutil
import weakref
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from sec_xbrl import history
from sec_xbrl.analytics import history_quarters as quarters


def _publication(root, records):
    info = {**history._write_records(root / "cells.parquet", records), "path": "cells.parquet"}
    history._write_json(root / "history_manifest.json", {
        "version": history.HISTORY_VERSION, "tables": [{"files": {"cells": info}}],
    })
    reader = history.HistoryPublicationReader(root)
    return reader, reader.manifest["tables"][0]["files"]["cells"]


def test_bounded_verify_decodes_all_fields_all_batches_and_derived(tmp_path, monkeypatch):
    records = tuple({"index": i, "late_json": {"nested": [i, None, True, {"unicode": "가😀"}]},
                     "nullable": None, "scalar": float(i)} for i in range(97))
    reader, info = _publication(tmp_path / "published", records)
    eager = reader._records(info)
    sizes = []
    original = pl.DataFrame.iter_rows

    def observed(frame, *args, **kwargs):
        sizes.append(frame.height)
        yield from original(frame, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "iter_rows", observed)
    monkeypatch.setattr(reader, "_records", lambda _: pytest.fail("eager reader invoked"))
    reader.manifest["derived_quarter"] = info
    reader.verify_all()
    assert max(sizes) <= 32
    assert sum(sizes) == 194
    assert tuple(history._iter_history_records(reader.root / info["path"], info)) == eager == records
    assert type(eager[0]["scalar"]) is float
    assert type(eager[0]["late_json"]["nested"][2]) is bool


@pytest.mark.parametrize("fault", ["json", "count", "hash", "schema"])
def test_bounded_verify_rejects_late_json_count_hash_and_schema(tmp_path, fault):
    root = tmp_path / "published"
    root.mkdir()
    path = root / "cells.parquet"
    pl.DataFrame({"nested": ['{}'] * 64 + ['{bad json']}).write_parquet(path, row_group_size=32)
    info = {"path": path.name, "count": 65, "json_fields": ["nested"], "sha256": history._sha256_file(path)}
    if fault == "count":
        info["count"] = 66
    elif fault == "hash":
        info.update(sha256="0" * 64, count=66)
    elif fault == "schema":
        info["json_fields"] = ["missing"]
    history._write_json(root / "history_manifest.json", {
        "version": history.HISTORY_VERSION, "tables": [{"files": {"cells": info}}],
    })
    match = {"json": "Expecting", "count": "count mismatch", "hash": "integrity mismatch", "schema": "schema mismatch"}[fault]
    with pytest.raises(ValueError, match=match):
        history.HistoryPublicationReader(root).verify_all()


@pytest.mark.parametrize("kind", ["root", "ancestor", "manifest", "file", "parent", "traversal", "partial"])
def test_reader_rejects_unsafe_paths(tmp_path, kind):
    root = tmp_path / "published"
    reader, info = _publication(root, ({"value": [1]},))
    if kind == "root":
        link = tmp_path / "linked"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif kind == "ancestor":
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        root = link / root.name
    elif kind in {"manifest", "file"}:
        path = root / ("history_manifest.json" if kind == "manifest" else "cells.parquet")
        moved = tmp_path / path.name
        path.rename(moved)
        path.symlink_to(moved)
    elif kind == "parent":
        (root / "linked").symlink_to(tmp_path, target_is_directory=True)
        info["path"] = "linked/published/cells.parquet"
    elif kind == "traversal":
        info["path"] = "../published/cells.parquet"
    else:
        moved = tmp_path / ".panels.partial-test"
        root.rename(moved)
        root = moved
    if kind in {"parent", "traversal"}:
        history._write_json(root / "history_manifest.json", reader.manifest)
    with pytest.raises(ValueError):
        history.HistoryPublicationReader(root).verify_all()


def _full_report(proof, stage, *, fixture_kind="SYNTHETIC_TEST"):
    verified_files = []
    for table in proof["tables"]:
        for name in ("columns", "rows", "cells"):
            info = table["files"][name]
            records = list(history._iter_history_records(stage / info["path"], info))
            digest = hashlib.sha256(json.dumps(records, sort_keys=True, default=str).encode()).hexdigest()
            verified_files.append({**info, "ordered_full_record_sha256": digest})
    return {
        "schema_version": "independent-staged-reported-component-audit-v1",
        "verdict": "PASS_STAGED_REPORTED_COMPONENT_ONLY", "fixture_kind": fixture_kind,
        "verification_level": "FULL_STAGED_REPORTED_PASS", "history_ready": False,
        "source_generation_sha": proof["generation_source_identity"],
        "stage_manifest": {"sha256": proof["staged_manifest_sha256"]},
        "source_intake": {"sha256": proof["intake_sha256"]},
        "input_fingerprint": proof["input_fingerprint"],
        "counts": {"tables": len(proof["tables"]), "stage_files": len(verified_files)},
        "full_verification": {key: True for key in (
            "all_reported_files_fully_decoded", "all_ordered_records_hashed", "all_json_fields_decoded",
            "all_physical_hashes_verified", "all_schema_counts_verified")},
        "verified_files": verified_files, "prefix_checks": [],
    }


def _recovery_fixture(tmp_path, monkeypatch):
    stage = tmp_path / ".panels.partial-failed"
    operational = tmp_path / "original"
    roots = {name: str(operational / name / operational.name) for name in ("t1", "t2", "t3", "t4")}
    filing = {"cik": "0000001234", "accession": "a", "form": "10-Q", "filed_date": "2026-08-01", "report_date": "2026-06-30"}
    plan = {"as_of_date": "2026-10-10", "companies": [{"cik": filing["cik"], "ticker": "EXAMPLE", "filings": [filing]}]}
    intake_path = tmp_path / "intake.json"
    history._write_json(intake_path, {"complete": True, "plan": plan, "filings": [{"filing": filing, "status": "REUSED", "source_run": str(tmp_path / "raw")}]})
    tables, expected_tables = [], []
    for view in ("AS_FILED", "LATEST_REPORTED"):
        column = {"fiscal_time_series_column_id": "column", "fiscal_year": 2026, "fiscal_quarter": 2, "period_class": "QTD_3M"}
        records = {
            "columns": (column,),
            "rows": ({"fiscal_time_series_row_id": "row", "nested": {"full": [1, "가", None]}},),
            "cells": ({"fiscal_time_series_cell_id": "cell", "fiscal_time_series_row_id": "row", "fiscal_time_series_column_id": "column", "value_status": "UNAVAILABLE", "value_lineage": None},),
        }
        files, expected_files = {}, {}
        for name, rows in records.items():
            relative = f"{filing['cik']}/{view}/QTD_3M/{name}.parquet"
            path = stage / relative
            files[name] = {**history._write_records(path, rows), "path": relative}
            expected_files[name] = {**files[name], "schema": [[n, str(d)] for n, d in pl.read_parquet_schema(path).items()]}
        table = {"cik": filing["cik"], "ticker": "EXAMPLE", "view": view, "period_class": "QTD_3M", "scope": {}, "files": files}
        tables.append(table)
        expected_tables.append({**table, "files": expected_files})
    manifest = {"version": history.HISTORY_VERSION, "tables": tables, "plan": plan, "views": ["AS_FILED", "LATEST_REPORTED"], "source_intake": str(intake_path), "input_fingerprint": "fingerprint", "operational_roots": roots, "quarterly_derivation_status": "NOT_MATERIALIZED_REPORTED_SERIES_ONLY"}
    history._write_json(stage / "history_manifest.json", manifest)
    report = tmp_path / "independent-report.json"
    history._write_json(report, {"status": "PASS", "complete_decode": True})
    log = tmp_path / "source.log"
    log.write_text("\n".join(json.dumps({"stage": "PANEL_WRITTEN", "ticker": t["ticker"], "view": t["view"], "period_class": t["period_class"], "rows": 1, "cells": 1}) for t in tables))
    proof = {"version": "reported-stage-recovery-v1", "status": "PASS", "generation_source_identity": "a" * 40, "recovery_source_identity": "b" * 40, "staged_manifest_sha256": history._sha256_file(stage / "history_manifest.json"), "intake_sha256": history._sha256_file(intake_path), "plan": plan, "views": manifest["views"], "input_fingerprint": "fingerprint", "tables": expected_tables, "operational_manifest_sha256": {key: "f" * 64 for key in roots}, "verification_report": {"path": str(report), "sha256": history._sha256_file(report)}, "source_execution_log": {"path": str(log), "sha256": history._sha256_file(log)}}
    proof["required_prefixes"] = []
    history._write_json(report, _full_report(proof, stage))
    proof["verification_report"]["sha256"] = history._sha256_file(report)
    attestation = tmp_path / "attestation.json"
    history._write_json(attestation, proof)
    monkeypatch.setattr(history, "_validate_recovery_sources", lambda *args: roots)
    monkeypatch.setattr(quarters, "Layer2PublicationReader", lambda: SimpleNamespace(load=lambda _: SimpleNamespace(identity={"layer2_run_fingerprint": "fingerprint"}, records=lambda _: ())))
    kwargs = {"staged_publication": stage, "output_root": tmp_path / "recovered", "intake_manifest": intake_path, "operational_root": operational, "attestation": attestation, "expected_attestation_sha256": history._sha256_file(attestation)}
    return kwargs, proof


def _bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_recovery_preserves_failed_bytes_and_matches_fresh_quarter_publication(tmp_path, monkeypatch):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    before = _bytes(kwargs["staged_publication"])
    fresh_reported = tmp_path / "fresh-reported"
    shutil.copytree(kwargs["staged_publication"], fresh_reported)
    fresh = quarters.publish_quarter_history(publication=fresh_reported, output_root=tmp_path / "fresh", operational_root=kwargs["operational_root"])
    recovered = history.recover_reported_history(**kwargs)
    assert _bytes(kwargs["staged_publication"]) == before
    assert _bytes(kwargs["output_root"] / "reported-panels") == before
    actual, expected = history.HistoryPublicationReader(recovered), history.HistoryPublicationReader(fresh)
    for table in actual.manifest["tables"]:
        query = {name: table[name] for name in ("ticker", "view", "period_class")}
        assert actual.load(**query) == expected.load(**query)
    assert actual.manifest["source_manifest_sha256"] == proof["staged_manifest_sha256"]
    assert actual.manifest["supersedes_publication"] == str(kwargs["output_root"] / "reported-panels")
    receipt = json.loads((kwargs["output_root"] / "reported_recovery_receipt.json").read_text())
    assert receipt["generation_source_identity"] != receipt["recovery_source_identity"]


@pytest.mark.parametrize("fault", ["attestation", "manifest", "intake", "schema", "inventory", "log", "extra", "missing", "quarter", "copy"])
def test_recovery_fails_closed_leaves_source_and_no_output(tmp_path, monkeypatch, fault):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    if fault == "attestation":
        kwargs["expected_attestation_sha256"] = "0" * 64
    elif fault == "manifest":
        proof["staged_manifest_sha256"] = "0" * 64
    elif fault == "intake":
        proof["intake_sha256"] = "0" * 64
    elif fault == "schema":
        proof["tables"][0]["files"]["cells"]["schema"] = []
    elif fault == "inventory":
        proof["tables"].pop()
    elif fault == "log":
        Path(proof["source_execution_log"]["path"]).write_text("")
        proof["source_execution_log"]["sha256"] = history._sha256_file(Path(proof["source_execution_log"]["path"]))
    elif fault == "extra":
        (kwargs["staged_publication"] / "unexpected").write_text("extra")
    elif fault == "missing":
        (kwargs["staged_publication"] / proof["tables"][0]["files"]["cells"]["path"]).unlink()
    elif fault == "quarter":
        monkeypatch.setattr(quarters, "publish_quarter_history", lambda **_: (_ for _ in ()).throw(ValueError("quarter failed")))
    elif fault == "copy":
        monkeypatch.setattr(history.shutil, "copyfile", lambda *_: (_ for _ in ()).throw(ValueError("copy failed")))
    if fault != "attestation":
        history._write_json(kwargs["attestation"], proof)
        kwargs["expected_attestation_sha256"] = history._sha256_file(kwargs["attestation"])
    before = _bytes(kwargs["staged_publication"])
    with pytest.raises((ValueError, FileNotFoundError)):
        history.recover_reported_history(**kwargs)
    assert _bytes(kwargs["staged_publication"]) == before
    assert not kwargs["output_root"].exists()


def test_quarter_bundle_releases_last_cell_and_rows_before_native_merge(tmp_path, monkeypatch):
    class Tracked(dict):
        pass

    row = Tracked(fiscal_time_series_row_id="r")
    cell = Tracked(fiscal_time_series_row_id="r", fiscal_time_series_column_id="c", value_status="UNAVAILABLE")
    refs = [weakref.ref(row), weakref.ref(cell)]
    bundle = {"columns": {"c": {"fiscal_time_series_column_id": "c"}}, "rows": {"r": row}, "cells": [cell]}
    del row, cell
    original = quarters._finalize_staged_records
    def finalize(plan):
        gc.collect()
        assert all(ref() is None for ref in refs)
        return original(plan)
    monkeypatch.setattr(quarters, "_finalize_staged_records", finalize)
    key = ("EXAMPLE", "AS_FILED", "QTD_3M")
    quarters._stage_quarter_bundle(bundle, key=key, table_index=0, chunk_index=0, chunk_root=tmp_path, targets={key: {"chunks": []}}, additive_by_pair={})
    assert not bundle


def test_quarter_source_results_die_before_next_load_and_final_verification(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    source = tmp_path / "reported"
    shutil.copytree(kwargs["staged_publication"], source)
    refs = []
    original_load = history.HistoryPublicationReader.load
    original_verify = history.HistoryPublicationReader.verify_all

    class TrackedResult:
        def __init__(self, result):
            self.columns, self.rows, self.cells, self.scope = result.columns, result.rows, result.cells, result.scope

    def load(reader, **query):
        gc.collect()
        assert all(ref() is None for ref in refs)
        result = TrackedResult(original_load(reader, **query))
        refs.append(weakref.ref(result))
        return result

    def verify(reader):
        gc.collect()
        assert all(ref() is None for ref in refs)
        return original_verify(reader)

    monkeypatch.setattr(history.HistoryPublicationReader, "load", load)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", verify)
    quarters.publish_quarter_history(publication=source, output_root=tmp_path / "out", operational_root=kwargs["operational_root"])
    assert len(refs) == 2


@pytest.mark.parametrize("fault", ["status", "generation", "view", "plan", "report", "roots", "source_child"])
def test_recovery_rejects_invalid_attestation_scope_and_source_roots(tmp_path, monkeypatch, fault):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    if fault == "status":
        proof["status"] = "NOT_VERIFIED"
    elif fault == "generation":
        proof["generation_source_identity"] = ""
    elif fault == "view":
        proof["views"] = ["LATEST_REPORTED"]
    elif fault == "plan":
        proof["plan"]["as_of_date"] = "2026-11-01"
    elif fault == "report":
        proof["verification_report"]["sha256"] = "0" * 64
    elif fault == "roots":
        monkeypatch.setattr(history, "_validate_recovery_sources", lambda *args: {})
    else:
        kwargs["output_root"] = kwargs["staged_publication"] / "child"
    history._write_json(kwargs["attestation"], proof)
    kwargs["expected_attestation_sha256"] = history._sha256_file(kwargs["attestation"])
    before = _bytes(kwargs["staged_publication"])
    with pytest.raises(ValueError):
        history.recover_reported_history(**kwargs)
    assert _bytes(kwargs["staged_publication"]) == before
    assert not kwargs["output_root"].exists()


def test_build_releases_graph_periods_ledgers_before_verify_and_quarter(tmp_path, monkeypatch):
    from sec_xbrl import analytics, longitudinal
    from sec_xbrl.analytics import FiscalTimeSeriesResult

    class Tracked(dict):
        pass

    class Publication:
        def __init__(self):
            self.identity = {"layer2_run_fingerprint": "fingerprint"}

    cik = "0000001234"
    filing = {"cik": cik, "accession": "a", "filing_id": "f", "form": "10-Q", "document_fiscal_year_focus": 2026, "document_fiscal_period_focus": "Q1"}
    plan = {"as_of_date": "2026-10-10", "companies": [{"cik": cik, "ticker": "EXAMPLE", "filings": [filing]}]}
    intake = tmp_path / "intake.json"
    history._write_json(intake, {"complete": True, "plan": plan, "filings": [{"filing": filing, "source_run": str(tmp_path / "raw"), "status": "REUSED"}]})
    output = tmp_path / "build"
    for name in ("t1", "t2", "t3", "t4"):
        (output / name / output.name).mkdir(parents=True)
    refs = []

    def load(_):
        result = Publication()
        refs.append(weakref.ref(result))
        return result

    def periods(_):
        row = Tracked(value="period")
        refs.append(weakref.ref(row))
        return {(cik, 2026, 1, "QTD_3M"): [row]}, {}

    def ledgers(*_):
        row = Tracked(value="ledger")
        refs.append(weakref.ref(row))
        return {cik: (row,)}

    monkeypatch.setattr(longitudinal, "CohortReleaseAdapter", lambda: SimpleNamespace(load=lambda *a, **k: SimpleNamespace(layer2_run=SimpleNamespace(fingerprint="fingerprint"), snapshots=(), records=lambda _: (filing,))))
    monkeypatch.setattr(longitudinal, "Layer2PublicationReader", lambda: SimpleNamespace(load=load))
    monkeypatch.setattr(history, "_partition_current_observations", periods)
    monkeypatch.setattr(history, "_company_ledgers", ledgers)
    monkeypatch.setattr(longitudinal, "ReportedObservationSelector", lambda: SimpleNamespace(select_period=lambda **kw: SimpleNamespace(rows=kw["observations"])))
    monkeypatch.setattr(analytics, "CompanyAnalysisPanelBuilder", lambda: SimpleNamespace(build=lambda **kw: SimpleNamespace(values=())))
    monkeypatch.setattr(analytics, "FiscalTimeSeriesBuilder", lambda: SimpleNamespace(build=lambda **kw: FiscalTimeSeriesResult(columns=({"column_status": "AVAILABLE", "fiscal_quarter": 1, "fiscal_year": 2026},), rows=({"id": "row"},), cells=({"id": "cell"},), scope={})))
    original_verify = history.HistoryPublicationReader.verify_all
    seen = []

    def verify(reader):
        gc.collect()
        assert all(ref() is None for ref in refs)
        seen.append("verify")
        return original_verify(reader)

    def publish(**_):
        gc.collect()
        assert all(ref() is None for ref in refs)
        seen.append("quarter")
        return output / "panels"

    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", verify)
    monkeypatch.setattr(quarters, "publish_quarter_history", publish)
    assert history.build_history(intake_manifest=intake, output_root=output) == output / "panels"
    assert seen == ["verify", "quarter"]


def test_recovery_sources_checks_all_roots_after_releasing_raw(tmp_path, monkeypatch):
    from sec_xbrl import longitudinal

    class Release:
        layer2_run = SimpleNamespace(fingerprint="fp")
        snapshots = ()

    release = Release()
    reference = weakref.ref(release)
    holder = [release]
    del release
    root = tmp_path / "original"
    hashes = {}
    for name in ("t1", "t2", "t3", "t4"):
        manifest = root / name / root.name / "layer2_run_manifest.json"
        history._write_json(manifest, {"name": name})
        hashes[name] = history._sha256_file(manifest)
    calls = []

    class Reader:
        manifest_name = "layer2_run_manifest.json"
        def load(self, path):
            gc.collect()
            assert reference() is None
            calls.append(path.parent.name)
            return SimpleNamespace(identity={"layer2_run_fingerprint": "fp"})

    monkeypatch.setattr(longitudinal, "CohortReleaseAdapter", lambda: SimpleNamespace(load=lambda *a, **kw: holder.pop()))
    monkeypatch.setattr(longitudinal, "Layer2PublicationReader", Reader)
    roots = history._validate_recovery_sources({"filings": [], "plan": {"companies": []}}, root, "fp", hashes)
    assert list(roots) == calls == ["t1", "t2", "t3", "t4"]


@pytest.mark.parametrize("fault", ["byte_only", "level", "status", "identity", "stage", "intake", "fingerprint", "count", "files", "digest", "json", "prefix"])
def test_recovery_rejects_incomplete_or_misbound_full_report(tmp_path, monkeypatch, fault):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    report_path = Path(proof["verification_report"]["path"])
    report = json.loads(report_path.read_text())
    if fault == "byte_only":
        report = {"status": "PASS", "all_hashes_match": True}
    elif fault == "level":
        report["verification_level"] = "METADATA_ONLY"
    elif fault == "status":
        report["verdict"] = "UNBOUND"
    elif fault == "identity":
        report["source_generation_sha"] = "c" * 40
    elif fault in {"stage", "intake"}:
        report["stage_manifest" if fault == "stage" else "source_intake"]["sha256"] = "0" * 64
    elif fault == "fingerprint":
        report["input_fingerprint"] = "wrong"
    elif fault == "count":
        report["counts"]["stage_files"] -= 1
    elif fault == "files":
        report["verified_files"].pop()
    elif fault == "digest":
        report["verified_files"][0]["ordered_full_record_sha256"] = None
    elif fault == "json":
        report["full_verification"]["all_json_fields_decoded"] = False
    elif fault == "prefix":
        proof["required_prefixes"] = [{"path": proof["tables"][0]["files"]["cells"]["path"], "count": 1, "expected_sha256": "f" * 64}]
    history._write_json(report_path, report)
    proof["verification_report"]["sha256"] = history._sha256_file(report_path)
    history._write_json(kwargs["attestation"], proof)
    kwargs["expected_attestation_sha256"] = history._sha256_file(kwargs["attestation"])
    with pytest.raises(ValueError, match="recovery report"):
        history.recover_reported_history(**kwargs)
    assert not kwargs["output_root"].exists()


@pytest.mark.parametrize("actual_digest", ["f" * 64, "e" * 64])
def test_recovery_report_enforces_authenticated_prefix_digest(tmp_path, monkeypatch, actual_digest):
    _kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    prefix = {"path": proof["tables"][0]["files"]["cells"]["path"], "count": 1, "expected_sha256": "f" * 64}
    proof["required_prefixes"] = [prefix]
    report_path = Path(proof["verification_report"]["path"])
    report = json.loads(report_path.read_text())
    report["prefix_checks"] = [{**prefix, "actual_sha256": actual_digest, "status": "PASS"}]
    history._write_json(report_path, report)
    if actual_digest == prefix["expected_sha256"]:
        history._validate_recovery_report(proof)
    else:
        with pytest.raises(ValueError, match="prefix mismatch"):
            history._validate_recovery_report(proof)
