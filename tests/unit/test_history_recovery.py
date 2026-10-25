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
    kwargs = {"trusted_exclusive_parent": True, "staged_publication": stage, "output_root": tmp_path / "recovered", "intake_manifest": intake_path, "operational_root": operational, "attestation": attestation, "expected_attestation_sha256": history._sha256_file(attestation)}
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
def test_recovery_fails_closed_preserves_source_and_retains_failed_transaction(tmp_path, monkeypatch, fault):
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
        monkeypatch.setattr(history, "_copy_recovery_payload", lambda *_: (_ for _ in ()).throw(ValueError("copy failed")))
    if fault != "attestation":
        history._write_json(kwargs["attestation"], proof)
        kwargs["expected_attestation_sha256"] = history._sha256_file(kwargs["attestation"])
    before = _bytes(kwargs["staged_publication"])
    with pytest.raises((ValueError, FileNotFoundError)):
        history.recover_reported_history(**kwargs)
    assert _bytes(kwargs["staged_publication"]) == before
    if fault in {"quarter", "copy"}:
        assert kwargs["output_root"].is_dir()
        assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
        with pytest.raises(ValueError, match="NOT_READY"):
            history.HistoryPublicationReader(kwargs["output_root"] / "reported-panels", allow_staging=True)
    else:
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
    assert len(refs) == 0  # Quarter production must never invoke eager load.


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
    fiscal_result = FiscalTimeSeriesResult(
        columns=(
            {
                "fiscal_time_series_column_id": "column",
                "column_status": "AVAILABLE",
                "fiscal_quarter": 1,
                "fiscal_year": 2026,
            },
        ),
        rows=({"fiscal_time_series_row_id": "row"},),
        cells=(
            {
                "fiscal_time_series_cell_id": "cell",
                "fiscal_time_series_row_id": "row",
                "fiscal_time_series_column_id": "column",
            },
        ),
        scope={},
    )

    class SpilledResult:
        def __init__(self):
            self.scope = fiscal_result.scope
            self.counts = {
                "columns": len(fiscal_result.columns),
                "rows": len(fiscal_result.rows),
                "cells": len(fiscal_result.cells),
            }

        @staticmethod
        def dataset(name):
            return getattr(fiscal_result, name)

        @staticmethod
        def close(*, success):
            assert success

    monkeypatch.setattr(
        analytics,
        "FiscalTimeSeriesBuilder",
        lambda: SimpleNamespace(build_spilled=lambda **kw: SpilledResult()),
    )
    original_validate = history.HistoryPublicationReader.validate
    seen = []

    def validate(reader, **kwargs):
        gc.collect()
        assert all(ref() is None for ref in refs)
        seen.append("validate")
        return original_validate(reader, **kwargs)

    def publish(**_):
        gc.collect()
        assert all(ref() is None for ref in refs)
        seen.append("quarter")
        return output / "panels"

    monkeypatch.setattr(history.HistoryPublicationReader, "validate", validate)
    monkeypatch.setattr(quarters, "publish_quarter_history", publish)
    assert history.build_history(intake_manifest=intake, output_root=output) == output / "panels"
    assert seen == ["validate", "quarter"]


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
            return SimpleNamespace(identity={"layer2_run_fingerprint": "fp", "layer2_manifest_sha256": hashes[path.parent.name]})

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
    proof["verification_report"]["sha256"] = history._sha256_file(report_path)
    if actual_digest == prefix["expected_sha256"]:
        history._validate_recovery_report(proof)
    else:
        with pytest.raises(ValueError, match="prefix mismatch"):
            history._validate_recovery_report(proof)


