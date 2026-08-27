import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import (
    ArelleFilingLoader,
    FilingIndexCache,
    FilingIndexError,
    FilingPackageResolver,
)
from sec_xbrl.filing.package_cache import AccessionPackageCache


def _filing(*, primary_document: str | None = "example-20241231.htm") -> FilingRef:
    return FilingRef(
        "0000320193",
        "0000320193-25-000079",
        "10-K",
        date(2025, 10, 31),
        primary_document=primary_document,
    )


def _zip_bytes(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, _xbrl_instance() if name.endswith(".xml") else "<html></html>")
    return buffer.getvalue()


def _index_bytes(*items: dict[str, str]) -> bytes:
    return json.dumps({"directory": {"item": list(items)}}).encode()


def _xbrl_instance() -> str:
    return """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<xbrl xmlns=\"http://www.xbrl.org/2003/instance\" />"""


def test_resolver_caches_index_and_resolves_primary_document_without_reuse_network(tmp_path: Path) -> None:
    filing = _filing()
    package_cache = AccessionPackageCache(tmp_path / "packages")
    index_cache = FilingIndexCache(tmp_path / "indexes")
    fetcher = _Fetch(
        _zip_bytes("example-20241231.htm", "example.xsd"),
        _index_bytes({"name": "example-20241231.htm", "type": "10-K"}),
    )

    resolved = FilingPackageResolver(package_cache, index_cache).resolve(filing, fetcher)

    assert resolved.entrypoint_name == "example-20241231.htm"
    assert resolved.index.source_url.endswith("/320193/000032019325000079/index.json")
    assert len(fetcher.urls) == 3
    assert FilingPackageResolver(package_cache, index_cache).resolve(filing, _NeverFetch()) == resolved


def test_resolver_accepts_discovery_primary_document_present_only_in_validated_zip(tmp_path: Path) -> None:
    filing = _filing(primary_document="example-20241231.htm")
    resolved = FilingPackageResolver(
        AccessionPackageCache(tmp_path / "packages"), FilingIndexCache(tmp_path / "indexes")
    ).resolve(
        filing,
        _Fetch(
            _zip_bytes("example-20241231.htm", "example.xsd"),
            _index_bytes({"name": "example.xsd", "type": "EX-101.SCH"}),
        ),
    )

    assert resolved.entrypoint_name == "example-20241231.htm"


def test_resolver_rejects_discovery_primary_document_absent_from_zip(tmp_path: Path) -> None:
    filing = _filing(primary_document="example-20241231.htm")

    with pytest.raises(FilingIndexError, match="primary document is absent from XBRL package"):
        FilingPackageResolver(
            AccessionPackageCache(tmp_path / "packages"), FilingIndexCache(tmp_path / "indexes")
        ).resolve(
            filing,
            _Fetch(
                _zip_bytes("instance.xml"),
                _index_bytes({"name": "example-20241231.htm", "type": "10-K"}),
            ),
        )


@pytest.mark.parametrize("primary_document", ["../outside.htm", "/absolute.htm", r"dir\\file.htm"])
def test_resolver_rejects_unsafe_discovery_primary_document(
    tmp_path: Path, primary_document: str
) -> None:
    filing = _filing(primary_document=primary_document)

    with pytest.raises(FilingIndexError, match="primary document has unsafe filename"):
        FilingPackageResolver(
            AccessionPackageCache(tmp_path / "packages"), FilingIndexCache(tmp_path / "indexes")
        ).resolve(
            filing,
            _Fetch(
                _zip_bytes("example-20241231.htm"),
                _index_bytes({"name": "example-20241231.htm", "type": "10-K"}),
            ),
        )


