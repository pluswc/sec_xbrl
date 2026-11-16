"""Offline, create-only company reuse qualification and financial proposals.

Commands do not bind accounting roles, capture data or publish market metrics.
Use the normal project Python runtime with PYTHONPATH=src.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from sec_xbrl.metrics.company_valuation_readiness import (
    accept_fresh,
    accept_reuse,
    project_fresh_candidates,
    project_reuse_candidates,
    propose_bindings,
    propose_fresh,
    propose_reuse,
)
from sec_xbrl.metrics.market_inputs import encoded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("propose-reuse", "project", "accept-reuse", "propose-fresh", "project-fresh", "accept-fresh", "propose-bindings"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, help="Pinned config, or proposal for accept-reuse")
        command.add_argument("--sha256", required=True)
        command.add_argument("--output", required=True)
        if not name.startswith("propose-"):
            command.add_argument("--evidence", required=True, help="Reuse proposal for project; ROOT receipt for accept-reuse")
            command.add_argument("--evidence-sha256", required=True)
    args = parser.parse_args()
    pin = {"path": args.config, "sha256": args.sha256}
    if args.command.startswith("propose-"):
        value = {"propose-fresh": propose_fresh, "propose-reuse": propose_reuse,
                 "propose-bindings": propose_bindings}[args.command](pin)
    else:
        evidence = {"path": args.evidence, "sha256": args.evidence_sha256}
        action = {"accept-reuse": accept_reuse, "project": project_reuse_candidates,
                  "accept-fresh": accept_fresh, "project-fresh": project_fresh_candidates}[args.command]
        value = action(pin, evidence)
    path = Path(args.output).absolute()
    if args.command == "propose-bindings":
        if path.exists():
            raise FileExistsError("append-only binding proposal directory exists")
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("binding proposal path must not traverse symlinks")
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".partial-company-bindings-", dir=path.parent))
        try:
            def write(name: str, item: object) -> dict:
                data = encoded(item)
                with (staging / name).open("xb") as handle:
                    handle.write(data)
                return {"path": str(path / name), "sha256": hashlib.sha256(data).hexdigest()}
            manifest = {k: v for k, v in value.items() if k not in {"proposals", "candidates"}}
            manifest["proposals"] = [{"cik": p["cik"], "proposal": write(p["cik"] + ".proposal.json", p)} for p in value["proposals"]]
            manifest["candidate_pin"] = write("candidates.json", value["candidates"])
            result = write("manifest.json", manifest)
            os.rename(staging, path)
            print(json.dumps(result))
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return
    data = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
    print(json.dumps({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}))


if __name__ == "__main__":
    main()
