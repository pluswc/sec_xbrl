# 데스크톱 분석 우선 워크벤치 — 1차

2026-11-13 승인. 기준 `d5324d381b`의 실제 인수 UI·매출 완전성·간결한 날짜를
보존한다. 단일 구현자와 별도 독립 검증을 유지한다. 이번 단계는 탐색/기업 상세/
기업 비교의 1차 표시·조작 개선이다. 2·3차 제안(지표 안내·이력·스크리닝 재설계 등)은 제외한다.

## Interface-design checkpoint

투자자의 작업은 목록에서 후보를 고른 뒤 재무 수준·변화를 바로 비교하는 것이다.
기존 ivory/paper/ink/slate/annotation blue, 4px 기반 8/12/16px 간격과 native
controls를 유지한다. 목록은 상태를 가진 작업면이며 삭제/재조회하지 않고 접는다.
분석은 목록 요약/복귀와 기업 전환을 가까이 두고 첫 화면을 차트 쌍에 할당한다.
반복 요약은 접을 수 있게 하고 full name·단위·누락/비교 보류·정확한 근거는 보존한다.

## 승인 범위와 경계

- 상세/비교를 열면 목록을 접고 분석으로 이동한다. 목록 복귀는 dataset/basis/
  latest/fixed/query/preset/sort/direction/선택 CIK와 matrix의 수직/수평 스크롤을
  유지한다. 삭제된 trigger는 기존 검색/비교 버튼으로 안전하게 복귀한다.
- 목록은 남은 viewport 높이를 활용하며 표준/촘촘한 행 밀도를 제공한다.
- 주요 8개 값의 원래 노드를 기본 닫힌 details로 보존한다. 재무 카드는 금액 위/
  전년비 또는 %p 아래 쌍을 유지하고 FCF처럼 이미 정한 짧은 표시명 ‘표준화 FCF’는 full title과
  접근성 이름을 동반한다. 카탈로그/재무 의미를 새로 정의하지 않는다.
- 비교 지표는 검색·카테고리 체크·선택 chip 삭제로 제공한다. 검색은 필터이며
  선택을 바꾸지 않는다. 원래 native select는 숨은 adapter로 정의/선택을 보존한다.
  회사 2–4개, 전체 기존 지표, actual period·기준과 기존 API 정렬/계산을 유지한다.
  선택 변경 직후 이전 비동기 token을 무효화하고 자동 비교한다. 0개 지표와
  부적절한 기업 수는 설명하며 오래된 성공/실패가 새 화면을 열거나 덮지 않는다.
- 비교 차트/표를 근접 배치한다. 차트 제목·단위/readout 위치, 긴 범례의 전체명·
  고정·키보드·resize/Escape를 보존한다. 동일 기업의 동일 FY 문구 중복만 정리한다.
  기준일·공시일·실제 기간, ISO title과 펼친 원천 근거는 변경하지 않는다.
- `.interface-design/system.md`를 현행 동작에 맞춰 저장한다. 고정 21사·한 지표
  차트 등 과거 설명을 현재의 데이터 기반 회사 수·다중 보드와 구분한다.

허용은 system.md, app.js/app.css, 관련 tests/screening, 이 계약과 planning이다.
backend·artifact·계산·저장 기록·main·원격·운영 프로세스는 변경하지 않는다.
브라우저에서 새 재무 계산/기간 추론을 하지 않는다.

수락: 1920×1080의 첫 차트 쌍이 첫 화면, 1440×900에서 가능한 3열,
1920/2560의 읽을 수 있는 4열, 125/150%에 대응하는 effective viewport와
390px 기본 기능 보존이다. 실제 browser zoom 검증과 equivalent CSS viewport
검증은 증거에서 구분한다.
목록 복귀·기업 전환·비교 선택·stale success/error·고정 설명·근거·기존 보드/
헤더 정렬·기록을 검사하고 전체 Node/Ruff 후 별도 실제 브라우저·독립 검증한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-13 1차 표시 구현 승인 |
| 구현 | `d19638fae378a4ef91764d4e291bf0ed3b33958f` 동결 |
| 독립 검증 | 별도 읽기 전용 Node 108개·Ruff PASS |
| 로컬 인수·운영 | LOCALLY_ACCEPTED 2026-11-13 · 18765 실제 적용 PASS |
| 원격 PR·CI·main | 미수행 |

작성자 검사: 전체 `node --test tests/screening/*.test.cjs` 108개 및
`ruff check .` 통과. 새 8개 행동 검사는 원래 목록 trigger/수직·수평 scroll·검색/
정렬·CIK 보존과 fallback, filtered/sorted 기업 순서와 늦은 실패 차단, 비교
검색/카테고리의 선택 불변·닫힌 picker chip 삭제 후 보이는 포커스, 0개 선택/
닫힌 화면의 오래된 성공·실패 차단, debounce/즉시 token 무효화·기업 수 경계,
동일 회사 FY 중복/표시 alias, 활성 기업 전환 실패의 선택기 복원과 비교 기업
칩 삭제 뒤 인접한 보이는 포커스를 확인한다.
현재 요청의 실패는 분석 바에 설명하고 기존 표시 기업 자료를 유지하며, 이전
요청의 실패는 현재 화면을 덮지 않는다. root의 실제 브라우저·확대 대응 측정과
독립 검증·운영 인수는 별도로 기록한다.

