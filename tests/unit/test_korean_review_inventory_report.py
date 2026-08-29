from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.analytics import KoreanReviewInventoryReportGenerator, ReviewInventoryReportInput
from sec_xbrl.longitudinal import ReviewInventoryError, ReviewInventoryPublisher, ReviewInventoryResult
from sec_xbrl.longitudinal.materialization import _READER_ATTESTATION_TOKEN, VerifiedLayer2Publication


class _Release:
    def __init__(self) -> None:
        self.ciks = ("0000000001",)
        self.layer2_run = type("Run", (), {"fingerprint": "f" * 64})()


def _upstream() -> VerifiedLayer2Publication:
    return VerifiedLayer2Publication(Path("/m1"), Path("/m1/manifest"), MappingProxyType({"layer2_run_fingerprint": "f" * 64, "layer2_manifest_sha256": "a" * 64}), ("0000000001",), MappingProxyType({}), _READER_ATTESTATION_TOKEN)


def _result() -> ReviewInventoryResult:
    return ReviewInventoryResult(({
        "review_candidate_id": "candidate:one", "cik": "0000000001", "review_status": "PENDING_SEMANTIC_REVIEW",
        "value_numeric": None, "formula": None, "company_canonical_concept_id": "company:one:concept:revenue",
        "fy_source": {"period_boundaries": ("2024-01-01", "2025-01-01", None), "source_filing_id": "fy-filing", "selected_fact_id": "fy-fact", "source_document": "fy.htm", "source_locator": "line:1", "context_id": "fy-context", "unit_id": "usd", "period_key": "2024-01-01/2025-01-01"},
        "ytd_9m_source": {"source_filing_id": "ytd-filing", "selected_fact_id": "ytd-fact", "source_document": "ytd.htm", "source_locator": "line:2", "context_id": "ytd-context", "unit_id": "usd", "period_key": "2024-01-01/2024-10-01"},
    },), (), ({"artifact_status": "ARTIFACT_RETAINED"},))


def _input(tmp_path: Path, ticker: str = "TEST") -> ReviewInventoryReportInput:
    release, upstream = _Release(), _upstream()
    published = ReviewInventoryPublisher().publish(_result(), output_root=tmp_path, run_version=ticker.lower(), upstream=upstream, release=release)  # type: ignore[arg-type]
    return ReviewInventoryReportInput(ticker, published.run_root, upstream, release)  # type: ignore[arg-type]


def test_korean_report_is_generic_and_keeps_zero_recast_interpretation(tmp_path: Path) -> None:
    report = KoreanReviewInventoryReportGenerator().generate((_input(tmp_path, "ALPHA"), _input(tmp_path, "BETA")), ticker_scope=("BETA",))
    assert report.summary["scope"] == ["BETA"]
    assert "기술 적합성" in report.markdown
    assert "의미 승인" in report.markdown
    assert "재제시가 없다는 결론이 아닙니다" in report.markdown
    assert "ALPHA" not in report.markdown
    assert "Q4 숫자를 계산하지 않고" in report.markdown


def test_report_reader_rejects_tampered_inventory(tmp_path: Path) -> None:
    value = _input(tmp_path)
    (value.inventory_root / "q4_review_candidate.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReviewInventoryError, match="content"):
        KoreanReviewInventoryReportGenerator().generate((value,))


def test_report_rejects_unknown_scope(tmp_path: Path) -> None:
    with pytest.raises(ReviewInventoryError, match="ticker scope"):
        KoreanReviewInventoryReportGenerator().generate((_input(tmp_path),), ticker_scope=("MISSING",))
