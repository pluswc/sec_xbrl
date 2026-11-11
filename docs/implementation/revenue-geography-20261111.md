# 공시 매출의 지역 보기와 명시적 보기 등록 — 2026-11-11

상태: IMPLEMENTED / 자체 검사 통과. 독립 검증·로컬 인수·main 병합·운영 전환은 대기다.
본 계약은 기존 50사 준비 데이터의 선택형 매출 보조 발행과 해당 화면만 다룬다.
신규 수집, Raw/Analytical 재생성, Nasdaq 수집 작업은 범위 밖이다.

## 입력과 수락 기준

- `screening-dataset-v3`의 정확한 부모를 재사용한다. 재무 cutoff는 2026-10-25,
  dataset manifest SHA-256은
  `afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4`다.
- 기존 사업부문·제품/서비스·연결 매출·제품 계층·비중/전년비의 공시 선택과 값을
  유지한다. 연간 4개, 분기 8개 실제 준비 기간을 사용한다.
- `srt:StatementGeographicalAxis`의 보고 항목을 지역 보기로 추가한다.
  지역 단독 및 등록된 사업부문·제품 축과의 명시적 조합을 지원한다.
  별도 근거 없는 과거 `us-gaap` 별칭, 사용자 정의 축의 이름 유사성,
  등록되지 않은 재분류 축을 자동으로 활성화하지 않는다.
- `REVENUE_VIEWS`의 명시적 등록이 기본 축, 허용 고정 분류, 보기 우선순위,
  표시 이름을 결정한다. 추가 분류는 계약 검토 후 등록하며 필요하면 분모 정책을
  지정한다. 모든 축을 수용하는 범용 의미 추정기는 아니다.

## 의미와 화면

지역 보기는 병렬 공시 관점이다. 지역 계층, 완전한 세계 분할, 중간 지역,
누락된 소계나 축간 합계를 만들지 않는다. 원래 공시 라벨과 전체 명시적 차원,
매핑 epoch, 원본 fact 계보, 충돌 및 기간 공백을 유지한다. 고정된 다른 축의
member를 함께 표시한다. 지역명만으로 소재지·청구지·배송지·고객 위치를 추정하지
않으며 회사간 같은 기준이라고 주장하지 않는다. AAPL 등의 지역성 사업부문도
사업부문 축에 있으면 기존 사업부문 보기로 유지한다.

지역 단독의 비중 분모는 동일 공시의 연결 매출이다. 다른 축이 고정된 지역은
전체 차원에서 지역 축만 제거한 정확한 scope의 독립적으로 보고된 부모를
기존 준비 행에서 유일하게 확인할 때만 비중을 제공한다. 동일 snapshot·filing·
concept·통화·기간·품질·전체 raw 차원 부분집합 검사를 유지한다. 고정 scope가
다르거나 부모가 없거나 경쟁하면 비중을 보류하며 연결 매출로 대체하지 않는다.
분모 출처 fact ID는 비중 계보에 남긴다. 다른 축을 합산하여 부모를 만들지 않는다.
전년비는 기존 `same-filing-revenue-ratios-v1`의 동일 공시·동일 전체 scope
비교만 사용한다. 기존 제품 계층 정책은 지역 행에 적용하지 않는다.

화면은 기존 워크시트의 native select, 표, 선택형 추이 보드와 원문 링크를
재사용한다. 서버가 발행한 보기 descriptor를 표시하며 이전 payload는 기존
보기에 지역 빈 보기를 더한 fallback으로 읽는다. 빈 payload/누락 그룹은 빈 상태로
표시한다. 보기별 차트 선택과 기간 clamp 정책을 유지한다. Display는 재무 비율을
계산하지 않는다. 기존 ivory/ink/slate/annotation-blue, 4px spacing과 표 계층을
유지하므로 별도 디자인 체계를 도입하지 않는다.

## 재현과 인계

필수 입력은 위 exact dataset manifest 및 그 부모 publication이다. bulk 보조
JSON은 Git에 넣지 않는다. 소스 검사는 다음과 같다.

```bash
.venv/bin/python -m pytest tests/screening/test_revenue_breakdowns.py -q
.venv/bin/ruff check examples/screening/prepare_revenue_breakdowns.py tests/screening/test_revenue_breakdowns.py
node tests/screening/screening_revenue_breakdowns.test.cjs
```

실제 발행은 `python -m examples.screening.prepare_revenue_breakdowns`의
`--dataset-manifest`, `--dataset-manifest-sha256`, `--output`으로 수행한다.
실제 결과 크기와 50사 기존 행 동등성, AMZN/MSFT/GOOGL의 기간별 실제 가용성,
새 산출물 해시는 아래 구현 증거에 기록한다. 운영 bridge 전환과 원본 journal
불변·실제 브라우저 검증은 리드가 별도로 수행하며 소스 자체 검사로 추정하지 않는다.


## 구현 증거 — 2026-11-11

명시적 등록표가 축 허용·주 축/member 선택·그룹·우선순위를 결정한다. 테스트에서
별도 고객 축 등록을 추가하여 추가 엔진 분기 없이 준비 행이 새 그룹으로 투영됨을
확인했다. 고객 축은 실제 발행에서는 활성화하지 않는다.

