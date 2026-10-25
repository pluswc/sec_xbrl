import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.company_metadata import (
    CandidateInventoryInput,
    CompanyMetadataError,
    CompanyMetadataReader,
    SnapshotInput,
    UniverseFilter,
    build_company_metadata,
    publish_company_metadata,
)

OBSERVED = datetime(2026, 10, 8, 1, 2, 3, tzinfo=UTC)


def _root(
    cik: str,
    *,
    name: str = "Example Corp",
    sic: object = "3571",
    tickers: list[str] | None = None,
    exchanges: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "cik": cik,
        "name": name,
        "sic": sic,
        "sicDescription": "Electronic Computers",
        "tickers": tickers if tickers is not None else ["EXM.A", "EXM.B"],
        "exchanges": exchanges if exchanges is not None else ["Nasdaq", "NYSE"],
        "formerNames": [{"name": "Old Example", "from": "2010-01-01", "to": "2015-01-01"}],
        "filings": {
            "recent": {"form": ["8-K", "10-K", "10-Q", "10-Q/A", "S-1"]}
        },
    }
    if sic is None:
        payload.pop("sic")
        payload.pop("sicDescription")
    return payload


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def test_build_preserves_one_issuer_multiple_share_classes_and_source_trace(tmp_path: Path) -> None:
    snapshot = _write(tmp_path / "0000000123" / "root.json", _root("123"))

    result = build_company_metadata(
        [SnapshotInput(snapshot, OBSERVED, source_url="https://data.sec.gov/submissions/CIK0000000123.json")]
    )

    assert len(result.companies) == 1
    company = result.companies[0]
    assert company["company_id"] == "sec-cik:0000000123"
    assert company["supported_forms"] == ["10-K", "10-Q", "10-Q/A"]
    assert json.loads(company["former_names_json"])[0]["name"] == "Old Example"
    assert company["source_path"] == str(snapshot.resolve())
    assert company["source_sha256"] == result.selected_inputs[0]["source_sha256"]
    ticker_rows = [row for row in result.company_identifiers if row["identifier_type"] == "TICKER"]
    assert [(row["identifier_value"], row["exchange"]) for row in ticker_rows] == [
        ("EXM.A", "Nasdaq"),
        ("EXM.B", "NYSE"),
    ]
    assert len(result.industry_classifications) == 1
    assert result.industry_classifications[0]["sic_code"] == "3571"


def test_missing_sic_is_explicit_and_malformed_or_unsafe_identity_fails(tmp_path: Path) -> None:
    missing = _write(tmp_path / "missing.json", _root("123", sic=None))
    built = build_company_metadata([missing], observed_at=OBSERVED)
    industry = built.industry_classifications[0]
    assert industry["sic_code"] is None
    assert industry["classification_status"] == "NOT_CLASSIFIED"

    malformed = _write(tmp_path / "malformed.json", _root("124", sic="35A1"))
    with pytest.raises(CompanyMetadataError, match="invalid SIC"):
        build_company_metadata([malformed], observed_at=OBSERVED)

    duplicate = _write(
        tmp_path / "duplicate.json",
        _root("125", tickers=["DUP", "dup"], exchanges=["NYSE", "nyse"]),
    )
    with pytest.raises(CompanyMetadataError, match="duplicate ticker/exchange"):
        build_company_metadata([duplicate], observed_at=OBSERVED)

    mismatched = _write(tmp_path / "0000000999" / "root.json", _root("123"))
    with pytest.raises(CompanyMetadataError, match="CIK mismatch"):
        build_company_metadata([mismatched], observed_at=OBSERVED)


def test_snapshot_cutoff_and_competing_latest_observations_are_explicit(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _root("123", name="Old Name"))
    new = _write(tmp_path / "new.json", _root("123", name="New Name"))
    later = OBSERVED + timedelta(days=1)

    selected_old = build_company_metadata(
        [SnapshotInput(old, OBSERVED), SnapshotInput(new, later)], cutoff=OBSERVED
    )
    assert selected_old.companies[0]["name"] == "Old Name"
    assert selected_old.companies[0]["observed_at"] == "2026-10-08T01:02:03Z"

    selected_new = build_company_metadata(
        [SnapshotInput(old, OBSERVED), SnapshotInput(new, later)]
    )
    assert selected_new.companies[0]["name"] == "New Name"

    with pytest.raises(CompanyMetadataError, match="ambiguous competing"):
        build_company_metadata([SnapshotInput(old, OBSERVED), SnapshotInput(new, OBSERVED)])
    with pytest.raises(CompanyMetadataError, match="timezone-aware"):
        build_company_metadata([old], observed_at=datetime.fromisoformat("2026-01-01"))


