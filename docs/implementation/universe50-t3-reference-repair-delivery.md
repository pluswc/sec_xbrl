# 50 issuer T3 참조 무결성 수리 전달 — 2026-10-17

## 결정과 상태

2026-10-17 사용자는 기존
[T3 참조 HOLD](universe50-t3-reference-hold-20261017.md)의 결함을 먼저
수리한 뒤 데이터 확장을 재개하도록 명시 승인했다. 승인 범위는 T3 node/edge
참조 무결성과 해당 producer/reader gate, 좁은 회귀 및 계약 문서다. 상태는
**IMPLEMENTED_CANDIDATE / INDEPENDENT_VERIFICATION_PENDING**이며, 동결 SHA는
구현자 인계와 후속 독립 검증 보고에 기록한다. 실제 CVX, first-five, exact-50
재생성·감사·로컬 인수와 main 병합은 아직 수행하지 않았다.

이 결정은 과거 HOLD와 실패 증거를 삭제하거나 다시 판정하지 않는다. Raw exact-50,
원본 SEC package, source `998ceee…`, 기존 T1–T4/publication, JNJ recovery,
보호 journal과 live UI는 읽기 전용으로 보존한다. 수리 결과는 반드시 새 output과
새 실행 run version으로 재생성한다.

## 마일스톤과 수락 기준

이번 마일스톤은 **T3 reference integrity repair**다. 다음 조건을 모두 만족해야
구현 후보가 된다.

1. observation에서 사용하는 `_concept_node_id`는 실제 발행 `CONCEPT` node의
   `analysis_exploration_node_id`와 같은 공식이다.
2. `analysis_exploration_edge`의 모든 `from_node_id`와 `to_node_id`는 같은 atomic
   publication의 실제 `analysis_exploration_node`로 resolve한다.
3. edge와 endpoint의 CIK는 같아야 한다. edge가 `source_filing_id`를 명시하면 두
   endpoint도 같은 filing이어야 하며, edge가 생략하더라도 두 endpoint가 모두
   filing을 명시하면 서로 같아야 한다.
4. node/edge 중 한 데이터셋만 있는 불완전 graph, dangling endpoint, cross-CIK,
   cross-filing graph는 producer와 공용 `Layer2PublicationReader` 모두 fail-closed한다.
   producer reject는 staging/publication을 남기지 않는다.
5. 정상 cycle, 여러 독립 lens, typed dimension scope와 여러 filing은 계속 허용한다.
   traversal은 기존 per-path cycle termination을 유지한다.
6. concept에서 `TOTAL_FACT`와 `CONCEPT_AXIS_LENS` edge를 실제 node로 따라갈 수
   있다. 값, Raw identity, role/network, axis scope와 lineage는 바꾸지 않는다.

이 gate는 각 row의 nonempty 검사로 대체하지 않는다. 같은 candidate의 두 전체
데이터셋을 교차 검사하되 이미 materialization 메모리에 있는 row sequence를 다시
완전 복사하지 않는다. 디스크의 기존 operational T3를 동일 run version으로
재사용하려 할 때는 public reader가 해당 publication을 다시 검증한다.

## 버전과 재생성 경계

새 producer row는
`exploration_graph_rule_version=analysis-t3-exploration-graph-v2`를 기록한다.
Layer 2 fingerprint의 기존 네 필드는 period, mapping, recast evidence, selection
회계·선택 계약이므로 T3 storage/reference 수리를 표현하도록 오용하지 않는다.
대신 운영 재생성은 새로운 output root basename을 새 `run_version`으로 사용한다.
`Layer2Run.fingerprint`가 run version을 포함하므로 새 T1–T4 실행은 기존 실행과
구분되며, 네 root는 계속 동일 fingerprint를 가진다. 예시는
`CVX-t3v2-20261017` 같은 실행별 이름이며 고정 회사 정책은 아니다.