@pytest.mark.parametrize("artifact", ["attestation", "verification_report", "source_execution_log", "intake", "manifest"])
def test_recovery_rejects_evidence_replacement_during_hash(tmp_path, monkeypatch, artifact):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    path = {"attestation": kwargs["attestation"], "intake": kwargs["intake_manifest"],
            "manifest": kwargs["staged_publication"] / "history_manifest.json"}.get(artifact)
    if path is None:
        path = Path(proof[artifact]["path"])
    before = path.read_bytes()
    real_hash = history.hashlib.sha256
    exchanged = False

    def hash_then_exchange(data=b""):
        nonlocal exchanged
        result = real_hash(data)
        if data == before and not exchanged:
            exchanged = True
            replacement = path.with_name(path.name + ".exchange")
            replacement.write_bytes(before + b" ")
            replacement.replace(path)
        return result

    monkeypatch.setattr(history.hashlib, "sha256", hash_then_exchange)
    with pytest.raises(ValueError, match="changed during read|identity/content changed"):
        history.recover_reported_history(**kwargs)
    assert exchanged
    assert not kwargs["output_root"].exists()


@pytest.mark.parametrize("succeed", [False, True])
def test_recovery_never_cleans_or_receipts_replacement_directory(tmp_path, monkeypatch, succeed):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    unrelated = tmp_path / "preexisting-publication"
    unrelated.mkdir()
    marker = unrelated / "do-not-delete.txt"
    marker.write_bytes(b"preexisting protected bytes")
    moved = tmp_path / "original-owned-transaction"

    def exchange(**_):
        kwargs["output_root"].rename(moved)
        unrelated.rename(kwargs["output_root"])
        if succeed:
            return kwargs["output_root"] / "panels"
        raise ValueError("quarter failure after ownership exchange")

    monkeypatch.setattr(quarters, "publish_quarter_history", exchange)
    with pytest.raises(ValueError, match="ownership changed"):
        history.recover_reported_history(**kwargs)
    assert (kwargs["output_root"] / marker.name).read_bytes() == b"preexisting protected bytes"
    assert sorted(p.name for p in kwargs["output_root"].iterdir()) == [marker.name]
    assert (moved / "reported-panels" / "history_manifest.json").is_file()
    assert not (moved / "reported_recovery_receipt.json").exists()


