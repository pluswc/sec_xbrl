"""Offline, create-only Q4 EPS source proposal, evidence discovery and qualification."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from sec_xbrl.metrics.market_inputs import encoded
from sec_xbrl.metrics.q4_eps_reconstruction import (
    augment_q4_eps_ttm,
    discover_accounting_evidence,
    propose_q4_eps,
    qualify_q4_eps,
    verify_q4_eps,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["propose", "discover-evidence", "qualify", "verify", "augment", "query"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output")
    parser.add_argument("--cik")
    parser.add_argument("--flavor", choices=["basic", "diluted"])
    parser.add_argument("--grammar")
    parser.add_argument("--grammar-sha256")
    parser.add_argument("--source-catalog")
    parser.add_argument("--source-catalog-sha256")
    args = parser.parse_args()
    pin = {"path": str(Path(args.input).absolute()), "sha256": args.sha256}
    if args.operation == "verify":
        artifact = verify_q4_eps(pin)
        print({"verified": True, "quarters": len(artifact["quarter_results"]), "ttm": len(artifact["observations"])})
        return
    if args.operation == "query":
        from sec_xbrl.screening.price_metric_publication import PriceMetricReader

        if not args.cik:
            parser.error("prepared query requires --cik")
        value = PriceMetricReader(pin).q4_eps(args.cik, args.flavor)
        if not args.output:
            print(encoded(value).decode())
            return
    if not args.output:
        parser.error("create operation requires --output")
    destination = Path(args.output).absolute()
    if destination.exists() or any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("create-only regular output required")
    if args.operation == "query":
        pass  # Only the prepared read above; no producer verification or calculation.
    elif args.operation == "discover-evidence":
        if not all((args.grammar, args.grammar_sha256, args.source_catalog, args.source_catalog_sha256)):
            parser.error("discover-evidence requires grammar and source-catalog paths and SHA256s")
        value = discover_accounting_evidence(pin,
            {"path": str(Path(args.grammar).absolute()), "sha256": args.grammar_sha256},
            {"path": str(Path(args.source_catalog).absolute()), "sha256": args.source_catalog_sha256})
    else:
        value = {"propose": propose_q4_eps, "qualify": qualify_q4_eps, "augment": augment_q4_eps_ttm}[args.operation](pin)
    data = encoded(value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(data)
    print({"path": str(destination), "sha256": hashlib.sha256(data).hexdigest()})


if __name__ == "__main__":
    main()
