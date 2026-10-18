# History recovery financial source pin R3 candidate

Status: **R3 SOURCE PIN LOCAL CANDIDATE; financial source is source/synthetic locally accepted,
but this recovery pin is pending independent review and remains unaccepted**.

This bounded change prepares the later-45 History recovery runner to require the source/synthetic
locally accepted financial R3 source `4357c838722da281d2474bfc881b3a4a2ed4e988`. The first pinned candidate
`5af1ef0244bcf014345d781f52c70a4e4914a256` was independently rejected; its report SHA-256 is
`4ba9ae18ffcac7deedab995a3ed5aba49dadda821a018be859d7cf500d1cfb24`. The following
`e56c1483a882ce000d0164cc91d561d4cc7bbf67` repair was also independently rejected; its report
SHA-256 is `45023e8aaa8a21e3b4e79bd0dc51bc983f94ef71322200dfb3d4691da0528201`.
The `a37763e…` candidate was then independently rejected; its report SHA-256 is
`1c86ee2f469d0ed95b7813af471d6b9b0501246bc5661cfeba8882bb548d3997`.
The repaired `4357c83…` source passed separate independent review and source/synthetic local
acceptance, recorded by lead acceptance SHA-256
`bdd454bdb7750f429bf1d90e3a44197a8ce987df4fb84751f7170044ce3e999e`.
This repin still grants no actual execution authority and is not itself accepted.

Only `FINANCIAL_SOURCE_SHA` changes in the runner. All 41 function bodies, the canonical
first-five validator, eight-stage receipt set, seventeen publication-manifest set, exact company
scope, fresh/reuse behavior, recovery engine, accounting selection, failure handling and resource
controls remain byte-equivalent after inverse literal normalization. The corresponding existing
unit-test expectation changes by the same single literal.

The runner remains fail-closed: later-45 requires a canonical first-five acceptance whose source
head, config, cohort, eight PASS receipts and seventeen publication manifests all bind to the exact
configured financial checkout. Existing R2 evidence cannot be relabeled or reused because R2 stage
7 ended before its quarterly receipt. A fresh first-five R3 must still produce all eight receipts
and seventeen manifests under exact source `4357c83…`, followed by the required actual audit,
before any later-45 execution can be considered.

This source/tiny candidate reads no actual payload, performs no actual hash walk, acquires no C
lock, and runs no financial or History stage. Separate independent review and local acceptance of
this recovery pin remain required. Main merge, push, PR, UI and remote work are outside this
delivery.