공용 reader는 graph rule 문자열만 보고 정상적인 legacy v1 graph를 일률 거부하지
않는다. 실제 endpoint와 scope가 완전한 v1 fixture/publication은 호환된다. 반대로
기존 결함 v1 T3는 endpoint가 실제 node에 resolve하지 않으므로 거부된다. 기존
파일은 수정·삭제하지 않는다.

## 구현 범위와 비범위

허용 구현은 다음으로 제한한다.

- `src/sec_xbrl/longitudinal/exploration_graph.py`
- `src/sec_xbrl/longitudinal/materialization.py`
- T3/materialization unit 및 cached integration 회귀
- 이 전달 문서, 계획 등록부, T3·수락 계약 설명

`history.py`, Raw parser/schema, consumer UI, metric/quarter/recast/selection 정책은
변경하지 않는다. 새로운 accounting rule, 자동 filing 선택, 집계, business driver
판정도 추가하지 않는다. 네트워크 수집, 실제 50사/CVX/JNJ payload 실행과 벌크
재생성은 구현자 범위가 아니다.

## 가정과 열린 XBRL 경계

- node/edge의 기존 ID, Raw QName, 값, role, `targetRole`, dimension evidence는
  그대로 유지하며 concept endpoint 공식만 이미 발행되는 node 공식에 맞춘다.
- 오래된 합성 fixture처럼 graph row에 filing metadata가 전혀 없는 경우 기존
  계약대로 허용한다. 일부 scope가 명시된 경우에는 확인 가능한 동일성을
  보수적으로 검사한다.
- cycle은 데이터 오류로 간주하지 않는다. cycle termination은 조회 path에만
  적용하며 graph publication에서 cycle 자체를 제거하지 않는다.
- 이 수리는 T3 참조 완전성만 증명한다. Raw 값, 회계 의미, actual CVX 품질,
  `FinancialREADY` 또는 50사 확장 인수를 증명하지 않는다.

## 검증과 후속 순서

구현자는 unit, 관련 cached integration, Ruff와 `git diff --check`를 실행하고 실제
cache 부재 skip을 구분해 보고한다. 첫 독립 실행은 기존 캐시의 NVDA 2-filing tiny
입력의 새 output에서 수행한다. 제공 intake locator는
`work/universe50_quarterly_20261010/resumption_20261013/independent_source_998ceee/cached-temp/test_default_history_build_con0/intake.json`,
기대 SHA-256은
`575761b6c7ae1e6fe2f855971ae3b1ee889a214225235769a2269426105cb1b7`이다.
기존 tiny T1–T4는 변경하지 않는다.

동결된 구현 후보에 대한 별도 Astra read-only 검증과 tiny PASS 뒤에만 lead가 actual
CVX를 새 output/run version으로 실행한다. 그 뒤 first-five와 exact-50 순으로
재생성·감사·인수한다. 각 실제 실행, 독립 PASS, 로컬 인수, PR/CI/main merge는
서로 별도 상태로 기록한다.

## 구현자 자체 검증

2026-10-17 구현 후보에서 다음을 확인했다. pytest cache plugin은 관리 worktree의
읽기 전용 cache 경계 때문에 비활성화했으며 테스트 의미는 바꾸지 않았다.

- 전체 unit: **1,497 passed / 4 skipped**. skip은 cached seven-company 2건,
  cached NVDA 1건, explicit cached integration 1건이다.
- T3 reference/exploration/materialization 집중 검사: **33 passed**.
- company panel·operational query 및 exploration/company-panel/custom-history/
  history-quarter cached 통합: **14 passed / 0 skipped**.
- 전체 Ruff와 `git diff --check`: PASS.
- 기존 tiny intake 실제 SHA-256:
  `575761b6c7ae1e6fe2f855971ae3b1ee889a214225235769a2269426105cb1b7`,
  계약의 기대값과 일치.

이 수치는 구현자 자체 검증이며 별도 독립 PASS나 actual CVX audit가 아니다.
