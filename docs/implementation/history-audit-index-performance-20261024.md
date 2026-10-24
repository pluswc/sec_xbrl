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
