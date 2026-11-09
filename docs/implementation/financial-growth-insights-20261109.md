# 재무 비교 보드의 전년 대비 변화

## 승인과 범위

2026-11-09 승인. 기준 소스 `8436ee9fa5`. 영업이익, 영업활동 현금흐름,
표준화 FCF의 연간·분기·TTM 전년 대비 비교를 차트에 제공한다. 오프라인
생산기는 고정한 기존 발행물에서 파생 결과를 만든다. Windows 브리지는 해시,
발행 범위와 CIK가 맞는 고정 결과를 조회 전용으로 전달한다. Python 패키지,
원본·부모 발행물, 매출 구성, 배치·스크리닝 카탈로그 및 저장 기록은 기존
경로를 사용한다. 결과는 스크리닝 조건 지표에 추가하지 않는다.

## 계산 및 비교 근거

- 같은 회사, 정의와 버전, USD 및 단위·차원·선택 보기와 재무 기준일이
  일치하는 준비 관측을 쌍으로 사용한다. 의미·매핑·보고 기준이 불명확하거나
  품질 보류, 중복, 누락인 관측은 보류한다. 준비 과정의 산술 보증을 재사용할 때
  재작성 기준의 비교 가능성을 주장하지 않는다.
- 연간은 직전 회계연도, 분기와 TTM은 직전 회계연도 같은 회사 회계분기다.
  연간과 TTM의 양쪽 기간은 364·365·366·371일 중 하나이며, 전년 종료일과
  현재 시작일이 같아야 한다. TTM은 각각 4개씩의
  유일하고 연속적인 분기 다리와 양쪽 실제 기간·기준을 검증한다. 준비 발행물에
  앞선 기간이 없으면 누락 사유를 남긴다.
- 비교 가능한 쌍은 현재−전년의 부호 있는 USD 차이를 발행한다. 전년이 양수이고
  현재가 0 이상이면 `(현재 / 전년 − 1) × 100`을 발행한다. 양수→0은
  −100%와 0 도달 상태를 함께 표시한다.
- 둘 다 음수일 때 일반 전년비는 비어 있으며 `(|전년| − |현재|) / |전년| × 100`의
  규모 변화와 방향을 별도로 발행한다. 영업손실, 영업현금 순유출, 음수 FCF를
  구분한다. 부호 전환, 전년 0, 음수→0의 상태를 일반 전년비와 구분한다.
- 발행 결과는 양쪽의 정확한 값·관측 ID·실제 기간 및 적용한 정책을 보존한다.
  종료일은 배타적이며 화면에서는 마지막 포함 날짜를 표시한다.
  화면에서 현재 금액·실제 기간과 제공된 관측 ID가 준비 관측과 맞을 때 사용한다. 상태와
  근거는 숫자 선이 없어도 읽을 수 있다. 일반 전년비의 누락에서는 선이 끊긴다.
  기존 매출 전년비와 매출 구성의 같은 공시 비율은 기존 경로를 유지한다.

## 세로축과 검증

재무·매출 보드의 기본 세로축은 현재 표시값의 범위를 사용하며, 사용자가
0을 포함하도록 전환할 수 있다. 0을 생략하면 축에 표시한다. 매출 금액은
선택 시리즈끼리 축을 공유하고, 재무 지표 및 백분율은 각각의 축을 쓴다.
재무 수준은 점이 기본이며 선으로 바꿀 수 있다. 재무 보드의 전년비는
항상 0을 기준으로 양수·음수를 나누어 표시하는 세로 막대다. 발행된 0은
기준선의 짧은 표식으로 표시한다. 금액 축 전환은 이 막대의 기준선을
바꾸지 않는다. 매출 구성의 여러 시리즈는 점과 선을 사용한다. 축 범위
계산은 표시용이다. [ONS 막대 차트 지침](https://service-manual.ons.gov.uk/data-visualisation/chart-types/bar-charts)

오프라인 생산기는 `examples/screening/prepare_financial_growth.py`다.
검증된 기존 combined manifest 경로와 SHA-256, 기존 source compatibility
경로와 SHA-256, 새 출력 경로를 받는다. 파생 결과 정의에는 규칙 버전, 공식,
단위와 적용 조건을 명시한다. Windows 브리지는 `--financial-growth`와
`--financial-growth-sha256`을 쌍으로 받아 `GET /api/financial-growth`의
가용성과 정확한 발행 범위의 기업별 준비 결과를 제공한다.

```sh
PYTHONPATH=src python examples/screening/prepare_financial_growth.py \
  --dataset-manifest "$parent_manifest" --dataset-manifest-sha256 "$parent_sha" \
  --source-compatibility "$compatibility_packet" "$compatibility_sha" --output "$new_growth_asset"
node --test tests/screening/*.test.cjs
python -m pytest -q tests/test_screening_display_assets.py tests/screening/test_screening_explorer.py tests/screening/test_revenue_breakdowns.py tests/screening/test_financial_growth.py
```

부호·0 조합, 작은 값, 의미 및 실제 기간 불일치, TTM 다리 누락·중복,
파일과 조회 범위 검증, 늦은 응답, 자동 축과 0 포함을 검사한다. 실제
부모 발행물의 준비 파일과 브라우저 검증, 운영 반영은 소스 검증과 구분한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-09 차트 전용 파생 지표와 세로축 표시 |
| 구현 | 동결 후보에서 확인 |
| 독립 검증 | 동결 SHA 대상으로 별도 기록 |
| 실제 발행과 로컬 인수 | 별도 기록 |
| 운영·main·PR·CI | 별도 판단 |
