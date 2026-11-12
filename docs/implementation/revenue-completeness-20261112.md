# 공시 매출 범위·누락 사유와 보수적 Q4 — 2026-11-12

상태: APPROVED / IMPLEMENTED 후보. 독립 검증·리드 인수·live·main은 대기다.
기준 main: `90652de1c07ee42b1c185d3269ad6be464cc2604`.

## 승인과 경계

사용자는 기존 50사 재무 데이터의 누락 사유 구분, 확인된 사업부문 추가 축,
보수적인 공통 매출 Q4 파생 및 새 보조 발행/live를 승인했다. 이 구현자는 소스와
새 불변 발행만 전달한다. Nasdaq 수집, 기존 Raw/History/분석 발행, 사용자
journal, main 및 runtime은 변경하지 않는다. 전체 History 재생성이나 회사별
예외는 없다. 상세 원본 조사는 선택적 로컬 evidence인
`work/revenue-completeness-inspection-20261112/findings.json` 및 NFLX/AAPL/AMZN
선택 입력에 보존하며 이 tracked 계약이 규범적 범위와 정책을 정의한다.

기존 exact dataset manifest SHA-256
`afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4`,
cutoff 2026-10-25와 모든 50사 부모 publication을 재사용한다. 기존 매출 asset
SHA-256 `187fb9b2fc4ccd64813ddd671576b331aab6497473f4677e0c8c1e9bf37203bb`가
이미 인수된 보고값·계보·비중·전년비·제품 계층의 보존 기준이다.

## 명시적 scope와 누락 사유

명시적 view 등록의 **사업부문**에만 공통 qualifier
`srt:ConsolidationItemsAxis = us-gaap:OperatingSegmentsMember`를 추가한다.
모든 회사에 같은 조건을 적용하고 전체 axis/member를 보존한다. 다른 member,
다른 추가 축, 제품/지역과의 새 Cartesian 조합은 자동 허용하지 않는다. 이처럼
새로 허용하지 않은 범위는 수치 합산·축 제거 대신 unsupported-scope evidence로
남긴다. 추가 범위의 사업부문도 연결 매출을 임의 분모로 삼지 않는다. 정확한
고정 scope의 독립 보고 부모가 없으면 비중을 보류한다. 기존 unqualified
사업부문 분모·계층 검색에는 새 qualified 행을 넣지 않는다.

화면과 발행은 현재 준비 행의 정확한 범위 입력 부재, 다른 공시 분류 기간의
행, 항목 연결 검토, 경쟁 scope, 지원하지 않는 추가 분류, Q4 FY/YTD9 입력 부재,
입력 충돌·기간/범위 불일치와 연결 미확인을 구분한다. `Q4_SCOPE_NOT_CONNECTED`는
연결을 입증하지 못한 상태이며 공시 데이터가 없다는 단정이 아니다.
FY의 연결 검토 source와 현재 표시 행의 동일한 전체 공시 범위는 **진단만**
설명할 수 있고 다른 canonical epoch의 재무 입력을 결합하지 않는다.

UI는 기존 ivory/ink/blue·표·차트·고정 헤더·원문 링크를 유지한다. 짧은 일반어
사유와 native details의 선택형 수량, focus/hover 설명을 사용한다. 빈 행이
표에서 생략돼도 보기/기간 사유가 표시된다. 전체 공시의 부재라고 주장하지 않는다.

## 별도 Derived 정책

`analytics/revenue_quarters.py`가 exact pinned T1 관측값에서 별도 Derived
record와 exclusions를 만든다. 기존 core `derive_quarter`의 scope/date/차감/계보
기구를 내부 helper로 분리해 재사용하며 core의 기존 `approved_additive` gate와
출력 의미는 유지한다. 기존 수동 reviewed-dimensional-Q4 경로도 그대로다.

