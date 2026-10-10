"""Verified read-only adapter for governed quarterly screening publications."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
    canonical_json,
    contained_file,
    read_json,
    real_directory,
    regular_file,
    require_cik,
    require_string,
    sha256_file,
)

MANIFEST = "quarterly_screening_metric_manifest.json"
VERSION = "quarterly-screening-metric-manifest-v1"
FILES = {
    "quarter_metric_definitions.json": "definitions",
    "quarter_metric_support.json": "support",
    "quarter_metric_observations.json": "observations",
    "quarter_period_inventory.json": "period_inventory",
}
SOURCE_KINDS = {"REPORTED", "DERIVED_QUARTER", "DERIVED_METRIC", "UNAVAILABLE"}
AVAILABILITY = {"AVAILABLE", "UNAVAILABLE"}


class QuarterlyScreeningMetricReader:
    """Read a frozen producer publication without selecting or calculating values."""

    def __init__(self, root: Path | str, *, manifest_sha256: str | None = None) -> None:
        self.root = real_directory(Path(root), "quarterly screening metric publication")
        manifest_path = regular_file(self.root / MANIFEST, "quarterly screening metric manifest")
        if manifest_sha256 is not None and sha256_file(manifest_path) != manifest_sha256:
            raise ValueError("quarterly metric manifest differs from pinned SHA-256")
        self.manifest = read_json(manifest_path, "quarterly screening metric manifest")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported quarterly screening metric publication")
        loaded: dict[str, list[dict[str, Any]]] = {}
        for filename, name in FILES.items():
            loaded[name] = self._payload(filename)
        self.definitions = loaded["definitions"]
        self.support = loaded["support"]
        self.observations = loaded["observations"]
        self.period_inventory = loaded["period_inventory"]
        self.verify_all()

    @property
    def publication_id(self) -> str:
        return require_string(self.manifest.get("publication_id"), "quarterly publication ID")

    def _payload(self, filename: str) -> list[dict[str, Any]]:
        info = self.manifest.get("files", {}).get(filename)
        if not isinstance(info, dict):
            raise TypeError("quarterly manifest file declaration is missing")
        path = contained_file(self.root, filename, "quarterly payload")
        if sha256_file(path) != info.get("sha256") or path.stat().st_size != info.get("size"):
            raise ValueError("quarterly payload changed")
        payload = read_json(path, "quarterly payload")
        records = payload.get("records") if isinstance(payload, dict) else None
        if (
            not isinstance(records, list)
            or not all(isinstance(row, dict) for row in records)
            or len(records) != info.get("record_count")
        ):
            raise ValueError("quarterly payload record count differs")
        if payload.get("fixture_kind") != self.manifest.get("fixture_kind"):
            raise ValueError("quarterly payload fixture kind differs")
        return records

    def verify_all(self) -> dict[str, Any]:
        if set(self.manifest.get("files", {})) != set(FILES):
            raise ValueError("quarterly payload file set changed")
        actual = {
            path.name
            for path in self.root.iterdir()
            if path.is_file() and path.name != MANIFEST and path.name != "MANIFEST.sha256"
        }
        if actual != set(FILES) or any(path.is_symlink() for path in self.root.iterdir()):
            raise ValueError("quarterly publication file set changed")
        spine = [
            (row.get("calendar_year"), row.get("calendar_quarter"))
            for row in self.manifest.get("global_quarter_spine", [])
        ]
        cutoff = date.fromisoformat(
            require_string(self.manifest.get("financial_as_of"), "financial as-of")
        )
        last_index = cutoff.year * 4 + (cutoff.month - 1) // 3 - 1
        expected_spine = [divmod(last_index - offset, 4) for offset in range(7, -1, -1)]
        expected_spine = [(year, quarter + 1) for year, quarter in expected_spine]
        spine_rows = self.manifest.get("global_quarter_spine", [])
        if (
            len(spine) != 8
            or spine != expected_spine
            or any(type(y) is not int or type(q) is not int for y, q in spine)
            or any(row.get("status") != "COMPLETED_BUCKET" for row in spine_rows)
        ):
            raise ValueError("quarterly publication must declare eight unique completed buckets")
        ciks = self.manifest.get("universe", {}).get("ciks")
        if not isinstance(ciks, list) or len(ciks) != self.manifest.get("universe", {}).get(
            "company_count"
        ):
            raise ValueError("quarterly company membership differs")
        ciks = [require_cik(cik) for cik in ciks]
        membership_hash = hashlib.sha256(("\n".join(ciks) + "\n").encode()).hexdigest()
        if (
            ciks != sorted(set(ciks))
            or membership_hash != self.manifest["universe"].get("company_membership_sha256")
            or membership_hash
            != self.manifest.get("annual_parent", {}).get("company_membership_sha256")
        ):
            raise ValueError("quarterly and annual company membership differ")
        definitions = {row.get("metric_id"): row for row in self.definitions}
        if (
            None in definitions
            or len(definitions) != len(self.definitions)
            or any(
                not str(metric_id).startswith(
                    "ttm_" if row.get("observation_basis") == "TTM" else "quarter_"
                )
                for metric_id, row in definitions.items()
            )
        ):
            raise ValueError("quarterly metric definitions are not unique and prefixed")
        support_keys = [(row.get("cik"), row.get("metric_id")) for row in self.support]
        observation_keys = [
            (
                row.get("cik"),
                row.get("metric_id"),
                row.get("calendar_year"),
                row.get("calendar_quarter"),
            )
            for row in self.observations
        ]
        inventory_keys = [
            (row.get("cik"), row.get("calendar_year"), row.get("calendar_quarter"))
            for row in self.period_inventory
        ]
        if (
            len(support_keys) != len(set(support_keys))
            or len(observation_keys) != len(set(observation_keys))
            or len(inventory_keys) != len(set(inventory_keys))
        ):
            raise ValueError("duplicate quarterly publication grain")
        if set(support_keys) != {(cik, metric) for cik in ciks for metric in definitions}:
            raise ValueError("quarterly support does not cover company/metric grain")
        if set(inventory_keys) != {(cik, year, quarter) for cik in ciks for year, quarter in spine}:
            raise ValueError("quarterly period inventory does not cover the fixed spine")
        if set(observation_keys) != {
            (cik, metric, year, quarter)
            for cik in ciks
            for metric in definitions
            for year, quarter in spine
        }:
            raise ValueError("quarterly observations do not cover metric/company/spine grain")
        self._prepared_identity_records: dict[str, str] = {}
        self._raw_identity_records: dict[tuple[str, ...], tuple[Decimal, str]] = {}
        for row in self.observations:
            self._remember_prepared_identity(row)
        for row in self.observations:
            self._verify_observation(row, definitions)
        self._verify_support(spine)
        self._verify_source_coherence()
        counts = self.manifest.get("counts", {})
        expected = {
            "definitions": len(self.definitions),
            "support": len(self.support),
            "observations": len(self.observations),
            "period_inventory": len(self.period_inventory),
        }
        if counts != expected:
            raise ValueError("quarterly manifest counts differ")
        return {
            "publication_id": self.publication_id,
            "fixture_kind": self.manifest["fixture_kind"],
            "financial_as_of": self.manifest["financial_as_of"],
            **expected,
        }

    def _verify_observation(
        self, row: dict[str, Any], definitions: dict[str, dict[str, Any]]
    ) -> None:
        definition = definitions.get(row.get("metric_id"))
        if (
            definition is None
            or row.get("definition_version") != definition.get("definition_version")
            or row.get("unit") != definition.get("unit")
        ):
            raise ValueError("quarterly observation differs from its definition")
        if (
            row.get("availability_status") not in AVAILABILITY
            or row.get("source_kind") not in SOURCE_KINDS
        ):
            raise ValueError("invalid quarterly observation status")
        available = row["availability_status"] == "AVAILABLE"
        if available != (row.get("value") is not None) or available == bool(row.get("reason")):
            raise ValueError("quarterly availability/value/reason disagree")
        if available:
            try:
                value = Decimal(row["value"])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("quarterly value must be an exact decimal string") from exc
            if not isinstance(row["value"], str) or not value.is_finite():
                raise ValueError("quarterly value must be an exact decimal string")
            required = (
                "period_end",
                "filed_date",
                "report_date",
                "fiscal_year",
                "fiscal_quarter",
            )
            if (
                any(row.get(field) is None for field in required)
                or "period_start" not in row
                or (
                    definition["observation_basis"] != "INSTANT" and row.get("period_start") is None
                )
            ):
                raise ValueError(
                    "available quarterly observation requires actual dates and fiscal labels"
                )
            if definition["observation_basis"] == "INSTANT" and row["period_start"] is not None:
                raise ValueError("quarterly instant observation cannot have a duration start")
            if row.get("selection_as_of_date") != self.manifest.get("financial_as_of"):
                raise ValueError("quarterly observation as-of differs from publication")
            if date.fromisoformat(row["filed_date"]) > date.fromisoformat(
                self.manifest["financial_as_of"]
            ):
                raise ValueError("quarterly observation filing is after cutoff")
            if row.get("selection_view") not in {"AS_FILED", "LATEST_REPORTED"}:
                raise ValueError("quarterly observation selection view is unsupported")
            if not isinstance(row.get("dimensions"), list):
                raise ValueError("quarterly observation dimensions must be explicit")
            if row.get("canonical_metric_id") != row["metric_id"]:
                raise ValueError("quarterly observation canonical metric identity differs")
            if row.get("source_kind") not in definition.get("allowed_source_kinds", []):
                raise ValueError("quarterly observation source kind is not allowed")
            if row.get("period_class") != definition.get("observation_basis"):
                raise ValueError("quarterly observation period class differs from definition")
            if definition.get("observation_basis") == "TTM" and not row.get("basis_version"):
                raise ValueError("available TTM observation requires a basis version")
        if row.get("period_end") is not None:
            if row.get("end_convention") != "EXCLUSIVE":
                raise ValueError("quarterly period end must remain exclusive")
            inclusive = date.fromisoformat(row["period_end"]) - timedelta(days=1)
            expected_quarter = (inclusive.month - 1) // 3 + 1
            if (inclusive.year, expected_quarter) != (
                row.get("calendar_year"),
                row.get("calendar_quarter"),
            ):
                raise ValueError("quarterly bucket differs from inclusive period end")
        if not isinstance(row.get("source_lineage"), dict):
            raise TypeError("quarterly observation lineage is required")
        if available:
            self._verify_available_lineage(row, definition)

    def _verify_available_lineage(self, row: dict[str, Any], definition: dict[str, Any]) -> None:
        """Check declared scope and input dates; never evaluate financial formulas."""
        lineage = row["source_lineage"]
        kind = row["source_kind"]
        inputs = lineage.get("derivation_inputs")
        if not isinstance(inputs, list) or not all(isinstance(x, dict) for x in inputs):
            raise ValueError("quarterly derivation inputs must be an explicit list")
        if kind == "REPORTED":
            if inputs:
                raise ValueError("reported quarterly source cannot contain derivation inputs")
            sources = [lineage]
        elif kind == "DERIVED_QUARTER":
            if len(inputs) != 2:
                raise ValueError("derived quarter requires exactly two cumulative source inputs")
            sources = inputs
        elif definition["observation_basis"] == "TTM":
            if len(inputs) != 4:
                raise ValueError("available TTM requires exactly four eligible QTD inputs")
            sources = inputs
        elif kind == "DERIVED_METRIC":
            self._verify_generic_metric(row, definition)
            return
        else:
            raise ValueError("quarterly derived metric requires a supported input contract")

        source_metric = row["metric_id"]
        if definition["observation_basis"] == "TTM":
            source_metric = require_string(definition.get("input_metric_id"), "TTM input metric")
            input_definition = next(
                (item for item in self.definitions if item["metric_id"] == source_metric), None
            )
            if (
                input_definition is None
                or input_definition.get("observation_basis") != "QTD_3M"
                or input_definition.get("unit") != row["unit"]
                or input_definition.get("unit_kind") != "MONEY"
            ):
                raise ValueError("TTM input metric definition is not an eligible monetary QTD")
        for source in sources:
            self._verify_source_scope(source, row, source_metric)
            if source.get("source_kind") == "DERIVED_QUARTER":
                if definition["observation_basis"] != "TTM":
                    raise ValueError("cumulative quarter inputs must be reported sources")
                source_definition = next(
                    (item for item in self.definitions if item["metric_id"] == source_metric), None
                )
                if source_definition is None:
                    raise ValueError("TTM derived input definition is missing")
                self._verify_observation(source, {source_metric: source_definition})
        self._verify_selected_eligibility(row, lineage, sources)

        if kind == "REPORTED":
            for field in (
                "period_start",
                "period_end",
                "end_convention",
                "filed_date",
                "report_date",
                "basis_version",
            ):
                if lineage.get(field) != row.get(field):
                    raise ValueError(f"reported quarterly source differs from observation {field}")
            if lineage["period_class"] != definition["observation_basis"]:
                raise ValueError("quarterly source period class differs from definition basis")
            if Decimal(lineage["value"]) != Decimal(row["value"]):
                raise ValueError("reported quarterly value differs from selected source")
            if lineage.get("selected_source_ids") != [lineage["source_id"]]:
                raise ValueError("reported quarterly selected source identity differs")
            return

        require_string(lineage.get("derivation_rule_version"), "quarterly derivation rule")
        if lineage["derivation_rule_version"] != definition.get("rule_version"):
            raise ValueError("quarterly derivation rule differs from definition")
        for field in (
            "canonical_mapping_version",
            "dimensions",
            "basis_version",
            "structural_version",
            "recast_version",
        ):
            if any(source.get(field) != sources[0].get(field) for source in sources[1:]):
                raise ValueError(f"quarterly derived input {field} differs")
        if any(source["basis_version"] != row.get("basis_version") for source in sources):
            raise ValueError("quarterly derived input basis differs from observation")
        if kind == "DERIVED_QUARTER":
            later, earlier = sources
            expected_classes = {
                "Q2": ("YTD_6M", "QTD_3M"),
                "Q3": ("YTD_9M", "YTD_6M"),
                "Q4": ("FY", "YTD_9M"),
            }
            if (
                definition["observation_basis"] != "QTD_3M"
                or definition.get("unit_kind") != "MONEY"
                or (later["period_class"], earlier["period_class"])
                != expected_classes.get(row["fiscal_quarter"])
                or later["period_start"] != earlier["period_start"]
                or row["period_start"] != earlier["period_end"]
                or row["period_end"] != later["period_end"]
                or not 75 <= _duration(row) <= 105
            ):
                raise ValueError("derived quarter cumulative periods differ from output scope")
        else:
            require_string(row.get("basis_version"), "available TTM basis version")
            if (
                definition.get("unit_kind") != "MONEY"
                or any(source["period_class"] != "QTD_3M" for source in sources)
                or any(not 75 <= _duration(source) <= 105 for source in sources)
                or any(a["period_end"] != b["period_start"] for a, b in pairwise(sources))
                or row["period_start"] != sources[0]["period_start"]
                or row["period_end"] != sources[-1]["period_end"]
            ):
                raise ValueError("TTM requires four contiguous QTD inputs matching output scope")
            if any(not source.get("basis_version") for source in sources):
                raise ValueError("available TTM inputs require compatible non-null basis versions")
        if row["filed_date"] != max(source["filed_date"] for source in sources):
            raise ValueError("quarterly derived filing date differs from source inputs")
        if row["report_date"] != sources[0 if kind == "DERIVED_QUARTER" else -1]["report_date"]:
            raise ValueError("quarterly derived report date differs from endpoint source")

    def _verify_selected_eligibility(
        self, row: dict[str, Any], lineage: dict[str, Any], sources: list[dict[str, Any]]
    ) -> None:
        kind = row["source_kind"]
        ineligible_fields = (
            "compatibility_failure",
            "ambiguity",
            "ambiguous",
            "mapping_uncertainty",
            "mapping_review_required",
        )
        if kind != "REPORTED":
            # Comparison breaks do not erase an independently known reported value.
            ineligible_fields += (
                "basis_break",
                "structural_break",
                "recast_break",
                "continuity_break",
                "recast_review_required",
            )
        for item in [row, lineage, *sources]:
            if any(item.get(key) for key in ineligible_fields):
                raise ValueError(
                    "available quarterly observation contains incompatible selected inputs"
                )
        if any(
            source.get("quality_blocking") or source.get("quality_status") == "BLOCK"
            for source in sources
        ) and not (
            kind == "REPORTED"
            and (row.get("quality_blocking") or row.get("quality_status") == "BLOCK")
        ):
            raise ValueError("quarterly selected source blocking is not preserved")

    def _verify_generic_metric(self, row: dict[str, Any], definition: dict[str, Any]) -> None:
        """Validate a producer's two prepared inputs without evaluating its formula."""
        contract = definition.get("input_contract")
        roles_by_kind = {
            "SAME_PERIOD_DIFFERENCE": ("CFO", "CAPEX"),
            "SAME_PERIOD_RATIO": ("NUMERATOR", "DENOMINATOR"),
            "ADJACENT_FISCAL_QUARTER_GROWTH": ("CURRENT", "PRIOR"),
            "SAME_FISCAL_QUARTER_YOY_GROWTH": ("CURRENT", "PRIOR"),
        }
        if (
            not isinstance(contract, dict)
            or contract.get("version") != "quarter-derived-input-scope-v1"
        ):
            raise ValueError("quarterly derived metric input contract is unsupported")
        contract_kind = contract.get("kind")
        roles = roles_by_kind.get(contract_kind) if isinstance(contract_kind, str) else None
        if (
            roles is None
            or definition["observation_basis"] not in {"QTD_3M", "INSTANT"}
            or set(contract) - {"version", "kind", "inputs", "denominator_policy", "basis_policy"}
        ):
            raise ValueError("quarterly derived metric kind or period is unsupported")
        output_kind = definition.get("unit_kind")
        permitted_units = {"MONEY": {"USD"}, "PERCENT": {"PERCENT"}, "RATIO": {"RATIO", "1"}}
        if (
            definition.get("unit") not in permitted_units.get(output_kind, set())
            or definition.get("canonical_value_scale") != "1"
            or (output_kind == "RATIO" and contract_kind != "SAME_PERIOD_RATIO")
        ):
            raise ValueError(
                "quarterly derived output unit or canonical value scale is incompatible"
            )
        declarations = contract.get("inputs")
        if (
            not isinstance(declarations, list)
            or len(declarations) != 2
            or not all(
                isinstance(item, dict)
                and set(item) == {"input_role", "metric_id", "value_constraint"}
                for item in declarations
            )
            or tuple(item["input_role"] for item in declarations) != roles
        ):
            raise ValueError("quarterly derived metric input role declarations differ")
        declared_metrics = {
            item["input_role"]: require_string(item["metric_id"], "input metric")
            for item in declarations
        }
        expected_constraints = (
            ("FINITE", "NONNEGATIVE")
            if contract_kind == "SAME_PERIOD_DIFFERENCE"
            else (
                ("NONNEGATIVE", "POSITIVE")
                if contract_kind.endswith("GROWTH") or definition["observation_basis"] == "INSTANT"
                else ("FINITE", "POSITIVE")
            )
        )
        if tuple(item["value_constraint"] for item in declarations) != expected_constraints:
            raise ValueError(
                "quarterly derived metric value constraints differ from approved policy"
            )
        lineage = row["source_lineage"]
        inputs = lineage.get("derivation_inputs")
        if (
            not isinstance(inputs, list)
            or len(inputs) != 2
            or not all(isinstance(item, dict) for item in inputs)
            or tuple(item.get("input_role") for item in inputs) != roles
        ):
            raise ValueError("quarterly derived metric requires exact named prepared inputs")
        if not row["metric_id"].startswith("quarter_") or "basis_version" not in row:
            raise ValueError("quarterly derived metric must declare quarter identity and basis")
        require_string(row.get("observation_id"), "quarterly derived observation identity")
        input_ids = [
            require_string(item.get("observation_id"), "prepared input observation identity")
            for item in inputs
        ]
        if len(set(input_ids)) != 2 or row["observation_id"] in input_ids:
            raise ValueError("quarterly derived metric input identity cycle or duplicate")
        definitions = {item["metric_id"]: item for item in self.definitions}
        for item in inputs:
            metric_id = declared_metrics[item["input_role"]]
            input_definition = definitions.get(metric_id)
            if (
                item.get("metric_id") != metric_id
                or input_definition is None
                or input_definition.get("observation_basis") not in {"QTD_3M", "INSTANT"}
                or input_definition.get("unit_kind") != "MONEY"
                or item.get("unit") != "USD"
                or item.get("source_kind") not in {"REPORTED", "DERIVED_QUARTER"}
                or item.get("availability_status") != "AVAILABLE"
            ):
                raise ValueError("quarterly derived metric input is not an eligible prepared value")
            if (
                "basis_version" not in item
                or "quality_status" not in item
                or type(item.get("quality_blocking")) is not bool
            ):
                raise ValueError("quarterly prepared input must declare basis and quality")
            if item["basis_version"] is not None:
                require_string(item["basis_version"], "prepared input basis version")
            if item["source_kind"] == "DERIVED_QUARTER":
                require_string(item.get("derived_metric_id"), "prepared derived quarter identity")
            # Generic derived inputs cannot recurse into another generic metric or TTM.
            self._verify_observation(item, definitions)
            if item["period_class"] == "QTD_3M" and not 75 <= _duration(item) <= 105:
                raise ValueError("quarterly derived metric input is not an eligible QTD duration")
            self._remember_prepared_identity(item)
            constraint = declarations[roles.index(item["input_role"])]["value_constraint"]
            if (constraint == "NONNEGATIVE" and Decimal(item["value"]) < 0) or (
                constraint == "POSITIVE" and Decimal(item["value"]) <= 0
            ):
                raise ValueError("quarterly derived metric input violates its value constraint")
            _fiscal_coordinate(item)
            for field in ("cik", "dimensions", "selection_view", "selection_as_of_date"):
                if item.get(field) != row.get(field):
                    raise ValueError(f"quarterly derived metric input {field} differs")
        scopes = [scope for item in inputs for scope in _prepared_input_scopes(item)]
        self._verify_selected_eligibility(row, lineage, scopes)
        for field in ("basis_version", "structural_version", "recast_version"):
            for item in inputs:
                if item.get(field) != row.get(field) or any(
                    scope[field] != item.get(field)
                    for scope in _prepared_input_scopes(item)
                    if field in scope
                ):
                    raise ValueError(f"quarterly derived metric input {field} differs")
        if (
            contract.get("basis_policy") != "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
            or lineage.get("compatibility_policy") != contract["basis_policy"]
        ):
            raise ValueError("quarterly derived metric requires declared arithmetic basis policy")
        if (
            not definition.get("rule_version")
            or lineage.get("derivation_rule_version") != definition["rule_version"]
        ):
            raise ValueError("quarterly derivation rule differs from definition")
        current, prior = inputs
        period_fields = (
            "period_start",
            "period_end",
            "end_convention",
            "period_class",
            "fiscal_year",
            "fiscal_quarter",
        )
        if any(current.get(field) != row.get(field) for field in period_fields):
            raise ValueError("quarterly derived metric output differs from current input period")
        if contract_kind.startswith("SAME_PERIOD_"):
            if any(prior.get(field) != row.get(field) for field in period_fields):
                raise ValueError("quarterly derived metric inputs must share the exact period")
        else:
            if (
                definition["observation_basis"] != "QTD_3M"
                or current["metric_id"] != prior["metric_id"]
                or current["definition_version"] != prior["definition_version"]
                or current["unit"] != prior["unit"]
                or prior["period_class"] != "QTD_3M"
            ):
                raise ValueError("quarterly growth inputs require the same QTD metric definition")
            year, quarter = _fiscal_coordinate(current)
            prior_coordinate = _fiscal_coordinate(prior)
            if contract_kind == "ADJACENT_FISCAL_QUARTER_GROWTH":
                expected = (year, quarter - 1) if quarter > 1 else (year - 1, 4)
                if prior_coordinate != expected or prior["period_end"] != current["period_start"]:
                    raise ValueError("QoQ inputs must be adjacent actual issuer fiscal quarters")
            elif (
                prior_coordinate != (year - 1, quarter)
                or prior["period_end"] > current["period_start"]
            ):
                raise ValueError(
                    "YoY predecessor must be the prior issuer fiscal year same quarter"
                )
            if _company_binding(current) != _company_binding(prior):
                raise ValueError("quarterly growth inputs have different company semantic bindings")
        if contract_kind == "SAME_PERIOD_DIFFERENCE":
            if (
                definition["observation_basis"] != "QTD_3M"
                or definition.get("unit_kind") != "MONEY"
                or row["unit"] != "USD"
                or contract.get("denominator_policy") != "NOT_APPLICABLE"
            ):
                raise ValueError("quarterly difference requires monetary QTD output")
        else:
            if (
                definition.get("unit_kind") not in {"PERCENT", "RATIO"}
                or contract.get("denominator_policy") != "STRICTLY_POSITIVE"
                or Decimal(prior["value"]) <= 0
            ):
                raise ValueError(
                    "quarterly ratio or growth requires a strictly positive denominator"
                )
        if row["filed_date"] != max(item["filed_date"] for item in inputs):
            raise ValueError("quarterly derived filing date differs from source inputs")
        if row["report_date"] != current["report_date"]:
            raise ValueError("quarterly derived report date differs from current endpoint")

    def _remember_prepared_identity(self, row: dict[str, Any]) -> None:
        observation_id = row.get("observation_id")
        if observation_id is None:
            return
        observation_id = require_string(observation_id, "prepared observation identity")
        identity = canonical_json({key: value for key, value in row.items() if key != "input_role"})
        previous = self._prepared_identity_records.setdefault(observation_id, identity)
        if previous != identity:
            raise ValueError("quarterly prepared observation identity has contradictory content")

    def _remember_raw_identity(self, source: dict[str, Any]) -> None:
        """One elected immutable Raw fact cannot change beneath prepared identities."""
        if source["source_kind"] != "REPORTED":
            return
        origin_fields = ("source_file_id", "source_file", "source_snapshot_id")
        intrinsic_fields = (
            "cik",
            "accession",
            "source_filing_id",
            "source_fact_id",
            "context_id",
            "raw_concept_qname",
            "raw_concept_namespace_uri",
            "unit",
            "unit_id",
            "dimensions",
            "period_start",
            "period_end",
            "end_convention",
            "context_instant_date",
            "filed_date",
            "report_date",
            *origin_fields,
        )
        # Decimal equality preserves exact numeric meaning without context rounding.
        intrinsic = (
            Decimal(source["value"]),
            canonical_json({field: source.get(field) for field in intrinsic_fields}),
        )
        # Stable IDs qualify the fact; optional filenames remain checked metadata.
        # A fact ID resolves within an immutable snapshot regardless of display paths.
        snapshot = source.get("source_snapshot_id")
        source_file_id = source.get("source_file_id")
        if snapshot is not None:
            require_string(snapshot, "quarterly raw snapshot identity")
            fact_identity = ("snapshot-fact", source["cik"], snapshot, source["source_fact_id"])
        elif source_file_id is not None:
            require_string(source_file_id, "quarterly raw source file identity")
            fact_identity = (
                "file-fact",
                source["cik"],
                source["source_filing_id"],
                source_file_id,
                source["source_fact_id"],
            )
        else:
            fact_identity = (
                "filing-fact",
                source["cik"],
                source["source_filing_id"],
                source["source_fact_id"],
            )
        identities = (("source", source["cik"], source["source_id"]), fact_identity)
        for identity in identities:
            previous = self._raw_identity_records.setdefault(identity, intrinsic)
            if previous != intrinsic:
                raise ValueError("quarterly raw source identity has contradictory content")

    def _verify_source_scope(
        self, source: dict[str, Any], row: dict[str, Any], source_metric: str
    ) -> None:
        for field in (
            "cik",
            "selection_view",
            "selection_as_of_date",
            "unit",
            "canonical_metric_id",
            "canonical_mapping_version",
            "period_end",
            "filed_date",
            "report_date",
            "period_class",
            "end_convention",
        ):
            require_string(source.get(field), f"quarterly source {field}")
        for field in ("cik", "selection_view", "selection_as_of_date"):
            if source[field] != row[field]:
                raise ValueError(f"quarterly source {field} differs from observation scope")
        if source.get("source_kind") == "DERIVED_QUARTER":
            require_string(source.get("derived_metric_id"), "quarterly derived source identity")
        else:
            if source.get("source_kind") != "REPORTED":
                raise ValueError("quarterly selected source kind must be explicit")
            for field in (
                "accession",
                "source_id",
                "source_filing_id",
                "source_fact_id",
                "context_id",
                "raw_concept_qname",
                "raw_concept_namespace_uri",
                "unit_id",
            ):
                require_string(source.get(field), f"quarterly source {field}")
        try:
            source_value = Decimal(source["value"])
        except (InvalidOperation, TypeError, KeyError) as exc:
            raise ValueError("quarterly source value must be an exact decimal string") from exc
        if not isinstance(source["value"], str) or not source_value.is_finite():
            raise ValueError("quarterly source value must be an exact decimal string")
        if "basis_version" not in source:
            raise ValueError("quarterly source basis declaration is missing")
        if source["canonical_metric_id"] != source_metric or source["unit"] != row["unit"]:
            raise ValueError("quarterly source metric or unit differs from observation scope")
        if source.get("dimensions") != row["dimensions"]:
            raise ValueError("quarterly source dimensions differ from observation scope")
        if source["period_class"] == "INSTANT":
            if (
                "period_start" not in source
                or source["period_start"] is not None
                or "duration_days" not in source
                or source["duration_days"] is not None
                or source.get("context_instant_date") != source["period_end"]
            ):
                raise ValueError("quarterly instant source scope must preserve its exact instant")
        else:
            require_string(source.get("period_start"), "quarterly source period_start")
            if type(source.get("duration_days")) is not int or source["duration_days"] != _duration(
                source
            ):
                raise ValueError("quarterly source period duration differs from its dates")
        if source.get("availability_status", "AVAILABLE") != "AVAILABLE":
            raise ValueError("quarterly selected input is unavailable")
        if source.get("reason") or source.get("reasons"):
            raise ValueError("quarterly selected input retains an unavailable reason")
        if source.get("end_convention") != "EXCLUSIVE":
            raise ValueError("quarterly source period end must remain exclusive")
        if date.fromisoformat(source["filed_date"]) > date.fromisoformat(
            self.manifest["financial_as_of"]
        ):
            raise ValueError("quarterly source filing is after cutoff")
        if date.fromisoformat(source["report_date"]) > date.fromisoformat(source["filed_date"]):
            raise ValueError("quarterly source report date is after filing")
        if date.fromisoformat(source["period_end"]) - timedelta(days=1) > date.fromisoformat(
            source["filed_date"]
        ):
            raise ValueError("quarterly source period is after filing")
        self._remember_raw_identity(source)

    def _verify_support(self, spine: list[tuple[int, int]]) -> None:
        for support in self.support:
            rows = [
                row
                for row in self.observations
                if row["cik"] == support["cik"] and row["metric_id"] == support["metric_id"]
            ]
            available = sum(row["availability_status"] == "AVAILABLE" for row in rows)
            source_counts = Counter(row["source_kind"] for row in rows)
            reason_counts = Counter(row["reason"] for row in rows if row.get("reason"))
            expected = {
                "fixed_bucket_count": len(spine),
                "available_bucket_count": available,
                "unavailable_bucket_count": len(spine) - available,
                "source_kind_counts": dict(sorted(source_counts.items())),
                "unavailable_reason_counts": dict(sorted(reason_counts.items())),
            }
            if any(support.get(key) != value for key, value in expected.items()):
                raise ValueError("quarterly support counts differ from observations")

    def _verify_source_coherence(self) -> None:
        accession_metadata: dict[str, tuple[Any, ...]] = {}
        inventory = {
            (row["cik"], row["calendar_year"], row["calendar_quarter"]): row
            for row in self.period_inventory
        }
        for observation in self.observations:
            anchors = _source_anchors(observation["source_lineage"])
            key = (
                observation["cik"],
                observation["calendar_year"],
                observation["calendar_quarter"],
            )
            if inventory[key]["bucket_status"] == "NO_FILING_AS_OF_CUTOFF" and anchors:
                raise ValueError("no-filing bucket contains source filing lineage")
            for row in anchors:
                if row.get("filed_date") is not None and date.fromisoformat(
                    row["filed_date"]
                ) > date.fromisoformat(self.manifest["financial_as_of"]):
                    raise ValueError("quarterly source filing is after cutoff")
                start = row.get("period_start")
                end = row.get("period_end")
                if start is not None and end is not None:
                    duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
                    if row.get("duration_days") != duration:
                        raise ValueError("source period duration differs from its dates")
                    period_class = row.get("period_class")
                    permitted_hold = (
                        observation["availability_status"] == "UNAVAILABLE"
                        and observation.get("reason") == "UNSUPPORTED_FISCAL_QUARTER_DURATION"
                    )
                    if (
                        period_class == "QTD_3M"
                        and not 75 <= duration <= 105
                        and not permitted_hold
                    ):
                        raise ValueError("QTD source duration is outside the governed range")
                    if period_class in {"YTD_9M", "FY"} and not (
                        (225 <= duration <= 315)
                        if period_class == "YTD_9M"
                        else (350 <= duration <= 378)
                    ):
                        raise ValueError("cumulative source duration is outside the governed range")
                    if period_class == "YTD_6M" and not 150 <= duration <= 210:
                        raise ValueError("YTD source duration is outside the governed range")
                accession = str(row["accession"])
                metadata = tuple(
                    row.get(field) for field in ("filed_date", "report_date", "source_filing_id")
                )
                prior = accession_metadata.setdefault(accession, metadata)
                if prior != metadata:
                    raise ValueError("accession source metadata is inconsistent")

    def copy_observations(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.observations)


