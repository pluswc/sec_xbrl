# History recovery financial source pin R3 candidate

Status: **FROZEN LOCAL SOURCE-ONLY CANDIDATE; financial source independently rejected, so
this pin is unusable and unaccepted**.

This bounded change prepares the later-45 History recovery runner to require the frozen financial
source candidate `5af1ef0244bcf014345d781f52c70a4e4914a256` instead of the previously accepted
`02226c91f36b5907f9e4d701c2b788747ef94c0a`. Separate independent review rejected the pinned
financial source candidate; its report SHA-256 is
`4ba9ae18ffcac7deedab995a3ed5aba49dadda821a018be859d7cf500d1cfb24`. This pin candidate
therefore grants no actual execution authority and does not describe `5af1ef0…` as accepted.

Only `FINANCIAL_SOURCE_SHA` changes in the runner. All 41 function bodies, the canonical
first-five validator, eight-stage receipt set, seventeen publication-manifest set, exact company
scope, fresh/reuse behavior, recovery engine, accounting selection, failure handling and resource
controls remain byte-equivalent after inverse literal normalization. The corresponding existing
unit-test expectation changes by the same single literal.

The runner remains fail-closed: later-45 requires a canonical first-five acceptance whose source
head, config, cohort, eight PASS receipts and seventeen publication manifests all bind to the exact
configured financial checkout. Existing R2 evidence cannot be relabeled or reused because R2 stage
7 ended before its quarterly receipt. If the financial source candidate is independently accepted,
a fresh first-five R3 must still produce all eight receipts and seventeen manifests under that exact
source, followed by the required actual audit, before any later-45 execution can be considered.

This source/tiny candidate reads no actual payload, performs no actual hash walk, acquires no C
lock, and runs no financial or History stage. Separate independent review of both the financial
source and this frozen pin candidate remains required after any separately approved repair and
repin. Main merge, push, PR, UI and remote work are outside this delivery.
