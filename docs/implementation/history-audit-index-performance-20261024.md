# History 감사 인덱스 저장 성능 실험 (2026-10-24)

## 상태와 범위

- 상태: **Stage A 구현·측정 완료, space-first 효과 리드 수락, 독립 검증 대기**
- 기준 소스: `59c1c7bc13b2ebcee8b8acad7dc128d26d886b8d`
- 대상: 독립 History 감사기가 소유하는 임시 SQLite 인덱스의 저장 방식
- 비대상: History 생산 엔진, 회계 선택·비교 정책, 공개 결과 형식, 실제 MRK
  감사 DB, Raw/History 원본, 기존 감사 결과

이 단계는 저장 후보를 측정하는 단계다. 측정 결과가 수락 기준을 충족한 뒤에만
별도 runtime 후보를 만들기로 했다. 제한 표본의 시간 목표는 충족하지 못했지만,
실제 disk-full 위험과 직접 관련된 공간 감소를 리드가 별도 수락해 R13 source-only
통합 후보 생성을 승인했다. 실제 감사 실행과 GO는 이 문서의 범위가 아니다.

## 변경 전 가설과 수락 기준

### H1: payload 본문 1회 저장과 candidate 참조

기존 인덱스는 `objects`, `expected`, `candidates` 각각에 canonical JSON 본문을
저장한다. candidate wrapper는 이미 저장한 cell, column, source row를 다시
직렬화한다. 불변 canonical payload를 SHA-256 ID로 한 번 저장하고 세 테이블이
그 ID를 참조하면, 같은 논리 레코드의 중복 바이트와 candidate 재직렬화를 줄일
수 있다고 예상했다.

### H2: 큰 canonical body의 선택 압축

초기에는 4 KiB 이상 scalar 문자열 interning을 검토했다. 첫 24건 승인 표본에는
해당 문자열이 없었고 큰 cell은 candidate가 아닐 수 있어, 이 방식은 실제 관측
병목을 설명하지 못했다. 이후 승인된 7.8 MiB rich cell은 `candidate_lineage` 안에
570개 navigation 항목이 있지만 `value_text`는 비어 있었다. 따라서 per-leaf SQL
DAG를 만들지 않고, 32 KiB 이상 canonical JSON body 전체만 zlib level 1로 저장하는
H2 compact arm으로 좁혔다.

초기 수락 목표는 풍부한 payload 사례에서 baseline보다 DB+sidecar 공간을 30%
이상 줄이고 insert+read 시간을 10% 이상 줄이며 RSS를 제한하는 것이었다. 모든
arm은 레코드 수와 순서가 같은 canonical 출력 SHA를 가져야 한다.

## 저장 계약

`tools/history_audit_index.py`는 감사 전용 deep utility다.

- 새 DB만 `history-audit-index-v2`로 만들며 구형·다른 버전을 자동 이행하지 않는다.
- `objects`와 `expected`는 immutable payload ID를 저장한다. `candidates`는
  cell/column/source-row payload ID 세 개를 저장하고 읽을 때 기존 wrapper를 복원한다.
- `put()`과 `emit()`은 해당 인덱스에 귀속된 `PayloadRef`를 반환한다. 다른 DB의
  ref와 존재하지 않는 ref는 거부한다.
- 같은 본문은 하나의 payload row를 공유하지만 서로 다른 bucket/key/ordinal 행은
  합치지 않는다. `first=True`, upsert 시 기존 ordinal, expected/candidate 중복과
  순서를 유지한다.
- payload ID는 압축 전 canonical 바이트의 SHA-256이다. hash hit는 strict
  decompression한 원본 바이트와 대조한다. 읽을 때 원본 길이, zlib stream 종료·잔여
  데이터와 SHA를 검사한다. dangling ref, 손상된 압축, schema 및 format 불일치는
  닫힌 실패다.
