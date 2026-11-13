"""Exact native producer transition; independent of historical successor packets."""
from __future__ import annotations

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
            or quarter.get("catalog_version") != CONTINUITY_CATALOG or quarter.get("source_commit_sha") != PRODUCER
            or quarter.get("config", {}).get("statement_metric_evidence") != payload["statement_metric_evidence"]):
        raise ValueError("native parent/definition/producer linkage differs")
    quality = read_json(_checked(payload["quality"]))
    if (quality.get("producer_revision") != PRODUCER or quality.get("financial_as_of") != payload["financial_as_of"]
            or identity.get("quality", {}).get("manifest_sha256") != payload["quality"]["sha256"]
            or identity["quality"].get("root") != str(Path(payload["quality"]["path"]).parent)
            or quality.get("storage_reuse") != payload["storage_reuse"]
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
        if approval != {"schema_version": APPROVAL_VERSION, "status": "ROOT_APPROVED_NATIVE_SOURCE_TRANSITION",
                        "packet": declaration["packet"]}:
            raise ValueError("native ROOT receipt differs")
        payload = read_json(packet_path)
        if (set(payload) != {"schema_version", "producer_revision", "financial_as_of", "ciks", "parents", "quality",
                            "statement_metric_evidence", "storage_reuse", "source", "routines"}
                or payload["schema_version"] != VERSION or payload["producer_revision"] != PRODUCER):
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
    identity = read_json(_checked(scope.payload["parents"]["identity"]))
    expected = sorted((row["ticker"], row["cik"]) for row in identity["config"]["companies"])
    actual = sorted((row["ticker"], row["cik"]) for row in scope_companies)
    if (actual != expected or str(collection_manifest) != identity["config"]["collection_manifest"]):
        raise ValueError("native status caller collection/company scope differs")
    return tuple(scope.payload["ciks"])


def require_native_assessment(assessed_ciks: tuple[str, ...] | None, *, collection_manifest: Path,
                              validation_mode: str, storage_reuse: dict | None) -> None:
    scope = _active()
    if scope is None:
        return
    identity = read_json(_checked(scope.payload["parents"]["identity"]))
    if (assessed_ciks != tuple(scope.payload["ciks"])
            or str(collection_manifest) != identity["config"]["collection_manifest"]
            or validation_mode != "financial_sources" or storage_reuse != scope.payload["storage_reuse"]):
        raise ValueError("native status requires its exact explicit assessment subset")


def prepare_native_source_packet(*, parents: dict[str, dict], old_source_root: Path,
                                 destination: Path) -> Path:
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
    _source_controls(payload)
    _data_controls(payload)
    if destination.exists():
        raise ValueError("native proposal destination must be new")
    write_json(destination, payload)
    return destination
