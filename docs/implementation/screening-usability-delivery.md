# 일반 투자자 스크리닝 R1 전달 계약

## 1. 승인과 상태

기준일은 **2026-10-09 KST**다. 사용자는 locally accepted 스크리닝 v1
`825c697050cdbf88aef46770452336bc00a3bac7`을 부모로 하는 R1 로컬 구현을
승인했다. 현재 상태는 **APPROVED / IMPLEMENTATION_IN_PROGRESS**다. 구현 브랜치는
`codex/screening-usability`이며 push, PR, remote CI와 `main` 병합은 승인 범위가
아니다.

R1의 목적은 일반 투자자가 기술 provenance를 먼저 읽지 않고도 성장성,
수익성, 현금흐름·재무안정성과 주요 보고 항목을 조건으로 선택하게 하는 것이다.
기술 근거는 삭제하지 않고 상세 설명과 불변 publication에 보존한다. SEC SIC,
후보 directory, 반복 단위·reason·raw trace를 기본 조건 화면의 중심 정보로 두지
않는 UI 작업은 별도 writer가 담당한다. 이 writer는 UI 파일을 수정하지 않는다.

기존 실제 21사 publication, 사용자 journal, 원천·history·analysis와 v1 dataset은
읽기 전용으로 보존한다. 새 actual runtime은
`data/processed/screening_runs/20261009_usability` 아래의 새 목적지에만 발행한다.
live 수집, 가격, 새 cohort, 전체 Q4 또는 기존 journal/schema/ID 재작성은 하지
않는다.

## 2. 전달 산출물

R1은 다음의 순서가 있는 producer/consumer 경계를 만든다.

1. opt-in expanded annual analysis bundle은 기존 annual FY와 정확히 같은 연도말의
   `INSTANT`를 함께 준비한다.
2. governed screening metric producer는 prepared analysis만 읽어 21개 reported와
   10개 derived 정의의 불변 publication을 만든다.
3. screening dataset v2 producer는 metric publication을 검증하고 화면 실행용
   observation/support/catalog을 만든다.
4. service는 발행된 dataset만 읽으며 formula, filing selection, mapping 또는
   회계 판단을 실행하지 않는다.

public API/CLI의 정확한 이름은 구현과 함께 동결하되 다음 역할을 제공한다.

```python
publish_screening_metrics(config_path, destination) -> ScreeningMetricPublication
ScreeningMetricReader(root).verify_all()
publish_screening_dataset_v2(config_path, destination) -> ScreeningPublication
```

```text
python -m sec_xbrl.screening metrics --config CONFIG --destination METRICS
python -m sec_xbrl.screening prepare-v2 --config CONFIG --destination DATASET
python -m sec_xbrl.screening status --dataset DATASET
```

`GET /api/metric-catalog?dataset_id=...`는 dataset별 deduplicated 정의를 반환한다.
각 항목은 `metric_id`, 일반 사용자 label, category, `unit_kind`, unit,
definition version, period class, company/period coverage와 business availability를
가진다. 기존 v1 endpoint, reader, export와 journal은 그대로 읽을 수 있어야 한다.
과거 screen/run은 결합 당시 v1 dataset을 계속 사용하며 새 v2를 자동으로
재평가하지 않는다.

## 3. analysis opt-in 경계

`prepare_analysis(..., include_year_end_balances=False)`를 추가한다. 기본값 `False`의
기존 ANNUAL/QUARTERLY 산출물은 byte-equivalent여야 한다. `True`는 `ANNUAL`에서만
FY와 `INSTANT`를 함께 읽으며 다음을 모두 만족한 기말 cell만 준비한다.

- 해당 회사·fiscal year에 unique FY end-exclusive가 있음
- raw instant가 그 FY end-exclusive와 정확히 같음
- `period_class`는 계속 `INSTANT`; FY와 합치거나 같은 year label만으로 연결하지 않음
- newest interim balance를 연말 값으로 승격하지 않음
- config는 12개 monetary FY와 9개 monetary INSTANT row를 명시함
- manifest와 context가 opt-in balance scope를 선언함

opt-in 결과는 기존 governed binding의 `primary_statement_evidence`를 typed IS/CF/
BS/EQ source evidence로 materialize한다. label이나 role 이름 추측으로 증거를
만들지 않는다. 기본 경로의 compact/output은 바꾸지 않는다.

## 4. metric publication 계약

metric publication은 최소 다음 파일을 원자적으로 발행한다.

```text
screening_metric_manifest.json
metric_definitions.json
metric_support.json
metric_observations.json
source_snapshots/<CIK>/<snapshot-id>.json
```

