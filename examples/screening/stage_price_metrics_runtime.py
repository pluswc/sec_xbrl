"""Create-only runtime staging; emits reviewed commands, never starts/stops a process.

Clone the currently observed live bundle, preserve every original financial/Q4
pin and backend argument, and add only the separate price worker. Private runs
use a SQLite backup of the current old journal plus a separate price journal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path, PureWindowsPath


def linux_path(value: str) -> Path:
    win = PureWindowsPath(value)
    if win.drive:
        return Path("/mnt") / win.drive[0].lower() / Path(*win.parts[1:])
    return Path(value)


def windows_path(value: Path) -> str:
    parts = value.absolute().parts
    if len(parts) < 4 or parts[1] != "mnt" or len(parts[2]) != 1:
        raise ValueError("Windows bundle destination must be on an explicit /mnt/<drive> path")
    return str(PureWindowsPath(parts[2].upper() + ":/", *parts[3:]))


def stage_runtime(*, observed_switch: Path, source: Path, publication: dict,
                  destination: Path, private_port: int, private_legacy_journal: Path,
                  private_price_journal: Path, live_price_journal: Path) -> dict:
    observed = json.loads(observed_switch.read_bytes())
    original_args = observed["args"]
    if len(original_args) % 2 != 1:
        raise ValueError("observed runtime needs exact argument pairs")
    original = dict(zip(original_args[1::2], original_args[2::2], strict=True))
    if int(original["--frontend-port"]) == private_port or not 1 <= private_port <= 65535:
        raise ValueError("private preview requires a separate valid port")
    if any(k.startswith("--price-") for k in original):
        raise ValueError("existing price-worker configuration needs explicit reconciliation")
    if destination.exists() or private_legacy_journal.exists() or private_price_journal.exists() or live_price_journal.exists():
        raise FileExistsError("staging and new journals are append-only; choose fresh paths")
    data = Path(publication["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != publication["sha256"]:
        raise ValueError("price publication pin differs")
    old_bundle = linux_path(original["--assets-root"])
    destination.mkdir(parents=True)
    bundle = destination / "bundle"
    shutil.copytree(old_bundle, bundle)
    overlays = {"app.js": source / "examples/screening/display-assets/app.js",
                "app.css": source / "examples/screening/display-assets/app.css",
                "windows-loopback-bridge.cjs": source / "examples/screening/windows-loopback-bridge.cjs"}
    for name, path in overlays.items():
        shutil.copyfile(path, bundle / name)
    old_journal = Path(original["--journal-store"])
    private_legacy_journal.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(old_journal.as_uri() + "?mode=ro", uri=True) as parent, sqlite3.connect(private_legacy_journal) as private:
        parent.backup(private)
    common = {**original, "--assets-root": windows_path(bundle),
              "--price-metrics-manifest": publication["path"], "--price-metrics-sha256": publication["sha256"],
              "--price-source-root": str(source / "src")}
    def command(options: dict) -> dict:
        return {"executable": observed["executable"], "args": [windows_path(bundle / "windows-loopback-bridge.cjs"),
                *[item for pair in options.items() for item in pair]]}
    private = command({**common, "--frontend-port": str(private_port),
        "--journal-store": str(private_legacy_journal), "--price-metrics-journal": str(private_price_journal)})
    live = command({**common, "--price-metrics-journal": str(live_price_journal)})
    commands = {"private-start": private, "live-start": live,
                "rollback": {"executable": observed["executable"], "args": original_args}}
    for name, value in commands.items():
        (destination / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
    (destination / "start-runtime.cjs").write_text('''"use strict";
const fs=require("node:fs"),cp=require("node:child_process");
const command=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));
const child=cp.spawn(command.executable,command.args,{detached:true,stdio:"ignore",windowsHide:true});
child.on("error",error=>{process.stderr.write(error.message+"\\n");process.exitCode=1});
child.unref();process.stdout.write(JSON.stringify({pid:child.pid,command:process.argv[2]})+"\\n");
''')
    receipt = {"schema_version": "price-metrics-runtime-staging-v1", "activated": False,
        "observed_switch": {"path": str(observed_switch), "sha256": hashlib.sha256(observed_switch.read_bytes()).hexdigest()},
        "bundle": str(bundle), "overlay_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in overlays.items()},
        "publication": publication, "private_port": private_port, "private_legacy_journal": str(private_legacy_journal),
        "original_journal": str(old_journal), "original_backend_port": original["--backend-port"],
        "original_financial_source": original["--source-root"],
        "commands": {name: windows_path(destination / f"{name}.json") for name in commands}}
    (destination / "staging-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("observed-switch", "source", "manifest", "sha256", "destination", "private-legacy-journal", "private-price-journal", "live-price-journal"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--private-port", type=int, default=18887)
    a = p.parse_args()
    print(json.dumps(stage_runtime(observed_switch=Path(a.observed_switch), source=Path(a.source),
        publication={"path": a.manifest, "sha256": a.sha256}, destination=Path(a.destination), private_port=a.private_port,
        private_legacy_journal=Path(a.private_legacy_journal), private_price_journal=Path(a.private_price_journal),
        live_price_journal=Path(a.live_price_journal)), ensure_ascii=False))


if __name__ == "__main__":
    main()
