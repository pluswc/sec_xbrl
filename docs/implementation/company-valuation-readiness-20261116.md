# 기업별 가치 지표 준비 확대 — 실행 계약, 2026-11-16

## 목적·승인·현재 단계

목적은 기존 가격 지표 엔진을 재사용해 실제 PER/PBR 등 조회 가능한 기업을 늘리고,
가격일 이후로 낡은 재무 cutoff가 남은 경우 필요한 공시 준비를 정당한 소스에서 갱신하는 것이다.
사용자는 준비된 자료 우선 재사용, 필요한 준비 갱신, 원본·저장 이력 보존, 실제 API/UI,
별도 Sol 독립 검증, 운영 및 PR/필수 CI/main 전달까지 승인했다. 완료는 계획·숫자상 cutoff
변경이 아니라 새로 준비된 회사/지표의 실제 값과 입력·판단 근거로 측정한다.

초기 CV0 계약/기계 목록을 ROOT가 수락한 뒤 **CV1 재사용 자격·후보 추출과 CV2 회사별
최신성/신규 준비 자격 접점 구현**을 승인했다. 각 회사의 실제 재사용/새 준비 자격과
회계 역할은 별도 ROOT exact receipt가 필요하다. 현재는 소스 `41f02a63a4f5bde464a32003896e06be7bd69ab9`와
최종 v2의 **별도 Sol 독립 PASS·ROOT 로컬/운영 인수 완료** 상태다. 실가치 조회는86회사,
PER9회사/PBR75회사이며 [109회사 읽기표](company-valuation-availability-20261116.md)에
실제 값·원 선택일·보류 사유를 기록했다. PR/필수 CI `test`/main 병합은 이 인수 기록 시점
아직 미수행이다. 아래 초기 proposal/v1 기록은 당시 상태이며 최종 결과와 구분한다.
작업 기준은 main
`365cce90f8a4b016dcc2574ab50042531c309df5` (PR104 포함), branch
`codex/company-valuation-readiness`, 전용 worktree
`work/company-valuation-readiness-20261116/source`다. 이전 구현/운영 worktree는 보존한다.

[전달 절차](delivery-workflow.md)에 따라 승인, 구현, 독립 검증, 로컬/운영 인수,
main 병합을 구분한다. ROOT는 회계·클래스·검토된0·분할·최신성 승인, 공식 네트워크
수집과 운영/원격 전달을 소유한다. 사용 가능한 GPT-6.1 Sol 단일 writer가 허용된
소스/문서/테스트를 수정하며, 독립 Sol은 별도 읽기 전용 역할이다. 추가 구현자는 만들지 않는다.

## 착수 시점 baseline과 입력

| 구분 | 기존 상태 |
| --- | --- |
|109회사 기본18765 |실제 가격2026-10-23, 재무 cutoff10/25; MSFT만 PER약29.22/PBR약8.81 등10가치 지표 준비 |
| 제한2회사18766 |AAPL/MSFT 실제 가격11/13; AAPL 적용 scope 미승인, MSFT 재무 cutoff10/25로 최신 가치 지표 차단 |
| 기존 financial-input-bundlev3 |48관측/13grant, 전부 MSFT의 정확한 승인 scope |
| common109 |13,549보고 입력,109회사,132증권 후보; 금융 cutoff2026-10-25 |
| latest direct12m diluted EPS assessment |12회사:11양수/LITE음수; 값 존재 자체는 class/share-basis 승인 아님 |
|4direct-QTD EPS 진단 |HON/ABBV 후보, share basis 미확인; 추정 TTM 승인 아님 |
| AAPL/NVDA/GOOGL |최신 financial anchor에 직접12m EPS gap; 오래된 FY값으로 채우지 않음 |

12개 직접12m 후보는 ADP/KLAC/MU/MSFT/CSCO/INTU/CPRT/COST/STX/PANW/LITE/SNDK다.
이는10/25 고정 입력의 관측이며 최신11/13 준비 또는 경제적 적합성 인증이 아니다.

필수 입력은 다음 기존 불변 자료와 원천 선언이다. 파일·해시를 새 산출물에 참조하고
이미 끝난 전체 Raw/History/회사 감사를 반복하지 않는다.

- `data/processed/market_inputs/20261114_common109/market_input_manifest.json`,
  SHA256`a1b1c8c3e29c92e5fdb2aaf1534dd4024a847b72b31936131f5df5899322ee58`;
  financial_inputs와 회사별 annual/quarterly Analysis/intake pins를 재사용한다.
- common109 assessmentv2 manifest,
  SHA256`ec827bfa25a21b336416e0a2673f69394dd9b9cd2c5a1ce0e88281b1ef2c93fa`;
  latest financial anchor, 직접 EPS와 class/header 후보 진단을 재사용한다.
- 기존 financial-input-bundlev3,
  SHA256`12a5e7ac2db12e7b1a09aa50b77c8e80b995463bffbe7dfb2d9a4ea1f62c3fc7`;
  MSFT48관측/13정확한 승인과 이전 증거는 다시 만들지 않는다.
-109가격 publicationv3 manifest,
  SHA256`1fc3fcfaf96ec6960ac2f8f778ba280bdad001bb9b9e8eb19ec8b470394c400a`,
  fresh2 manifest SHA256`107b39a2ea6c6481733f3817e0a54cbdfd3cfb1a7808fad783b57d0fb511ec7d`;
  공급자 batch/통화/세션/실제 날짜 참조는 해당 승인 계약을 따른다.
- 기존 scope/EV/직접 EPS/기록 재열기 규칙은
  [가격 지표 실행 계약](price-related-metrics-20261116.md),
  [공통 입력 계약](price-common-inputs-20261114.md),
  [입력 handoff](metric-input-handoff.md), [기간 규칙](period-rules.md),
  [Analytical 모델](../architecture/analytical-data-model.md)을 따른다.
