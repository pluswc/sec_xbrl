# History 저장 경로 성능 가설과 제한 구현

상태: **IMPLEMENTED — 자체 검증 완료, 독립 검증 전**
기준 source: `6c1d9de66d8d9b58c8d9bbed9b64571e694f6553`
범위: 실제 SEC 자료를 읽지 않는 합성 source-only 계측과 `_stage_records` 내부 한 개선

## 관측 배경

MRK reported-stage recovery build는 5,966.767초가 걸렸다. 12개 표의
`QUARTER_SPILL_END` elapsed 합은 2,084.895초였고, 첫 표 전 967.39초와 마지막 spill 종료 뒤
2,779.95초는 verification, load, derive, assemble, final checks가 섞인 구간이다. 이 값은
병목 후보를 찾는 운영 관측이며 어느 한 함수의 비용이나 개선 효과를 증명하지 않는다.
실제 MRK History, Raw, cache와 완료 산출물은 이번 작업에서 읽거나 재실행하지 않는다.

## H1 — recovery output 전수 경로 검사

`_RecoveryOutput.check()`는 복구 transaction의 모든 guarded boundary에서 output root를
`rglob`하고 각 entry를 `lstat`한다. 10,332개 파일과 72개 디렉터리 규모에서는 호출 수와
파일 수의 곱으로 metadata 작업이 증가할 수 있다. 동일 디렉터리의
`(dev, ino, mtime_ns, ctime_ns)`를 근거로 변경된 디렉터리만 다시 검사하는 방안이 후보지만,
이는 recovery 전용이고 남은 일반 회사의 guard-unset 실행에는 적용되지 않는다. 또한 sole
writer·ownership·symlink exchange 보호를 완화할 위험이 있다. 이번 작업은 합성 tree의 entry
방문 수와 wall time만 계측하며 H1을 구현하지 않는다.

## H2 — `_stage_records` 준비 순회 결합

현재 `_stage_records`는 reiterable `Sequence`를 세 번 읽는다.

1. table-global `json_fields` 발견
2. bounded local schema 발견과 global super-schema 결정
3. 원본 값을 최종 JSON/native representation으로 encode하고 bounded chunk 작성

가설은 1과 2를 한 순회로 합쳐 full record read/decode를 3회에서 2회로 줄일 수 있다는
것이다. 각 bounded batch에서 nested field를 찾는 동시에 값을 보존하지 않는 local schema
sketch를 만든다. 전체 순회 뒤 확정된 global JSON field가 local schema에 scalar로 나타났던
경우 해당 column만 `String`으로 정규화한 뒤 기존 global super-schema 결정을 사용한다.
최종 encoding, 32-row/8-MiB cap, chunk merge, SHA-256, manifest `json_fields`, row/column order,
IDs, provenance, ownership guard와 failure cleanup은 그대로 유지한다.

Local inference가 `OverflowError` 또는 Polars schema inference 오류로 실패하면 table-global
`json_fields`를 확정한 뒤 기존 schema pass를 실행한다. Fallback은 원래 유효했던 late-JSON
extreme scalar를 조기 실패시키지 않기 위한 것이며, fallback 자체의 오류나 ownership 오류를
숨기지 않는다. 전체 payload 또는 encoded value를 cache하지 않는다.

## 수락 기준과 기대 효과

- 동일 합성 fixture에서 baseline과 candidate의 decoded values, native types, JSON fields,
  schema, order와 count가 동일하다.
- 결정적 Parquet byte hash가 환경에서 동일하면 기록하며, 동일하지 않으면 decoded/schema
  equality를 필수 기준으로 유지한다.
- reiterable on-disk synthetic Sequence에서 baseline 3회와 candidate 2회의 iteration/record
  decode count를 직접 기록한다.
- late JSON, numeric/bool/string/None/empty/sparse, extreme integer fallback, cleanup/integrity를
  focused offline test로 확인한다.
- paired wall time, operation count, max RSS와 기존 32-row cap을 기록한다.

기대 효과는 `_stage_records` 준비 단계의 한 full read/decode 제거다. 합성 계측 결과를 MRK
99분 전체 실행 개선으로 외삽하지 않는다. H2 비용이 미미하면 source를 변경하지 않는다.

대안은 기존 3-pass 구조를 유지하는 것이다. 구현이 단순하고 fallback이 필요 없지만,
on-disk spill Sequence의 반복 DB read/unmarshal 비용을 그대로 지불한다. H1 directory cache는
recovery ownership contract를 재설계하고 별도 독립 보안 검토를 받을 때만 다시 검토한다.

## 계측 및 검증 결과

실자료를 사용하지 않은 4,096행 JSONL disk-backed Sequence의 paired profile 결과는 다음과
같다. 결과는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/performance_engine_writer_20261024/final_profile.json`에
있다.

| 항목 | 기존 3-pass | H2 production 후보 |
| --- | ---: | ---: |
| Sequence iteration | 3 | 2 |
| record decode | 12,288 | 8,192 |
| wall time (비프로파일 1회) | 0.428초 | 0.381초 |
| Parquet bytes | 224,749 | 224,749 |
| SHA-256 | `16087f…e9ca` | `16087f…e9ca` |

같은 프로세스의 전체 peak RSS는 80,940 KiB였다. 이는 두 실행을 포함한 process peak라서
후보 단독 peak 감소를 뜻하지 않는다. Operation count는 정상 schema inference 경로에서 full
read/decode 1회를 제거했음을 직접 보여준다. Wall time은 단일 합성 실행이며 실제 MRK 99분
실행의 절감률로 외삽하지 않는다.

H1 합성 tree는 파일 10,332개와 디렉터리 72개, 총 10,404 entry를 한 scan에서 방문했고
0.028초가 걸렸다. 실제 filesystem과 guard 호출 횟수를 대표하지 않으며 recovery 전용 보호
계약 위험도 있으므로 구현하지 않았다.

H2는 batch-local nested field 발견과 값 없는 schema sketch를 같은 순회에서 만든다. 순회
완료 뒤 table-global JSON column의 local schema를 `String`으로 정규화한다. Local inference가
overflow 또는 Polars 오류를 내면 확정된 global JSON fields로 기존 schema pass를 그대로 다시
실행한다. 따라서 정상 경로는 2-pass이고 compatibility fallback은 3-pass다. 최종 encoding,
32-row/8-MiB cap, chunk merge, hash, storage guard 및 cleanup은 변경하지 않았다.

최종 focused 검사는 source corpus sentinel을 존재하지 않는 경로로 지정하고 reviewed Q4 flag를
unset하며 `POLARS_MAX_THREADS=2`로 실행했다. 신규 performance test와 기존 bounded writer,
schema promotion, empty/all-null, no-serialization inference, row/byte cap, staged lifetime 및 merge
failure cleanup 검사를 합쳐 **13 passed in 0.42s**였다. 첫 실행은 11 passed/2 failed였고,
실패 원인은 sparse Parquet column의 누락값 materialization 기대와 현재 Polars Decimal128 범위에
들어가는 `2**100` 자극값이었다. Fixture 기대를 `None` materialization에 맞추고 실제 overflow인
`2**200`으로 바꾼 뒤 최종 검사가 통과했다. 실제 SEC 자료, 기존 History publication, Raw 또는
cache는 읽거나 재실행하지 않았다.
