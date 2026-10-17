# Universe 50 immutable package view

## Scope and state

This bounded operational adapter prepares one package root for the approved
exact-50 annual-and-quarterly input set (KDP replaces held PEP; financial cutoff
2026-10-10). It does not discover filings, parse XBRL, alter Raw data, select a
recast, calculate a metric, or assert financial readiness.

The proposal and code implementation are approved for local development. The
first frozen implementation `07c12cf` failed independent verification and
remains immutable evidence. Its three returned findings (submission-agent
accession prefixes, metadata hash/reopen races, and unsafe recursive failure
cleanup) are repaired in the subsequent frozen local commit after self-tests.
Independent Astra re-verification is **PENDING**. Local acceptance,
actual-data execution, PR, CI, main merge, and operational publication have not
occurred. In particular, this work has not read, hashed, or linked the 1,097
actual ZIP payloads.

The selection input is
`actual50_kdp_raw_candidate_v2.json`, expected SHA-256
`cbcf87dd3deedb75035b7bacc752af93d55d96a3f63ed577d416b97b3b994249`.
The approval correction contract is historical evidence at SHA-256
`8be34278059921773e7178c526b5c60a11f7b880296d6035ea8f694683698ff7`;
the tracked contract here is sufficient to understand and verify the adapter.

## Contract

`tools/universe50_package_view.py publish` requires the candidate path and
expected digest, each cache root in deterministic priority order, and a new
absolute destination. It verifies the candidate, every selected plan and
intake digest, exact plan/intake CIK-accession membership, unique selection,
and candidate totals. Each intake `source_run` identifies its immutable
`snapshots/{cik}/{accession-without-dashes}/layer1_manifest.json`; that manifest
must match the filing identity and supplies the authoritative package SHA-256.
The accession prefix is not required to equal the filer CIK because a filing
agent may be the accession submitter; the plan, intake, and Layer 1 manifest
must instead agree exactly on the separately validated CIK and accession.
This receipt is a source-package identity check, not a new Raw-quality or
financial-readiness decision.

For each filing, the adapter checks only the canonical ZIP location beneath
each explicitly declared cache root. It performs no hidden discovery. It
streams the full SHA-256 of every existing candidate ZIP, records all matches,
and chooses the first matching root. Missing matches, conflicting selection
metadata, changed files, duplicate identities, symlinks, path traversal,
existing/partial destinations, destinations beneath cache or source-run roots,
and different filesystems fail closed.

Candidate, plan, intake, Layer 1, and package-view manifest JSON is hashed and
parsed from the same open file bytes. Device, inode, size, mode, and nanosecond mtime
receipts are checked against the path and checked again before publication or
verification completes, so replacing a path cannot bless different parsed
content under the original hash.

Publication uses `os.link` only. It has no copy fallback and never writes,
chmods, or changes timestamps on source or linked ZIP inodes. Source device,
inode, size, mode, and nanosecond mtime are checked before and after linking.
The expected hardlink-count and ctime changes are not claimed as immutable. A
sibling private temporary directory holds the links and manifest; strict
verification completes before one rename exposes the new root. Destination
ancestors and the temporary root are pinned by device and inode. On failure,
the adapter never recursively deletes a replaceable pathname: partial evidence
is preserved at the named temporary path for explicit inspection and cleanup.

The manifest binds the candidate, ordered roots, 50-CIK/1,097-filing scope,
Layer 1 manifest path and digest, authoritative archive digest, chosen source
path and file identity, every matching cache source, output relative path,
linked identity, size, and full linked-file digest. `verify` requires the
expected manifest SHA-256, reopens every source receipt and Layer 1 manifest,
re-hashes each linked ZIP, proves source/output inode equality, and rejects
missing or extra files.

## Replay (synthetic data only)

```bash
./.venv/bin/python -m pytest -q tests/unit/test_universe50_package_view.py
./.venv/bin/ruff check tools/universe50_package_view.py tests/unit/test_universe50_package_view.py
./.venv/bin/python tools/universe50_package_view.py --help
```

An eventual approved actual-data run must pass seven explicit `--cache-root`
arguments and a new destination on their shared filesystem. That run and its
arguments remain outside this implementation milestone.