- 입력은 기존 `json.dumps(..., sort_keys=True, ensure_ascii=False,
  separators=(",", ":"), allow_nan=False)` 왕복 의미를 유지한다. 큰 정수, bool,
  null, Unicode, float와 `-0.0`을 같은 canonical JSON 값으로 복원한다. NaN은 계속
  거부한다.
- 기본값은 H1(refs-only)이다. H2 compact는 측정용 명시 옵션이며 runtime
  기본값으로 채택하지 않았다.

이 utility는 저장과 무결성만 담당한다. source/derive/consumer/finish의 회계 규칙,
선택 범위와 공개 결과를 정의하지 않는다.

## 측정 방법

Python은 프로젝트 `.venv`의 Python 3.12를 `-B`와
`PYTHONDONTWRITEBYTECODE=1`로 실행했고, subprocess마다 SQLite pragma를 같게
설정했다. arm 순서를 회전해 각 사례를 3회 직렬 실행했다. 각 subprocess의 제한은
30초이며 RLIMIT_AS는 사용하지 않았다. 보고값은 세 번의 중앙값이다.

세 arm은 다음과 같다.

1. `baseline`: 동결 R12와 같은 본문 중복 테이블
2. `refs`: H1, canonical JSON payload와 candidate 세 ref
3. `compact`: H1 + 32 KiB 이상 canonical body의 zlib level 1 저장

합성 사례는 small financial 2,000건과 logical write 117,914,560 B인 긴 반복 문자열
512건, 레코드마다 고유하지만 cell 내부에서 반복되는 긴 문자열 512건이다. 승인된
고정 표본 두 개는 원본 record를 한 번씩만 사용했다.

```text
work/universe50_quarterly_20261010/resumption_20261017_t3v2/
  audit_index_cached_sample_20261024/transactions.jsonl
SHA-256 0afec342e3a7d17246623ade353854c166969a57b744f57936a0fbe00dbf73ea
크기 895,765 B, 원본 24건, eligible 12건

work/universe50_quarterly_20261010/resumption_20261017_t3v2/
  audit_index_rich_sample_20261024/transactions.jsonl
SHA-256 eb87a0810910e0194db98498fc8749d7bfabf1292a8226a0392d449a2d29a1f6
크기 7,838,575 B, 원본 1건, eligible 0건, candidate_lineage 570건
```

24건 prefix 표본 수집에서는 3 MiB를 넘은 36개 cell이 제외됐다. rich 표본은 그중
가장 큰 cell 하나를 별도 제한 수집한 것이다. 두 표본은 전체 MRK 분포가 아니며
전체 감사 시간이나 최종 DB 크기를 대표하지 않는다.

## 결과

모든 비교에서 arm별 ordered canonical output SHA와 objects/expected/candidates
count가 일치했다. 합성/prefix peak RSS는 약 25~28 MiB였고 rich 1건은
baseline 98.0 MiB, refs 90.6 MiB, compact 80.5 MiB였다.

| 사례 | arm | insert+read 중앙값 (s) | 전체 중앙값 (s) | DB+sidecar (MiB) | baseline 대비 공간 | baseline 대비 insert+read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| prefix 표본 24건 | baseline | 0.0193 | 0.0339 | 1.070 | - | - |
| prefix 표본 24건 | refs | 0.0201 | 0.0462 | 0.918 | -14.2% | +4.0% |
| prefix 표본 24건 | compact | 0.0214 | 0.0467 | 0.434 | -59.5% | +10.9% |
| rich 표본 1건 | baseline | 0.1245 | 0.1404 | 7.523 | - | - |
| rich 표본 1건 | refs | 0.1280 | 0.1841 | 7.543 | +0.3% | +2.8% |
| rich 표본 1건 | compact | 0.1379 | 0.1939 | 0.570 | -92.4% | +10.8% |
| 긴 반복 문자열 | baseline | 1.1584 | 1.1730 | 112.801 | - | - |
| 긴 반복 문자열 | refs | 1.0434 | 1.1750 | 65.047 | -42.3% | -9.9% |
| 긴 반복 문자열 | compact | 1.0204 | 1.1444 | 1.215 | -98.9% | -11.9% |
| 고유·내부반복 긴 문자열 | baseline | 0.7053 | 0.7201 | 112.801 | - | - |
| 고유·내부반복 긴 문자열 | refs | 0.6109 | 0.7335 | 65.047 | -42.3% | -13.4% |
| 고유·내부반복 긴 문자열 | compact | 0.7199 | 0.8400 | 1.215 | -98.9% | +2.1% |
| small financial | baseline | 0.1467 | 0.1640 | 3.738 | - | - |
| small financial | refs | 0.2413 | 0.3034 | 4.590 | +22.8% | +64.5% |
| small financial | compact | 0.2469 | 0.3164 | 4.590 | +22.8% | +68.3% |