def test_recovery_reservation_does_not_own_concurrent_creator(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = history.os.mkdir
    triggered = False

    def mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal triggered
        if path == kwargs["output_root"].name and dir_fd is not None and not triggered:
            triggered = True
            original(path, mode, dir_fd=dir_fd)
            (kwargs["output_root"] / "preexisting.txt").write_text("concurrent creator")
        return original(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(history.os, "mkdir", mkdir)
    with pytest.raises(FileExistsError):
        history.recover_reported_history(**kwargs)
    assert (kwargs["output_root"] / "preexisting.txt").read_text() == "concurrent creator"


def test_recovery_rejects_source_payload_exchange_after_copy(tmp_path, monkeypatch):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    original = history._copy_recovery_payload
    source_path = kwargs["staged_publication"] / proof["tables"][0]["files"]["cells"]["path"]

    def copy_then_exchange(source, *args):
        original(source, *args)
        if source == source_path:
            replacement = source.with_name("exchange.parquet")
            replacement.write_bytes(source.read_bytes())
            replacement.replace(source)

    monkeypatch.setattr(history, "_copy_recovery_payload", copy_then_exchange)
    with pytest.raises(ValueError, match="identity/content changed"):
        history.recover_reported_history(**kwargs)
    assert kwargs["output_root"].exists()
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()


def test_recovery_output_cannot_alias_intake_source_root(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    kwargs["output_root"] = tmp_path / "raw" / "new-output"
    with pytest.raises(ValueError, match="immutable source root"):
        history.recover_reported_history(**kwargs)
    assert not kwargs["output_root"].exists()


def test_recovery_ancestor_exchange_preserves_unrelated_tree(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    parent = tmp_path / "output-parent"
    parent.mkdir()
    kwargs["output_root"] = parent / "recovered"
    replacement = tmp_path / "unrelated-parent"
    (replacement / "recovered").mkdir(parents=True)
    (replacement / "recovered" / "keep.txt").write_text("keep")
    moved = tmp_path / "moved-owned-parent"

    def exchange(**_):
        parent.rename(moved)
        replacement.rename(parent)
        raise ValueError("ancestor exchange")

    monkeypatch.setattr(quarters, "publish_quarter_history", exchange)
    with pytest.raises(ValueError, match="ownership changed"):
        history.recover_reported_history(**kwargs)
    assert (parent / "recovered" / "keep.txt").read_text() == "keep"
    assert (moved / "recovered" / "reported-panels").is_dir()


def test_recovery_rejects_normalized_raw_source_overlap(tmp_path, monkeypatch):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    (tmp_path / "alias-parent").mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    intake = json.loads(kwargs["intake_manifest"].read_text())
    intake["filings"][0]["source_run"] = str(tmp_path / "alias-parent" / ".." / "raw")
    history._write_json(kwargs["intake_manifest"], intake)
    proof["intake_sha256"] = history._sha256_file(kwargs["intake_manifest"])
    report_path = Path(proof["verification_report"]["path"])
    report = json.loads(report_path.read_text())
    report["source_intake"]["sha256"] = proof["intake_sha256"]
    history._write_json(report_path, report)
    proof["verification_report"]["sha256"] = history._sha256_file(report_path)
    history._write_json(kwargs["attestation"], proof)
    kwargs["expected_attestation_sha256"] = history._sha256_file(kwargs["attestation"])
    kwargs["output_root"] = raw / "new-output"
    with pytest.raises(ValueError, match="immutable source root"):
        history.recover_reported_history(**kwargs)
    assert list(raw.iterdir()) == []


@pytest.mark.parametrize("artifact", ["manifest", "dataset", "root"])
def test_recovery_rejects_operational_source_exchange_inside_public_validator(tmp_path, monkeypatch, artifact):
    from sec_xbrl import longitudinal

    operational = tmp_path / "operational"
    hashes = {}
    for name in ("t1", "t2", "t3", "t4"):
        root = operational / name / operational.name
        history._write_json(root / "layer2_run_manifest.json", {"name": name})
        (root / "dataset").write_bytes(b"original dataset bytes")
        hashes[name] = history._sha256_file(root / "layer2_run_manifest.json")
    monkeypatch.setattr(longitudinal, "CohortReleaseAdapter", lambda: SimpleNamespace(load=lambda *a, **kw: SimpleNamespace(layer2_run=SimpleNamespace(fingerprint="fp"), snapshots=())))

    class Reader:
        manifest_name = "layer2_run_manifest.json"
        def load(self, path):
            if artifact == "root":
                path.rename(path.with_name("displaced"))
                path.mkdir()
            else:
                source = path / (self.manifest_name if artifact == "manifest" else "dataset")
                source.write_bytes(source.read_bytes() + b" ")
            return SimpleNamespace(identity={"layer2_run_fingerprint": "fp", "layer2_manifest_sha256": hashes[path.parent.name]})

    monkeypatch.setattr(longitudinal, "Layer2PublicationReader", Reader)
    with pytest.raises(ValueError, match="changed"):
        history._validate_recovery_sources({"filings": [], "plan": {"companies": []}}, operational, "fp", hashes)


@pytest.mark.parametrize("succeed", [False, True])
def test_recovery_creation_gap_never_adopts_nonempty_replacement(tmp_path, monkeypatch, succeed):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_bytes(b"existing bytes")
    moved = tmp_path / "moved-created"
    original = history.os.mkdir
    triggered = False

    def exchange(path, mode=0o777, *, dir_fd=None):
        nonlocal triggered
        result = original(path, mode, dir_fd=dir_fd)
        if path == kwargs["output_root"].name and dir_fd is not None and not triggered:
            triggered = True
            kwargs["output_root"].rename(moved)
            foreign.rename(kwargs["output_root"])
        return result

    monkeypatch.setattr(history.os, "mkdir", exchange)
    monkeypatch.setattr(quarters, "publish_quarter_history", lambda **_: kwargs["output_root"] / "panels" if succeed else (_ for _ in ()).throw(ValueError("quarter")))
    with pytest.raises(ValueError, match="not empty"):
        history.recover_reported_history(**kwargs)
    assert triggered and _bytes(kwargs["output_root"]) == {"keep.txt": b"existing bytes"}
    assert list(moved.iterdir()) == []


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("succeed", [False, True])
def test_recovery_preserves_exchanged_descendants_on_failure_and_success(tmp_path, monkeypatch, empty, succeed):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    if not empty:
        (foreign / "keep.txt").write_bytes(b"existing bytes")
    expected = _bytes(foreign)
    displaced = tmp_path / "displaced-reported"

    def exchange(**_):
        reported = kwargs["output_root"] / "reported-panels"
        reported.rename(displaced)
        foreign.rename(reported)
        if succeed:
            return kwargs["output_root"] / "panels"
        raise ValueError("quarter failed")

    monkeypatch.setattr(quarters, "publish_quarter_history", exchange)
    with pytest.raises(ValueError, match="ownership changed"):
        history.recover_reported_history(**kwargs)
    assert _bytes(kwargs["output_root"] / "reported-panels") == expected
    assert (displaced / "history_manifest.json").is_file()
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "reported-panels")


def test_recovery_failure_after_consumer_publication_is_denied_by_default_readers(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = quarters.publish_quarter_history
    produced = []

    def fail_after_publish(**arguments):
        result = original(**arguments)
        produced.append(result)
        for factory in (history.HistoryPublicationReader, history.open_history_publication):
            with pytest.raises(ValueError, match="NOT_READY"):
                factory(result)
        with pytest.raises(ValueError, match="NOT_READY"):
            history.HistoryPublicationReader(result, allow_staging=True, _recovery_access=object())
        raise ValueError("failure after final consumer manifest")

    monkeypatch.setattr(quarters, "publish_quarter_history", fail_after_publish)
    with pytest.raises(ValueError, match="failure after final consumer"):
        history.recover_reported_history(**kwargs)
    assert (produced[0] / "history_manifest.json").is_file()
    assert (produced[0] / ".chunks").is_dir()
    assert list(produced[0].rglob("*.chunks-*"))
    gc.collect()
    assert list(produced[0].rglob("*.chunks-*"))
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(produced[0], allow_staging=True)
    assert history._RECOVERY_OUTPUT.get() is None
    assert history._HISTORY_STORAGE_GUARD.get() is None


@pytest.mark.parametrize("fault", ["missing_marker", "changed_marker", "missing_receipt", "status", "token", "report", "consumer", "source", "control_symlink"])
def test_recovery_default_gate_rejects_missing_or_tampered_completion(tmp_path, monkeypatch, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    reader = history.HistoryPublicationReader(result)
    control = next(kwargs["output_root"].glob(".history-recovery-*"))
    marker = control / "transaction.json"
    receipt_path = kwargs["output_root"] / "reported_recovery_receipt.json"
    if fault == "missing_marker":
        marker.unlink()
    elif fault == "changed_marker":
        marker.write_bytes(marker.read_bytes() + b" ")
    elif fault == "missing_receipt":
        receipt_path.unlink()
    elif fault == "control_symlink":
        target = tmp_path / "moved-control"
        control.rename(target)
        control.symlink_to(target, target_is_directory=True)
    else:
        receipt = json.loads(receipt_path.read_text())
        key = {"status": "status", "token": "transaction_token", "report": "verification_report_sha256", "consumer": "consumer_manifest_sha256", "source": "source_manifest_sha256"}[fault]
        receipt[key] = "INVALID"
        receipt_path.write_text(json.dumps(receipt))
    for factory in (history.HistoryPublicationReader, history.open_history_publication):
        with pytest.raises(ValueError, match="NOT_READY"):
            factory(result)
    with pytest.raises(ValueError, match="NOT_READY"):
        reader.verify_all()
    with pytest.raises(ValueError, match="NOT_READY"):
        reader.load(ticker="EXAMPLE", view="AS_FILED")


def test_recovery_marker_failure_retains_control_and_denies_reader(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = history._RecoveryOutput.create_file

    def fail_marker(self, relative):
        fd = original(self, relative)
        if relative.name == "transaction.json":
            history.os.close(fd)
            raise ValueError("marker write failed")
        return fd

    monkeypatch.setattr(history._RecoveryOutput, "create_file", fail_marker)
    with pytest.raises(ValueError, match="marker write failed"):
        history.recover_reported_history(**kwargs)
    assert list(kwargs["output_root"].glob(".history-recovery-*"))
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "panels", allow_staging=True)


@pytest.mark.parametrize("fault", ["acknowledgment", "shared_parent"])
def test_recovery_requires_explicit_trusted_parent_contract(tmp_path, monkeypatch, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    if fault == "acknowledgment":
        kwargs["trusted_exclusive_parent"] = False
    else:
        parent = tmp_path / "shared-parent"
        parent.mkdir(mode=0o777)
        parent.chmod(0o777)
        kwargs["output_root"] = parent / "output"
    with pytest.raises(ValueError, match="trusted"):
        history.recover_reported_history(**kwargs)
    assert not kwargs["output_root"].exists()


def test_recovery_atomic_commit_refuses_existing_receipt_and_preserves_it(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = history._RecoveryOutput.commit

    def conflicting_receipt(self, receipt):
        (self.root / "reported_recovery_receipt.json").write_bytes(b"foreign receipt")
        return original(self, receipt)

    monkeypatch.setattr(history._RecoveryOutput, "commit", conflicting_receipt)
    with pytest.raises(FileExistsError):
        history.recover_reported_history(**kwargs)
    assert (kwargs["output_root"] / "reported_recovery_receipt.json").read_bytes() == b"foreign receipt"
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "panels")


def test_empty_same_uid_creation_replacement_is_explicitly_outside_trust_boundary(tmp_path, monkeypatch):
    # mkdir cannot return an atomic owned directory FD. Under the documented
    # sole-operator contract this exchange is forbidden, not claimed protected.
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "empty-foreign"
    foreign.mkdir()
    moved = tmp_path / "moved-created"
    original = history.os.mkdir
    triggered = False

    def exchange(path, mode=0o777, *, dir_fd=None):
        nonlocal triggered
        result = original(path, mode, dir_fd=dir_fd)
        if path == kwargs["output_root"].name and dir_fd is not None and not triggered:
            triggered = True
            kwargs["output_root"].rename(moved)
            foreign.rename(kwargs["output_root"])
        return result

    monkeypatch.setattr(history.os, "mkdir", exchange)
    monkeypatch.setattr(quarters, "publish_quarter_history", lambda **_: (_ for _ in ()).throw(ValueError("quarter failed")))
    with pytest.raises(ValueError, match="quarter failed"):
        history.recover_reported_history(**kwargs)
    assert triggered and moved.exists() and kwargs["output_root"].exists()
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "reported-panels")


@pytest.mark.parametrize("fault", ["input_fingerprint", "source_manifest_sha256", "supersedes_publication", "quarterly_derivation_status"])
def test_recovery_refuses_complete_receipt_for_misbound_consumer(tmp_path, monkeypatch, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = quarters.publish_quarter_history

    def publish(**arguments):
        result = original(**arguments)
        path = result / "history_manifest.json"
        payload = json.loads(path.read_text())
        payload[fault] = "wrong"
        path.write_text(json.dumps(payload))
        return result

    monkeypatch.setattr(quarters, "publish_quarter_history", publish)
    with pytest.raises(ValueError, match="consumer provenance"):
        history.recover_reported_history(**kwargs)
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "panels")


@pytest.mark.parametrize("succeed", [False, True])
def test_recovery_empty_root_replacement_after_capture_is_rejected(tmp_path, monkeypatch, succeed):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "empty-foreign"
    foreign.mkdir()
    moved = tmp_path / "moved-transaction"

    def exchange(**_):
        kwargs["output_root"].rename(moved)
        foreign.rename(kwargs["output_root"])
        if succeed:
            return kwargs["output_root"] / "panels"
        raise ValueError("quarter failure")

    monkeypatch.setattr(quarters, "publish_quarter_history", exchange)
    with pytest.raises(ValueError, match="ownership changed"):
        history.recover_reported_history(**kwargs)
    assert list(kwargs["output_root"].iterdir()) == []
    assert (moved / "reported-panels" / "history_manifest.json").is_file()
    assert not (moved / "reported_recovery_receipt.json").exists()


def test_recovery_never_overwrites_an_existing_quarter_output_file(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = quarters._stage_records
    injected = []

    def inject(path, records):
        if not injected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"existing foreign file")
            injected.append(path)
        return original(path, records)

    monkeypatch.setattr(quarters, "_stage_records", inject)
    with pytest.raises(ValueError, match="overwrite"):
        history.recover_reported_history(**kwargs)
    assert injected[0].read_bytes() == b"existing foreign file"
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()



def test_recovery_atomic_directory_publication_never_replaces_empty_concurrent_destination(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    original = history.ctypes.CDLL
    foreign_inode = []

    def inject(*args, **arguments):
        if not foreign_inode:
            destination = kwargs["output_root"] / "reported-panels"
            destination.mkdir()
            foreign_inode.append(destination.stat().st_ino)
        return original(*args, **arguments)

    monkeypatch.setattr(history.ctypes, "CDLL", inject)
    with pytest.raises(FileExistsError):
        history.recover_reported_history(**kwargs)
    destination = kwargs["output_root"] / "reported-panels"
    assert destination.stat().st_ino == foreign_inode[0]
    assert list(destination.iterdir()) == []
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()



def _assert_default_recovery_denied(result):
    for factory in (history.HistoryPublicationReader, history.open_history_publication):
        with pytest.raises(ValueError, match="NOT_READY|symlink"):
            factory(result).verify_all()


def test_default_gate_rejects_reported_only_copy_with_structurally_bound_fake_receipt(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(quarters, "publish_quarter_history", lambda **_: (_ for _ in ()).throw(ValueError("stop before quarter")))
    with pytest.raises(ValueError, match="stop before quarter"):
        history.recover_reported_history(**kwargs)
    root = kwargs["output_root"]
    result = root / "panels"
    shutil.copytree(root / "reported-panels", result)
    control = next(root.glob(".history-recovery-*"))
    marker = json.loads((control / "transaction.json").read_text())
    receipt = {k: v for k, v in marker.items() if k not in {"output_root", "root_identity", "token"}}
    receipt.update(status="COMPLETE", transaction_sha256=control.name.removeprefix(".history-recovery-"),
                   transaction_token=marker["token"], reported_publication=str(root / "reported-panels"),
                   consumer_publication=str(result), consumer_manifest_sha256=history._sha256_file(result / "history_manifest.json"))
    (root / "reported_recovery_receipt.json").write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("identifier", ["receipt_symlink", "receipt_directory", "control_symlink", "control_file", "temporary_symlink", "temporary_directory"])
def test_default_gate_never_treats_stale_identifiers_as_legacy(tmp_path, monkeypatch, identifier):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    root = kwargs["output_root"]
    next(root.glob(".history-recovery-*")).rename(tmp_path / "saved-control")
    (root / "reported_recovery_receipt.json").unlink()
    for temporary in root.glob(".receipt.partial-*"):
        temporary.unlink()
    names = {"receipt": "reported_recovery_receipt.json", "control": ".history-recovery-stale", "temporary": ".receipt.partial-stale"}
    kind, entry = identifier.split("_")
    path = root / names[kind]
    if entry == "symlink":
        path.symlink_to(tmp_path / "does-not-exist")
    elif entry == "directory":
        path.mkdir()
    else:
        path.write_text("stale identifier")
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("field", ["version", "attestation", "source_stage", "verification_report_sha256", "generation_source_identity", "recovery_source_identity", "input_fingerprint", "reported_publication", "consumer_publication", "missing", "extra", "duplicate"])
def test_default_gate_rejects_receipt_contract_tamper(tmp_path, monkeypatch, field):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(path.read_text())
    if field == "missing":
        del receipt["attestation"]
    elif field == "extra":
        receipt["undeclared"] = True
    elif field == "duplicate":
        path.write_text('{"status":"COMPLETE",' + json.dumps(receipt)[1:])
    else:
        receipt[field] = "INVALID"
    if field != "duplicate":
        path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("scalar", [None, True, 1, 1.0, [], {}, float("nan")])
def test_default_gate_rejects_receipt_hash_non_string_scalars(tmp_path, monkeypatch, scalar):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(path.read_text())
    receipt["consumer_manifest_sha256"] = scalar
    path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("fault", ["derived_absent", "derived_file_missing", "derived_count_bool", "derived_count_wrong", "derived_json_schema", "period_rule", "derivation_rule", "supersedes_publication", "source_manifest_sha256", "operational_roots", "tables", "period_reclassification_counts", "file_count_bool", "file_hash_scalar", "file_path", "file_json_fields"])
def test_default_gate_validates_completed_consumer_after_manifest_hash_rebinding(tmp_path, monkeypatch, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    path = result / "history_manifest.json"
    manifest = json.loads(path.read_text())
    # A valid empty governed derived file is a success control, not absence.
    assert manifest["derived_quarter"]["count"] == 0
    history.HistoryPublicationReader(result).verify_all()
    if fault == "derived_absent":
        del manifest["derived_quarter"]
    elif fault == "derived_file_missing":
        (result / "derived_quarter.parquet").unlink()
    elif fault == "derived_count_bool":
        manifest["derived_quarter"]["count"] = False
    elif fault == "derived_count_wrong":
        manifest["derived_quarter"]["count"] = 1
    elif fault == "derived_json_schema":
        manifest["derived_quarter"]["json_fields"] = ["nonexistent"]
    elif fault == "operational_roots":
        manifest[fault] = {}
    elif fault == "tables":
        manifest[fault] = []
    elif fault == "period_reclassification_counts":
        manifest[fault] = {"changed": True}
    elif fault.startswith("file_"):
        info = manifest["tables"][0]["files"]["cells"]
        key, value = {"file_count_bool": ("count", True), "file_hash_scalar": ("sha256", 1),
                      "file_path": ("path", "../foreign.parquet"), "file_json_fields": ("json_fields", {})}[fault]
        info[key] = value
    else:
        manifest[fault] = "wrong"
    path.write_text(json.dumps(manifest))
    receipt_path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["consumer_manifest_sha256"] = history._sha256_file(path)
    receipt_path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("artifact", ["attestation.json", "verification_report.json"])
@pytest.mark.parametrize("fault", ["missing", "changed", "dangling", "directory"])
def test_default_gate_requires_retained_authenticated_full_proof(tmp_path, monkeypatch, artifact, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    control = next(result.parent.glob(".history-recovery-*"))
    path = control / artifact
    if fault == "changed":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path.unlink()
        if fault == "dangling":
            path.symlink_to(tmp_path / "missing")
        elif fault == "directory":
            path.mkdir()
    _assert_default_recovery_denied(result)


def test_default_gate_accepts_retained_full_proof_without_external_locator_reads(tmp_path, monkeypatch):
    kwargs, proof = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    for path in (kwargs["attestation"], Path(proof["verification_report"]["path"])):
        path.rename(path.with_suffix(".retained-original"))
    reader = history.HistoryPublicationReader(result)
    reader.verify_all()
    assert reader.load(ticker="EXAMPLE", view="AS_FILED").cells


def test_default_gate_rejects_float_root_identity_even_when_numerically_equal(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    control = next(result.parent.glob(".history-recovery-*"))
    marker_path = control / "transaction.json"
    marker = json.loads(marker_path.read_text())
    marker["root_identity"] = [float(v) for v in marker["root_identity"]]
    marker_path.write_text(json.dumps(marker))
    digest = history._sha256_file(marker_path)
    control.rename(control.with_name(".history-recovery-" + digest))
    path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(path.read_text())
    receipt["transaction_sha256"] = digest
    path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("fault", ["byte_only", "wrong_generation", "wrong_stage", "wrong_fingerprint"])
def test_default_gate_rechecks_full_report_after_all_local_hashes_are_rebound(tmp_path, monkeypatch, fault):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    control = next(result.parent.glob(".history-recovery-*"))
    report_path = control / "verification_report.json"
    report = json.loads(report_path.read_text())
    if fault == "byte_only":
        report["verification_level"] = "METADATA_ONLY"
    elif fault == "wrong_generation":
        report["source_generation_sha"] = "f" * 40
    elif fault == "wrong_stage":
        report["stage_manifest"]["path"] = str(tmp_path / "wrong-stage" / "history_manifest.json")
    else:
        report["input_fingerprint"] = "wrong fingerprint"
    report_path.write_text(json.dumps(report))
    report_hash = history._sha256_file(report_path)
    proof_path = control / "attestation.json"
    proof = json.loads(proof_path.read_text())
    proof["verification_report"]["sha256"] = report_hash
    proof_path.write_text(json.dumps(proof))
    marker_path = control / "transaction.json"
    marker = json.loads(marker_path.read_text())
    marker.update(verification_report_sha256=report_hash, attestation_sha256=history._sha256_file(proof_path))
    marker_path.write_text(json.dumps(marker))
    marker_hash = history._sha256_file(marker_path)
    control.rename(control.with_name(".history-recovery-" + marker_hash))
    receipt_path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt.update(transaction_sha256=marker_hash, verification_report_sha256=report_hash,
                   attestation_sha256=marker["attestation_sha256"])
    receipt_path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("count", [0, 1])
def test_default_gate_rejects_non_governed_derived_schema_even_with_rebound_hashes(tmp_path, monkeypatch, count):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    result = history.recover_reported_history(**kwargs)
    data_path = result / "derived_quarter.parquet"
    pl.DataFrame({"arbitrary": list(range(count))}, schema={"arbitrary": pl.Int64}).write_parquet(data_path)
    manifest_path = result / "history_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["derived_quarter"].update(count=count, sha256=history._sha256_file(data_path))
    manifest_path.write_text(json.dumps(manifest))
    receipt_path = result.parent / "reported_recovery_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["consumer_manifest_sha256"] = history._sha256_file(manifest_path)
    receipt_path.write_text(json.dumps(receipt))
    _assert_default_recovery_denied(result)


@pytest.mark.parametrize("fail_after_quarter", [False, True])
def test_module_cli_owns_one_scoped_recovery_capability(tmp_path, monkeypatch, fail_after_quarter):
    import runpy
    import sys
    import warnings

    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign-pending"
    shutil.copytree(kwargs["staged_publication"], foreign / "panels")
    (foreign / ".history-recovery-uncommitted").mkdir()
    original = quarters.publish_quarter_history
    capabilities = []

    def publish(**arguments):
        capability = arguments["_recovery_access"]
        capabilities.append(capability)
        assert history._RECOVERY_OUTPUT.get() is capability
        # The real quarter reader must see the same owned context as the CLI.
        history.HistoryPublicationReader(arguments["publication"], _recovery_access=capability).verify_all()
        with pytest.raises(ValueError, match="NOT_READY"):
            history.HistoryPublicationReader(arguments["publication"])
        with pytest.raises(ValueError, match="NOT_READY"):
            history.HistoryPublicationReader(foreign / "panels", _recovery_access=capability)
        result = original(**arguments)
        if fail_after_quarter:
            raise ValueError("controlled CLI quarter failure")
        return result

    monkeypatch.setattr(quarters, "publish_quarter_history", publish)
    argv = ["sec_xbrl.history", "recover-reported", "--trusted-exclusive-parent"]
    for name, value in kwargs.items():
        if name != "trusted_exclusive_parent":
            argv.extend(["--" + name.replace("_", "-"), str(value)])
    monkeypatch.setattr(sys, "argv", argv)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="'sec_xbrl.history' found in sys.modules", category=RuntimeWarning)
        if fail_after_quarter:
            with pytest.raises(ValueError, match="controlled CLI quarter failure"):
                runpy.run_module("sec_xbrl.history", run_name="__main__", alter_sys=True)
        else:
            runpy.run_module("sec_xbrl.history", run_name="__main__", alter_sys=True)
    assert len(capabilities) == 1
    assert history._RECOVERY_OUTPUT.get() is None
    assert history._HISTORY_STORAGE_GUARD.get() is None
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(foreign / "panels", _recovery_access=capabilities[0])
    if fail_after_quarter:
        assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
        with pytest.raises(ValueError, match="NOT_READY"):
            history.HistoryPublicationReader(kwargs["output_root"] / "reported-panels", _recovery_access=capabilities[0])
    else:
        history.HistoryPublicationReader(kwargs["output_root"] / "panels").verify_all()
