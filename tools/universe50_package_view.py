#!/usr/bin/env python3
"""Publish and strictly verify an explicit hardlink view of immutable SEC ZIPs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

VERSION = "sec-universe50-package-view-v1"
MANIFEST_NAME = "package_view_manifest.json"
CIK = re.compile(r"^[0-9]{10}$")
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a non-symlink regular file: {path}")
    if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise ValueError(f"{label} is not regular: {path}")
    return path


def directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be an absolute non-symlink directory: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def authenticated_json(
    path: Path, label: str, expected_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hash and parse the same bytes while pinning the opened file identity."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} path must be absolute without traversal: {path}")
    parent_receipts = directory_chain_receipts(path.parent)
    path = regular(path, label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    receipt = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
    if receipt != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode):
        raise ValueError(f"{label} changed while reading: {path}")
    path_info = regular(path, label).stat(follow_symlinks=False)
    if receipt != (path_info.st_dev, path_info.st_ino, path_info.st_size,
                   path_info.st_mtime_ns, path_info.st_mode):
        raise ValueError(f"{label} path changed while reading: {path}")
    verify_directory_chain(parent_receipts, f"{label} ancestor")
    content = b"".join(chunks)
    actual_hash = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ValueError(f"{label} SHA-256 differs")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value, {
        "path": str(path),
        "sha256": actual_hash,
        "device": before.st_dev,
        "inode": before.st_ino,
        "size": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "mode": before.st_mode,
    }


def verify_authenticated_receipt(receipt: dict[str, Any], label: str) -> None:
    """Require a pinned metadata path to retain its exact bytes and file identity."""
    path = regular(Path(receipt.get("path", "")), label)
    info = path.stat(follow_symlinks=False)
    observed = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)
    expected = (
        receipt.get("device"), receipt.get("inode"), receipt.get("size"), receipt.get("mtime_ns"),
        receipt.get("mode")
    )
    if observed != expected:
        raise ValueError(f"{label} file identity changed: {path}")
    _payload, reopened = authenticated_json(path, label, receipt.get("sha256"))
    if reopened != receipt:
        raise ValueError(f"{label} receipt changed: {path}")


def within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def identity(cik: object, accession: object) -> tuple[str, str]:
    if not isinstance(cik, str) or CIK.fullmatch(cik) is None:
        raise ValueError(f"unsafe CIK: {cik!r}")
    if not isinstance(accession, str) or ACCESSION.fullmatch(accession) is None:
        raise ValueError(f"unsafe accession: {accession!r}")
    return cik, accession


def plan_filings(payload: dict[str, Any], cik: str) -> dict[tuple[str, str], dict[str, Any]]:
    companies = payload.get("companies")
    if not isinstance(companies, list) or len(companies) != 1 or companies[0].get("cik") != cik:
        raise ValueError(f"plan must contain exactly selected CIK {cik}")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for filing in companies[0].get("filings", []):
        key = identity(filing.get("cik"), filing.get("accession"))
        if key in result:
            raise ValueError(f"duplicate plan filing: {key}")
        result[key] = filing
    return result


def intake_filings(payload: dict[str, Any], cik: str) -> dict[tuple[str, str], dict[str, Any]]:
    if payload.get("complete") is not True:
        raise ValueError(f"intake is incomplete for {cik}")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload.get("filings", []):
        filing = row.get("filing", {})
        key = identity(filing.get("cik"), filing.get("accession"))
        if key in result:
            raise ValueError(f"duplicate intake filing: {key}")
        if row.get("status") not in {"INGESTED", "REUSED"}:
            raise ValueError(f"selected intake filing is not successful: {key}")
        result[key] = row
    return result


def source_receipt(
    row: dict[str, Any], cik: str, accession: str
) -> tuple[dict[str, Any], str]:
    source_run = Path(row.get("source_run", ""))
    if not source_run.is_absolute():
        raise ValueError(f"source_run must be absolute for {accession}")
    manifest = source_run / "snapshots" / cik / accession.replace("-", "") / "layer1_manifest.json"
    payload, receipt = authenticated_json(manifest, "Layer 1 manifest")
    if payload.get("cik") != cik or payload.get("accession") != accession:
        raise ValueError(f"Layer 1 manifest identity differs for {accession}")
    package_hash = payload.get("package_sha256")
    if not isinstance(package_hash, str) or SHA256.fullmatch(package_hash) is None:
        raise ValueError(f"invalid Layer 1 package hash for {accession}")
    return receipt, package_hash


def directory_chain_receipts(path: Path) -> list[tuple[Path, int, int]]:
    """Pin each existing absolute directory component and reject symlink ancestors."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe directory path: {path}")
    receipts: list[tuple[Path, int, int]] = []
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        info = cursor.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"directory chain contains unsafe component: {cursor}")
        receipts.append((cursor, info.st_dev, info.st_ino))
    return receipts