def _duration(row: dict[str, Any]) -> int:
    return (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days


def _source_anchors(lineage: dict[str, Any]) -> list[dict[str, Any]]:
    """Visit selected value lineage only, never PRE/CAL/candidate evidence dictionaries."""
    anchors = [lineage] if lineage.get("accession") else []
    for source in lineage.get("derivation_inputs", []):
        if isinstance(source, dict):
            anchors.extend(_source_anchors(source.get("source_lineage", source)))
    return anchors


def _prepared_input_scopes(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Only the bounded, already-validated reported/M8 value path is selected evidence."""
    lineage = row["source_lineage"]
    return [
        row,
        lineage,
        *(lineage["derivation_inputs"] if row["source_kind"] == "DERIVED_QUARTER" else []),
    ]


def _fiscal_coordinate(row: dict[str, Any]) -> tuple[int, int]:
    year, quarter = row.get("fiscal_year"), row.get("fiscal_quarter")
    if type(year) is not int or quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        raise ValueError("quarterly derived input requires exact issuer fiscal coordinates")
    return year, int(quarter[1])


def _company_binding(row: dict[str, Any]) -> tuple[str, ...]:
    bindings = {
        require_string(scope["company_canonical_concept_id"], "company canonical concept")
        for scope in _prepared_input_scopes(row)
        if scope.get("company_canonical_concept_id") is not None
    }
    if len(bindings) > 1:
        raise ValueError("quarterly growth input has inconsistent company semantic bindings")
    return tuple(sorted(bindings))
