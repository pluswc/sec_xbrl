# C3-M3 — Reviewed Current/Comparable Companion

## Purpose

C3-M3 adds a separate `CURRENT_COMPARABLE` companion to one verified C3-M1
`AS_FILED` release. It does not modify, overwrite, or republish the original
AS_FILED facts. A consumer can therefore distinguish a fact as it was filed
from a later, evidence-governed comparable presentation.

## Evidence intake boundary

The companion accepts a versioned reviewed registry
(`c3-m3-reviewed-recast-evidence-v1`). Registry population is a reviewed data
operation. The code does **not** read filing prose, run NLP, infer a recast
from a changed number, or treat a later filing as proof by itself.

Every registry record identifies:

- company (CIK), canonical concept, complete canonical dimension key, period
  class, and every target period key;
- old and new basis versions;
- exact C3-M1 source-series candidate/raw Fact and exact prior AS_FILED fact
  IDs;
- source filing/date, document and table/narrative locator, and a durable
  narrative/table evidence identity;
- whether the output is directly re-presented (`RECAST_REPORTED`) or a
  reviewed derivation (`DERIVED_RECAST`).

The parser verifies every one of these bindings against the verified C3-M1
publication. A direct recast requires the exact later candidate/raw Fact. A
derived recast requires all exact candidate inputs, a compatible full scope,
and an approved derivation rule. Missing evidence, a mismatched dimension,
period, filing, or basis fails closed.

## Empty and incomplete registry behaviour

An empty registry is valid. It emits one `CURRENT_COMPARABLE` row per C3-M1
AS_FILED fact with `source_type=UNAVAILABLE` and
`RECAST_EVIDENCE_NOT_AVAILABLE`. It never silently falls back to AS_FILED.
The accompanying coverage table makes this lack of reviewed comparable
coverage explicit.

## Publication and consumption

The companion is an atomic, immutable directory containing:

- `current_comparable_fact.jsonl`
- `reviewed_recast_evidence.jsonl`
- `comparable_coverage.jsonl`
- `current_comparable_manifest.json`

Its manifest records the exact C3-M1 run fingerprint and manifest hash, row
counts, content hashes, and validation gates. The reader rejects a changed,
partial, extra-file, or upstream-mismatched release.

This is an analytical-plane producer. It is not an Excel policy, a default
basis selector, a Metric producer, or a text-extraction workflow.

## NVIDIA geographic recast golden

The test fixture models the FY2026 NVIDIA U.S. geographic principle:

- original Q1/Q2 AS_FILED facts remain in the upstream release;
- a reviewed revised Q1 can become `CURRENT_COMPARABLE` only through its
  exact evidence-bound later source;
- Q2/Q3/Q4 remain unavailable unless their own compatible evidence and source
  inputs exist; and
- old and new basis values are never combined.

The implementation contains no NVIDIA-specific condition or hard-coded value.