def verify_directory_chain(receipts: Sequence[tuple[Path, int, int]], label: str) -> None:
    for path, device, inode in receipts:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{label} directory became unsafe: {path}")
        if (info.st_dev, info.st_ino) != (device, inode):
            raise ValueError(f"{label} directory identity changed: {path}")


def cached_path(root: Path, cik: str, accession: str) -> Path:
    return root / cik / accession.replace("-", "") / f"{accession}-xbrl.zip"


def source_stat(path: Path, root: Path, accession: str) -> os.stat_result:
    regular(path, f"cached package for {accession}")
    if not within(path, root):
        raise ValueError(f"cached package escapes declared root: {path}")
    cursor = root
    for part in path.relative_to(root).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"cached package path contains symlink: {cursor}")
    return path.stat(follow_symlinks=False)


def publish_package_view(
    *, candidate: Path, candidate_sha256: str, cache_roots: Sequence[Path], destination: Path
) -> Path:
    """Publish a new atomic hardlink-only view from explicit cache roots."""
    if SHA256.fullmatch(candidate_sha256) is None:
        raise ValueError("candidate_sha256 must be lowercase SHA-256")
    candidate = Path(candidate)
    payload, candidate_receipt = authenticated_json(
        candidate, "actual50 candidate", candidate_sha256
    )
    roots = [directory(Path(root), "cache root") for root in cache_roots]
    if not roots or len({root.resolve() for root in roots}) != len(roots):
        raise ValueError("cache roots must be a non-empty unique ordered list")
    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError("destination must be absolute")
    if ".." in destination.parts:
        raise ValueError("destination cannot contain path traversal")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination must be new: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory(destination.parent, "destination parent")
    destination_chain = directory_chain_receipts(destination.parent)
    root_chains = [directory_chain_receipts(root) for root in roots]
    if any(within(destination, root) for root in roots):
        raise ValueError("destination cannot be inside a source root")
    destination_dev = destination.parent.stat().st_dev
    if any(root.stat().st_dev != destination_dev for root in roots):
        raise ValueError("cache roots and destination must share a filesystem")

    selection = payload.get("selection")
    if not isinstance(selection, list) or not selection:
        raise ValueError("candidate selection must be non-empty")
    rows: list[dict[str, Any]] = []
    companies: set[str] = set()
    filings: set[tuple[str, str]] = set()
    source_runs: set[Path] = set()
    metadata_receipts: list[dict[str, Any]] = [candidate_receipt]
    for company in selection:
        cik = company.get("cik")
        if not isinstance(cik, str) or CIK.fullmatch(cik) is None:
            raise ValueError(f"unsafe CIK: {cik!r}")
        if cik in companies:
            raise ValueError(f"duplicate selection CIK: {cik}")
        companies.add(cik)
        plan_path, intake_path = Path(company.get("plan", "")), Path(company.get("intake", ""))
        for path, expected, label in (
            (plan_path, company.get("plan_sha256"), "plan"),
            (intake_path, company.get("intake_sha256"), "intake"),
        ):
            if not path.is_absolute() or not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
                raise ValueError(f"invalid {label} path/hash for {cik}")
        plan_payload, plan_receipt = authenticated_json(plan_path, "plan", company["plan_sha256"])
        intake_payload, intake_receipt = authenticated_json(
            intake_path, "intake", company["intake_sha256"]
        )
        metadata_receipts.extend((plan_receipt, intake_receipt))
        planned = plan_filings(plan_payload, cik)
        intakes = intake_filings(intake_payload, cik)
        if set(planned) != set(intakes):
            raise ValueError(f"plan/intake membership differs for {cik}")
        if any(planned[key] != intakes[key].get("filing") for key in planned):
            raise ValueError(f"plan/intake filing metadata differs for {cik}")
        if company.get("selected_filings") != len(planned):
            raise ValueError(f"selected filing count differs for {cik}")
        for key in sorted(planned):
            if key in filings:
                raise ValueError(f"duplicate selected filing: {key}")
            filings.add(key)
            filing_cik, accession = key
            intake_row = intakes[key]
            manifest_receipt, expected_hash = source_receipt(intake_row, filing_cik, accession)
            metadata_receipts.append(manifest_receipt)
            source_runs.add(Path(intake_row["source_run"]).resolve())
            matches: list[dict[str, Any]] = []
            for index, root in enumerate(roots):
                verify_directory_chain(root_chains[index], "cache root")
                path = cached_path(root, filing_cik, accession)
                if not path.exists() and not path.is_symlink():
                    continue
                before = source_stat(path, root, accession)
                actual_hash = sha256(path)
                after = source_stat(path, root, accession)
                receipt = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                           before.st_mode)
                if receipt != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                               after.st_mode):
                    raise ValueError(f"cached package changed while hashing: {accession}")
                if actual_hash == expected_hash:
                    matches.append({"cache_root_index": index, "path": str(path), "device": before.st_dev,
                                    "inode": before.st_ino, "size": before.st_size,
                                    "mtime_ns": before.st_mtime_ns, "mode": before.st_mode})
            if not matches:
                raise ValueError(f"no cached ZIP matches expected hash for {accession}")
            rows.append({"ticker": company.get("ticker"), "cik": filing_cik, "accession": accession,
                         "expected_package_sha256": expected_hash,
                         "layer1_manifest_path": manifest_receipt["path"],
                         "layer1_manifest_sha256": manifest_receipt["sha256"],
                         "layer1_manifest_receipt": manifest_receipt,
                         "source_run": intake_row["source_run"],
                         "chosen_source": matches[0], "all_matching_sources": matches})
    if any(within(destination, source_run) for source_run in source_runs):
        raise ValueError("destination cannot be inside a selected source_run")
    if payload.get("membership") != len(companies) or payload.get("selected_filings_total") != len(rows):
        raise ValueError("candidate totals differ from selected plan/intake scope")

    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    verify_directory_chain(destination_chain, "destination ancestor")
    temporary.mkdir(mode=0o700)
    temporary_info = temporary.stat(follow_symlinks=False)
    temporary_receipt = (temporary_info.st_dev, temporary_info.st_ino)
    try:
        outputs: list[dict[str, Any]] = []
        for row in rows:
            verify_directory_chain(destination_chain, "destination ancestor")
            current_temporary = temporary.stat(follow_symlinks=False)
            if (current_temporary.st_dev, current_temporary.st_ino) != temporary_receipt:
                raise ValueError(f"temporary root identity changed; failure artifacts preserved at {temporary}")
            accession = row["accession"]
            relative = Path(row["cik"]) / accession.replace("-", "") / f"{accession}-xbrl.zip"
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = Path(row["chosen_source"]["path"])
            verify_directory_chain(root_chains[row["chosen_source"]["cache_root_index"]], "cache root")
            before = source.stat(follow_symlinks=False)
            os.link(source, target, follow_symlinks=False)
            after = source.stat(follow_symlinks=False)
            linked = target.stat(follow_symlinks=False)
            receipt = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                       before.st_mode)
            if receipt != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                           after.st_mode):
                raise ValueError(f"source changed while linking: {accession}")
            if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError(f"output is not a hardlink for {accession}")
            linked_hash = sha256(target)
            if linked_hash != row["expected_package_sha256"]:
                raise ValueError(f"linked ZIP hash differs for {accession}")
            outputs.append({**row, "view_relative_path": relative.as_posix(), "linked_device": linked.st_dev,
                            "linked_inode": linked.st_ino, "linked_size": linked.st_size,
                            "linked_sha256": linked_hash})
        for receipt in metadata_receipts:
            verify_authenticated_receipt(receipt, "authenticated metadata")
        verify_directory_chain(destination_chain, "destination ancestor")
        current_temporary = temporary.stat(follow_symlinks=False)
        if (current_temporary.st_dev, current_temporary.st_ino) != temporary_receipt:
            raise ValueError(f"temporary root identity changed; failure artifacts preserved at {temporary}")
        manifest = {"schema_version": VERSION, "candidate": candidate_receipt,
                    "cache_roots": [str(root) for root in roots], "company_count": len(companies),
                    "filing_count": len(outputs), "selected_ciks": sorted(companies),
                    "metadata_receipts": metadata_receipts, "filings": outputs}
        manifest_path = temporary / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify_package_view(temporary, sha256(manifest_path))
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"destination appeared during publication: {destination}")
        verify_directory_chain(destination_chain, "destination ancestor")
        current_temporary = temporary.stat(follow_symlinks=False)
        if (current_temporary.st_dev, current_temporary.st_ino) != temporary_receipt:
            raise ValueError(f"temporary root identity changed; failure artifacts preserved at {temporary}")
        temporary.rename(destination)
        published = destination.stat(follow_symlinks=False)
        if (published.st_dev, published.st_ino) != temporary_receipt:
            raise ValueError("published root identity differs from owned temporary root")
    except BaseException as error:
        error.add_note(f"partial package-view artifacts were preserved; inspect owned temp path: {temporary}")
        raise
    return destination / MANIFEST_NAME


