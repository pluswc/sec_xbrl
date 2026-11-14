"""Read-only export, deliberately executable with the *original* sec_xbrl source.

This tool has no dependency on the new snapshot reader or publisher. Run with
PYTHONPATH pinned to the accepted old source. A ROOT approval is a separate act.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

VERSION = "screening-read-snapshot-v1"
MANIFEST = "screening_read_snapshot_manifest.json"
METADATA = ("companies", "metadata", "metric_definitions", "metric_support", "quarter_definitions",
            "quarter_support", "quarter_period_inventory", "latest_source_period_guards", "latest_quarter_periods")


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def pinned(pin: dict) -> bytes:
    path = Path(pin["path"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("export pin is not a regular file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("export pin changed")
    return data


def observation_identity(row: dict) -> str:
    return row.get("metric_observation_id") or row.get("observation_id") or "legacy-coordinate-" + digest(
        {key: row.get(key) for key in ("cik", "metric_id", "fiscal_year", "period_class", "view")})


def verify_pins(config: dict) -> None:
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != config["exporter_sha256"]:
        raise ValueError("exporter source changed")
    for pin in [*config["source_files"], *config["source_aux_files"], *config["artifact_files"], config["catalog"]]:
        pinned(pin)
    bridge = Path(config["source_root"]).resolve().parents[1] / "examples/screening/windows-loopback-bridge.cjs"
    if len(config["source_aux_files"]) != 1 or Path(config["source_aux_files"][0]["path"]).resolve() != bridge:
        raise ValueError("original bridge source pin is required")
    source = Path(config["source_root"]).resolve()
    repository = source.parents[1]
    if subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip() != config["source_revision"]:
        raise ValueError("original source revision differs")
    if subprocess.run(["git", "-C", str(repository), "diff", "--quiet", "HEAD", "--", "src/sec_xbrl", "examples/screening/windows-loopback-bridge.cjs"], check=False).returncode:
        raise ValueError("original source differs from its accepted revision")
    actual = sorted(str(path.resolve()) for path in source.rglob("*.py"))
    if actual != sorted(pin["path"] for pin in config["source_files"]):
        raise ValueError("complete original Python source inventory differs")


def export_reader(reader: Any, destination: Path, origin: dict) -> Path:
    """Preserve complete public read contract; only one company's evidence in memory."""
    from sec_xbrl.screening.runtime_projection import _split, hydrate_observation, observation_rows

    if destination.exists() or any(path.is_symlink() for path in [destination, *destination.parents]):
        raise ValueError("snapshot requires a new nonsymlink destination")
    destination.mkdir(parents=True)
    properties = {key: getattr(reader, key) for key in METADATA if hasattr(reader, key)}
    properties["reader_contract"] = {"module": type(reader).__module__, "class": type(reader).__name__}
    properties["quarterly_manifest"] = getattr(getattr(reader, "quarterly", None), "manifest", None)
    from sec_xbrl.screening.dataset import ScreeningDatasetReader
    from sec_xbrl.screening.dataset_v2 import ScreeningDatasetV2Reader
    properties["capabilities"] = {"explorer": not isinstance(reader, ScreeningDatasetReader),
                                  "quarterly": not isinstance(reader, (ScreeningDatasetReader, ScreeningDatasetV2Reader))}
    if hasattr(reader, "quarter_definitions"):
        properties["capabilities"]["quarterly"] = True
    properties["status"] = reader.verify_all()
    if not getattr(reader, "bounded_export", False):
        properties["row_order"] = {name: [observation_identity(row)
            for row in observation_rows(reader, quarterly=quarterly, latest=latest)]
            for name, quarterly, latest in (("annual", False, False), ("quarter", True, False),
                                            ("annual_latest", False, True), ("quarter_latest", True, True))}
    properties["original_manifest"] = reader.manifest
    properties["original_manifest_sha256"] = getattr(reader, "_manifest_sha256", None) or hashlib.sha256((reader.root / "screening_dataset_manifest.json").read_bytes()).hexdigest()
    files = {}
    owners = getattr(reader, "_owners", {})
    for company in reader.companies:
        cik = company["cik"]
        if not isinstance(cik, str) or len(cik) != 10 or not cik.isdigit() or cik in files:
            raise ValueError("invalid or duplicate company")
        owner = owners.get(cik, reader)
        payload = {"company": reader.company(cik), "owner": {
            "manifest": owner.manifest, "manifest_sha256": getattr(owner, "_manifest_sha256", None)}, "views": {}, "details": {}}
        for name, quarterly, latest in (("annual", False, False), ("quarter", True, False),
                                        ("annual_latest", False, True), ("quarter_latest", True, True)):
            cores = []
            for row in observation_rows(reader, cik=cik, quarterly=quarterly, latest=latest):
                full = hydrate_observation(reader, row, quarterly=quarterly)
                identity = observation_identity(full)
                if not identity:
                    raise ValueError("original observation identity is missing")
                if identity in payload["details"] and payload["details"][identity] != full:
                    raise ValueError("same original observation ID has different contents")
                payload["details"][identity] = full
                core, _ = _split(full)
                core.pop("comparison_evidence", None)
                cores.append(core)
            payload["views"][name] = cores
        data = encoded(payload)
        (destination / f"{cik}.json").write_bytes(data)
        files[cik] = {"path": f"{cik}.json", "sha256": hashlib.sha256(data).hexdigest()}
    body = {"schema_version": VERSION, "reader_version": VERSION, "origin": origin,
            "properties": properties, "files": files}
    manifest = {**body, "logical_sha256": digest(body)}
    path = destination / MANIFEST
    path.write_bytes(encoded(manifest))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(pinned({"path": str(args.config), "sha256": args.config_sha256}))
    verify_pins(config)
    from sec_xbrl.screening.service import ScreeningService

    module = Path(sys.modules[ScreeningService.__module__].__file__).resolve()
    if not module.is_relative_to(Path(config["source_root"]).resolve()):
        raise ValueError("export did not import the approved original source")
    completed = []
    with TemporaryDirectory(prefix="screening-read-export-") as private:
        from sec_xbrl.screening.cli import _catalog
        pinned(config["catalog"])
        catalog = _catalog(Path(config["catalog"]["path"]))
        service = ScreeningService(catalog, Path(private) / "private.sqlite", **config.get("service_options", {}))
        for dataset_id in config["dataset_ids"]:
            reader = service.datasets[dataset_id]
            origin = {"source_revision": config["source_revision"], "source_root": config["source_root"],
                      "python_version": sys.version, "polars_version": __import__("polars").__version__, "reader_module": str(module),
                      "command": sys.argv, "service_options_sha256": digest(config.get("service_options", {})),
                      "source_files": config["source_files"], "source_aux_files": config["source_aux_files"],
                      "artifact_files": config["artifact_files"],
                      "config_sha256": args.config_sha256, "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            with service._compatibility_scope():
                path = export_reader(reader, args.destination / dataset_id, origin)
            receipt = {"schema_version": "screening-read-export-verification-v1", "verified": True,
                       "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "logical_sha256": json.loads(path.read_bytes())["logical_sha256"], "origin": origin}
            completed.append((path, receipt))
    verify_pins(config)
    for path, receipt in completed:
        (path.parent / "verification.json").write_bytes(encoded(receipt))


if __name__ == "__main__":
    main()