- 운영/새 공시 준비 전 ROOT의 현재 상태·journal·원본/발행물 pin 보존 snapshot이 필요하다.
  이전 PID/hash를 최신 상태로 가정하거나 옛 backup으로 복원하지 않는다.

## 단계와 수락 기준

| 단계 | 산출물·수락 조건 | 현재 상태 |
| --- | --- | --- |
| CV0 읽기 전용 조사 |공통 입력 및 선택 Analytical metadata로 회사별 역할 후보/기간/차원/단위/결측·정책 의존성 목록; 정책/후속 범위를 ROOT에 제안 |109회사 조사/후속 범위 ROOT 수락, 추가 기업 조사 종료 |
| CV1 기존 준비 재사용 |exact 후보 IDs/보고 사실/기간 및 class/currency/split/scope 근거를 binding/grant로 연결; 실제 값과 보류 사유 측정 |최종87회사 current binding; CRM book-only를 제외한86회사 실제 가치 지표, PER/PBR 중 하나 이상76회사. PER9/PBR75 실제 검증 |
| CV2 가격일에 맞는 재무 준비 |필요한 공시/준비·소스 자격 검증 후 새 as-of/anchor 확인; 숫자만 cutoff 수정하지 않음 |42회사 source25 재사용+65회사 신규 filing source13+2회사 기존 Raw 재준비 source13,109회사 exact readiness ROOT 수락 |
| CV3 실제 소비자 경로 |불변 별도 발행물과 기존 공통 reader/스크리닝/비교/시계열/밴드/근거·명시 저장/원본 재열기; API/UI에서 대상 기업 실제 값 검증 |최종v2 2834행의 실제 HTTP/reader 동등, 실제 기업 화면·비교·과거기간·old3/new2 사적 저장/원본 재열기·export·cold restart PASS |
| CV4 전달 |별도 Sol 독립 PASS, ROOT 로컬/운영 인수·보존 확인, PR/필수 CI/main 실제 결과를 분리 기록 |별도 Sol 최종 PASS 및 ROOT 로컬/18765 운영 인수 완료. PR/필수 CI `test`/main은 별도 원격 전달 미수행 |

최종 cohort/회사별 수치 목표는 CV0 근거 뒤 ROOT가 확정한다. 자료가 준비된 기업까지
모두 보류하거나 MSFT 하나의 기존 값만 재확인한 것으로 확대 완료를 선언하지 않는다.
새로운 숫자가 가능한 경우와 Raw는 있으나 적용 scope가 미승인인 경우, 최신 공시 준비가
필요한 경우, 현재 direct12m 입력이 없는 경우를 구분한다. 각 지표의 baseline/변경 후
가용 회사 수·새 실제 회사·기간·입력 provenance 및 정당한 미준비 사유를 보고한다.

## 추출 seam과 미결정 사항

기존 `project_financial_inputs`와 assessment는 EPS/실제·가중평균 shares를 구분한다.
`project_additional_candidates`는 선택 Analysis의 named standard QName VALUE cells와
필요 trace shards만 읽고 후보를 만든다. `bind_financial_inputs`와 `bind_bundle`은
정확히 승인된 선언·원천 ID·단위/차원/기간과 receipt를 확인한다. 가격 producer/reader/
worker를 회사별로 다시 만들거나 ticker 분기로 확장하지 않는다.

초기 가용성 목록은 선택된 node/cell metadata와 이미 발행된 공통 입력을 사용한다.
이는 보고 사실·단위·전체 차원·날짜·가치 적용 범위의 최종 검증이 아니다. 필요한 trace
확인과 제한된 원문 증거는 ROOT가 우선 cohort/정책을 확정한 뒤 그 범위에서만 수행한다.
같은 latest end의 여러 역할/차원/클래스는 모두 후보로 보존하고 첫 행을 고르지 않는다.

ROOT 확정이 필요한 핵심은 최신 financial anchor를 기준으로 한 후보 절단,
common equity와 total/NCI/preferred 포함 자본의 구분, 실제 common shares의 클래스·자기주식
범위, 주당 분할 기준, 직접 EPS 및 기존 governed TTM 경로, 최신 금액 기간/TTM 준비,
EV 부채/금융리스 포함 중복과 명시적 preferred/NCI0 및 operating D&A scope다.
코드의 표준 QName 후보 allowlist는 common-equity/EV 의미 승인 자체가 아니다.

## CV0 측정·초기 정책 제안 — 2026-11-16 역사 기록

109회사의 기존 선택 annual/quarterly VALUE node/cell metadata와 공통 EPS/share 입력을
한 번씩 읽어 현재 assessment financial anchor와 끝이 같은 후보6,692개를 모았다.
소요34.4초는 이 로컬 조사 실행의 관측이다. trace shard/Raw를 다시 읽거나 재무 panel을
재생성하지 않았다. 모든 새 후보는 `metadata_only=true`, `trace_validated=false`,
`binding_approved=false`다. QName allowlist에 없거나 차원이 다른 입력은 이 목록에서
빠질 수 있으므로 빈 역할을 Raw 공시 부재로 해석하지 않는다.

직접 양수12m EPS11회사는 모두 같은 anchor의 양수 자본과 undimensioned actual-share
metadata도 있다. LITE는 직접 EPS−92.96을 보존하며 양수 PER 대상에 넣지 않는다.
단순 양수 book 후보는71회사지만 common-equity/class/split 승인이 아니다. 나머지38회사에는
같은 anchor의 undimensioned actual-share 후보가 없는35회사, 자본 비양수8회사,
named undimensioned direct equity 후보가 없는3회사가 중복 포함된다. 다른 날짜의 cover
shares, class 차원 또는 custom QName을 별도로 검토할 여지가 있다.