def verify_package_view(root: Path, manifest_sha256: str) -> dict[str, Any]:
    """Reopen a view and verify manifest, exact files, hashes and source hardlinks."""
    if SHA256.fullmatch(manifest_sha256) is None:
        raise ValueError("manifest_sha256 must be lowercase SHA-256")
    root = directory(Path(root), "package view root")
    root_chain = directory_chain_receipts(root)
    manifest_path = root / MANIFEST_NAME
    manifest, _manifest_receipt = authenticated_json(
        manifest_path, "package view manifest", manifest_sha256
    )
    metadata_receipts = manifest.get("metadata_receipts")
    if not isinstance(metadata_receipts, list) or not metadata_receipts:
        raise ValueError("package view metadata receipts are missing")
    for receipt in metadata_receipts:
        if not isinstance(receipt, dict):
            raise TypeError("package view metadata receipt must be an object")
        verify_authenticated_receipt(receipt, "authenticated metadata")
    declared_roots = manifest.get("cache_roots")
    if not isinstance(declared_roots, list) or not declared_roots:
        raise ValueError("package view cache roots are missing")
    roots = [directory(Path(root), "cache root") for root in declared_roots]
    if len({root.resolve() for root in roots}) != len(roots):
        raise ValueError("package view cache roots are not unique")
    root_chains = [directory_chain_receipts(root) for root in roots]
    rows = manifest.get("filings")
    if manifest.get("schema_version") != VERSION or not isinstance(rows, list):
        raise ValueError("invalid package view manifest")
    expected, identities, ciks = {MANIFEST_NAME}, set(), set()
    for row in rows:
        cik, accession = identity(row.get("cik"), row.get("accession"))
        if (cik, accession) in identities:
            raise ValueError(f"duplicate manifest filing: {cik}/{accession}")
        identities.add((cik, accession)); ciks.add(cik)
        relative = Path(row.get("view_relative_path", ""))
        canonical = Path(cik) / accession.replace("-", "") / f"{accession}-xbrl.zip"
        if relative != canonical or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe/noncanonical view path for {accession}")
        target = regular(root / relative, "view package")
        linked = target.stat(follow_symlinks=False)
        source = regular(Path(row.get("chosen_source", {}).get("path", "")), "chosen source")
        source_info = source.stat(follow_symlinks=False)
        if (linked.st_dev, linked.st_ino) != (source_info.st_dev, source_info.st_ino):
            raise ValueError(f"view package is no longer linked to source for {accession}")
        if (source_info.st_dev, source_info.st_ino, source_info.st_size, source_info.st_mtime_ns,
                source_info.st_mode) != (
            row["chosen_source"].get("device"), row["chosen_source"].get("inode"),
            row["chosen_source"].get("size"), row["chosen_source"].get("mtime_ns"),
            row["chosen_source"].get("mode")
        ):
            raise ValueError(f"source file identity changed for {accession}")
        matches = row.get("all_matching_sources")
        if not isinstance(matches, list) or not matches or matches[0] != row.get("chosen_source"):
            raise ValueError(f"matching source receipts are invalid for {accession}")
        indexes = [match.get("cache_root_index") for match in matches]
        if indexes != sorted(set(indexes)):
            raise ValueError(f"matching source root order is invalid for {accession}")
        for match in matches:
            index = match.get("cache_root_index")
            if not isinstance(index, int) or index < 0 or index >= len(roots):
                raise ValueError(f"matching source root index is invalid for {accession}")
            verify_directory_chain(root_chains[index], "cache root")
            if Path(match.get("path", "")) != cached_path(roots[index], cik, accession):
                raise ValueError(f"matching source path is noncanonical for {accession}")
            matching_source = regular(Path(match.get("path", "")), "matching source")
            matching_info = matching_source.stat(follow_symlinks=False)
            if (matching_info.st_dev, matching_info.st_ino, matching_info.st_size,
                    matching_info.st_mtime_ns, matching_info.st_mode) != (
                match.get("device"), match.get("inode"), match.get("size"), match.get("mtime_ns"),
                match.get("mode")
            ):
                raise ValueError(f"matching source identity changed for {accession}")
            if sha256(matching_source) != row.get("expected_package_sha256"):
                raise ValueError(f"matching source hash changed for {accession}")
            matching_after = matching_source.stat(follow_symlinks=False)
            if (matching_after.st_dev, matching_after.st_ino, matching_after.st_size,
                    matching_after.st_mtime_ns, matching_after.st_mode) != (
                match.get("device"), match.get("inode"), match.get("size"), match.get("mtime_ns"),
                match.get("mode")
            ):
                raise ValueError(f"matching source changed while hashing for {accession}")
        actual = sha256(target)
        if actual != row.get("linked_sha256") or actual != row.get("expected_package_sha256"):
            raise ValueError(f"view package hash changed for {accession}")
        manifest_receipt = row.get("layer1_manifest_receipt")
        if not isinstance(manifest_receipt, dict):
            raise TypeError(f"Layer 1 manifest receipt is missing for {accession}")
        verify_authenticated_receipt(manifest_receipt, "Layer 1 manifest")
        if (manifest_receipt.get("path"), manifest_receipt.get("sha256")) != (
            row.get("layer1_manifest_path"), row.get("layer1_manifest_sha256")
        ):
            raise ValueError(f"Layer 1 manifest receipt differs for {accession}")
        expected.add(relative.as_posix())
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    if actual_files != expected:
        raise ValueError("package view contains missing or extra files")
    if manifest.get("filing_count") != len(rows) or manifest.get("company_count") != len(ciks) or manifest.get("selected_ciks") != sorted(ciks):
        raise ValueError("package view scope totals differ")
    verify_authenticated_receipt(_manifest_receipt, "package view manifest")
    verify_directory_chain(root_chain, "package view root")
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="publish a new hardlink-only view")
    publish.add_argument("--candidate", type=Path, required=True)
    publish.add_argument("--candidate-sha256", required=True)
    publish.add_argument("--cache-root", action="append", type=Path, required=True)
    publish.add_argument("--destination", type=Path, required=True)
    verify = commands.add_parser("verify", help="strictly verify an existing view")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--manifest-sha256", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline publish/verify CLI."""
    args = parser().parse_args(argv)
    if args.command == "publish":
        manifest = publish_package_view(candidate=args.candidate, candidate_sha256=args.candidate_sha256,
                                        cache_roots=args.cache_root, destination=args.destination)
        print(json.dumps({"manifest": str(manifest), "manifest_sha256": sha256(manifest)}))
    else:
        manifest = verify_package_view(args.root, args.manifest_sha256)
        print(json.dumps({"status": "PASS", "filing_count": manifest["filing_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
