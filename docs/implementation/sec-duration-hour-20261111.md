# SEC durhour와 continuation-aware 실패 진단 — 2026-11-11

상태: APPROVED / IMPLEMENTED 후보. 독립 검증·리드 소스 인수·실제 재처리·main 반영은 대기다.
기준 main은 `f46460086ea52a7ad5238ef04b21d528627b6e2c`다.

## 승인 범위와 의미

사용자는 공통 SEC `durhour` 지원 및 continuation을 고려한 실패 진단과,
소스 인수 후 **기존 23건 계획 중 실패한 ISRG 연간 5건만**의 재처리를 승인했다.
이미 수락된 18건과 모든 기존 Raw/분석/사용자 journal을 보존한다. Nasdaq 수집은
별도 운영자가 계속한다. 본 소스 전달에서는 실제 5건 parsing이나 수집·재발행을
실행하지 않는다. 기존 accession discovery, accounting 지표, source binding/
compatibility witness gate, 캐시 정책, Raw 표 schema를 변경하지 않는다.

공개 SEC-staff 기준은 [Arelle EDGAR transform 모듈의 durhour](https://github.com/Arelle/EDGAR/blob/master/transform/__init__.py)다.
정확한 SEC 2015 namespace
`http://www.sec.gov/inlineXBRL/transformation/2015-08-31`에만 등록한다.
기존 strict Decimal lexical parser와 SEC component renderer를 재사용한다.
절댓값의 정수 시간으로 절삭하여 `PT20H`, `PT1000H`, `-PT20H`를 만들고
분/초/일을 추정하지 않는다. 소수 시간은 버리며 절삭 결과가 0이면 부호를 없애
`PT0H`로 쓴다. exponent·comma·word·비유한 수는 허용하지 않는다.
어떤 회사·CIK·concept·특정 숫자 예외도 없다.

소스 확인의 다섯 HTML SHA-256은 다음과 같다. 원본은 수정하지 않는다.

| 연간 source | SHA-256 |
| --- | --- |
| 2021 | `387a3399bff8589ef425e8e25a4f52b44a401978bd7df61457071d087579709d` |
| 2022 | `ff0d34c5e071ca0ea27202466544898517b594f8377aa113d4e4fc434a504443` |
| 2023 | `b6b6e17df00f98463ab66c4d175af04be52b660c5aa36881285b5fa117a40810` |
| 2024 | `8c8ba8ec17aca4427df9ca1b99ce0bf56f9f123072d0528da6f148b299a37d7e` |
| 2025 | `641088f0a3b536403fa4b964d9bae9225848ebd441bfec82220f629b8a128873` |

로컬 상세 조사 `work/nasdaq100-expansion-20261111/ISRG-source-rule-investigation.json`은
선택적 source evidence다. 2022–2025의 `durwordsen` 첫 노드 `one`은 실제로
`continuedAt`으로 ` year`에 이어진다. 전체 lexical은 `one year`이며 기존 문법으로
`P1Y`다. 단독 `one`을 year로 추정하거나 기존 word-duration 문법을 넓히지 않는다.

## 진단·실패 계약

`Layer1Ingestor`의 기존 실패 메시지에만 `fact_diagnostics` JSON을 덧붙인다.
별도 Raw/parse-state schema 필드를 추가하지 않는다. 최대 5개 실패 Fact와
각 문자열 최대 512자로 제한하며 긴 lexical은 `lexical_truncated`를 표시한다.
QName·format은 가능한 경우 Clark namespace를 보존하고 context와 fact ID,
Arelle의 **effective `rawValue`**를 사용한다. 독립 `itertext`나 자체 continuation
재구성·변환을 하지 않는다. 정상 Fact의 lexical을 진단으로 저장하지 않고 정상
적재의 추가 corpus 순회도 없다. 원래 fatal model error code와 실패 gate는 보존한다.

Arelle의 `continuationMissing`, `continuationCycle`, `continuationTarget`,
`continuationChainNested`는 정확한 추가 fatal marker다. 이 네 오류가 있으면
신뢰할 수 없는 chain의 `rawValue`를 읽지 않고
`lexical_unavailable: INVALID_CONTINUATION_CHAIN`을 기록한다. 따라서 오류
진단 자체가 순환 lexical을 따라가지 않는다. 그 밖의 기존 비치명적 경고 정책은
바꾸지 않는다. 미등록 format, 다른 namespace, invalid lexical은 계속 실패하고
snapshot을 발행하지 않는다.

## 버전과 후속 호환 경계

변환 coverage 확장이므로 신규 Raw는 **m2-layer1-v7**이다. 기존 v5/v6 snapshot은
불변이며 버전을 바꾸지 않는다. 정상 history source 재열기에는 기존 same-schema
5/6 자격에 정확히 7만 추가하며 v1–v4·v8 등 미등록 버전은 거부한다.
8개 표·hash·행 수·참조·CIK/accession/filing metadata 검증은 그대로다.

**중요 후속 경계:** `source_bindings.py`의 public mixed-v5/v6 proof allowlist 및
source hash 계약은 이 변경에서 넓히지 않았다. v7 Raw를 이후 해당 public binding/
release 경로로 전달하려면 별도 명시적 qualification/승인이 필요하다. History의
v7 정상 읽기를 downstream gate 전체의 승인으로 해석하지 않는다. 리드에 이
제약을 구현 중 보고했으며 본 범위에서 bypass하지 않았다.

## 자체 검증과 재현

다음은 모두 네트워크 없이 합성 fixture로 수행하는 검사다. 실제 5개 SEC
공시의 Arelle 재적재 성공을 의미하지 않는다.

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_sec_inline_transforms.py tests/unit/test_layer1_ingestion.py tests/unit/test_history_workflow.py -q
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_sec_duration_hour_ingestion.py tests/integration/test_sec_inline_metadata_transforms.py -q
```

첫 focused 단위 검사 578 PASS(1.09초), 신규 정상 Arelle loader 통합 9 PASS(0.56초)다.
기존 metadata loader 통합을 함께 검사한 10개도 PASS(0.61초)이며 변경 Python Ruff와
diff whitespace 검사를 통과했다. 통합은
시간 변환, `ix:exclude`/continuation의 전체 `one year`, 실패 parse-state의
namespace/context/format/전체 lexical, missing/cycle/wrong target 거부를 포함한다.
기존 snapshot에 두 번째 적재를 거부한 뒤 표/manifest bytes와 package hash가
같음을 확인했다. Poison lexical 속성 검사는 잘못된 continuation의 rawValue를
진단이 호출하지 않음을 확인한다. 5건/512자 한도와 기존 v5/v6 재사용·v7 정확
자격·v8 거부도 검증한다. 기존 다른 SEC 변환 결과 회귀는 유지한다.

인계 후 리드는 동결 SHA의 별도 읽기 전용 검증과 소스 수락을 수행한다. 그 뒤
운영자가 exact 기존 23건 계획과 별도 ISRG parent에서 5건만 재처리하고 나머지
18건은 Raw REUSED로 유지한다. 실제 운영 결과·독립 검증·로컬 수락·main 병합은
각각 그 증거가 생겼을 때 갱신한다. 현재 commit/push/main/수집 완료를 추정하지 않는다.

## 독립 FAIL 반환과 진단 corpus 정렬 보완 — 2026-11-11

초기 후보 `33044c59b92687ee470936aed0fcb22d60a0f54a`는 독립 검증에서 진단
ordinal 정렬 P2 FAIL을 받았다. 검증기가 선택한 tuple 제외 corpus와 진단 helper의
원래 model.facts 순서가 달라 정상 Fact의 lexical이 잘못 표시될 수 있었다.
보완은 모든 선택 후 실패 경로에서 **동일한 corpus.facts**를 진단에 전달한다.
선택 전 fatal 오류에서는 동일 select_fact_corpus의 legacy factsInInstance fallback을
사용하며 corpus가 불명확하면 진단만 생략하고 원래 fatal 오류를 유지한다.
검증 gate·변환·Raw 추출 의미는 변경하지 않는다.

Tuple+정상+실패 Fact의 invalid/sentinel/evaluation/early-fatal 경로와 legacy
fallback을 함께 검사한 신규 8개 및 불명확한 corpus의 원래 fatal 보존 1개,
합계 **9 PASS (0.07초)**다. 변경 Python Ruff·diff whitespace도 PASS다.
이전 578 단위/10 통합 근거는 유지하며 이 보완에서 전체 재실행이나 실제 5건
재처리는 하지 않았다. 새 동결 SHA의 독립 검증·리드 소스 인수는 별도 대기다.
