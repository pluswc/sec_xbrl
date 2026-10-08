# 로컬 기업 스크리닝 대시보드 이용 가이드

## 경계와 준비물

이 대시보드는 준비된 annual `AnalysisClient` bundle을 screening 전용 immutable
publication으로 한 번 발행한 뒤 읽는다. 일반 화면 query와 실행은 screening
publication만 읽는다. service 시작과 `status`의 integrity 단계는 선언된
completion/metadata/analysis parent의 manifest, prepared file hash와 U5 snapshot을
read-only로 다시 대조한다. 이 단계도 SEC 문서나 Raw XML을 읽지 않고 Arelle,
filing selection, recast 또는 metric 계산을 실행하지 않는다. 재무값·period·
mapping·quality와 trace는 upstream publication의 값을 그대로 보존한다.

v1에서 실행 가능한 지표는 실제 prepared coverage가 있는 직접 보고 annual
`revenue`, `cfo`, `operating_income`, `net_income`이다. `revenue_growth`와
`operating_margin`은 기존 metric policy의 `ACTUAL_PERIOD_REQUIRED` 때문에
비활성 상태와 사유만 보인다. 임계값은 사용자가 입력한 조건이며 제품의 투자
추천이나 매수 기준이 아니다.

필요한 입력은 다음과 같다.

- overall `READY` 회사-universe completion publication
- completion과 같은 CIK를 가진 회사 metadata publication
- completion의 각 governed history manifest hash에 묶인 회사별 `ANNUAL`
  analysis bundle
- 전체 company membership을 정확히 선언한 prepare config

config 형태는
[`prepare_config.example.json`](../../examples/screening/prepare_config.example.json)을
참고한다. 예시는 구조 설명용 한 회사만 적었으며 실제 config는 completion의
전체 CIK를 중복 없이 정확히 선언해야 한다. 모든 경로는 실행 환경의 절대
경로로 바꾼다.

## publication 준비와 확인

main 프로젝트의 Python 환경을 사용하되 현재 checkout의 `src`를 먼저 import한다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m sec_xbrl.screening prepare \
  --config /absolute/run/prepare_config.json \
  --destination /absolute/run/screening_dataset_v1

PYTHONPATH="$PWD/src" .venv/bin/python -m sec_xbrl.screening status \
  --dataset /absolute/run/screening_dataset_v1
```

목적지는 새 경로여야 한다. publisher는 completion/metadata/analysis manifest,
모든 analysis data file, history binding과 21개의 U5 snapshot을 검증하고 새
목적지에 원자적으로 발행한다. 기존 publication을 고치거나 덮어쓰지 않는다.
`status`는 SEC/parser/metric 계산 없이 자체 manifest/file hash/count/unique grain,
prepared parent의 exact file set/hash, source snapshot의 cell/context/trace identity를
다시 확인한다. source anchor가 없거나 바뀐 `ACTUAL_PREPARED` publication은
자체 JSON을 일관되게 다시 hash했더라도 거부한다.

출력은 다음과 같다.

- `screening_dataset_manifest.json`: publication, 입력과 모든 파일 digest
- `companies.json`: financial prepared target CIK
- `metadata_inventory.json`: 준비되지 않은 `UNKNOWN_SIC` 후보를 포함한 metadata
- `metric_support.json`: 회사별 지원·불가 지표와 reason
- `metric_observations.json`: 실제 연간 값·blank·기간·quality·lineage
- `source_snapshots/<CIK>/<snapshot-id>.json`: 원본 U5 canonical snapshot

`context_end_date`는 upstream Arelle/XBRL duration context의 **exclusive end**를
그대로 보존한다. 화면도 이 규칙을 표시하며 실제 소스 값을 임의로 하루
변환하지 않는다. upstream admin quality overlay가 없으면
`quality_status: null`을 `NOT_DECLARED`로 보여주며 `CLEAR`를 만들지 않는다.

## service 시작

발행본을 catalog에 등록한다. 형태는
[`catalog.example.json`](../../examples/screening/catalog.example.json)과 같다.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m sec_xbrl.screening serve \
  --catalog /absolute/run/catalog.json \
  --store /absolute/run/user_journal.sqlite \
  --exports /absolute/run/exports \
  --host 127.0.0.1 --port 8765
```

브라우저에서 `http://127.0.0.1:8765/`를 연다. service는 loopback 주소만
허용하고 state-changing browser request의 `Origin`이 같은 local service인지
검사한다. 인터넷 연결, 로그인, cloud sync는 없다. journal과 export 경로는
symlink를 통과하지 않는 로컬 경로를 사용한다.

주요 HTTP 경계는 다음과 같다.

| 동작 | endpoint |
| --- | --- |
| service/dataset 상태 | `GET /api/status` |
| 지표 지원·시계열 | `GET /api/availability`, `GET /api/series` |
| metadata/SIC peer | `GET /api/metadata`, `GET /api/peers` |
| 조건 저장·revision | `GET/POST /api/screens`, `POST /api/screens/{id}/revisions` |
| 실행·재열기·trace | `GET/POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/trace` |
| 실행 비교 | `GET /api/run-comparison` |
| 판단 journal | `GET/POST /api/decisions` |
| full/selected export | `POST /api/runs/{id}/exports` |

