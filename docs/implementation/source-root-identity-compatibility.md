# Cohort source-root identity compatibility

## Status

This change is implemented on the dedicated source-root-identity branch and
awaits independent verification and local acceptance. It does not authorize an
actual History build.

## Compatibility rule

`CohortReleaseAdapter` identifies an intake source by its resolved physical
directory. Distinct source directories may have the same leaf name, such as
`intake`, because their absolute roots still preserve separate provenance.
Passing the same physical directory more than once, including through a
relative `.` or `..` alias, is rejected.

The existing source contract remains in force: each declared `run_id` must
equal its source directory name, the top-level source cannot be a symlink, and
the directory must exist. Relative source paths remain supported. Snapshot
CIK/accession uniqueness, manifest and table integrity, reference validation,
deterministic ordering, and the Layer 2 fingerprint are unchanged.

This is a provenance adapter compatibility correction. It does not rewrite an
intake, copy or merge Raw data, change period or selection rules, or alter any
accounting meaning.
