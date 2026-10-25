# 누적 투자자 워크플로 main 통합 인계

## 상태와 범위

사용자는 2026-10-25에 누적 변경을 다음 순서로 검토해 하나의 PR로 `main`에
반영하는 범위를 승인했다.

1. 정확성·복구
2. 스크리닝·명시적 저장·탐색기
3. 50사 확대·회사 설명
4. History 증분 처리·성능 개선

통합 브랜치는 `main` 기준 `201acf9…` 위에 History·증분 계보 `01d8946…`
(145 commits)와 21사 runtime 안정화·명시적 저장·운영 도구 계보 `4dc90a4…`
(공통 기준 뒤 101 commits)를 ordinary 3-way merge한다. 두 계보가 함께 바꾼
`history.py`의 scoped READY reader, recovery guard와 최신 증분 producer를 모두
유지한다. 이 문서는 구현 후보의 전달 상태를 기록하며, 원격 push·PR·CI·main
병합 완료를 선언하지 않는다.

## 통합 보정

Recovery output은 quarter 임시 트리를 정상 제거한 뒤에도 그 경로를 소유권
목록에 남겨 후속 guard가 성공 실행을 거부했다. 통합 후보는 소유한 디렉터리의
identity를 확인하고 제거가 성공했으며 경로가 사라진 경우에만 해당 binding을
해제한다. 제거 실패나 외부 경로 교체는 binding과 외부 경로를 보존한 채
fail-closed로 끝난다. 이 규칙은 일반 History 실행의 삭제 동작을 바꾸지 않는다.

Universe delivery의 작은 가짜 History fixture는 routine validation 도입 전 형식의
임의 bytes였다. 제품 검증을 우회하지 않고 실제 Parquet, version, count와
`json_fields`를 선언하도록 fixture를 갱신했다.

## 호환성과 증거 경계

기준 `main`의 Layer 1 parser v2에서 통합 후보의 v6로 전진한다. Raw SEC 자료는
수정하거나 이관하지 않는다. History 입력은 v5와 v6를 명시적으로 허용하고,
source-binding 및 duration 품질 경계는 각 publication에 기록된 parser와 규칙을
계속 확인한다. v2 Raw를 v6로 재해석했다는 주장은 하지 않으며, 기존 Raw의 후속
사용은 해당 adapter·migration 계약을 통과해야 한다.

이번 병합은 전체 `sec_xbrl` source identity를 바꾼다. 따라서 과거 성능 수치와
독립 검증은 당시 동결 SHA에 대한 증거로만 남는다. 기존 History reuse 또는
migration evidence를 새 code identity로 자동 repin하지 않는다. 새 identity와
결속된 receipt가 없으면 기존 fallback 규칙대로 전체 경로를 사용한다. 기존
운영 runtime과 source pin도 자동 교체하지 않는다.

History 50사 수락, 재무 결과의 수락, 기존 21사 live runtime은 서로 다른 상태다.
코드 통합만으로 재무 준비 완료나 21사 runtime 전환을 선언하지 않으며, 저장된
journal·설정·Raw·publication을 다시 생성하거나 수정하지 않았다.

## 자체 검사

완료 기업 검증과 과거 성능 benchmark는 반복하지 않았다. 통합 후보에서 다음
제한 검사를 수행했다.

- fresh collection: `1904 tests collected`
- recovery source guard: `151 passed`; 이후 test-only fixture 보정 1건 `1 passed`
- recovery 교체·capability 경계: `7 passed`
- screening 저장·CLI·분기 consumer·service·store: sandbox `55 passed`, loopback
  허용 환경에서 socket 경계 `2 passed`
- collection·회사 metadata·universe delivery·회사 설명: 최초 `123 passed` 뒤
  stale History fixture 3건과 loopback 1건을 각각 재검사해 `3 passed`, `1 passed`
- scoped History read, performance event, financial/recovery public API와 direct-worker
  guard의 교차 계보 seam: `7 passed`

전체 clean-runner pytest와 required CI `test`는 PR에서 수행해야 한다. 로컬 검사는
실제 회사 cache, 완료 기업 감사, live journal 또는 네트워크를 사용하지 않았다.

## 남은 전달 단계

브랜치 동결 뒤 별도 읽기 전용 검토를 수행하고, 원격 PR에서 clean full CI를
통과한 경우에만 총괄이 main 병합을 판단한다. 병합 뒤에도 실제 runtime source
전환, 새 receipt 발급, cached data 재생성은 별도 운영 승인과 source-bound 검증이
필요하다.