`전체`에는 candidate 저장소의 SHA/참조 무결성 전수 검사가 포함된다. rich compact의
`verify_seconds` 중앙값은 약 0.0349초이고 prefix compact는 약 0.0036초다. baseline은
content-addressed hash 검사가 없으므로 이 비용은 거의 0이다. insert+read만 비교해도
실제 표본 후보는 빨라지지 않았다. compact는 rich 표본의 공간을 92.4% 줄였지만
insert+read는 10.8% 느려졌다. 공간 부족 회피에는 유의미한 후보이나, 현재 계약의 시간과
공간 동시 수락 기준은 충족하지 않았다.

측정 JSON:

- 합성: `work/.../audit_payload_storage_writer_20261024/synthetic_profile.json`
  (`35b563dcfe8606ac4597c8e7409e5daea441a916ac19b80d319c36919fc851d0`)
- prefix 표본: `work/.../audit_payload_storage_writer_20261024/cached_sample_profile.json`
  (`af3a3ff1c7161333b389a5607b9f6e3a6ab412374589d36882dfc176142936c9`)
- rich 표본: `work/.../audit_payload_storage_writer_20261024/rich_sample_profile.json`
  (`145d96ed116810508aa568a8f4cca7bfc1c70015f221b053c4238a33f81329bc`)

## 결정과 한계

H1/H2 모두 시간·공간 동시 수락 기준을 충족하지 않았다. 리드는 반복된 실제
disk-full 위험을 근거로 rich 표본의 공간·RSS 효과와 CPU 비용을 함께 수락했다.
따라서 source-only R13 통합 후보는 만들 수 있지만 실제 MRK 전체 감사가 빨라진다고
주장할 수 없다. active R12, 실제 audit SQLite, 기존 결과와 원본은 읽거나 수정하지
않았다.

`verify_storage()`는 새 content-addressed format의 payload hash, 압축 원본 길이,
dangling ref와 SQLite integrity를 final seal 전에 전수 확인한다. semantic consumer가
읽지 않는 bucket/payload도 있을 수 있어 필요한 저장 무결성 검사이며 회계 계산을
다시 수행하지 않는다. 비용은 profile에서 별도 stage로 기록해 숨기지 않는다.

rich 1건은 압축의 공간 효과를 보여 주지만 전체 분포와 SQLite 총량을 외삽할 수 없다.
다음 단계가 필요하면 리드가 공간 절감과 시간 증가의 tradeoff를 별도 수락하거나,
대표성이 더 넓은 제한 fixture로 전체 write/read 비중을 다시 측정해야 한다. 그 근거
없이 per-leaf DAG, 공개 schema 변경 또는 회계 경계 변경을 진행하지 않는다.

## 재현 명령

