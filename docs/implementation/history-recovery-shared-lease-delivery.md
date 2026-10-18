# History recovery shared C lease delivery

Status: **SOURCE/OWNED-SYNTHETIC IMPLEMENTED CANDIDATE; independent verification and
local acceptance pending; no actual execution authority**.

## Milestone and acceptance boundary

This resource-only change lets the accepted History recovery runner borrow the
canonical collection C lock from a fixed outer lifecycle keeper. The keeper can
therefore retain the lock until its complete owned process forest has stopped and
been reaped. The public CLI without an external capability keeps the existing
`heavy_lock` behavior. History selection, financial validation, the canonical
first-five eight-receipt/seventeen-manifest gate, source pins, recovery outputs,
receipt schemas, accounting rules and worker resource limits are unchanged.

This candidate is based on accepted recovery source `d714f5a679670e12ba53dbb023e1201c3bc64f80`.
The exact frozen candidate and evidence hashes are recorded in the separate writer
report. This delivery does not authorize actual payload reads, a real C lock, a
later-45 recovery, Layer 3 execution, main merge, push or PR.

## Optional private capability

External mode is selected only when all three inherited environment values exist:

- `SEC_XBRL_RECOVERY_SHARED_C_FD`: the inherited canonical C descriptor;
- `SEC_XBRL_RECOVERY_SHARED_C_CAP_FD`: a one-shot pipe containing at most 65,536
  bytes of JSON;
- `SEC_XBRL_RECOVERY_SHARED_C_PARENT_PID`: the immediate keeper PID.

Any partial declaration rejects instead of falling back to the internal lock. The
JSON object has the exact keys `schema_version`, `operation`, `parent`, `config`,
`go` and `lease`. Its version is
`universe50-history-recovery-shared-c-lease-v1`, operation is
`recover-history-one`, parent binds PID and Linux process birth ticks, config and
GO bind canonical absolute paths plus SHA-256, and lease binds the canonical
`resource_root/.one-heavy.lock` path, device, inode and mode.

Validation occurs before the unchanged GO/source validator. It proves the parent
PID and birth both before and after validation, the descriptor/path identity, the
parent-owned exclusive flock in `/proc/locks`, and the lock row attached to the
inherited descriptor in `/proc/self/fdinfo`. The latter distinguishes the locked
open file description from a separately opened descriptor to the same inode.
Linux reports `/proc/locks` device numbers in hexadecimal and its inode in decimal;
the parser and real-FD regression preserve that distinction.

The capability pipe is consumed and closed once. Its environment fields are
removed before the recovery worker environment is built. `run_stage` passes the
same borrowed descriptor to the existing worker beside the existing supervisor
token pipe. Neither runner nor worker opens, flocks, unlocks or closes that
descriptor early. The outer keeper owns its last close after whole-forest cleanup.
The worker's existing independent nonblocking lock probe remains unchanged and
continues to require that C is held.

## Verification and limits

Owned Linux regressions cover exact positive binding; every envelope field;
changed config/GO bytes; missing or partial environment; non-pipe capability;
unheld, wrong-identity and same-inode/different-open-description descriptors;
worker environment sanitation; same-FD inheritance without a second C lock;
legacy internal-lock compatibility; and lock retention after the original keeper
exits until the inherited borrower descriptor exits. Existing recovery and
canonical-source suites are rerun under the recorded 1 GiB/120-second guard with
PDEATHSIG, subreaper/whole-forest sampling, child and adopted-child reaping,
unlimited `RLIMIT_AS`, pre-import actual/cache/network denial, Polars 2 and BLAS 1.
The writer recorded 30 focused lease PASS, 94 existing recovery PASS with the
accepted parent-death test deselected, and 35 canonical/reuse/source-proof PASS.
These are writer checks and do not replace the pending independent review.

The guarantee covers the fixed outer keeper and inherited open file description.
It does not claim protection after uncatchable keeper `SIGKILL`, kernel failure,
power loss or a hostile same-user Python process. Phase-two Layer 3 entry changes
and the outer later-45 keeper remain separate implementation and acceptance work.