ROOT는 기존 SECSubmissionsClient/불변 snapshot/FilingRef 경로로109회사 root JSON의
2026-10-25 이후부터11/13까지 recent window를 확인했다. 모든 회사에서 window 시작을
포괄하며65회사는 미처리 신규 공시1개,44회사는 추가 공시0개다. 이는 해당 최신성 window
증거이며 전체 과거 공시 수집 완료를 뜻하지 않는다.

| 구분 | 재사용 우선 후보 | 적용 전 필요한 판단 |
| --- | --- | --- |
| 추가 공시0개44회사 중 양수 직접 EPS6회사 |MU, CSCO, INTU, CPRT, COST, PANW |정확한 class/EPS basis·actual shares·분할·통화·source scope 및 verified-through 승인 |
| 추가 공시0개 중 단순 양수 book metadata28회사 |ADI, AMAT, TGT, GE, IBM, UNP, WDC, CSX, DE, HD, MU, CTAS, PAYX, ROST, NEE, HON, ADBE, FAST, CSCO, SNPS, INTU, CPRT, COST, ISRG, NFLX, TSLA, PANW, AVGO |EPS와 독립적으로 common equity/actual shares 또는 직접 BPS 경로 검토 |
| 신규 공시1개65회사 중 기존 양수 직접 EPS5회사 |ADP, KLAC, MSFT, STX, SNDK |신규 공시의 anchor 반영 전 기존 FY EPS를 최신값으로 승격하지 않음 |
| 신규 공시가 있는 대표 예외 |AAPL 새10-K, MSFT 새10-Q, LITE 음수 EPS |ROOT가 필요한 공시 준비 범위를 정한 후 별도 자격 검증 |

CPRT의 선택 자본 후보는 NCI 포함 자본뿐이므로 그대로 common equity로 바인딩할 수 없다.
KLAC의 자본/NCI 포함 자본 값이 같아도 NCI0으로 승인하지 않는다. CSCO/PANW에는
assets/liabilities/common capital/retained earnings/AOCI의 reconciliation metadata가 있으나
전체 범위·원문·trace 검증 전 검토된0이나 common-equity 승인으로 쓰지 않는다.
기존 governed TTM revenue/FCF 경로는 별도 재사용 대상이다. 이번 direct-cell 목록의
FY/TTM 후보 수만으로 그 경로의 가용성을 부정하지 않는다.

제안하는 최신성 seam은 기존 `source_selection_as_of=2026-10-25`와 새
`verified_through=2026-11-13`을 분리하는 것이다. 기존 projector는 원래 cutoff로 호출하고,
추가 공시0개 window receipt·기존 소스 완전성·anchor 불변·정확한 소스 pins를 ROOT가
승인한 후에만 별도 준비 자격으로 사용한다. manifest cutoff 일치 검사나 가격일 guard를
완화하지 않는다. 이 분리 seam은 CV0 제안 뒤 ROOT가 구현을 승인했으며, 각 회사의 실제
자격과 회계 역할은 exact receipt 전까지 승인되지 않는다.

후속 좁은 추출에는 기존 projector의 anchor/cell-ID 사전 필터를 검토할 수 있다.
현재 모든 과거 후보의 trace를 읽는 기본 경로를109회사 현재값 준비에 반복하지 않도록
선택한 cells의 필요한 trace만 읽는 방향이다. 기존 binder는 역할 간 동일 period_end를
요구하므로 다른 날짜의 cover shares를 섞는 정책은 별도 결정이 필요하다. 첫6회사에는
anchor의 share 후보가 있으므로 그 문제를 먼저 확대할 필요는 없다.

작업 산출물은 새 work 폴더의 선택 metadata, 회사 cohort, 예외 및 discovery 교차표다.
원천 선언·후속 재현에 필요한 기준은 위 계약과 아래 pins이며 work 파일이 규범은 아니다.

| create-only 조사 파일 | SHA256 |
| --- | --- |
| `proposal/selected-role-metadata-v1.json` |`350dddb033a2b52021a560f76adb7211ae36bc50bf2728adb6dc41b29164c27c` |
| `proposal/company-cohort-v1.json` |`a194601b3d11f90e8db392c6dc8d3027d79ba42d8c47057626f2843a9bbf4e1e` |
| `proposal/summary-v1.json` |`b753ba32146e1fa6d19f42c7193ea04a519923d8238508eeb79c72d5784551d0` |
| `proposal/cohort-and-exceptions-v1.json` |`8afa9b8138ddc16b0f00a035a6609d10b91dc4865e2fc53ae38dc516d477e49f` |
| `proposal/cohort-discovery-crosswalk-v1.json` |`90c32c15bee059b135f0a2861544d5d5fb0d9307e3bd2469f41ceb1cd5217dc8` |
| ROOT `discovery/manifest.json` |`b03c624443e7a6477494a7c5790068b0377cac45347d121d4f441460ccdda57d` |

위 경로의 기준은 `work/company-valuation-readiness-20261116/`다. 초기 CV0는 소스 코드,
단위 테스트, 기존 입력/receipt/journal 및 운영 상태를 변경하지 않았고 commit/원격 전달을
수행하지 않았다. 다음 CV1/CV2 기록이 이후 승인된 구현 범위를 설명하며 실제 역할 binding은
별도 ROOT 검토를 기다린다.

## CV1/CV2 초기 구현·pilot — 2026-11-16 역사 기록

`company_valuation_readiness`는 후보 추출과 구분되는 준비 자격 helper다.
`propose_reuse`는44개별 receipt와 원 discovery root JSON, baseline intake complete,
CIK/ticker, recent window 범위, 새 financial filing 부재, 최신 filing/anchor 및 기존
Analysis cutoff10/25를 검증한다.65delta는 명시 제외한다. `accept_reuse`는 정확한 proposal
pin과 `approved_ciks` 부분집합을 ROOT가 `APPROVED_FOR_EXACT_REUSE`로 승인한 receipt를
요구하고 원 pins에서 proposal을 재검증한다. 출력은 class/common-equity/EPS/분할 승인과
독립적이다.

