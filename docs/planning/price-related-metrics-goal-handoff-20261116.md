# 가격 관련 지표 전체 구현: 다음 GOAL 세션 인계

작성일: 2026-11-16. **이번 작업은 문서 인계만 승인됐다.** GOAL 생성, 지표 코드,
가격 조회·검증·발행, 운영 변경은 지금 실행하지 않는다. 아래 실행 프롬프트를 사용자가
새 세션에 전달할 때 그 세션의 승인 범위로 채택한다. 정책 제안은 구현 승인과 구분한다.

## 목적과 완료 기준

개인 투자자가 가격·재무 지표로 후보를 선별하고, 미준비 이유를 확인하며, 기업 비교·시계열·
가격 밴드를 살펴본 뒤 조건·결과·메모를 저장하고 같은 자료로 다시 열 수 있게 한다.
범위는 **가격 관련 지표 전체 계열**이며 PER만 구현하고 종료하는 과제가 아니다.
DCF, 실시간 피드, 주문·매매 엔진, 대규모 새 기업 확장은 이번 GOAL 범위 밖이다.

완료는 계획서가 아니라 IMPLEMENTED다. 공통 입력 registry·공급자 batch 연결,
버전 있는 backend 정의·계산·입력 lineage, 공통 조회 경로, 유효한 지표의 스크리닝·비교·
시계열·밴드 등록, 명시적 저장·재열기 pin, 의미 있는 검사·대표 실자료·UI 확인,
추적 문서·Git 커밋·전달 근거까지 완료해야 한다. 모든109개사의 모든 지표 숫자는 요구하지 않는다.
각 요청 계열에는 코드·검사와 입력이 가능한 대표 실자료 사례가 있어야 한다.
회사별 결측은 typed reason으로 남기되 **계열 미구현을 데이터 결측으로 표시해 완료할 수 없다.**
공급자 데이터나 정책이 계열 전체를 막으면 의존성을 사용자에게 설명하고 독립 계열은 계속한다.

## 완료된 기준선과 보존

