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

## Bounded 3-arm 측정

각 case는 fresh serial subprocess에서 R14, R15, R17을 회전 순서로 3회 실행했다. 각 arm은
동일 SQLite pragma와 32 KiB compression threshold로 metadata write, row/column/T1 lookup,
source transform, expected write, consumer compare, `verify_storage()`를 수행했다. 제한은
process당 30초, peak RSS 1 GiB다. R14는 deep-copy+decoded compare, R15는 COW+decoded
compare, R17은 COW+verified-canonical compare다. 이는 bounded fixture workload이며 실제
회사 처리량이 아니다.

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

## 한계와 다음 단계

이 측정은 복사된 immutable fixture에 한정된다. 실제 COP audit, live DB, SEC 원본 또는 완료
기업 검증을 실행하지 않았고 실제 전체 audit 시간 개선을 입증하지 않는다. Source
row/column/T1은 아직 매 cell마다 조회한다. 그 cache는 mutable alias와 corruption masking을
피하기 위해 operation count를 먼저 본 뒤 job-local, byte-bounded, transaction/version
invalidated 형태로 별도 검토한다. 이후 물리 순차 읽기와 병렬 scheduling은 이 정확성 경계를
유지하는 별도 마일스톤이다.
