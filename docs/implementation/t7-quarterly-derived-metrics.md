# T7 — Quarterly Derived Metrics

T7 consumes an already built T6 quarterly pivot in memory and emits separate
derived records. It never reads Layer 1, selects a fact, rewrites a pivot,
recasts a value, or derives Q4.

The initial governed output is percentage points: QoQ growth, YoY growth,
evidenced component share, Gross Margin, and Operating Margin. QoQ uses the
explicit fiscal policy `(FY, Q) -> (FY, Q-1)`, with Q1 mapping to prior FY Q4;
YoY maps to `(FY-1, same Q)`. The matching predecessor column must actually
exist.

Every calculation requires reported numeric inputs with matching unit, full
canonical dimensions, selection view/as-of date, basis version, mapping
versions, and complete context lineage. Otherwise an `UNAVAILABLE` record
keeps the considered cell IDs and copied lineage. Standard metric roles are
recognised only from exact `us-gaap` QNames, never labels or local names.

Component share is intentionally narrower: it is emitted only where the T5
child definition names the exact same-column parent line and the child binding
has a `STATEMENT_COMPONENT` edge in `relationship_navigation`. Display order,
labels, and a dimension lens never create a parent/child claim.
