# 기업 탐색 표의 헤더 정렬

2026-11-11 승인. 기준 `4e0dd33327`의 재무 요약·비교 발행 작업을 유지하고,
기업 탐색의 기업명 및 현재 표시 지표 헤더에 정렬 버튼을 제공한다.
연간·분기·TTM 모두 같은 기존 정렬 선택과 실행 경로를 사용한다.
기간과 비교 선택 열에는 새 정렬 의미를 추가하지 않는다.

같은 헤더는 오름/내림차순을 바꾸며, 다른 기업명 열은 오름차순,
다른 숫자 열은 내림차순으로 시작한다. 기존 표시·정렬 드롭다운과 basis별
view state를 맞춘다. native button, 현재 `aria-sort`, 다음 동작 이름과
눈에 보이는 방향 표시를 제공한다. 다시 그리기 직전에 헤더가 활성화되어
있던 경우에만 같은 헤더에 포커스를 복원한다.

`loadExplorer`의 기존 연간 API 정렬, 중간 기간의 정확한 십진 비교·누락값
후순위 및 비동기 소유권/토큰을 재사용한다. query·preset·기간·latest·선택
CIK를 바꾸지 않는다. backend·자료·artifact·원본·계산·저장 기록은 변경하지 않는다.
표시 자산·관련 Node 검사·이 문서와 계획 등록부만 변경한다.

수락 검사는 헤더 토글, 새 키 기본 방향, 드롭다운 상태와 방향 표시,
키보드·포커스, 연간 API 인자 및 분기/TTM의 기존 null·정확한 정렬 유지다.
전체 Node 검사와 Ruff를 실행하고, 리드가 실제 브라우저를 별도 검증한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-11 헤더 정렬 구현 승인 |
| 구현 | `cbd3ac31530c64a04b9a50d451cbffb413227682` 동결 |
| 독립 검증 | 별도 Astra Node 33개·Ruff 통과 |
| 로컬 인수·운영 | 2026-11-11 리드 실제 화면 인수·18765 적용 PASS |
| push·PR·CI·main | 미수행 |

작성자 검사: `node --test tests/screening/*.test.cjs` 80개 통과,
`ruff check .` 통과. 추가한 4개 검사는 상태·접근성 마크업, 분기/TTM
정밀 정렬·누락값·snapshot 재사용, 연간 API 인자, 활성 헤더만 포커스 복원이다.
키보드 실제 동작과 운영 화면은 별도 리드 브라우저 검증 대상이다.

## 실제 화면 인수 — 2026-11-11

운영 구현은 `cbd3ac31530c64a04b9a50d451cbffb413227682`이며 이후 완료 문서
커밋과 구분한다. 작성자 전체 Node 80개와 별도로 독립 Astra의 집중 Node
33개 및 Ruff가 통과했다. 리드는 preview와 실제 18765 화면에서 연간·분기·
TTM 헤더 토글, 숫자 순서·null 후순위, Enter/Space와 포커스 유지,
드롭다운 동기화 및 선택한 AAPL 유지에 PASS를 기록했다. 1464·1024·390px의
화면과 screenshot에서 문서 가로 넘침이 없었다.

첫 브라우저 스크립트는 접힌 표시·정렬 안의 드롭다운을 직접 조작하다
시간 초과했다. 사용자처럼 해당 details를 연 뒤 검사하도록 고쳐 모두 통과했다.
이는 제품 결함이나 제품 수정의 근거로 취급하지 않는다.

당시 frontend PID 52008로 적용했고 backend 19070, bridge, 고정 v2 artifact는
유지했다. Apple·Alphabet·Amazon 매출 계층과 50개 회사의 정확한 v2 응답,
잘못된 범위의 400/409도 통과했다. 변경 전 API History와 최종 응답이 정확히
같았으며 SQLite는 전후 byte-identical이었다. SHA-256:
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`.

선택적 실행 증거는 현재 세션 visualization의 `explorer-header-sort-20261111/`
안에 있다. `live-sort-report.json`, `hierarchy-live.json`,
`live-endpoint-report.json`, `history-final.json`, `journal-after.json`이 실제
검사와 보존을 기록한다. `bundle-hashes.json`으로 자산을 확인하고,
`bridge-growth.json`의 전체 인자를 사용해 기존 고정 bundle을 재시작한다.
`prior.json`은 이전 상태의 기록이다. 리드 로컬 인수와 실제 적용은 완료했으며
원격 push·PR·CI·main 병합은 이 기록 시점에 수행하지 않았다.

## 원격 전달 — 2026-11-11

사용자가 push와 PR을 승인했다. 원격 `codex/financial-summary-readability`에
결합 전달 HEAD `42a5785473649a8e33a1d8054ffd2c9cc7d0086e`를 push하고
[PR #86](https://github.com/pluswc/sec_xbrl/pull/86)을 열었다. 최종 구현 소스는
`cbd3ac31530c64a04b9a50d451cbffb413227682`이며 나머지 후속 커밋은 완료
문서다. 전달 당시 원격 main은 기준 `b1b783d418`에서 변하지 않았고
PR은 OPEN·mergeable이었다. main 병합은 수행하지 않았다.

[CI run 43030529258](https://github.com/pluswc/sec_xbrl/actions/runs/43030529258)은
이 기록 시점에 실행 중이다. 통과를 주장하지 않으며 이후의 최종 결과는
[PR checks](https://github.com/pluswc/sec_xbrl/pull/86/checks)와 PR 본문을 확인한다.
앞선 로컬 전용 상태는 당시의 역사적 기록이며, 원격 전달 상태만 이 항목으로
갱신한다. 실제 운영·자료·기록 보존 인수 결과는 그대로다.
