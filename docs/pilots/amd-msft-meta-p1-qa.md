# AMD · MSFT · META P1 QA matrix

Run timestamp: **2026-08-24T02:28:04.338627Z**. The six packages were fetched
to the ignored caller-owned cache `data/cache/pilots/amd-msft-meta`, validated
against their immutable package/index manifests, then loaded by Arelle with its
web cache offline. Layer 1 tables were extracted in memory only; no Parquet or
other generated analytical store was written.

| Accession | Package / Arelle | Selected entry point | Facts / contexts / dimensions | PRE / CAL / DEF | Package-manifest SHA-256 |
| --- | --- | --- | ---: | ---: | --- |
| 0000002488-26-000018 | PASS / PASS | `amd-20251227.htm` | 60 / 22 / 21 | 821 / 129 / 633 | `4e3847af7935752584251f50d0e0a73834c359a299c7ae64535db246161069d8` |
| 0000002488-26-000076 | PASS / PASS | `amd-20260328.htm` | 20 / 8 / 5 | 444 / 0 / 335 | `a77a294514778fd7d0e6b7f903fd705065041d863be446c60923b82f7ae0d17b` |
| 0000950170-25-100235 | PASS / PASS | `msft-20250630.htm` | 138 / 60 / 85 | 776 / 0 / 612 | `2fcf648791ee25e6d54e47b88ee8e3cdb200eb3d77f7d6b1cc32a058bc98f0a9` |
| 0001193125-26-191507 | PASS / PASS | `msft-20260331.htm` | 105 / 49 / 67 | 548 / 0 / 446 | `aa19ba8f80cd9c9e0a18cd486b089a9fe0f4023ecda71219a73e841ea0825080` |
| 0001628280-26-003942 | PASS / PASS | `meta-20251231.htm` | 76 / 31 / 28 | 635 / 135 / 388 | `d631be8d6eb6e33a634bec385c3d38135d8ab97a20aec7d82b6c9a23703364cf` |
| 0001628280-26-028526 | PASS / PASS | `meta-20260331.htm` | 52 / 28 / 29 | 387 / 0 / 279 | `b2b077c8186e3aa66732943e68f789bac63c4afc8fac48f30d905905b430c604` |

The `0` CAL values are as-filed relationship-presence results, not inferred
failures. They remain explicit review signals for later M3/M4 evidence work.
The P1 entry-point adapter takes the unique document whose SEC index-header
`TYPE` equals the requested form; it rejects absence or ambiguity and never
guesses from a filename.

The runner requires an identifying SEC User-Agent and explicit ignored cache
and report paths. It records failures as their contract stage and exact
exception text in the local JSON matrix; neither the raw files nor that
generated matrix are committed.

```text
uv run python -m sec_xbrl.pilots.amd_msft_meta_p1 \
  --manifest docs/pilots/amd-msft-meta-filing-manifest.json \
  --cache-root data/cache/pilots/amd-msft-meta \
  --report data/cache/pilots/amd-msft-meta/p1-qa.json \
  --user-agent "Organization contact@example.com"
```