def test_snapshot_selection_compares_fractional_observation_times_as_datetimes(
    tmp_path: Path,
) -> None:
    older = _write(tmp_path / "older.json", _root("123", name="Older"))
    newer = _write(tmp_path / "newer.json", _root("123", name="Newer"))
    fractional = OBSERVED + timedelta(microseconds=1)

    selected = build_company_metadata(
        [SnapshotInput(older, OBSERVED), SnapshotInput(newer, fractional)]
    )
    assert selected.companies[0]["name"] == "Newer"
    assert selected.companies[0]["observed_at"] == "2026-10-08T01:02:03.000001Z"

    cutoff_selected = build_company_metadata(
        [SnapshotInput(older, OBSERVED), SnapshotInput(newer, fractional)],
        cutoff=OBSERVED,
    )
    assert cutoff_selected.companies[0]["name"] == "Older"


def test_identical_snapshot_with_conflicting_provenance_fails_in_any_input_order(
    tmp_path: Path,
) -> None:
    snapshot = _write(tmp_path / "root.json", _root("123"))
    one = SnapshotInput(snapshot, OBSERVED, source="source-a", source_url="https://a.example")
    two = SnapshotInput(snapshot, OBSERVED, source="source-b", source_url="https://b.example")

    for inputs in ([one, two], [two, one]):
        with pytest.raises(CompanyMetadataError, match="conflicting provenance"):
            build_company_metadata(inputs)


def test_publication_is_immutable_reusable_and_defensively_read(tmp_path: Path) -> None:
    snapshot = _write(tmp_path / "root.json", _root("123"))
    built = build_company_metadata([snapshot], observed_at=OBSERVED)
    destination = tmp_path / "publication"

    published = publish_company_metadata(built, destination)
    assert published.reused is False
    assert publish_company_metadata(built, destination).reused is True
    reader = CompanyMetadataReader(destination)
    assert reader.publication_id == built.publication_id
    assert pl.read_parquet(destination / "companies.parquet").height == 1

    changed_snapshot = _write(tmp_path / "changed.json", _root("123", name="Changed"))
    changed = build_company_metadata([changed_snapshot], observed_at=OBSERVED)
    with pytest.raises(CompanyMetadataError, match="collision"):
        publish_company_metadata(changed, destination)

    manifest_path = destination / "company_metadata_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication_id"] = "company-metadata-000000000000000000000000"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CompanyMetadataError, match="identity mismatch"):
        CompanyMetadataReader(destination)


def test_reader_rejects_parquet_dtype_change_even_with_updated_file_digest(tmp_path: Path) -> None:
    snapshot = _write(tmp_path / "root.json", _root("123"))
    built = build_company_metadata([snapshot], observed_at=OBSERVED)
    destination = publish_company_metadata(built, tmp_path / "publication").root
    identifiers_path = destination / "company_identifiers.parquet"
    identifiers = pl.read_parquet(identifiers_path).with_columns(pl.col("ordinal").cast(pl.UInt32))
    identifiers.write_parquet(identifiers_path)
    manifest_path = destination / "company_metadata_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][identifiers_path.name]["sha256"] = hashlib.sha256(
        identifiers_path.read_bytes()
    ).hexdigest()
    manifest["files"][identifiers_path.name]["size"] = identifiers_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CompanyMetadataError, match="schema mismatch"):
        CompanyMetadataReader(destination)


