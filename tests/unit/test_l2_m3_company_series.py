from __future__ import annotations

from pathlib import Path

from sec_xbrl.longitudinal import (
    CompanySeriesMaterializer,
    Layer1SnapshotInput,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
    MemberOrderingView,
)


def _map(
    filing: str, raw: str, entity: str, canonical: str, *, review: bool = False
) -> dict[str, object]:
    return {
        "mapping_id": f"map:{filing}:{entity}:{raw}",
        "cik": "0000320193",
        "entity_type": entity,
        "source_raw_id": raw,
        "source_filing_id": filing,
        "company_canonical_id": canonical,
        "relation": "UNCERTAIN" if review else "SAME",
        "review_required": review,
        "mapping_version": "map-v1",
        "evidence": {"fixture": raw},
    }


def _observation(
    *,
    fact: str,
    filing: str,
    form: str,
    period_class: str,
    end: str,
    value: str | None,
    member: str | None = None,
    review_concept: bool = False,
) -> dict[str, object]:
    dimension = () if member is None else (("product-axis", member, None, "explicit", False),)
    return {
        "period_observation_id": f"ob:{fact}",
        "cik": "0000320193",
        "source_fact_id": fact,
        "source_filing_id": filing,
        "form": form,
        "filed_date": "2026-05-01",
        "report_date": end,
        "raw_concept_id": "revenue-review" if review_concept else "revenue",
        "period_class": period_class,
        "period_key": end,
        "context_start_date": "2026-01-01",
        "context_end_date": end,
        "context_instant_date": None,
        "unit_id": "arbitrary-unit-id",
        "unit_numerator_measures": ("iso4217:USD",),
        "unit_denominator_measures": (),
        "dimension_signature": dimension,
        "value_numeric": value,
        "reported_or_derived": "REPORTED",
        "classification_rule_version": "period-v1",
    }


def _maps() -> tuple[dict[str, object], ...]:
    rows = [
        _map("k25", "revenue", "concept", "company:revenue"),
        _map("q26", "revenue", "concept", "company:revenue"),
        _map("k25", "revenue-review", "concept", "company:review", review=True),
        _map("k25", "product-axis", "axis", "company:product-axis"),
        _map("q26", "product-axis", "axis", "company:product-axis"),
        _map("k25", "iphone", "member", "company:iphone"),
        _map("q26", "iphone", "member", "company:iphone"),
        _map("q26", "mac", "member", "company:mac"),
    ]
    return tuple(rows)


def test_m3_annual_current_keys_preserve_boundaries_units_and_mapping_review() -> None:
    observations = (
        _observation(
            fact="fy",
            filing="k25",
            form="10-K",
            period_class="FY",
            end="2025-09-27",
            value="391035",
            member="iphone",
        ),
        _observation(
            fact="qtd",
            filing="q26",
            form="10-Q",
            period_class="QTD_3M",
            end="2025-12-27",
            value="70000",
            member="iphone",
        ),
        _observation(
            fact="ytd",
            filing="q26",
            form="10-Q",
            period_class="YTD_6M",
            end="2025-12-27",
            value="130000",
            member="iphone",
        ),
        _observation(
            fact="uncertain",
            filing="k25",
            form="10-K",
            period_class="FY",
            end="2025-09-27",
            value="1",
            review_concept=True,
        ),
    )
    result = CompanySeriesMaterializer().materialize(observations=observations, mappings=_maps())

    assert {row["source_fact_id"] for row in result.annual} == {"fy", "uncertain"}
    assert {row["source_fact_id"] for row in result.current} == {"fy", "qtd", "ytd", "uncertain"}
    qtd = next(row for row in result.current if row["source_fact_id"] == "qtd")
    ytd = next(row for row in result.current if row["source_fact_id"] == "ytd")
    assert qtd["series_family_key"] != ytd["series_family_key"]
    assert qtd["unit_semantics"] == (("iso4217:USD",), ())
    assert qtd["actual_period_boundaries"] == ("2026-01-01", "2025-12-27", None)
    uncertain = next(row for row in result.annual if row["source_fact_id"] == "uncertain")
    assert uncertain["series_status"] == "REVIEW_REQUIRED"
    assert uncertain["company_canonical_concept_id"].startswith("raw-review:")


def test_m3_does_not_join_unmapped_member_and_snapshot_mismatch_is_explicit() -> None:
    result = CompanySeriesMaterializer().materialize(
        observations=(
            {
                **_observation(
                    fact="unknown",
                    filing="q26",
                    form="10-Q",
                    period_class="QTD_3M",
                    end="2025-12-27",
                    value="10",
                    member="unknown",
                ),
                "source_snapshot_id": "declared",
            },
            {
                **_observation(
                    fact="bad",
                    filing="q26",
                    form="10-Q",
                    period_class="QTD_3M",
                    end="2025-12-27",
                    value="1",
                ),
                "source_snapshot_id": "not-declared",
            },
        ),
        mappings=_maps(),
        declared_snapshot_ids=("declared",),
    )
    assert result.current[0]["series_status"] == "REVIEW_REQUIRED"
    assert result.current[0]["company_canonical_dimension_key"][0][1].startswith("raw-unmapped:")
    assert result.exclusions[0]["exclusion_reason"] == "SOURCE_SNAPSHOT_NOT_DECLARED"


def test_member_ordering_is_latest_qtd_value_desc_without_reordering_candidates() -> None:
    candidates = (
        CompanySeriesMaterializer()
        .materialize(
            observations=(
                _observation(
                    fact="iphone-old",
                    filing="q26",
                    form="10-Q",
                    period_class="QTD_3M",
                    end="2025-12-27",
                    value="70",
                    member="iphone",
                ),
                _observation(
                    fact="iphone-new",
                    filing="q26",
                    form="10-Q",
                    period_class="QTD_3M",
                    end="2026-03-28",
                    value="60",
                    member="iphone",
                ),
                _observation(
                    fact="mac",
                    filing="q26",
                    form="10-Q",
                    period_class="QTD_3M",
                    end="2026-03-28",
                    value="30",
                    member="mac",
                ),
            ),
            mappings=_maps(),
        )
        .current
    )
    before = tuple(row["series_candidate_id"] for row in candidates)
    ordering = MemberOrderingView().build(candidates)
    assert [row["member_id"] for row in ordering] == ["company:iphone", "company:mac"]
    assert [row["latest_value_numeric"] for row in ordering] == ["60", "30"]
    assert tuple(row["series_candidate_id"] for row in candidates) == before


def test_m3_candidates_can_publish_without_premature_analytical_fact(tmp_path: Path) -> None:
    result = CompanySeriesMaterializer().materialize(
        observations=(
            _observation(
                fact="fy",
                filing="k25",
                form="10-K",
                period_class="FY",
                end="2025-09-27",
                value="391035",
            ),
        ),
        mappings=_maps(),
    )
    run = Layer2Run(
        run_version="l2-m3-fixture-v1",
        corpus_run_id="fixture",
        inputs=(
            Layer1SnapshotInput(
                "0000320193", "acc", "10-K", "2025-11-01", "2025-09-27", "snap", "a" * 64
            ),
        ),
        rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
    )
    published = Layer2Publisher(tmp_path / "layer2").publish(run, result.as_datasets())
    assert published.output_counts["annual_series_candidate"] == 1
