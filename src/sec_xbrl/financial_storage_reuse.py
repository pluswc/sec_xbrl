"""Explicit ROOT-approved storage proof reuse for financial attestation only.

The legacy typed decoder stays unchanged. This boundary reuses a pinned completed
storage check and verifies governed input bytes. V1 also hashes retained physical
files; explicit V2 checks their safe topology only. Neither makes a new semantic
audit claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.history_selection import _pin
from sec_xbrl.screening.common import (
    digest_value,
    read_json,
    require_cik,
    require_ticker,
    sha256_file,
)

VERSION = "financial-history-storage-reuse-v1"
VERSION_V2 = "financial-history-storage-reuse-v2"
DIAGNOSTIC_POLICY = "NONCONSUMED_TOPOLOGY_ONLY"
_ISSUER = object()
_POLICY = ("history.py", "history_validation.py", "collection_operations.py",
           "history_selection.py", "financial_storage_reuse.py")


def financial_storage_policy_sources() -> dict[str, str]:
    root = Path(__file__).parent
    return {f"src/sec_xbrl/{name}": sha256_file(root / name) for name in _POLICY}


@dataclass(frozen=True)
class FinancialStorageReuse:
    declaration: dict[str, str]
    companies: dict[str, dict[str, Any]]
    controls: dict[str, dict[str, str]]
    _issuer: object
    _seal: str


def resolve_storage_reuse(declaration: dict, *, collection_manifest: Path,
                          scope_companies: list[dict]) -> FinancialStorageReuse:
    from sec_xbrl.collection_operations import (
        _attest_intake,
        _declared_publication_files,
        _validate_build_attestation,
    )
    from sec_xbrl.history import HistoryPublicationReader

    declaration = _pin(declaration)
    payload = read_json(Path(declaration["path"]))
    fields = {"schema_version", "status", "collection_manifest", "current_policy_source_sha256s", "companies"}
    v2 = isinstance(payload, dict) and payload.get("schema_version") == VERSION_V2
    if v2:
        fields.add("diagnostic_policy")
    if (not isinstance(payload, dict) or set(payload) != fields
        or payload.get("schema_version") not in {VERSION, VERSION_V2}
        or (v2 and payload.get("diagnostic_policy") != DIAGNOSTIC_POLICY)
        or payload.get("status") != "ROOT_APPROVED"
        or payload.get("current_policy_source_sha256s") != financial_storage_policy_sources()):
        raise ValueError("storage reuse requires exact ROOT-approved current policy compatibility")
    collection_pin = _pin(payload["collection_manifest"])
    if collection_pin["path"] != str(collection_manifest.resolve()):
        raise ValueError("storage reuse collection differs")
    collection = read_json(collection_manifest)
    parent = {(row["ticker"], row["cik"]): row for row in collection["companies"]}
    scope = {(row["ticker"], row["cik"]) for row in scope_companies}
    entries = payload["companies"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("storage reuse needs explicit company proofs")
    result = {}
    controls = {"STORAGE_REUSE": declaration, "COLLECTION": collection_pin}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"ticker", "cik", "histories"}:
            raise ValueError("storage reuse company fields differ")
        ticker = require_ticker(entry["ticker"], "storage reuse ticker")
        cik = require_cik(entry["cik"], "storage reuse CIK")
        if ticker != entry["ticker"] or ticker in result or (ticker,cik) not in parent or (ticker,cik) not in scope:
            raise ValueError("storage reuse company is duplicated or outside scope")
        histories = entry["histories"]
        if not isinstance(histories, list) or not histories:
            raise ValueError("storage reuse needs explicit History proofs")
        result[ticker] = {"ticker":ticker, "cik":cik, "histories":[]}
        seen = set()
        for history_index, history_entry in enumerate(histories):
            history_fields = {"acceptance", "previous_validation", "build_manifest", "history_manifest", "payload_inventory"}
            if v2:
                history_fields.add("retained_diagnostics")
            if not isinstance(history_entry, dict) or set(history_entry) != history_fields:
                raise ValueError("storage reuse History fields differ")
            history_path = history_entry["history_manifest"].get("path")
            if history_path in seen:
                raise ValueError("duplicate storage reuse History proof")
            seen.add(history_path)
            pins = {name: _pin(history_entry[name]) for name in ("acceptance", "previous_validation", "build_manifest", "history_manifest")}
            prior = read_json(Path(pins["previous_validation"]["path"]))
            manifest = read_json(Path(pins["history_manifest"]["path"]))
            root = Path(pins["history_manifest"]["path"]).parent
            # Explicit ROOT approval binds historical acceptance as an opaque JSON
            # witness. Do not recurse into old audits, code trees, or Raw inventories.
            if not isinstance(read_json(Path(pins["acceptance"]["path"])), dict):
                raise TypeError("storage reuse acceptance witness is malformed")
            HistoryPublicationReader(root)  # enforce any public recovery gate
            declared = _declared_publication_files(root, manifest)
            if prior.get("kind") == "ACCEPTED_CURRENT_ROUTINE_HISTORY":
                if not v2:
                    raise ValueError("current routine evidence requires explicit v2 scope")
                historical = _current_routine_evidence(prior, pins=pins, declared=declared)
                controls.update({f"{ticker}:{history_index}:CURRENT:{name}": pin
                                 for name,pin in historical.items()})
            elif prior.get("schema_version") == "accepted-financial-storage-evidence-v1":
                historical = _normalized_evidence(prior, pins=pins, declared=declared,
                                                  ticker=ticker, cik=cik)
                controls.update({f"{ticker}:{history_index}:HISTORICAL:{name}": pin
                                 for name,pin in historical.items()})
            else:
                if (prior.get("version") != 1 or prior.get("full_storage_validation") is not True
                    or prior.get("validation_level") not in {"DETAILED", "DETAILED_FALLBACK"}
                    or prior.get("manifest_sha256") != pins["history_manifest"]["sha256"]
                    or prior.get("publication_root") != str(root)):
                    raise ValueError("storage reuse prior validation is not a completed exact typed storage proof")
                prior_files = prior.get("files")
                if not isinstance(prior_files, dict) or {name:info.get("sha256") for name,info in prior_files.items()} != declared:
                    raise ValueError("storage reuse prior declared payload hashes differ")
            inventory = history_entry["payload_inventory"]
            if not isinstance(inventory, dict) or not set(declared) <= set(inventory) or inventory.get("history_manifest.json") != pins["history_manifest"]["sha256"]:
                raise ValueError("storage reuse physical payload inventory is incomplete")
            from sec_xbrl.history_selection import _retained_diagnostic
            diagnostics = history_entry.get("retained_diagnostics") if v2 else None
            if v2:
                if (not isinstance(diagnostics, list) or diagnostics != sorted(set(diagnostics))
                    or set(inventory) != set(declared) | {"history_manifest.json"}
                    or any(not _retained_diagnostic(name, set(declared)) for name in diagnostics)):
                    raise ValueError("v2 storage reuse diagnostic scope is unsafe or differs")
            else:
                extras = set(inventory) - set(declared) - {"history_manifest.json"}
                if any(not _retained_diagnostic(relative, set(declared)) for relative in extras):
                    raise ValueError("storage reuse inventory includes an unknown retained payload")
            _verify_payload_inventory(root, inventory, diagnostics)
            company = parent[(ticker,cik)]
            plan_path = Path(company["plan_path"])
            plan = read_json(plan_path)
            intake = collection_manifest.parent/"companies"/ticker/"intake/history_intake.json"
            build = read_json(Path(pins["build_manifest"]["path"]))
            if (build.get("status") != "READY" or build.get("history_manifest") != pins["history_manifest"]["path"]
                or build.get("history_manifest_sha256") != pins["history_manifest"]["sha256"]):
                raise ValueError("storage reuse build does not bind the approved History")
            error = _validate_build_attestation(build, ticker=ticker, plan=plan,
                        plan_sha256=company["plan_sha256"], intake_path=intake,
                        intake=_attest_intake(intake,plan))
            if error:
                raise ValueError(f"storage reuse original build provenance failed: {error}")
            for name,pin in pins.items():
                controls[f"{ticker}:{history_index}:{name}"] = pin
            for name in ("request_path",):
                path=Path(collection[name]);controls[f"{ticker}:{history_index}:{name}"]=_pin({"path":str(path),"sha256":collection["request_sha256"]})
            controls[f"{ticker}:{history_index}:plan"]=_pin({"path":str(plan_path),"sha256":company["plan_sha256"]})
            controls[f"{ticker}:{history_index}:intake"]=_pin({"path":str(intake),"sha256":build["intake_sha256"]})
            result[ticker]["histories"].append({**history_entry, **pins})
    return FinancialStorageReuse(declaration,result,controls,_ISSUER,digest_value([declaration,result,controls]))


def verify_storage_entry(root: Path, entry: dict) -> None:
    """Verify the already approved entry's current bytes at each use boundary."""
    history = _pin(entry["history_manifest"])
    if Path(history["path"]).parent != root.resolve():
        raise ValueError("storage reuse History root differs")
    _verify_payload_inventory(root, entry["payload_inventory"], entry.get("retained_diagnostics"))


