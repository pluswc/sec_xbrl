"""Fail-closed reuse for a strictly later, single-company history append."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.canonical import CompanyCanonicalizer, MappingTables
from sec_xbrl.longitudinal.corpus_release import CorpusRelease, CorpusSnapshot
from sec_xbrl.longitudinal.materialization import (
    Layer2PublicationReader,
    OperationalLayer2Publisher,
    VerifiedLayer2Publication,
    _read_publication_manifest,
    _run_from_manifest,
)


class HistoryAppendReuseError(ValueError):
    """Raised when a declared previous publication cannot prove safe reuse."""


@dataclass(slots=True)
class HistoryAppendReusePlan:
    layer2_run: Any
    previous_history: Path
    previous_reported: Path
    previous_roots: Mapping[str, Path]
    previous_manifest_sha256: Mapping[str, str]
    old_snapshot_ids: frozenset[str]
    new_snapshots: tuple[CorpusSnapshot, ...]
    new_filing_count: int
    mappings_by_cik: Mapping[str, MappingTables]
    filing_by_id: Mapping[str, Mapping[str, Any]]
    ledger_inputs_by_cik: Mapping[str, tuple[Mapping[str, Any], ...]]
    dirty_period_classes: frozenset[str]
    producer_code_identity: str

    @property
    def reused_filings(self) -> int:
        return len(self.old_snapshot_ids)


def prepare_history_append(
    *, previous_history: Path, release: CorpusRelease, views: tuple[str, ...],
    migration_evidence: Path | None = None,
) -> HistoryAppendReusePlan:
    """Prove an immutable input prefix and prepare one shared canonical map."""
    previous_history = Path(previous_history).absolute()
    manifest_path = previous_history / "history_manifest.json"
    try:
        history_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryAppendReuseError("previous history manifest is unavailable") from exc
    if tuple(history_manifest.get("views") or ()) != views:
        raise HistoryAppendReuseError("previous history views differ")
    previous_reported = Path(
        history_manifest.get("supersedes_publication") or previous_history
    ).absolute()
    reported_manifest = json.loads(
        (previous_reported / "history_manifest.json").read_text(encoding="utf-8")
    )
    roots_value = reported_manifest.get("operational_roots")
    if not isinstance(roots_value, dict) or set(roots_value) != {"t1", "t2", "t3", "t4"}:
        raise HistoryAppendReuseError("previous history has no complete operational roots")
    roots = {name: Path(value).absolute() for name, value in roots_value.items()}
    manifests = {
        name: path / "layer2_run_manifest.json" for name, path in roots.items()
    }
    old_run = _run_from_manifest(_read_publication_manifest(manifests["t1"]))
    current_run = release.layer2_run
    reported_sha = _sha256(previous_reported / "history_manifest.json")
    if (
        history_manifest.get("input_fingerprint") != old_run.fingerprint
        or reported_manifest.get("input_fingerprint") != old_run.fingerprint
        or history_manifest.get("source_manifest_sha256") != reported_sha
        or history_manifest.get("plan") != reported_manifest.get("plan")
        or history_manifest.get("views") != reported_manifest.get("views")
    ):
        raise HistoryAppendReuseError("previous reported and consumer publications disagree")
    if len({item.cik for item in current_run.inputs}) != 1:
        raise HistoryAppendReuseError("append reuse supports exactly one company")
    declared_ciks = {
        str(company.get("cik")) for company in reported_manifest.get("plan", {}).get("companies", ())
    }
    if declared_ciks != {current_run.inputs[0].cik}:
        raise HistoryAppendReuseError("previous history company scope differs")
    if old_run.contract_version != current_run.contract_version or old_run.rules != current_run.rules:
        raise HistoryAppendReuseError("Layer 2 contract or rules changed")
    old_inputs = tuple(old_run.inputs)
    current_inputs = tuple(current_run.inputs)
    if len(current_inputs) != len(old_inputs) + 1 or current_inputs[: len(old_inputs)] != old_inputs:
        raise HistoryAppendReuseError("current inputs are not an exact one-filing suffix append")
    old_last = _input_order(old_inputs[-1])
    new_input = current_inputs[-1]
    if _input_order(new_input) <= old_last:
        raise HistoryAppendReuseError("new filing is not strictly later than the previous prefix")
    for manifest in manifests.values():
        run = _run_from_manifest(_read_publication_manifest(manifest))
        if run != old_run:
            raise HistoryAppendReuseError("previous T1-T4 declarations differ")
    mappings = _canonical_mappings(release)
    previous_t1 = Layer2PublicationReader().load(roots["t1"])
    _verify_mapping_prefix(previous_t1, mappings, old_inputs)
    del previous_t1
    filing_by_id, ledger_inputs_by_cik = _small_release_state(release)
    old_snapshot_ids = frozenset(item.snapshot_id for item in old_inputs)
    new_snapshots = tuple(
        snapshot for snapshot in release.snapshots if snapshot.input.snapshot_id not in old_snapshot_ids
    )
    if tuple(snapshot.input for snapshot in new_snapshots) != (new_input,):
        raise HistoryAppendReuseError("new snapshot does not match the declared suffix")
    dirty = _dirty_period_classes(new_snapshots)
    producer_code_identity = _producer_code_identity()
    _verify_reuse_evidence(
        migration_evidence=migration_evidence,
        previous_history=previous_history,
        previous_manifest=manifest_path,
        roots=roots,
        manifests=manifests,
        producer_code_identity=producer_code_identity,
    )
    return HistoryAppendReusePlan(
        layer2_run=current_run,
        previous_history=previous_history,
        previous_reported=previous_reported,
        previous_roots=roots,
        previous_manifest_sha256={
            name: _sha256(manifest) for name, manifest in manifests.items()
        },
        old_snapshot_ids=old_snapshot_ids,
        new_snapshots=new_snapshots,
        new_filing_count=len(new_snapshots),
        mappings_by_cik=mappings,
        filing_by_id=filing_by_id,
        ledger_inputs_by_cik=ledger_inputs_by_cik,
        dirty_period_classes=frozenset(dirty),
        producer_code_identity=producer_code_identity,
    )


def publish_append_roots(
    *, plan: HistoryAppendReusePlan, output_root: Path
) -> tuple[dict[str, Path], str]:
    """Publish a new full declaration while constructing only suffix T1/T2/T4 rows."""
    from sec_xbrl.longitudinal.accession_version_ledger import (
        AccessionVersionLedgerPipeline,
        _ledger_rows,
    )
    from sec_xbrl.longitudinal.period_observation import PeriodObservationMaterializer
    from sec_xbrl.longitudinal.relationship_index import _edge_row
    from sec_xbrl.longitudinal.versioned_observation_panel import _panel_row

    run = plan.layer2_run
    new_accessions = {snapshot.input.accession for snapshot in plan.new_snapshots}
    mapping = None
    rows: Sequence[Mapping[str, Any]] = ()
    snapshot = None
    result = None
    filing = None
    concept_map = None
    axis_map = None
    member_map = None
    concepts: Sequence[Mapping[str, Any]] = ()
    roles: Mapping[str, Mapping[str, Any]] = {}
    relationship = None
    roots = {name: Path(output_root) / name / run.run_version for name in ("t1", "t2", "t3", "t4")}
    reader = Layer2PublicationReader()
    old_t1 = reader.load(plan.previous_roots["t1"])
    t1: dict[str, list[dict[str, Any]]] = {
        name: list(old_t1.records(name)) for name in old_t1.datasets
    }
    old_observations = tuple(t1.get("reported_period_observation", ()))
    for dataset in ("company_concept_map", "company_axis_map", "company_member_map"):
        t1[dataset] = []
    for mapping in plan.mappings_by_cik.values():
        for dataset, rows in (
            ("company_concept_map", mapping.company_concept_map),
            ("company_axis_map", mapping.company_axis_map),
            ("company_member_map", mapping.company_member_map),
        ):
            t1[dataset].extend(dict(row) for row in rows)
    materializer = PeriodObservationMaterializer()
    for snapshot in plan.new_snapshots:
        filing = _one_filing(snapshot)
        result = materializer.materialize(
            filing=filing,
            concepts=snapshot.records("concept"),
            contexts=snapshot.records("context"),
            units=snapshot.records("unit"),
            facts=snapshot.records("fact"),
            dimension_facts=snapshot.records("dimension_fact"),
            q4_policy_by_fact_id=None,
            source_snapshot_id=snapshot.input.snapshot_id,
        )
        mapping = plan.mappings_by_cik[snapshot.input.cik]
        concept_map = _mapping_index(mapping.company_concept_map)
        axis_map = _mapping_index(mapping.company_axis_map)
        member_map = _mapping_index(mapping.company_member_map)
        t1.setdefault("reported_period_observation", []).extend(
            _panel_row(
                {
                    **row,
                    "source_is_amendment": bool(filing.get("is_amendment"))
                    or str(filing.get("form") or "").endswith("/A"),
                    "source_amends_accession": filing.get("amends_accession"),
                },
                concept_map,
                axis_map,
                member_map,
            )
            for row in result.observations
        )
        if result.exclusions:
            t1.setdefault("period_observation_exclusion", []).extend(result.exclusions)
    OperationalLayer2Publisher(Path(output_root) / "t1").publish(
        run, {name: tuple(rows) for name, rows in t1.items() if rows}
    )
    del old_t1, t1

    old_t2 = reader.load(plan.previous_roots["t2"])
    old_edges = list(old_t2.records("filing_relationship_edge"))
    new_edges: list[dict[str, Any]] = []
    for snapshot in plan.new_snapshots:
        filing = _one_filing(snapshot)
        filing_id = str(filing["filing_id"])
        concepts = snapshot.records("concept")
        roles = {str(row.get("role_id") or ""): row for row in snapshot.records("role")}
        concept_map = _mapping_index(plan.mappings_by_cik[snapshot.input.cik].company_concept_map)
        for relationship in snapshot.records("relationship"):
            new_edges.append(
                _edge_row(
                    cik=snapshot.input.cik,
                    relationship=relationship,
                    filing_by_id={filing_id: filing},
                    roles_by_filing={filing_id: roles},
                    concepts_by_id={(filing_id, str(row["raw_concept_id"])): row for row in concepts},
                    concept_map=concept_map,
                    snapshot_id_by_filing={filing_id: snapshot.input.snapshot_id},
                )
            )
    OperationalLayer2Publisher(Path(output_root) / "t2").publish(
        run, {"filing_relationship_edge": tuple(old_edges + new_edges)}
    )
    del old_t2, old_edges
    # Canonical mappings and Raw suffix rows are no longer needed once T1/T2
    # are immutable. Do not retain them beside current T1/T2 and the old T3.
    plan.mappings_by_cik = {}
    plan.new_snapshots = ()
    mapping = None
    rows = ()
    snapshot = None
    result = None
    filing = None
    concept_map = None
    axis_map = None
    member_map = None
    concepts = ()
    roles = {}
    relationship = None

    t1_pub = reader.load(roots["t1"])
    current_observations = t1_pub.records("reported_period_observation")
    if not _rows_equal_with_schema_union(
        old_observations, current_observations[: len(old_observations)]
    ):
        raise HistoryAppendReuseError("published T1 observation prefix changed")
    del old_observations, current_observations
    t2_pub = reader.load(roots["t2"])
    old_t3 = reader.load(plan.previous_roots["t3"])
    try:
        t3_rows = _merge_graph(
            old_t3,
            t1_pub,
            t2_pub,
            new_edges,
        )
        OperationalLayer2Publisher(Path(output_root) / "t3").publish(run, t3_rows)
        del t3_rows
        t3_mode = "STAGE_PRESERVING_MERGE"
    except (HistoryAppendReuseError, ValueError) as exc:
        from sec_xbrl.longitudinal.exploration_graph import ExplorationGraphPipeline

        print(
            json.dumps({"stage": "T3_APPEND_FULL_FALLBACK", "reason": str(exc)}),
            flush=True,
        )
        ExplorationGraphPipeline().publish(t1_pub, t2_pub, output_root=Path(output_root) / "t3")
        t3_mode = "FULL_FALLBACK"
    finally:
        del old_t3
    del t1_pub, t2_pub, new_edges

    old_t4 = reader.load(plan.previous_roots["t4"])
    old_ledger = list(old_t4.records("accession_version_ledger"))
    new_ledger = [
        row
        for cik, inputs in plan.ledger_inputs_by_cik.items()
        for row in _ledger_rows(cik, inputs, selected_accessions=new_accessions)
    ]
    OperationalLayer2Publisher(Path(output_root) / "t4").publish(
        run, {AccessionVersionLedgerPipeline.dataset: tuple(old_ledger + new_ledger)}
    )
    del old_t4, old_ledger
    return roots, t3_mode


def reuse_manifest_payload(plan: HistoryAppendReusePlan) -> dict[str, Any]:
    """Return provenance for manifests and the external append receipt."""
    return {
        "mode": "STRICTLY_LATER_SINGLE_CIK_APPEND_V1",
        "previous_history": str(plan.previous_history),
        "previous_reported": str(plan.previous_reported),
        "reused_filings": plan.reused_filings,
        "new_filings": plan.new_filing_count,
        "dirty_period_classes": sorted(plan.dirty_period_classes),
        "producer_code_identity": plan.producer_code_identity,
        "previous_manifests": {
            name: digest
            for name, digest in sorted(plan.previous_manifest_sha256.items())
        },
    }


def history_policy_changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Compare serving policy while allowing the declared filing suffix itself."""
    def normalized(value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        result["companies"] = [
            {key: item for key, item in company.items() if key != "filings"}
            for company in value.get("companies", ())
        ]
        return result

    return normalized(previous) != normalized(current)


def write_reuse_receipt(output_root: Path, payload: Mapping[str, Any]) -> Path:
    """Bind the completed publication for the next append without changing it."""
    output_root = Path(output_root).absolute()
    current_history = output_root / "panels"
    roots = {name: output_root / name / output_root.name for name in ("t1", "t2", "t3", "t4")}
    receipt = {
        **payload,
        "version": "history-append-reuse-receipt-v1",
        "status": "PASS",
        "current_history": str(current_history),
        "current_history_manifest_sha256": _sha256(current_history / "history_manifest.json"),
        "current_operational_manifest_sha256": {
            name: _sha256(root / "layer2_run_manifest.json")
            for name, root in sorted(roots.items())
        },
        "current_operational_content_sha256": {
            name: _root_content_pins(root) for name, root in sorted(roots.items())
        },
    }
    path = Path(output_root) / "history_append_reuse_receipt.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _canonical_mappings(release: CorpusRelease) -> dict[str, MappingTables]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for snapshot in release.snapshots:
        for table in ("filing", "concept", "dimension_fact", "relationship", "role"):
            grouped[snapshot.input.cik][table].extend(snapshot.records(table))
    return {
        cik: CompanyCanonicalizer().build(
            filings=tables["filing"],
            concepts=tables["concept"],
            dimension_facts=tables["dimension_fact"],
            relationships=tables["relationship"],
            roles=tables["role"],
        )
        for cik, tables in grouped.items()
    }


def _small_release_state(
    release: CorpusRelease,
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[dict[str, Any], ...]]]:
    """Retain only filing and amendment inputs after Raw prefix proof completes."""
    from sec_xbrl.longitudinal.accession_version_ledger import _amendment_evidence

    filing_by_id: dict[str, dict[str, Any]] = {}
    ledger: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in release.snapshots:
        filing = _one_filing(snapshot)
        filing_by_id[str(filing["filing_id"])] = filing
        ledger[snapshot.input.cik].append(
            {
                "filing": filing,
                "snapshot_id": snapshot.input.snapshot_id,
                "amendment_evidence": _amendment_evidence(
                    snapshot.records("concept"), snapshot.records("fact")
                ),
            }
        )
    return filing_by_id, {cik: tuple(rows) for cik, rows in ledger.items()}


