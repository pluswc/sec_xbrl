# U3–U5 main delivery

## Integration scope and status

The user authorized integration of the already accepted U3–U5 history into
`main`. [PR #63](https://github.com/pluswc/sec_xbrl/pull/63) merged that history
at `9708508ec953ee4323ae29318c639abc9e0650b6` on
2026-09-10 03:12:14 UTC (2026-09-10 12:12:14 KST). The
[PR CI](https://github.com/pluswc/sec_xbrl/actions/runs/34432286122) and
[post-merge main CI](https://github.com/pluswc/sec_xbrl/actions/runs/34432422811)
both completed successfully.

The integration candidate contains these accepted boundaries:

| Stage | Accepted source/evidence | Delivered capability |
| --- | --- | --- |
| U3 | product `3098be6db7622f2ec444a9979732b7dfaa685641`; closeout `32212caba5daf8273663d70ba3075db5d1d56fc7` | importance, source/PRE hierarchy, complete Axis time series and provenance |
| U4 | product `3236778e57872b8ea41e421534e4a9d9ea0d58ff`; local completion `51c196f` | bounded explicit refresh, recovery/resume and quality materialization |
| U5 | product `8867229455f9441807117a4a4a3e1ebaa8ae7eee`; local acceptance `2d2c96e56cc2f831b9aa9d21d67dd08bf479ca65` | canonical snapshot and offline JSON/CSV/HTML/XLSX exports |

The integration includes accepted revision
`2d2c96e56cc2f831b9aa9d21d67dd08bf479ca65` and its later documentation-only
delivery records. PR #63 added the accumulated U3–U5 changes and governance
records without rewriting accepted product source.

## Reproduction and fresh-checkout requirements

The previously completed local verification includes U5's 679 passed / 37
skipped full suite and 21 explicit cached tests, U4's acceptance evidence and
U3's independent Axis/hierarchy evidence. These remain historical evidence;
PR #63 and post-merge `main` CI both passed as linked above.

For a source-only checkout:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
git fetch origin main
git merge-base --is-ancestor 9708508ec953ee4323ae29318c639abc9e0650b6 origin/main
```

The ancestry command exits `0` when the fetched remote `main` contains the
recorded U3–U5 merge.

Cache-backed/live acceptance materials are deliberately absent from a fresh
clone. Cached tests require the explicit prepared bundle paths documented in
the U3/U5 completion records. Live refresh additionally requires SEC network
access, administrator inputs, a writable workspace and explicit as-of/review
cutoffs. Normal API and export usage needs only a prepared bundle; see the
[investor usage guide](../usage/investor-analysis.md).

## Limits

This delivery does not add product behavior beyond accepted U3–U5 source. It
does not make collection autonomous, approve accounting mappings, merge Axis
views, fill nulls, or treat a registration as prepared data. Prepared reports
are shareable local files, not a hosted service. U5's native desktop Excel and
cross-browser limits, U4's bounded orchestration boundary and U3's reviewed
hierarchy limits remain in their completion contracts.

The PR URL, CI results and merge SHA above are the current delivery record.
Historical local-acceptance documents retain the status that applied on their
recorded dates.