def _verify_payload_inventory(root: Path, inventory: dict, diagnostics: list[str] | None) -> None:
    actual = set()
    excluded = set(diagnostics or ())
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ValueError("storage reuse unsafe inventory")
        if path.is_file():
            relative = str(path.relative_to(root))
            actual.add(relative)
            if relative not in excluded and (relative not in inventory or sha256_file(path) != inventory[relative]):
                raise ValueError("storage reuse current payload bytes changed")
        elif path.is_dir() and not any(path.iterdir()):
            raise ValueError("storage reuse unknown empty directory")
    if actual != set(inventory) | excluded or set(inventory) & excluded:
        raise ValueError("storage reuse current inventory changed")


def checked_storage_reuse(value: FinancialStorageReuse, *, collection_manifest: Path,
                          declaration: dict | None = None) -> FinancialStorageReuse:
    """Accept only an intact proof minted in this invocation, without global cache."""
    if (not isinstance(value, FinancialStorageReuse) or value._issuer is not _ISSUER
        or value._seal != digest_value([value.declaration,value.companies,value.controls])
        or value.controls["COLLECTION"]["path"] != str(collection_manifest.resolve())
        or (declaration is not None and value.declaration != declaration)):
        raise ValueError("untrusted or mutated per-invocation storage proof")
    _pin(value.declaration)
    _pin(value.controls["COLLECTION"])
    return value