```bash
PYTHONDONTWRITEBYTECODE=1 POLARS_MAX_THREADS=2 \
  /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -B \
  tools/profile_history_audit_index.py --rotations 3 --output /tmp/synthetic.json

PYTHONDONTWRITEBYTECODE=1 POLARS_MAX_THREADS=2 \
  /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -B \
  tools/profile_history_audit_index.py --rotations 3 \
  --fixture /absolute/path/to/authorized/transactions.jsonl \
  --fixture-cycles 1 --output /tmp/cached-sample.json
```

fixture CLI는 지정한 단일 JSONL만 읽고 16 MiB를 넘으면 거부한다. 원본 표본 건수와
exercise 건수를 분리해 출력한다.

## focused 검증

```text
PYTHONDONTWRITEBYTECODE=1 .../.venv/bin/python -B -m pytest -q \
  -p no:cacheprovider tests/unit/test_history_audit_index.py
10 passed in 0.36s

PYTHONDONTWRITEBYTECODE=1 .../.venv/bin/python -B -m ruff check --no-cache \
  tools/history_audit_index.py tools/profile_history_audit_index.py \
  tests/unit/test_history_audit_index.py
All checks passed!
```

## Stage B: 분기 생성 private spill의 공간 절감

Stage A 후보 `4bc5f67c6946a3525f49292fd196fcfabb981c46`은 독립 검증
`8450b147e8321da966988041bdca4661974afc04e88bdfd977c6ed559647940d`에서
PASS했고, 리드가
`5445620925fb319bafa6067f810b3431999c6fc2fa74fc55ab65331625f621f2`로
로컬 수락했다. Stage B는 같은 공간 절감 원리를 History 분기 생성의 private
SQLite spill에만 적용한다. 공개 History 결과, 회계 계산, candidate locator,
보호 journal과 감사 runtime binding은 대상이 아니다.

관측된 문제는 `_QuarterSpill`이 동일한 typed value를 anonymous SQLite BLOB과
이름 있는 보호 journal에 모두 기록한다는 점이다. 선택한 설계는 기존
`_spill_pack()` 결과가 32 KiB 이상이고 zlib level 1 결과가 더 짧을 때에만 private
DB BLOB을 압축하는 작은 versioned envelope다. envelope는 raw/compressed 구분,
압축 전 길이와 SHA-256을 가진다. 읽기는 1 GiB 상한 안에서 stream 종료, 잔여 입력,
원본 길이와 hash를 확인하고 기존 typed bytes를 반환한다. 작은 값이나 압축 이득이
없는 값은 raw envelope로 둔다.

기존 `_spill_pack()`/`_spill_unpack()`, `_append_event()`, PLANNED/APPLIED 순서,
원본 key와 ordinal, 소유권·경로·FD 검사 및 journal framing은 바꾸지 않았다. DB
row factory가 `value` 열만 기존 typed bytes로 복원하므로 mapping/sequence의
getitem, items, values, slice와 음수 index 인터페이스도 그대로다. 구형 DB를 여는
경로와 이행은 추가하지 않았다. 대안인 journal 압축은 forensic 형식을 바꾸므로
채택하지 않았고, 값 dedup이나 per-leaf SQL DAG도 순서와 실패 면적을 넓히므로
추가하지 않았다.

### Stage B 측정

기준은 `59c1c7bc13b2ebcee8b8acad7dc128d26d886b8d`이고 candidate는 Stage A
커밋 위 작업본이다. 각 arm을 별도 subprocess로 3회 교차 순서 실행했다. 각 실행은
30초 timeout, 1 GiB RSS watchdog, SQLite 설정과 read pass 2회를 동일하게 사용했다.
RLIMIT_AS는 사용하지 않았다. 표의 시간과 RSS는 3회 중앙값이다. 모든 비교에서
ordered typed semantic SHA, record count, journal event count, decoded typed journal
SHA와 raw framed journal SHA가 arm 사이에 일치했다.
anonymous DB 수치는 `PRAGMA page_count * page_size`인 논리 SQLite page bytes이며,
OS의 실제 할당량이나 `du` 수치가 아니다. journal은 이름 있는 파일의 실제 byte다.

