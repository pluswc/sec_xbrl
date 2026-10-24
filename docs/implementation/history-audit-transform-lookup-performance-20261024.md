# History audit 반복 변환 제거 (2026-10-24)

## 목표와 범위

이 마일스톤은 독립 History audit의 의미를 바꾸지 않고 consumer 검증에서 반복하던
expected JSON decode와 canonical JSON 재생성을 줄인다. 현재 실행 중인 R14와 그 SQLite는
읽거나 수정하지 않았다. 기존 R15의 copy-on-write source transform과 shared typed hash를
그대로 재사용한다. 물리 순차 읽기와 병렬 scheduling, source row/column/T1 cache는 다음
단계다.

저장 형식, payload ID, DB schema, candidate multiplicity, accounting 정책, FileStream의
physical/raw 및 decoded hash, count/schema 검증, `verify_storage()`는 그대로다.

## 구현

`AuditIndex.expected_canonical()`과 `item_canonical_values()`는 expected 또는 object row와
payload를 한 번의 ordered `LEFT JOIN`으로 읽는다. 각 payload는 기존과 같은 encoding,
압축 경계, 원래 byte length와 SHA-256을 검증한다. `LEFT JOIN`이므로 dangling reference가
inner join에서 사라지지 않고 명시적으로 실패한다. ordinal과 multiplicity를 그대로
보존하며 N+1 payload lookup을 만들지 않는다.

Consumer는 actual record를 한 번만 `canonical_text()`로 만든다. 검증된 expected bytes와
정확히 같으면 expected JSON decode와 재인코딩을 생략한다. 이 fast path의 actual bytes는
strict canonical encoder가 방금 만든 유효 JSON이고 expected bytes는 길이·encoding·hash가
검증됐으므로, byte equality일 때 별도의 expected parse가 결과를 더 검증하지 않는다.

Bytes가 다르면 expected를 기존 finite-float/UTF-8/JSON 규칙으로 strict decode하고,
`{actual keys: null} + expected` top-level schema-union padding을 적용한 뒤 이미 만든 actual
canonical text와 비교한다. 따라서 missing-vs-null은 이전처럼 통과하고 nested 값, record
순서 또는 multiplicity 차이는 실패한다. 기존 `equal_record()`의 공개 동작은 유지했다.
Columns는 boundary metadata에서 다시 만드는 `rebuilt_columns()` 경로를 그대로 사용한다.

R17은 accepted R15 standard runtime의 19개 Python script와 dependency metadata를 복사해
만들었다. `audit_index.py`, `checker.py`, `phase_engine.py`만 위 동작을 추가했다.
`typed_hash.py`와 나머지 runtime logic은 R15와 byte-identical이다. `audit_gate.py`는 COP가
실제로 생성된 engine `2b5dde23c50b6ac0b83459df42777f38f312da0b`에 맞춰 승인된 세
상수(`ENGINE_SHA`, `ENGINE_ACCEPTANCE`, `ENGINE_HASHES`)만 바꿨다. Gate logic과
`build_spec.py`는 바꾸지 않았다. 실제 GO, dispatch, keeper 또는 audit는 만들거나 실행하지
않았다.

이 구현의 production source 커밋은
`b8c1c8664f41994accd835b7a5fcbee708a59fe0`이다. 2026-10-24 독립 검증은
이 source와 R17의 19-script frozen map에 PASS했고, ROOT는 같은 날 source와 bounded
kernel 비교를 로컬 수락했다. 이 상태는 main merge나 실제 배포를 뜻하지 않는다.

## 정확성 검증

Focused 검증은 다음 경계를 포함한다.

- exact match는 expected decode 0회, actual canonical encode 1회다.
- top-level missing-vs-null은 strict fallback으로 통과한다.
- nested 값, record order, multiplicity, large integer, bool, null, `-0.0`, Unicode와 non-finite
  입력은 기존 pass/fail을 유지한다.
- plain/zlib payload mutation, truncate/length/hash 오류, dangling/foreign ref, deleted ref,
  collision과 rollback은 fail closed 또는 원복 후 정상 동작을 유지한다.
- `get()`/`items()`는 호출마다 fresh decoded object를 돌려주는 기존 동작을 유지한다.
- COP gate는 head, acceptance pin 또는 `history_quarters` hash가 하나라도 다르면 실제
  production predicate가 false가 된다. R15 gate와의 AST 차이는 승인된 세 상수뿐이다.

첫 focused 실행은 테스트 코드의 지역 변수 누락 1건 때문에 17 PASS/1 FAIL이었고, 그
테스트만 수정해 1 PASS로 재실행했다. 제품 동작 실패는 없었다. 기존 완료 기업 audit와
기존 broad suite는 반복하지 않았다.

별도 독립 검증은 8개 boundary case와 production `phase_engine.consumer_file()`을 직접
호출하는 synthetic integration 1개를 통과했다. Integration은 rows/cells/derived의 exact와
null-padding 성공, columns 재구성, missing/reorder/value/corruption 거부를 확인했다. 최초
integration fixture에 `audit_counts` table이 빠져 생긴 실패는 reviewer-owned fixture만
고친 뒤 해당 검사만 재실행해 PASS했으며 제품 결함은 아니었다. 이전 마일스톤에서 수락한
R15 COW와 shared typed-hash 증거는 그대로 이어받았고 그 코드는 바꾸지 않았다. 독립 보고서
SHA-256은 `43d44a5045ec167ac02b6925777c2870634b52e8308d36b9a1aa3f80a8c97f8f`다.

## Bounded 3-arm 측정