def _verify_mapping_prefix(
    previous: VerifiedLayer2Publication,
    mappings: Mapping[str, MappingTables],
    old_inputs: Sequence[Any],
) -> None:
    old_filing_ids = {
        str(row.get("source_filing_id") or row.get("filing_id") or "")
        for dataset in ("company_concept_map", "company_axis_map", "company_member_map", "structural_change")
        for row in previous.records(dataset)
    }
    old_filing_ids.discard("")
    for dataset in ("company_concept_map", "company_axis_map", "company_member_map"):
        expected = list(previous.records(dataset))
        actual = [
            dict(row)
            for mapping in mappings.values()
            for row in getattr(mapping, dataset)
            if str(row.get("source_filing_id") or row.get("filing_id") or "") in old_filing_ids
        ]
        if not _rows_equal_with_schema_union(expected, actual):
            raise HistoryAppendReuseError(f"previous {dataset} prefix changed")
    if len(old_inputs) == 0:
        raise HistoryAppendReuseError("previous input prefix is empty")


def _rows_equal_with_schema_union(left: Sequence[Any], right: Sequence[Any]) -> bool:
    if len(left) != len(right):
        return False
    return all(_value_equal_with_schema_union(a, b) for a, b in zip(left, right, strict=True))


def _value_equal_with_schema_union(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = set(left) | set(right)
        return all(
            _value_equal_with_schema_union(left.get(key), right.get(key)) for key in keys
        )
    # Polars returns Parquet list values as lists while the in-memory producer
    # uses tuples. This is the only cross-type normalization at this boundary.
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _value_equal_with_schema_union(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _verify_reuse_evidence(
    *,
    migration_evidence: Path | None,
    previous_history: Path,
    previous_manifest: Path,
    roots: Mapping[str, Path],
    manifests: Mapping[str, Path],
    producer_code_identity: str,
) -> None:
    receipt_path = previous_history.parent / "history_append_reuse_receipt.json"
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HistoryAppendReuseError("previous append receipt is unavailable") from exc
        expected_receipt = {
            "version": "history-append-reuse-receipt-v1",
            "status": "PASS",
            "current_history": str(previous_history),
            "current_history_manifest_sha256": _sha256(previous_manifest),
            "current_operational_manifest_sha256": {
                name: _sha256(manifest)
                for name, manifest in sorted(manifests.items())
            },
            "current_operational_content_sha256": {
                name: _root_content_pins(root)
                for name, root in sorted(roots.items())
            },
            "producer_code_identity": producer_code_identity,
        }
        if any(receipt.get(key) != value for key, value in expected_receipt.items()):
            raise HistoryAppendReuseError("previous append receipt does not bind the current producer")
        return
    if migration_evidence is None:
        raise HistoryAppendReuseError("legacy append requires explicit migration evidence")
    try:
        evidence = json.loads(Path(migration_evidence).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryAppendReuseError("migration evidence is unavailable") from exc
    expected = {
        "version": "history-append-migration-v1",
        "status": "ROOT_APPROVED",
        "previous_history": str(previous_history),
        "previous_history_manifest_sha256": _sha256(previous_manifest),
        "previous_operational_manifest_sha256": {
            name: _sha256(manifest)
            for name, manifest in sorted(manifests.items())
        },
        "previous_operational_content_sha256": {
            name: _root_content_pins(root)
            for name, root in sorted(roots.items())
        },
        "compatible_producer_code_identity": producer_code_identity,
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise HistoryAppendReuseError("migration evidence does not bind the previous and current producers")


def _producer_code_identity() -> str:
    """Hash all Python producer and policy bytes through the shared identity seam."""
    from sec_xbrl.history_validation import validation_code_identity

    package = Path(__file__).parent
    return validation_code_identity(
        sources=tuple(sorted(package.rglob("*.py"))),
        rules={"history_append_reuse_contract": "strictly-later-single-cik-v1"},
    )


def _root_content_pins(root: Path) -> dict[str, str]:
    """Hash every immutable operational payload without buffering whole files."""
    root = Path(root)
    pins: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path == root / "layer2_run_manifest.json":
            continue
        if path.is_symlink():
            raise HistoryAppendReuseError("operational publication contains a symlink")
        if path.is_file():
            pins[str(path.relative_to(root))] = _sha256(path)
    if not pins:
        raise HistoryAppendReuseError("operational publication has no payload files")
    return pins


def _dirty_period_classes(snapshots: Sequence[CorpusSnapshot]) -> set[str]:
    from sec_xbrl.longitudinal.period_observation import PeriodObservationMaterializer

    dirty: set[str] = set()
    for snapshot in snapshots:
        filing = _one_filing(snapshot)
        result = PeriodObservationMaterializer().materialize(
            filing=filing,
            concepts=snapshot.records("concept"),
            contexts=snapshot.records("context"),
            units=snapshot.records("unit"),
            facts=snapshot.records("fact"),
            dimension_facts=snapshot.records("dimension_fact"),
            q4_policy_by_fact_id=None,
            source_snapshot_id=snapshot.input.snapshot_id,
        )
        dirty.update(
            str(row["period_class"])
            for row in result.observations
            if row.get("comparative_type") == "CURRENT_FOCUS"
        )
        form = str(filing.get("form") or "").removesuffix("/A")
        if form in {"10-Q", "10-K"}:
            dirty.add("QTD_3M")
    if dirty & {"FY", "YTD_6M", "YTD_9M"}:
        dirty.add("QTD_3M")
    return dirty


def _merge_graph(
    previous: VerifiedLayer2Publication,
    current_t1: VerifiedLayer2Publication,
    current_t2: VerifiedLayer2Publication,
    new_edges: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Merge a filing-scoped suffix in the exact full-producer stage order."""
    from sec_xbrl.longitudinal.exploration_graph import _graph_datasets

    old_filing_ids = {
        str(row.get("source_filing_id") or "")
        for row in previous.records("analysis_exploration_node")
        if row.get("source_filing_id")
    }
    new_observations = [
        row
        for row in current_t1.records("reported_period_observation")
        if str(row.get("source_filing_id") or "") not in old_filing_ids
    ]
    maps = {
        kind: {
            (str(row.get("source_filing_id")), str(row.get("source_raw_id"))): row
            for row in current_t1.records(dataset)
        }
        for kind, dataset in (
            ("axis", "company_axis_map"),
            ("member", "company_member_map"),
        )
    }
    previous_nodes = list(previous.records("analysis_exploration_node"))
    previous_edges = list(previous.records("analysis_exploration_edge"))
    new = _graph_datasets(new_observations, list(new_edges), maps)
    old_nodes = previous_nodes
    old_edges = previous_edges
    old_relationship_ids = [
        str(row["source_relationship_edge_id"])
        for row in old_edges
        if row.get("source_relationship_edge_id")
    ]
    current_relationship_ids = [
        str(row["filing_relationship_edge_id"])
        for row in current_t2.records("filing_relationship_edge")
    ]
    if current_relationship_ids[: len(old_relationship_ids)] != old_relationship_ids:
        raise HistoryAppendReuseError("T3 relationship stage is not an exact suffix")
    return _merge_graph_stages(
        old_nodes,
        old_edges,
        list(new["analysis_exploration_node"]),
        list(new["analysis_exploration_edge"]),
        current_t1,
    )


def _merge_graph_stages(
    old_nodes: list[dict[str, Any]],
    old_edges: list[dict[str, Any]],
    new_nodes: list[dict[str, Any]],
    new_edges: list[dict[str, Any]],
    current_t1: VerifiedLayer2Publication,
) -> dict[str, tuple[dict[str, Any], ...]]:
    from sec_xbrl.longitudinal.exploration_graph import (
        _concept_node_id,
        _dimension_node,
        _fact_node,
    )

    maps = {
        kind: {
            (str(row.get("source_filing_id")), str(row.get("source_raw_id"))): row
            for row in current_t1.records(dataset)
        }
        for kind, dataset in (("axis", "company_axis_map"), ("member", "company_member_map"))
    }
    stage1: set[str] = set()
    for row in current_t1.records("reported_period_observation"):
        stage1.add(_concept_node_id(row))
        stage1.add(_fact_node(row)["analysis_exploration_node_id"])
        for axis_raw_id, member_raw_id, *_rest in tuple(row.get("raw_dimension_signature") or ()):
            axis = maps["axis"].get((str(row["source_filing_id"]), str(axis_raw_id)))
            if axis is not None:
                stage1.add(_dimension_node(row, axis, "AXIS")["analysis_exploration_node_id"])
            member = maps["member"].get((str(row["source_filing_id"]), str(member_raw_id))) if member_raw_id else None
            if member is not None:
                stage1.add(_dimension_node(row, member, "MEMBER")["analysis_exploration_node_id"])
    old_stage1 = [row for row in old_nodes if row["analysis_exploration_node_id"] in stage1]
    old_relationship = [row for row in old_nodes if row["analysis_exploration_node_id"] not in stage1]
    new_stage1 = [row for row in new_nodes if row["analysis_exploration_node_id"] in stage1]
    new_relationship = [row for row in new_nodes if row["analysis_exploration_node_id"] not in stage1]
    merged_nodes = old_stage1 + new_stage1 + old_relationship + new_relationship

    def edge_stage(row: Mapping[str, Any]) -> str:
        if row.get("source_relationship_edge_id"):
            return "relationship"
        if row.get("scope_kind") == "TOTAL_FACT_AXIS_LENS":
            return "augmentation"
        return "initial"

    merged_edges = [
        row
        for stage in ("initial", "augmentation", "relationship")
        for rows in (old_edges, new_edges)
        for row in rows
        if edge_stage(row) == stage
    ]
    node_ids = [row["analysis_exploration_node_id"] for row in merged_nodes]
    edge_ids = [row["analysis_exploration_edge_id"] for row in merged_edges]
    if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
        raise HistoryAppendReuseError("T3 append produced colliding identities")
    if any(
        row[endpoint] not in set(node_ids)
        for row in merged_edges
        for endpoint in ("from_node_id", "to_node_id")
    ):
        raise HistoryAppendReuseError("T3 append produced a dangling endpoint")
    return {
        "analysis_exploration_node": tuple(merged_nodes),
        "analysis_exploration_edge": tuple(merged_edges),
    }


def _mapping_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("source_filing_id") or ""), str(row.get("source_raw_id") or "")): dict(row)
        for row in rows
    }


def _one_filing(snapshot: CorpusSnapshot) -> dict[str, Any]:
    rows = snapshot.records("filing")
    if len(rows) != 1:
        raise HistoryAppendReuseError("snapshot must contain one filing")
    return rows[0]


def _input_order(value: Any) -> tuple[str, str, str]:
    return (str(value.filed_date), str(value.accession), str(value.snapshot_id))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
