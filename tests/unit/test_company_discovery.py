import json
from pathlib import Path

import httpx
import pytest

from sec_xbrl.filing.company_discovery import (
    CompanySubmissionsAccessionProvider,
    CompanySubmissionsCollector,
    DiscoveryError,
    DiscoveryStateStore,
    DuplicateAccessionError,
    SECSubmissionsClient,
    SubmissionsSnapshotStore,
    canonicalize_cik,
    load_company_targets,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_load_company_targets_canonicalizes_and_sorts(tmp_path: Path) -> None:
    targets_file = tmp_path / "companies.jsonl"
    targets_file.write_text('{"cik":"320193","ticker":"AAPL"}\n{"cik":789019}\n')

    assert [target.cik for target in load_company_targets(targets_file)] == [
        "0000320193",
        "0000789019",
    ]
    assert canonicalize_cik("320193") == "0000320193"


def test_provider_maps_all_supported_forms_and_orders_deterministically(tmp_path: Path) -> None:
    root = FIXTURES / "sec_submissions_root.json"
    history = FIXTURES / "sec_submissions_history.json"
    provider = CompanySubmissionsAccessionProvider([root, history], cik="320193")

    filings = list(provider.iter_filings(forms={"10-K", "10-Q", "10-Q/A", "10-K/A"}))

    assert [(filing.form, filing.accession) for filing in filings] == [
        ("10-Q", "0000320193-24-000006"),
        ("10-K/A", "0000320193-24-000099"),
        ("10-Q/A", "0000320193-25-000008"),
        ("10-K", "0000320193-25-000079"),
    ]
    assert filings[0].cik == "0000320193"
    assert filings[-1].report_date is not None
    assert filings[-1].is_xbrl is True
    assert filings[-1].source == "sec_submissions"
    assert filings == list(provider.iter_filings(forms={"10-K", "10-Q", "10-Q/A", "10-K/A"}))


def test_provider_rejects_malformed_and_conflicting_records(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryError, match="expected CIK is required"):
        list(
            CompanySubmissionsAccessionProvider(
                [FIXTURES / "sec_submissions_history.json"]
            ).iter_filings(forms={"10-Q"})
        )

    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps({"cik": "1", "accessionNumber": ["bad"], "form": ["10-K"], "filingDate": ["2025-01-01"]}))
    with pytest.raises(DiscoveryError, match="invalid accession"):
        list(
            CompanySubmissionsAccessionProvider([malformed], cik="1").iter_filings(forms={"10-K"})
        )

    conflicting = tmp_path / "conflicting.json"
    conflicting.write_text(
        (FIXTURES / "sec_submissions_history.json")
        .read_text()
        .replace("20251031", "20251030", 1)
    )
    with pytest.raises(DuplicateAccessionError):
        list(
            CompanySubmissionsAccessionProvider(
                [FIXTURES / "sec_submissions_root.json", conflicting], cik="320193"
            ).iter_filings(forms={"10-K"})
        )
    with pytest.raises(DiscoveryError, match="unsupported forms"):
        list(CompanySubmissionsAccessionProvider([malformed]).iter_filings(forms={"8-K"}))

    third_party_accession = tmp_path / "third-party-accession.json"
    third_party_accession.write_text(
        (FIXTURES / "sec_submissions_history.json")
        .read_text()
        .replace("0000320193-24-000006", "0001193125-24-000006")
    )
    assert list(
        CompanySubmissionsAccessionProvider([third_party_accession], cik="320193").iter_filings(
            forms={"10-Q"}
        )
    )
    wrong_company = tmp_path / "wrong-company-history.json"
    payload = json.loads((FIXTURES / "sec_submissions_history.json").read_text())
    payload["cik"] = "0000789019"
    wrong_company.write_text(json.dumps(payload))
    with pytest.raises(DiscoveryError, match="submissions CIK mismatch"):
        list(CompanySubmissionsAccessionProvider([wrong_company], cik="320193").iter_filings(forms={"10-Q"}))


def test_sec_submissions_client_sets_user_agent_and_retries_locally() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.headers["User-Agent"] == "sec-xbrl contact@example.com"
        return httpx.Response(503 if request_count == 1 else 200, content=b"{}")

    client = SECSubmissionsClient(
        user_agent="sec-xbrl contact@example.com",
        min_interval_seconds=0,
        retries=1,
        transport=httpx.MockTransport(handler),
    )

    assert client.fetch("https://data.sec.gov/submissions/CIK0000320193.json") == b"{}"
    assert request_count == 2


def test_collector_caches_root_and_history_immutably_and_writes_state(tmp_path: Path) -> None:
    root = (FIXTURES / "sec_submissions_root.json").read_bytes()
    history = (FIXTURES / "sec_submissions_history.json").read_bytes()
    requested: list[str] = []

    def fetch(url: str) -> bytes:
        requested.append(url)
        return history if url.endswith("-001.json") else root

    collector = CompanySubmissionsCollector(
        fetch,
        SubmissionsSnapshotStore(tmp_path / "raw"),
        DiscoveryStateStore(tmp_path / "state"),
    )
    snapshots = collector.collect("320193")

    assert len(snapshots) == 2
    assert all(path.exists() for path in snapshots)
    assert collector.collect("0000320193") == snapshots
    assert len(list((tmp_path / "raw" / "0000320193").glob("*.json"))) == 2
    state = json.loads((tmp_path / "state" / "0000320193.json").read_text())
    assert state["snapshot_hashes"] == [path.stem for path in snapshots]
    assert requested == [
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json",
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json",
    ]
