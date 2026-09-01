# C3-M5 M2-v2 — Scoped Q4 Policy Registry / 범위 기반 Q4 정책

The reviewed registry is separate from consumer input.  It admits only the
fixed reviewed US-GAAP local-name allowlist and a retained PRE relationship in
a controlled primary consolidated Income / Operations or Cash Flows role. Both
FY and YTD source Facts must independently meet this evidence test.

A declaration identity contains normalized CIK, company canonical concept,
complete canonical dimension key, basis version, and unit semantics.  This
means an empty dimension signature is one governed scope and every Axis/Member
signature is a different governed scope. M2-v2
uses a registry reader and accepts a derived pair only when both analytical
Fact IDs are in the same exact-scope declaration.  It never authorizes a
custom, EPS/share/ratio/instant Fact through a concept-only match.

## Dimensional Q4 extension

`l2-m7-dimensional-q4-policy-v1` extends the governed policy to dimensional
Facts; it does not relax the accounting controls. A derived Axis/Member Q4 is
permitted only when the FY and YTD_9M inputs have the same company canonical
concept, full canonical Axis/Member (including typed/default-member) signature,
basis version, and unit semantics, and both are directly reported AS_FILED
monetary duration Facts. The output remains a separate `DERIVED` candidate
with `FY - YTD_9M`, both analytical/raw Fact IDs, filing IDs, declaration ID,
and rule version.

The extension intentionally does **not** derive a Q4 when a Product, Service,
segment, or geography label is only a custom-company concept or lacks the
retained standard-concept/PRE evidence required by the registry. It also does
not join different Members, fill a missing input from another basis, or derive
EPS, shares, ratios, margins, averages, instant values, or non-additive Facts.
Those cases remain explicit exclusions or require a separately reviewed policy.

`QuarterlyPolicyV2Publisher` stores derived Q4 candidates, exclusions and
predecessor linkages in an immutable companion.  Its manifest binds the exact
reader-attested M1 fingerprint/manifest, `CorpusRelease` fingerprint, and Q4
registry manifest SHA/version.  `QuarterlyPolicyV2Reader` verifies all of
these plus layout and content hashes before a consumer may display Derived Q4.

The Korean report can display reader-verified `Reported AS_FILED`, `Derived
Q4`, and `Pending Review`; it never computes Q4 itself or activates a recast.
