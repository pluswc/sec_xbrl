import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.legacy_package_adoption import (
    LEGACY_SOURCE,
    LegacyPackageAdopter,
    LegacyPackageAdoptionError,
)
from sec_xbrl.filing.package_cache import AccessionPackageCache


def _filing() -> FilingRef:
    return FilingRef("0000320193", "0000320193-25-000079", "10-K", date(2025, 10, 31))


def _write_legacy_package(
    root: Path,
    filing: FilingRef,
    *,
    cik: str | None = None,
    form: str | None = None,
    include_zip: bool = True,
    include_headers: bool = True,
    valid_zip: bool = True,
) -> Path:
    date_dir = root / "20251101"
    package_dir = date_dir / filing.accession
    package_dir.mkdir(parents=True)
    (date_dir / "index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {"adsh": filing.accession, "cik": cik or filing.cik, "form": form or filing.form}
                ]
            }
        ),
        encoding="utf-8",
    )
    if include_zip:
        zip_path = package_dir / f"{filing.accession}-xbrl.zip"
        if valid_zip:
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("instance.xml", "<xbrl />")
        else:
            zip_path.write_bytes(b"corrupt zip")
    if include_headers:
        (package_dir / f"{filing.accession}-index-headers.html").write_text(
            "<html>headers</html>", encoding="utf-8"
        )
    return package_dir


def test_adopts_matching_legacy_package_atomically_with_sha256(tmp_path: Path) -> None:
    filing = _filing()
    legacy_root = tmp_path / "legacy-data"
    legacy_package = _write_legacy_package(legacy_root, filing)
    cache = AccessionPackageCache(tmp_path / "packages")

    report = LegacyPackageAdopter(legacy_root, cache).adopt([filing])

    assert not report.rejected
    assert len(report.adopted) == 1
    manifest = report.adopted[0]
    assert manifest.source == LEGACY_SOURCE
    assert [artifact.filename for artifact in manifest.artifacts] == [
        f"{filing.accession}-xbrl.zip",
        f"{filing.accession}-index-headers.html",
    ]
    for artifact in manifest.artifacts:
        destination = cache.package_dir(filing) / artifact.filename
        assert destination.read_bytes() == (legacy_package / artifact.filename).read_bytes()
        assert artifact.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert not list(cache.package_dir(filing).parent.glob(".*.partial-*"))


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"include_zip": False}, "LEGACY_ZIP_MISSING"),
        ({"include_headers": False}, "LEGACY_HEADERS_MISSING"),
        ({"valid_zip": False}, "LEGACY_ZIP_INVALID"),
        ({"cik": "0000320194"}, "LEGACY_IDENTITY_MISMATCH"),
        ({"form": "10-Q"}, "LEGACY_IDENTITY_MISMATCH"),
    ],
)
def test_rejects_missing_corrupt_or_mismatched_legacy_packages(
    tmp_path: Path, kwargs: dict[str, object], code: str
) -> None:
    filing = _filing()
    legacy_root = tmp_path / "legacy-data"
    _write_legacy_package(legacy_root, filing, **kwargs)
    cache = AccessionPackageCache(tmp_path / "packages")

    report = LegacyPackageAdopter(legacy_root, cache).adopt([filing])

    assert not report.adopted
    assert [issue.code for issue in report.rejected] == [code]
    assert not cache.package_dir(filing).exists()


def test_rejects_ambiguous_accession_without_publishing(tmp_path: Path) -> None:
    filing = _filing()
    legacy_root = tmp_path / "legacy-data"
    _write_legacy_package(legacy_root, filing)
    second_date = legacy_root / "20251102"
    second_package = second_date / filing.accession
    second_package.mkdir(parents=True)
    (second_date / "index.json").write_text(
        json.dumps({"filings": [{"adsh": filing.accession, "cik": filing.cik, "form": filing.form}]}),
        encoding="utf-8",
    )
    with zipfile.ZipFile(second_package / f"{filing.accession}-xbrl.zip", "w") as archive:
        archive.writestr("instance.xml", "<xbrl />")
    (second_package / f"{filing.accession}-index-headers.html").write_text("headers", encoding="utf-8")
    cache = AccessionPackageCache(tmp_path / "packages")

    with pytest.raises(LegacyPackageAdoptionError, match="LEGACY_ACCESSION_AMBIGUOUS"):
        LegacyPackageAdopter(legacy_root, cache).adopt_one(filing)
    assert not cache.package_dir(filing).exists()


def test_report_keeps_adopting_after_a_rejection(tmp_path: Path) -> None:
    accepted = _filing()
    rejected = FilingRef("0000320193", "0000320193-25-000080", "10-Q", date(2025, 11, 1))
    legacy_root = tmp_path / "legacy-data"
    _write_legacy_package(legacy_root, accepted)
    cache = AccessionPackageCache(tmp_path / "packages")

    report = LegacyPackageAdopter(legacy_root, cache).adopt([accepted, rejected])

    assert [manifest.accession for manifest in report.adopted] == [accepted.accession]
    assert [issue.code for issue in report.rejected] == ["LEGACY_ACCESSION_MISSING"]
    assert cache.package_dir(accepted).is_dir()
