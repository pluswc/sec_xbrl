from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace

import pytest

from sec_xbrl.analytics import statement_source
from sec_xbrl.longitudinal import corpus_release
from sec_xbrl.metrics import statement_metric_evidence as evidence

CIK = "0000000042"
ACCESSION = "0000000042-26-000001"


def _case():
    filing = {
        "cik": CIK, "accession": ACCESSION, "form": "10-Q",
        "filed_date": "2026-07-31", "report_date": "2026-06-30",
        "filing_id": "filing", "primary_document": "filing.htm", "package_hash": "pinned-package",
    }
    fact = {
        "fact_id": "fact", "raw_concept_id": "concept", "context_id": "context", "unit_id": "usd",
        "concept": {
            "qname": evidence.PRODUCTIVE_ASSETS, "is_standard": True,
            "namespace_uri": "https://fasb.org/us-gaap/2026", "data_type": "monetaryItemType",
            "period_type": "duration",
        },
        "context": {"entity_identifier": "http://www.sec.gov/CIK:" + CIK},
        "scope": {
            "dimensions": [], "unit": {"numerator": ["iso4217:USD"], "denominator": []},
            "period": {"class": "QTD_3M", "type": "duration", "start": "2026-04-01", "end": "2026-07-01"},
        },
        "value_numeric": "54208000000", "is_nil": False, "reported_or_derived": "REPORTED",
        "source_locations": [{
            "table_id": "table", "row_id": "row", "binding_status": "EXACT_RAW_ID",
            "table_locator": "/table", "row_locator": "/table/tr",
            "cell_locator": "/table/tr/td[2]", "inline_id": "inline",
        }],
    }
    table = {
        "table_id": "table", "section": "CF", "role_id": "role",
        "source_document": "filing.htm", "source_document_sha256": "document", "table_sha256": "table-digest",
    }
    row = {
        "row_id": "row", "coverage_status": "INCLUDED",
        "label": "Purchases of property and equipment", "pre_path_ids": ["pre"],
    }
    pre = {"row_id": "pre", "raw_concept_id": "concept", "network_identity": {"role_id": "role"}, "cycle": False}
    return filing, {
        "statement_facts": [fact], "source_tables": [table],
        "source_statement_rows": [row], "statement_rows": [pre],
    }


def test_exact_primary_occurrence_preserves_raw_identity_and_amount():
    filing, prepared = _case()
    result, = evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                               snapshot_manifest_sha256="manifest")
    assert result["source_fact_id"] == "fact"
    assert result["value"] == "54208000000"
    assert result["source_row_id"] == "row"
    assert result["statement_role_id"] == "role"
    assert result["source_document_sha256"] == "document"


@pytest.mark.parametrize(
    ("record", "field", "value"),
    [
        ("source_statement_rows", "label", "Purchases of productive assets"),
        ("source_statement_rows", "label", "Purchases of property and equipment, net"),
        ("source_statement_rows", "label", "Purchases of leased property and equipment"),
        ("source_tables", "section", "DISCLOSURE"),
        ("statement_rows", "raw_concept_id", "another-concept"),
        ("statement_facts", "value_numeric", "-54208000000"),
    ],
)
def test_occurrence_rejects_broad_or_conflicting_source(record, field, value):
    filing, prepared = _case()
    prepared[record][0][field] = value
    assert evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                           snapshot_manifest_sha256="manifest") == ()


def test_occurrence_rejects_segment_and_does_not_arbitrarily_pick_duplicates():
    filing, prepared = _case()
    fact = prepared["statement_facts"][0]
    fact["scope"]["dimensions"] = [{"member": "segment"}]
    assert evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                           snapshot_manifest_sha256="manifest") == ()
    fact["scope"]["dimensions"] = []
    prepared["statement_facts"].append({**deepcopy(fact), "fact_id": "duplicate"})
    assert evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                           snapshot_manifest_sha256="manifest") == ()


def test_builder_verifies_cutoff_and_pins_before_binding_statement(monkeypatch, tmp_path):
    filing, prepared = _case()
    directory = tmp_path / "snapshots" / CIK / ACCESSION.replace("-", "")
    directory.mkdir(parents=True)
    manifest = directory / "layer1_manifest.json"
    manifest.write_bytes(b"manifest")
    digest = hashlib.sha256(b"manifest").hexdigest()
    table_hashes = {"fact": "pinned-fact-table"}
    snapshot = SimpleNamespace(
        input=SimpleNamespace(manifest_sha256=digest, snapshot_id="snapshot"),
        records=lambda _: [filing],
        table_sha256=table_hashes,
    )
    monkeypatch.setattr(corpus_release, "_load_declared_cohort_snapshot", lambda *_: snapshot)
    reads = []
    monkeypatch.setattr(statement_source, "read_primary_document", lambda **kw: reads.append(kw) or b"html")
    monkeypatch.setattr(statement_source, "prepare_filing", lambda **_: prepared)
    kwargs = {
        "entry": {"source_run": str(tmp_path), "filing": filing}, "package_root": tmp_path,
        "snapshot_manifest_sha256": digest, "snapshot_table_sha256": table_hashes,
        "financial_as_of": "2026-10-25",
    }
    with pytest.raises(ValueError, match="after cutoff"):
        evidence.build_statement_metric_evidence(**(kwargs | {"financial_as_of": "2026-07-30"}))
    with pytest.raises(ValueError, match="manifest differs"):
        evidence.build_statement_metric_evidence(**(kwargs | {"snapshot_manifest_sha256": "bad"}))
    with pytest.raises(ValueError, match="tables differ"):
        evidence.build_statement_metric_evidence(**(kwargs | {"snapshot_table_sha256": {"fact": "bad"}}))
    assert not reads
    result, = evidence.build_statement_metric_evidence(**kwargs)
    assert result["source_snapshot_id"] == "snapshot"
    assert reads[0]["package_root"] == tmp_path


def test_revenue_primary_occurrence_attests_only_exact_same_raw_aspects():
    filing, prepared = _case()
    fact = prepared["statement_facts"][0]
    fact["concept"]["qname"] = evidence.LEGACY_REVENUE
    fact["decimals"] = "-6"
    prepared["source_tables"][0]["section"] = "IS"
    prepared["source_statement_rows"][0]["label"] = "Revenues"
    elected = {**deepcopy(fact), "fact_id": "elected-duplicate", "source_locations": []}
    prepared["statement_facts"].append(elected)
    occurrence, = evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                                   snapshot_manifest_sha256="manifest")
    assert occurrence["equivalent_source_fact_ids"] == ["elected-duplicate", "fact"]
    elected["decimals"] = "-3"
    assert evidence._statement_occurrences(prepared, filing=filing, snapshot_id="snapshot",
                                           snapshot_manifest_sha256="manifest") == ()


def test_evidence_pin_rejects_working_directory_relative_path(tmp_path, monkeypatch):
    artifact = tmp_path / "evidence.json"
    artifact.write_bytes(b"{}")
    monkeypatch.chdir(tmp_path)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    for path in (artifact.name, "", None):
        with pytest.raises(ValueError, match="nonempty absolute path"):
            evidence.read_statement_metric_evidence({"path": path, "sha256": digest}, "2026-10-25")