실제 50사 보조 발행은 8,570,993 bytes이며 기존 16MiB asset 한도 안이다.
전체 company 응답(scope 필드 포함) 최대는 DE 815,217 bytes, p95는 319,922
bytes다. DE만 이전 512KiB 한도를 초과했으므로 리드가 정확한 1MiB 매출 응답
한도를 승인했다. 준비기와 bridge가 동일하게 전체 응답 bytes를 검사한다.
일반 JSON을 유지하고 압축 인코딩·페이지 잘림·자료 삭제는 도입하지 않았다.
공통 financial-growth 응답 한도는 기존 512KiB를 유지한다.

기존 보조 발행 SHA-256
`2d461aa7524b38d0143d3e6bd768128ecfd697bbdeb0cbe89ca39ea6df1a71b9`과
모든 50사×연간/분기의 기존 view 필드를 정확히 비교했다. 새 `views` descriptor와
`groups.geography`를 제외하면 기존 사업부문·제품/서비스 행, 연결 매출, 비중·전년비,
계층, 기간, 원본/발행 계보를 포함한 **차이 0건**이다. 기존 asset은 5,420,594 bytes다.
새 발행은 아래 위치에 보존하며 Git에는 넣지 않는다.

- 로컬 산출물: `work/revenue-geography-20261111/revenue-breakdowns-current50.json`
- SHA-256: `187fb9b2fc4ccd64813ddd671576b331aab6497473f4677e0c8c1e9bf37203bb`
- 크기·기존 결과 대조: `work/revenue-geography-20261111/size-and-legacy-comparison.json`

준비된 기간/허용 매출 개념의 실제 지역 가용성은 연간 42사, 분기 28사다. 전체
prepared axis inventory의 범위와 다르므로 이를 최신 SEC 전체 공시 커버리지로
주장하지 않는다. 지역 행은 연간 930개/보고 셀 937개, 분기 678개/보고 셀 877개다.
고정 scope 지역 행은 연간 187개/보고 셀 190개, 분기 302개/보고 셀 313개다.
고정 scope의 비중은 각각 156/218셀에서 확인됐고 나머지는 보고 금액을 보존한 채
보류했다.

| 회사 | 연간 실제 보고 | 분기 실제 보고와 공백 |
| --- | --- | --- |
| AMZN | FY2022–2025 각 5개 항목 | 준비된 8개 기간의 지역 보고 셀 없음 |
| MSFT | FY2023–2026 각 2개 항목 | FY2025/2026 Q1–Q3 각 2개, 두 Q4 공백 |
| GOOGL | FY2022–2025 각 4개 항목 | FY2024 Q3, FY2025 Q1–Q3, FY2026 Q1–Q2 각 4개, 두 Q4 공백 |
| AAPL | FY2022–2025 각 3개 항목 | 준비된 8개 기간의 지역 보고 셀 없음 |

GOOGL 등의 일부 기간 비중 보류는 동일 공시·개념의 분모 조건을 그대로 적용한
결과이며 다른 매출 개념을 대신 사용하지 않는다. 지역적 명칭의 기존 사업부문은
사업부문에 그대로 남는다.

자체 focused Python 16 PASS, Node 9 PASS, 변경 Python lint PASS,
두 JavaScript syntax 검사와 diff whitespace PASS다. 실제 artifact의 bridge
load에서 50사와 최대 응답 815,217 bytes를 확인했다. 원본 자료 및 서비스에는
쓰기하지 않았다. 별도 브라우저의 실제 화면 검증과 독립 검증·리드 인수·main
병합·live 전환은 이 소스 자체 검사의 범위가 아니다.

## 독립 FAIL 반환과 고정 scope 분모 보완 — 2026-11-11

후보 `ca09c3f5f92d46e7c3763e768adf8819ba1ff87b`는 독립 검증에서 P1 FAIL을 받았다.
동일 고정 scope의 부모 후보를 ratio-bind 성공 여부로 먼저 걸러서, 명시적으로
`COMPETING_PREPARED_SCOPE`인 부모가 사라진 뒤 다른 정상 부모만 선택될 수 있었다.
지역의 고정 scope 부모는 해당 기간에 보고 값이 있거나 명시적인 충돌 상태인
모든 후보를 먼저 세고, 단 하나인 경우에만 기존 ratio-bind를 적용하도록 고쳤다.
기존 제품·사업부문 분모 선택은 변경하지 않았다.

새 회귀 검사는 충돌 부모와 정상 부모가 함께 있을 때 지역 보고 금액과 검증된
동일 공시 전년비를 유지하면서 비중만 보류함을 확인한다. 보완 후 focused Python
17 PASS, 변경 Python lint와 diff whitespace PASS다. 이전 Node 9 PASS는 변경 없는
화면/bridge 근거로 유지한다. 새 소스의 독립 검증과 인수는 별도 대기다.

기존 current50 payload의 고정 scope 보고 503셀과 공표 비중 374셀만 대상으로
부모 후보를 재검사했다. 명시적 충돌 부모 0셀, 복수 활성 부모 0셀, 영향받는
기존 공표 비중 0셀이다. `work/revenue-geography-20261111/fixed-parent-conflict-check.json`에
결과를 보존한다. 이 보완은 실제 artifact 값을 바꾸지 않으므로 deep rebuild나
기존 전체 감사는 반복하지 않았고 위 artifact bytes와 SHA-256을 그대로 유지한다.
