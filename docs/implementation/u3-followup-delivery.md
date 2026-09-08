# H1 → U3-R → H2 → H3 local delivery contract

This followup starts from frozen U3 `09309c80700fed2115e2b18eddd2c21dc5e200e3`
on `codex/u3-followup-hierarchy`. The original worktree and every original
publication remain unchanged. `work/U3_FOLLOWUP_TASK_DEFINITIONS.md` was found
and read; the old `work/U3_HANDOFF.md` is not a completion record.

The replacement implementation session is the sole writer. The prior Sol writer
was closed before replacement; it left a plan and untested CAL draft. The lead
approved replacement after that draft did not produce a tested slice. Lead
requirements/accounting decisions and a separate read-only Astra/Pascal verifier
remain separate roles. The current writer environment identifies GPT-6; no claim
about a model's relative speed, price or quality follows. Terra's read-only source
comparison is evidence, not candidate certification. Final acceptance requires
an independent PASS at the locally frozen SHA. User authorization excludes
push/PR/merge, overriding delivery-workflow's remote-push prerequisite.

## New producer and datasets

`analytics.hierarchy_publication.prepare_hierarchy` takes an immutable existing
analysis bundle, explicit source-run → package-root adapters, a new destination,
a local taxonomy cache and new supplemental-extraction directory, and explicit
review records. It verifies every old dataset before copying its bytes. History
intakes identify the eligible snapshots; the existing complete snapshot verifier
checks the actual Raw tables. ZIP SHA must equal both package manifest and Raw
filing package hash. The discovery-declared primary member alone supplies the
HTML row census. No discovery rewrite, raw correction, or new selection engine
was introduced.

The new `hierarchy` manifest has company/file-scoped datasets:

- `filings`, `filing_coverage`: all attested eligible filings and per-section
  primary-table inclusion/unprepared reasons, including amendments.
- `source_tables`, `source_statement_rows`, `row_coverage`: independent actual
  HTML table/row enumeration, original cell text and column/span positions,
  document/table SHA, XPath, Inline identity and exact Raw fact binding. Blank,
  heading, untagged and numeric rows all remain in the denominator. Every table
  is catalogued, including notes, segments, adjustments and equity disclosures.
- `statement_facts`: copied Raw values, full concept/namespace/taxonomy, Context,
  Unit, all explicit/typed/default dimensions, filing, report/filed dates,
  source locators, M6 period classifications and reasons. FY/YTD/QTD/instant
  stay separate; `RAW_AS_FILED` does not claim a longitudinal canonical mapping.
- `statement_rows`: PRE paths including abstracts, source edge order, distinct
  filing/role/arcrole/link/arc base sets, alternative paths and cycle stops.
- `statement_relationships`: original Raw relationships with origin tags, plus
  explicitly tagged supplementary Arelle Calculation 1.1 evidence where needed.
- `calculation_checks`: strict Raw-scope signed checks. Distinct duplicate
  parents/inputs are ambiguous, conflicting identical IDs reject, repeated arcs
  never double count. Nonfinite/nil, missing input/parent, incompatible scope,
  duplicate and genuine mismatch states remain distinct. No rounding tolerance.
- `source_calculation_checks`: separate exact source-table occurrence checks;
  all facts must actually bind that table and the complete network remains
  separate. A repeated fact in MD&A cannot make the uniquely bound statement
  cell ambiguous, while global Raw ambiguity stays in `calculation_checks`.
- `member_paths`: independent Axis DEF paths, targetRole, full remaining base
  set, per-path cycle/usability evidence and actual source fact references.
  No member/axis aggregation or fabricated Cartesian products.
- `raw_importance_v2`, per-view `importance_v2`: five separately persisted
  evidence signals described below.
- `source_reconciliation_checks`: separately reviewed exact source equations;
  they never become CAL, semantic equivalence, or share approval.

