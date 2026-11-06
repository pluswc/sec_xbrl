# 2026-11-07 공통 기준100 추이·선택 usability 계약

## 승인·범위·상태

사용자는 실제 금액/기준100 전환과 선택→해제 등 일반 사용성 기준의 검토를 요청했다.
ROOT는 아래0/음수 정책을 먼저 설명하고 구현 범위를 확정했다. 기준 main은
`485fe940f8ecdc1aa9d2aeafe7be098a97dc6246`, branch는 `codex/indexed-trends-usability`다.
제품은 companion app.js/app.css뿐이며 focused tests/docs만 동반한다. Python119/bridge/
backend/API/verifier/packet/data/catalog/journal/지침은 변경하지 않는다.

구현·자체 focused 검사와 ROOT preview는 완료했다. 새 동결 SHA의 독립 검증·소스 인수·
18765 전환·PR/CI/main은 별도 대기다. 이전 PR71/main485/live41024 완료와 구분한다.
이번에 승인한 것은 **비저장 Display 정규화**이며 기존 계약의 ‘indexing 없음’은 이전
scope의 기록이다. Governed metric/TTM/저장 값·조건/CSV/XLSX 계산 정책을 추가하지 않는다.

## 명시한 정책과 사용자 표시

기본값은 AMOUNT다. INDEX100의 공통 기준은 선택 end window 안에서 **모든 선택 기업의
AVAILABLE/nonblocked raw value가 엄격히 양수인 최초 동일 FY/calendar 좌표**다.
기업마다 실제 재무 날짜가 같다고 가정하지 않는다. 회사별 다른 기준 시점, epsilon,
절댓값 분모나 일부 기업 제외로 기준을 만들지 않는다.

`각 값 / 각 기업의 공통 기준 좌표 값 × 100`을 decimal string/BigInt로 half-up 처리한다.
지수는 소수2자리이며 음수 tie는0에서 멀어지고 negative0은0.00이다. 기준의0/음수는
나눗셈·부호 역전 문제 때문에 허용하지 않는다. 이후의 실제0은0.00, 음수는 음수 지수,
missing은 gap이다. 기준 이전 point는 숨기지만 원금액은 details 표에 남긴다.

공통 양수 기준이 없거나 선택 기업 조회가 실패하면 설명과 함께 **실제 AMOUNT**를
유지한다. Control/axis/table 단위도 AMOUNT이고 INDEX label 아래 금액 축을 두지 않는다.
BASE caption과100 reference/0 tick을 표시한다. Raw cached observation.value는 바꾸지
않고 별도 display model에만 plotValue를 둔다. Mode flip/resize는 fetch0이며 AMOUNT로
돌아오면 원래 금액이 그대로 보인다. Index tooltip/table에도 금액·날짜/FYQ를 유지한다.

Native hooks: `#comparison-trend-scale`의 AMOUNT/INDEX100, `#comparison-trend-base`,
`#comparison-trend-retry`, `#comparison-trend-reset`. Reset은 매출+AMOUNT만 복원하고
basis/end/선택 기업/조건·저장 결과는 유지한다. Retry는 성공 cache를 쓰고 실패만 다시 읽는다.

## 선택 전이·상태·접근성

Checkbox/chip/remove/clear는 `transitionExplorerSelection` 하나를 사용한다. Chip label은
pinned explorer registry에서 가져오며 현재 filter나 과거21 저장 run의 S.companies/catalog에
의존하지 않는다. `#explorer-selection-tray/list/count/status`, chip의
`data-remove-explorer-cik`, `#explorer-selection-clear`, `#comparison-selection-clear`가 hooks다.

0/1은2개 필요를 설명하고 compare를 비활성화한다.2~4를 허용하며5번째는 해당 시도만
rollback하고 기존4-company chart/cache는 유지한다. Clear0은 idempotent이고 모든
checkbox/선택/옛 chart/matrix를 지우며 API/save가 없다. Filter에 숨은 기업도 chip에서
해제할 수 있다. 유효한2~4 선택 변경은 열린 panel의 trend만 갱신하고 matrix에는
‘기업 선택 변경·표 다시 조회’를 표시한다. 자동 다중 metric 조회는 하지 않는다.

Close/Escape는 선택을 유지하고 사용할 수 있는 compare button/search로 focus를 돌린다.
Clear는 선택을 지우며0이면 search로 focus를 옮긴다. Async/resize는 focus/scroll하지 않는다.
기존 ledger palette/14·11px type/4px rhythm/SVG/native controls와 PR70 owned READY guard는
유지한다. Token+exact context에 현재 scale을 적용하여 late close/selection/metric/period
응답이 옛 view를 다시 그리지 않는다. Raw/model과 화면 단위를 섞지 않는다.