def storage_history(proof: FinancialStorageReuse | None, ticker: str, manifest: Path) -> dict | None:
    if proof is None:
        return None
    return next((entry for entry in proof.companies.get(ticker, {}).get("histories", [])
                 if entry["history_manifest"]["path"] == str(manifest.resolve())), None)


def _normalized_evidence(value: dict, *, pins: dict, declared: dict,
                         ticker: str, cik: str) -> dict:
    if set(value) != {"schema_version", "kind", "history_manifest", "build_manifest",
                      "declared_payload_sha256s", "historical_controls"}:
        raise ValueError("normalized storage evidence fields differ")
    if (value["history_manifest"] != pins["history_manifest"]
        or value["build_manifest"] != pins["build_manifest"]
        or value["declared_payload_sha256s"] != declared):
        raise ValueError("normalized storage evidence parent or payload hashes differ")
    evidence=value["historical_controls"]
    if not isinstance(evidence,dict) or "acceptance" not in evidence:
        raise ValueError("normalized storage evidence lacks historical acceptance")
    controls={name:_pin(pin) for name,pin in evidence.items()}
    if controls["acceptance"] != pins["acceptance"]:
        raise ValueError("normalized storage evidence acceptance differs")
    acceptance=read_json(Path(controls["acceptance"]["path"]))
    if value["kind"] == "FULL_TYPED_COMPANY_AUDIT":
        if "report" not in controls or controls["report"] not in acceptance.values():
            raise ValueError("historical acceptance does not bind the typed audit report")
        report=read_json(Path(controls["report"]["path"]))
        build=read_json(Path(pins["build_manifest"]["path"]))
        if (report.get("ticker")!=ticker or report.get("cik")!=cik
            or report.get("output_root")!=build.get("output_root")
            or not str(report.get("verdict", "")).startswith("PASS")):
            raise ValueError("historical typed audit scope or verdict differs")
        rows=report.get("all_file_results")
        if not isinstance(rows,list):
            raise ValueError("historical typed audit lacks file results")
        indexed={row.get("path"):row for row in rows}
        if len(indexed)!=len(rows):
            raise ValueError("historical typed audit repeats physical file paths")
        root=Path(pins["history_manifest"]["path"]).parent
        for relative,digest in declared.items():
            row=indexed.get(str(root/relative),{})
            if (row.get("physical_sha256")!=digest or row.get("all_records_consumed") is not True
                or row.get("hash_schema_checked_before_after") is not True):
                raise ValueError("historical typed audit does not prove each declared payload")
    elif value["kind"] == "ACCEPTED_FIRST5_FINANCIAL_CHAIN":
        if (acceptance.get("schema_version")!="universe50-first5-financial-acceptance-v1"
            or acceptance.get("status")!="LOCALLY_ACCEPTED_FIRST5_FINANCIAL"
            or controls.get("config")!=acceptance.get("first5_config")):
            raise ValueError("historical first financial acceptance does not bind config")
        config=read_json(Path(controls["config"]["path"]))
        rows=config.get("companies",[])
        matched=[row for row in rows if (row.get("ticker"),row.get("cik"))==(ticker,cik)]
        if len(matched)!=1:
            raise ValueError("historical first financial config company differs")
        row=matched[0]
        build=read_json(Path(pins["build_manifest"]["path"]))
        if (row.get("history_manifest_sha256")!=pins["history_manifest"]["sha256"]
            or row.get("build_manifest_sha256")!=pins["build_manifest"]["sha256"]
            or row.get("build_manifest")!=pins["build_manifest"]["path"]
            or row.get("history_root")!=str(Path(pins["history_manifest"]["path"]).parent)
            or any(row.get(key)!=build.get(key) for key in ("plan_sha256","intake_sha256"))):
            raise ValueError("historical first financial config History/build provenance differs")
    else:
        raise ValueError("unsupported normalized historical storage evidence kind")
    return controls