Primary HTML locators use maximum overlap with a qualifying primary PRE role,
then original source order as a deterministic tie break. Scores and all excluded
nonprimary tables are retained for audit. This is a locator policy, not an SEC
statement-meaning guarantee. PRE paths and actual HTML coverage are separate.
Untagged heading alignment only uses unique exact normalized PRE abstract
labels, tagged as display evidence within that role; it grants no accounting
relation. The exact NVDA OpEx grouping additionally has a hash/row/PRE-bound
lead display review. No numeric value or dimension is relabelled.

The 82-file real cache contains 4,771 original tables. AMD's 10-K/A
`0000002488-26-000021` has no classified IS/BS/CF table: all three section
statuses explicitly say unprepared, while its Raw amendment and HTML remain
preserved. This delivery does not claim three primary tables per filing.

## Source gaps and bounded approvals

MSFT `0001193125-26-191507` contains Calculation 1.1 arcs in its cached XSD.
The old extractor recognizes only the 2003 summation-item arcrole, so its
immutable snapshot has no CAL rows. `calculation11` uses Arelle's effective
fully qualified sets for exactly
`https://xbrl.org/2023/arcrole/summation-item`, validates endpoint/role IDs
against the snapshot, and persists the package/document hashes, source arc
line, Arelle parser version and supplemental policy version. No old Raw row
is changed. A missing local taxonomy/extraction configuration fails closed
when such source evidence is present. Only exact signed Decimal arithmetic
is checked: this is **not** Calculation 1.1 interval/rounding certification.

The actual MSFT primary statement has GrossProfit + R&D(-) + selling/marketing(-)
+ G&A(-) = OperatingIncome. It has no displayed OpEx subtotal. The different
NVDA OpEx network never replaces this four-input structure.

Only NVDA `0001045810-25-000230`, document SHA
`341328ad66e7618d5c10b8143d3833ffb0e6d837211f81948819bb594496c368`,
table `/html/body/div[64]/table`, table SHA
`edc07da1ff5638aff62833c5a98f7cb655f502bf796794e820fb68715fc5d6da`,
has a two-period economic share review. Current three-month Inline IDs are
R&D f-42, SG&A f-46, parent f-50; same-table prior IDs are f-43, f-47, f-51.
The initial Terra prior **prepared-panel** IDs belonged to a different filing;
lead and Terra corrected this before approvals were bound. The actual same-table
prior Raw IDs are `fact_6c196d8796454dc9360eebc6`,
`fact_675f87e3a9257c1a15535b0d`, `fact_f41e243c8b7f94b85d1ec570`.
The review never transfers to a different source-selected comparative cell.
Current shares are approximately 80.5789% and 19.4211%; changes are ±1.502589pp,
so neither triggers the 5pp rule. FY/YTD and newer filings have no share review.

A separate exact source-reconciliation approval covers the same NVDA document,
table `/html/body/ix:continuation[33]/ix:continuation/div/table`, SHA
`adf883a005faa1ba3e025e0f287caa53c5f1b35d801816483c330b25fa5b2808`:

```
+ f-902 38,267m segment operating income
- f-906  1,655m stock-based compensation
- f-910    515m unallocated operating expense
- f-914     87m acquisition/other cost
+ f-918    624m interest income
- f-922     61m interest expense
+ f-926  1,363m other income
= f-930 37,936m consolidated pretax income
```

Inputs retain OperatingSegmentsMember and CorporateNonSegmentMember scopes;
the parent is undimensioned. An exact per-input scope review authorizes only
this equation. Common CIK, filing, actual period, unit, view/as-of and Raw basis
must still agree. No intermediate 36,010m row is inserted in the original table,
no same-scope CAL gate is relaxed, and no segment-profit equivalence or share
approval follows. All original source values remain unchanged.

## U3-R v2 decision

Policy `u3r-important-items-v2` is additive to unchanged U3 v1:

