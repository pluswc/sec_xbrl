from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[2] / "tools" / "universe50_package_view.py"
SPEC = importlib.util.spec_from_file_location("universe50_package_view", MODULE_PATH)
assert SPEC and SPEC.loader
view = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(view)


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path, *, duplicate: bool = False, missing: bool = False) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cik = "0000000123"
    accessions = ["0000000123-25-000001", "0000000123-25-000002"]
    roots = [tmp_path / "cache-a", tmp_path / "cache-b"]
    for root in roots:
        root.mkdir()
    plan_rows, intake_rows = [], []
    for index, accession in enumerate(accessions):
        content = f"synthetic ZIP bytes {accession}".encode()
        package_hash = hashlib.sha256(content).hexdigest()
        source_run = tmp_path / f"source-{index}"
        write_json(
            source_run / "snapshots" / cik / accession.replace("-", "") / "layer1_manifest.json",
            {"cik": cik, "accession": accession, "package_sha256": package_hash},
        )
        filing = {"cik": cik, "accession": accession, "form": "10-K"}
        plan_rows.append(filing)
        intake_rows.append(
            {"filing": filing, "source_run": str(source_run), "status": "INGESTED", "ticker": "TEST"}
        )
        if not (missing and index == 1):
            target_roots = roots if index == 0 else roots[1:]
            for root in target_roots:
                package = root / cik / accession.replace("-", "") / f"{accession}-xbrl.zip"
                package.parent.mkdir(parents=True)
                package.write_bytes(content)
    if duplicate:
        plan_rows.append(dict(plan_rows[0]))
    plan = write_json(tmp_path / "plan.json", {"companies": [{"cik": cik, "filings": plan_rows}]})
    intake = write_json(tmp_path / "intake.json", {"complete": True, "filings": intake_rows})
    candidate = write_json(
        tmp_path / "candidate.json",
        {
            "membership": 1,
            "selected_filings_total": 2,
            "selection": [
                {
                    "ticker": "TEST",
                    "cik": cik,
                    "plan": str(plan),
                    "plan_sha256": digest(plan),
                    "intake": str(intake),
                    "intake_sha256": digest(intake),
                    "selected_filings": 2,
                }
            ],
        },
    )
    return {"candidate": candidate, "candidate_hash": digest(candidate), "roots": roots,
            "destination": tmp_path / "view", "cik": cik, "accessions": accessions}


def publish(case: dict[str, object]) -> Path:
    return view.publish_package_view(
        candidate=case["candidate"], candidate_sha256=case["candidate_hash"],
        cache_roots=case["roots"], destination=case["destination"]
    )


def test_publish_selects_declared_root_order_and_creates_only_hardlinks(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    manifest_path = publish(case)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["filing_count"] == 2
    assert manifest["company_count"] == 1
    first = manifest["filings"][0]
    assert [item["cache_root_index"] for item in first["all_matching_sources"]] == [0, 1]
    assert first["chosen_source"]["cache_root_index"] == 0
    for row in manifest["filings"]:
        output = Path(case["destination"]) / row["view_relative_path"]
        source = Path(row["chosen_source"]["path"])
        assert output.stat().st_ino == source.stat().st_ino
        assert output.stat().st_dev == source.stat().st_dev
        assert output.stat().st_blocks == source.stat().st_blocks
    verified = view.verify_package_view(Path(case["destination"]), digest(manifest_path))
    assert verified["selected_ciks"] == [case["cik"]]


def test_rejects_wrong_candidate_hash(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    case["candidate_hash"] = "0" * 64
    with pytest.raises(ValueError, match="candidate SHA-256 differs"):
        publish(case)


def test_rejects_missing_matching_archive_without_partial_destination(tmp_path: Path) -> None:
    case = fixture(tmp_path, missing=True)
    with pytest.raises(ValueError, match="no cached ZIP matches"):
        publish(case)
    assert not Path(case["destination"]).exists()


def test_rejects_duplicate_cik_accession(tmp_path: Path) -> None:
    case = fixture(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="duplicate plan filing"):
        publish(case)


def test_rejects_conflicting_plan_intake_metadata(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    intake_path = Path(json.loads(Path(case["candidate"]).read_text())["selection"][0]["intake"])
    intake = json.loads(intake_path.read_text())
    intake["filings"][0]["filing"]["form"] = "10-Q"
    write_json(intake_path, intake)
    candidate = json.loads(Path(case["candidate"]).read_text())
    candidate["selection"][0]["intake_sha256"] = digest(intake_path)
    write_json(Path(case["candidate"]), candidate)
    case["candidate_hash"] = digest(Path(case["candidate"]))
    with pytest.raises(ValueError, match="filing metadata differs"):
        publish(case)


def test_rejects_symlinked_archive(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    accession = case["accessions"][1]
    package = Path(case["roots"][1]) / case["cik"] / accession.replace("-", "") / f"{accession}-xbrl.zip"
    real = package.with_suffix(".real")
    package.rename(real)
    package.symlink_to(real)
    with pytest.raises(ValueError, match="non-symlink regular file"):
        publish(case)


def test_rejects_output_inside_source_and_existing_partial_destination(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    case["destination"] = Path(case["roots"][0]) / "view"
    with pytest.raises(ValueError, match="inside a source root"):
        publish(case)
    case = fixture(tmp_path / "other")
    Path(case["destination"]).mkdir()
    (Path(case["destination"]) / "partial").write_text("partial")
    with pytest.raises(FileExistsError, match="destination must be new"):
        publish(case)


def test_cross_filesystem_link_failure_has_no_copy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = fixture(tmp_path)

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(view.os, "link", fail_link)
    with pytest.raises(OSError, match="cross-device link"):
        publish(case)
    assert not Path(case["destination"]).exists()


def test_verify_rejects_changed_manifest_and_missing_view_file(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    manifest_path = publish(case)
    manifest_hash = digest(manifest_path)
    with pytest.raises(ValueError, match="manifest SHA-256 differs"):
        view.verify_package_view(Path(case["destination"]), "0" * 64)
    manifest = json.loads(manifest_path.read_text())
    (Path(case["destination"]) / manifest["filings"][0]["view_relative_path"]).unlink()
    with pytest.raises(ValueError, match="view package"):
        view.verify_package_view(Path(case["destination"]), manifest_hash)


def test_verify_rejects_changed_archive_bytes(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    manifest_path = publish(case)
    manifest_hash = digest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    Path(manifest["filings"][0]["chosen_source"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="source file identity changed|package hash changed"):
        view.verify_package_view(Path(case["destination"]), manifest_hash)