새 규칙은 `confirmed-dimensional-revenue-fy-ytd9-q4-v1`이다. 두 표준 us-gaap
매출 QName `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`의
직접 보고 USD monetary duration만 대상으로 삼는다. 동일 CIK/회계연도/공통
연간 시작일·정확한 full confirmed canonical concept/dimensions, 통화와 호환
basis/structural/recast scope, FY/YTD9 actual 기간, cutoff, nil/품질/연속성/재작성
검토 및 입력 유일성을 검사한다. Mapping review 또는 불완전한 mapping ID는
거부한다. 사용자 정의 namespace/member를 이름·QName·label만으로 이어 붙이지 않는다.
다른 통화, amendment, 중복 입력, 미확인 scope와 누락 입력은 보류하고 0으로
대체하지 않는다. 0·음수의 유효 결과는 그대로 보존한다.

기존 core와 같이 양쪽 basis/structural/recast의 부재가 일치하면 이를 명시적으로
기록한다. Assurance는 **ARITHMETIC_ONLY_NOT_RECAST_VALIDATED**이며 재작성
동등성이나 리뷰 완료를 주장하지 않는다. `FY − YTD_9M` 실제 Q4 날짜가 표시
대상 기간과 정확히 맞아야 한다. 직접 Q4 값이나 충돌 상태는 우선하며 덮어쓰지
않는다. 두 원본 Fact ID/snapshot/accession과 ordered source inputs, 규칙·수식·
실제 기간·full canonical scope 및 exact 부모 History/T1 manifest/관측 파일 hash를
독립 companion에 남긴다. 표시 셀은 Derived ID/규칙, 값, 두 compact SEC 출처만
소비하며 모든 business 계산은 UI 밖에 있다.

새 파생 셀은 기존 reported-only ratio 정책을 통과하지 않으므로 비중/전년비를
보류한다. UI는 매출 차감값의 가용성과 직접 공시값만 비율 계산 대상으로 쓰는
현재 로직을 별도로 설명한다. 파생 Q4의 매핑 epoch/full scope가 다른 이전 선을
label로 연결하지 않는다.

## 불변 발행과 기존 출력 재사용

`--derived-output`은 별도 governed companion을 만들고 asset 및 회사별 quarterly
API에 SHA-256/규칙/schema pin을 연결한다. API pin에는 로컬 절대 경로를 넣지
않는다. Companion은 전체 증거를 보존하고 UI asset에는 입력 T1 행을 중복 넣지
않는다. 기존 asset 16MiB와 회사 응답 1MiB 상한은 유지한다.

선택형 `--baseline-asset`/`--baseline-sha256` 쌍은 동일 dataset/publication/cutoff,
부모 analysis·T1 pins, 기간·연결 매출, full row/axis/member/epoch 및 모든 원래
값의 amount/status/cellID/source identity를 먼저 대조한다. 같은 source의 이미
인수된 ratio/계층만 재사용한다. 달라진 Fact나 경쟁 scope를 숨기거나 새 scope에
이전 비율을 상속하지 않는다. 불일치는 실패한다. 이 source가 없는 새 경로도
qualified 부모를 legacy 검색에서 분리해 기존 정책을 유지한다.

## 자체 증거와 현재 산출물

실제 준비의 첫 시도는 qualifier를 모든 view로 넓혔다가 MRK 3,090,309-byte
응답으로 상한에서 실패했고 아무 발행도 쓰지 않았다. 리드가 확인된 사업부문
qualifier만 승인한 뒤 재시도했다. 실패 resource 기록도 보존한다. 성공 준비는
102.40초, peak RSS 1,603,312 KiB였다. 새 API pin·사유·기존 ratio 보존의 최종
재포장은 동일 helper로 완료된 projection을 재사용했으며 T1을 다시 읽지 않았다.

최종 파일은 `work/revenue-completeness-20261112/` 아래에 있으며 Git에 넣지 않는다.

| 산출물 | bytes | SHA-256 |
| --- | ---: | --- |
| `revenue-breakdowns-current50-v3.json` | 12,171,438 | `db71131a490b479278e49a4708a9518a321212df0efa3a09cffbf9cdbd53b231` |
| `governed-revenue-q4-current50.json` | 10,225,572 | `c8e3d9c50a00f12ebb15ee48813f9b66d5eabd2608de38dc535b58ca8789a8d1` |