- share ≥ 10% with a separately reviewed complete/exclusive positive parent;
- absolute comparable share change ≥ 5 percentage points;
- absolute YoY rate ≥ 25% AND absolute delta ≥ 1% of an exact positive
  disclosed reference scalar; that scalar is a scale, not a composition claim;
- top three comparable monetary amounts as a display signal, without sorting
  the source statement into rank order.

Amount, share, amount change, rate, and share change each carry value/status,
reason, source inputs, actual current/prior periods and relevant denominators.
The policy ID, review and selection cutoffs and selection reason are exposed.
The new review decision cutoff is separate from the historical source/recast
selection cutoff. Review timestamps are timezone-aware and not backdated.

Both share periods require separate exact approved source cells, identical
parent definition and complete child concept sets, common unit/full dimensions,
company/view/as-of/basis, the same reviewed source table/economic scope and
actual compatible 3M/YoY boundaries. A shared economic-scope string is
insufficient. Four source IDs and both parent denominators accompany pp changes.
Zero-child decompositions are not approved in this initial new review contract;
zero/negative parents, zero/negative base rates, nil, nonfinite and sign changes
fail closed. Compatible monetary delta remains available when a rate is
unavailable. No normalized share or residual Other is produced.

Prepared Analytical comparisons reuse the existing governed ratio compatibility
gate and retain unknown/broken basis warnings. Exact source-table monetary
amounts also receive v2 evidence. Only same-filing, same-table official standard
monetary QTD concepts can receive Raw reported-value YoY arithmetic, with exact
unit/full dimension/view/as-of/basis and real year/start/end intervals. This is
explicitly `REPORTED_ARITHMETIC_NOT_RECAST_VALIDATED`, not a new canonical or
CURRENT_COMPARABLE approval. Custom raw concepts remain comparison-unapproved.
No annual/YTD growth policy is introduced. Latest Raw reference periods are
prepared per period class and never filled from an old absent disclosure.

AMD Q3 2024 Embedded -25.42%/-316m and Client +29.46%/+428m motivate examining
a 25% default instead of inheriting v1's 50%. They are not claimed as actual
25%+1%-scale selections: their compact analytical rows lack an exact compatible
parent scalar, which remains a warning. Actual approved NVDA R&D/SG&A provide
the real positive rate+scale case. Rank-six share and pp-only triggers, exact
threshold neighbors, tiny-base, invalid denominator and incompatible reviews
are separately labelled **synthetic** tests, not actual-company evidence.

## H2 consumer and operational limitations

`AnalysisClient` adds `statement_catalog`, `statement`, `pre_table`, `axes`,
`member_metrics`, and `importance_v2`. All read prepared checksum-verified
Parquet. Unknown company/filing/axis/member/concept is not called a missing
disclosure. Member lookup returns only actually reported metrics and retains
full multidimensional signatures, aliases and definition distinctions.

`display.hierarchy.render_hierarchy` writes a standalone local HTML screen and
prepared JS shards. It reads the same API/datasets, never source ZIP/XML.
One table body supports source order/reviewed grouping, a separately labelled
PRE order, and exact independent Axis/member metrics. Folding changes visibility
only. Protected subtotals and mandatory warnings survive ancestor collapse.
Blank layout rows are retained in coverage but may be hidden for readability;
full restore reveals them and the count. Exact decimal strings receive thousands
separators without conversion to binary floating point. Korean font is copied
from the locally installed Windows font to generated output, never committed.