| 사례 | DB baseline→candidate | journal | 합산 공간 변화 | 전체 시간 변화 | peak RSS 변화 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 승인 prefix 24건, 613,936 B typed | 684,032→364,544 B | 630,172 B 동일 | -24.31% | +18.57% | +0.08% |
| 승인 rich 1건, 5,025,774 B typed | 5,050,368→311,296 B | 5,026,899 B 동일 | -47.03% | +20.55% | -8.88% |
| 합성 repeated-rich, 49,257,032 B typed | 50,413,568→4,276,224 B | 49,593,884 B 동일 | -46.13% | +38.40% | +0.43% |
| 합성 small typed, 32,107,985 B typed | 34,062,336 B 동일 | 35,127,205 B 동일 | 0.00% | +2.92% | -0.16% |

승인 fixture는 각각 원본 24건과 1건을 한 cycle만 사용했다. rich 사례의 anonymous
DB는 93.84% 줄었지만 journal을 그대로 보존하므로 합산 절감은 47.03%다. 이 결과는
private DB 중복으로 인한 공간 압력을 줄이는 근거이며, 생성 속도 개선 근거는 아니다.
압축 대상의 write/read CPU 비용 때문에 실제 rich 표본 전체 시간은 20.55%, 합성
repeated-rich는 38.40% 늘었다. 작은 값은 page 단위 공간 변화가 없고 시간은 2.92%
늘었다. 한정 표본을 전체 기업이나 MRK 실행 시간·최종 크기로 외삽하지 않는다.

측정 JSON은 다음과 같다.

- `work/.../quarter_spill_storage_writer_20261024/synthetic_profile.json`
  (`8117775eceb5b84704cef364ea4f9ccce9aa6c350d61a72c00375f6115d6ada6`)
- `work/.../quarter_spill_storage_writer_20261024/prefix24_profile.json`
  (`4d28b839c73f60be786a96101718f68ffb21741fa3f5add5f014f9e33cbab351`)
- `work/.../quarter_spill_storage_writer_20261024/rich1_profile.json`
  (`530de099e272b9f601396a16a2ab59b1ee6f4aabe6f2d13a53ae0933dec69b3b`)

프로파일 도구는 명시한 JSONL 하나만 읽고 16 MiB를 넘으면 거부한다. 원본 fixture
건수, cycle과 실제 exercise 건수를 분리해 기록한다. 실제 producer, SEC 원본,
active MRK SQLite 또는 완료 결과는 읽거나 실행하지 않았다. 이 단계는 source-only
후보이며 새 GO, runtime binding과 실제 작업 실행은 별도 수락 대상이다.

focused 검증은 codec 손상·상한, 모든 기존 typed 값, mapping/sequence 경로,
journal 바이트 동일성, 비압축 6 MiB 값의 실제 anonymous disk spill, 기존 분기 spill
동작과 메모리 성능 계약을 포함했다. 기존 대형 반복 fixture의 anonymous DB가 반드시
20 MiB를 넘는다는 물리 크기 기대는 공간 개선과 충돌하므로, 전체 typed journal
20 MiB 보존과 공개 결과·streaming 검사는 유지하면서 DB page bytes가 5 MiB 미만임을
검사하도록 바꿨다.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<candidate>/src .../.venv/bin/python -B \
  -m pytest -q -p no:cacheprovider \
  tests/unit/test_history_quarter_spill_codec.py \
  tests/unit/test_history_quarter_spill.py \
  tests/unit/test_history_quarter_spill_performance.py
38 passed in 1.30s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<candidate>/src .../.venv/bin/python -B \
  -m ruff check --no-cache src/sec_xbrl/analytics/history_quarters.py \
  tests/unit/test_history_quarter_spill_codec.py \
  tests/unit/test_history_quarter_spill.py tools/profile_quarter_spill_storage.py
All checks passed!
```
