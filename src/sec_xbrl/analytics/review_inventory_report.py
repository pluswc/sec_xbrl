"""Reusable Korean consumer report for reader-verified C3-M5 review inventory."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal import (
    CorpusRelease,
    CorpusReleaseAdapter,
    Layer2PublicationReader,
    Layer2RuleVersions,
    QuarterlyPolicyV2Reader,
    ReviewInventoryPublicationReader,
)
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication
from sec_xbrl.longitudinal.review_inventory import ReviewInventoryError, ReviewInventoryResult
from sec_xbrl.longitudinal.quarterly_policy import QuarterlyPolicyResult


@dataclass(frozen=True, slots=True)
class ReviewInventoryReportInput:
    """One review inventory plus the exact objects required to attest it."""

    ticker: str
    inventory_root: Path
    upstream: VerifiedLayer2Publication
    release: CorpusRelease
    quarterly_result: QuarterlyPolicyResult | None = None


@dataclass(frozen=True, slots=True)
class KoreanReviewInventoryReport:
    markdown: str
    summary: Mapping[str, Any]

    def write(self, *, markdown_path: Path, json_path: Path) -> None:
        Path(markdown_path).write_text(self.markdown, encoding="utf-8")
        Path(json_path).write_text(
            json.dumps(self.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class KoreanReviewInventoryReportGenerator:
    """Render inventory-only Korean output without analytical activation policy."""

    def generate(
        self,
        inputs: Iterable[ReviewInventoryReportInput],
        *,
        ticker_scope: Iterable[str] = (),
        top_n: int = 10,
    ) -> KoreanReviewInventoryReport:
        requested = {item.upper() for item in ticker_scope}
        if top_n < 1:
            raise ReviewInventoryError("top_n must be positive")
        reports: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in inputs:
            ticker = str(item.ticker).upper()
            if not ticker or ticker in seen:
                raise ReviewInventoryError("report inputs require unique non-empty tickers")
            seen.add(ticker)
            if requested and ticker not in requested:
                continue
            result = ReviewInventoryPublicationReader().load(
                Path(item.inventory_root), upstream=item.upstream, release=item.release
            )
            reports.append(_company_summary(ticker, result, item.upstream, item.quarterly_result, top_n=top_n))
        if requested - seen:
            raise ReviewInventoryError("ticker scope has no supplied report input")
        if not reports:
            raise ReviewInventoryError("report has no selected inventory inputs")
        summary = {
            "report_type": "C3_M5_REVIEW_INVENTORY_KO",
            "scope": [row["ticker"] for row in reports],
            "policy": {
                "q4": "기술 후보이며 승인 또는 계산 결과가 아님",
                "recast": "근거 검토 후보이며 재제시 주장 또는 CURRENT_COMPARABLE 활성화가 아님",
            },
            "companies": reports,
            "reviewer_intake": _reviewer_intake(),
        }
        return KoreanReviewInventoryReport(_render_markdown(summary), summary)


def _company_summary(ticker: str, result: ReviewInventoryResult, upstream: VerifiedLayer2Publication, quarterly: QuarterlyPolicyResult | None, *, top_n: int) -> dict[str, Any]:
    q4 = [dict(row) for row in result.q4_candidates]
    recast = [dict(row) for row in result.recast_candidates]
    artifact = [dict(row) for row in result.artifact_coverage]
    if any(row.get("review_status") != "PENDING_SEMANTIC_REVIEW" for row in q4):
        raise ReviewInventoryError("review inventory contains unsupported Q4 review status")
    if any(row.get("value_numeric") is not None or row.get("formula") is not None for row in q4):
        raise ReviewInventoryError("review inventory must not contain a Q4 value or formula")
    if any(row.get("review_status") != "PENDING_EVIDENCE_REVIEW" or row.get("recast_claim") != "NOT_MADE" for row in recast):
        raise ReviewInventoryError("review inventory contains an activated recast claim")
    counts = Counter(
        (str(row["fy_source"].get("period_boundaries", (None, None))[1]), str(row.get("company_canonical_concept_id")))
        for row in q4
    )
    breakdown = [
        {"fy_end": fy_end, "company_concept_id": concept, "technical_candidate_count": count}
        for (fy_end, concept), count in counts.most_common(top_n)
    ]
    example = _lineage_example(q4[0]) if q4 else None
    return {
        "ticker": ticker,
        "cik": q4[0].get("cik") if q4 else None,
        "candidate_counts": {"reported_as_filed": sum(1 for row in upstream.records("analytical_fact") if row.get("view") == "AS_FILED"), "q4_derived": 0 if quarterly is None else len(quarterly.q4_candidates), "q4_technical": len(q4), "recast_evidence_review": len(recast)},
        "q4_status": {"technical_eligibility": "PENDING_SEMANTIC_REVIEW", "semantic_approval": "NOT_APPROVED"},
        "q4_top_fy_end_concepts": breakdown,
        "q4_lineage_example": example,
        "artifact_coverage": dict(sorted(Counter(str(row.get("artifact_status")) for row in artifact).items())),
        "recast_interpretation": (
            "후보 0건은 재제시가 없다는 결론이 아닙니다. 현재의 제한된 기술 매칭 규칙에서 "
            "다른 filing의 동일 범위 관측치를 찾지 못했다는 뜻이며, CURRENT_COMPARABLE을 활성화하지 않습니다."
            if not recast
            else "후보는 증거 검토 대기 상태이며 재제시 주장이나 CURRENT_COMPARABLE 활성화가 아닙니다."
        ),
    }


def _lineage_example(row: Mapping[str, Any]) -> dict[str, Any]:
    def source(value: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value.get(key) for key in ("source_filing_id", "selected_fact_id", "source_document", "source_locator", "context_id", "unit_id", "period_key")}
    return {"review_candidate_id": row.get("review_candidate_id"), "fy_source": source(row["fy_source"]), "ytd_9m_source": source(row["ytd_9m_source"])}


def _reviewer_intake() -> list[str]:
    return [
        "기록된 FY·YTD 9M 문서와 locator에서 공시 의미 및 가산성(additive)을 검토합니다.",
        "승인 시에만 버전이 있는 M2 QuarterlySemanticDeclaration을 통제 registry에 등록합니다.",
        "재제시 의심 건은 filing-local 표/서술 근거를 보존하고, 정확한 과거 Fact·새 source·basis·locator를 연결한 M3 evidence record를 등록합니다.",
        "M2/M3를 재실행하며, inventory·AS_FILED Fact·Q4·CURRENT_COMPARABLE 값을 수동 편집하지 않습니다.",
    ]


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines = ["# C3-M5 분기 상태 및 검토 인벤토리", "", "이 문서는 governed consumer 출력입니다. Reported AS_FILED와 승인된 Derived Q4, 그리고 아직 검토 대기인 후보를 분리합니다. Pending Review에 대해서는 Q4 숫자를 계산하지 않고, 재제시를 주장하거나 CURRENT_COMPARABLE을 활성화하지 않습니다.", "", "## 기업별 현황", "", "| 티커 | CIK | Reported AS_FILED | Derived Q4 | Pending Review | 재제시 근거 검토 후보 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for company in summary["companies"]:
        counts = company["candidate_counts"]
        lines.append(f"| {company['ticker']} | {company['cik'] or 'N/A'} | {counts['reported_as_filed']} | {counts['q4_derived']} | {counts['q4_technical']} | {counts['recast_evidence_review']} |")
    for company in summary["companies"]:
        lines += ["", f"## {company['ticker']} ({company['cik'] or 'N/A'})", "", "**기술 적합성**: FY/YTD 9M의 기간·단위·차원·통화 조건이 맞는 검토 후보입니다.  **의미 승인**: 아직 `NOT_APPROVED`이며, `PENDING_SEMANTIC_REVIEW`는 Q4 계산 허가가 아닙니다.", "", "상위 FY 종료일 / 기술 Concept (최대 10개):", "", "| FY 종료일 | 기술 Concept ID | 후보 수 |", "| --- | --- | ---: |"]
        for row in company["q4_top_fy_end_concepts"]:
            lines.append(f"| {row['fy_end']} | `{row['company_concept_id']}` | {row['technical_candidate_count']} |")
        example = company["q4_lineage_example"]
        if example:
            lines += ["", "Q4/FY/YTD lineage 예시 (계산 결과 아님):", "", f"- 후보 ID: `{example['review_candidate_id']}`", _source_line("FY", example["fy_source"]), _source_line("YTD 9M", example["ytd_9m_source"])]
        lines += ["", "Source artifact coverage: " + ", ".join(f"`{key}`={value}" for key, value in company["artifact_coverage"].items()) + ".", "", f"재제시 검토: {company['candidate_counts']['recast_evidence_review']}건. {company['recast_interpretation']}"]
    lines += ["", "## 검토 승인 입력 절차", ""] + [f"{index}. {value}" for index, value in enumerate(summary["reviewer_intake"], start=1)]
    return "\n".join(lines) + "\n"


def _source_line(label: str, source: Mapping[str, Any]) -> str:
    return (f"- {label}: filing `{source['source_filing_id']}`, Fact `{source['selected_fact_id']}`, "
            f"문서 `{source['source_document']}`, locator `{source['source_locator']}`, "
            f"context `{source['context_id']}`, unit `{source['unit_id']}`, period `{source['period_key']}`.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reader-verified C3-M5 Korean review inventory report")
    parser.add_argument("--inventory-root", action="append", required=True)
    parser.add_argument("--layer2-root", action="append", required=True)
    parser.add_argument("--quarterly-policy-root", action="append", required=True)
    parser.add_argument("--q4-policy-registry-root", action="append", required=True)
    parser.add_argument("--ticker", action="append", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--corpus-run-id", required=True)
    parser.add_argument("--output-markdown", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args(argv)
    if not (len(args.inventory_root) == len(args.layer2_root) == len(args.quarterly_policy_root) == len(args.q4_policy_registry_root) == len(args.ticker)):
        parser.error("inventory-root, layer2-root, quarterly-policy-root, q4-policy-registry-root, and ticker must have matching counts")
    inputs = []
    for inventory, layer2, quarterly_policy, registry, ticker in zip(args.inventory_root, args.layer2_root, args.quarterly_policy_root, args.q4_policy_registry_root, args.ticker, strict=True):
        upstream = Layer2PublicationReader().load(Path(layer2))
        release = CorpusReleaseAdapter().load(Path(args.corpus_root), corpus_run_id=args.corpus_run_id,
            ciks=set(upstream.input_ciks), run_version=str(upstream.identity["layer2_run_version"]),
            rules=Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"))
        quarterly = QuarterlyPolicyV2Reader().load(Path(quarterly_policy), upstream=upstream, release=release, registry_root=Path(registry))
        inputs.append(ReviewInventoryReportInput(ticker, Path(inventory), upstream, release, quarterly))
    report = KoreanReviewInventoryReportGenerator().generate(inputs, ticker_scope=args.ticker)
    report.write(markdown_path=Path(args.output_markdown), json_path=Path(args.output_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
