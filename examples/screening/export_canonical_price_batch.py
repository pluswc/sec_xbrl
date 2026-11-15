"""Supplier-runtime offline export. No Arelle/SEC environment dependency or network."""
from __future__ import annotations

import argparse
import hashlib
import json
import runpy
from pathlib import Path


def main() -> None:
    from market_data_pipeline.delivery import verify_delivery_manifest
    from market_data_pipeline.query import CanonicalQuery
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    module = Path(__file__).resolve().parents[2] / "src/sec_xbrl/metrics/price_batch.py"
    implementation = runpy.run_path(str(module))
    config = implementation["pinned_json"]({"path": args.config, "sha256": args.sha256})
    result = implementation["canonical_price_batch"](CanonicalQuery(config["supplier_root"]), verify_delivery_manifest,
        delivery_pin=config["delivery"], companies=config["companies"], start=config["start"], end=config["end"],
        currency_pin=config.get("currency"), currency_manifest_pin=config.get("currency_manifest"))
    result["producer"] = {"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          "batch_rule_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                          "config": {"path": args.config, "sha256": args.sha256}}
    data = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    with Path(args.output).open("xb") as handle:
        handle.write(data)
    print(json.dumps({"path": str(Path(args.output).absolute()), "sha256": hashlib.sha256(data).hexdigest(),
                      "prices": len(result["prices"]), "companies": len(result["companies"])}))


if __name__ == "__main__":
    main()