화면에서 조건 이름, 전체/SIC/CIK universe, 고정 FY 또는 최신 완료 FY,
여러 AND predicate, column set과 정렬을 revision으로 저장한다. 저장 완료 표시는
SQLite commit 뒤에만 나온다. 서버와 브라우저를 닫은 뒤 같은 journal로 다시
실행하면 저장 조건, frozen run, 판단 event를 다시 연다.

## 판정과 화면 읽기

각 predicate는 `PASS`, `FAIL`, `UNDETERMINED`와 reason을 가진다. 누락,
`MULTIPLE_CANDIDATES`, `UNAVAILABLE`, quality block은 0으로 바뀌지 않는다. 하나의
유효 `FAIL`이 있으면 aggregate는 `FAIL`, 모든 predicate가 유효 `PASS`이고
blocking/unknown이 없으면 `PASS`, 나머지는 `UNDETERMINED`다.

상단 context strip은 financial as-of, 기간, universe, saved revision, 짧은 run과
review 상태를 보여준다. 긴 publication/hash와 parser·mapping·selection·period·
metric version vector는 `자료 출처·버전`에서
확인한다. 결과 행을 열면 값, unit, 실제 period start/context end, mapping,
Fact/accession과 전체 prepared trace가 오른쪽 패널에 나온다. 같은 FY label의 두
회사가 같은 날짜라는 뜻은 아니다.

관심·보류·제외는 사용자의 별도 append-only `DecisionEvent`다. 수정하면 이전
event를 참조하는 새 event가 생기며 재무값이나 query PASS를 바꾸지 않는다.
old run을 열어도 full rows/hash는 그대로이고 같은 revision을 새 dataset에
실행하면 별도 run이 생긴다. `CACHE_FUTURE_UPDATE_FIXTURE`는 화면과 비교 결과에서
그 label을 유지하며 live refresh로 표시하지 않는다.

full/selected CSV와 XLSX는 별도 `screen-run-export-v1`이다. export는 run/revision/
universe/publication/date/version, 전 row의 status·unknown·reason과 순서를
보존한다. CSV와 XLSX의 text는 formula로 실행되지 않는다. 같은 immutable
목적지 이름을 다시 쓰려 하면 실패한다.

## backup과 restore

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m sec_xbrl.screening backup \
  --store /absolute/run/user_journal.sqlite \
  --destination /absolute/backup/screening-journal-20261009

PYTHONPATH="$PWD/src" .venv/bin/python -m sec_xbrl.screening restore \
  --backup /absolute/backup/screening-journal-20261009 \
  --destination /absolute/restored/user_journal.sqlite
```

backup은 SQLite online backup, integrity check와 file hash가 있는 manifest를
만든다. restore는 새 빈 목적지에서만 성공한다. 기존 journal을 reset·삭제하거나
덮어쓰는 명령은 제공하지 않는다.

## S01–S08 실제 인수 실행

최종 인수는
[`screening-dashboard-user-acceptance.md`](../implementation/screening-dashboard-user-acceptance.md)의
순서를 따른다.

1. 실제 21사 publication에서 지원 matrix를 확인하고 별도 독립 oracle의 CIK,
   선택 값과 예상 집합 hash를 고정한다.
2. 전체 21사·SIC 미분류 포함 revision을 저장하고 재시작·blank restore 뒤 다시
   연다. 이후 별도 SIC revision의 target CIK를 frozen snapshot과 대조한다.
3. 실행 결과가 모든 target을 한 번씩 보존하고 count 식과 독립 oracle을
   만족하는지 확인한다.
4. reported positive control의 실제 날짜, unit, Fact/accession과 full trace를
   DOM과 JSON에서 대조한다.
5. 실제 날짜가 다른 SIC peer를 비교하고 `UNKNOWN_SIC` 후보가 metadata query에
   남는지 확인한다.
6. 관심→보류 두 event와 restart readback을 확인한다.
7. frozen old run과 별도 `CACHE_FUTURE_UPDATE_FIXTURE` run을 비교한다. 실제 값이
   같은 재발행 control은 `NO_VERSION_CHANGE`/data identity 차이를 사실대로
   기록하고, 값 변화 control은 synthetic/cache label로 별도 실행한다.
8. full/selected CSV/XLSX 네 파일을 canonical run과 재대조한다.
9. zero result, invalid metric, missing, synthetic save failure, keyboard focus,
   1,440px/1,024px 화면을 확인한다.

독립 expected 결과는 screening executor를 호출해 만들지 않는다. browser 자동
검사 결과, 독립 검증, lead 로컬 인수, 사용자의 직접 walkthrough와 원격 merge는
서로 다른 상태로 보고한다.