`propose_fresh`는 신규 단일 filing 준비 cohort에 대해 기존 등록109 CIK/ticker,
discovery window의 정확한 새 filing, delta ingest complete/INGESTED, Raw의 단일
`filing.parquet` metadata와 Layer1 manifest, History plan/source identity/CURRENT_FOCUS,
Analysis source hash/cutoff/최신 anchor를 연결한다. Raw facts·과거 panel 전체를 재감사하지
않는다. Raw의 form/공시일/report date/primary document/DEI fiscal year/분기와 package
hash도 서로 맞아야 한다. 기존 annual manifest의 `period_mode=ANNUAL`과 quarterly의
명시적 `quarter_source_evidence`를 각각 검증한다. 기존 native/backend 승인 상속을 거부한다.
정확한 `APPROVED_FOR_EXACT_FRESH_PREPARATION` ROOT receipt 전에는
`PROPOSED_FRESH_PREPARATION`이며 price plane에만 한정한다.

두 receipt의 schema는 `company-valuation-readiness-acceptance-v1`이며 `reviewer=ROOT`,
해당 status, 정확한 `proposal` path/SHA256 pin, 중복 없는 비어 있지 않은 `approved_ciks`가
필요하다. 기존44는 source selection10/25와 verified-through11/13을 분리하며, 새65는
source selection13/verified-through13이다. 승인 boolean이나 cutoff 숫자 변경만으로
회사 준비를 통과시킬 수 없다. 서로 겹치지 않는 accepted 자료는
`company-valuation-readiness-set-v1`의 `readiness_pins`로 합칠 수 있고 중복 CIK는 거부한다.

`project_additional_candidates`의 optional `anchor_end`/`cell_ids`는 trace shard 읽기 전에
대상을 줄인다. 지정 cells는 모두 해소되어야 하며 생략 시 기존 전체 기간 동작과 cutoff/
trace selection guard를 유지한다. ROOT가 허용한 treasury 금액/수량·common/preferred
issued 수량 QName도 보고 후보로 추가했다. issued 단독을 actual shares로 쓰지 않는다.
기존 EPS/share는 공통 발행물의 정확한 원 행/ID를 재사용하고 새 filing도 같은 projector를
사용한다. 직접12m 없는 새10-Q에서 오래된 FY EPS나 FY−9m EPS를 만들지 않는다.

28회사 후보 v1은1,623개(직접 보고 검사 통과1,566/조건 미충족57), 소요21.1초였다.
새 허용 QName을 포함한 v2는 별도 생성했다. 6회사 compact source proof는187개 원 행과
exact observation/fact/filing/snapshot/context ID·단위·차원·기간을 포함하지만 적용 승인은
아니다. 실제 직접 EPS는 MU74.33, CSCO3.33, INTU16.46, CPRT1.55, COST20.76,
PANW0.40이다. actual-share 예외35회사에서는 같은 anchor의 class-dimensional BS shares
후보20회사, 같은 기간/차원/source filing/단위의 issued/treasury 쌍 후보10회사를 찾았다.
이 집합들은 겹치며 수량 차감·클래스 합산·다른 날짜 cover shares 혼합은 하지 않았다.

새 준비 pilot은 AAPL/QCOM/SBUX/MSFT4회사로 자격 proposal 및224개 source 후보를
생성했다. 직접 FY diluted EPS는 각각 AAPL8.98/QCOM12.70/SBUX2.21이며 MSFT 신규
quarter에는 직접12m EPS가 없다. 첫 자격 실행은 기존 quarterly manifest에 annual과 같은
period_mode가 없어서 실패했고, 명시된 기존 quarter evidence를 검증하도록 caller adapter를
수정한 뒤 동일 config로 통과했다. 원 준비 파일은 변경하지 않았고 실패 시 proposal은
생성되지 않았다. 이 pilot은 전체65회사 준비/회계 승인/운영 완료 증거가 아니다.

bundle의 optional `company_readiness`는 exact accepted 자격·typed source pins/공시 지식일과
최신 anchor를 검증한다. publisher는 해당 CIK만 검증된 through date를 cutoff 인수로
전달한다. 없는 회사는 기존 source financial_as_of10/25를 유지한다. 기존 엔진의
class/anchor/cutoff/기간 검사와 정의는 그대로다. `dataset_scope`는 기존109 parent dataset
locator로 보존하고 manifest/query/capability의 별도 `company_financial_readiness[CIK]`에
source_selection_as_of/verified_through/financial_anchor/readiness_id/status를 노출한다.
과거 불변 결과·저장 재열기는 현 producer 규칙으로 수치를 재계산하지 않는다.

현재 자체 검사77개 PASS는 새 자격/source/filter/서로 다른 회사 cutoff 통합 검사와 기존
price calculation/publication/공통 입력 회귀를 포함한다. 합성 두 회사의11/13 publication에서
승인된 회사만 PER50, 다른 회사는 `FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF`였고 global
cutoff와 parent dataset locator10/25를 보존했다. 실회사 역할 승인·발행·운영과 독립 검증은
아직 미수행이다. commit/push도 수행하지 않았다.

재현 CLI는 프로젝트 Python3.12에서 `PYTHONPATH=src`와 함께 실행한다. config/proposal/
receipt 인수는 절대 path와 SHA256이다. 모든 출력은 create-only다.

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/screening/test_company_valuation_readiness.py \
  tests/screening/test_company_valuation_fresh_preparation.py \
  tests/screening/test_price_related_metrics.py tests/screening/test_price_metric_publication.py \
  tests/screening/test_market_inputs.py
PYTHONPATH=src .venv/bin/python examples/screening/prepare_company_valuations.py propose-reuse \
  --config ABS_CONFIG --sha256 CONFIG_SHA256 --output NEW_PROPOSAL
PYTHONPATH=src .venv/bin/python examples/screening/prepare_company_valuations.py project \
  --config ABS_CANDIDATE_CONFIG --sha256 CONFIG_SHA256 \
  --evidence ABS_REUSE_PROPOSAL --evidence-sha256 PROPOSAL_SHA256 --output NEW_CANDIDATES