이 수치는 **emulated bounded kernel** 비교다. 각 case는 fresh serial subprocess에서 R14,
R15, R17 알고리즘 모드를 회전 순서로 3회 실행했다. 세 모드는 모두 새 candidate
`AuditIndex`를 사용하고, profiler 안의 지역 `_cow_cell`과 inline comparison으로 각각
deep-copy/decoded compare, COW/decoded compare, COW/verified-canonical compare를 재현한다.
동일 SQLite pragma와 32 KiB compression threshold로 metadata write, row/column/T1 lookup,
source transform, expected write, consumer compare, `verify_storage()`, commit과 close를
수행한다. 제한은 process당 30초, peak RSS 1 GiB다.

Timer는 import, fixture load와 입력 fingerprint 생성을 제외한다. Peak RSS는 process 시작을
포함한 fresh-process 최대값이다. 이 harness는 실제 `FileStream`의 physical/raw 및 decoded
hash, 전체 `source_file()`과 `consumer_file()`, 전체 runtime 또는 회사 audit 시간을
측정하지 않는다. 따라서 아래 차이를 whole-audit 또는 runtime 속도 개선으로 부르지 않는다.

| 입력/case | records | R14 total | R15 total | R17 total | R14→R17 | R15→R17 |
|---|---:|---:|---:|---:|---:|---:|
| rich 1 × 4, exact | 4 | 0.8354s | 0.5983s | 0.3902s | -53.3% | -34.8% |
| prefix 24 × 32, exact | 768 | 0.6849s | 0.5202s | 0.3631s | -47.0% | -30.2% |
| prefix 24 × 32, null-padding fallback | 768 | 0.7020s | 0.5314s | 0.5221s | -25.6% | -1.7% |

Exact consumer phase는 rich에서 R15 대비 -57.7%, prefix에서 -58.0%였다. Exact R17은
expected decode/re-encode가 0회였고, null-padding case는 768개 모두 strict decode와
재인코딩을 수행했다. Null-padding consumer phase도 R15 대비 -2.9%였으므로 actual text를
두 번 만들지 않는 fallback이 regression을 만들지 않았다. `object_payload_selects`라는
profile field는 trace된 전체 SQL SELECT 수를 세는 초기 이름이며, exact prefix에서
8,608→7,840으로 줄었다.

Median RSS는 rich에서 R15 대비 -10.8%였지만 prefix exact는 +1.8%, null-padding은 +4.1%였다.
작은 prefix의 RSS 차이는 개선으로 해석하지 않는다. DB와 sidecar bytes, ordered semantic
fingerprint와 storage payload count는 모든 arm/rotation에서 같았다.

입력 pin은 다음과 같다.

- `audit_index_cached_sample_20261024/transactions.jsonl`:
  `0afec342e3a7d17246623ade353854c166969a57b744f57936a0fbe00dbf73ea`, 24 records.
- `audit_index_rich_sample_20261024/transactions.jsonl`:
  `eb87a0810910e0194db98498fc8749d7bfabf1292a8226a0392d449a2d29a1f6`, 1 record,
  570 candidates.

프로젝트 Python 3.12 환경에서 다음 명령으로 기존 측정을 재현할 수 있다. `WORK_ROOT`는
fixture와 결과를 둔 `resumption_20261017_t3v2` 절대 경로다. 별도 orchestration 도구는
필요하지 않다.

```bash
PYTHONDONTWRITEBYTECODE=1 /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -B \
  tools/profile_history_audit_transform_lookup.py compare \
  --fixture "$WORK_ROOT/audit_index_rich_sample_20261024/transactions.jsonl" \
  --cycles 4 --rotations 3 --case exact \
  --output "$WORK_ROOT/audit_transform_lookup_writer_20261024/paired_rich_exact.json"

PYTHONDONTWRITEBYTECODE=1 /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -B \
  tools/profile_history_audit_transform_lookup.py compare \
  --fixture "$WORK_ROOT/audit_index_cached_sample_20261024/transactions.jsonl" \
  --cycles 32 --rotations 3 --case exact \
  --output "$WORK_ROOT/audit_transform_lookup_writer_20261024/paired_cached_exact.json"

PYTHONDONTWRITEBYTECODE=1 /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -B \
  tools/profile_history_audit_transform_lookup.py compare \
  --fixture "$WORK_ROOT/audit_index_cached_sample_20261024/transactions.jsonl" \
  --cycles 32 --rotations 3 --case null-padding \
  --output "$WORK_ROOT/audit_transform_lookup_writer_20261024/paired_cached_null_padding.json"
```

## 한계와 다음 단계

이 측정은 복사된 immutable fixture에 한정된다. 실제 COP audit, live DB, SEC 원본 또는 완료
기업 검증을 실행하지 않았고 실제 전체 audit 시간 개선을 입증하지 않는다. Source
row/column/T1은 아직 매 cell마다 조회한다. 그 cache는 mutable alias와 corruption masking을
피하기 위해 operation count를 먼저 본 뒤 job-local, byte-bounded, transaction/version
invalidated 형태로 별도 검토한다. 다음 승인 방향은 물리 순차 읽기, 그 다음 메모리 예산을
지키는 병렬 scheduling이며 둘 다 아직 구현하지 않았다.

2026-10-24 인계 시점에 ABT의 기존 감사 47건은 수락됐으며 재실행하지 않았다. 남은 실제
대상은 COP, DUK, LIN이다. R17은 COP의 engine `2b5dde23c50b6ac0b83459df42777f38f312da0b`에
정확히 묶인 후보지만, static binding review와 별도 actual GO가 남아 있어 실제 COP audit는
시작하지 않았다. 실제 채택·dispatch와 완료 판정은 이 source 수락과 별도 운영 단계다.
