"""Offline, create-only Q4 EPS source proposal, evidence discovery and qualification."""
from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from zipfile import BadZipFile

from sec_xbrl.metrics.market_inputs import encoded, pinned_json
from sec_xbrl.metrics.q4_eps_reconstruction import (
    augment_q4_eps_ttm,
    discover_accounting_evidence,
    propose_q4_eps,
    qualify_q4_eps,
    verify_q4_eps,
)


def _prepare_cal_sources(proposal_pin: dict, catalog_pin: dict, *, projection_root: Path,
                         taxonomy_cache: Path) -> dict:
    from sec_xbrl.metrics.cal_eps_source import prepare_cal_eps_filing

    proposal, catalog = pinned_json(proposal_pin), pinned_json(catalog_pin)
    if proposal.get("schema_version") != "common-q4-eps-proposal-v1":
        raise ValueError("CAL source preparation requires a registered Q4 EPS proposal")
    if not projection_root.is_absolute() or projection_root.exists() or any(
        p.is_symlink() for p in (projection_root, *projection_root.parents)
    ):
        raise ValueError("create-only regular projection root required")
    filings, snapshots, documents = defaultdict(list), defaultdict(list), defaultdict(list)
    for filing in proposal["source_filings"]:
        key = filing["cik"], filing["accession"]
        if not re.fullmatch(r"\d{10}", key[0]) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", key[1]):
            raise ValueError("registered CAL source accession must be canonical")
        filings[key].append(filing)
    for snapshot in proposal["snapshots"]:
        _, cik, accession, *_ = snapshot["snapshot_id"].split(":")
        snapshots[cik, accession].append(snapshot)
    for document in catalog["documents"]:
        documents[document["cik"], document["accession"]].append(document)
    projection_root.mkdir(parents=True, exist_ok=False)
    prepared, holds = [], []
    for key in sorted(filings.keys() | documents.keys()):
        cik, accession = key
        coordinate = {"cik": cik, "accession": accession}
        packages = {encoded(d["original_package"]): d["original_package"] for d in documents[key]
                    if isinstance(d.get("original_package"), dict)
                    and set(d["original_package"]) == {"path", "sha256"}}
        matching_snapshots = snapshots[cik, accession.replace("-", "")]
        reason = (
            "SOURCE_ACCESSION_NOT_REGISTERED" if key not in filings else
            "REGISTERED_FILING_AMBIGUOUS" if len(filings[key]) != 1 else
            "REGISTERED_PACKAGE_PIN_MISSING" if not packages else
            "REGISTERED_PACKAGE_PIN_AMBIGUOUS" if len(packages) != 1 else
            "REGISTERED_SNAPSHOT_MISSING_OR_AMBIGUOUS" if len(matching_snapshots) != 1 else None
        )
        if reason:
            holds.append({**coordinate, "reason": reason})
            continue
        try:
            projection = prepare_cal_eps_filing(matching_snapshots[0], next(iter(packages.values())),
                                                 taxonomy_cache=taxonomy_cache)
        except (ValueError, RuntimeError, OSError, BadZipFile) as exc:
            holds.append({**coordinate, "reason": "SOURCE_PREPARATION_FAILED",
                          "detail": f"{type(exc).__name__}: {exc}"})
            continue
        data = encoded(projection)
        destination = projection_root / cik / (accession + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(data)
        prepared.append({**coordinate, "projection": {
            "path": str(destination), "sha256": hashlib.sha256(data).hexdigest(),
        }})
    return {"schema_version": "cal-eps-filing-catalog-v1", "proposal": proposal_pin,
            "source_catalog": catalog_pin, "filings": prepared, "holds": holds}


def _verify_cal_sources(pin: dict, *, taxonomy_cache: Path) -> dict:
    from sec_xbrl.metrics.cal_eps_source import verify_cal_eps_filing

    catalog = pinned_json(pin)
    if catalog.get("schema_version") != "cal-eps-filing-catalog-v1":
        raise ValueError("CAL source verification requires a prepared filing catalog")
    for name in ("proposal", "source_catalog"):
        if name in catalog:
            pinned_json(catalog[name])
    seen = set()
    for entry in catalog["filings"]:
        key = entry["cik"], entry["accession"]
        if key in seen:
            raise ValueError("CAL source catalog repeats an accession")
        seen.add(key)
        projection = verify_cal_eps_filing(entry["projection"], taxonomy_cache=taxonomy_cache)
        if (projection["filing"]["cik"], projection["filing"]["accession"]) != key:
            raise ValueError("CAL source catalog accession differs from replay")
    return {"verified": True, "prepared_filings_verified": len(seen),
            "preparation_holds": len(catalog.get("holds", []))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["propose", "discover-evidence", "qualify", "verify", "augment", "query",
                                              "prepare-cal-sources", "verify-cal-sources"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output")
    parser.add_argument("--cik")
    parser.add_argument("--flavor", choices=["basic", "diluted"])
    parser.add_argument("--grammar")
    parser.add_argument("--grammar-sha256")
    parser.add_argument("--source-catalog")
    parser.add_argument("--source-catalog-sha256")
    parser.add_argument("--projection-root")
    parser.add_argument("--taxonomy-cache")
    args = parser.parse_args()
    pin = {"path": str(Path(args.input).absolute()), "sha256": args.sha256}
    if args.operation in {"prepare-cal-sources", "verify-cal-sources"} and not args.taxonomy_cache:
        parser.error("CAL source operations require --taxonomy-cache for offline Arelle")
    if args.operation == "verify-cal-sources":
        print(_verify_cal_sources(pin, taxonomy_cache=Path(args.taxonomy_cache).absolute()))
        return
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
    if args.operation == "prepare-cal-sources":
        if not all((args.source_catalog, args.source_catalog_sha256, args.projection_root)):
            parser.error("prepare-cal-sources requires source-catalog pins and --projection-root")
        value = _prepare_cal_sources(pin,
            {"path": str(Path(args.source_catalog).absolute()), "sha256": args.source_catalog_sha256},
            projection_root=Path(args.projection_root).absolute(),
            taxonomy_cache=Path(args.taxonomy_cache).absolute())
    elif args.operation == "query":
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