manifest는 config, 모든 analysis parent manifest/file, 회사·CIK·financial-as-of,
정확한 view, metric definition/rule version, mapping/selection/period/parser version,
file hash/size와 publication ID를 묶는다. reader는 file set/hash, count, unique grain,
source parent identity와 copied cell을 read-only로 재검증한다. 자체 JSON을 함께
고쳐 다시 hash한 위조가 prepared parent와 달라지면 거부한다.

reported observation은 `REPORTED`이고 derived observation은 `DERIVED_METRIC`이다.
모두 company, actual period, fiscal year, period class, view/as-of, finite decimal
string, unit, complete dimensions, basis/comparability/status/reason, source cell·Fact·
accession·QName·filing, mapping/selection/parser version을 보존한다. derived row는
formula, sign/scaling convention, ordered input ID/value, compatibility 결과와 계산
rule version을 추가한다. unavailable도 definition/support에서 빠지지 않는다.

## 5. 공통 입력 gate

계산 입력은 existing selected `REPORTED` 또는 이 계약의 앞선 governed
`DERIVED_METRIC` 중 다음 조건을 모두 만족해야 한다.

- 유한 Decimal, USD monetary unit, 같은 company와 complete dimension signature
- 필요한 실제 period/instant, source filing과 typed primary statement evidence
- `mapping_review_required`가 false이고 original quality `BLOCK`이 아님
- basis가 같고 호환됨. null/null은 `REPORTED_VALUES_NOT_RECAST_VALIDATED` 산술
  policy를 명시할 때만 사용하며 `COMPATIBLE`로 승격하지 않음
- custom concept bridge, split debt 합산, liabilities를 debt로 치환하지 않음.
  단, `net_debt`의 debt leg는 지표 정의 계약의 exact standard QName note allowance를
  만족할 때만 typed primary BS evidence 예외를 허용함

실패는 `UNAVAILABLE`와 business reason으로 남긴다. 누락을 0으로 채우지 않는다.
계산은 고정 local Decimal context를 사용하고 exact canonical decimal string을
발행한다. ambient Decimal precision에 의존하지 않는다.

세부 정의는 [스크리닝 지표 정의 계약](screening-metric-definitions.md)에 있다.

## 6. dataset v2와 화면 소비 경계

dataset v2는 metric publication만으로 실행 observation과 support matrix를 만든다.
analysis, raw/history, SEC/XML을 직접 읽거나 metric을 다시 계산하지 않는다.
metric parent publication ID/manifest SHA와 모든 copied row/hash를 묶고, v2 reader가
이를 다시 검증한다. source kind와 stable metric observation/input ID를 보존하며
FY와 INSTANT를 같은 연도 key로 합치지 않는다.

predicate는 각 metric의 definition version을 사용한다. money threshold는 USD,
rate/ratio threshold는 percentage point다. NaN/Infinity와 unit/period mismatch를
거부한다. unsupported/unavailable/review/block는 기존처럼 `UNDETERMINED`이며
0이나 FAIL로 바뀌지 않는다.

category는 `GROWTH`, `PROFITABILITY`, `CASH_FLOW`, `FINANCIAL_STABILITY`,
`OTHER_REPORTED`다. metric catalog는 실제 coverage와 불가 사유를 보여주며 31개
전부가 모든 회사·연도에서 사용 가능하다고 주장하지 않는다. 조건 임계값은
사용자 입력이고 투자 추천 preset을 제공하지 않는다.

## 7. 검증과 전달 gate

구현 writer는 다음을 확인하고 source SHA를 동결한다.

- 기본 `prepare_analysis` golden byte identity와 opt-in FY/INSTANT year-end selection
- 31개 정의, 정상·손실·0·부호·basis·period·mapping·dimension·unit·typed role mismatch
- revenue YoY의 52/53주·consecutive year·duration/gap gate
- margin, standardized FCF와 balance ratio/net debt의 source/filer compatibility
- metric/source parent coordinated tamper와 copied row 위조 거부
- v1 dataset/reader/API/export와 기존 journal 재열기 호환
- v2 catalog의 supported/unavailable coverage 및 mixed FY/INSTANT grain
- unit/integration, 실제 cached 21사 control, 전체 regression과 Ruff

별도 verifier가 frozen SHA와 실제 새 runtime을 읽기 전용 검증한 뒤 lead가 로컬
인수 여부를 판단한다. UI writer 결과는 별도 commit으로 통합한 뒤 같은 최종 SHA를
다시 동결한다. 구현, 독립 PASS, lead 로컬 인수와 원격 병합을 서로 대신 쓰지
않는다.

