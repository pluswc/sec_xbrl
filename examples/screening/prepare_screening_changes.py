"""Publish the approved 27 screening comparisons from a ROOT-approved read snapshot.

All arithmetic and accounting gates remain in the existing v1/v2 engines. This
module registers their prepared outputs, never evaluates a screening predicate.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

from examples.screening import financial_comparison_v2 as v2
from examples.screening import prepare_financial_growth as v1
from sec_xbrl.screening.common import digest_value, sha256_file
from sec_xbrl.screening.read_snapshot import ScreeningReadSnapshot, read_pin
from tools.export_screening_read_snapshot import encoded, export_reader

VERSION = "screening-prepared-changes-v1"
MONEY = tuple(prefix + base for prefix in ("", "quarter_", "ttm_") for base in v1.METRICS)
RATIOS = tuple(prefix + base for prefix in ("", "quarter_") for base in
               ("gross_margin", "operating_margin", "net_margin", "fcf_margin", "current_ratio",
                "liabilities_to_equity", "liabilities_to_assets")) + tuple("ttm_" + base for base in
               ("gross_margin", "operating_margin", "net_margin", "fcf_margin"))
SOURCES = MONEY + RATIOS


def definitions(parent: ScreeningReadSnapshot) -> tuple[list[dict], list[dict]]:
    if not hasattr(parent, "metric_definitions") or not hasattr(parent, "quarter_definitions"):
        raise ValueError("prepared changes requires an annual and quarterly catalog")
    source = {row["metric_id"]: row for row in [*parent.metric_definitions, *parent.quarter_definitions]}
    if not set(SOURCES) <= set(source):
        raise ValueError("approved comparison inputs are not all declared in the parent catalog")
    annual, quarter = [], []
    for metric in SOURCES:
        base = source[metric]
        pp = metric in RATIOS
        if base["unit"] != ("PERCENT" if pp else "USD"):
            raise ValueError("comparison source catalog unit differs")
        is_quarter = metric.startswith(("quarter_", "ttm_"))
        label = (base.get("label") or base.get("label_ko")) + (" 전년 동기 변화" if is_quarter and pp else
                    " 전년 변화" if pp else " 전년 동기 대비" if is_quarter else " 전년 대비")
        description = ("현재 비율 − 전년 비율. 비율 자체의 퍼센트포인트 변화이며 성장률의 변화가 아닙니다." if pp else
                       "전년 값이 양수이고 현재 값이 0 이상인 비교 가능한 값의 (현재 / 전년 − 1) × 100입니다. 전환·영 기준·음수 기준은 수치 조건으로 판정하지 않습니다.")
        definition = {"metric_id": metric + ("_yoy_pp" if pp else "_yoy"),
            "definition_version": VERSION, "label": label, "label_ko": label,
            "category": base["category"] if pp else "GROWTH", "source_kind": "DERIVED_METRIC",
            "allowed_source_kinds": ["DERIVED_METRIC"], "unit_kind": "PERCENT",
            "unit": "PERCENTAGE_POINT" if pp else "PERCENT", "canonical_value_scale": "1",
            "period_class": base.get("period_class") or base.get("observation_basis"),
            "observation_basis": base.get("observation_basis") or base.get("period_class"),
            "rule_version": VERSION, "arithmetic_rule_version": VERSION,
            "formula": "current - prior" if pp else "(current / prior - 1) * 100",
            "input_metric_ids": [metric, metric], "description": description,
            "meaning": description, "use": "동일한 발행물에서 준비된 변화값을 조건과 상세 비교에 사용합니다.",
            "comparison_of": metric, "comparison_kind": "PERCENTAGE_POINT" if pp else "YOY",
            "period_relationship": "PRIOR_FISCAL_YEAR" if not is_quarter else "SAME_FISCAL_QUARTER_PRIOR_YEAR",
            "source_definition_version": base["definition_version"],
            "comparison_engine": v2.RULE if pp else v1.RULE}
        (quarter if is_quarter else annual).append(definition)
    return annual, quarter


def compare_rows(rows: list[dict], *, quarterly: bool, parent: ScreeningReadSnapshot,
                 by_id: dict[str, dict], catalog: dict[str, dict]) -> list[dict]:
    """Register existing governed engine cells, including explicit unavailable states."""
    chosen = [row for row in rows if row["metric_id"] in SOURCES]
    fiscal = defaultdict(list)
    for row in chosen:
        fiscal[(row["metric_id"], v2.coordinate(row))].append(row)
    result = []
    for row in chosen:
        if row["metric_id"] in catalog and v1._version(row) != catalog[row["metric_id"]]["definition_version"]:
            raise ValueError("prepared input definition differs from its catalog")
        point = v2.coordinate(row)
        prior = fiscal[(row["metric_id"], point - 4)] if point is not None else []
        ambiguous = point is not None and (len(fiscal[(row["metric_id"], point)]) != 1 or len(prior) > 1)
        previous = prior[0] if len(prior) == 1 else None
        pp = row["metric_id"] in RATIOS
        cell = (v2.compare(row, previous, parent.manifest["financial_as_of"], by_id, catalog, ambiguous)
                if pp else v1.compare_periods(row, previous, "FY" if not quarterly else row["period_class"],
                    parent.manifest["financial_as_of"], by_id, ambiguous=ambiguous))
        value = cell.get("change_pp" if pp else "yoy")
        ids = [v1._id(item) for item in (row, previous) if item is not None]
        keys = ("cik", "ticker", "fiscal_year", "fiscal_quarter", "calendar_year", "calendar_quarter", "period_class",
                "period_start", "period_end", "end_convention", "view", "financial_as_of", "selection_view",
                "selection_as_of_date", "dimensions", "basis_version", "comparability_policy")
        prepared = {key: copy.deepcopy(row[key]) for key in keys if key in row}
        prepared.update({"metric_id": row["metric_id"] + ("_yoy_pp" if pp else "_yoy"),
            "definition_version" if quarterly else "metric_definition_version": VERSION,
            "source_kind": "DERIVED_METRIC", "unit": "PERCENTAGE_POINT" if pp else "PERCENT",
            "value": value, "availability_status": "AVAILABLE" if value is not None else "UNAVAILABLE",
            "quality_status": "PASS" if value is not None else "UNAVAILABLE", "quality_blocking": False,
            "unavailable_reason": None if value is not None else cell.get("reason") or cell["status"],
            "comparison_status": cell["status"], "comparison_evidence": cell,
            "formula": "current - prior" if pp else "(current / prior - 1) * 100",
            "arithmetic_rule_version": VERSION, "input_metric_ids": [row["metric_id"], row["metric_id"]],
            "input_observation_ids": ids, "source_filings": copy.deepcopy(row.get("source_filings", [])),
            "trace": {"comparison": cell, "input_observation_ids": ids, "rule_version": VERSION},
            "source_lineage": {"comparison": cell, "input_observation_ids": ids, "derivation_rule_version": VERSION}})
        prepared["observation_id" if quarterly else "metric_observation_id"] = "prepared-change-" + digest_value(prepared)
        result.append(prepared)
    return result


def support(company: dict, definitions: list[dict], rows: list[dict]) -> list[dict]:
    output = []
    for definition in definitions:
        present = [row for row in rows if row["metric_id"] == definition["metric_id"]]
        available = sum(row["availability_status"] == "AVAILABLE" for row in present)
        reasons = sorted({row["unavailable_reason"] for row in present if row.get("unavailable_reason")})
        output.append({"cik": company["cik"], "ticker": company["ticker"], "metric_id": definition["metric_id"],
            "definition_version": VERSION, "execution_supported": bool(available),
            "support_status": "AVAILABLE" if available else "UNAVAILABLE", "available_periods": available,
            "observed_periods": len(present), "reasons": reasons or ([] if available else ["PERIOD_NOT_PREPARED"])})
    return output


class PreparedReader(ScreeningReadSnapshot):
    """Bounded in-memory company adapter, used only while publishing a new snapshot."""

    def __init__(self, parent: ScreeningReadSnapshot, dataset_id: str) -> None:
        self.parent = parent
        annual, quarter = definitions(parent)
        self.new_definitions = annual, quarter
        for key in ("companies", "metadata", "metric_support", "quarter_support", "quarter_period_inventory",
                    "quarterly", "capabilities", "latest_source_period_guards", "latest_quarter_periods"):
            if hasattr(parent, key):
                setattr(self, key, copy.deepcopy(getattr(parent, key)))
        self.metric_definitions = copy.deepcopy(parent.metric_definitions) + annual
        self.quarter_definitions = copy.deepcopy(parent.quarter_definitions) + quarter
        source_root = Path(__file__).resolve().parents[2]
        producer_sources = {str(path.relative_to(source_root)): sha256_file(path) for path in
            [*sorted((source_root / "src/sec_xbrl").rglob("*.py")), Path(__file__).resolve(),
             source_root / "examples/screening/prepare_financial_growth.py",
             source_root / "examples/screening/financial_comparison_v2.py",
             source_root / "tools/export_screening_read_snapshot.py",
             source_root / "examples/screening/windows-loopback-bridge.cjs"]}
        body = {**copy.deepcopy(parent.manifest), "schema_version": VERSION, "dataset_id": dataset_id,
                "financial_as_of": parent.manifest["financial_as_of"], "fixture_kind": parent.manifest["fixture_kind"],
                "parent_dataset_id": parent.manifest["dataset_id"], "parent_publication_id": parent.publication_id,
                "parent_logical_sha256": parent.logical_sha256, "parent_manifest_sha256": parent._manifest_sha256, "definition_sha256": digest_value([annual, quarter]), "producer_sources": producer_sources,
                "versions": {**parent.manifest.get("versions", {}), "prepared_changes_rule": VERSION},
                **{key: copy.deepcopy(parent.manifest[key]) for key in
                   ("auxiliary_owners", "auxiliary_contexts", "latest_company_periods", "latest_source_period_guards", "global_quarter_spine") if key in parent.manifest}}
        body.pop("publication_id", None)
        self.manifest = {**body, "publication_id": "screening-prepared-changes-" + digest_value(body)[:24]}
        self.publication_id = self.manifest["publication_id"]
        self._manifest_sha256 = digest_value(self.manifest)
        self._loaded_cik = None
        self._views = {}
        self.coverage = {}
        self.bounded_export = True

    def hydrate(self, row: dict, *, quarterly: bool = False) -> dict:
        return copy.deepcopy(row)

    def company(self, cik: str) -> dict:
        return self.parent.company(cik)

    def _load(self, cik: str) -> None:
        if self._loaded_cik == cik:
            return
        views = {name: [self.parent.hydrate(row, quarterly=quarterly) for row in
                      (self.parent.latest_rows if latest else self.parent.rows)(cik=cik, quarterly=quarterly)]
                 for name, quarterly, latest in (("annual", False, False), ("quarter", True, False),
                    ("annual_latest", False, True), ("quarter_latest", True, True))}
        catalog = {row["metric_id"]: {**row, "period_class": row.get("period_class") or row.get("observation_basis")}
                   for row in [*self.parent.metric_definitions, *self.parent.quarter_definitions]}
        by_id = {}
        for rows in views.values():
            for row in rows:
                identity = v1._id(row)
                if identity in by_id and by_id[identity] != row:
                    raise ValueError("one original observation identity has different bytes across views")
                by_id[identity] = row
        for name, rows in views.items():
            additions = compare_rows(rows, quarterly=name.startswith("quarter"), parent=self.parent, by_id=by_id, catalog=catalog)
            views[name] = rows + additions
            if not name.endswith("latest"):
                definitions = self.new_definitions[name == "quarter"]
                destination = self.quarter_support if name == "quarter" else self.metric_support
                # Only add once; export visits each company in original order.
                if not any(row["cik"] == cik and row["metric_id"] in {d["metric_id"] for d in definitions} for row in destination):
                    destination.extend(support(self.company(cik), definitions, additions))
            counts = Counter((row["metric_id"], row["availability_status"], row.get("unavailable_reason")) for row in additions)
            self.coverage[(cik, name)] = [{"cik": cik, "view": name, "metric_id": key[0], "availability_status": key[1],
                                  "reason": key[2], "period_count": count} for key, count in sorted(counts.items(), key=str)]
        self._views, self._loaded_cik = views, cik

    def rows(self, *, quarterly: bool = False, cik: str | None = None, metric_id: str | None = None,
             year: int | None = None, quarter: int | None = None) -> list[dict]:
        return self._select(False, quarterly, cik, metric_id, year, quarter)

    def latest_rows(self, *, quarterly: bool = False, cik: str | None = None, metric_id: str | None = None,
                    year: int | None = None, quarter: int | None = None) -> list[dict]:
        return self._select(True, quarterly, cik, metric_id, year, quarter)

    def _select(self, latest, quarterly, cik, metric_id, year, quarter):
        if cik is None:
            raise ValueError("prepared publisher requires a bounded company selection")
        self._load(cik)
        name = ("quarter" if quarterly else "annual") + ("_latest" if latest else "")
        return copy.deepcopy([row for row in self._views[name] if (metric_id is None or row["metric_id"] == metric_id)
            and (year is None or row["calendar_year" if quarterly else "fiscal_year"] == year)
            and (quarter is None or row["calendar_quarter"] == quarter)])

    def verify_all(self) -> dict:
        for company in self.companies:
            self._load(company["cik"])
        return {**self.parent.verify_all(), "publication_id": self.publication_id, "dataset_id": self.manifest["dataset_id"],
                "auxiliary_manifest_sha256": self._manifest_sha256,
                "annual_definition_count": len(self.metric_definitions),
                "company_count": len(self.companies),
                "quarter_definition_count": len(self.quarter_definitions),
                "quarter_observation_count": self.parent.verify_all().get("quarter_observation_count", 0)
                    + sum(row["observed_periods"] for row in self.quarter_support if row["definition_version"] == VERSION)}


def publish(config_pin: dict, destination: Path) -> Path:
    config = read_pin(config_pin)
    parent = ScreeningReadSnapshot(config["parent_root"], config["parent"])
    reader = PreparedReader(parent, config["dataset_id"])
    source_root = Path(__file__).resolve().parents[2]
    origin = {"kind": VERSION, "config_sha256": config_pin["sha256"], "parent": config["parent"],
              "producer_files": [{"path": str(source_root / name), "sha256": digest}
                                 for name, digest in reader.manifest["producer_sources"].items()]}
    path = export_reader(reader, destination, origin)
    declared_python = {name for name in reader.manifest["producer_sources"] if name.startswith("src/sec_xbrl/")}
    if declared_python != {str(path.relative_to(source_root)) for path in (source_root / "src/sec_xbrl").rglob("*.py")}:
        raise ValueError("producer Python source inventory changed")
    for pin in origin["producer_files"]:
        if sha256_file(Path(pin["path"])) != pin["sha256"]:
            raise ValueError("producer changed during publication")
    ScreeningReadSnapshot(config["parent_root"], config["parent"])
    read_pin(config_pin)
    # The export verification is not a ROOT approval, which must be supplied separately.
    receipt = {"schema_version": "screening-read-export-verification-v1", "verified": True,
               "manifest_sha256": sha256_file(path), "logical_sha256": json.loads(path.read_bytes())["logical_sha256"], "origin": origin}
    # Coverage belongs beside, not inside, the strictly inventoried immutable snapshot.
    destination.with_suffix(".coverage.json").write_bytes(encoded([row for rows in reader.coverage.values() for row in rows]))
    (destination / "verification.json").write_bytes(encoded(receipt))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(publish({"path": args.config, "sha256": args.config_sha256}, args.destination))


if __name__ == "__main__":
    main()