def current_history_validation_identity(manifest: dict) -> str:
    """Exact current public History.validate identity, without validating records."""
    from dataclasses import asdict

    from sec_xbrl import history
    from sec_xbrl.history_validation import validation_code_identity
    return validation_code_identity(sources=tuple(sorted(Path(history.__file__).parent.rglob("*.py"))),
        rules={"history_version":history.HISTORY_VERSION,
               "layer2_rules":asdict(history._history_layer2_rule_versions()),
               "period_rule":manifest.get("period_rule"),"derivation_rule":manifest.get("derivation_rule")})


def _current_routine_evidence(value: dict, *, pins: dict, declared: dict) -> dict:
    """Reuse completed routine checks; never assert a historical full typed audit."""
    from sec_xbrl.history_validation import (
        VALIDATION_POLICY_VERSION,
        _canonical_hash,
        _manifest_inventory,
        _safe_identity,
        _scope_key,
    )
    if (set(value) != {"schema_version","kind","history_manifest","build_manifest",
                       "declared_payload_sha256s","historical_controls"}
        or value.get("schema_version") != "accepted-financial-storage-evidence-v1"
        or value["history_manifest"] != pins["history_manifest"]
        or value["build_manifest"] != pins["build_manifest"]
        or value["declared_payload_sha256s"] != declared
        or not isinstance(value["historical_controls"],dict)
        or set(value["historical_controls"]) != {"acceptance","report"}):
        raise ValueError("current routine evidence scope differs")
    controls={name:_pin(pin) for name,pin in value["historical_controls"].items()}
    if controls["acceptance"] != pins["acceptance"]:
        raise ValueError("current routine acceptance differs")
    approval=read_json(Path(controls["acceptance"]["path"]))
    expected={"status":"ROOT_APPROVED","kind":"ACCEPTED_CURRENT_ROUTINE_HISTORY",
              "build_manifest":pins["build_manifest"],"history_manifest":pins["history_manifest"],
              "validation_report":controls["report"]}
    if approval != expected:
        raise ValueError("current routine ROOT approval does not bind exact controls")
    report=read_json(Path(controls["report"]["path"]))
    build=read_json(Path(pins["build_manifest"]["path"]))
    manifest=read_json(Path(pins["history_manifest"]["path"]))
    root=Path(pins["history_manifest"]["path"]).parent
    level=report.get("validation_level")
    native_result=report.get("result",{})
    allowed={"ROUTINE_INITIAL","ROUTINE_CHANGED","ROUTINE_UNCHANGED"}
    marker=build.get("storage_validation",{})
    if (report.get("version") != 1 or report.get("policy_version") != VALIDATION_POLICY_VERSION
        or report.get("code_identity") != current_history_validation_identity(manifest)
        or report.get("scope_key") != _scope_key(manifest)
        or report.get("publication_root") != str(root)
        or report.get("manifest_sha256") != pins["history_manifest"]["sha256"]
        or report.get("full_storage_validation") is not False or report.get("semantic_validation") is not False
        or level not in allowed or report.get("validation_reason") != level
        or marker != {"level":level,"reason":level,"report":controls["report"]["path"],"detailed_fallback":False}
        or native_result.get("level") != level or native_result.get("reason") != level
        or native_result.get("detailed_fallback") is not False
        or native_result.get("state_path") != controls["report"]["path"]
        or native_result.get("declared_files") != declared):
        raise ValueError("current routine native report is stale, incomplete or not genuine READY evidence")
    inventory=_manifest_inventory(manifest)
    files=report.get("files")
    if not isinstance(files,dict) or set(files) != set(inventory):
        raise ValueError("current routine native file scope differs")
    checked=native_result.get("checked_files")
    reused=native_result.get("reused_files")
    hashed=native_result.get("hashed_files")
    if (not all(isinstance(group,list) and len(group)==len(set(group)) for group in (checked,reused,hashed))
        or set(checked) & set(reused) or set(checked) | set(reused) != set(inventory)
        or not set(hashed) <= set(inventory)):
        raise ValueError("current routine completed file coverage differs")
    if any(type(native_result.get(key)) is not int or native_result[key] < 0
           for key in ("sampled_rows", "decoded_json_values")):
        raise ValueError("current routine sample counters are invalid")
    for relative,entry in inventory.items():
        row=files[relative]
        expected_file={"identity":list(_safe_identity(root/relative)),"sha256":entry["info"]["sha256"],
                       "count":entry["info"]["count"],"json_fields":entry["info"].get("json_fields"),
                       "table_key":entry["table_key"],"role":entry["role"]}
        if (not isinstance(row,dict) or set(row) != set(expected_file)|{"schema_fingerprint"}
            or any(row.get(key)!=item for key,item in expected_file.items())
            or (relative in checked and not isinstance(row.get("schema_fingerprint"),str))):
            raise ValueError("current routine file identity/count/schema metadata differs")
        if row["schema_fingerprint"] is not None:
            import polars as pl
            schema = pl.read_parquet_schema(root / relative)
            if row["schema_fingerprint"] != _canonical_hash([(name, str(dtype)) for name, dtype in schema.items()]):
                raise ValueError("current routine Parquet schema fingerprint differs")
    return controls
