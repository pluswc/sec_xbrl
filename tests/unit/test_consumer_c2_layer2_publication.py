from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sec_xbrl.analytics import AnalyticalRepository, CompanyNotFoundError
from sec_xbrl.longitudinal import (
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2PublicationValidationError,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
)


def _run(run_version: str = "consumer-c2-fixture") -> Layer2Run:
    return Layer2Run(
        run_version=run_version,
        corpus_run_id="fixture-corpus",
        inputs=(
            Layer1SnapshotInput("0000320193", "aapl-acc", "10-Q", "2026-05-01", "2026-03-28", "aapl-snapshot", "a" * 64),
            Layer1SnapshotInput("0001045810", "nvda-acc", "10-Q", "2026-05-20", "2026-04-26", "nvda-snapshot", "b" * 64),
        ),
        rules=Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"),
    )


def _fact(cik: str, identifier: str, *, view: str = "AS_FILED", as_of: str = "2026-05-01") -> dict[str, object]:
    return {
        "analytical_fact_id": identifier,
        "cik": cik,
        "raw_concept_id": "us-gaap:Revenue",
        "period_class": "QTD_3M",
        "period_key": "FY26-Q2",
        "view": view,
        "as_of_date": as_of,
        "basis_version": "reported-v1",
        "source_type": "REPORTED",
        "selected_fact_id": f"raw:{identifier}",
        "selection_rule_version": "selection-v1",
        "value_numeric": "100",
        "company_canonical_dimension_key": (("axis", "member"),),
    }


def _capability(cik: str, identifier: str) -> dict[str, object]:
    return {
        "capability_inventory_id": identifier,
        "cik": cik,
        "raw_concept_id": "us-gaap:Revenue",
        "capability_type": "CONCEPT",
        "capability_status": "AVAILABLE",
        "period_classes": ("QTD_3M",),
        "series_types": ("CURRENT",),
        "source_fact_ids": (f"raw:{identifier}",),
        "source_filing_ids": (f"filing:{identifier}",),
        "source_role_ids": ("role:revenue",),
        "source_disclosure_ids": ("disclosure:revenue",),
        "capability_inventory_version": "l2-m5-v1",
    }


def _publication(tmp_path: Path):
    return Layer2Publisher(tmp_path / "layer2").publish(
        _run(),
        {
            "analytical_fact": [
                _fact("0000320193", "aapl-as-filed"),
                _fact("0000320193", "aapl-comparable", view="CURRENT_COMPARABLE", as_of="2026-06-01"),
                _fact("0001045810", "nvda-as-filed"),
            ],
            "capability_inventory": [
                _capability("0000320193", "aapl-capability"),
                _capability("0001045810", "nvda-capability"),
            ],
        },
    )


def test_reader_and_repository_expose_only_verified_l2_rows_with_identity(tmp_path: Path) -> None:
    published = _publication(tmp_path)
    verified = Layer2PublicationReader().load(published.run_root)
    reader_rows = verified.records("analytical_fact")
    reader_rows[0]["value_numeric"] = "mutated"
    assert verified.records("analytical_fact")[0]["value_numeric"] == "100"
    repository = AnalyticalRepository.from_layer2_publications(
        (published.run_root,),
        company_catalog=(
            {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc."},
            {"cik": "0001045810", "ticker": "NVDA"},
        ),
    )

    aapl = repository.get_analytical_facts(
        "AAPL", view="AS_FILED", concept="us-gaap:Revenue", period_class="QTD_3M", period_key="FY26-Q2", as_of_date="2026-05-01"
    )
    assert [row["analytical_fact_id"] for row in aapl] == ["aapl-as-filed"]
    assert aapl[0]["layer2_publication_identity"]["layer2_run_version"] == "consumer-c2-fixture"
    assert repository.discover_capabilities("NVDA")[0]["layer2_publication_identity"]["layer2_run_fingerprint"]
    assert repository.resolve_company("0001045810") == {"cik": "0001045810", "ticker": "NVDA"}


def test_reader_rejects_tampering_manifest_mismatch_extra_and_partial_roots(tmp_path: Path) -> None:
    published = _publication(tmp_path)
    root = published.run_root
    data_path = root / "0000320193" / "analytical_fact.jsonl"
    data_path.write_text(data_path.read_text(encoding="utf-8").replace('"100"', '"101"', 1), encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="content hashes"):
        Layer2PublicationReader().load(root)

    published = _publication(tmp_path / "again")
    (published.run_root / "0000320193" / "unexpected.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="unexpected"):
        Layer2PublicationReader().load(published.run_root)

    partial = tmp_path / "layer2" / ".staging" / ".consumer.partial-x"
    partial.mkdir(parents=True)
    with pytest.raises(Layer2PublicationValidationError, match="partial"):
        Layer2PublicationReader().load(partial)


def test_reader_rejects_bad_jsonl_count_and_manifest_declaration(tmp_path: Path) -> None:
    published = _publication(tmp_path)
    root = published.run_root
    path = root / "0000320193" / "analytical_fact.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="invalid JSONL"):
        Layer2PublicationReader().load(root)

    published = _publication(tmp_path / "count")
    manifest_path = published.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_counts"]["analytical_fact"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="row counts"):
        Layer2PublicationReader().load(published.run_root)

    published = _publication(tmp_path / "manifest")
    manifest = json.loads(published.manifest_path.read_text(encoding="utf-8"))
    manifest["run_fingerprint"] = "0" * 64
    published.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="fingerprint"):
        Layer2PublicationReader().load(published.run_root)

    published = _publication(tmp_path / "validation")
    manifest = json.loads(published.manifest_path.read_text(encoding="utf-8"))
    manifest["validation"] = {}
    published.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Layer2PublicationValidationError, match="successful validation"):
        Layer2PublicationReader().load(published.run_root)


def test_repository_does_not_infer_company_metadata_and_returns_deep_copies(tmp_path: Path) -> None:
    published = _publication(tmp_path)
    repository = AnalyticalRepository.from_layer2_publications((published.run_root,))
    assert repository.resolve_company("0000320193") == {"cik": "0000320193"}
    with pytest.raises(CompanyNotFoundError):
        repository.resolve_company("AAPL")
    first = repository.get_analytical_facts("0000320193", view="AS_FILED")
    expected = deepcopy(first)
    first[0]["layer2_publication_identity"]["layer2_run_version"] = "mutated"
    assert repository.get_analytical_facts("0000320193", view="AS_FILED") == expected


def test_factory_rejects_catalog_outside_publication_and_bad_view(tmp_path: Path) -> None:
    published = _publication(tmp_path)
    with pytest.raises(Exception, match="not declared"):
        AnalyticalRepository.from_layer2_publications(
            (published.run_root,), company_catalog=({"cik": "0000000001", "ticker": "NOPE"},)
        )
    repository = AnalyticalRepository.from_layer2_publications((published.run_root,))
    with pytest.raises(Exception, match="explicit view"):
        repository.get_analytical_facts("0000320193", view="CURRENT")