## UX 수락 matrix — 발견·조치·근거

| 일반 기준 | 구체 발견과 이번 조치/의도적 예외 | 확인 근거 |
| --- | --- | --- |
| 역동작 쌍 | Filter 밖 선택 해제/전체 해제, Escape, chart reset/실패 retry가 부족했다. Chip/clear·close·reset·retry를 같은 기존 흐름에 추가 | 신규 selection/inverse/reset/retry tests, ROOT7 scenario groups |
| 왕복 불변 | AMOUNT→INDEX→AMOUNT 원금액 불변/fetch0. Annual/Q/TTM state와 기존 guide/profile 유지 | 신규 raw roundtrip/metamorphic tests + 기존 explorer 회귀, 실제 roundtrip |
| 상태 일치 | Checkbox/count/chip/button/chart가 갈라지지 않게 단일 전이와 READY 조건 사용. Hidden 선택 label은 pinned registry | 신규 filter/4→5/refresh/focus tests, 실제 filtered/remove/clear |
| 경계·조합 |0/1/2/4/5, 양수/0/음수/missing, partial/allfail·공통 기준 없음에서 임의 대체 금지 | 신규 policy/selection cases, 별도 browser policy fixtures4 |
| 멱등·변형 | Clear 두 번, mode fetch0, 공통 BASE 모두100, 양수 동일배율로 raw를 확대해도 지수 동일 | 신규 exact/metamorphic/clear tests |
| Async·회복 | Close/clear/selection/mode 변경 중 응답 소유권, partial retry는 실패 기업만 | 신규 in-flight/latest-scale/retry tests, 실제 partial failure retry1GET |
| 키보드·responsive | Native select/details/buttons, Escape/focus,1024/390 table/chart 제약 유지 | ROOT actual keyboard/mobile + 최종 READY/focus3 checks |
| 기존 counterpart 점검 | Detail close/Escape·focus trap, criteria expand/collapse/새 조건은 이미 존재하여 보존. History는 추가 기록/다시 열기이며 삭제는 승인 범위 밖 | 기존 source read-only 대조, 보호된 workflow 회귀·과거 saved21 실제 재열기 |

이는 임의 삭제 기능을 덧붙이는 일반 checklist가 아니다. 발견된 선택/비교/차트 쌍만
보완했으며 이력의 append-only 정책과 기존 화면 의미는 유지한다.

## 검사·preview·전달

```bash
node --test tests/screening/screening_indexed_trends_usability.test.cjs
python -m pytest -q -p no:cacheprovider tests/test_screening_display_assets.py
```

신규10 + 기존26 = **Node36 cases**, pytest wrapper **1 PASS**다. Lint/syntax/diff PASS,
main 대비 Python119/bridge 변경 없음이다. 기존 source/금융/회사 audit/발행·backend 검사를
반복하지 않았다. Protected threshold/execute/save/open/export는 그대로다.

ROOT의 초기1b7738b4/CSS78a54d26 preview는 실제7 criteria groups/5 screenshots PASS,
errors0/GET-only/journal API deep-identical이다. 실제 금액 왕복/fetch0/reset/Escape,
filtered chip/clear/0·1,4→5 보존/4→3 갱신, 실제 FCF 음수/index/raw,TTM/mobile과 저장21을
확인했다. 별도 policy fixtures4는 common BASE25Q1/이전 억제/이후0·-50, allnegative/zero
fallback과 partial failure retry1GET을 확인했다. Fixture 그림을 실제 재무 관측값으로
기록하지 않는다. 근거는 Windows visualizations `indexed-trends-usability-20261107/`의
`browser-uat.json`, `policy-fixture-uat.json`이다.

마지막 READY/focus 보완 뒤 JS는
`1173a29c4fe49d476054cf8d6e97e9b277c5c991b96b53b48324d278be34fbbc`, CSS는
`78a54d26929c9727660d59f289a296b75551fa88c20c1689fd7baddc94a33f7b`다.
최종1173의 targeted actual3 checks도 PASS다: pending FY2024 +3→2 해제 중 compare는
READY까지 disabled, Escape는2개 선택/focus 복원, 두 clear는0개/search focus를 확인했다.
`final-guard-uat.json`, `06-final-indexed-guard.png`가 근거다. 초기 actual7 groups/fixture4는
1b77 근거를 재사용했고 반복하지 않았다. 독립 소스 인수와 합치지 않으며 별도 Sol review는
ROOT가 담당한다.
동결 뒤 ROOT만 exact assets의 frontend 전환·PR/CI/main을 수행하고 backend245090과
원본 데이터/journal을 유지한다. Writer는 추가 운영·원격 작업을 하지 않는다.