def test_query_retains_exclusions_unknown_ciks_and_finds_coarse_peers(tmp_path: Path) -> None:
    one = _write(tmp_path / "one.json", _root("123", name="One", tickers=["ONE"], exchanges=["Nasdaq"]))
    two = _write(tmp_path / "two.json", _root("124", name="Two", tickers=["TWO"], exchanges=["NYSE"]))
    three = _write(tmp_path / "three.json", _root("125", name="Three", sic=None, tickers=[], exchanges=[]))
    built = build_company_metadata([one, two, three], observed_at=OBSERVED)
    reader = CompanyMetadataReader(publish_company_metadata(built, tmp_path / "pub").root)

    rows = reader.list_companies(
        UniverseFilter(
            exchanges=frozenset({"Nasdaq"}),
            forms=frozenset({"10-K", "10-Q"}),
            sic_codes=frozenset({"3571"}),
            ciks=frozenset({"123", "125", "999"}),
        )
    )
    by_cik = {row.cik: row for row in rows}
    assert by_cik["0000000123"].eligible is True
    assert "CIK_EXCLUDED" in by_cik["0000000124"].exclusion_reasons
    assert "INDUSTRY_NOT_CLASSIFIED" in by_cik["0000000125"].exclusion_reasons
    assert by_cik["0000000999"].exclusion_reasons == ("METADATA_UNAVAILABLE",)

    peers = reader.peer_candidates("123")
    assert [(row.cik, row.name) for row in peers] == [("0000000124", "Two")]
    assert "not accounting equivalence" in peers[0].limitation
    assert reader.peer_candidates("125") == ()


def test_cached_candidate_inventory_broadens_candidates_without_claiming_sic_coverage(
    tmp_path: Path,
) -> None:
    root = _write(tmp_path / "root.json", _root("123", tickers=["ONE"], exchanges=["Nasdaq"]))
    inventory = _write(
        tmp_path / "inventory.json",
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [123, "Example Corp", "ONE", "Nasdaq"],
                [777, "Candidate Ltd", "CAND", None],
                [777, "Candidate Ltd", "CAND.OTC", "OTC"],
                [778, "Unknown Exchange Ltd", "UNK", None],
            ],
        },
    )
    result = build_company_metadata(
        [root],
        observed_at=OBSERVED,
        candidate_inventory=CandidateInventoryInput(inventory, OBSERVED),
    )
    reader = CompanyMetadataReader(publish_company_metadata(result, tmp_path / "pub").root)
    rows = {row.cik: row for row in reader.list_companies()}

    assert rows["0000000123"].metadata_status == "ROOT_OBSERVED"
    candidate = rows["0000000777"]
    assert candidate.metadata_status == "CANDIDATE_ONLY"
    assert candidate.tickers == ("CAND", "CAND.OTC")
    assert candidate.exchanges == ("OTC",)
    assert candidate.sic_code is None
    assert candidate.eligible is False
    assert candidate.exclusion_reasons == ("ROOT_METADATA_UNAVAILABLE",)
    filtered_candidate = {
        row.cik: row
        for row in reader.list_companies(UniverseFilter(exchanges=frozenset({"NYSE"})))
    }["0000000778"]
    assert "EXCHANGE_UNAVAILABLE" in filtered_candidate.exclusion_reasons
    industry = {
        row["cik"]: row
        for row in pl.read_parquet(tmp_path / "pub" / "industry_classifications.parquet").to_dicts()
    }
    assert industry["0000000777"]["classification_status"] == "NOT_CLASSIFIED"

    duplicate_inventory = _write(
        tmp_path / "duplicate-inventory.json",
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [888, "Duplicate Ltd", "DUP", None],
                [888, "Duplicate Ltd", "dup", None],
            ],
        },
    )
    with pytest.raises(CompanyMetadataError, match="duplicate candidate"):
        build_company_metadata(
            [root],
            observed_at=OBSERVED,
            candidate_inventory=CandidateInventoryInput(duplicate_inventory, OBSERVED),
        )


def test_publication_rejects_same_ticker_exchange_owned_by_two_ciks(tmp_path: Path) -> None:
    one = _write(tmp_path / "one.json", _root("123", tickers=["DUP"], exchanges=["NYSE"]))
    two = _write(tmp_path / "two.json", _root("124", tickers=["dup"], exchanges=["nyse"]))
    with pytest.raises(CompanyMetadataError, match="identity collision"):
        build_company_metadata([one, two], observed_at=OBSERVED)
