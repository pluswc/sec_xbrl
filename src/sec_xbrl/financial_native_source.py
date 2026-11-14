"""Exact native producer transition; independent of historical successor packets."""
from __future__ import annotations

import ast
import copy
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from sec_xbrl.screening.common import digest_value, read_json, regular_file, sha256_file, write_json

VERSION = "financial-native-source-v1"
APPROVAL_VERSION = "financial-native-source-approval-v1"
PRODUCER = "401be11b04fd203f6e74eda7b34e44ca0e7bc406"
_ORIGIN_INVENTORY = "a2410ec9540c12255821d23c5964d7b029a2676740ac39a36ef552e8a15b865b"
_SOURCE_ROOT = Path(__file__).parent
_BASE_CHANGES = {
    "metric_quality.py": "5f29bd7ef4789c74a8fe865410036406e4fc6e23a5cee334a38dce220bdfba1c",
    "history.py": "b0923a1d5cbe51b3317bac4be271d9a0deed6944aedc7c972089301b6d5c3a6f",
    "source_bindings.py": "4622de98cda8757b49f39e1d1010304835093d7326d2bb468d418425be286711",
    "facts/layer1.py": "6c0d530068778d8d7c0e48d7e584d1dbc3f517b95da75716aaff02c23971d18e",
    "filing/layer1_ingestion.py": "a37a7451be4f087ddaa9a12c1d592e4bee1885116b1fec1d449e4c55110da080",
    "filing/sec_inline_transforms.py": "bbc1505dc389edab07b7063bf937d5ddc6aa20afc4e6abaa54b1080bf7b4376d",
}
_NATIVE_CHANGES = frozenset({"financial_native_source.py", "financial_storage_reuse.py",
                             "screening/dataset_v3.py", "screening/verified_source_closure.py",
                             "collection_operations.py", "screening/metric_identity.py"})
_PARENT_FILES = {"identity": "generic_metric_identity_manifest.json", "annual_metrics": "screening_metric_manifest.json",
                 "annual_dataset": "screening_dataset_manifest.json", "quarterly_metrics": "quarterly_screening_metric_manifest.json"}
_PARENT_SCHEMAS = {"identity": "generic-metric-identity-attestation-v1", "annual_metrics": "screening-metrics-v1",
                   "annual_dataset": "screening-dataset-v2", "quarterly_metrics": "quarterly-screening-metric-manifest-v1"}


VERSION_V2 = "financial-native-source-v2"
APPROVAL_VERSION_V2 = "financial-native-source-approval-v2"
_CONSUMER_BASELINE_INVENTORY = "e38792671c712b1a9167749c41138f1e2d9f64cf70c6c8a226e3735bb8e73a74"
_CONSUMER_CHANGES = frozenset({"financial_native_source.py", "metrics/screening.py",
    "screening/metric_identity.py", "screening/verified_source_closure.py",
    "screening/governed_delta.py", "screening/cohort_union.py", "screening/runtime_projection.py",
    "screening/service.py", "screening/cli.py"})
_PARTIAL_CONSUMER_FILES = {'metrics/screening.py': '58e9bdb42d579085a685a71c167cf413cafb68a80f03d5de5d9c4e145ed9134b',
 'screening/metric_identity.py': 'a66dce05b3428361826a190e6198bbc87ec0792d91f01dec0089ff24a2e1a9ba',
 'screening/verified_source_closure.py': '75dd64bd1bc4b309298c6bd2c567aa6eb0db45b6daec5a4ffbe17976b5575412'}
_PRODUCER_PROFILES = {'partial-annual-882-v1': {'producer_revision': '882ac6ac6b0682d2c593cc511a5a1c565cd8d9fb',
                           'origin_inventory': '9eaac547d7f119a0f2494b633cf44f2206a13f745843ccba78abe9e9b7356d2a',
                           'parser_profiles': [{'parser_source_commit': '4077e87097c294ed779186b613157839f215a63e',
                                                'parser_version': 'm2-layer1-v6',
                                                'profile': 'sec-inline-duration-approved-lexical-and-metadata-v1',
                                                'transform_rule_version': 'sec-duration-conformance-v1'}],
                           'quality_rules': {'approved_lexical_repair_rule': 'sec-supported-lexical-repairs-v1',
                                             'duration_transform_rule': 'sec-duration-conformance-v1',
                                             'quality_rule': 'generic-metric-raw-transform-quality-v1',
                                             'source_binding_schema': 'sec-source-bindings-v2'},
                           'annual_coverage_policy': 'available-annual-baselines-v1'},
 'duration-hour-20ec-v1': {'producer_revision': '20ec4398ba7f6841edf5d03bef482d34a8b2e26c',
                           'origin_inventory': 'c5dfc52013c8e57a451d09a03a3edfe18036bb5337b8616bc898099f14e58d73',
                           'parser_profiles': [{'parser_source_commit': '4077e87097c294ed779186b613157839f215a63e',
                                                'parser_version': 'm2-layer1-v6',
                                                'profile': 'sec-inline-duration-approved-lexical-and-metadata-v1',
                                                'transform_rule_version': 'sec-duration-conformance-v1'},
                                               {'parser_source_commit': '82cc02eddfd6f05997c5e1e7d2a5c78ab2f4dd08',
                                                'parser_version': 'm2-layer1-v7',
                                                'profile': 'sec-inline-duration-hour-approved-lexical-and-metadata-v1',
                                                'transform_rule_version': 'sec-duration-hour-conformance-v1'}],
                           'quality_rules': {'approved_lexical_repair_rule': 'sec-supported-lexical-repairs-v1',
                                             'duration_transform_rule': 'sec-duration-conformance-v1',
                                             'quality_rule': 'generic-metric-raw-transform-quality-v1',
                                             'source_binding_schema': 'sec-source-bindings-v2'},
                           'annual_coverage_policy': 'STRICT_5_INPUT_4_DISPLAY'}}