## 최종 로컬 인수 — 2026-11-13

검증·운영 소스는 `d19638fae378a4ef91764d4e291bf0ed3b33958f`이며 이후
완료 문서 커밋과 구분한다. 별도 독립 검증은 Node 108개·Ruff를 통과했다.
리드는 별도로 live desktop 8개 폭, interaction 5개 그룹과 race 5개 그룹을
확인했다. 기업 칩 제거의 인접 포커스, 현재 실패의 선택기 복원과 안내,
닫기/새 상세·비교 진입의 이전 오류 초기화도 포함한다.

1920×1080에서 표준 목록의 완전히 보이는 행은 8→12개, 재무 카드 위쪽은
957.21875→483.828125px, 첫 growth plot 아래쪽은 1348.53125→878.828125px다.
1440×900은 3열이며 첫 차트 쌍이 약 879px 안에 들어갔고 1920/2560에서는
4열을 유지했다. 125/150% 대응은 equivalent effective CSS viewport 검사다.
실제 브라우저 zoom은 검증하지 않았으며 두 종류를 같은 측정으로 주장하지 않는다.
390px의 기본 조작과 가로 넘침, 날짜/전체 이름 접근성도 실제 검사에 포함했다.

기존 날짜 24개 context, 재무 workbench 10개 그룹, screening 7개 그룹,
연간/분기/TTM 정렬, 50개 회사 endpoint의 정확한 결과와 잘못된 scope의
409/400, 매출 4개 경우가 모두 통과했다. 18765는 당시 새 PID 27800으로
적용했고 backend 19070은 유지했다. History API는 변경 전과 같고 SQLite
bytes도 같다. SHA-256:
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`.
기존 매출 artifact `db71131a…d53b231`과 financial growth artifact
`a9df827e…f62938` 및 고정 경로를 변경하지 않았다.

선택적 실행 증거는
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/desktop-first-phase1-20261113/`의
`local-acceptance.json`과 `live*` 보고서다. 독립 소스 검증과 리드의 실제
브라우저·운영 인수는 구분한다. 이 작업의 원격 push·PR·CI·main 병합은
수행하지 않았다. 2·3차 제안은 이 완료 기록으로 구현됐다고 주장하지 않는다.

## 원격 전달 승인과 최신 main 통합 — 2026-11-13

사용자는 push와 PR을 명시 승인했다. 원격 병합은 승인 범위가 아니다.
`origin/main`의 `72575d89f578d6c0ae01528753d06a469141a1b3`를 일반 merge
`1dfc42b3b04cc3b9ea826afcb22f5ff1328d232b`로 통합했다. 충돌이 없었고,
통합 tree는 직전 로컬 인수 문서 HEAD `ee1bb723cd95947fb77e0b6fbee691df2207bf42`와
정확히 같다. upstream 매출 변경은 이미 포함돼 있어 UI·계산·backend 변화가 없다.

인수된 실행 소스 `d19638fae378a4ef91764d4e291bf0ed3b33958f`의 UI 자산은
그대로다. JS SHA-256은 `802bef69a263758269181179fa794148ac8a77e2229aabdceea2955045e1eb0b`,
CSS는 `6be818971561405eb3f33d943ae8967b94b4264ca1d6900656b82e066e118f7a`다.
이 통합의 별도 독립 재검증과 원격 push·PR·CI는 기록 시점에 대기다.
작업 브랜치를 main에 병합하거나 운영·자료·기록을 변경하지 않았다. 앞선
로컬 인수와 당시 원격 미수행 문구는 역사적 기록으로 보존한다.

## PR 전달 상태 — 2026-11-13

통합 전달 HEAD `bf91b303eac3df2f256dffa4c377457ed55ecdec`는 별도 독립
Node 108개·Ruff·diff, 최신 main 포함 및 인수 UI 동일성 검증을 통과했다.
리드가 push하고 [PR #91](https://github.com/pluswc/sec_xbrl/pull/91)을 열었다.
PR은 OPEN이며 main에 병합하지 않았다. 원격 CI는 기록 시점에 진행 중이고,
최종 근거는 [PR #91 최신 head checks](https://github.com/pluswc/sec_xbrl/pull/91/checks)다.

리드는 실제 운영 JS/CSS가 기존 인수 hash와 같고 History API가 baseline과
정확히 같음을 재확인했다. SQLite SHA-256도
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로 같다.
앞선 로컬 전용/전달 대기 문구는 당시 기록이며 이 항목이 원격 전달 상태를 갱신한다.
