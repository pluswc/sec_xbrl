# History recovery financial source pin R3 candidate

Status: **REPAIRED SOURCE PIN LOCAL CANDIDATE; financial source and this pin are pending
independent review and remain unaccepted**.

This bounded change prepares the later-45 History recovery runner to require the frozen financial
source repair candidate `e56c1483a882ce000d0164cc91d561d4cc7bbf67`. The preceding pinned candidate
`5af1ef0244bcf014345d781f52c70a4e4914a256` was independently rejected; its report SHA-256 is
`4ba9ae18ffcac7deedab995a3ed5aba49dadda821a018be859d7cf500d1cfb24`. The `e56c148…` repair
candidate is frozen but still awaiting independent review and lead acceptance. This repin therefore
grants no actual execution authority and does not describe either source candidate as accepted.

Only `FINANCIAL_SOURCE_SHA` changes in the runner. All 41 function bodies, the canonical
first-five validator, eight-stage receipt set, seventeen publication-manifest set, exact company
scope, fresh/reuse behavior, recovery engine, accounting selection, failure handling and resource
controls remain byte-equivalent after inverse literal normalization. The corresponding existing
unit-test expectation changes by the same single literal.

The runner remains fail-closed: later-45 requires a canonical first-five acceptance whose source
head, config, cohort, eight PASS receipts and seventeen publication manifests all bind to the exact
configured financial checkout. Existing R2 evidence cannot be relabeled or reused because R2 stage
7 ended before its quarterly receipt. If `e56c148…` is independently verified and locally accepted,
a fresh first-five R3 must still produce all eight receipts and seventeen manifests under that exact
source, followed by the required actual audit, before any later-45 execution can be considered.

This source/tiny candidate reads no actual payload, performs no actual hash walk, acquires no C
lock, and runs no financial or History stage. Separate independent review of both the financial
source and this repaired pin candidate remains required. Main merge, push, PR, UI and remote work
are outside this delivery.