- PR [#101](https://github.com/pluswc/sec_xbrl/pull/101)은 main
  `1b0a4f26d1a001f6f3d8e1a6a6c76aa77c9c38b7`에 MERGED다.
  필수 CI `43606365273`: 3,118 PASS / 46 SKIP. 옛 pending 기록은 당시 상태다.
- 인계 브랜치 시작 main은 `004b621acc933c36ab3aa215b72371421ab5b8d1`이며
  이후 PR100의 Q4 매출 구성 개선도 포함한다. 다음 세션은 당시 최신 main·변경을 확인한다.
- 공통109 가격/EPS/주식 수, assessment, 기업 상세 UI는 완료됐지만 PER은 아직 없다.
  Raw/공시/선택된 Analytical/별도 Derived/표시 계층을 섞거나 보고 값을 덮어쓰지 않는다.
- 2026-11-14 관측: 최신 직접12개월 EPS12개(양수11, LITE 음수), 최신 직접4분기 입력은
  HON/ABBV2개지만 basis 미확인. 나머지95개는 해당 최신 기간의 결측·범위 등의 사유가 있다.
  이 숫자는 최신 실시간 현황이 아니다. 가격 지표 구현 전체를 EPS 대기 상태로 묶지 않는다.
- 기존 EPS/WAVG direct-only, EPS의 FY−9개월 차감 금지는 유지한다. 추정 TTM이 필요하면
  별도 DERIVED 정의와 승인을 받고 보고 EPS를 대체하지 않는다. basis unknown은 분할 오류 판정이 아니다.
- 2026-11-14까지 완료한27/8·routing·새7·wrapper·실제 UI·CI 근거를 재사용한다.
  로직 변경·실제 이상 없이 완료 회사 전체 감사, Raw/History/panel 재생성은 하지 않는다.

## 전체 계열과 정책 경계

아래 계산·기간 선택 세부안은 **PROPOSED**다. 계열 범위는 유지하되 중요한 회계·동등성
선택은 종속 코드 전에 확인한다. 단순 구현 선택으로 매번 중단하지 않고 미차단 작업은 진행한다.

| 요청 계열 | 제안 계산·입력과 필수 경계 |
| --- | --- |
| 가격 수익률 | 미국 거래일1/5/21/63/126/252개 전 대비 `split_adj_close` 변화. 배당 포함 total return이 아님 |
| 연율화 변동성 | 20/60/252거래일. 단순/로그 수익률, 표본 기준, 연율화252 가정은 H0에서 확정 |
| 상대 거래량 | 최근 거래량 / 이전20거래일 기준 거래량. 최근의 의미·당일 제외 평균·완료 세션 기준을 확정; true-split 호환 volume만 사용 |
| 시가총액 | 같은 시점 가격 × 실제 유통/발행 common shares. common 종류별 가격·수량·권리 범위를 확인; WAVG 대체 금지 |
| PER | `P / diluted EPS12m`; 클래스·통화·분할/공시 EPS 기준 정렬. EPS≤0은 PER 미준비와 이유, 음수 EPS 자체는 보존 |
| PBR | common market cap / common equity 또는 `P / BPS` 경로를 명시적으로 분리. BPS는 일치하는 실제 common shares, WAVG 아님 |
| P/S | common market cap / TTM revenue. 회사 전체 매출과 common 가격·클래스 범위의 결합 근거 필요 |
| Earnings yield | `EPS / P`; 의미 있는0·음수 EPS 보존. PER 불가와 EY 불가를 같은 규칙으로 처리하지 않음 |
| 표준화 FCF yield | 기존 standardized FCF / 현재 common market cap. 기존 공식·기간·범위 유지; FCFE라고 주장하지 않음 |
| EV/Revenue | EV = common market cap + 이자부채 + 명시적 preferred/NCI − cash. 구성·리스 정책은 확인 필요; liabilities≠debt, 결측≠0 |
| EV/EBITDA | 위 EV와 같은 범위의 reported 또는 governed `operating income + D&A`. 임의 CFO addback 금지; 기간·부호·D&A 범위 확인 |
| 고정 배수 가격 밴드 | 공시/승인된 EPS·BPS × 사용자 선택 PER·PBR 배수. 선택 근거·적용 기간을 명시; 전망가 보장 아님 |
| 과거 배수 분포 | 별도의 최근3년 historical multiple percentiles. 고정 밴드와 구분; 각 과거 시점에 알 수 있던 분모 사용 |

가격 지표는 명시적 미국 세션 목록·검증 범위로 계산한다. 관측 행 수 shift, 평일 가정,
forward-fill, 결측일 건너뛰기로 N세션을 만들지 않는다. 각 창의 최소 데이터·gap 규칙을 정한다.
과거 PER 전체에 현재 EPS를 끼워 넣지 않는다. filed-day 가정과 실제 historical ready 증거,
기존 lag0 미국 세션 정책을 구분하며 ready 미확인은 백테스트 적격 인증이 아니다.
모든 비율은 단위·통화·분모0/결측/음수 정책을 버전 정의에 명시한다. UI에서 회계 계산하지 않는다.

정책 참고: [CFA Institute의 price/enterprise-value multiples 설명](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples).
가격/EV 배수, 비양수 EPS의 E/P와 PER 차이, historical EPS 시점, common equity/BPS를
구분하는 참고다. 위 창 길이·임계값·산식 선택을 회계 표준으로 승인한 근거는 아니다.

## 입력·코드 위치와 공급자 계약

규범 기준: [공통 입력 계약·운영 인수](../implementation/price-common-inputs-20261114.md),
[전달 절차](../implementation/delivery-workflow.md), [Analytical 모델](../architecture/analytical-data-model.md),
[기간 규칙](../implementation/period-rules.md), [입력 handoff](../implementation/metric-input-handoff.md).
코드: `examples/screening/prepare_market_inputs.py`, `prepare_market_input_profile.py`,
`src/sec_xbrl/metrics/{market_inputs,market_input_assessment}.py`,
`src/sec_xbrl/screening/market_input_publication.py`, 기존 display assets·Windows bridge.

불변 입력 locator(기존 근거를 다시 감사하라는 지시가 아님):

| 입력 | 경로·SHA256 |
| --- | --- |
| common109, 약40.34MB | `data/processed/market_inputs/20261114_common109/market_input_manifest.json` · `a1b1c8c3e29c92e5fdb2aaf1534dd4024a847b72b31936131f5df5899322ee58` |
| assessment v2, 약0.77MB | `data/processed/market_inputs/20261114_common109_assessment_v2/market_input_assessment_manifest.json` · `ec827bfa25a21b336416e0a2673f69394dd9b9cd2c5a1ce0e88281b1ef2c93fa` |
| profile 자산 | `work/price-common-inputs-20261114/operating/market-input-profile.json` · `271100cca9f27802088ea4bd262fa73bd9e8635248234c8d348f5831c0bd32f6` |

공급자는 `/home/plusbdw/user_work/projects/market_data_pipeline`(읽기 전용)의 공식
`CanonicalQuery`다. [공급자 소유 대화](codex://threads/01a09991-9bd0-7c20-b3c7-048130610c54)에
새 통화·corporate action·갱신 필드를 먼저 요청한다. 다른 저장소 쓰기나 별도 scraper로 대체하지 않는다.
기준 SDK0.5.1 tag `24f0b87160f793871f3dfea8faaf43092b1905d7`, 외부 계약1.1.1,
추천 `broad-price-oct2026-20261108-r1`이다. 공급자 문서:
`docs/BROAD_PRICE_OCT2026_DELIVERY_20261108.md`, `EXTERNAL_DATA_CONTRACT.md`,
`PRICE_CANONICAL_CONTRACT.md`, `CONSUMER_DATA_GUIDE.md`를 해당 저장소에서 확인한다.

- delivery: 공급자 `data/collections/broad-price-oct2026-20261108/price/delivery-v051.json`,
  SHA `46cd97b2fa674631399aa9f81300f16a6d63a61bc633f57ee71a2693c535a56f`.
- price SHA `ad53a47f3616fc4bae2e79ab553626a5f43f4679cd3c17c934ee8d9f0ffdd49c`,
  security SHA `26265d9297e47bbdd8a5373512c7a80cbd49ec5338817d0f843e24c50a400554`.
- 채택/교체 때 `verify_delivery_manifest`; 요청마다 또는 회사마다 전체 hash/scan 금지.
  `get_price_history` batch IDs를 사용하고 약3,400만 행/766MB를109번 읽거나 복사하지 않는다.
- `get_securities(cik)`는1:N이다. 첫 행 선택 금지. 등록 CIK+ticker 관측 일치는 EPS 적용 승인 아님.
- 가격 통화는 현재 계약에 없고 UNKNOWN이다. USD를 추정하지 말고 증명된 입력을 요청한다.
- `as_traded`와 true `split_adj`를 분리한다. `split_factor`는 고정 horizon까지의
  거래일 이후 실제 분할 누적값이며 EPS factor나 spinoff 보정값이 아니다.
  재작성 EPS에 일괄 재적용하지 않는다. 거래량도 공급자 기준과 일치해야 한다.
- 고정 자료 마지막 관측10/30, 수집11/8, horizon11/9. 기존 재무 cutoff10/25에는10/23 종가를
  사용했다. **2026-11-16 최신가·자동 갱신 자료가 아니다.** 요청일 D의 전일 자동 대체 금지:
  선택 정책, 실제 거래일·staleness를 명시하고 결측·0·행 부재를 구별한다.
- 새로운 일별 incremental refresh·source version이 필요하다. historical readiness는
  미확인 상태이며, 최신 공시를 옛 고정 producer 승인에 억지로 통과시키지 않는다.

## 동적 운영 상태와 작업 보존

다음 세션에서 실제 main·관련 계약·현재 프로세스/자산/데이터 metadata를 좁게 확인한다.
운영 URL은 `http://127.0.0.1:18765/`; qualified backend19078은
`work/screening-prepared-changes-20261114/source`의 `d1e` 계열이다.
마지막2026-11-14 관측 frontend는 Node40460,
`C:/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/revenue-q4-continuity-20261114/live-bundle`이었다.
이 PID·경로를 최신 사실로 가정하지 말고 추가 Q4 UI와 동시 작업을 보존한다.
옛 Node58984/bundle로 되돌리거나 광범위한 worktree 정리를 하지 않는다.

journal `data/processed/screening_runs/20261009_initial/user_journal.sqlite`의 마지막11/14 SHA는
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`다.
새 사용자 기록을 보존해야 하므로 옛 SHA/backup으로 복원하지 않는다. 새 변경은 불변 발행물로
추가하고 옛 publication/저장 조건·결과·메모는 다시 열 수 있어야 한다.
새 main 모듈은 기존 native/source 승인을 자동 상속하지 않는다. 정확한 source·의도된
호환 범위를 명시하며 승인 guard를 조용히 완화하지 않는다. 선택 근거는 추적 문서에 둔다.
선택적 병합 receipt: `work/price-common-inputs-20261114/main-delivery/main-merge-acceptance.json`.

## 작은 단계와 검증

- H0: 현 상태·입력 재사용 인계, 중요한 정책 선택 확인. 목표·수락 범위를 추적 문서에 고정.
- H1: 공유 registry와 결측 계약, 공급자 통화·클래스·분할·날짜 입력 계약, batch와 기존 projection 참조 재사용.
- H2: 계약 후 독립 가격 지표·상대 가치·EV 계열 구현과 대표 가능한 실자료 사례. 미차단 계열부터 진행.
- 공유 batch 가격 읽기를 한 번 수행하고 long metric 출력은 원 입력을 참조한다. 지표별/회사별
  766MB 재검증·복사, 큰 새 index나 full panel 재생성은 피한다. 통화·corporate action은
  공식 공급자의 작은 metadata 보완을 우선하고 전체 가격 이력 재수집으로 대체하지 않는다.
- 많은 agent가 필수는 아니다. 공유 registry 뒤 단일 writer와 프로그램 batch 병행으로도
  독립 가격/가치 계열을 진행할 수 있다. 창 길이·거래량 구간은 제안 기본값이지 불변 회계 결정이 아니다.
- H3: 고정 PER/PBR 밴드와 별도3년 배수 분포·시점/과거 품질 검사.
- H4: 기존 interface-design/system 기준 조회·스크리닝·비교·시계열·저장·재열기와 실제 화면 확인.
- H5: 새 일별/incremental refresh smoke, 옛 이력 불변·대표 최신성 확인, 문서·전달 근거 완료.
  실제 투자용 이용 전에 최신 refresh를 검증한다. DCF는 후속 과제다.

검사는 산식·분모0/음수·단위/클래스/분할·세션 gap·future leak·공급자 batch 횟수,
publication 재열기·pin tamper, UI 비동기 전환·미준비 설명, 저장/재열기·옛 기록 보존을 포함한다.
재사용 근거와 새 검사 대상을 구분한다. 수정된 로직·상호작용만 좁게 재검증하고 독립 검토는
전달 절차를 따른다. 관련 없는 full audit·원본 수집을 반복하지 않는다.
공통 입력 계약 이후에만 독립 작업 병렬화를 고려한다. 파일별 한 writer, 최소 Sol 구현자를
쓰며 Astra 자동 위임은 하지 않는다. 독립 검증 역할은 구현자와 분리한다.

## 다음 세션에 붙여 넣을 실행 프롬프트

```text
이 문서 docs/planning/price-related-metrics-goal-handoff-20261116.md를 읽고
가격 관련 지표 전체를 GOAL로 구현해줘. 이번 새 세션에서는 코드 구현·검사·독립 검토와
검토된 변경의 운영 반영·push/PR·필수 CI·main 병합까지 승인한다. 중요한 회계 정책이나
승인 guard 범위 확대는 먼저 설명하고 확인하되, 독립적으로 가능한 작업은 계속해줘.

먼저 AGENTS.md, delivery-workflow와 인계의 관련 계약만 읽고 현재 main/작업 상태 및
운영·저장 기록의 최신 metadata를 좁게 확인해줘. 이전 PID/저장 hash를 현재 사실로 보거나
동시 작업·Q4 UI·새 기록을 덮어쓰지 마. 그 다음 create_goal로 명확한 구현 목표를 시작해줘.
요청하지 않은 token_budget은 설정하지 마. 문서·계획만 만들고 목표를 완료 처리하지 마.

전체 범위는 1/5/21/63/126/252 미국 세션 수익률, 20/60/252 변동성, 최근/20 상대 거래량,
시가총액·PER·PBR·P/S·earnings yield·standardized FCF yield·EV/Revenue·EV/EBITDA,
고정 PER/PBR 가격 밴드와 별도3년 historical multiple percentiles야. PER만 끝내거나
EV·밴드를 조용히 빼지 마. DCF·실시간 피드·매매 엔진·새 대규모 universe는 범위 밖이야.

공통 입력/lineage를 재사용하고 공급자 공식 CanonicalQuery batch를 사용해줘.
가격 통화 UNKNOWN, 클래스·분할·실제 거래일·공시/준비 시점 차이를 무시하지 마.
EPS direct-only와 FY−9개월 EPS 차감 금지는 유지하고, 새 추정은 별도 정의·승인을 받아줘.
현재 고정 가격을 최신가로 표시하지 말고 새 일별/incremental 갱신을 실제 이용 전에 검증해줘.

각 계열의 backend 정의·버전 계산·공통 query와 유효한 스크리닝/비교/시계열/밴드,
명시적 저장·재열기 pin, 의미 있는 단위/통합·대표 실자료·화면 확인과 Git 근거까지 완성해줘.
회사별 미준비는 사유로 남겨도 되지만 계열 미구현을 결측으로 위장해 완료하지 마.
계열 전체가 공급자 입력/정책 때문에 불가능하면 의존성을 구체적으로 질문하고 다른 계열은 진행해줘.
공통 계약 확정 후에만 최소 Sol 병렬 작업을 고려하고 같은 파일 writer는 하나로 유지해줘.
완료 수집·회사 감사·기존 모든 검사를 반복하지 말고 변경/실제 이상에 필요한 검사만 해줘.
마지막에 계열별 구현·실자료 가용성·보류, source/발행물 pin·검사·운영/main 결과를 구분해 보고해줘.
```