이전 asset은 8,570,993 bytes다. Bridge 50사 재열기와 API proof pin을 확인했고
최대 응답은 1,000,126 bytes다. 원래 non-null **4,702셀**의 값·계보·비율과
기존 모든 행·기간·연결 매출·계층은 **차이 0건**이다. 새 qualified 보고 셀은
762개/30사, 표시된 Derived Q4는 **224셀/30사**다. Companion의 적격 542 record 중
78개는 prepared mapping scope 부재로 표시 보류되고 다른 기간의 기록도 포함한다.
이 수를 모두 새 표시 셀로 주장하지 않는다.

AAPL FY2026 Q1–Q3에는 각각 5개 사업부문이 추가 full scope로 보인다. NFLX
FY2025 Q4의 확인된 US scope는 4,900,000,000이며 Streaming 지역은 연결 검토로
유지한다(표시 row/epoch 기준 검토 gap 20, 연간 입력 부재 8, 연결 미확인 4).
AMZN geographic Q4는 YTD9 입력 부재·연결 검토를 구분하고 임의 보충하지 않는다.

최종 row-period gap 수는 다른 공시 분류 기간 15,280, 정확한 범위 입력 없음
1,498, 연결 검토 2,681, Q4 연결 검토 2,330, Q4 연간 입력 없음 696,
Q4 scope 연결 미확인 1,651, Q4 중복 입력 38, Q4 범위/기간 불일치 17,
Q4 YTD9 입력 없음 12, 경쟁 scope 96, 준비값 검토 1이다. 역사적 epoch의 빈
셀을 포함하는 수이며 회사 수나 미공시 항목 수가 아니다.

검사는 focused Q4/표시 단위, 기존 core targeted 회귀 및 완전한 기존 core 반환값
9개 직접 동등성, baseline 불일치 거부, qualified 분모 보류, API pin, 빈 보기 사유와
keyboard 표시를 포함한다. 상세 실제 비교는 `publication-comparison-final.json`,
두 준비 resource 기록은 `preparation-resource-attempt1-failed.txt`와
`preparation-resource-attempt2.txt`다. 로컬 증거 없이도 위 정책·pins·상태가 인계의
기준이며 실제 live/main 완료는 리드의 별도 증거 후 기록한다.

최종 focused 실행은 다음과 같다.

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_revenue_quarters.py tests/screening/test_revenue_breakdowns.py -q
node tests/screening/screening_revenue_breakdowns.test.cjs
```

Python **42 PASS(0.07초)**, Node **11 PASS**, 변경 Python Ruff, JavaScript syntax,
diff whitespace가 PASS다. 기존 core targeted 27개 근거와 직접 반환값 동등성
9개는 재사용한다. 새 정책의 structural/recast/basis break 및 compatibility_failure
거부도 검증하며 현재 companion의 1,084개 source inputs에 해당 flag가 없고
최종 qualification을 모두 통과함을 확인했다. 이 확인으로 별도 데이터 재생성은
하지 않았다. Source fixture의 legacy segment 부모에도 생산 경로와 같은 full
axis 정보를 유지하도록 보완했다.

새 발행은 아래 producer 인자를 사용한다. `$REVENUE_DATASET_MANIFEST`와
`$REVENUE_BASELINE_ASSET`은 위 정확한 pins의 기존 입력 파일이고 나머지 두 경로는
존재하지 않는 새 출력이어야 한다.

```bash
PYTHONPATH=src .venv/bin/python -m examples.screening.prepare_revenue_breakdowns \
  --dataset-manifest "$REVENUE_DATASET_MANIFEST" \
  --dataset-manifest-sha256 afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4 \
  --baseline-asset "$REVENUE_BASELINE_ASSET" \
  --baseline-sha256 187fb9b2fc4ccd64813ddd671576b331aab6497473f4677e0c8c1e9bf37203bb \
  --derived-output "$REVENUE_NEW_GOVERNED_OUTPUT" --output "$REVENUE_NEW_DISPLAY_OUTPUT"
```

이는 준비된 입력의 새 발행이며 SEC 다운로드·parser·History 감사 명령이 아니다.
현재 최종 v3는 같은 producer finalizer로 두 번째 projection을 재사용해 증거 pin,
세분화된 사유와 이미 인수된 보고 비율/계층을 연결한 불변 산출물이다.
