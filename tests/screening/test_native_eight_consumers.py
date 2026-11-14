"""Approved delta composition preserves original values, latest evidence and catalog scopes."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sec_xbrl import financial_native_source as native
from sec_xbrl.metrics.quarterly_screening import _observation_id
from sec_xbrl.screening import cohort_union as union
from sec_xbrl.screening import governed_delta as delta
from sec_xbrl.screening.common import read_json, write_json
from sec_xbrl.screening.runtime_projection import (
    hydrate_observation,
    observation_rows,
    publish_runtime_projection,
)
from sec_xbrl.screening.service import ScreeningService
from tests.screening.test_cohort_union import _member, _pin
from tests.screening.test_governed_delta import _approve, _parent


def _other_parent(tmp_path):
    members = []
    for index in (1, 2):
        _, source = _member(tmp_path, index)
        source.metadata = [row for row in source.metadata if row["financial_prepared"]]
        old, new = f"{index:010d}", f"{index + 2:010d}"

        def replace(value, old=old, new=new):
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return value.replace(old, new) if isinstance(value, str) else value

        for attribute in ("companies", "metadata", "observations", "quarter_observations", "metric_support",
                          "quarter_support", "quarter_period_inventory", "manifest"):
            setattr(source, attribute, replace(getattr(source, attribute)))
        if index == 2:
            source.observations = []
            source.metric_support = [{**row, "execution_supported": False, "available_periods": 0,
                                      "reasons": ["NO_ANNUAL_BASELINE"], "reason": "NO_ANNUAL_BASELINE"}
                                     for row in source.metric_support]
        source.quarterly.manifest = replace(source.quarterly.manifest)
        write_json(source.root / "screening_dataset_manifest.json", source.manifest)
        source._manifest_sha256 = _pin(source.root / "screening_dataset_manifest.json")["sha256"]
        projection = publish_runtime_projection(source.root, tmp_path / f"projection-{index}",
                                                tmp_path / "other-blobs", reader=source)
        members.append({"dataset_manifest": _pin(source.root / "screening_dataset_manifest.json"), "projection": _pin(projection)})
    config = tmp_path / "other-union.json"
    write_json(config, {"schema_version": union.CONFIG_VERSION, "dataset_id": "other-parent", "members": members,
                        "expose_auxiliary_owners": True})
    root = union.publish_cohort_union(config, tmp_path / "other-parent")
    pin = _pin(root / union.MANIFEST)
    return root, pin, union.ScreeningCohortUnionReader(root, pin)


def _adopt(tmp_path, parent_pin, parent, name, latest=None):
    config = tmp_path / f"{name}.json"
    write_json(config, {"schema_version": delta.CONFIG_VERSION, "dataset_id": name, "parent": parent_pin,
                        **({"latest_quarters": [latest]} if latest else {})})
    root = delta.publish_governed_delta(config, tmp_path / name, parent=parent)
    # Each approval must be distinct; the historical helper uses one sibling name.
    declaration = _approve(root)
    approval = tmp_path / f"{name}-approval.json"
    write_json(approval, read_json(Path(declaration["approval"]["path"])))
    declaration["approval"] = _pin(approval)
    return root, declaration, delta.ScreeningGovernedDeltaReader(root, declaration, parent=parent)


def test_typed_union_public_publish_latest_passthrough_and_topological_service(tmp_path, monkeypatch):
    old = tmp_path / "old"; old.mkdir()
    parent_root, parent_pin, parent = _parent(old, latest=True)
    owner_config = read_json(parent_root / union.MANIFEST)["config"]
    owner_config["expose_auxiliary_owners"] = True
    owner_path = old / "parent-owners.json"; write_json(owner_path, owner_config)
    parent_root = union.publish_cohort_union(owner_path, old / "parent-with-owners")
    parent_pin = _pin(parent_root / union.MANIFEST)
    parent = union.ScreeningCohortUnionReader(parent_root, parent_pin)
    cik = "0000000001"
    owner = parent._owners[cik]
    qpath = Path(owner.manifest["config"]["quarterly_metric_root"]) / "quarterly_screening_metric_manifest.json"
    company = read_json(qpath)["config"]["companies"][0]
    request = {"cik": cik, "ticker": "T1", "owner_manifest": _pin(owner.root / "screening_dataset_manifest.json"),
               "quarterly_manifest": _pin(qpath), "analysis_manifest": _pin(Path(company["analysis_root"]) / "analysis_manifest.json")}
    anchor = {**parent.latest_source_period_guards[cik], "bucket_status": "PERIOD_AVAILABLE", "filed_date": "2026-10-23"}
    records = [{**deepcopy(hydrate_observation(parent, row, quarterly=True)), "calendar_quarter": 4,
                "fiscal_year": 2027, "fiscal_quarter": "Q1", "period_end": anchor["period_end"],
                "period_start": anchor["period_start"] if row["period_class"] == "QTD_3M" else row.get("period_start")}
               for row in observation_rows(parent, quarterly=True, cik=cik, year=2026, quarter=3)]
    for row in records:
        row["observation_id"] = _observation_id(row)
    monkeypatch.setattr(delta, "prepare_latest_quarter", lambda **_: (records, [anchor], []))
    old_root, old_decl, old_reader = _adopt(old, parent_pin, parent, "approved92", request)
    fresh = tmp_path / "fresh"; fresh.mkdir()
    new_parent_root, new_parent_pin, new_parent = _other_parent(fresh)
    new_root, new_decl, new_reader = _adopt(fresh, new_parent_pin, new_parent, "approved8")
    assert observation_rows(new_reader, cik="0000000004") == []
    assert next(row for row in new_reader.metric_support if row["cik"] == "0000000004"
                and row["metric_id"] == "revenue_yoy")["reasons"] == ["NO_ANNUAL_BASELINE"]
    config = tmp_path / "100-config.json"
    body = {"schema_version": union.CONFIG_VERSION_V2, "dataset_id": "composed100", "expose_auxiliary_owners": True,
            "members": [{"kind": "GOVERNED_DELTA", "declaration": item} for item in (old_decl, new_decl)]}
    write_json(config, body)
    root = union.publish_cohort_union(config, tmp_path / "100")
    pin = _pin(root / union.MANIFEST)
    reader = union.ScreeningCohortUnionReader(root, pin, shared_readers=(old_reader, new_reader))
    assert reader._members[0] is old_reader
    assert len(reader.companies) == 4
    assert observation_rows(reader, cik=cik, quarterly=True, latest=True) == observation_rows(old_reader, cik=cik, quarterly=True, latest=True)
    assert observation_rows(reader, cik=cik, quarterly=True) == observation_rows(old_reader, cik=cik, quarterly=True)
    assert reader.latest_quarter_periods[cik] == anchor
    assert reader.manifest["auxiliary_owners"][cik] == old_reader.manifest["auxiliary_owners"][cik]
    service = ScreeningService({"composed100": root, "approved8": new_root, "approved92": old_root,
                                "parent": parent_root, "other-parent": new_parent_root}, tmp_path / "private.sqlite",
        cohort_unions={"composed100": pin, "parent": parent_pin, "other-parent": new_parent_pin},
        governed_deltas={"approved92": old_decl, "approved8": new_decl})
    assert service.datasets["composed100"]._members[0] is service.datasets["approved92"]
    assert service.quarter_periods("composed100")["latest_company_periods"]["records"] == [anchor]
    assert service.quarter_series("composed100", cik=cik, metric_id="quarter_revenue", latest=True)["observations"][-1]["calendar_quarter"] == 4
    with pytest.raises(ValueError, match="owned"):
        union._compose(body, [old_reader, old_reader])
    changed = deepcopy(new_reader.metric_definitions)
    new_reader.metric_definitions[0]["label"] = "different definition"
    with pytest.raises(ValueError, match="definition"):
        union._compose(body, [old_reader, new_reader])
    new_reader.metric_definitions = changed
    broken = deepcopy(body); broken["members"][1]["declaration"]["manifest"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        union._open_members(broken)


def test_reader_source_transition_is_exact_per_artifact_and_does_not_grant_producer(tmp_path, monkeypatch):
    _parent_root, pin, parent = _parent(tmp_path)
    root, declaration, _ = _adopt(tmp_path, pin, parent, "approved92")
    origin_sources = delta._source_hashes()
    current = {**origin_sources, "screening/cohort_union.py": "9" * 64}
    monkeypatch.setattr(delta, "_source_hashes", lambda source_root=None: current if source_root is None else origin_sources)
    with pytest.raises(ValueError, match="current source"):
        delta.ScreeningGovernedDeltaReader(root, declaration, parent=parent)
    baseline = {key: value for key, value in origin_sources.items() if key.endswith(".py")}
    monkeypatch.setattr(native, "_CONSUMER_BASELINE_INVENTORY", native.digest_value(baseline))
    # Keep the synthetic source receipt internally consistent without changing real pins.
    monkeypatch.setattr(native, "_PARTIAL_CONSUMER_FILES",
                        {name: baseline[name] for name in native._PARTIAL_CONSUMER_FILES})
    receipt = tmp_path / "reader-only.json"
    body = {"schema_version": "governed-delta-reader-source-transition-v1", "status": "ROOT_APPROVED_READER_ONLY_SOURCE_TRANSITION",
            "manifest": declaration["manifest"], "approval": declaration["approval"], "origin_source_root": str(tmp_path),
            "origin_implementation_sources": origin_sources, "current_implementation_sources": current,
            "consumer_baseline_files": baseline}
    write_json(receipt, body)
    qualified = {**declaration, "reader_source_transition": _pin(receipt)}
    reader = delta.ScreeningGovernedDeltaReader(root, qualified, parent=parent)
    assert reader.parent is parent
    assert native.native_controls() == ({}, ())
    with pytest.raises(ValueError, match="current source"):
        delta.ScreeningGovernedDeltaReader(root, declaration, parent=parent)
    for field in ("manifest", "approval", "origin_implementation_sources", "current_implementation_sources"):
        invalid = deepcopy(body)
        invalid[field] = {}
        write_json(receipt, invalid)
        with pytest.raises(ValueError, match="transition"):
            delta.ScreeningGovernedDeltaReader(root, {**declaration, "reader_source_transition": _pin(receipt)}, parent=parent)
