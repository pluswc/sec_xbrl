import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "docs/pilots/amd-msft-meta-filing-manifest.json"
)


def test_amd_msft_meta_manifest_is_a_complete_metadata_only_pilot_definition() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = manifest["records"]

    assert manifest == {
        "schema_version": 1,
        "pilot_id": "amd-msft-meta",
        "as_of_date": "2026-08-24",
        "source": "sec_edgar_archive",
        "records": records,
    }
    assert len(records) == 6

    required_fields = {
        "company",
        "ticker",
        "cik",
        "accession",
        "form",
        "filed_date",
        "report_date",
        "selection_role",
        "filing_url",
    }
    expected = {
        ("AMD", "0000002488", "0000002488-26-000018", "10-K", "2026-02-04", "2025-12-27", "ANNUAL_BASELINE"),
        ("AMD", "0000002488", "0000002488-26-000076", "10-Q", "2026-05-06", "2026-03-28", "CURRENT_UPDATE"),
        ("MSFT", "0000789019", "0000950170-25-100235", "10-K", "2025-07-30", "2025-06-30", "ANNUAL_BASELINE"),
        ("MSFT", "0000789019", "0001193125-26-191507", "10-Q", "2026-04-29", "2026-03-31", "CURRENT_UPDATE"),
        ("META", "0001326801", "0001628280-26-003942", "10-K", "2026-01-29", "2025-12-31", "ANNUAL_BASELINE"),
        ("META", "0001326801", "0001628280-26-028526", "10-Q", "2026-04-30", "2026-03-31", "CURRENT_UPDATE"),
    }

    assert {
        (
            record["ticker"],
            record["cik"],
            record["accession"],
            record["form"],
            record["filed_date"],
            record["report_date"],
            record["selection_role"],
        )
        for record in records
    } == expected
    assert Counter(record["ticker"] for record in records) == {"AMD": 2, "MSFT": 2, "META": 2}

    for record in records:
        assert set(record) == required_fields
        assert re.fullmatch(r"\d{10}", record["cik"])
        assert re.fullmatch(r"\d{10}-\d{2}-\d{6}", record["accession"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["filed_date"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["report_date"])

        parsed_url = urlparse(record["filing_url"])
        accession_nodash = record["accession"].replace("-", "")
        assert parsed_url.scheme == "https"
        assert parsed_url.netloc == "www.sec.gov"
        assert parsed_url.path == f"/Archives/edgar/data/{int(record['cik'])}/{accession_nodash}/"
