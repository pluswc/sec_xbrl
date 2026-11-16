"""Offline, create-only exact quarter EPS derivation and additive bundle assembly."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from sec_xbrl.metrics.market_inputs import encoded
from sec_xbrl.metrics.price_financial_inputs import augment_reported_quarter_eps
from sec_xbrl.metrics.reported_quarter_eps import prepare_ttm, verify_ttm


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["derive", "augment", "verify"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    pin = {"path": str(Path(args.input).absolute()), "sha256": args.sha256}
    if args.operation == "verify":
        value = verify_ttm(pin)
        print({"verified": True, "observations": len(value["observations"]), "holds": value["holds"]})
        return
    if not args.output:
        parser.error("derive/augment require --output")
    path = Path(args.output).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or path.exists():
        raise ValueError("create-only regular output required")
    value = prepare_ttm(pin) if args.operation == "derive" else augment_reported_quarter_eps(pin)
    data = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
    print({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})


if __name__ == "__main__":
    main()
