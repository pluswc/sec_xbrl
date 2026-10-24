from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from sec_xbrl import collection_operations, history, history_validation
from sec_xbrl.analytics import history_quarters
from sec_xbrl.history_validation import validate_publication


def _publication(root: Path, *, value: str = "10", second: bool = True) -> tuple[Path, dict]:
    tables = []
    for index in range(2 if second else 1):
        relative = Path("0000000001") / "LATEST_REPORTED" / f"QTD_{index}"
        row_id = f"row-{index}"
        column_id = f"column-{index}"
        records = {
            "columns": ({"fiscal_time_series_column_id": column_id, "fiscal_year": 2026,
                         "fiscal_quarter": index + 1, "period_class": "QTD_3M"},),
            "rows": ({"fiscal_time_series_row_id": row_id, "definition": {"label": f"Row {index}"}},),
            "cells": tuple(
                {
                    "fiscal_time_series_cell_id": f"cell-{index}-{offset}",
                    "fiscal_time_series_row_id": row_id,
                    "fiscal_time_series_column_id": column_id,
                    "value_lineage": {
                        "value_numeric": value if index == 0 else str(index + offset),
                        "candidate_lineage": [{"source_fact_id": f"fact-{index}-{offset}"}],
                    },
                }
                for offset in range(20)
            ),
        }
        files = {}
        for role, rows in records.items():
            path = root / relative / f"{role}.parquet"
            info = history._write_records(path, rows)
            files[role] = {**info, "path": str(relative / path.name)}
        tables.append(
            {
                "ticker": "TEST",
                "cik": "0000000001",
                "view": "LATEST_REPORTED",
                "period_class": f"QTD_{index}",
                "scope": {"fixture": True},
                "files": files,
            }
        )
    manifest = {
        "version": history.HISTORY_VERSION,
        "plan": {"companies": [{"ticker": "TEST", "cik": "0000000001"}]},
        "views": ["LATEST_REPORTED"],
        "source_intake": str((root.parent / "intake.json").absolute()),
        "input_fingerprint": "fixture",
        "tables": tables,
    }
    history._write_json(root / "history_manifest.json", manifest)
    return root, manifest


def _copy_publication(source: Path, destination: Path) -> tuple[Path, dict]:
    shutil.copytree(source, destination)
    return destination, json.loads((destination / "history_manifest.json").read_text())


def _rewrite_first_cell(root: Path, manifest: dict, *, dangling: bool = False) -> dict:
    table = manifest["tables"][0]
    path = root / table["files"]["cells"]["path"]
    rows = list(history.HistoryPublicationReader(root)._records(table["files"]["cells"]))
    changed_index = len(rows) // 2 if dangling else 0
    rows[changed_index] = {
        **rows[changed_index],
        "fiscal_time_series_row_id": "missing-row" if dangling else rows[changed_index]["fiscal_time_series_row_id"],
        "value_lineage": {**rows[changed_index]["value_lineage"], "value_numeric": "99"},
    }
    path.unlink()
    info = history._write_records(path, tuple(rows))
    table["files"]["cells"] = {**info, "path": table["files"]["cells"]["path"]}
    (root / "history_manifest.json").unlink()
    history._write_json(root / "history_manifest.json", manifest)
    return manifest


def _rewrite_role(root: Path, manifest: dict, role: str, rows: list[dict]) -> None:
    table = manifest["tables"][0]
    info = table["files"][role]
    path = root / info["path"]
    path.unlink()
    written = history._write_records(path, tuple(rows))
    table["files"][role] = {**written, "path": info["path"]}
    (root / "history_manifest.json").unlink()
    history._write_json(root / "history_manifest.json", manifest)


def test_routine_initial_unchanged_cross_root_and_changed_table(tmp_path: Path) -> None:
    root, _ = _publication(tmp_path / "first")
    state = tmp_path / "state"
    first = history.HistoryPublicationReader(root).validate(state_root=state)
    assert first.level == "ROUTINE_INITIAL"
    assert len(first.checked_files) == 6
    assert 0 < first.sampled_rows < 44
    assert not first.detailed_fallback

    unchanged = history.HistoryPublicationReader(root).validate(state_root=state)
    assert unchanged.level == "ROUTINE_UNCHANGED"
    assert unchanged.checked_files == ()
    assert unchanged.hashed_files == ()

    copied, manifest = _copy_publication(root, tmp_path / "copied")
    across_root = history.HistoryPublicationReader(copied).validate(state_root=state)
    assert across_root.level == "ROUTINE_UNCHANGED"
    assert len(across_root.hashed_files) == 6
    assert across_root.checked_files == ()

    _rewrite_first_cell(copied, manifest)
    changed = history.HistoryPublicationReader(copied).validate(state_root=state)
    assert changed.level == "ROUTINE_CHANGED"
    assert len(changed.checked_files) == 3
    assert all("QTD_0" in path for path in changed.checked_files)