```

새 준비는 위 command를 `propose-fresh`/`project-fresh`로 바꾸고 해당 fresh schema config를
사용한다. `accept-reuse`/`accept-fresh`는 config 인수에 정확한 proposal pin, evidence 인수에
ROOT receipt pin을 받는다. reuse config에는 공통 manifest/assessment rows/discovery manifest
pins, candidate config에는 원 공통 financial_inputs pin과 tickers가 필요하다. fresh config에는
같은 등록 common/discovery 및 delta intake execution manifest pin과 개별 execution/intake/
history_manifest/raw_manifest/raw_filing pins의 preparations 목록이 필요하다. fresh candidate
config는 준비된 cohort에서 고른 tickers를 지정한다. 전용 worktree에서는 부모 `.venv`의
절대 Python 경로를 사용할 수 있으며 `PYTHONPATH=src`로 해당 worktree를 선택한다.

| 추가 create-only proposal | SHA256 |
| --- | --- |
| `proposal/reuse-qualification-proposal-v1.json` |`2168cb12478ba7aca0b27d367ce21c6d478648138d6909b545dbfdd33a873593` |
| `proposal/reuse-financial-candidates-v2.json` |`8f3e769999ea831b1bf0e151ad2ad35fc92362e884c73c869d25d277c585b66e` |
| `proposal/six-company-source-proof-v1.json` |`2653bdd6c329a5a1c47faae89230c99522e5aa99ca044a0044630359762798c3` |
| `proposal/share-scope-followup-v1.json` |`ed01bc2d49a4a333fefaf09b994c54310b430bfa3422c8a818f84c4673b6b51d` |
| `proposal/fresh-pilot-qualification-proposal-v1.json` |`290b3db5407bee3c7d6d8a614dd1ce53d004ab80bdb76b3accf028067dd99730` |
| `proposal/fresh-pilot-financial-candidates-v1.json` |`37eb195f4f2664f32522c66b194bb2f99d80791a8a9716f4b2d5b34b3fa37d19` |

## 금지와 허용 경계

- Raw와 보고 값을 덮어쓰지 않는다. collector를 재작성하거나 전체109 SEC 감사/전체 panel을 재생성하지 않는다.
- EPS direct-only와 FY−9개월 EPS 차감 금지, current financial anchor·공시/실제 준비/가격일 구분을 유지한다.
- 오래된 FY EPS를 최신 TTM처럼 쓰거나 일괄 status=approved, cutoff 숫자 변경, old native/source guard 자동 상속을 하지 않는다.
- WAVG/issued/free-float를 실제 자기주식 제외 common shares로 대체하지 않는다.
- 결측 preferred/NCI/debt/cash를0으로 바꾸지 않고 EV/영업이익+D&A proxy 정의를 유지한다.
- 공급자·이전 source/worktree/runtime/config/journal/발행물/원래승인·지침·skills·interface system을 수정하지 않는다.
- 허용 변경은 이 계약/등록부, company readiness helper/준비 CLI, 기존 financial 후보
  projector의 제한/허용 QName, 승인된 bundle/publisher/service metadata 접점과 관련 검사 및
  새 work 폴더의 create-only proposal이다. writer의 network·운영·원격·commit/push는 금지다.

## Producer 동결 전 확정 계약 — 2026-11-16 v1 역사 기록

ROOT의 최신성/역할 검토로 current83회사 역할 선언을 수락했다. 이는 엔진에서 수치가
실제로 나오는 회사 수나 이번 운영 인수를 뜻하지 않는다. 전체109회사 가격은 별도 새
공식 SDK snapshot을 한 번 수집해 한 번 CanonicalQuery batch로 채택한다. ROOT 보고
capture940,031행과 batch109,218행은 원 supplier history와 bounded consumer query의
서로 다른 크기다. 기존 가격/금융 입력·발행물·journal·native source guard는 수정하지 않는다.
공식 full-history refresh이며 incremental API나 supplier의 독립 인수를 주장하지 않는다.

최종 재무 readiness는42회사 재사용,65회사 신규 단일 filing,2회사 기존 Raw 재준비다.
기존44 재사용 전체 조사 중 LRCX/PG는 현재 anchor의 선택 cells가0개였지만 Raw는 이미
존재했다. ROOT가 각 latest Raw1개를 새 intake/History/Analysis로 준비했고 Raw 자체를
재수집/수정하지 않았다. 두 회사의 실제 Raw DEI FY2027Q1을 사용해 이전 Analysis 연도
준비 gap을 해결했다. 기존109 금융 backend/일반 기업 상세의 승인을 상속하지 않는
price-plane 전용 준비이며 현재 금융 화면의 source/cutoff locator는 그대로다.

이 경로는 config에 `preparation_kind=EXISTING_RAW_LATEST_ANCHOR`를 명시해야 한다.
추가 assessment pin과 기존 `_verify_window`에 준하는 새 공시0개/anchor 불변 증거,
baseline intake의 정확한 latest filing/원 source_run, `REUSED/new_filings=0`, 동일 Raw
filing metadata/package hash를 요구한다. 기존65 new-filing 경로는 `INGESTED/1`을 유지하며
이 opt-in으로 default 검사를 완화하지 않는다. helper는 원 source25를 덮어쓰지 않고 새로
선택한 Analysis13의 source/검증일을 별도로 기록한다. historical system-ready 인증도 아니다.

역할 제안 helper는 ROOT가 지정한 exact 값/IDs/산식/범위만 기존 binding-proposal schema로
전개한다. 새 회계 역할을 ticker로 추론하지 않는다. 각 source ID/QName/값/단위/전체 차원/
실제 기간/공시일/fact/filing/snapshot/context와 review pins를 보존한다. annual/quarterly
alias는 이 source identity 전체가 같은 경우에만 annual을 우선한다. 다른 fact/QName은
동일 값이어도 alias로 합치지 않으며 ROOT가 확인한 primary BS/IS/CFS의 정확한 consolidated
source를 선택한다. INTU 매출은 이 검토로 `us-gaap:Revenues`를 선택했다.

새 proposal의 pinned candidate pool은 bind 시 한 번 읽고 ID index를 cache한다. 승인된
pool의 원 행과 공급된 flat 행이 완전히 같아야 하므로 ID만 유지한 값/QName/lineage 변조를
거부한다. 옛 proposal schema와 과거 불변 결과를 현 producer로 재해석하지 않는다.
reviewer proof의 임시 `/tmp` pins는 동일 bytes의 durable evidence 복사본으로 별도 v2에
repin하고 선언/소스 값·IDs 동등성을 확인했다. 원 v1은 보존했다.

actual common shares의 알려진 issued/WAVG QName DIRECT 오용을 차단하되 검토된 custom
QName을 일괄 금지하지 않는다. issued-minus-treasury는 정확한 수량 순서·같은 filing/
instant period/단위/원 전체 차원일 때만 허용한다. net이라고 확인된 MELI actual shares나
repurchase가 이미 share column에서 빠지는 KLAC/CDNS SOE balance에는 treasury를 다시
빼지 않는다. 반대로 BKNG의 QName Outstanding1618m는 실제 issued column이므로 쓰지 않고
명시 issued1618m−treasury872m를 사용한다. IBM은 static12b의 등록 Capital stock과 정확한
945120805 common-outstanding을 검토했으며 rounded issued2300m−treasury1355m로 대체하지 않는다.

common-equity는 ROOT가 검토한 common-only subtotal/owner equity 또는 명시 source 차감
경로만 허용한다. CPRT/QCOM/AVGO의 including-NCI QName 자체가 common-equity 의미나
EV NCI0을 보장하지 않는다. 해당 source의 실제 전체 capital 구성을 검토한 정확한 범위만
연결한다. GILD13040m/GE17522m처럼 검토된 reporting precision 차이는 원 보고 총계를
보존하며 엔진에 자동 tolerance/총계 보정 규칙을 만들지 않는다. SBUX/ORLY/HONA/MCD/LOW/
BKNG의 음수 book도 입력 원값을 보존하고 PBR/BPS의 비양수 분모 정책으로 처리한다.

다음 잔여 제약은 Raw 부재나 해당 지표 엔진 미구현으로 표시하지 않는다.

| 구분 | 이번 처리·제약 |
| --- | --- |
| WMT/ADSK/NVDA/KLAC/CDNS 등 class-dimensional actual shares |원 차원 그대로 cap/PBR 연결; issuer equity와 차원이 다른 PER_SHARE는 보류 |
| issued-minus-treasury actual shares |cap/PBR 독립 연결; 계산된 중간 shares를 분모로 쓰는 nested BPS는 현재 binding 산식 범위 밖 |
| CAT |total21482m−명시 NCI(−1m)=common21483m; 계산된 common-equity를 재사용하는 nested BPS는 미선언 |
| DUK |cap만 연결; owner55377m−classA preferred973m은 검토된 범위 변환이 필요해 common-equity 보류, scope guard 유지 |
| MCHP/LITE/PG/MRVL preferred scope |0par 또는 일부 capital 구성만으로 common-equity/EV zero를 승인하지 않음; 준비된 actual shares는 독립 사용 |
| CRM |common-equity38378m만 준비; same-anchor actual shares 미준비, 뒤8/20 cover shares 대입 금지 |
| ORCL/MRVL actual shares·복수 class·CSX 수량 충돌 |각 회사의 적용 범위/실제 수량 문제로 보류하며 빈 입력을0/첫 행으로 대체하지 않음 |
| 신규10-Q EPS/12m flow |직접 현재12m 부재를 이전 FY 분모나 FY−9m EPS로 채우지 않음 |

원문으로 명시된 preferred/NCI currency0 DIRECT가 exact ROOT source 승인을 받은 경우에만
`evidenced_zero=true`, `zero_evidence_kind=REPORTED_ZERO`를 남긴다. derived0/결측은 이 경로가
아니다. 이전 `EVIDENCED_ZERO` 레코드에는 새 필드를 일괄 추가하지 않아 old48 관측의 형태/
ID를 보존한다. 새 AAPL/MSFT EV의0은 보고0이 아닌 전체 book-capital reconciliation의
검토 residual이며 `reporting_precision=MILLION_USD`,
`zero_kind=REVIEWED_RECONCILIATION_RESIDUAL_NOT_REPORTED_ZERO`로 별도 기록한다.

EV는 기존 승인 정의를 유지한다. AAPL debt는 이미 current/noncurrent 합인 term78114m에
CP1997m와 별도 finance lease1456m를 한 번 더해81567m, cash36305m다. CP의 un-dim carrying
1997m와 class-dimensional face2000m를 구분한다. MSFT debt35481m+별도 finance70973m=
106454m, cash20281m다. operating lease는 제외하고 financing은 선택한 reported carrying
basis임을 밝힌다. preferred/NCI0은 같은 complete common-capital scope의 검토 residual에
한정한다. 최신 MSFT12m/새 D&A scope를 만들지 않으므로 없는 EV/Revenue 또는
EV/영업이익+D&A proxy 분모는 보류한다. 이 proxy를 통상 EBITDA로 이름 바꾸지 않는다.

새 query/capability는 기업별 원 선택일/검증 through date/실제 report date를 따로 제공하고
가격 화면에 가격 기준·기업별 재무 확인·기존 금융 화면 기준을 구분한다. 데이터 수치 계산은
backend에서만 한다. old publication에 `company_financial_readiness`가 없으면 새 빈 metadata,
query dataset_scope/reopen source_context/export source_context를 추가하지 않는다. old 저장
payload·정의·메모·원 source pin·내보내기 schema를 그대로 유지하고 active 새 날짜를 원본에
상속하지 않는다. 새 저장/내보내기만 새 source context를 포함한다.

동결 전 자체 검사는 Python96 PASS/Node12 PASS/Ruff9개 Python 파일/diff 검사다.
이는 합성/격리된 로컬 source 검사이며 새109 실발행·실제 API/UI·독립/운영 수락은 아니다.
PER/PBR/cap 예상 수는 완료 기준으로 고정하지 않는다. ROOT 실발행 뒤109회사×지표의
available/unavailable·정확한 이유·음수 분모·미승인 scope·binding 산식 제약을 실제 측정한다.
writer가 수정한 정확한 파일을 ROOT가 commit해 producer를 동결한 후 실자료·소비자·독립
검증과 기존 데이터 보존을 대조한다. PR/필수 CI `test`/main 결과는 이후 실제 상태로 기록한다.

현재 ROOT 입력 승인 pins는 다음과 같다. 경로 기준은 이 작업의 `evidence/`이며 이 표가
Raw/회계 수치 전체를 대체하지 않는다. 소스 선언·상태·제약은 위 계약으로 이해할 수 있어야 한다.

| ROOT exact 수락 자료 | SHA256 |
| --- | --- |
| `readiness-set109-v2.json` |`5e29170340c09447b102f9f771a501d2e90ae10fede139ec9c0d94ec65a987e1` |
| `ten-company-binding-acceptance-v1/manifest.json` |`0256f2f0f33a11b86b2f514849438226731981b48e530b2496827582a46c03e5` |
| `fresh40-binding-acceptance-v1/manifest.json` |`4811ec8d09a882ed084070dde29b533b8c397689f7fbf21813ee4b795cdd3bd8` |
| `reuse26-binding-acceptance-v2/manifest.json` |`82863e14709fdb9ba2a2a1decb88cd76b31277974662c135c3cf9190041f650a` |
| `remaining6-binding-acceptance-v1/manifest.json` |`317794af95ba310a42cb64ec3822e2bb782c826e759566c5266616f3f1c60024` |
| `ev2-binding-acceptance-v2/manifest.json` |`782b933d327da6255818259c67647ae0312e096282229c782e8ab32e690e0540` |
| `ibm-binding-acceptance-v1/manifest.json` |`98741b000a51d0be21c0481aa1f564a254806bc9ed7db09b564f75023f2c263c` |

## 최종 v2 독립·로컬·운영 인수 — 2026-11-16

이 절은 앞선83회사/v1·미발행·인수 대기 기록 이후의 실제 상태다. 소스는
`41f02a63a4f5bde464a32003896e06be7bd69ab9`로 동결했다. Python producer는 첫 동결
`53fcdbe440810d04d0c9733cd1244476c5c0b01a`와 byte 동일하며41f 변경은 가격 UI와 과거
시계열 caption 회귀 검사뿐이다. 현재 financial anchor caption은 발행물 price_as_of와
행의 날짜가 같을 때만 표시한다. MSFT10/23 PER의 FY6/30 근거에 현재9/30 기간을 붙이지 않는다.

ROOT는 실회사 matrix와 이미 준비된 후보를 마지막 대조해 PYPL/KHC/ALAB/ABBV4회사의
누락 연결을 v2로 추가했다. 신규 조사/Raw 수집/소스·정의·테스트 변경은 없었다. PYPL net
837m/common equity19483m, KHC net1184m/owner35975m, ALAB174752000/1999468000은
shares/book/BPS 각3역할이다. ABBV는 exact issued1844582836−treasury77073558=
1767509278과 원 negative owner−4583m의2역할이며 nested BPS를 만들지 않았다.
PYPL/KHC의 treasury를 이미 net인 actual shares에서 다시 차감하지 않는다. KHC의 NCI102m와
redeemable13m를 common-equity로 포함하거나 EV0으로 바꾸지 않는다.

중간 v1은83current binding/cap82/PBR72/BPS57,1319가용/1515미준비였으며 최종 수치와
구분한다. 최종 financial bundle은322관측/100grant(87current+13원 MSFT historical)다. v1의 기존
311관측/96grant와 그 안의 원48 MSFT 관측은 그대로다. v1/v2 사이105회사의525개 파일
descriptor/hash/bytes/rows가 같고4회사의20개 파일만 바뀌었다. 28정의·공유 price batch·세션·
readiness도 그대로다. 추가4회사가 제공한10개 실제 값까지 독립 검증했으며 기존83회사
검증을 새로 전체 재실행하거나 v1을 덮어쓰지 않았다.

최종 발행물은 `data/processed/price_metrics/20261116_company109_valuations_v2/price_metric_manifest.json`,
ID `screening-price-metrics-d5e6c94177ccec71918629ec`, SHA256
`9774ca17e449cc484da809dece739eba0da1f08655b52a9a616ebfa5677f9f03`다. actual price11/13,
요청11/16,3calendar-day 차이의 고정 자료다.109×26=2834행 중1329 AVAILABLE/1505 UNAVAILABLE다.
87current binding 중 CRM은 book-only이므로 하나 이상의 실제 가치 지표가 있는 회사는86,
PER/PBR 중 하나라도 있는 회사는76이다. source readiness109와 역할/수치86을 혼동하지 않는다.

| 현재 가치 지표 | 실제 가용 회사 수 | 범위·제약 |
| --- | ---: | --- |
| 공시 보통주 수 기반 시가총액 |86 |실제 일별 유통 주식 수 측정값으로 이름 바꾸지 않음 |
| PER |9 |AAPL, MU, QCOM, SBUX, CSCO, INTU, CPRT, COST, PANW |
| PBR(common cap/common equity) |75 |음수 book/미승인 범위/미연결 입력은 분리 보존 |
| 가격/BPS |60 |원 차원 또는 nested binding 제약은 별도 경로 보류 |
| P/S |9 |최신 anchor의 승인12개월 매출 |
| earnings yield |9 |승인된 직접12개월 EPS 경로 |
| 표준화 FCF yield |7 |기존 CFO−PPE 정의 유지 |
| EV |2 |AAPL, MSFT의 정확한 current financing/cash/검토 residual0 범위 |
| EV/Revenue |1 |AAPL. 최신 MSFT12개월 매출 대체 없음 |
| EV/영업이익+D&A proxy |0 |공통 코드/조회는 구현됨. 현재12개월 기간·operating D&A scope 승인 부족 |

[109회사 표](company-valuation-availability-20261116.md)는 원 matrix의 PER/PBR/별도 BPS
경로·cap·선택일·실제 재무기간·보류를 읽기용으로 표시한다. PBR이 양수지만 BPS만 보류된
15회사는 원 차원5(ADSK/CDNS/KLAC/NVDA/WMT), 복합 binding10(ABT/CAT/COP/CVX/GEHC/
JNJ/KO/MRK/PCAR/TXN)이다. 자료가 없거나 공통 BPS 엔진이 미구현인 것으로 표현하지 않는다.

가격10지표도 새 공유 batch에서 실제 조회했다.1/5/21/63-session return,20/60-session
volatility 및 relative volume은 각각109회사,126-return104회사,252-return/volatility는
각101회사다. 검증된 US session gap/완전 창 규칙을 유지한다. 사용자 fixed PER/PBR band는
각9/60회사에서 가능하며 원 배수와 입력/정의/source pins를 명시 저장한다.

MSFT의 과거 PBR 두 경로는754/754 eligible sessions, 중앙값(P50)
`10.90338128415986488516302005224456`이다. 제출일 가정 진단이며 backtest_eligible=false다.
과거 PER은64/754로 최소252세션에 못 미쳐 미제공한다. 이는 이전 고정 source의 PER62 또는
H5 fresh2의 PBR739/754와 다른 window/source 준비 결과다. 새 Q가 알려진10/28 이후 옛 FY
EPS를 replay하지 않았고 AAPL 새 FY는 실제 공시11/03부터만 쓴다. historical system-ready
시간을 filed date로 채우거나 이 진단을 준비 시점 인증으로 제시하지 않는다.

별도 Sol의 최종 PASS는 소스/실v2/사적 consumer 증거를 대상으로 한다.96 focused Python과
24 actual Node(가격 UI13+공통 market5+Q4 6), Ruff9 Python/JS syntax/diff 검사를 통과했다.
독립 검증자는109×10 가치 결정과 모든258개 가용 현재 값을 Decimal로 대조했고, point-in-time
대표 시계열/quantile·545 v1 파일 및 v2 delta를 확인했다. 완료된 capture/기존 원문 검토를
재사용했으며 모든87회사의 모든 Raw fact를 다시 감사했다는 뜻은 아니다.

브라우저는 ROOT가 직접 실행했다. 독립 검증자는 실제 HTTP2834개 row 객체·정의/source/
날짜/readiness의 reader 동등성, ROOT 브라우저 receipt/스크린샷과 SQLite를 읽기 전용으로
대조했다. 실제4회사 비교의16개 값, AAPL/NVDA PBR, 최신 MSFT PER 미준비, SBUX 음수
book, 원 기간 caption을 확인했다. 사적 복사본에는 old3 fixture와 명시적으로 저장한 new2가
있으며 cold restart 전후 전체5 SQL 행·메모·정의/source·old/new export bytes가 같다.
oldA의10/23 quote524.510009765625/EPS17.95/밴드201.9375는 원 source로 유지되고 newB의
AAPL11.25×8.98=101.0250은 별도 context로 재열린다. 새 metadata를 old export에 추가하지 않았다.

ROOT는2026-11-16T06:14:18Z에18765의 최종 v2를 운영 인수했다(그 시점 frontend PID30276).
실제 HTTP2834행/정의와 NVDA 화면을 확인했다. backend19078/qualified d1e/native14datasets,
원 legacy 및 price journals·원 발행물/common/assessment의6보호 pins, 기존18766의 old2
제한 view는 exact 보존했다. 운영 journal에 테스트 저장은0건이다. 사적 저장 시험을 운영
사용자 journal의 신규 행으로 기록하지 않는다.

| 최종 근거 | SHA256 |
| --- | --- |
| `company-valuation-independent-final-41f02a6.md` |`286aed756d858416f928a62d389db435e2ddd74f39eb826b59f02e376c3fd2c2` |
| `root-operating-acceptance-v2.json` |`28835680ac250c05f2073f2212af5a6047bc411b8788a62b5f9bab9e30fa3463` |
| `private-consumer-acceptance-v2.json` |`e27eff8cd82b4f92b7127de96345985ef5f4a449a443eb4b8b87406098631b59` |
| `company-availability-109-v2.csv` |`ee3e967c002e2d415c6ee2ac0dd971cbecfb3faa40a739833e29225e3c6c0550` |
| `company-availability-109-v2.json` |`101143d9e4a477d1ec64afcd9548afd563212a6ddbb43a37c760659002502811` |
| 최종 financial bundle |`81a405ea2cc03dbdae513b4efffd06bdf8b1abb92c48b49f74356505e637eda6` |

위 파일 경로는 이 작업의 보존된 evidence/발행물에 있다. 이 문서는 **독립·로컬·운영 인수
시점**의 기록이다. 이번 docs-only 갱신은 source/Python/JS/tests/정의/Raw/운영을 바꾸지 않으며
완료된 source/data/consumer 검증을 재사용한다. PR 생성·필수 CI `test`·main 병합은 아직
미수행이며 최종 원격 상태는 이후 실제 PR/CI/Git 기록으로 별도 확인한다. 운영 수락이나
이전 PR104 병합을 이번 GOAL의 main 병합 성공으로 대신하지 않는다.