def test_resolver_falls_back_to_unique_xbrl_instance_and_rejects_ambiguity(tmp_path: Path) -> None:
    filing = _filing(primary_document=None)
    package_cache = AccessionPackageCache(tmp_path / "packages")
    index_cache = FilingIndexCache(tmp_path / "indexes")
    resolver = FilingPackageResolver(package_cache, index_cache)

    resolved = resolver.resolve(
        filing,
        _Fetch(
            _zip_bytes("instance.xml", "report.htm"),
            _index_bytes(
                {"name": "instance.xml", "type": "EX-101.INS"},
                {"name": "report.htm", "type": "10-K"},
            ),
        ),
    )
    assert resolved.entrypoint_name == "instance.xml"

    ambiguous = _filing(primary_document=None)
    ambiguous_resolver = FilingPackageResolver(
        AccessionPackageCache(tmp_path / "ambiguous-packages"), FilingIndexCache(tmp_path / "ambiguous-indexes")
    )
    with pytest.raises(FilingIndexError, match="ambiguous XBRL instance"):
        ambiguous_resolver.resolve(
            ambiguous,
            _Fetch(
                _zip_bytes("one.xml", "two.xml"),
                _index_bytes(
                    {"name": "one.xml", "type": "EX-101.INS"},
                    {"name": "two.xml", "type": "EX-101.INS"},
                ),
            ),
        )


def test_index_cache_rejects_tampering_and_unsafe_metadata(tmp_path: Path) -> None:
    filing = _filing()
    cache = FilingIndexCache(tmp_path / "indexes")
    cache.ensure(filing, _IndexOnlyFetch(_index_bytes({"name": "example-20241231.htm", "type": "10-K"})))
    (cache.cache_dir(filing) / "index.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FilingIndexError, match="artifact hash mismatch"):
        cache.ensure(filing, _NeverFetch())

    unsafe_cache = FilingIndexCache(tmp_path / "unsafe-indexes")
    with pytest.raises(FilingIndexError, match="unsafe filename"):
        unsafe_cache.ensure(filing, _IndexOnlyFetch(_index_bytes({"name": "../outside.xml", "type": "EX-101.INS"})))
    assert not unsafe_cache.cache_dir(filing).exists()


def test_arelle_loader_extracts_local_entrypoint_and_uses_injected_loader(tmp_path: Path) -> None:
    filing = _filing()
    resolved = FilingPackageResolver(
        AccessionPackageCache(tmp_path / "packages"), FilingIndexCache(tmp_path / "indexes")
    ).resolve(
        filing,
        _Fetch(
            _zip_bytes("example-20241231.htm"),
            _index_bytes({"name": "example-20241231.htm", "type": "10-K"}),
        ),
    )
    seen: list[Path] = []

    class _Model:
        modelDocument = object()

    model = ArelleFilingLoader(lambda entrypoint: seen.append(entrypoint) or _Model()).load(
        resolved, tmp_path / "working"
    )

    assert isinstance(model, _Model)
    assert seen == [tmp_path / "working" / "example-20241231.htm"]
    assert seen[0].read_text(encoding="utf-8") == "<html></html>"


def test_arelle_loads_a_local_cached_xbrl_fixture_without_network(tmp_path: Path) -> None:
    pytest.importorskip("arelle")
    filing = _filing(primary_document=None)
    resolved = FilingPackageResolver(
        AccessionPackageCache(tmp_path / "packages"), FilingIndexCache(tmp_path / "indexes")
    ).resolve(
        filing,
        _Fetch(
            _zip_bytes("instance.xml"),
            _index_bytes({"name": "instance.xml", "type": "EX-101.INS"}),
        ),
    )

    model = ArelleFilingLoader().load(resolved, tmp_path / "working")

    assert model.modelDocument is not None


class _Fetch:
    def __init__(self, zip_content: bytes, index_content: bytes) -> None:
        self.zip_content = zip_content
        self.index_content = index_content
        self.urls: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        if url.endswith(".zip"):
            return self.zip_content
        if url.endswith("index.json"):
            return self.index_content
        return b"headers"


class _IndexOnlyFetch:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def fetch(self, url: str) -> bytes:
        assert url.endswith("index.json")
        return self.content


class _NeverFetch:
    def fetch(self, url: str) -> bytes:
        raise AssertionError(f"network must not be used: {url}")