Original source-label wording, row/table differences, unreconciled or missing
CAL evidence and custom mapping caveats remain inspectable. Deep DEF diamonds
and targetRole are kept; `usable=false` excludes that target, not its descendants.
Per-path usability is **not** full DRS validation, including conflicting usable
paths in one effective domain. See the
[XBRL Dimensions specification](https://www.xbrl.org/specification/dimensions/per-2011-11-20/dimensions-per-2011-11-20.html).

AMD's FY2025 Gaming tags retain the original complete Product/BusinessSegments
scope discrepancy even where rendered business labels suggest a different
classification. Existing reviewed Layer 2 data remain available through the
unchanged Analytical APIs; the new Raw member lookup never infers a historical
reclassification from a display label. Source segment adjustments remain
separate from the connected primary statement values.

## Reproducible evidence and freeze

Final generated files belong under `work/u3_followup_complete`. Provisional
candidate directories are retained; original U3 files are never overwritten.
`approved_configuration_final.json` contains exact review scopes, inputs and
source hashes. `probes/build_final.py` invokes the generic producer from all six
existing registered history sources and renders the local screen. This is
cached re-preparation, not live SEC collection. Existing registration and
refresh code remains covered by its original regression tests.

Focused synthetic tests live under `tests/unit/test_statement_*`,
`test_importance_v2.py`, `test_calculation11.py`, `test_source_reconciliation.py`.
`tests/test_hierarchy_cached.py` is explicitly opt-in actual-cache evidence using
`SEC_XBRL_HIERARCHY_BUNDLE` and `SEC_XBRL_PROJECT_ROOT`. The real suite verifies
HTML row coverage, FY/YTD/QTD/instant, NVDA and MSFT arithmetic, disclosed
segments/adjustments, AMD reorganization/amendment, six-company queries and old
v1 byte/value equality. Producer/parser/network entry points are blocked during
consumer probes. The lead's 831-file hashes provide the original-file baseline.

The writer reports full pytest, Ruff, actual browser/API parity and immutable
hash checks in `VERIFICATION.md` in the generated output directory. A separate
read-only verifier must certify the final local SHA; interim lead probes and
writer self-checks are not independent final PASS.

## Independent review F1–F3 display correction

The first frozen candidate `ea336a3b9d012e6a2a99d6f579434c77645fb10d`
received an independent **FAIL** for three display defects. Its complete final
bundle/HTML and independent evidence are preserved under generated
`work/u3_followup_complete/frozen_ea336a3`. The lead authorized the sole writer
to correct these defects without changing the approved economic scope.

Analytical is a company-publication overview. Its heading now uses the exact
prepared overview context: company, view, as-of/source selection cutoff, original
review cutoff, fiscal period range, and recast-comparability warnings. It does
not claim to be the selected historical filing or a historical as-of query.
Filing/table controls are disabled there and restored for source/PRE/member
exploration. Analytical coverage describes its prepared periods and rows, not
an unrelated source table.

PRE rows now merge mandatory importance warnings by exact current fact ID,
including sign/base/scope warnings. The existing visibility protection therefore
keeps these rows visible through ancestor collapse and depth restrictions.
Warnings on a different fact ID do not transfer merely through a concept label.
Raw duration labels explicitly say `종료일 제외` in both period headers and value
cells; instant labels say `시점`. Raw dates are not changed.

These display-only corrections reuse the byte-identical governed bundle and
its original publication ID. A rebuilt HTML page separately embeds
`renderer_source_commit`; generated freeze records distinguish this renderer
source from the bundle-producing commit. No producer recomputation or review
cutoff adjustment is needed.

The committed opt-in browser regression `tests/browser/hierarchy_regression.mjs`
tests historical-selection/Analytical transitions for six companies, prepared
context/value parity, source/PRE/member control restoration, actual AMD tax and
discontinued-operations warnings, exact-ID synthetic warning isolation through
collapse/depth, and duration/instant labels. Run with explicit local paths:

```bash
SEC_XBRL_HIERARCHY_HTML=/absolute/path/to/html/index.html \
SEC_XBRL_BROWSER_REPORT=/absolute/path/to/new-report.json \
SEC_XBRL_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
SEC_XBRL_CHROMIUM=/absolute/path/to/chrome \
node tests/browser/hierarchy_regression.mjs
```

Playwright and Chromium may use installed defaults when those optional paths
are omitted. HTTP(S) requests are blocked and asserted absent. Synthetic
browser fixtures are labelled separately from actual filing evidence.
