"""Explicit same-cutoff composition retains source observations and metadata owners."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sec_xbrl.screening.cohort_union import (
    CONFIG_VERSION,
    MANIFEST,
    ScreeningCohortUnionReader,
    publish_cohort_union,
)
from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.runtime_projection import publish_runtime_projection
from sec_xbrl.screening.service import ScreeningService
from tests.screening.test_runtime_projection import _condition, _stand_in_source
from tests.screening.test_screening_explorer import _reader as annual_fixture


def _pin(path):
    return {"path": str(path), "sha256": sha256_file(path)}


def _member(tmp_path, index, *, additive=False, definition_conflict=False, cutoff=None):
    parent = tmp_path / f"fixture-{index}"
    parent.mkdir()
    source, reader = _stand_in_source(parent, f"source-{index}")
    cik = f"{index:010d}"
    reader.companies = [row for row in reader.companies if row["cik"] == cik]
    reader.quarterly.manifest = copy.deepcopy(reader.quarterly.manifest)
    reader.quarterly.manifest["universe"]["ciks"] = [cik]
    reader.quarter_period_inventory = [row for row in reader.quarter_period_inventory if row["cik"] == cik]
    reader.quarter_observations = [row for row in reader.quarter_observations if row["cik"] == cik]
    reader.quarter_support = [row for row in reader.quarter_support if row["cik"] == cik]
    annual = annual_fixture()
    reader.metric_definitions = annual.metric_definitions
    reader.observations = [{**row, "view": "LATEST_REPORTED"} for row in annual.observations if row["cik"] == cik]
    reader.metric_support = [{"cik": cik, "metric_id": row["metric_id"], "definition_version": row["definition_version"],
                              "execution_supported": True, "available_periods": 4} for row in reader.metric_definitions]
    reader.metadata = [
        {"cik": f"{company:010d}", "name": f"observed-by-{index}", "sic_code": f"{index:04d}",
         "tickers": [f"T{company}"], "financial_prepared": company == index, "observed_at": f"2026-10-0{index}"}
        for company in (1, 2, 3)
    ]
    if additive:
        definition = copy.deepcopy(reader.quarter_definitions[0])
        definition["metric_id"] = "quarter_additive"
        reader.quarter_definitions = [*reader.quarter_definitions, definition]
        rows = []
        for row in reader.quarter_observations:
            if row["metric_id"] == definition["metric_id"]:
                continue
            if row["metric_id"] == reader.quarter_definitions[0]["metric_id"]:
                rows.append({**row, "metric_id": "quarter_additive"})
        reader.quarter_observations += rows
        reader.quarter_support = [*reader.quarter_support, {"cik": cik, "metric_id": "quarter_additive",
                                  "definition_version": definition["definition_version"], "available_bucket_count": 1}]
    if definition_conflict:
        reader.metric_definitions = copy.deepcopy(reader.metric_definitions)
        reader.metric_definitions[0]["label"] = "conflicting meaning"
    if cutoff:
        reader.manifest["financial_as_of"] = cutoff
    path = source / "screening_dataset_manifest.json"
    write_json(path, reader.manifest)
    reader._manifest_sha256 = sha256_file(path)
    projection = publish_runtime_projection(source, parent / "projection", tmp_path / "blobs", reader=reader)
    return {"dataset_manifest": _pin(path), "projection": _pin(projection)}, reader


def _publish(tmp_path, members):
    config = tmp_path / "union-config.json"
    write_json(config, {"schema_version": CONFIG_VERSION, "dataset_id": "union", "members": members})
    root = publish_cohort_union(config, tmp_path / "union")
    assert publish_cohort_union(config, root) == root
    return root, ScreeningCohortUnionReader(root, _pin(root / MANIFEST))


def test_union_routes_exact_rows_and_honors_prepared_metadata_owner(tmp_path):
    first, old = _member(tmp_path, 1, additive=True)
    second, new = _member(tmp_path, 2)
    root, reader = _publish(tmp_path, [first, second])
    assert [row["cik"] for row in reader.companies] == ["0000000001", "0000000002"]
    assert reader.metadata[0] == old.metadata[0]
    assert reader.metadata[1] == new.metadata[1]
    assert reader.metadata[2] == {"cik": "0000000003", "financial_prepared": False,
                                  "metadata_conflict": True, "reason": "COHORT_CANDIDATE_METADATA_CONFLICT"}
    assert all(member._evidence.cache_info().misses == 0 for member in reader._members)
    for original in (old, new):
        cik = original.companies[0]["cik"]
        core = reader.rows(cik=cik, quarterly=True)
        assert [reader.hydrate(row, quarterly=True) for row in core] == original.quarter_observations
        assert reader.company(cik) == original.company(cik)
    assert reader.rows(cik="0000000002", metric_id="quarter_additive", quarterly=True) == []
    assert reader.verify_all()["quarter_observation_count"] == len(old.quarter_observations) + len(new.quarter_observations)

    service = ScreeningService({"union": root}, tmp_path / "journal.sqlite", cohort_unions={"union": _pin(root / MANIFEST)})
    assert service.company_explorer("union")["rows"]
    observation = next(row for row in old.quarter_observations
                       if row["metric_id"] == "quarter_additive" and row["availability_status"] == "AVAILABLE")
    definition = next(row for row in reader.quarter_definitions if row["metric_id"] == "quarter_additive")
    policy = {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": observation["calendar_year"],
              "calendar_quarter": observation["calendar_quarter"]}
    preview = service.preview(_condition(policy, definition), "union")
    assert preview["counts"]["target"] == 2
    absent = next(row for row in preview["rows"] if row["cik"] == "0000000002")
    assert absent["aggregate"] == "UNDETERMINED" and absent["predicates"][0]["observation"] is None
    present = next(row for row in preview["rows"] if row["cik"] == "0000000001")
    assert present["predicates"][0]["observation"]["source_lineage"] == observation["source_lineage"]
    saved = service.save_result(name="union", content=preview["content"], dataset_id="union", preview_hash=preview["preview_hash"])
    reopened = ScreeningService({"union": root}, service.store.path, cohort_unions={"union": _pin(root / MANIFEST)})
    assert reopened.run(saved["run_id"]) == saved


def test_union_rejects_overlap_cutoff_and_shared_definition_conflicts(tmp_path):
    first, _ = _member(tmp_path, 1)
    second, _ = _member(tmp_path, 2, definition_conflict=True)
    with pytest.raises(ValueError, match="owned by more than one"):
        _publish(tmp_path, [first, first])
    with pytest.raises(ValueError, match="metric definition differs"):
        _publish(tmp_path, [first, second])
    other = tmp_path / "other"
    other.mkdir()
    third, _ = _member(other, 2, cutoff="2026-10-11")
    with pytest.raises(ValueError, match="cutoff"):
        _publish(tmp_path, [first, third])


def test_union_pin_and_source_integrity_have_no_legacy_fallback(tmp_path):
    first, _ = _member(tmp_path, 1)
    second, _ = _member(tmp_path, 2)
    root, _ = _publish(tmp_path, [first, second])
    pinned = _pin(root / MANIFEST)
    source = Path(second["dataset_manifest"]["path"])
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ValueError, match="input differs from pinned digest"):
        ScreeningCohortUnionReader(root, pinned)
    with pytest.raises(ValueError, match="outside the catalog"):
        ScreeningService({"union": root}, tmp_path / "unused.sqlite", cohort_unions={"other": pinned})


def test_auxiliary_owners_are_opt_in_exact_prepared_members_and_api_pin(tmp_path):
    first, old = _member(tmp_path, 1)
    second, new = _member(tmp_path, 2)
    config = tmp_path / "owner-config.json"
    write_json(config, {"schema_version": CONFIG_VERSION, "dataset_id": "owner-union", "members": [first, second],
                        "expose_auxiliary_owners": True})
    root = publish_cohort_union(config, tmp_path / "owner-union")
    reader = ScreeningCohortUnionReader(root, _pin(root / MANIFEST))
    owners = reader.manifest["auxiliary_owners"]
    assert set(owners) == {"0000000001", "0000000002"}
    for member, original in [(first, old), (second, new)]:
        cik = original.companies[0]["cik"]
        assert owners[cik] == {"dataset_id": original.manifest["dataset_id"],
            "dataset_publication_id": original.publication_id, "financial_as_of": original.manifest["financial_as_of"],
            "dataset_manifest_sha256": member["dataset_manifest"]["sha256"]}
    service = ScreeningService({"owner-union": root}, tmp_path / "private.sqlite",
        cohort_unions={"owner-union": _pin(root / MANIFEST)})
    assert service.status()["datasets"][0]["auxiliary_manifest_sha256"] == sha256_file(root / MANIFEST)
    changed = copy.deepcopy(reader.manifest)
    changed["auxiliary_owners"]["0000000001"] = owners["0000000002"]
    write_json(root / MANIFEST, changed)
    with pytest.raises(ValueError, match="exact parents"):
        ScreeningCohortUnionReader(root, _pin(root / MANIFEST))


def test_union_company_description_uses_only_exact_owner_parent(tmp_path):
    from types import SimpleNamespace

    from sec_xbrl.screening.runtime_projection import ScreeningRuntimeProjection
    first, _ = _member(tmp_path, 1)
    second, _ = _member(tmp_path, 2)
    config = tmp_path / "description-owner-config.json"
    write_json(config, {"schema_version": CONFIG_VERSION, "dataset_id": "described-union", "members": [first, second],
                        "expose_auxiliary_owners": True})
    root = publish_cohort_union(config, tmp_path / "described-union")
    source_root = Path(first["dataset_manifest"]["path"]).parent
    old = ScreeningRuntimeProjection(source_root, first["projection"])
    seen = []
    def company(cik):
        seen.append(cik)
        return {"status": "AVAILABLE", "text": "Original owner text"}
    descriptions = SimpleNamespace(dataset_id=old.manifest["dataset_id"], dataset=old,
                                   publication_id="description-publication", company=company)
    service = ScreeningService({"described-union": root, old.manifest["dataset_id"]: source_root}, tmp_path / "descriptions-private.sqlite",
        runtime_projections={old.manifest["dataset_id"]: first["projection"]},
        cohort_unions={"described-union": _pin(root / MANIFEST)}, company_descriptions=descriptions)
    described = service.company_profile("described-union", cik="0000000001", fiscal_year=2025)
    assert described["company_description"]["text"] == "Original owner text"
    assert described["company_description"]["source_scope"]["dataset_manifest_sha256"] == first["dataset_manifest"]["sha256"]
    service.company_profile("described-union", cik="0000000002", fiscal_year=2025)
    assert seen == ["0000000001"]
