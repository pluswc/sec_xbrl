from __future__ import annotations

import copy
import gc
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl import analysis, history


def _publication(tmp_path: Path) -> Path:
    root = tmp_path / "history"
    root.mkdir()
    columns = ({
        "fiscal_time_series_column_id": "fy-2025",
        "fiscal_year": 2025,
        "fiscal_quarter": 4,
        "period_class": "FY",
        "column_status": "AVAILABLE",
    },)
    rows = ({"fiscal_time_series_row_id": "row", "raw_concept_qname": "us-gaap:Revenues"},)
    cells = tuple(
        {
            "fiscal_time_series_cell_id": f"cell-{number}",
            "fiscal_time_series_row_id": "row",
            "fiscal_time_series_column_id": "fy-2025" if number == 0 else "outside-window",
            "value_lineage": {"number": number, "payload": "x" * 1000},
        }
        for number in range(65)
    )
    files = {}
    for name, records in (("columns", columns), ("rows", rows), ("cells", cells)):
        relative = f"TEST/LATEST_REPORTED/{name}.parquet"
        files[name] = {"path": relative, **history._write_records(root / relative, records)}
    manifest = {
        "version": history.HISTORY_VERSION,
        "tables": [{
            "ticker": "TEST",
            "period_class": "FY",
            "view": "LATEST_REPORTED",
            "scope": {"selection_as_of_date": "2026-10-10"},
            "files": files,
        }],
    }
    (root / "history_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_ordinary_history_cells_are_lazy_single_pass_and_complete(tmp_path: Path) -> None:
    reader = history.HistoryPublicationReader(_publication(tmp_path))
    streamed = reader.stream_cells(ticker="TEST", period_class="FY", view="LATEST_REPORTED")

    assert iter(streamed.cells) is streamed.cells
    assert streamed.columns[0]["fiscal_year"] == 2025
    assert next(streamed.cells)["fiscal_time_series_cell_id"] == "cell-0"
    assert [row["fiscal_time_series_cell_id"] for row in streamed.cells] == [
        f"cell-{number}" for number in range(1, 65)
    ]
    assert list(streamed.cells) == []


@pytest.mark.parametrize("failure", ["hash", "count", "schema", "malformed"])
def test_stream_fails_closed_for_invalid_out_of_scope_cells(
    tmp_path: Path, failure: str
) -> None:
    root = _publication(tmp_path)
    manifest_path = root / "history_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    info = manifest["tables"][0]["files"]["cells"]
    if failure == "hash":
        info["sha256"] = "0" * 64
    elif failure == "count":
        info["count"] += 1
    elif failure == "schema":
        info["json_fields"].append("field-not-in-schema")
    else:
        import polars as pl

        path = root / info["path"]
        pl.read_parquet(path).with_columns(
            pl.when(pl.col("fiscal_time_series_column_id") == "outside-window")
            .then(pl.lit("{invalid-json"))
            .otherwise(pl.col("value_lineage"))
            .alias("value_lineage")
        ).write_parquet(path)
        info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    reader = history.HistoryPublicationReader(root)

    if failure == "hash":
        with pytest.raises(ValueError, match="integrity"):
            reader.stream_cells(ticker="TEST", period_class="FY", view="LATEST_REPORTED")
    else:
        streamed = reader.stream_cells(ticker="TEST", period_class="FY", view="LATEST_REPORTED")
        with pytest.raises(ValueError, match="count|schema|Expecting"):
            list(streamed.cells)


class _TrackedCell(dict):
    live = 0
    maximum = 0
    created = 0

    def __init__(self, source: dict) -> None:
        super().__init__(source)
        type(self).live += 1
        type(self).created += 1
        type(self).maximum = max(type(self).maximum, type(self).live)

    def __del__(self) -> None:
        type(self).live -= 1


def _fixture_tables(periods: tuple[str, ...]) -> dict[tuple[str, str], SimpleNamespace]:
    tables = {}
    for view in ("AS_FILED", "LATEST_REPORTED"):
        for period in periods:
            columns = tuple({
                "fiscal_time_series_column_id": f"{period}-{year}",
                "fiscal_year": year,
                "fiscal_quarter": 4,
                "period_class": period,
                "column_status": "AVAILABLE",
                "actual_start_date": None if period == "INSTANT" else f"{year - 1}-01-01",
                "actual_end_date": None if period == "INSTANT" else f"{year}-12-31",
                "actual_instant_date": f"{year}-12-31" if period == "INSTANT" else None,
                "fiscal_label": f"{period}-{year}",
            } for year in (2023, 2024, 2025))
            concept = "us-gaap:Assets" if period == "INSTANT" else "us-gaap:Revenues"
            rows = (
                {"fiscal_time_series_row_id": f"{period}-total", "raw_concept_qname": concept,
                 "mapping_review_required": False, "row_identity": ["JOIN"]},
                {"fiscal_time_series_row_id": f"{period}-null", "raw_concept_qname": "test:NullCandidate",
                 "mapping_review_required": True, "row_identity": ["REVIEW"]},
            )
            cells = []
            for year in (2023, 2024, 2025):
                for suffix, value in (("total", str(year * 10)), ("null", None)):
                    row_id = f"{period}-{suffix}"
                    lineage = None if suffix == "null" else {
                        "selected_source_fact_id": f"fact-{view}-{period}-{year}",
                        "source_filing_id": f"filing-{year}",
                        "accession": f"accession-{year}",
                        "selection_view": view,
                        "selection_as_of_date": "2026-10-10",
                        "context_start_date": None if period == "INSTANT" else f"{year - 1}-01-01",
                        "context_end_date": None if period == "INSTANT" else f"{year}-12-31",
                        "context_instant_date": f"{year}-12-31" if period == "INSTANT" else None,
                        "source_type": "REPORTED",
                        "raw_concept_id": f"concept-{period}",
                        "raw_concept_qname": concept,
                        "raw_concept_is_standard": True,
                        "raw_concept_taxonomy_family": "us-gaap",
                        "raw_concept_data_type": "xbrli:monetaryItemType",
                        "company_canonical_concept_id": f"canonical-{period}",
                        "canonical_dimension_signature": [],
                        "raw_dimension_signature": [],
                        "unit_numerator_measures": '["iso4217:USD"]',
                        "unit_denominator_measures": "[]",
                        "mapping_review_required": False,
                        "value_numeric": value,
                    }
                    cells.append({
                        "fiscal_time_series_cell_id": f"cell-{view}-{period}-{suffix}-{year}",
                        "fiscal_time_series_row_id": row_id,
                        "fiscal_time_series_column_id": f"{period}-{year}",
                        "value_status": "UNAVAILABLE" if value is None else "REPORTED",
                        "value_numeric": value,
                        "value_lineage": lineage,
                        "binding": {"primary_statement_evidence": [{
                            "source_filing_id": f"filing-{year}", "role_uri": "role:primary",
                            "statement_types": ["BS" if period == "INSTANT" else "IS"],
                            "rich_payload": ["evidence", {"year": year}],
                        }]},
                        "comparability_status": "REVIEW_REQUIRED" if value is None else "COMPARABLE",
                        "resolution_reason": "NULL_CANDIDATE" if value is None else None,
                    })
            tables[(view, period)] = SimpleNamespace(
                columns=columns,
                rows=rows,
                cells=tuple(cells),
                scope={"selection_as_of_date": "2026-10-10", "cik": "0000000001"},
            )
    return tables


def _reader(tables: dict, root: Path, *, streaming: bool) -> SimpleNamespace:
    manifest = {"tables": [
        {"ticker": "TEST", "period_class": period, "view": view}
        for view, period in tables
    ]}
    reader = SimpleNamespace(root=root, manifest=manifest)
    reader.load = lambda **kw: copy.deepcopy(tables[(kw["view"], kw["period_class"])])
    if streaming:
        def stream_cells(**kw) -> SimpleNamespace:
            panel = tables[(kw["view"], kw["period_class"])]

            def records() -> Iterator[dict]:
                for row in panel.cells:
                    yield _TrackedCell(copy.deepcopy(row))

            return SimpleNamespace(
                columns=copy.deepcopy(panel.columns),
                rows=copy.deepcopy(panel.rows),
                cells=records(),
                scope=copy.deepcopy(panel.scope),
            )

        reader.stream_cells = stream_cells
    return reader


def _logical_bundle(root: Path) -> dict:
    client = analysis.AnalysisClient(root)
    result = {}
    for view, view_info in client.manifest["companies"]["TEST"]["views"].items():
        result[view] = {
            name: client._records("TEST", view, name)
            for name in view_info["files"]
        }
    manifest = copy.deepcopy(client.manifest)
    manifest.pop("publication_id")
    result["manifest"] = manifest
    return result


@pytest.mark.parametrize(
    ("period_mode", "periods", "explicit", "include_balances", "quarter_evidence"),
    [
        ("ANNUAL", ("FY", "INSTANT"), True, True, False),
        ("QUARTERLY", ("FY", "QTD_3M", "INSTANT"), False, False, True),
    ],
)
def test_prepare_analysis_streams_source_cells_with_legacy_exact_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    period_mode: str,
    periods: tuple[str, ...],
    explicit: bool,
    include_balances: bool,
    quarter_evidence: bool,
) -> None:
    tables = _fixture_tables(periods)
    publication = tmp_path / "history"
    publication.mkdir()
    (publication / "history_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(analysis, "_raw_material", lambda *_: ({}, []))
    profile = [
        {"row_id": "revenue", "label": "Revenue", "section": "IS", "period_class": "FY" if period_mode == "ANNUAL" else "QTD_3M",
         "concepts": ["us-gaap:Revenues"], "required": True},
        {"row_id": "assets", "label": "Assets", "section": "BS", "period_class": "INSTANT",
         "concepts": ["us-gaap:Assets"], "required": True},
    ]
    common = {
        "publication": publication,
        "tickers": ("TEST",),
        "configuration": {"TEST": {"core_rows": profile}},
        "fiscal_years": 2,
        "period_mode": period_mode,
        "include_year_end_balances": include_balances,
        "include_quarter_source_evidence": quarter_evidence,
    }
    if explicit:
        common.update(fiscal_start=2024, fiscal_end=2025)

    monkeypatch.setattr(
        analysis,
        "open_history_publication",
        lambda _: _reader(tables, publication, streaming=False),
    )
    legacy = analysis.prepare_analysis(destination=tmp_path / "legacy", **common)

    _TrackedCell.live = _TrackedCell.maximum = _TrackedCell.created = 0
    monkeypatch.setattr(
        analysis,
        "open_history_publication",
        lambda _: _reader(tables, publication, streaming=True),
    )
    streamed = analysis.prepare_analysis(destination=tmp_path / "streamed", **common)
    gc.collect()

    assert _logical_bundle(streamed) == _logical_bundle(legacy)
    expected_visits = 24 if period_mode == "ANNUAL" else 30
    assert _TrackedCell.created == expected_visits
    assert _TrackedCell.maximum <= 2
    assert _TrackedCell.live == 0