def test_rebound_table_files_recheck_old_and_new_reference_closures(tmp_path: Path) -> None:
    root, manifest = _publication(tmp_path / "publication")
    state = tmp_path / "state"
    history.HistoryPublicationReader(root).validate(state_root=state)
    state_path = next(state.glob("*.json"))
    before = state_path.read_bytes()

    first, second = manifest["tables"]
    first["files"]["rows"], second["files"]["rows"] = (
        second["files"]["rows"], first["files"]["rows"]
    )
    history._write_json(root / "history_manifest.json", manifest)

    with pytest.raises(ValueError, match="routine check anomaly"):
        history.HistoryPublicationReader(root).validate(state_root=state)
    assert state_path.read_bytes() == before


def test_reference_check_reads_each_narrow_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    root, manifest = _publication(tmp_path / "publication", second=False)
    inventory = history_validation._manifest_inventory(manifest)
    original = pl.LazyFrame.collect
    calls = 0

    def counted(frame, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(frame, *args, **kwargs)

    monkeypatch.setattr(pl.LazyFrame, "collect", counted)
    history_validation._check_table_references(root, inventory, set(inventory))
    assert calls == 3


@pytest.mark.parametrize(
    "anomaly",
    [
        "row-null",
        "row-duplicate",
        "column-null",
        "column-duplicate",
        "cell-null",
        "cell-duplicate",
        "row-reference-null",
        "column-reference-null",
        "row-reference-type",
    ],
)
def test_reference_anomalies_fail_and_preserve_state(tmp_path: Path, anomaly: str) -> None:
    root, manifest = _publication(tmp_path / "publication", second=False)
    state = tmp_path / "state"
    history.HistoryPublicationReader(root).validate(state_root=state)
    state_path = next(state.glob("*.json"))
    before = state_path.read_bytes()
    table = manifest["tables"][0]
    role = "rows" if anomaly.startswith("row-") else "columns"
    if "reference" in anomaly or anomaly.startswith("cell-"):
        role = "cells"
    rows = list(history.HistoryPublicationReader(root)._records(table["files"][role]))
    if anomaly.endswith("duplicate"):
        if role == "cells":
            rows[len(rows) // 2] = {
                **rows[len(rows) // 2],
                "fiscal_time_series_cell_id": rows[0]["fiscal_time_series_cell_id"],
            }
        else:
            rows.append(dict(rows[0]))
    elif anomaly == "row-null":
        rows[0] = {**rows[0], "fiscal_time_series_row_id": None}
    elif anomaly == "column-null":
        rows[0] = {**rows[0], "fiscal_time_series_column_id": None}
    elif anomaly == "cell-null":
        rows[len(rows) // 2] = {
            **rows[len(rows) // 2], "fiscal_time_series_cell_id": None
        }
    elif anomaly == "row-reference-null":
        rows[len(rows) // 2] = {
            **rows[len(rows) // 2], "fiscal_time_series_row_id": None
        }
    elif anomaly == "column-reference-null":
        rows[len(rows) // 2] = {
            **rows[len(rows) // 2], "fiscal_time_series_column_id": None
        }
    else:
        rows[0] = {**rows[0], "fiscal_time_series_row_id": 7}
    _rewrite_role(root, manifest, role, rows)

    with pytest.raises(ValueError, match="routine check anomaly"):
        history.HistoryPublicationReader(root).validate(state_root=state)
    assert state_path.read_bytes() == before


def test_state_or_code_drift_uses_detailed_storage_fallback(tmp_path: Path) -> None:
    root, manifest = _publication(tmp_path / "publication", second=False)
    state = tmp_path / "state"
    history.HistoryPublicationReader(root).validate(state_root=state)
    state_path = next(state.glob("*.json"))
    state_path.write_text("{broken", encoding="utf-8")
    calls = []
    result = validate_publication(
        root=root,
        manifest=manifest,
        detailed=lambda: calls.append("detailed"),
        code_identity="changed-code",
        state_root=state,
    )
    assert result.level == "DETAILED_FALLBACK"
    assert result.detailed_fallback
    assert calls == ["detailed"]
    saved = json.loads(state_path.read_text())
    assert saved["full_storage_validation"] is True
    assert saved["semantic_validation"] is False


@pytest.mark.parametrize("anomaly", ["extra", "dangling"])
def test_known_structure_or_reference_anomaly_remains_failure(
    tmp_path: Path, anomaly: str
) -> None:
    root, manifest = _publication(tmp_path / "publication", second=False)
    state = tmp_path / "state"
    history.HistoryPublicationReader(root).validate(state_root=state)
    state_path = next(state.glob("*.json"))
    before = state_path.read_bytes()
    if anomaly == "extra":
        extra = root / "foreign" / "history_manifest.json"
        extra.parent.mkdir()
        extra.write_bytes(b"foreign")
    else:
        _rewrite_first_cell(root, manifest, dangling=True)
    calls = []
    with pytest.raises(ValueError, match="anomaly"):
        validate_publication(
            root=root,
            manifest=json.loads((root / "history_manifest.json").read_text()),
            detailed=lambda: calls.append("strict-pass"),
            code_identity=json.loads(before)["code_identity"],
            state_root=state,
        )
    assert calls == ["strict-pass"]
    assert state_path.read_bytes() == before


def test_collection_attestation_uses_routine_result_without_second_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, manifest = _publication(tmp_path / "output" / "TEST" / "panels", second=False)
    intake = Path(manifest["source_intake"])
    intake.write_text("{}\n", encoding="utf-8")
    plan = manifest["plan"]
    marker = collection_operations._create_build_attestation(
        ticker="TEST",
        plan=plan,
        plan_sha256="plan",
        intake_path=intake,
        intake_sha256="intake",
        destination=tmp_path / "output" / "TEST",
        publication=publication,
        views=("LATEST_REPORTED",),
        validation_mode="routine",
        validation_state_root=tmp_path / "state",
    )
    assert marker["storage_validation"]["level"] == "ROUTINE_INITIAL"
    assert marker["declared_files"] == {
        info["path"]: info["sha256"]
        for info in manifest["tables"][0]["files"].values()
    }
    assert marker["history_manifest_sha256"] == hashlib.sha256(
        (publication / "history_manifest.json").read_bytes()
    ).hexdigest()


def test_detailed_result_does_not_record_file_changed_during_validation(tmp_path: Path) -> None:
    root, manifest = _publication(tmp_path / "publication", second=False)
    state = tmp_path / "state"
    history.HistoryPublicationReader(root).validate(state_root=state)
    state_path = next(state.glob("*.json"))
    before = state_path.read_bytes()
    data_path = root / manifest["tables"][0]["files"]["cells"]["path"]

    def mutate_during_detailed() -> None:
        with data_path.open("ab") as stream:
            stream.write(b"changed-after-check")

    with pytest.raises(ValueError, match="changed during detailed"):
        validate_publication(
            root=root,
            manifest=manifest,
            detailed=mutate_during_detailed,
            code_identity="explicit-detailed",
            mode="detailed",
            state_root=state,
        )
    assert state_path.read_bytes() == before


def test_quarter_publisher_default_enters_routine_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    class Reader:
        def __init__(self, *args, **kwargs) -> None:
            self.manifest = {
                "source_intake": str(tmp_path / "intake.json"),
                "views": ["LATEST_REPORTED"],
            }

        def validate(self, **kwargs) -> None:
            calls.append(kwargs)

        def verify_all(self) -> None:
            pytest.fail("ordinary quarter publication must use routine validation")

    monkeypatch.setattr(history_quarters, "HistoryPublicationReader", Reader)
    (tmp_path / "output" / "panels").mkdir(parents=True)
    with pytest.raises(ValueError, match="immutable quarterly publication"):
        history_quarters.publish_quarter_history(
            publication=tmp_path / "reported", output_root=tmp_path / "output"
        )
    assert calls == [{"mode": "routine", "state_root": None}]