def _file(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.resolve() != path:
        raise ValueError("native control requires an absolute non-aliased path")
    return regular_file(path, "native control")


def _pin(path: Path) -> dict[str, str]:
    path = _file(path)
    return {"path": str(path), "sha256": sha256_file(path)}


def _checked(pin: dict) -> Path:
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or type(pin["path"]) is not str:
        raise ValueError("native control pin fields differ")
    path = _file(Path(pin["path"]))
    if _pin(path) != pin:
        raise ValueError("native control bytes differ")
    return path


def _inventory(root: Path) -> dict[str, str]:
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("native source root differs")
    return {str(path.relative_to(root)): sha256_file(_file(path)) for path in sorted(root.rglob("*.py"))}


def _source_controls(payload: dict) -> dict[str, dict]:
    if payload.get("schema_version") in {PREPARATION_VERSION, VERSION_V3}:
        return _preparation_source_controls(payload)
    if payload.get("schema_version") == VERSION_V2:
        return _source_controls_v2(payload)
    source = payload["source"]
    if set(source) != {"old_root", "old_files", "current_files"}:
        raise ValueError("native source fields differ")
    old_root = Path(source["old_root"])
    old = _inventory(old_root)
    current = _inventory(_SOURCE_ROOT)
    if (old != source["old_files"] or digest_value(old) != _ORIGIN_INVENTORY
            or current != source["current_files"]):
        raise ValueError("native exact source inventory differs")
    changed = {name for name in old.keys() | current.keys() if old.get(name) != current.get(name)}
    if not changed <= _BASE_CHANGES.keys() | _NATIVE_CHANGES:
        raise ValueError("native source changes an unapproved module")
    if any(current.get(name) != digest for name, digest in _BASE_CHANGES.items()):
        raise ValueError("native accepted parser/profile source differs")
    if "metric_quality.py" in _BASE_CHANGES:
        # Prove the accepted B implementation plus only the scoped status caller.
        data = (_SOURCE_ROOT / "metric_quality.py").read_bytes()
        import_line = b"    from sec_xbrl.financial_native_source import native_assessed_ciks\n"
        new_call = b", _verified_storage_reuse=verified_storage if status_storage else None,\n                                 assessed_ciks=native_assessed_ciks(collection_manifest=collection_manifest, scope_companies=expected_companies))"
        old_call = b", _verified_storage_reuse=verified_storage if status_storage else None)"
        if data.count(import_line) != 1 or data.count(new_call) != 1:
            raise ValueError("native quality status call-site differs")
        original = data.replace(import_line, b"").replace(new_call, old_call)
        if hashlib.sha256(original).hexdigest() != "114836d6d35d5d1f936dfe1eb8874da5b3a23b293962fad7e2071ef1936b5393":
            raise ValueError("native quality changes the accepted B rules/profile")
    if set(current) - set(old) != {"financial_native_source.py"} or set(old) - set(current):
        raise ValueError("native source file additions/removals differ")
    return {f"{kind}:{name}": {"path": str(root / name), "sha256": digest}
            for kind, root, files in (("OLD_SOURCE", old_root, old), ("CURRENT_SOURCE", _SOURCE_ROOT, current))
            for name, digest in files.items()}


def _data_controls(payload: dict) -> dict[str, dict]:
    from sec_xbrl.financial_storage_reuse import history_validation_rules
    from sec_xbrl.history_validation import _scope_key, validation_code_identity
    from sec_xbrl.metrics.statement_metric_evidence import (
        CONTINUITY_CATALOG,
        read_statement_metric_evidence,
    )

    v3 = payload.get("schema_version") == VERSION_V3
    producer = (payload["financial_producer_revision"] if v3 else
                _profile(payload)["producer_revision"] if payload.get("schema_version") == VERSION_V2 else PRODUCER)
    preparation = _checked_preparation(payload["preparation"])[0] if v3 else None
    parents = payload["parents"]
    if set(parents) != set(_PARENT_FILES):
        raise ValueError("native four parent roles differ")
    values = {name: read_json(_checked(pin)) for name, pin in parents.items()}
    ciks = payload["ciks"]
    if not ciks or ciks != sorted(set(ciks)):
        raise ValueError("native CIK scope differs")
    for name, body in values.items():
        if body.get("config", {}).get("source_compatibility") is not None:
            raise ValueError("native parent cannot carry a historical witness")
        actual = body.get("universe", {}).get("ciks") if name == "quarterly_metrics" else body.get("configured_ciks")
        if (body.get("schema_version") != _PARENT_SCHEMAS[name]
                or not isinstance(actual, list) or sorted(actual) != ciks
                or body.get("financial_as_of") != payload["financial_as_of"]):
            raise ValueError("native parent schema/company/cutoff differs")
        if Path(parents[name]["path"]).name != _PARENT_FILES[name]:
            raise ValueError("native parent manifest name differs")
    identity, annual, dataset, quarter = (values[n] for n in ("identity", "annual_metrics", "annual_dataset", "quarterly_metrics"))
    identity_pin = parents["identity"]
    expected_identity = {"kind": "GENERIC_METRIC_IDENTITY_ATTESTATION", "root": str(Path(identity_pin["path"]).parent),
                         "manifest_sha256": identity_pin["sha256"]}
    if (annual.get("config", {}).get("identity_source") != expected_identity
            or dataset.get("config", {}).get("identity_source") != expected_identity
            or dataset.get("config", {}).get("metric_manifest_sha256") != parents["annual_metrics"]["sha256"]
            or dataset["config"].get("metric_root") != str(Path(parents["annual_metrics"]["path"]).parent)
            or quarter.get("annual_parent", {}).get("manifest_sha256") != parents["annual_metrics"]["sha256"]
            or quarter.get("annual_parent", {}).get("generic_identity", {}).get("manifest_sha256") != identity_pin["sha256"]
            or quarter.get("catalog_version") != CONTINUITY_CATALOG or quarter.get("source_commit_sha") != producer
            or quarter.get("config", {}).get("statement_metric_evidence") != payload["statement_metric_evidence"]):
        raise ValueError("native parent/definition/producer linkage differs")
    quality = read_json(_checked(payload["quality"]))
    if (quality.get("producer_revision") != (PRODUCER if v3 else producer) or quality.get("financial_as_of") != payload["financial_as_of"]
            or identity.get("quality", {}).get("manifest_sha256") != payload["quality"]["sha256"]
            or identity["quality"].get("root") != str(Path(payload["quality"]["path"]).parent)
            or quality.get("storage_reuse") != (preparation["parent_storage_reuse"] if v3 else payload["storage_reuse"])
            or identity.get("config", {}).get("storage_reuse") != payload["storage_reuse"]):
        raise ValueError("native quality/storage linkage differs")
    read_statement_metric_evidence(payload["statement_metric_evidence"], payload["financial_as_of"])
    storage = read_json(_checked(payload["storage_reuse"]))
    controls = {**{f"PARENT:{n}": p for n, p in parents.items()},
                "QUALITY": payload["quality"], "EVIDENCE": payload["statement_metric_evidence"], "STORAGE": payload["storage_reuse"]}
    if (sorted(company["cik"] for company in storage["companies"]) != ciks
            or len({company["ticker"] for company in storage["companies"]}) != len(ciks)):
        raise ValueError("native storage company scope differs")
    routines = []
    for company in storage["companies"]:
        if company["cik"] not in ciks:
            raise ValueError("native routine company outside parent scope")
        for entry in company["histories"]:
            pins = {n: entry[n] for n in ("acceptance", "previous_validation", "build_manifest", "history_manifest")}
            prior = read_json(_checked(pins["previous_validation"]))
            report = prior.get("historical_controls", {}).get("report")
            body = read_json(_checked(report))
            history = read_json(_checked(pins["history_manifest"]))
            rules = history_validation_rules(history)
            old_identity = validation_code_identity(sources=tuple(sorted(Path(payload["source"]["old_root"]).rglob("*.py"))), rules=rules)
            if (body.get("code_identity") != old_identity or prior.get("kind") != "ACCEPTED_CURRENT_ROUTINE_HISTORY"
                    or body.get("version") != 1 or body.get("full_storage_validation") is not False
                    or body.get("semantic_validation") is not False
                    or body.get("scope_key") != _scope_key(history)
                    or body.get("publication_root") != str(Path(pins["history_manifest"]["path"]).parent)
                    or body.get("manifest_sha256") != pins["history_manifest"]["sha256"]
                    or body.get("validation_level") not in {"ROUTINE_INITIAL", "ROUTINE_CHANGED", "ROUTINE_UNCHANGED"}
                    or body.get("result", {}).get("declared_files") != prior.get("declared_payload_sha256s")):
                raise ValueError("native routine producer/rules/scope differ")
            claim = {"report": report, "pins": pins, "declared": prior["declared_payload_sha256s"], "rules": rules}
            routines.append(claim)
            for name, pin in {**pins, "report": report}.items():
                _checked(pin)
                controls[f"ROUTINE:{company['cik']}:{len(routines)}:{name}"] = pin
    if (routines != payload["routines"] or len(routines) != len(ciks)
            or len({claim["report"]["path"] for claim in routines}) != len(routines)):
        raise ValueError("native named routine scope differs")
    for pin in controls.values():
        _checked(pin)
    if v3:
        prep, prep_controls = _checked_preparation(payload["preparation"])
        if (identity["config"].get("native_preparation") != payload["preparation"]
                or prep["source"] != payload["source"] or prep["ciks"] != payload["ciks"]
                or prep["quality"] != payload["quality"] or prep["storage_reuse"] != payload["storage_reuse"]
                or prep["financial_producer_revision"] != producer or prep["routines"] != payload["routines"]
                or payload["statement_metric_evidence"] != read_json(_checked(prep["occurrence_inputs"]))["evidence"]):
            raise ValueError("final native parents differ from exact preparation scope/producer")
        controls.update(prep_controls)
    elif payload.get("schema_version") == VERSION_V2:
        controls.update(_occurrence_controls(payload, quality, identity))
    return controls


@dataclass(frozen=True, slots=True)
class _Scope:
    payload: dict
    controls: dict
    seal: str


_ACTIVE: ContextVar[_Scope | None] = ContextVar("financial_native_source", default=None)


def _active() -> _Scope | None:
    scope = _ACTIVE.get()
    if scope is not None:
        if digest_value([scope.payload, scope.controls]) != scope.seal:
            raise ValueError("native context mutated")
        _checked(scope.controls["PACKET"])
        _checked(scope.controls["APPROVAL"])
        _source_controls(scope.payload)
    return scope


@contextmanager
def use_native_source(declaration: dict | None, *, config: dict | None = None,
                      quarter_path: Path | None = None) -> Iterator[None]:
    scope = None
    if declaration is not None:
        if not isinstance(declaration, dict) or set(declaration) != {"packet", "approval"}:
            raise ValueError("native declaration requires explicit packet and ROOT receipt")
        packet_path = _checked(declaration["packet"])
        approval = read_json(_checked(declaration["approval"]))
        if approval != {"schema_version": (APPROVAL_VERSION_V3 if read_json(packet_path).get("schema_version") == VERSION_V3 else APPROVAL_VERSION_V2 if read_json(packet_path).get("schema_version") == VERSION_V2 else APPROVAL_VERSION), "status": "ROOT_APPROVED_NATIVE_SOURCE_TRANSITION",
                        "packet": declaration["packet"]}:
            raise ValueError("native ROOT receipt differs")
        payload = read_json(packet_path)
        fields = {"schema_version", "producer_revision", "financial_as_of", "ciks", "parents", "quality",
                  "statement_metric_evidence", "storage_reuse", "source", "routines"}
        v2 = payload.get("schema_version") == VERSION_V2
        v3 = payload.get("schema_version") == VERSION_V3
        if v2:
            fields |= {"producer_profile", "consumer_baseline_files", "occurrence_inputs"}
        if v3:
            fields |= {"preparation", "financial_producer_revision", "consumer_baseline_files"}
        if (set(payload) != fields or payload.get("schema_version") not in {VERSION, VERSION_V2, VERSION_V3}
                or payload["producer_revision"] != (_profile(payload)["producer_revision"] if v2 else PRODUCER)):
            raise ValueError("native packet contract differs")
        controls = {"PACKET": declaration["packet"], "APPROVAL": declaration["approval"],
                    **_source_controls(payload), **_data_controls(payload)}
        if config is not None:
            p = payload["parents"]
            if (config.get("source_compatibility") is not None or "quarterly_successor" in config
                    or config.get("annual_manifest_sha256") != p["annual_dataset"]["sha256"]
                    or config.get("quarterly_manifest_sha256") != p["quarterly_metrics"]["sha256"]
                    or Path(config.get("annual_dataset_root", "")) != Path(p["annual_dataset"]["path"]).parent
                    or Path(config.get("quarterly_metric_root", "")) != Path(p["quarterly_metrics"]["path"]).parent
                    or (quarter_path is not None and quarter_path != Path(p["quarterly_metrics"]["path"]))):
                raise ValueError("native invocation mixes parent or historical scopes")
        scope = _Scope(payload, controls, digest_value([payload, controls]))
    token = _ACTIVE.set(scope)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def native_policy_matches(old: dict, current: dict, declaration: dict) -> bool:
    scope = _active()
    if scope is None or declaration != scope.payload["storage_reuse"]:
        return False
    source = scope.payload["source"]
    return (old == {n: source["old_files"].get(n.removeprefix("src/sec_xbrl/")) for n in current}
            and current == {n: source["current_files"].get(n.removeprefix("src/sec_xbrl/")) for n in current})


def native_routine_matches(*, report: dict, pins: dict, declared: dict, rules: dict, current_identity: str) -> bool:
    from sec_xbrl.history_validation import validation_code_identity
    scope = _active()
    if scope is None:
        return False
    claim = {"report": report, "pins": pins, "declared": declared, "rules": rules}
    if claim not in scope.payload["routines"]:
        return False
    _checked(report)
    return current_identity == validation_code_identity(
        sources=tuple(sorted(_SOURCE_ROOT.rglob("*.py"))), rules=rules)


def native_controls() -> tuple[dict[str, dict], tuple[Path, ...]]:
    scope = _active()
    if scope is None:
        return {}, ()
    return copy.deepcopy(scope.controls), (Path(scope.payload["source"]["old_root"]), _SOURCE_ROOT)


def native_assessed_ciks(*, collection_manifest: Path, scope_companies: list | tuple) -> tuple[str, ...] | None:
    """Return only the explicit native parent assessment; default callers stay full."""
    scope = _active()
    if scope is None:
        return None
    config = _assessment_config(scope.payload)
    expected = sorted((row["ticker"], row["cik"]) for row in config["companies"])
    actual = sorted((row["ticker"], row["cik"]) for row in scope_companies)
    if (actual != expected or str(collection_manifest) != config["collection_manifest"]):
        raise ValueError("native status caller collection/company scope differs")
    return tuple(scope.payload["ciks"])


def require_native_assessment(assessed_ciks: tuple[str, ...] | None, *, collection_manifest: Path,
                              validation_mode: str, storage_reuse: dict | None) -> None:
    scope = _active()
    if scope is None:
        return
    config = _assessment_config(scope.payload)
    if (assessed_ciks != tuple(scope.payload["ciks"])
            or str(collection_manifest) != config["collection_manifest"]
            or validation_mode != "financial_sources" or storage_reuse != scope.payload["storage_reuse"]):
        raise ValueError("native status requires its exact explicit assessment subset")


def prepare_native_source_packet(*, parents: dict[str, dict], old_source_root: Path,
                                 destination: Path, producer_profile: str | None = None,
                                 consumer_baseline_files: dict | None = None, occurrence_inputs: dict | None = None,
                                 preparation: dict | None = None) -> Path:
    """Write a proposal only; a separate pinned ROOT approval is mandatory."""
    from sec_xbrl.financial_storage_reuse import history_validation_rules
    identity = read_json(_checked(parents["identity"]))
    quarter = read_json(_checked(parents["quarterly_metrics"]))
    quality = _pin(Path(identity["quality"]["root"]) / "generic_metric_quality_manifest.json")
    storage_pin = identity["config"]["storage_reuse"]
    storage = read_json(_checked(storage_pin))
    routines = []
    for company in storage["companies"]:
        for entry in company["histories"]:
            pins = {n: entry[n] for n in ("acceptance", "previous_validation", "build_manifest", "history_manifest")}
            prior = read_json(_checked(pins["previous_validation"]))
            history = read_json(_checked(pins["history_manifest"]))
            routines.append({"report": prior["historical_controls"]["report"], "pins": pins,
                             "declared": prior["declared_payload_sha256s"], "rules": history_validation_rules(history)})
    payload = {"schema_version": VERSION, "producer_revision": PRODUCER, "financial_as_of": identity["financial_as_of"],
               "ciks": identity["configured_ciks"], "parents": parents, "quality": quality,
               "statement_metric_evidence": quarter["config"]["statement_metric_evidence"], "storage_reuse": storage_pin,
               "source": {"old_root": str(old_source_root), "old_files": _inventory(old_source_root),
                          "current_files": _inventory(_SOURCE_ROOT)}, "routines": routines}
    if preparation is not None:
        if producer_profile is not None or consumer_baseline_files is not None or occurrence_inputs is not None:
            raise ValueError("final native preparation cannot mix older profile contracts")
        prep, _ = _checked_preparation(preparation)
        payload.update(schema_version=VERSION_V3, preparation=preparation,
                       financial_producer_revision=prep["financial_producer_revision"],
                       consumer_baseline_files=prep["consumer_baseline_files"])
    elif producer_profile is not None:
        payload.update(schema_version=VERSION_V2, producer_profile=producer_profile,
                       consumer_baseline_files=consumer_baseline_files, occurrence_inputs=occurrence_inputs)
        payload["producer_revision"] = _profile(payload)["producer_revision"]
    elif consumer_baseline_files is not None or occurrence_inputs is not None:
        raise ValueError("native v2 controls require an explicit named profile")
    _source_controls(payload)
    _data_controls(payload)
    if destination.exists():
        raise ValueError("native proposal destination must be new")
    write_json(destination, payload)
    return destination


def _profile(payload: dict) -> dict:
    profile = _PRODUCER_PROFILES.get(payload.get("producer_profile"))
    if profile is None:
        raise ValueError("native producer profile is not qualified")
    return profile


def qualified_consumer_files(baseline: dict, current: dict) -> None:
    """Accept only named consumer changes from the exact merged acceptance baseline."""
    if not isinstance(baseline, dict) or digest_value(baseline) != _CONSUMER_BASELINE_INVENTORY:
        raise ValueError("consumer acceptance baseline inventory differs")
    if set(baseline) != set(current):
        raise ValueError("consumer source additions/removals differ")
    changed = {name for name in baseline if baseline[name] != current[name]}
    if not changed <= _CONSUMER_CHANGES:
        raise ValueError("consumer changes an unqualified accounting/source module")
    if any(current.get(name) != value for name, value in _PARTIAL_CONSUMER_FILES.items()):
        raise ValueError("consumer partial-window transplant or invariant arithmetic differs")


def _source_controls_v2(payload: dict) -> dict:
    profile = _profile(payload)
    source = payload["source"]
    if set(source) != {"old_root", "old_files", "current_files"}:
        raise ValueError("native source fields differ")
    old_root = Path(source["old_root"])
    old, current = _inventory(old_root), _inventory(_SOURCE_ROOT)
    if (old != source["old_files"] or digest_value(old) != profile["origin_inventory"]
            or current != source["current_files"]):
        raise ValueError("native named producer/current inventory differs")
    qualified_consumer_files(payload["consumer_baseline_files"], current)
    return {f"{kind}:{name}": {"path": str(directory / name), "sha256": digest}
            for kind, directory, files in (("OLD_SOURCE", old_root, old), ("CURRENT_SOURCE", _SOURCE_ROOT, current))
            for name, digest in files.items()}


def _occurrence_controls(payload: dict, quality: dict, identity: dict) -> dict:
    profile = _profile(payload)
    if (quality.get("rule_versions") != profile["quality_rules"]
            or sorted(quality.get("parser_profiles", []), key=digest_value) != sorted(profile["parser_profiles"], key=digest_value)):
        raise ValueError("native quality/parser profile differs")
    policy = identity["config"].get("annual_coverage_policy")
    expected = profile["annual_coverage_policy"]
    if policy != (None if expected == "STRICT_5_INPUT_4_DISPLAY" else expected):
        raise ValueError("native named annual coverage policy differs")
    controls = {"OCCURRENCE_INPUTS": payload["occurrence_inputs"]}
    inputs = read_json(_checked(payload["occurrence_inputs"]))
    evidence = read_json(_checked(payload["statement_metric_evidence"]))
    if (inputs.get("evidence") != payload["statement_metric_evidence"] or inputs.get("admitted_records") != 0
            or evidence.get("records") != [] or not isinstance(inputs.get("selected_filings"), list)):
        raise ValueError("native empty occurrence requires its exact input inventory")
    controls["OCCURRENCE_PLAN"] = inputs["cohort_plan"]
    _checked(inputs["cohort_plan"])
    expected_entries = {}
    intakes = {}
    for company in quality["collection_status"]:
        pin = {"path": company["intake_manifest_path"], "sha256": company["intake_sha256"]}
        intake = read_json(_checked(pin))
        if not intake.get("complete"):
            raise ValueError("native occurrence intake is incomplete")
        controls[f"OCCURRENCE_INTAKE:{company['cik']}"] = pin
        intakes[company["cik"]] = pin
        for entry in intake["filings"]:
            if entry.get("status") not in {"INGESTED", "REUSED"}:
                raise ValueError("native occurrence intake is not accepted")
            ref = entry["filing"]
            key = (ref["cik"], ref["accession"])
            if key in expected_entries or ref["cik"] != company["cik"]:
                raise ValueError("native occurrence intake scope conflicts")
            expected_entries[key] = entry
    actual = set()
    for index, row in enumerate(inputs["selected_filings"]):
        scope = row["scope"]
        key = (scope["cik"], scope["accession"])
        checkpoint = read_json(_checked(row["checkpoint"]))
        if (key in actual or key not in expected_entries or scope["entry"] != expected_entries[key]
                or scope["intake"] != intakes[scope["cik"]] or scope["financial_as_of"] != payload["financial_as_of"]
                or scope["builder_sha256"] != payload["source"]["old_files"]["metrics/statement_metric_evidence.py"]
                or scope["entry"]["filing"]["filed_date"] > payload["financial_as_of"]
                or checkpoint != {"input": scope, "records": []} or row["admitted_records"] != 0):
            raise ValueError("native occurrence checkpoint/scope differs")
        expected_path = Path(scope["entry"]["source_run"]) / "snapshots" / scope["cik"] / scope["accession"].replace("-", "") / "layer1_manifest.json"
        if Path(scope["snapshot_manifest"]["path"]) != expected_path:
            raise ValueError("native occurrence Raw parent differs")
        _checked(scope["snapshot_manifest"])
        controls[f"OCCURRENCE_CHECKPOINT:{index}"] = row["checkpoint"]
        controls[f"OCCURRENCE_RAW:{index}"] = scope["snapshot_manifest"]
        actual.add(key)
    if actual != set(expected_entries) or set(intakes) != set(payload["ciks"]):
        raise ValueError("native occurrence filing/company coverage differs")
    return controls


PREPARATION_VERSION = "financial-native-preparation-v1"
PREPARATION_APPROVAL = "financial-native-preparation-approval-v1"
VERSION_V3 = "financial-native-source-v3"
APPROVAL_VERSION_V3 = "financial-native-source-approval-v3"
_PREPARATION_BASELINE = "0dc4cbb7a8023e4c8ff0b98cbc69359c7ad343cf8045b255de93ab796f5dfacc"
_IDENTITY_CORE = "f3a52b12234f2574614b18be7283920ce114d93197a2af863bf83b0f90d1d49c"
_PREPARATION_CHANGES = frozenset({"financial_native_source.py", "screening/metric_identity.py",
    "screening/verified_source_closure.py", "screening/governed_delta.py", "screening/cohort_union.py", "screening/service.py"})


def qualified_preparation_consumer_files(baseline: dict, current: dict) -> None:
    if digest_value(baseline) != _PREPARATION_BASELINE or set(baseline) != set(current):
        raise ValueError("preparation consumer baseline/file scope differs")
    if {name for name in baseline if baseline[name] != current[name]} - _PREPARATION_CHANGES:
        raise ValueError("preparation changes an unqualified financial/source module")
    tree = ast.parse((_SOURCE_ROOT / "screening/metric_identity.py").read_text())
    excluded = {"publish_generic_metric_identity", "_publish_generic_metric_identity", "_verify_configured_sources",
                "_verify_configured_sources_inner", "_validate_config"}
    core = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in excluded:
            core[node.name] = ast.dump(node, include_attributes=False)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    core[node.name + "." + child.name] = ast.dump(child, include_attributes=False)
    if digest_value(core) != _IDENTITY_CORE:
        raise ValueError("preparation changes identity core selection/period rules")


def _preparation_source_controls(payload: dict) -> dict:
    source = payload["source"]
    if set(source) != {"old_root", "old_files", "current_files"}:
        raise ValueError("preparation source fields differ")
    old_root = Path(source["old_root"])
    old, current = _inventory(old_root), _inventory(_SOURCE_ROOT)
    if old != source["old_files"] or digest_value(old) != _ORIGIN_INVENTORY or current != source["current_files"]:
        raise ValueError("preparation exact401/current source inventory differs")
    qualified_preparation_consumer_files(payload["consumer_baseline_files"], current)
    return {f"{kind}:{name}": {"path": str(directory / name), "sha256": digest}
            for kind, directory, files in (("OLD_SOURCE", old_root, old), ("CURRENT_SOURCE", _SOURCE_ROOT, current))
            for name, digest in files.items()}


def _assessment_config(payload: dict) -> dict:
    return (payload["identity_request"] if payload["schema_version"] == PREPARATION_VERSION
            else read_json(_checked(payload["parents"]["identity"]))["config"])


def _routine_claims(storage: dict) -> list[dict]:
    from sec_xbrl.financial_storage_reuse import history_validation_rules
    claims = []
    for company in storage["companies"]:
        for entry in company["histories"]:
            pins = {name: entry[name] for name in ("acceptance", "previous_validation", "build_manifest", "history_manifest")}
            prior = read_json(_checked(pins["previous_validation"]))
            manifest = read_json(_checked(pins["history_manifest"]))
            claims.append({"report": prior["historical_controls"]["report"], "pins": pins,
                           "declared": prior["declared_payload_sha256s"], "rules": history_validation_rules(manifest)})
    return claims


def _preparation_controls(payload: dict) -> dict:
    from sec_xbrl.history_validation import _scope_key, validation_code_identity
    from sec_xbrl.metric_quality import GenericMetricQualityReader

    required = {"schema_version", "producer_revision", "financial_producer_revision", "financial_as_of", "ciks",
                "source", "consumer_baseline_files", "identity_request", "quality", "parent_storage_reuse",
                "storage_reuse", "occurrence_inputs", "selected_occurrences", "routines"}
    if (set(payload) != required or payload["schema_version"] != PREPARATION_VERSION
            or payload["producer_revision"] != PRODUCER or len(payload["financial_producer_revision"]) != 40
            or any(c not in "0123456789abcdef" for c in payload["financial_producer_revision"])):
        raise ValueError("preparation packet/producer contract differs")
    controls = _preparation_source_controls(payload)
    from sec_xbrl.screening.metric_identity import _validate_config
    request = payload["identity_request"]
    if _validate_config(request) != request:
        raise ValueError("preparation identity request is not canonical")
    companies = sorted(({"ticker": row["ticker"], "cik": row["cik"]} for row in request["companies"]), key=lambda row: row["cik"])
    if (payload["ciks"] != sorted({row["cik"] for row in companies}) or not payload["ciks"]
            or "native_preparation" in request or "source_compatibility" in request
            or request["financial_as_of"] != payload["financial_as_of"]
            or request.get("annual_coverage_policy") is not None or request["storage_reuse"] != payload["storage_reuse"]):
        raise ValueError("preparation identity scope differs")
    quality_path = _checked(payload["quality"])
    quality = GenericMetricQualityReader(quality_path.parent, manifest_sha256=payload["quality"]["sha256"])
    q = quality.manifest
    if (q["producer_revision"] != PRODUCER or q["financial_as_of"] != payload["financial_as_of"]
            or q["storage_reuse"] != payload["parent_storage_reuse"]
            or request["quality_root"] != str(quality.root) or request["quality_manifest_sha256"] != payload["quality"]["sha256"]
            or not {(r["ticker"], r["cik"]) for r in companies} < {(r["ticker"], r["cik"]) for r in q["companies"]}):
        raise ValueError("preparation requires a strict subset of the exact401 quality proof")
    controls["PREPARATION_QUALITY"] = payload["quality"]
    controls["PREPARATION_STORAGE_PARENT"] = payload["parent_storage_reuse"]
    controls["PREPARATION_STORAGE"] = payload["storage_reuse"]
    parent_storage = read_json(_checked(payload["parent_storage_reuse"]))
    storage = read_json(_checked(payload["storage_reuse"]))
    expected = {**parent_storage, "companies": [row for row in parent_storage["companies"] if row["cik"] in payload["ciks"]]}
    if storage != expected or sorted(row["cik"] for row in storage["companies"]) != payload["ciks"]:
        raise ValueError("preparation storage subset changes original proof records")
    if parent_storage["collection_manifest"]["sha256"] != q["collection_manifest_sha256"] or request["collection_manifest_sha256"] != q["collection_manifest_sha256"]:
        raise ValueError("preparation collection differs from quality/storage")
    if storage["collection_manifest"]["path"] != request["collection_manifest"]:
        raise ValueError("preparation collection path differs")
    if payload["routines"] != _routine_claims(storage) or len(payload["routines"]) != len(companies):
        raise ValueError("preparation routine scope differs")
    for index, claim in enumerate(payload["routines"]):
        report = read_json(_checked(claim["report"]))
        history = read_json(_checked(claim["pins"]["history_manifest"]))
        prior = read_json(_checked(claim["pins"]["previous_validation"]))
        old_identity = validation_code_identity(sources=tuple(sorted(Path(payload["source"]["old_root"]).rglob("*.py"))), rules=claim["rules"])
        if (report.get("code_identity") != old_identity or report.get("scope_key") != _scope_key(history)
                or report.get("manifest_sha256") != claim["pins"]["history_manifest"]["sha256"]
                or report.get("full_storage_validation") is not False or report.get("semantic_validation") is not False
                or report.get("validation_level") not in {"ROUTINE_INITIAL", "ROUTINE_CHANGED", "ROUTINE_UNCHANGED"}
                or prior.get("kind") != "ACCEPTED_CURRENT_ROUTINE_HISTORY"
                or report.get("result", {}).get("declared_files") != claim["declared"]):
            raise ValueError("preparation does not reuse an exact unchanged401 routine")
        for name, pin in {**claim["pins"], "report": claim["report"]}.items():
            _checked(pin)
            controls[f"PREPARATION_ROUTINE:{index}:{name}"] = pin
    def add_pins(value, prefix):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                pin = {name: value[name] for name in ("path", "sha256")}
                _checked(pin)
                controls[prefix] = pin
            else:
                for key, item in value.items():
                    add_pins(item, prefix + ":" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                add_pins(item, prefix + ":" + str(index))
    add_pins(q["evidence_hashes"], "PREPARATION_QUALITY_CONTROL")
    for name, info in q["files"].items():
        add_pins({"path": str(quality.root / name), "sha256": info["sha256"]}, "PREPARATION_QUALITY_FILE:" + name)
    for company in request["companies"]:
        for role in ("history", "annual_analysis", "quarterly_analysis"):
            filename = "history_manifest.json" if role == "history" else "analysis_manifest.json"
            add_pins({"path": str(Path(company[role + "_root"]) / filename), "sha256": company[role + "_manifest_sha256"]},
                     "PREPARATION_ANALYSIS:" + company["cik"] + ":" + role)
        if len(company["input_years"]) != 5 or len(company["display_years"]) != 4:
            raise ValueError("preparation cannot alter the strict annual window")
    inputs = read_json(_checked(payload["occurrence_inputs"]))
    controls["PREPARATION_OCCURRENCE_INPUTS"] = payload["occurrence_inputs"]
    evidence = read_json(_checked(inputs["evidence"]))
    if inputs["admitted_records"] != 0 or evidence["records"] != [] or evidence["financial_as_of"] != payload["financial_as_of"]:
        raise ValueError("preparation occurrence proof differs")
    expected_full = {(row["cik"], row["accession"]) for row in q["filings"]}
    if {(row["scope"]["cik"], row["scope"]["accession"]) for row in inputs["selected_filings"]} != expected_full or len(inputs["selected_filings"]) != len(expected_full):
        raise ValueError("preparation occurrence parent coverage differs")
    selected = [row for row in inputs["selected_filings"] if row["scope"]["cik"] in payload["ciks"]]
    if selected != payload["selected_occurrences"]:
        raise ValueError("preparation occurrence subset differs")
    statuses = {row["cik"]: row for row in q["collection_status"]}
    for index, row in enumerate(selected):
        scope = row["scope"]
        status = statuses[scope["cik"]]
        intake_pin = {"path": status["intake_manifest_path"], "sha256": status["intake_sha256"]}
        intake = read_json(_checked(intake_pin))
        if (scope["entry"] not in intake["filings"] or scope["intake"] != intake_pin
                or scope["financial_as_of"] != payload["financial_as_of"] or row["admitted_records"] != 0
                or scope["builder_sha256"] != payload["source"]["old_files"]["metrics/statement_metric_evidence.py"]
                or read_json(_checked(row["checkpoint"])) != {"input": scope, "records": []}):
            raise ValueError("preparation occurrence checkpoint does not belong to selected source")
        controls[f"PREPARATION_OCCURRENCE_CHECKPOINT:{index}"] = row["checkpoint"]
    add_pins(inputs["evidence"], "PREPARATION_OCCURRENCE_EVIDENCE")
    return controls


def _checked_preparation(declaration: dict) -> tuple[dict, dict]:
    if not isinstance(declaration, dict) or set(declaration) != {"packet", "approval"}:
        raise ValueError("preparation requires an explicit packet/root receipt")
    packet = read_json(_checked(declaration["packet"]))
    approval = read_json(_checked(declaration["approval"]))
    if approval != {"schema_version": PREPARATION_APPROVAL, "status": "ROOT_APPROVED_NATIVE_PREPARATION", "packet": declaration["packet"]}:
        raise ValueError("preparation root receipt differs")
    return packet, {"PACKET": declaration["packet"], "APPROVAL": declaration["approval"], **_preparation_controls(packet)}


@contextmanager
def use_native_preparation(declaration: dict | None, *, config: dict | None = None) -> Iterator[None]:
    if declaration is None:
        active = _ACTIVE.get()
        token = _ACTIVE.set(None if active is not None and active.payload["schema_version"] == PREPARATION_VERSION else active)
        try:
            yield
        finally:
            _ACTIVE.reset(token)
        return
    payload, controls = _checked_preparation(declaration)
    if config is not None and {key: value for key, value in config.items() if key != "native_preparation"} != payload["identity_request"]:
        raise ValueError("preparation identity request differs")
    scope = _Scope(payload, controls, digest_value([payload, controls]))
    token = _ACTIVE.set(scope)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def verify_prepared_quality(reader, *, config: dict, history_hashes: dict) -> None:
    scope = _active()
    if scope is None or scope.payload["schema_version"] != PREPARATION_VERSION or config.get("native_preparation") != {"packet": scope.controls["PACKET"], "approval": scope.controls["APPROVAL"]}:
        raise ValueError("quality subset requires its sealed preparation context")
    payload = scope.payload
    q = reader.manifest
    if (_pin(reader.manifest_path) != payload["quality"]
            or history_hashes != {row["ticker"]: q["history_manifest_sha256s"][row["ticker"]] for row in config["companies"]}
            or config.get("prospective_selection") != q.get("prospective_selection")
            or config.get("history_selection") != q.get("history_selection")):
        raise ValueError("quality selected source proof differs")


def prepare_native_preparation_packet(*, identity_config: dict, old_source_root: Path, consumer_baseline_files: dict,
                                      occurrence_inputs: dict, financial_producer_revision: str, destination: Path) -> Path:
    from sec_xbrl.screening.metric_identity import _validate_config
    config = _validate_config(identity_config)
    if "native_preparation" in config:
        raise ValueError("preparation proposal cannot recursively contain itself")
    quality_pin = _pin(Path(config["quality_root"]) / "generic_metric_quality_manifest.json")
    quality = read_json(_checked(quality_pin))
    storage = read_json(_checked(config["storage_reuse"]))
    inputs = read_json(_checked(occurrence_inputs))
    ciks = [row["cik"] for row in config["companies"]]
    payload = {"schema_version": PREPARATION_VERSION, "producer_revision": PRODUCER,
        "financial_producer_revision": financial_producer_revision, "financial_as_of": config["financial_as_of"], "ciks": ciks,
        "source": {"old_root": str(old_source_root), "old_files": _inventory(old_source_root), "current_files": _inventory(_SOURCE_ROOT)},
        "consumer_baseline_files": consumer_baseline_files, "identity_request": config, "quality": quality_pin,
        "parent_storage_reuse": quality["storage_reuse"], "storage_reuse": config["storage_reuse"],
        "occurrence_inputs": occurrence_inputs, "selected_occurrences": [row for row in inputs["selected_filings"] if row["scope"]["cik"] in ciks],
        "routines": _routine_claims(storage)}
    _preparation_controls(payload)
    if destination.exists():
        raise ValueError("preparation proposal destination must be new")
    write_json(destination, payload)
    return destination
