# Universe-50 History resource observation

Status: **IMPLEMENTED locally; operational evidence only**

Scope: bounded, read-only observation of an already authorized History worker

Acceptance effect: none; this does not perform accounting, XBRL, History or period-readiness
verification

## Purpose and interface

`tools/profile_history_run.py` attaches to one explicitly supplied Linux PID. It verifies an
expected command fragment without recording the process argv or environment, then fixes identity to
the PID's `/proc/<pid>/stat` start time. It records cumulative process CPU seconds, interval CPU use
as a percentage of one core, RSS, and kernel read/write byte counters when `/proc/<pid>/io` provides
them. Missing I/O counters are `null` with a reason; they are never presented as zero.

The caller must supply one log and one small output root. Log observation reads only newly appended
bytes, except for a bounded tail on initial attachment or truncation. Only JSON objects with a string
`stage` are stage events, and only their `stage`, `event`, `status` and `timestamp` scalar fields are
retained. If no recognized new event exists, the sample says `unknown`; the observer does not infer a
stage or ETA. Filesystem state is separate supporting evidence: a bounded non-symlink file scan
reports regular-file and temporary-file bytes, deltas and available filesystem bytes. A
`--max-files` cap prevents repeated unbounded file enumeration, and capped totals are explicitly
partial.

The output directory must be fresh and outside the observed root. It receives append-only
`samples.jsonl`, atomically replaced `summary.json`, and a short atomically replaced `report.md`.
The sampler sends no signal, uses no ptrace, changes no process or observed file, and does not read
Raw or parent hashes, decode Parquet, query SQLite, or traverse `/proc/<pid>/fd`.

## MRK invocation

The authorized MRK recovery worker supplied for this milestone had the following exact invocation.
The evidence directory name must be new for each attachment.

```bash
/home/plusbdw/anaconda3/envs/bundle_py31213/bin/python \
  tools/profile_history_run.py \
  --pid 1293268 \
  --expected-command-fragment universe50_history_recovery_ops.py \
  --log /home/plusbdw/user_work/projects/sec_xbrl/work/universe50_quarterly_20261010/resumption_20261017_t3v2/actual_execution/later45-MRK-reported-reuse-r2/execution.summary.log \
  --observe-root /home/plusbdw/user_work/projects/sec_xbrl/work/universe50_quarterly_20261010/resumption_20261017_t3v2/ops_writer/history-mrk-reported-reuse-20261022/MRK-history-recovery-t3v2-later45-20261024-mrk-reuse-r2 \
  --output-dir /home/plusbdw/user_work/projects/sec_xbrl/work/universe50_quarterly_20261010/resumption_20261017_t3v2/performance_observations_20261024/mrk-sampler-r1 \
  --interval 5 \
  --duration 60 \
  --max-files 2000
```

`--duration` limits the attachment interval; omitting it observes until process exit, zombie state or
PID reuse. Process exit and PID reuse have distinct termination reasons. Elapsed time always starts
when this sampler attaches, so it must not be described as the worker's complete runtime.
The sampler must run in a PID namespace and permission context that can read the worker's `/proc`
entries. Absence from a restricted sandbox's `/proc` is not evidence that the host worker exited.
The start-time identity check still rejects an actually reused PID.

## Current bounded evidence

The ROOT operational evidence
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/performance_observations_20261024/mrk_cpu_delta.json`
recorded start ticks `70183310`. Across its 86.270-second observation interval, process CPU advanced
88.16 seconds, or 102.19% of one core, while RSS was approximately 0.98 GB. The environment had no
`/proc/<pid>/io` file, so read and write bytes are unavailable rather than zero.

The component-completion file timestamp was 2026-10-22 20:00:49 KST and the later recovery
`keeper_invocation` file timestamp was 2026-10-24 00:26:40 KST, a roughly 28 hour 26 minute dispatch
gap. That wall-clock gap is historical scheduling/dispatch evidence, not computation time. At the
referenced observation checkpoint the reported panels existed and the execution log was empty. A
later bounded filesystem observation found quarter temporary directory
`panels/.panels.partial-e2m2age8`, which supports only that quarter publishing entered an initial
materialization interval. These filesystem facts do not identify the exact function or stage. The
log-derived stage therefore remains `unknown` until a recognized JSON event is observed.

## Limits and interpretation

- `/proc/<pid>/io` may be absent or unreadable. The observer reports `null` counters and the reason.
- The observer must share a readable PID namespace with the target; initial attachment fails when
  the target is invisible, and sandbox invisibility must not be interpreted as host-process exit.
- Unlinked open SQLite or other spill files are invisible because file-descriptor traversal is
  deliberately excluded. Root byte totals can therefore differ from actual open storage use.
- A capped or interrupted root scan is partial and carries `capped` or `scan_error` evidence.
- File growth and filesystem free space can show where bytes accumulate, but they do not establish
  accounting correctness or a precise code stage.
- The reports are resource observations after attachment. They are not History `PASS`, governed
  period readiness, ROOT acceptance, or authorization for a retry, cleanup or future scheduled run.

The chosen structure keeps one direct CLI module because it has one caller-facing operation and no
second production adapter. Its private calculation/read seams make offline edge cases testable
without introducing a framework. A viable alternative is an external system profiler; reconsider it
if stack sampling, open-file visibility or fleet-wide correlation becomes authorized, accepting the
additional privilege, deployment and evidence-governance cost.
