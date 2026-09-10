# U5 completion and local acceptance

## Accepted boundary

U5 is **locally accepted and not merged** as of 2026-09-10. The accepted
product source is
`8867229455f9441807117a4a4a3e1ebaa8ae7eee`, based on completion baseline
`51c196f`. This acceptance covers prepared core overview and Axis time-series
canonical snapshots plus JSON, CSV, HTML and XLSX archival files. It does not
authorize or claim a remote push, PR, CI run or merge to `main`.

The offline hierarchy screen downloads the complete prepared table for the
current company, selected core metric or selected Axis. Screen collapse and
depth controls do not change that export and hidden rows remain included.
Arbitrary ordered partial row/period exports are the Python API boundary; a
concrete partial example is preserved at
`work/u5_delivery/final_8867229/examples/NFLX-revenue-2026Q1-Q2.{json,csv,html,xlsx}`.
Display values use the prepared raw unit with divisor `1`. Full unit
numerator/denominator, raw lineage, warnings, selection state and publication
identities remain in the canonical snapshot.

The consumer/export boundary performs no SEC collection, production parsing,
filing or recast selection, accounting calculation, approval, or cross-Axis
merge. Missing and blocked values remain null; no period or disclosure absence
is fabricated.

## Independent verification and acceptance evidence

Independent verification returned `PASS` for the frozen product SHA. The lead
then recorded `LOCAL_ACCEPTED_NOT_MERGED` in
`work/u5_delivery/LEAD_ACCEPTANCE.json`. Evidence is preserved without
overwriting the earlier failed candidate:

- final normal/quality artifacts and example:
  `work/u5_delivery/final_8867229/`;
- independent PASS report and probes:
  `work/u5_delivery/independent_8867229/REPORT.md`;
- prior independent FAIL report:
  `work/u5_delivery/independent_0562400/REPORT.md`.

The final verification measured:

- full pytest: **679 passed, 37 skipped in 46.77 seconds**;
- cached Axis/hierarchy regression: **21 passed in 42.48 seconds**;
- Ruff: **PASS**;
- **80** snapshots and **320** format files reconstructed and compared;
- **4,844** exported cells compared with the preimplementation API oracle;
- **24** actual offline browser downloads across normal/quality overview,
  selected metric and selected Axis states;
- **1,432** sealed U4 input artifact hashes unchanged.

Reproduce the full suite from the U5 worktree with:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp=/tmp/u5-independent-8867229-pytest
```

The explicit cached regression uses
`work/u3_axis_timeseries_complete/bundle` for `SEC_XBRL_AXIS_BUNDLE` and
`SEC_XBRL_HIERARCHY_BUNDLE`, `work/u3_followup_complete/bundle` for
`SEC_XBRL_AXIS_SOURCE_BUNDLE`, and the project root for
`SEC_XBRL_PROJECT_ROOT`, then runs `tests/test_axis_timeseries_cached.py` and
`tests/test_hierarchy_cached.py`. Exact browser and format probes are listed in
the independent report.

## Rework record and remaining limits

There was one independent-verification rework cycle. Candidate
`05624002c449a289736da787b01ff9b4cc61736a` failed on three P2 issues: JSON/HTML
links navigated rather than downloaded, HTML/XLSX presentation prefixed signed
amounts with an apostrophe, and null or malformed reported/derived provenance
did not fail closed. The replacement product commit resolved all three and the
full independent verification was rerun from the new frozen SHA.

Native desktop Excel rendering and cross-browser acceptance were unavailable;
XLSX content, types, layout and reconstruction were inspected through
openpyxl, while browser behavior was exercised with local Chromium 1210 and
HTTP blocked. The 37 skipped full-suite tests remain explicit. Verification did
not perform a live SEC collection, remote CI, push, PR or merge. The two test
durations above are measured command times. Model wall time was not measured,
and this record makes no performance claim.

This document-only completion commit records acceptance. It does not alter the
accepted product source or expand the U5 contract.
