from __future__ import annotations

import hashlib
import json
import sys

import pytest

from examples.screening import prepare_q4_eps_reconstruction as cli
from sec_xbrl.metrics import cal_eps_source
from sec_xbrl.metrics.market_inputs import encoded, pinned_json


def _pin(path, value):
    data = encoded(value)
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _coordinate(number):
    return {"cik": f"{number:010}", "accession": f"{number:010}-26-000001"}


def _metadata(tmp_path, numbers=(42, 73)):
    filings = [_coordinate(n) for n in numbers]
    proposal = {"schema_version": "common-q4-eps-proposal-v1", "source_filings": filings,
                "snapshots": [{"snapshot_id": f"l1:{f['cik']}:{f['accession'].replace('-', '')}:manifest"}
                              for f in filings]}
    documents = [{**f, "original_package": {"path": f"/immutable/{f['accession']}.zip", "sha256": "a" * 64}}
                 for f in filings]
    return proposal, {"documents": documents}


def _fake_prepare(calls):
    def prepare(snapshot, package, *, taxonomy_cache):
        _, cik, nodash, _ = snapshot["snapshot_id"].split(":")
        accession = nodash[:10] + "-" + nodash[10:12] + "-" + nodash[12:]
        calls.append((cik, accession))
        return {"schema_version": "cal-eps-filing-v1", "snapshot": snapshot, "package": package,
                "filing": {"cik": cik, "accession": accession}}
    return prepare


def test_cli_prepares_arbitrary_registered_companies_with_order_independent_pins(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cal_eps_source, "prepare_cal_eps_filing", _fake_prepare(calls))
    outputs = []
    for suffix, numbers in (("first", (73, 42)), ("second", (42, 73))):
        proposal, catalog = _metadata(tmp_path, numbers)
        # Identical package metadata from two source documents is one accession.
        catalog["documents"].append(dict(catalog["documents"][0]))
        proposal_pin = _pin(tmp_path / (suffix + "-proposal.json"), proposal)
        catalog_pin = _pin(tmp_path / (suffix + "-sources.json"), catalog)
        destination = tmp_path / (suffix + "-catalog.json")
        monkeypatch.setattr(sys, "argv", ["prepare-q4", "prepare-cal-sources", "--input", proposal_pin["path"],
            "--sha256", proposal_pin["sha256"], "--source-catalog", catalog_pin["path"],
            "--source-catalog-sha256", catalog_pin["sha256"], "--projection-root", str(tmp_path / suffix),
            "--taxonomy-cache", str(tmp_path / "offline-taxonomy"), "--output", str(destination)])
        cli.main()
        result = json.loads(destination.read_text())
        assert result["schema_version"] == "cal-eps-filing-catalog-v1"
        assert result["holds"] == []
        assert pinned_json(proposal_pin) == proposal
        assert pinned_json(catalog_pin) == catalog
        outputs.append([(r["cik"], r["accession"], r["projection"]["sha256"]) for r in result["filings"]])
        for entry in result["filings"]:
            assert pinned_json(entry["projection"])["filing"] == {k: entry[k] for k in ("cik", "accession")}
    assert outputs[0] == outputs[1]
    assert calls == [("0000000042", "0000000042-26-000001"), ("0000000073", "0000000073-26-000001")] * 2


@pytest.mark.parametrize(("problem", "reason"), [
    ("missing", "REGISTERED_PACKAGE_PIN_MISSING"),
    ("ambiguous", "REGISTERED_PACKAGE_PIN_AMBIGUOUS"),
    ("snapshot", "REGISTERED_SNAPSHOT_MISSING_OR_AMBIGUOUS"),
    ("filing", "REGISTERED_FILING_AMBIGUOUS"),
    ("unregistered", "SOURCE_ACCESSION_NOT_REGISTERED"),
])
def test_batch_source_contract_reports_holds_without_parsing_unresolved_coordinates(tmp_path, monkeypatch, problem, reason):
    proposal, catalog = _metadata(tmp_path, (42,))
    if problem == "missing":
        catalog["documents"][0]["original_package"].pop("sha256")
    elif problem == "ambiguous":
        catalog["documents"].append({**catalog["documents"][0],
                                     "original_package": {"path": "/other.zip", "sha256": "b" * 64}})
    elif problem == "snapshot":
        proposal["snapshots"] = []
    elif problem == "filing":
        proposal["source_filings"].append(dict(proposal["source_filings"][0]))
    else:
        proposal["source_filings"] = []
    calls = []
    monkeypatch.setattr(cal_eps_source, "prepare_cal_eps_filing", _fake_prepare(calls))
    result = cli._prepare_cal_sources(_pin(tmp_path / "proposal.json", proposal),
        _pin(tmp_path / "sources.json", catalog), projection_root=tmp_path / "projections",
        taxonomy_cache=tmp_path / "cache")
    assert calls == []
    assert result["filings"] == []
    assert result["holds"] == [{**_coordinate(42), "reason": reason}]


def test_source_batch_refuses_mutated_pins_and_existing_outputs(tmp_path, monkeypatch):
    proposal, catalog = _metadata(tmp_path, (42,))
    proposal_pin = _pin(tmp_path / "proposal.json", proposal)
    catalog_pin = _pin(tmp_path / "sources.json", catalog)
    (tmp_path / "sources.json").write_text('{}')
    with pytest.raises(ValueError, match="hash mismatch"):
        cli._prepare_cal_sources(proposal_pin, catalog_pin, projection_root=tmp_path / "new",
                                 taxonomy_cache=tmp_path / "cache")
    assert not (tmp_path / "new").exists()
    catalog_pin = _pin(tmp_path / "sources.json", catalog)
    projection_root = tmp_path / "existing"
    projection_root.mkdir()
    sentinel = projection_root / "original.json"
    sentinel.write_text("immutable")
    with pytest.raises(ValueError, match="create-only"):
        cli._prepare_cal_sources(proposal_pin, catalog_pin, projection_root=projection_root,
                                 taxonomy_cache=tmp_path / "cache")
    assert sentinel.read_text() == "immutable"


def test_verify_source_batch_replays_each_pin_and_rejects_duplicate_coordinates(tmp_path, monkeypatch):
    projection_pin = _pin(tmp_path / "filing.json", {"filing": _coordinate(42)})
    entry = {**_coordinate(42), "projection": projection_pin}
    catalog = {"schema_version": "cal-eps-filing-catalog-v1", "filings": [entry], "holds": [{"reason": "OTHER_HOLD"}]}
    seen = []

    def verify(pin, *, taxonomy_cache):
        seen.append(pin)
        return pinned_json(pin)

    monkeypatch.setattr(cal_eps_source, "verify_cal_eps_filing", verify)
    result = cli._verify_cal_sources(_pin(tmp_path / "catalog.json", catalog), taxonomy_cache=tmp_path / "cache")
    assert seen == [projection_pin]
    assert result == {"verified": True, "prepared_filings_verified": 1, "preparation_holds": 1}
    catalog["filings"].append(entry)
    with pytest.raises(ValueError, match="repeats an accession"):
        cli._verify_cal_sources(_pin(tmp_path / "duplicate.json", catalog), taxonomy_cache=tmp_path / "cache")
