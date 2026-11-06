from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl import history
from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import Layer2PublicationReader
from sec_xbrl.longitudinal.corpus_release import CorpusRelease, CorpusSnapshot
from sec_xbrl.longitudinal.fiscal_focus_correction import (
    FiscalFocusCorrectionError,
    FiscalFocusCorrectionRegistry,
)
from sec_xbrl.longitudinal.materialization import Layer1SnapshotInput, Layer2Run
from sec_xbrl.longitudinal.period_observation import PeriodObservationMaterializer
from sec_xbrl.longitudinal.versioned_observation_panel import VersionedObservationPanelPipeline

CIK = "0000000999"
ACCESSION = "0000000999-26-000060"
PACKAGE_MANIFEST_SHA = "097fdd83464cd8deff6491dd11da23bfc38ab6fce031e3a9ed931cb5106e0cbc"
LAYER1_MANIFEST_SHA = "9f3d28a4415306406964d36d231ac60c657cc1380ef8f12988d8fa144268ce20"


def _write_json(path: Path, payload: object) -> str:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _correction(
    tmp_path: Path,
    *,
    approval_scope: dict[str, object] | None = None,
    context_start: str = "2025-02-01",
) -> tuple[Path, str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    member = (
        '<html><xbrli:context id="c-1"><xbrli:entity><xbrli:identifier '
        'scheme="http://www.sec.gov/CIK">0000000999</xbrli:identifier></xbrli:entity>'
        f'<xbrli:period><xbrli:startDate>{context_start}</xbrli:startDate>'
        '<xbrli:endDate>2026-01-31</xbrli:endDate></xbrli:period></xbrli:context>'
        '<ix:nonNumeric contextRef="c-1" name="dei:DocumentFiscalYearFocus" '
        'id="f-36">2025</ix:nonNumeric></html>'
    ).encode()
    source_zip = tmp_path / "source.zip"
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fixture-20260131.htm", member)
    raw_zip_sha = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    with zipfile.ZipFile(source_zip) as archive:
        info = archive.getinfo("fixture-20260131.htm")
    scope = {
        "cik": CIK,
        "accession": ACCESSION,
        "qname": "dei:DocumentFiscalYearFocus",
        "fact_id": "f-36",
        "context_ref": "c-1",
        "reported_year": 2025,
        "effective_year": 2026,
        "package_manifest_sha256": PACKAGE_MANIFEST_SHA,
        "raw_xbrl_zip_sha256": raw_zip_sha,
    }
    if approval_scope:
        scope.update(approval_scope)
    approval = tmp_path / "approval.json"
    approval_sha = _write_json(
        approval,
        {
            "schema_version": "lead-accession-fiscal-focus-approval-v1",
            "status": "USER_APPROVED_BOUNDED_IMPLEMENTATION",
            "authorized_by": "HUMAN_USER",
            "scope": scope,
        },
    )
    supplement = tmp_path / "evidence-supplement.json"
    supplement_sha = _write_json(
        supplement,
        {
            "schema_version": "lead-accession-fiscal-focus-evidence-supplement-v1",
            "status": "ROOT_APPROVED_EVIDENCE_DETAIL_WITHIN_HUMAN_APPROVED_SCOPE",
            "authorized_by": "ROOT_LEAD",
            "human_approval": {"path": str(approval), "sha256": approval_sha},
            "scope": {
                **scope,
                "primary_document": "fixture-20260131.htm",
                "context_start_date": "2025-02-01",
                "context_end_date": "2026-01-31",
                "layer1_manifest_sha256": LAYER1_MANIFEST_SHA,
            },
            "source_evidence": {
                "member_name": "fixture-20260131.htm",
                "member_size": info.file_size,
                "member_crc32": f"{info.CRC:08x}",
                "maximum_prefix_bytes": 131072,
                "reported_lexical_value": "2025",
                "narrative_fiscal_year": 2026,
            },
        },
    )
    artifact = tmp_path / "corrections.json"
    artifact_sha = _write_json(
        artifact,
        {
            "schema_version": "layer2-fiscal-focus-corrections-v1",
            "corrections": [
                {
                    "correction_id": "fixture-2026-fiscal-focus-v1",
                    "cik": CIK,
                    "accession": ACCESSION,
                    "form": "10-K",
                    "primary_document": "fixture-20260131.htm",
                    "report_date": "2026-01-31",
                    "reported": {
                        "qname": "dei:DocumentFiscalYearFocus",
                        "fact_id": "f-36",
                        "context_ref": "c-1",
                        "fiscal_year": 2025,
                        "fiscal_period": "FY",
                        "context_start_date": "2025-02-01",
                        "context_end_date": "2026-01-31",
                    },
                    "source": {
                        "package_manifest_sha256": PACKAGE_MANIFEST_SHA,
                        "raw_xbrl_zip_path": str(source_zip),
                        "raw_xbrl_zip_sha256": raw_zip_sha,
                        "layer1_manifest_sha256": LAYER1_MANIFEST_SHA,
                    },
                    "effective": {"fiscal_year": 2026},
                    "approval": {"path": str(approval), "sha256": approval_sha},
                    "evidence_supplement": {
                        "path": str(supplement), "sha256": supplement_sha,
                    },
                }
            ],
        },
    )
    return artifact, artifact_sha, raw_zip_sha


def _snapshot(
    *,
    accession: str = ACCESSION,
    package_sha: str = "a" * 64,
    cik: str = CIK,
    form: str = "10-K",
    report_date: str = "2026-01-31",
    primary_document: str = "fixture-20260131.htm",
    fiscal_year_focus: str = "2025",
    fiscal_period_focus: str = "FY",
    context_start: str = "2025-02-01",
    context_end: str = "2026-01-31",
    layer1_manifest_sha: str = LAYER1_MANIFEST_SHA,
) -> CorpusSnapshot:
    filing_id = f"filing:{accession}"
    filing = {
        "filing_id": filing_id,
        "cik": cik,
        "accession": accession,
        "form": form,
        "filed_date": "2026-03-04",
        "report_date": report_date,
        "primary_document": primary_document,
        "document_fiscal_year_focus": fiscal_year_focus,
        "document_fiscal_period_focus": fiscal_period_focus,
        "fiscal_year_end": "--01-31",
        "is_amendment": False,
    }
    current_duration_days = (
        date.fromisoformat(context_end) - date.fromisoformat(context_start)
    ).days
    contexts = (
        {"filing_id": filing_id, "context_id": "current", "period_kind": "DURATION", "start_date": context_start, "end_date": context_end, "instant_date": None, "duration_days": current_duration_days},
        {"filing_id": filing_id, "context_id": "prior", "period_kind": "DURATION", "start_date": "2024-02-01", "end_date": "2025-01-31", "instant_date": None, "duration_days": 365},
    )
    tables = {
        "filing": (filing,),
        "concept": ({"filing_id": filing_id, "raw_concept_id": "revenue", "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "namespace_uri": "http://fasb.org/us-gaap/2025", "local_name": "RevenueFromContractWithCustomerExcludingAssessedTax", "period_type": "duration", "data_type": "monetaryItemType", "is_standard": True},),
        "context": contexts,
        "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
        "fact": tuple({"filing_id": filing_id, "fact_id": f"fact:{name}", "raw_concept_id": "revenue", "context_id": name, "unit_id": "usd", "value_numeric": value, "value_text": None, "is_nil": False, "source_document": primary_document, "source_locator": "line:8", "comparative_type": "CURRENT_FOCUS" if name == "current" else "PRIOR_YEAR_COMPARABLE"} for name, value in (("current", "100"), ("prior", "90"))),
        "dimension_fact": (),
        "role": (),
        "relationship": (),
    }
    manifest = Layer1SnapshotManifest(
        schema_version=1, cik=cik, accession=accession, form=form,
        source_url="fixture", package_sha256=package_sha, fact_corpus_source="fixture",
        source_fact_count=2, materialized_fact_count=2, concept_count=1, context_count=2,
        unit_count=1, dimension_fact_count=0, role_count=0, relationship_count=0,
        layer1_parser_version="m2-layer1-v6", relationship_parser_version="fixture",
    )
    input_row = Layer1SnapshotInput(
        cik, accession, form, "2026-03-04", report_date, f"snapshot:{accession}",
        layer1_manifest_sha,
    )
    frozen = MappingProxyType(
        {name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}
    )
    return CorpusSnapshot(
        input_row, manifest, Path("/fixture/layer1_manifest.json"), MappingProxyType({}),
        MappingProxyType({name: len(rows) for name, rows in tables.items()}), frozen,
    )


def _release(snapshot: CorpusSnapshot, artifact_sha: str | None = None) -> CorpusRelease:
    rules = history._history_layer2_rule_versions(artifact_sha)
    run = Layer2Run("fixture-correction-test", "fixture", (snapshot.input,), rules)
    return CorpusRelease(Path("/fixture"), "fixture", (snapshot.input.cik,), (snapshot,), run)


def _generic_v2_corrections(
    tmp_path: Path,
) -> tuple[Path, str, tuple[CorpusSnapshot, ...]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cik = "0000000888"
    definitions = (
        {
            "correction_id": "fixture-2021-annual-focus-v1",
            "accession": "0000000888-22-000018",
            "form": "10-K",
            "primary_document": "fixture-20211231.htm",
            "report_date": "2021-12-31",
            "qname": "dei:DocumentFiscalYearFocus",
            "fact_id": "annual-year",
            "context_ref": "annual-context",
            "context_start_date": "2021-01-01",
            "context_end_date": "2021-12-31",
            "reported_year": 2020,
            "reported_period": "FY",
            "effective_year": 2021,
            "effective_period": "FY",
            "layer1_manifest_sha256": "1" * 64,
        },
        {
            "correction_id": "fixture-2021-q3-focus-v1",
            "accession": "0000000888-21-000065",
            "form": "10-Q",
            "primary_document": "fixture-20210930.htm",
            "report_date": "2021-09-30",
            "qname": "dei:DocumentFiscalPeriodFocus",
            "fact_id": "quarter-period",
            "context_ref": "quarter-context",
            "context_start_date": "2021-01-01",
            "context_end_date": "2021-09-30",
            "reported_year": 2021,
            "reported_period": "Q2",
            "effective_year": 2021,
            "effective_period": "Q3",
            "layer1_manifest_sha256": "2" * 64,
        },
    )
    prepared: list[dict[str, object]] = []
    snapshots: list[CorpusSnapshot] = []
    for definition in definitions:
        reported_lexical = (
            str(definition["reported_year"])
            if definition["qname"] == "dei:DocumentFiscalYearFocus"
            else str(definition["reported_period"])
        )
        member = (
            f'<html><xbrli:context id="{definition["context_ref"]}">'
            '<xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">'
            f'{cik}</xbrli:identifier></xbrli:entity><xbrli:period>'
            f'<xbrli:startDate>{definition["context_start_date"]}</xbrli:startDate>'
            f'<xbrli:endDate>{definition["context_end_date"]}</xbrli:endDate>'
            '</xbrli:period></xbrli:context>'
            f'<ix:nonNumeric contextRef="{definition["context_ref"]}" '
            f'name="{definition["qname"]}" id="{definition["fact_id"]}">'
            f'{reported_lexical}</ix:nonNumeric></html>'
        ).encode()
        source_zip = tmp_path / f'{definition["accession"]}.zip'
        with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(str(definition["primary_document"]), member)
        raw_zip_sha = hashlib.sha256(source_zip.read_bytes()).hexdigest()
        with zipfile.ZipFile(source_zip) as archive:
            info = archive.getinfo(str(definition["primary_document"]))
        prepared.append(
            {
                **definition,
                "reported_lexical": reported_lexical,
                "effective_lexical": (
                    str(definition["effective_year"])
                    if definition["qname"] == "dei:DocumentFiscalYearFocus"
                    else str(definition["effective_period"])
                ),
                "source_zip": source_zip,
                "raw_zip_sha": raw_zip_sha,
                "member_size": info.file_size,
                "member_crc32": f"{info.CRC:08x}",
            }
        )
        snapshots.append(
            _snapshot(
                cik=cik,
                accession=str(definition["accession"]),
                form=str(definition["form"]),
                report_date=str(definition["report_date"]),
                primary_document=str(definition["primary_document"]),
                fiscal_year_focus=str(definition["reported_year"]),
                fiscal_period_focus=str(definition["reported_period"]),
                context_start=str(definition["context_start_date"]),
                context_end=str(definition["context_end_date"]),
                package_sha=raw_zip_sha,
                layer1_manifest_sha=str(definition["layer1_manifest_sha256"]),
            )
        )
    diagnosis = tmp_path / "diagnosis.json"
    diagnosis_sha = _write_json(
        diagnosis,
        {
            "schema_version": "root-hon-original-fiscal-metadata-conflict-diagnosis-v1",
            "status": "SOURCE_CONFLICT_CONFIRMED_NO_CORRECTION_AUTHORIZED",
            "verified_by": "ROOT_LEAD",
            "source_conflicts": [
                {
                    "accession": item["accession"],
                    "raw_zip": {
                        "path": str(item["source_zip"]),
                        "sha256": item["raw_zip_sha"],
                    },
                    "member": {
                        "name": item["primary_document"],
                        "size": item["member_size"],
                        "crc32": item["member_crc32"],
                    },
                    "bounded_prefix_bytes": 131072,
                    "layer1_manifest": {
                        "path": f'/fixture/{item["accession"]}/layer1_manifest.json',
                        "sha256": item["layer1_manifest_sha256"],
                    },
                    "package_manifest_sha256": item["raw_zip_sha"],
                    "facts": [
                        {
                            "qname": item["qname"],
                            "value": item["reported_lexical"],
                            "fact_id": item["fact_id"],
                            "context_ref": item["context_ref"],
                        }
                    ],
                    "contexts": {
                        item["context_ref"]: (
                            f'<xbrli:context id="{item["context_ref"]}"><xbrli:period>'
                            f'<xbrli:startDate>{item["context_start_date"]}</xbrli:startDate>'
                            f'<xbrli:endDate>{item["context_end_date"]}</xbrli:endDate>'
                            '</xbrli:period></xbrli:context>'
                        )
                    },
                }
                for item in prepared
            ],
            "proposed_effective_corrections": [
                {
                    "accession": item["accession"],
                    "qname": item["qname"],
                    "reported": item["reported_lexical"],
                    "effective": item["effective_lexical"],
                }
                for item in prepared
            ],
        },
    )
    approval = tmp_path / "approval.json"
    approval_payload = {
        "schema_version": "lead-hon-exact-two-fiscal-focus-user-approval-v1",
        "status": "USER_APPROVED_BOUNDED_IMPLEMENTATION",
        "authorized_by": "HUMAN_USER",
        "diagnosis": {"path": str(diagnosis), "sha256": diagnosis_sha},
        "cik": cik,
        "corrections": [
            {
                "accession": item["accession"],
                "qname": item["qname"],
                "reported": item["reported_lexical"],
                "effective": item["effective_lexical"],
            }
            for item in prepared
        ],
    }
    approval_sha = _write_json(approval, approval_payload)
    approval_ref = {"path": str(approval), "sha256": approval_sha}
    supplement = tmp_path / "evidence-supplement.json"
    supplement_sha = _write_json(
        supplement,
        {
            "schema_version": "lead-accession-fiscal-focus-evidence-supplement-v2",
            "status": "ROOT_APPROVED_EVIDENCE_DETAIL_WITHIN_HUMAN_APPROVED_SCOPE",
            "authorized_by": "ROOT_LEAD",
            "human_approval": approval_ref,
            "diagnosis": approval_payload["diagnosis"],
            "corrections": [
                {
                    "cik": cik,
                    "accession": item["accession"],
                    "primary_document": item["primary_document"],
                    "qname": item["qname"],
                    "fact_id": item["fact_id"],
                    "context_ref": item["context_ref"],
                    "context_start_date": item["context_start_date"],
                    "context_end_date": item["context_end_date"],
                    "reported_lexical_value": item["reported_lexical"],
                    "effective_lexical_value": item["effective_lexical"],
                    "package_manifest_sha256": item["raw_zip_sha"],
                    "raw_xbrl_zip_sha256": item["raw_zip_sha"],
                    "layer1_manifest_sha256": item["layer1_manifest_sha256"],
                    "source_evidence": {
                        "member_name": item["primary_document"],
                        "member_size": item["member_size"],
                        "member_crc32": item["member_crc32"],
                        "maximum_prefix_bytes": 131072,
                    },
                }
                for item in prepared
            ],
        },
    )
    artifact = tmp_path / "fixture-corrections.json"
    artifact_sha = _write_json(
        artifact,
        {
            "schema_version": "layer2-fiscal-focus-corrections-v2",
            "corrections": [
                {
                    "correction_id": item["correction_id"],
                    "cik": cik,
                    "accession": item["accession"],
                    "form": item["form"],
                    "primary_document": item["primary_document"],
                    "report_date": item["report_date"],
                    "reported": {
                        "qname": item["qname"],
                        "fact_id": item["fact_id"],
                        "context_ref": item["context_ref"],
                        "fiscal_year": item["reported_year"],
                        "fiscal_period": item["reported_period"],
                        "context_start_date": item["context_start_date"],
                        "context_end_date": item["context_end_date"],
                    },
                    "source": {
                        "package_manifest_sha256": item["raw_zip_sha"],
                        "raw_xbrl_zip_path": str(item["source_zip"]),
                        "raw_xbrl_zip_sha256": item["raw_zip_sha"],
                        "layer1_manifest_sha256": item["layer1_manifest_sha256"],
                    },
                    "effective": {
                        "fiscal_year": item["effective_year"],
                        "fiscal_period": item["effective_period"],
                    },
                    "approval": approval_ref,
                    "evidence_supplement": {
                        "path": str(supplement), "sha256": supplement_sha,
                    },
                }
                for item in prepared
            ],
        },
    )
    return artifact, artifact_sha, tuple(snapshots)


def test_exact_correction_preserves_reported_focus_and_corrects_current_and_comparative(tmp_path: Path) -> None:
    artifact, artifact_sha, raw_zip_sha = _correction(tmp_path)
    registry = FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)
    snapshot = _snapshot(package_sha=raw_zip_sha)
    original_filing = snapshot.records("filing")[0]

    result = VersionedObservationPanelPipeline().publish(
        _release(snapshot, artifact_sha),
        output_root=tmp_path / "corrected",
        _effective_filings={snapshot.input.snapshot_id:registry.apply(snapshot,original_filing)},
    )
    registry.require_all_consumed()
    rows = Layer2PublicationReader().load(result.publication.run_root).records(
        "reported_period_observation"
    )
    by_type = {row["comparative_type"]: row for row in rows}

    assert by_type["CURRENT_FOCUS"]["fiscal_year"] == 2026
    assert by_type["PRIOR_YEAR_COMPARABLE"]["fiscal_year"] == 2025
    assert all(row["reported_document_fiscal_year_focus"] == "2025" for row in rows)
    assert all(row["effective_document_fiscal_year_focus"] == "2026" for row in rows)
    assert all(row["fiscal_focus_correction_artifact_sha256"] == artifact_sha for row in rows)
    assert all("reported_document_fiscal_period_focus" not in row for row in rows)
    assert original_filing["document_fiscal_year_focus"] == "2025"


def test_v2_year_and_period_corrections_preserve_both_reported_focuses(
    tmp_path: Path,
) -> None:
    artifact, artifact_sha, snapshots = _generic_v2_corrections(tmp_path)
    registry = FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)
    rows = []
    materializer = PeriodObservationMaterializer()
    for snapshot in snapshots:
        filing = registry.apply(snapshot, snapshot.records("filing")[0])
        result = materializer.materialize(
            filing=filing,
            concepts=snapshot.records("concept"),
            contexts=snapshot.records("context"),
            units=snapshot.records("unit"),
            facts=snapshot.records("fact"),
            dimension_facts=snapshot.records("dimension_fact"),
            source_snapshot_id=snapshot.input.snapshot_id,
        )
        rows.extend(result.observations)
    registry.require_all_consumed()
    annual = [row for row in rows if row["accession"] == "0000000888-22-000018"]
    quarter = [row for row in rows if row["accession"] == "0000000888-21-000065"]

    assert {row["fiscal_year"] for row in annual} == {2021}
    assert {row["fiscal_quarter"] for row in annual} == {4}
    assert {row["fiscal_year"] for row in quarter} == {2021}
    assert {row["fiscal_quarter"] for row in quarter} == {3}
    assert all(row["reported_document_fiscal_year_focus"] == "2020" for row in annual)
    assert all(row["effective_document_fiscal_year_focus"] == "2021" for row in annual)
    assert all(row["reported_document_fiscal_period_focus"] == "FY" for row in annual)
    assert all(row["effective_document_fiscal_period_focus"] == "FY" for row in annual)
    assert all(row["reported_document_fiscal_year_focus"] == "2021" for row in quarter)
    assert all(row["effective_document_fiscal_year_focus"] == "2021" for row in quarter)
    assert all(row["reported_document_fiscal_period_focus"] == "Q2" for row in quarter)
    assert all(row["effective_document_fiscal_period_focus"] == "Q3" for row in quarter)


def test_v2_rejects_unchanged_or_wrong_qname_correction(tmp_path: Path) -> None:
    artifact, _artifact_sha, _snapshots = _generic_v2_corrections(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    quarter = payload["corrections"][1]
    quarter["effective"]["fiscal_period"] = "Q2"
    unchanged_sha = _write_json(artifact, payload)
    with pytest.raises(FiscalFocusCorrectionError, match="exactly one focus field"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=unchanged_sha)

    artifact, _artifact_sha, _snapshots = _generic_v2_corrections(tmp_path / "wrong-qname")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["corrections"][1]["reported"]["qname"] = "dei:DocumentFiscalYearFocus"
    wrong_qname_sha = _write_json(artifact, payload)
    with pytest.raises(FiscalFocusCorrectionError, match="QName"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=wrong_qname_sha)

    artifact, _artifact_sha, _snapshots = _generic_v2_corrections(tmp_path / "bad-period")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["corrections"][1]["effective"]["fiscal_period"] = True
    bad_period_sha = _write_json(artifact, payload)
    with pytest.raises(FiscalFocusCorrectionError, match="unsupported"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=bad_period_sha)


def test_v2_rejects_missing_approved_entry_and_duplicate_consumption(tmp_path: Path) -> None:
    artifact, _artifact_sha, snapshots = _generic_v2_corrections(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["corrections"] = payload["corrections"][:1]
    missing_sha = _write_json(artifact, payload)
    with pytest.raises(FiscalFocusCorrectionError, match="approval correction identities"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=missing_sha)

    artifact, artifact_sha, snapshots = _generic_v2_corrections(tmp_path / "duplicate")
    registry = FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)
    filing = snapshots[0].records("filing")[0]
    registry.apply(snapshots[0], filing)
    with pytest.raises(FiscalFocusCorrectionError, match="consumed more than once"):
        registry.apply(snapshots[0], filing)


def test_v2_rejects_replaced_source_even_when_artifact_and_supplement_are_repinned(
    tmp_path: Path,
) -> None:
    artifact, _artifact_sha, _snapshots = _generic_v2_corrections(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    entry = payload["corrections"][0]
    original_zip = Path(entry["source"]["raw_xbrl_zip_path"])
    member_name = entry["primary_document"]
    with zipfile.ZipFile(original_zip) as archive:
        replaced_member = archive.read(member_name) + b" "
    replaced_zip = tmp_path / "repinned-substitute.zip"
    with zipfile.ZipFile(replaced_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, replaced_member)
    replaced_sha = hashlib.sha256(replaced_zip.read_bytes()).hexdigest()
    with zipfile.ZipFile(replaced_zip) as archive:
        info = archive.getinfo(member_name)
    entry["source"].update(
        {
            "package_manifest_sha256": replaced_sha,
            "raw_xbrl_zip_path": str(replaced_zip),
            "raw_xbrl_zip_sha256": replaced_sha,
        }
    )
    supplement_path = Path(entry["evidence_supplement"]["path"])
    supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
    supplement_record = supplement["corrections"][0]
    supplement_record["package_manifest_sha256"] = replaced_sha
    supplement_record["raw_xbrl_zip_sha256"] = replaced_sha
    supplement_record["source_evidence"].update(
        {"member_size": info.file_size, "member_crc32": f"{info.CRC:08x}"}
    )
    supplement_sha = _write_json(supplement_path, supplement)
    for correction in payload["corrections"]:
        correction["evidence_supplement"]["sha256"] = supplement_sha
    artifact_sha = _write_json(artifact, payload)

    with pytest.raises(FiscalFocusCorrectionError, match="diagnosis source identity"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)


def test_default_and_unrelated_accessions_remain_unchanged(tmp_path: Path) -> None:
    snapshot = _snapshot(accession="0000000999-25-000001")
    result = VersionedObservationPanelPipeline().publish(
        _release(snapshot), output_root=tmp_path / "default"
    )
    rows = Layer2PublicationReader().load(result.publication.run_root).records(
        "reported_period_observation"
    )
    assert {row["fiscal_year"] for row in rows} == {2025}
    assert all("fiscal_focus_correction_id" not in row for row in rows)
    assert history._history_layer2_rule_versions().period_rule_version == "period-fiscal-boundaries-v2"


def test_correction_fails_closed_on_source_mismatch_or_unconsumed_entry(tmp_path: Path) -> None:
    artifact, artifact_sha, _raw_zip_sha = _correction(tmp_path)
    registry = FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)
    with pytest.raises(FiscalFocusCorrectionError, match="snapshot evidence mismatch"):
        registry.apply(_snapshot(package_sha="f" * 64), _snapshot().records("filing")[0])

    fresh = FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)
    with pytest.raises(FiscalFocusCorrectionError, match="not consumed"):
        fresh.require_all_consumed()


def test_correction_fails_closed_on_artifact_or_approval_corruption(tmp_path: Path) -> None:
    artifact, _artifact_sha, _raw_zip_sha = _correction(tmp_path)
    with pytest.raises(FiscalFocusCorrectionError, match="artifact SHA-256 mismatch"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256="0" * 64)

    mismatched, mismatched_sha, _mismatched_raw_sha = _correction(
        tmp_path / "mismatch", approval_scope={"fact_id": "wrong-fact"}
    )
    with pytest.raises(FiscalFocusCorrectionError, match="approval scope"):
        FiscalFocusCorrectionRegistry.load(mismatched, expected_sha256=mismatched_sha)


def test_correction_fails_closed_when_hash_bound_inline_context_differs(tmp_path: Path) -> None:
    artifact, artifact_sha, _raw_zip_sha = _correction(
        tmp_path, context_start="1900-01-01"
    )
    with pytest.raises(FiscalFocusCorrectionError, match="context period differs"):
        FiscalFocusCorrectionRegistry.load(artifact, expected_sha256=artifact_sha)


def test_correction_hash_changes_history_fingerprint() -> None:
    base = _release(_snapshot()).layer2_run
    corrected = replace(base, rules=history._history_layer2_rule_versions("a" * 64))
    assert corrected.rules.period_rule_version.endswith("a" * 64)
    assert corrected.fingerprint != base.fingerprint


def test_effective_filing_copy_is_shared_with_append_ledger_and_coverage(tmp_path):
    from sec_xbrl.history_reuse import _small_release_state
    artifact,artifact_sha,snapshots=_generic_v2_corrections(tmp_path)
    registry=FiscalFocusCorrectionRegistry.load(artifact,expected_sha256=artifact_sha)
    effective={snapshot.input.snapshot_id:registry.apply(snapshot,snapshot.records("filing")[0]) for snapshot in snapshots}
    registry.require_all_consumed()
    release=_release(snapshots[0],artifact_sha)
    release=replace(release,snapshots=snapshots)
    filings,ledger=_small_release_state(release,effective_filings=effective)
    assert {row["document_fiscal_year_focus"] for row in filings.values()}=={"2021"}
    assert {row["document_fiscal_period_focus"] for row in filings.values()}=={"FY","Q3"}
    assert {row["filing"]["document_fiscal_period_focus"] for rows in ledger.values() for row in rows}=={"FY","Q3"}
    coverage=history._filing_coverage_keys(tuple(filings.values()),"0000000888")
    assert any(key[1]==2021 and key[2]==3 for key in coverage)
    assert snapshots[0].records("filing")[0]["document_fiscal_year_focus"]=="2020"
