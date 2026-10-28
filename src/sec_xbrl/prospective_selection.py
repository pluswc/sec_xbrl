"""Proof-bound current-cutoff selection over unchanged accepted source inventories.

This producer does not parse SEC documents, build History, or recalculate money.
Legacy publications remain immutable and strict consumers retain exact cutoffs.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sec_xbrl.history_selection import _pin, resolve_history_selection
from sec_xbrl.screening.common import (
    digest_value,
    read_json,
    require_cik,
    require_ticker,
    safe_new_destination,
    sha256_file,
    write_json,
)

CONFIG_VERSION = "prospective-selection-config-v1"
MANIFEST_VERSION = "prospective-selection-v1"
POLICY_VERSION = "prospective-policy-compatibility-v1"
_ISSUER = object()
# Accounting selection modules only. Explicit ROOT compatibility approval covers
# transitions from legacy manifests without historical source hashes.
_POLICY_MODULES = (
    "analysis.py",
    "history.py",
    "analytics/company_analysis_panel.py",
    "analytics/fiscal_time_series.py",
    "analytics/history_quarters.py",
    "longitudinal/quarterly_policy.py",
    "longitudinal/canonical.py",
    "longitudinal/period_observation.py",
    "longitudinal/reported_selection.py",
    "longitudinal/exploration_graph.py",
    "longitudinal/q4_policy_registry.py",
)


def prospective_policy_sources() -> dict[str, str]:
    """Current relevant policy hashes; never a claim about legacy producer code."""
    root = Path(__file__).parent
    return {f"src/sec_xbrl/{name}": sha256_file(root / name) for name in _POLICY_MODULES}


def analysis_selection_policy(manifest: dict, ticker: str) -> dict[str, Any]:
    """Exact persisted settings a ROOT compatibility assessment must approve."""
    scope = manifest["companies"][ticker]
    return copy.deepcopy(
        {
            "configuration": manifest["configuration"],
            "quality_overlay": manifest.get("quality_overlay"),
            "review_cutoff": scope.get("review_cutoff"),
            "reviewed_q4": manifest.get("reviewed_q4"),
        }
    )


@dataclass(frozen=True)
class ProspectiveSelections:
    declaration: dict[str, str]
    financial_as_of: str
    companies: dict[str, dict[str, Any]]
    controls: dict[str, dict[str, str]]
    storage_reuse: Any = None
    _issuer: Any = None
    _seal: str = ""


def _file_pin(path: Path) -> dict[str, str]:
    return _pin({"path": str(path.absolute()), "sha256": sha256_file(path)})


def _inventory(root: Path) -> dict[str, str]:
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError("unsafe prospective source directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("prospective source aliases are prohibited")
        if path.is_file():
            result[str(path.relative_to(root))] = sha256_file(path)
        elif not path.is_dir():
            raise ValueError("unsupported prospective source entry")
    return result


def prospective_raw_inventory(
    collection_manifest: Path, ticker: str, cik: str
) -> dict[str, dict[str, str]]:
    """Digest-only exact atomic Raw inventory for an explicit ROOT assessment."""
    from sec_xbrl.longitudinal.corpus_release import RAW_TABLES
    from sec_xbrl.source_bindings import _load_collection_scope_v2

    _, _, scope, _, _ = _load_collection_scope_v2(
        collection_manifest, requested=({"ticker": ticker, "cik": cik},)
    )
    result = {}
    expected = {"layer1_manifest.json", *(f"{name}.parquet" for name in RAW_TABLES)}
    for filing in scope:
        files = _inventory(filing.snapshot_root)
        if set(files) != expected:
            raise ValueError("prospective Raw inventory is not atomic and complete")
        manifest = read_json(filing.snapshot_manifest)
        if manifest.get("cik") != cik or manifest.get("accession") != filing.accession:
            raise ValueError("prospective Raw identity differs")
        result[filing.accession] = files
    return result


def _analysis(pin: dict, ticker: str, cik: str, history: dict, mode: str) -> dict:
    from sec_xbrl.screening.metric_identity import _verify_analysis

    path = Path(pin["path"])
    manifest = read_json(path)
    scope = manifest.get("companies", {}).get(ticker, {})
    _verify_analysis(
        str(path.parent),
        pin["sha256"],
        ticker=ticker,
        cik=cik,
        financial_as_of=scope.get("as_of"),
        history_root=Path(history["path"]).parent,
        history_sha=history["sha256"],
        period_mode=mode,
        input_years=scope.get("years") if mode == "ANNUAL" else None,
    )
    return manifest


def _collection_controls(
    path: Path, ticker: str, cik: str, controls: dict, label: str
) -> tuple[dict, Path]:
    from sec_xbrl.source_bindings import _load_collection_header, _materialize_collection_scope

    _, _request, rows = _load_collection_header(path)
    selected = tuple(row for row in rows if (row["ticker"], row["cik"]) == (ticker, cik))
    if len(selected) != 1:
        raise ValueError("prospective company is absent from collection")
    _materialize_collection_scope(path, selected)
    plan_path = Path(selected[0]["plan_path"])
    intake_path = path.parent / "companies" / ticker / "intake/history_intake.json"
    controls[f"{ticker}:{label}:request"] = _file_pin(Path(read_json(path)["request_path"]))
    controls[f"{ticker}:{label}:plan"] = _file_pin(plan_path)
    controls[f"{ticker}:{label}:intake"] = _file_pin(intake_path)
    return read_json(plan_path), intake_path


def _resolve_config(config_pin: dict[str, str]) -> tuple[str, dict, dict, Any]:
    from sec_xbrl.collection_operations import _attest_intake, _validate_build_attestation
    from sec_xbrl.filing.company_discovery import (
        SUPPORTED_FORMS,
        CompanySubmissionsAccessionProvider,
    )
    from sec_xbrl.history import _ref_record, select_history_filings
    from sec_xbrl.screening.metric_identity import _quarter_spine

    config_pin = _pin(config_pin)
    config = read_json(Path(config_pin["path"]))
    fields = {
        "schema_version",
        "current_collection",
        "financial_as_of",
        "discovery_summary",
        "companies",
    }
    if (
        not isinstance(config, dict)
        or not fields <= set(config)
        or set(config) - fields - {"storage_reuse"}
        or config.get("schema_version") != CONFIG_VERSION
    ):
        raise ValueError("unsupported prospective selection config")
    current_pin = _pin(config["current_collection"])
    current = Path(current_pin["path"])
    cutoff = config["financial_as_of"]
    date.fromisoformat(cutoff)
    summary_pin = _pin(config["discovery_summary"])
    summary = read_json(Path(summary_pin["path"]))
    if summary.get("cutoff") != cutoff or not isinstance(summary.get("companies"), list):
        raise ValueError("prospective completeness cutoff differs")
    discovery = {(row["ticker"], row["cik"]): row for row in summary["companies"]}
    if len(discovery) != len(summary["companies"]):
        raise ValueError("duplicate discovery company")
    controls = {"CONFIG": config_pin, "CURRENT_COLLECTION": current_pin, "DISCOVERY": summary_pin}
    result = {}
    storage_proofs = {}
    origin_selections = {}
    entries = config["companies"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("prospective companies must be explicit")
    for entry in entries:
        required = {
            "ticker",
            "cik",
            "origin_collection",
            "origin_history_manifest",
            "origin_annual_analysis",
            "origin_quarterly_analysis",
            "current_policy",
        }
        if (
            not isinstance(entry, dict)
            or not required <= set(entry)
            or set(entry) - required - {"origin_history_selection"}
        ):
            raise ValueError("invalid prospective company fields")
        ticker = require_ticker(entry["ticker"], "prospective ticker")
        cik = require_cik(entry["cik"], "prospective CIK")
        if ticker in result or ticker != entry["ticker"]:
            raise ValueError("duplicate or unsafe prospective company")
        pins = {name: _pin(entry[name]) for name in required - {"ticker", "cik"}}
        old_collection = Path(pins["origin_collection"]["path"])
        current_plan, current_intake = _collection_controls(
            current, ticker, cik, controls, "CURRENT"
        )
        old_plan, old_intake = _collection_controls(old_collection, ticker, cik, controls, "ORIGIN")
        if current_plan.get("as_of_date") != cutoff:
            raise ValueError("prospective canonical plan cutoff differs")
        old_cutoff = old_plan.get("as_of_date")
        if (
            not isinstance(old_cutoff, str)
            or old_cutoff >= cutoff
            or _quarter_spine(old_cutoff) != _quarter_spine(cutoff)
        ):
            raise ValueError(
                "prospective selection requires a later cutoff in the same completed quarter spine"
            )
        old_company, current_company = old_plan["companies"][0], current_plan["companies"][0]
        if old_company["filings"] != current_company["filings"]:
            raise ValueError("prospective eligible filing inventory changed")
        if {k: v for k, v in old_plan.items() if k not in {"as_of_date", "companies"}} != {
            k: v for k, v in current_plan.items() if k not in {"as_of_date", "companies"}
        }:
            raise ValueError("prospective filing selection policy changed")
        observed = discovery.get((ticker, cik), {})
        snapshots = current_company.get("submissions")
        if (
            observed.get("status") != "FETCHED"
            or not snapshots
            or observed.get("submissions") != snapshots
            or len(set(snapshots)) != len(snapshots)
        ):
            raise ValueError("prospective submissions completeness differs from canonical plan")
        for index, source in enumerate(snapshots):
            pin = _file_pin(Path(source))
            if Path(source).stem != pin["sha256"]:
                raise ValueError("prospective submissions snapshot is not content addressed")
            controls[f"{ticker}:SUBMISSIONS:{index}"] = pin
        _check_submissions_completeness([read_json(Path(path)) for path in snapshots], cik)
        refs = tuple(
            CompanySubmissionsAccessionProvider(
                tuple(Path(p) for p in snapshots), cik=cik
            ).iter_filings(forms=set(SUPPORTED_FORMS))
        )
        selected = select_history_filings(
            refs,
            as_of=date.fromisoformat(cutoff),
            report_start=date.fromisoformat(current_plan["report_start"])
            if current_plan.get("report_start")
            else None,
            report_end=date.fromisoformat(current_plan["report_end"])
            if current_plan.get("report_end")
            else None,
            recent_fiscal_years=current_plan.get("recent_fiscal_years"),
        )
        if [_ref_record(ref) for ref in selected] != current_company["filings"]:
            raise ValueError("current plan omits or changes eligible submissions filings")
        old_outcomes = read_json(old_intake)["filings"]
        new_outcomes = read_json(current_intake)["filings"]
        if [(r["filing"], r["source_run"]) for r in old_outcomes] != [
            (r["filing"], r["source_run"]) for r in new_outcomes
        ]:
            raise ValueError("prospective Raw origin locators differ")
        storage = None
        if "storage_reuse" in config:
            from sec_xbrl.financial_storage_reuse import resolve_storage_reuse

            key = str(old_collection)
            if key not in storage_proofs:
                storage_proofs[key] = resolve_storage_reuse(
                    config["storage_reuse"],
                    collection_manifest=old_collection,
                    scope_companies=read_json(old_collection)["companies"],
                )
                controls.update(
                    {f"STORAGE:{name}": pin for name, pin in storage_proofs[key].controls.items()}
                )
                for owner, company in storage_proofs[key].companies.items():
                    for context, stored in enumerate(company["histories"]):
                        root = Path(stored["history_manifest"]["path"]).parent
                        for relative, digest in stored["payload_inventory"].items():
                            controls[f"STORAGE:{owner}:{context}:PAYLOAD:{relative}"] = {
                                "path": str(root / relative),
                                "sha256": digest,
                            }

            storage = storage_proofs[key]
        selected_origin = None
        if "origin_history_selection" in entry:
            selection_pin = _pin(entry["origin_history_selection"])
            selection_key = (str(old_collection), selection_pin["path"], selection_pin["sha256"])
            if selection_key not in origin_selections:
                origin_selections[selection_key] = resolve_history_selection(
                    selection_pin, collection_manifest=old_collection,
                    scope_companies=read_json(old_collection)["companies"], storage_reuse=storage)
            selected_origin = origin_selections[selection_key]
            if ticker not in selected_origin.companies:
                raise ValueError("prospective origin selection omits its company")
            controls.update({f"{ticker}:SELECTED:{k}": v for k, v in selected_origin.controls.items()})
        build_path = (
            Path(selected_origin.companies[ticker]["build_manifest"]["path"])
            if selected_origin
            else old_collection.parent / "companies" / ticker / "build_manifest.json"
        )
        build = read_json(build_path)
        error = _validate_build_attestation(
            build,
            ticker=ticker,
            plan=old_plan,
            plan_sha256=sha256_file(Path(controls[f"{ticker}:ORIGIN:plan"]["path"])),
            intake_path=old_intake,
            intake=_attest_intake(old_intake, old_plan),
        )
        if (
            error
            or build.get("status") != "READY"
            or build.get("history_manifest") != pins["origin_history_manifest"]["path"]
            or build.get("history_manifest_sha256") != pins["origin_history_manifest"]["sha256"]
        ):
            raise ValueError(f"prospective origin History is not exactly accepted READY: {error}")
        policy = read_json(Path(pins["current_policy"]["path"]))
        analyses = {
            mode: _analysis(
                pins[f"origin_{mode.lower()}_analysis"],
                ticker,
                cik,
                pins["origin_history_manifest"],
                mode,
            )
            for mode in ("ANNUAL", "QUARTERLY")
        }
        rules = prospective_rule_versions()
        expected_policy = {
            "schema_version": POLICY_VERSION,
            "status": "ROOT_APPROVED",
            "origin_analyses": {mode: pins[f"origin_{mode.lower()}_analysis"] for mode in analyses},
            "current_policy_source_sha256s": prospective_policy_sources(),
            "rules": rules,
            "current_collection": current_pin,
            "financial_as_of": cutoff,
            "discovery_summary": summary_pin,
            "raw_inventory": prospective_raw_inventory(current, ticker, cik),
            **{mode: analysis_selection_policy(value, ticker) for mode, value in analyses.items()},
        }
        if policy != expected_policy or any(
            value["companies"][ticker]["as_of"] != old_cutoff for value in analyses.values()
        ):
            raise ValueError(
                "prospective selection lacks exact ROOT policy/settings/Raw compatibility approval"
            )
        for name, pin in pins.items():
            controls[f"{ticker}:{name}"] = pin
        controls[f"{ticker}:ORIGIN:build"] = _file_pin(build_path)
        _bind_origin_history(controls, ticker=ticker, manifest=pins["origin_history_manifest"],
                             declared=build["declared_files"], storage=storage)
        for accession, files in expected_policy["raw_inventory"].items():
            outcome = next(row for row in new_outcomes if row["filing"]["accession"] == accession)
            root = Path(outcome["source_run"]) / "snapshots" / cik / accession.replace("-", "")
            for relative, digest in files.items():
                controls[f"{ticker}:RAW:{accession}:{relative}"] = {
                    "path": str(root / relative),
                    "sha256": digest,
                }
        for mode, manifest in analyses.items():
            root = Path(pins[f"origin_{mode.lower()}_analysis"]["path"]).parent
            for view in manifest["companies"][ticker]["views"].values():
                for name, info in view["files"].items():
                    controls[f"{ticker}:{mode}:{info['path']}"] = _pin(
                        {"path": str(root / info["path"]), "sha256": info["sha256"]}
                    )
        result[ticker] = {
            "ticker": ticker,
            "cik": cik,
            "selection_status": "SELECTION_EQUIVALENT",
            "collection_status": "RAW_COMPLETE",
            "origin_financial_as_of": old_cutoff,
            **pins,
            "origin_build_manifest": _file_pin(build_path),
            "current_plan": controls[f"{ticker}:CURRENT:plan"],
            "current_intake": controls[f"{ticker}:CURRENT:intake"],
        }
    return cutoff, result, controls, next(iter(storage_proofs.values()), None)


def publish_prospective_selection(*, config_path: Path, destination: Path) -> Path:
    """Publish immutable evidence only after replaying the complete proof."""
    destination = safe_new_destination(destination, "prospective selection")
    producer_sources = _producer_source_pins()
    pin = _file_pin(config_path)
    cutoff, companies, controls, _storage = _resolve_config(pin)
    # Recheck every input at the write boundary; no stale preflight proof.
    _verify_control_bytes(controls)
    _check_input_topologies(controls, _storage)
    _verify_producer_sources(producer_sources)
    destination.mkdir(parents=True)
    path = destination / "prospective_selection_manifest.json"
    write_json(
        path,
        {
            "schema_version": MANIFEST_VERSION,
            "publication_id": uuid.uuid4().hex,
            "config": pin,
            "financial_as_of": cutoff,
            "companies": companies,
            "controls": controls,
        },
    )
    return path


def resolve_prospective_selection(
    declaration: dict, *, collection_manifest: Path, scope_companies: list[dict]
) -> ProspectiveSelections:
    selection = _resolve_manifest(declaration)
    allowed = {(row["ticker"], row["cik"]) for row in scope_companies}
    if any(
        (ticker, row["cik"]) not in allowed for ticker, row in selection.companies.items()
    ) or selection.controls["CURRENT_COLLECTION"]["path"] != str(collection_manifest.resolve()):
        raise ValueError("prospective selection is outside configured scope")
    return selection


def _resolve_manifest(declaration: dict) -> ProspectiveSelections:
    declaration = _pin(declaration)
    value = read_json(Path(declaration["path"]))
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "publication_id",
            "config",
            "financial_as_of",
            "companies",
            "controls",
        }
        or value.get("schema_version") != MANIFEST_VERSION
        or not isinstance(value.get("publication_id"), str)
        or not value["publication_id"]
    ):
        raise ValueError("unsupported prospective selection manifest")
    cutoff, companies, controls, storage = _resolve_config(value["config"])
    if (
        value["financial_as_of"] != cutoff
        or value["companies"] != companies
        or value["controls"] != controls
    ):
        raise ValueError("prospective selection proof replay differs")
    controls = {**controls, "PROSPECTIVE_MANIFEST": declaration}
    return ProspectiveSelections(
        declaration,
        cutoff,
        companies,
        controls,
        storage,
        _ISSUER,
        digest_value([declaration, cutoff, companies, controls]),
    )


def checked_prospective_selection(
    value: ProspectiveSelections, *, declaration: dict, collection_manifest: Path
) -> ProspectiveSelections:
    """Check an internal invocation proof without replaying every company again."""
    if (
        not isinstance(value, ProspectiveSelections)
        or value._issuer is not _ISSUER
        or value._seal
        != digest_value([value.declaration, value.financial_as_of, value.companies, value.controls])
        or value.declaration != declaration
        or value.controls["CURRENT_COLLECTION"]["path"] != str(collection_manifest.resolve())
    ):
        raise ValueError("untrusted or mutated prospective invocation proof")
    _pin(value.declaration)
    _pin(value.controls["CURRENT_COLLECTION"])
    return value


def prepare_reselected_analysis(
    *, prospective_selection: dict, ticker: str, period_mode: str, destination: Path
) -> Path:
    """Prepare one target through the same bounded batch proof boundary."""
    return prepare_reselected_analysis_batch(
        prospective_selection=prospective_selection,
        destinations={ticker: {period_mode: destination}},
    )[ticker][period_mode]


def prepare_reselected_analysis_batch(
    *, prospective_selection: dict, destinations: dict[str, dict[str, Path]]
) -> dict[str, dict[str, Path]]:
    """Replay one immutable proof, stage all targets, then recheck inputs once.

    Only a pinned publication is accepted; callers cannot supply a trusted proof.
    No target becomes visible before the complete batch input closure is rechecked.
    A failed filesystem rename may leave new targets for diagnosis, never a false
    all-or-nothing transaction claim or modifications to an existing publication.
    """
    producer_sources = _producer_source_pins()
    selection = _resolve_manifest(prospective_selection)
    if not isinstance(destinations, dict) or not destinations:
        raise ValueError("reselection batch requires explicit destinations")
    targets = []
    for ticker, modes in destinations.items():
        if (
            require_ticker(ticker, "reselected ticker") != ticker
            or ticker not in selection.companies
            or not isinstance(modes, dict)
            or not modes
            or set(modes) - {"ANNUAL", "QUARTERLY"}
        ):
            raise ValueError("reselection requires an approved company and period mode")
        for mode, destination in modes.items():
            path = safe_new_destination(Path(destination), "reselected analysis")
            if any(
                path == other or path in other.parents or other in path.parents
                for _, _, other in targets
            ):
                raise ValueError("reselection destinations overlap")
            targets.append((ticker, mode, path))
    staged = [
        (
            ticker,
            mode,
            path,
            _stage_reselected_analysis(
                selection, ticker=ticker, period_mode=mode, destination=path
            ),
        )
        for ticker, mode, path in targets
    ]
    # Current controls, Raw tables and governed History/analysis payloads, once per
    # batch. Retained nonconsumed diagnostics remain topology-only under v2.
    _verify_control_bytes(selection.controls)
    _check_input_topologies(selection.controls, selection.storage_reuse)
    _verify_producer_sources(producer_sources)
    result: dict[str, dict[str, Path]] = {}
    for ticker, mode, destination, staging in staged:
        # Recheck destination safety at commit, without another source replay.
        safe_new_destination(destination, "reselected analysis")
        staging.rename(destination)
        result.setdefault(ticker, {})[mode] = destination
    return result


def _verify_control_bytes(controls: dict) -> None:
    # Distinct provenance roles may bind the same payload. Hash each physical
    # input once at this boundary while rejecting conflicting declarations.
    unique = {}
    for pin in controls.values():
        previous = unique.setdefault(pin["path"], pin)
        if previous != pin:
            raise ValueError("prospective controls conflict for one physical input")
    for pin in unique.values():
        _pin(pin)


def _bind_origin_history(controls: dict, *, ticker: str, manifest: dict,
                         declared: dict, storage: Any) -> None:
    """Active History freshness never depends on optional prior-check reuse."""
    from sec_xbrl.financial_storage_reuse import storage_history
    from sec_xbrl.history_selection import _retained_diagnostic
    root = Path(manifest["path"]).parent
    entry = storage_history(storage, ticker, Path(manifest["path"]))
    if entry is not None and "retained_diagnostics" in entry:
        # Only an explicitly verified v2 entry may exclude diagnostic bodies.
        inventory = entry["payload_inventory"]
    else:
        # No optimization (or v1) retains the strict physical-byte policy.
        inventory = _inventory(root)
        extras = set(inventory) - set(declared) - {"history_manifest.json"}
        if any(not _retained_diagnostic(relative, set(declared)) for relative in extras):
            raise ValueError("prospective origin History has unknown physical inputs")
    if (inventory.get("history_manifest.json") != manifest["sha256"]
        or any(inventory.get(relative) != digest for relative, digest in declared.items())):
        raise ValueError("prospective origin History payload inventory differs")
    for relative, digest in inventory.items():
        controls[f"{ticker}:ORIGIN_HISTORY_PAYLOAD:{relative}"] = {
            "path": str(root / relative), "sha256": digest}


def _producer_source_pins() -> dict[str, dict[str, str]]:
    package = Path(__file__).parent
    return {str(path.relative_to(package)): _file_pin(path)
            for path in sorted(package.rglob("*.py"))}


def _verify_producer_sources(expected: dict) -> None:
    # Invocation-local freshness. Persisting absolute runtime source paths in the
    # selection proof would prohibit relocation of byte-identical accepted code.
    if _producer_source_pins() != expected:
        raise ValueError("prospective producer sources changed before commit")


def _check_input_topologies(controls: dict, storage: Any) -> None:
    """Recheck exact active input membership without hashing file bodies twice."""
    raw_roots = {}
    for key, pin in controls.items():
        if ":RAW:" in key:
            path = Path(pin["path"])
            raw_roots.setdefault(path.parent, set()).add(path.name)
    for root, expected in raw_roots.items():
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                raise ValueError("prospective Raw topology changed")
            actual.add(str(path.relative_to(root)))
        if actual != expected:
            raise ValueError("prospective Raw inventory changed")
    from sec_xbrl.financial_storage_reuse import storage_history
    for key, manifest in controls.items():
        if not key.endswith(":origin_history_manifest"):
            continue
        ticker = key.removesuffix(":origin_history_manifest")
        root = Path(manifest["path"]).parent
        prefix = ticker + ":ORIGIN_HISTORY_PAYLOAD:"
        expected = {name.removeprefix(prefix) for name in controls if name.startswith(prefix)}
        entry = storage_history(storage, ticker, Path(manifest["path"]))
        if entry is not None and "retained_diagnostics" in entry:
            expected.update(entry["retained_diagnostics"])
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                raise ValueError("prospective origin History has unsafe topology")
            if path.is_file():
                actual.add(str(path.relative_to(root)))
            elif not any(path.iterdir()):
                raise ValueError("prospective origin History has an unknown empty directory")
        if actual != expected:
            raise ValueError("prospective origin History inventory changed")
    if storage is not None:
        for company in storage.companies.values():
            for entry in company["histories"]:
                root = Path(entry["history_manifest"]["path"]).parent
                actual = set()
                for path in root.rglob("*"):
                    if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                        raise ValueError("storage reuse unsafe inventory at batch commit")
                    if path.is_file():
                        actual.add(str(path.relative_to(root)))
                    elif not any(path.iterdir()):
                        raise ValueError("storage reuse unknown empty directory at batch commit")
                if actual != set(entry["payload_inventory"]) | set(
                    entry.get("retained_diagnostics", ())
                ):
                    raise ValueError("storage reuse inventory changed at batch commit")

def _stage_reselected_analysis(
    selection: ProspectiveSelections, *, ticker: str, period_mode: str, destination: Path
) -> Path:
    from sec_xbrl.analysis import AnalysisClient
    from sec_xbrl.history import _write_records

    entry = selection.companies[ticker]
    origin = entry[f"origin_{period_mode.lower()}_analysis"]
    client = AnalysisClient(Path(origin["path"]).parent)
    manifest = copy.deepcopy(client.manifest)
    event = uuid.uuid4().hex
    origin_link = {
        "analysis_manifest": origin,
        "publication_id": manifest["publication_id"],
        "financial_as_of": entry["origin_financial_as_of"],
        "prospective_selection": selection.declaration,
        "prospective_selection_event_id": event,
    }
    manifest["publication_id"] = uuid.uuid4().hex
    manifest["prospective_selection"] = origin_link
    manifest["companies"][ticker]["as_of"] = selection.financial_as_of
    staging = destination.parent / (".partial-" + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    for view, view_info in manifest["companies"][ticker]["views"].items():
        datasets = _reselected_records(
            client,
            ticker=ticker,
            view=view,
            cutoff=selection.financial_as_of,
            origin_link=origin_link,
        )
        for name, info in view_info["files"].items():
            info.update(_write_records(staging / info["path"], tuple(datasets[name])))
    write_json(staging / "analysis_manifest.json", manifest)
    return staging


def prospective_rule_versions() -> dict[str, str]:
    from sec_xbrl.analytics.history_quarters import PERIOD_RULE, QUARTER_RULE
    from sec_xbrl.history import HISTORY_VERSION, MAPPING_VERSION
    from sec_xbrl.longitudinal.q4_policy_registry import Q4_POLICY_REGISTRY_VERSION
    from sec_xbrl.longitudinal.quarterly_policy import QUARTERLY_POLICY_VERSION
    from sec_xbrl.longitudinal.reported_selection import REPORTED_SELECTION_RULE_VERSION

    return {
        "history_version": HISTORY_VERSION,
        "mapping_version": MAPPING_VERSION,
        "period_rule": PERIOD_RULE,
        "quarter_rule": QUARTER_RULE,
        "quarterly_policy": QUARTERLY_POLICY_VERSION,
        "q4_registry": Q4_POLICY_REGISTRY_VERSION,
        "reported_selection": REPORTED_SELECTION_RULE_VERSION,
        "selection_rule": "selection-v1",
        "recast_rule": "recast-v1",
    }


def _reselected_records(client, *, ticker: str, view: str, cutoff: str, origin_link: dict) -> dict:
    from sec_xbrl.analysis import stable

    old_cutoff = origin_link["financial_as_of"]
    event = origin_link["prospective_selection_event_id"]
    datasets = {
        name: client._records(ticker, view, name)
        for name in client.manifest["companies"][ticker]["views"][view]["files"]
    }
    prepared_ids = {
        row["cell_id"]
        for name in ("cells", "core_cells")
        for row in datasets.get(name, [])
        if isinstance(row.get("cell_id"), str)
    }
    ids = {
        old: ("missing:" if old.startswith("missing:") else "")
        + "analysis-reselection:"
        + digest_value([event, old])
        for old in prepared_ids
    }

    def current_selection(value, *, lineage=False):
        if isinstance(value, list):
            return [current_selection(item, lineage=lineage) for item in value]
        if isinstance(value, dict):
            result = {
                key: current_selection(item, lineage=lineage or key == "value_lineage")
                for key, item in value.items()
            }
            for key in ("as_of", "selection_as_of_date"):
                if key in value:
                    if value[key] not in (None, old_cutoff):
                        raise ValueError("origin contains a different selection cutoff")
                    if value[key] is not None:
                        result[key] = cutoff
            if not lineage:
                for key in ("cell_id", "selected_cell_id", "anchor_cell_id"):
                    if isinstance(value.get(key), str) and value[key] in ids:
                        result[key] = ids[value[key]]
                if isinstance(value.get("input_ids"), list):
                    result["input_ids"] = [ids.get(item, item) for item in value["input_ids"]]
                if "cell_id" in value and value["cell_id"] in ids:
                    result["origin_prepared_cell_id"] = value["cell_id"]
                    result["prospective_selection_event_id"] = event
            return result
        return value

    transformed = {}
    traces = []
    for name, records in datasets.items():
        updated = []
        for record in records:
            row = current_selection(record)
            if name.startswith("trace_"):
                row["origin_selection"] = {
                    **origin_link,
                    "cell_id": record.get("cell_id"),
                    "value_lineage": copy.deepcopy(record.get("value_lineage")),
                }
                if isinstance(row.get("value_lineage"), dict):
                    row["value_lineage"]["prospective_selection_event_id"] = event
            updated.append(row)
        if name.startswith("trace_"):
            traces.extend(updated)
        else:
            transformed[name] = updated
    for digit in "0123456789abcdef":
        transformed["trace_" + digit] = [
            row for row in traces if stable(row["cell_id"])[0] == digit
        ]
    return transformed


def verify_reselected_analysis(
    root: Path, *, selection: ProspectiveSelections, ticker: str, period_mode: str
) -> None:
    """Replay the explicit current selection event against the pinned origin bundle."""
    from sec_xbrl.analysis import AnalysisClient

    current = AnalysisClient(root)
    entry = selection.companies[ticker]
    origin = entry[f"origin_{period_mode.lower()}_analysis"]
    client = AnalysisClient(Path(origin["path"]).parent)
    link = current.manifest.get("prospective_selection")
    if not isinstance(link, dict) or set(link) != {
        "analysis_manifest",
        "publication_id",
        "financial_as_of",
        "prospective_selection",
        "prospective_selection_event_id",
    }:
        raise ValueError("current reselected analysis lacks explicit origin/event")
    if (
        link["analysis_manifest"] != origin
        or link["publication_id"] != client.manifest["publication_id"]
        or link["financial_as_of"] != entry["origin_financial_as_of"]
        or link["prospective_selection"] != selection.declaration
        or not isinstance(link["prospective_selection_event_id"], str)
        or len(link["prospective_selection_event_id"]) != 32
        or current.manifest["publication_id"] == client.manifest["publication_id"]
        or analysis_selection_policy(current.manifest, ticker)
        != analysis_selection_policy(client.manifest, ticker)
    ):
        raise ValueError("current reselected analysis origin/settings differ")
    expected = copy.deepcopy(client.manifest)
    expected["publication_id"] = current.manifest["publication_id"]
    expected["prospective_selection"] = link
    expected["companies"][ticker]["as_of"] = selection.financial_as_of
    for view, info in expected["companies"][ticker]["views"].items():
        datasets = _reselected_records(
            client, ticker=ticker, view=view, cutoff=selection.financial_as_of, origin_link=link
        )
        actual_files = current.manifest["companies"][ticker]["views"][view]["files"]
        if set(info["files"]) != set(actual_files):
            raise ValueError("reselected analysis dataset set differs")
        for name in info["files"]:
            if current._records(ticker, view, name) != datasets[name]:
                raise ValueError(
                    "reselected analysis differs from current event over approved unchanged observations"
                )
            expected["companies"][ticker]["views"][view]["files"][name] = actual_files[name]
    if current.manifest != expected:
        raise ValueError("reselected analysis envelope differs from approved origin")


def _check_submissions_completeness(snapshots: list[dict], cik: str) -> None:
    """Check the existing collector's full root/archive snapshot membership."""
    roots = [value for value in snapshots if isinstance(value.get("filings"), dict)]
    archives = [value for value in snapshots if not isinstance(value.get("filings"), dict)]
    if len(roots) != 1 or str(roots[0].get("cik", "")).zfill(10) != cik:
        raise ValueError("prospective submissions need exactly one matching company root")
    declarations = roots[0]["filings"].get("files")
    if not isinstance(declarations, list) or len(declarations) != len(archives):
        raise ValueError("prospective submissions archive membership is incomplete")
    names = [row.get("name") for row in declarations if isinstance(row, dict)]
    if (
        len(names) != len(declarations)
        or any(not isinstance(name, str) or Path(name).name != name for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("prospective submissions archive names are unsafe or repeated")
    # SEC archive endpoint declarations can include buffer days. Check counts and
    # containment, preserving the existing provider as the only filing adapter.
    candidates = []
    for archive in archives:
        accessions = archive.get("accessionNumber")
        dates = archive.get("filingDate")
        if (
            not isinstance(accessions, list)
            or not isinstance(dates, list)
            or len(dates) != len(accessions)
            or not dates
        ):
            raise ValueError("prospective archive filing inventory is malformed")
        parsed = [date.fromisoformat(value) for value in dates]
        candidates.append(
            [
                index
                for index, row in enumerate(declarations)
                if row.get("filingCount") == len(accessions)
                and date.fromisoformat(row["filingFrom"]) <= min(parsed)
                and max(parsed) <= date.fromisoformat(row["filingTo"])
            ]
        )
    # Iterative augmenting paths prove one-to-one coverage without a fixed depth.
    assigned = {}
    for origin in range(len(archives)):
        queue = [origin]
        seen = {origin}
        parents = {}
        free = None
        for archive_index in queue:
            for declaration_index in candidates[archive_index]:
                owner = assigned.get(declaration_index)
                if owner is None:
                    free = (archive_index, declaration_index)
                    break
                if owner not in seen:
                    seen.add(owner)
                    parents[owner] = (archive_index, declaration_index)
                    queue.append(owner)
            if free is not None:
                break
        if free is None:
            raise ValueError("prospective archive snapshots do not cover the root declarations")
        owner, target = free
        assigned[target] = owner
        while owner in parents:
            owner, target = parents[owner]
            assigned[target] = owner
