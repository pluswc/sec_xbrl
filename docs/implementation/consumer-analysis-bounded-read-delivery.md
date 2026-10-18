# Consumer analysis bounded History read delivery

## Status and scope

This delivery implements a source-and-tiny-fixture candidate for bounded
ordinary History cell consumption during consumer analysis preparation. The
approved base is `fd9a17910a7b1cfbb4e71e2ded6f4bc23cda686e`. The candidate is
not independently verified or locally accepted until those states are recorded
separately, and it does not make the actual first-five financial stage ready.

The trigger was an actual first-five `annual-analysis` run that stopped at the
16 GiB process-tree RSS limit. Its sampled stop value does not establish the
eventual unbounded peak or the contribution of each allocation. Actual Raw,
History, failed output, and partial output payloads were not read during this
source diagnosis and tiny implementation.

## Implemented boundary

`HistoryPublicationReader.stream_cells()` is an additive ordinary-publication
API. It retains canonical columns, rows, and scope, while exposing cells as a
lazy single-pass iterator backed by the existing bounded verifier. The reader
still verifies the declared file hash before iteration and validates row count,
schema, declared JSON fields, and every decoded record. A consumer may discard
an out-of-window cell only after that cell has passed the same decoding and
validation path.

`prepare_analysis()` consumes that stream directly. It immediately transforms
each selected source cell into the existing compact cell, trace, node, source
index, and evidence records and does not retain a tuple of source cells or their
bulky bindings. Fiscal-year inference drains its cell stream completely, even
though inference uses only column headers. Downstream code retains period scope
dictionaries instead of complete source panels.

Reviewed publications continue through their existing composed `load()` path.
This preserves reviewed suppression, quarantine, additions, and review scope;
the ordinary parent files are never used as a shortcut around the overlay. The
existing eager public `load()` API and all generation and recovery behavior
remain unchanged.

## Preserved contracts

The change does not alter formulas, core-row selection, fiscal-period rules,
basis compatibility, stable IDs, record order, quality decisions, source
lineage, CAL direction, DEF traversal and `targetRole`, PRE evidence, graph
materialization, or publication schemas. `_raw_material()` and complete
eight-table Raw snapshot verification are unchanged. No ticker-specific path,
sampling, reduced fiscal scope, memory-cap increase, or Raw validation bypass
is introduced.

## Tiny acceptance evidence

The owned synthetic tests compare every logical analysis dataset produced by
the streaming path with the legacy eager path. They cover:

- explicit annual FY plus exact fiscal-year-end INSTANT preparation;
- inferred-year quarterly QTD plus INSTANT preparation;
- both `AS_FILED` and `LATEST_REPORTED` views;
- primary-statement evidence in rich bindings, missing/null candidates, stable
  IDs, order, typed values, traces, provenance, graph records, and metrics;
- a live-source-record invariant demonstrating that source cells are consumed
  incrementally rather than retained as a full population; and
- hash, count, schema, and malformed-JSON failures in cells outside the selected
  analytical window.

Only publication UUID volatility is excluded from the logical comparison.
Business IDs, values, ordering, and lineage are compared exactly.

## Remaining gates

The implementation candidate requires a frozen local commit and separate
read-only Astra verification. Source/tiny PASS does not authorize reading or
rerunning actual first-five data. A new actual run, local acceptance, native
dashboard use, push, PR, CI, and main merge remain separate lead/user decisions.
