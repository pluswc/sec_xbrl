from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    AccessionVersionLedgerPipeline,
    AccessionVersionLedgerReader,
    CorpusRelease,
    CorpusSnapshot,
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
)


def _release() -> CorpusRelease:
    cik = "0000320193"
    snapshots = (
        _snapshot(cik, "0000320193-25-000010", "10-Q", "2025-05-01"),
        _snapshot(
            cik,
            "0000320193-25-000011",
            "10-Q/A",
            "2025-06-01",
            description="Amendment Number 2; see 0000320193-25-000010.",
        ),
        _snapshot(cik, "0000320193-25-000009", "10-K", "2025-06-01"),
    )
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    return CorpusRelease(
        Path("/fixture"),
        "fixture",
        (cik,),
        snapshots,
        Layer2Run("t4-accession-ledger-fixture-v1", "fixture", tuple(s.input for s in snapshots), rules),
    )


def _snapshot(
    cik: str, accession: str, form: str, filed_date: str, *, description: str | None = None
) -> CorpusSnapshot:
    filing_id = f"filing:{accession}"
    concepts = ()
    facts = ()
    if description is not None:
        concepts = (
            {"filing_id": filing_id, "raw_concept_id": "dei:flag", "local_name": "AmendmentFlag", "taxonomy_family": "dei"},
            {"filing_id": filing_id, "raw_concept_id": "dei:description", "local_name": "AmendmentDescription", "taxonomy_family": "dei"},
        )
        facts = (
            {"filing_id": filing_id, "fact_id": "fact:flag", "raw_concept_id": "dei:flag", "value_text": "true", "is_nil": False},
            {"filing_id": filing_id, "fact_id": "fact:description", "raw_concept_id": "dei:description", "value_text": description, "is_nil": False},
        )
    tables = {
        "filing": (
            {
                "filing_id": filing_id,
                "cik": cik,
                "accession": accession,
                "form": form,
                "filed_date": filed_date,
                "report_date": "2025-03-29" if form.startswith("10-Q") else "2024-09-28",
                "is_amendment": form.endswith("/A"),
            },
        ),
        "concept": concepts,
        "context": (),
        "unit": (),
        "fact": facts,
        "dimension_fact": (),
        "role": (),
        "relationship": (),
    }
    manifest = Layer1SnapshotManifest(
        1, cik, accession, form, "fixture", "a" * 64, "fixture", 1, len(concepts), 0,
        0, len(facts), 0, 0, 0, "fixture", "fixture",
    )
    input_row = Layer1SnapshotInput(
        cik, accession, form, filed_date, tables["filing"][0]["report_date"],
        f"snap:{accession[-6:]}", hashlib.sha256(accession.encode()).hexdigest(),
    )
    frozen = MappingProxyType(
        {name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}
    )
    return CorpusSnapshot(
        input_row, manifest, Path(f"/fixture/{accession}/layer1_manifest.json"),
        MappingProxyType({}), MappingProxyType({name: len(rows) for name, rows in tables.items()}), frozen,
    )


def test_t4_ledger_keeps_dei_evidence_and_only_explicit_ordinal(tmp_path: Path) -> None:
    result = AccessionVersionLedgerPipeline().publish(_release(), output_root=tmp_path / "layer2")
    publication = Layer2PublicationReader().load(result.publication.run_root)
    rows = AccessionVersionLedgerReader().get_company(publication, cik="0000320193")

    assert result.filing_count == 3
    assert [row["accession"] for row in rows] == [
        "0000320193-25-000010", "0000320193-25-000009", "0000320193-25-000011"
    ]
    amendment = rows[-1]
    assert amendment["amendment_flag_state"] == "REPORTED_TRUE"
    assert amendment["dei_amendment_description_fact_id"] == "fact:description"
    assert amendment["amends_accession"] == "0000320193-25-000010"
    assert amendment["amendment_linkage_state"] == "LINKED"
    assert amendment["amendment_linkage_method"] == "DEI_DESCRIPTION_ACCESSION"
    assert amendment["reported_amendment_ordinal"] == "2"
    assert amendment["amendment_ordinal_method"] == "DEI_DESCRIPTION_TEXT"
    assert rows[0]["reported_amendment_ordinal_state"] == "NOT_REPORTED"


def test_t4_compatible_filing_is_candidate_not_a_confirmed_amendment(tmp_path: Path) -> None:
    cik = "0000789019"
    original = _snapshot(cik, "0000789019-25-000010", "10-Q", "2025-05-01")
    amendment = _snapshot(cik, "0000789019-25-000011", "10-Q/A", "2025-06-01")
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    release = CorpusRelease(
        Path("/fixture"), "fixture", (cik,), (original, amendment),
        Layer2Run("t4-accession-ledger-candidate-v1", "fixture", (original.input, amendment.input), rules),
    )
    result = AccessionVersionLedgerPipeline().publish(release, output_root=tmp_path / "layer2")
    direct = AccessionVersionLedgerReader().query_parquet(result.publication.run_root, cik=cik)
    row = direct[-1]

    assert row["amends_accession"] == "0000789019-25-000010"
    assert row["amendment_linkage_state"] == "CANDIDATE"
    assert row["amendment_linkage_review_status"] == "REVIEW_REQUIRED"
    assert row["reported_amendment_ordinal_state"] == "NOT_REPORTED"


def test_t4_does_not_treat_custom_same_local_name_as_dei_evidence(tmp_path: Path) -> None:
    cik = "0001652044"
    amendment = _snapshot(cik, "0001652044-25-000011", "10-Q/A", "2025-06-01")
    filing_id = str(amendment.records("filing")[0]["filing_id"])
    tables = {name: amendment.records(name) for name in amendment.tables}
    tables["concept"] = (
        {
            "filing_id": filing_id,
            "raw_concept_id": "custom:flag",
            "local_name": "AmendmentFlag",
            "taxonomy_family": "company-extension",
            "namespace_uri": "http://example.com/custom/2025",
        },
        {
            "filing_id": filing_id,
            "raw_concept_id": "custom:description",
            "local_name": "AmendmentDescription",
            "taxonomy_family": "company-extension",
            "namespace_uri": "http://example.com/custom/2025",
        },
    )
    tables["fact"] = (
        {"filing_id": filing_id, "fact_id": "custom:flag", "raw_concept_id": "custom:flag", "value_text": "true", "is_nil": False},
        {"filing_id": filing_id, "fact_id": "custom:description", "raw_concept_id": "custom:description", "value_text": "Amendment Number 99", "is_nil": False},
    )
    custom_snapshot = CorpusSnapshot(
        amendment.input, amendment.manifest, amendment.manifest_path, amendment.table_sha256,
        MappingProxyType({name: len(rows) for name, rows in tables.items()}),
        MappingProxyType({name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}),
    )
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    release = CorpusRelease(
        Path("/fixture"), "fixture", (cik,), (custom_snapshot,),
        Layer2Run("t4-accession-ledger-custom-qname-v1", "fixture", (custom_snapshot.input,), rules),
    )
    result = AccessionVersionLedgerPipeline().publish(release, output_root=tmp_path / "layer2")
    row = AccessionVersionLedgerReader().query_parquet(result.publication.run_root, cik=cik)[0]

    assert row["amendment_flag_state"] == "NOT_REPORTED"
    assert row["dei_amendment_description_raw"] is None
    assert row["reported_amendment_ordinal_state"] == "NOT_REPORTED"
