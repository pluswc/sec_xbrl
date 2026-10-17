# 50 issuer T3 참조 결함과 확장 중지 — 2026-10-17

이 문서는 50 issuer 재무 확대 중 확인된 기존 T3 탐색 그래프의 참조 결함과
lead의 중지 결정을 기록한다. 상태는
**HOLD_FINANCIAL_EXPANSION_PENDING_T3_REFERENCE_DISPOSITION**이다. 이번 기록은
상태·후속 제안 문서화만 승인받았으며, T3 소스 수리, 실제 CVX payload 감사,
재무 publication 재생성, Raw 변경 또는 기존 publication 덮어쓰기를 승인하지 않는다.

## 확인된 결함과 범위

동결 source `998ceee6ab0723b64186fd555587bd25bc8b1dab`의
`exploration_graph.py`에서 concept edge endpoint는
`_id("concept", cik, filing, raw_id)`로 만들지만, 발행되는 `CONCEPT` node는
`_id("node", cik, filing, "CONCEPT", raw_id)`로 만든다. source `1d3a068…`과
`998ceee…`의 관련 파일은 동일하므로 이번 memory 수리에서 새로 생긴 결함이 아니다.

독립 검증자는 cached NVDA 2-filing fresh-build parent의 9개 파일·30,722개
record를 전수 검사했다. `DIMENSION_LENS` 1,307개와 `FACT_SCOPE` 1,485개,
합계 2,792개 edge endpoint가 발행 node ID 집합에 없었고, 서로 다른 누락 ID
788개는 모두 실제 존재하는 concept node와 raw identity가 같지만 위의 다른 ID
공식을 사용했다. 이 결과는 T3 graph의 node-edge 참조 무결성 FAIL이며 Raw Fact,
회계 금액 또는 actual CVX 전체에 대한 판정은 아니다.

finding report는
`work/universe50_quarterly_20261010/resumption_20261013/independent_cvx_history_998ceee/t3_reference_finding_report.json`
(SHA-256 `e46de9bb7925eba709cd166b76d961f38d028f13a3ebfde9c70504d0569fda24`)이다.
lead hold 결정은 같은 evidence root의 `lead_data_expansion_hold_20261017.json`
(SHA-256 `cb19e42f904ee255218c12a4238a082e80a71c2459a08c86414af8e848e9794f`)에,
JNJ component 수락은 `lead_jnj_history_acceptance_20261017.json`
(SHA-256 `b52691a99bb57888882782c3d86d9ffd3602b1dcc940987b00dd5b89dbe93a7e`)에
기록됐다.
선택적 증거 locator이며, 이 파일이 없는 checkout에서도 위 결함과 중지 판단을
이 문서로 이해할 수 있어야 한다.

## 현재 수락과 중지 경계

| 대상 | 2026-10-17 상태 |
| --- | --- |
| Raw exact-50 | 기존 수락 유지: 50 CIK, 1,097 filings. T3 finding으로 Raw를 수정하거나 재분류하지 않음 |
| JNJ recovered History | `998ceee…`에서만 **LOCALLY_ACCEPTED_ACTUAL_JNJ_RECOVERED_HISTORY_ONLY**. 독립 77-job audit가 complete record 248,518개와 derived record 242개를 PASS; report SHA-256 `1c2039abfa5c20f2725cd632a5a678d47d1ff0ab89bf49d2109359821fbc8209` |
| JNJ T3·재무 준비 | 위 component 수락은 full T3 graph upstream truth, annual/standalone-quarter metric 또는 `FinancialREADY`를 뜻하지 않음 |
| CVX fresh History 후보 | process exit 0, 383.507초, sampled peak 3,181,904 KiB/16 GiB guard, 61개 operator file hash inventory, 10 tables와 176 derived records. operator report SHA-256 `bc6e5a7cb0ef127e521e968e40879d4c1611166290c1d080e5d076719cf5cbc8` |
| CVX 독립 판정 | parent tiny 준비 단계에서 FAIL. actual CVX payload는 **NOT_ACCESSED**, actual audit는 **NOT_EVALUATED**; CVX `HistoryREADY`를 선언하지 않음 |
| first-five·50사·native | 모두 `FinancialREADY = false`, native-50 ready = false, 확대 중지 |
| main·원격 | main `201acf9aec2f8183acb7dd843579938db14236cd` unchanged; PR·CI·merge 없음 |

동결 source `998ceee…`와 보호된 journal SHA-256
`fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c`는
변경하지 않는다. 별도 UI explicit-save/reopen 수리 source
`d81a15940cef967282a6c9011552cc85ddb88d45`의 독립 검증은 병행할 수 있지만,
그 결과는 원본 financial snapshot의 품질 수락 근거가 아니다.

## 다음 결정 제안 — PROPOSED / 미승인

1. 같은 raw identity와 기존 회계 의미를 유지하면서 concept edge endpoint와 실제
   발행 concept node의 ID 생성을 일치시키고, 모든 발행 graph의 cross-file endpoint
   존재 검증을 추가한다.
2. 새 rule/source version과 새 output에서 별도 독립 검증자가 cached tiny 회귀를
   먼저 수행한다.
3. tiny PASS 뒤에만 actual CVX를 새 output으로 재생성·감사하고, 이어 first-five와
   exact-50을 순서대로 재생성·인수한다.

위 순서는 제안일 뿐 구현·실행 승인이 아니다. Raw 재다운로드, 기존 publication의
in-place 수정·덮어쓰기, 검증 완화는 허용하지 않는다. 각 단계의 구현, 독립 검증,
local acceptance와 main merge는 계속 별도 상태로 기록한다.
