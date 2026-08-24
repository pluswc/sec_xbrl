import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

from sec_xbrl.filing.filing_index import ArelleFilingLoader
from sec_xbrl.pilots.amd_msft_meta_p1 import (
    PilotManifestError,
    PilotP1Runner,
    _relationship_presence_counts,
    load_pilot_manifest,
    write_qa_report,
)

_MANIFEST = Path(__file__).resolve().parents[2] / "docs/pilots/amd-msft-meta-filing-manifest.json"


def test_p1_runner_uses_committed_manifest_and_local_cache_only(tmp_path: Path) -> None:
    filings = load_pilot_manifest(_MANIFEST)
    fetcher = _Fetch()
    runner = PilotP1Runner(
        cache_root=tmp_path / "caller-selected-cache",
        fetcher=fetcher,
        model_loader=ArelleFilingLoader(lambda _: _Model()),
        now=lambda: datetime(2026, 8, 24, 1, 2, 3, tzinfo=UTC),
    )

    rows = runner.run(filings)

    assert len(rows) == 6
    assert all(row.package_result == "PASS" and row.stage is None for row in rows)
    assert all(row.entrypoint == "instance.xml" for row in rows)
    assert all(row.arelle_outcome == "PASS" for row in rows)
    assert all(row.fact_count == 0 and row.context_count == 0 for row in rows)
    assert all(row.run_timestamp_utc == "2026-08-24T01:02:03Z" for row in rows)
    assert len(fetcher.urls) == 18
    assert not any(path.suffix == ".parquet" for path in tmp_path.rglob("*"))

    assert runner.run(filings) == rows
    assert len(fetcher.urls) == 18

    report = tmp_path / "review" / "qa.json"
    write_qa_report(rows, report)
    assert json.loads(report.read_text(encoding="utf-8"))["rows"][0]["accession"] == rows[0].accession


def test_p1_manifest_rejects_url_that_does_not_match_accession(tmp_path: Path) -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    payload["records"][0]["filing_url"] = "https://www.sec.gov/Archives/edgar/data/1/incorrect/"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PilotManifestError, match="does not match filing identity"):
        load_pilot_manifest(path)


def test_relationship_presence_counts_only_the_fully_scoped_role_key() -> None:
    arcrole = "http://www.xbrl.org/2003/arcrole/summation-item"
    model = _RelationshipModel(
        {
            (arcrole, "role", "link", "arc"): 2,
            (arcrole, "role", "link", None): 2,
            (arcrole, "role", None, "arc"): 2,
            (arcrole, "role", None, None): 2,
        }
    )

    assert _relationship_presence_counts(model) == {"PRE": 0, "CAL": 2, "DEF": 0}


class _Model:
    modelDocument = object()
    factsInInstance: tuple[object, ...] = ()
    baseSets: ClassVar[dict[object, object]] = {}
    roleTypes: ClassVar[dict[object, object]] = {}

    def relationshipSet(self, *_: object) -> object:
        return type("Relationships", (), {"modelRelationships": ()})()


class _Fetch:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.zip_content = _zip_content()
        self.index_content = json.dumps(
            {"directory": {"item": [{"name": "instance.xml", "type": "EX-101.INS"}]}}
        ).encode("utf-8")

    def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        if url.endswith(".zip"):
            return self.zip_content
        if url.endswith("index.json"):
            return self.index_content
        return (
            b"&lt;DOCUMENT&gt;\n&lt;TYPE&gt;10-K\n&lt;FILENAME&gt;instance.xml\n&lt;/DOCUMENT&gt;\n"
            b"&lt;DOCUMENT&gt;\n&lt;TYPE&gt;10-Q\n&lt;FILENAME&gt;instance.xml\n&lt;/DOCUMENT&gt;"
        )


def _zip_content() -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("instance.xml", '<?xml version="1.0"?><xbrl/>')
    return content.getvalue()


class _RelationshipModel:
    def __init__(self, counts: dict[tuple[str, str, str | None, str | None], int]) -> None:
        self.baseSets = {key: object() for key in counts}
        self.counts = counts

    def relationshipSet(self, *key: object) -> object:
        return type("Relationships", (), {"modelRelationships": (object(),) * self.counts[key]})()
