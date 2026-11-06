# 2026-11-06 기업 탐색 연간·분기·TTM 보기 전달 계약

## 승인과 현재 상태

최신 repair 상태: source336은 basis switch continuation의 stale-render race로 독립
FAIL했다. 아래11-06 repair는 해당 post-await ownership만 보완한 후보이며 관련
Node12 PASS다. 새 동결 SHA의 독립 검증·ROOT 인수는 대기다. 기존 실제12 visual/
4 guard 근거는 보존하고 다시 실행하지 않았다.

사용자는 기업 둘러보기의 연간·분기·TTM 전환과 기업 비교를 요청했고 기존 연간 기능·
저장 기록 보존 및 기존 기능 재사용을 승인했다. ROOT가 확정한 최소 범위는 companion
`examples/screening/display-assets/app.js`, `app.css`와 관련 focused tests/문서다.
기준 main은 `588198b8c4f1a5e369f578c6b38b64de389ab277`, branch는
`codex/explorer-period-basis`다. Python119, bridge, 금융 verifier/packet, API/서버,
데이터/catalog/journal, 지침과 운영 process는 writer가 변경하지 않는다.

구현·자체 focused 검사는 완료했다. ROOT가 preview의 실제 API/화면을 검증했으며
독립 검증·최종 소스 인수·18765 운영 전환·PR/CI/main 반영은 별도 대기다.
이전 Display PR69/main/live 완료와 이번 새 기능의 상태를 구분한다.

## UI 의도와 기존 기능 경계

투자자가 같은 기업을 다른 재무 기간으로 읽고 비교하도록 기존 탐색 표에 native
`보기 기준`과 의존적인 기간 필드만 더한다. 표가 focal surface이며 ledger ivory,
filing-paper/ink/slate/blue,14px body·11px metadata·4px 간격과 기존 낮은 경계 대비를
유지한다. 기존 고정 열·오른쪽 숫자 정렬·부분 숫자 `…`는 그대로 사용한다.

- `#explorer-basis`: `ANNUAL`/`QUARTERLY`/`TTM`; 초기값은 연간이다.
- 연간은 기존 `#explorer-year`와31개 정의, API/4개년 프로필, preset을 유지한다.
- 분기/TTM은 `#explorer-quarter`의 `YYYYQn` 종료 버킷을 선택한다. 연간 연도·preset·
  정렬 상태와 분기/TTM의 기간·preset·정렬 상태를 따로 기억한다.
- 분기는 catalog의 non-TTM32개, TTM은 기존 TTM9개만 사용한다. 표 preset과 비교
  지표는 현재 basis의 정의 안에서 선택한다. 분기 전체 지표도 native preset으로 열린다.
- TTM은 핵심 금액5개/수익성6개/현금흐름3개/전체9개라는 실제 subset과 caption을
  사용한다. 제공되지 않는 성장률·안정성이나 잔액 합산을 TTM에 만들지 않는다.

`explorerBasis`는 탐색 전용 상태다. Annual guide catalog와 `S.explorerYear`를 quarter
catalog로 덮어쓰지 않는다. `S.run`/`S.catalog`/`S.revision`·조건/저장 결과를 바꾸지
않는다. Threshold 변환·execute/save/export 및 원래 저장 자료 열기 함수는 byte 그대로
유지한다. 기존 테스트의 허용 변경 목록은 실제 바뀐 explorer 함수로만 좁게 확장했다.

## 기간·자료 읽기와 계산 금지

`/api/quarter-periods`의 `PERIOD_AVAILABLE`를 회사별로 집계해 가장 최근의 전체 준비
버킷을 기본 선택한다. 전체 공통이 없으면 가장 최근 일부 준비 버킷을 선택하며 날짜를
코드에 고정하지 않는다. 실제 inventory에서2026Q3는27/50,2026Q2는50/50이므로 이번
자료의 기본 선택은2026Q2다. Empty/unsupported inventory는 두 interim option을
비활성화하고 탐색 안에 설명한다. 기존21 등 annual-only 자료의 연간 boot는 유지한다.

`/api/quarter-explorer`의 이미 발행된41개 정의/관측값만 사용한다. Dataset+bucket의
promise snapshot cache는 최대2개다. 같은 버킷의 query/filter/sort/preset/Q↔TTM은 이
snapshot을 재사용하며 큰 nested lineage 응답을 다시 요청하지 않는다. 기간 응답의
calendar 좌표를 확인하고 stale 응답은 현재 표에 적용하지 않는다. Annual guide는
기존 연간 API와 catalog를 계속 사용한다.

선택한 종료 버킷과 실제 공시 기간·회사의 FY/Q를 구분한다. AAPL의 calendar2026Q2는
FY2026Q3이며 quarterly revenue는109,417,000,000 USD, TTM revenue는466,823,000,000 USD다.
두 값은 각각 이미 발행된 관측값이고 browser가 TTM을 계산하지 않는다. Actual API의
exclusive end는 기존 표시 규칙으로만 inclusive caption으로 바꾼다. Missing/UNAVAILABLE/
quality blocking은 `—`와 이유이며0이나 연간 값으로 대체하지 않는다.

검색은 기업명/ticker/업종을 포함한다. 현재 basis의 raw decimal string으로 정확하게
정렬하며 binary float로 순서를 정하지 않는다. 미제공은 양 방향 모두 마지막이고
동률은 기업명/CIK로 결정한다. Sorting/formatting은 financial metric 계산이 아니다.

## 비교·프로필·비동기 연결

선택 기업2~4개의 비교는 현재 basis만 사용한다. Annual은 기존 comparison API를
유지하고 interim은 선택 metric마다 기존 `/api/quarter-comparison`을 호출한다.
따라서 API의 definition/unit/as-of scope 검증을 cache의 임의 조합으로 대체하지 않는다.
비교 cell은 각 관측값의 실제 기간/FY/Q를 표시한다. Context가 바뀌면 이전 비교를
지우고 닫으며 아직 준비되지 않은 context에서는 비교를 열지 않는다.

프로필은 기존 drawer·summary·grouped metrics·chart/table 표현을 재사용한다. Interim
summary는 선택 snapshot에서 읽고 선택 metric의 `/api/quarter-series?limit=8`만 lazy
조회한다. Calendar year/Q와 실제 FY/Q는 별도 표시한다.8버킷 chart는 year/Q를 두 줄로,
missing은 별도 줄로 표시하고 첫/마지막 available point만 숫자 label을 둔다. 모든 값은
표와 title에 남는다. 기존 annual4개년 chart는 유지한다.

탐색-local loading/error와 `#explorer-table[aria-busy]`를 제공한다. Load/profile/series/
comparison token과 dataset+basis+period key를 확인하여 새 context에 이전 성공/실패
응답이 덮이지 않게 한다. Annual의 지연 detail 실패도 explorer-local로 처리한다.
이 처리는 저장 상태나 데이터 조회 의미를 변경하지 않는다.

## 자체 focused 검사와 ROOT preview

```bash
node --test tests/screening/screening_explorer_period_basis.test.cjs
python -m pytest -q -p no:cacheprovider tests/test_screening_display_assets.py
```

신규 Node9건은 공통/부분 준비 기간 선택, exact sorting/missing/quality,2-snapshot 재사용,
32/9 분리 및 TTM preset, annual 상태 분리, stale quarter/detail/comparison/series 응답과
늦은 annual 실패, unsupported inventory, 기존 comparison endpoint의 actual/fiscal 표시를
검사했다. 기존 Display5건과 합쳐14건을 기존 pytest wrapper **1 PASS**로 실행했다.
Wrapper lint·JS syntax·diff 검사 PASS, Python/bridge의 main 대비 diff는 없다.
기존 금융·회사 audit·backend/full publication 검사는 다시 실행하지 않았다.

ROOT19065 actual preview는12 checks/12 screenshots, page errors0, 모든 요청 GET과
journal API deep-identical을 기록했다. 연간 기본/기억된FY2024·preset·정렬 복원,
기본Q2/FYQ3·분기 비교/profile8, TTM9 비교/profile8·정직한 subset, 최신Q3에서도50행과
AAPL missing 유지, 기존21 저장 결과 재열기 후 탐색TTM50 유지,390px 회사 고정을 확인했다.
두 고유 기간에 정확히2 quarter-explorer 요청만 있었고 filter/mode/sort 중 중복 요청은 없었다.
근거는 Windows visualizations의 `explorer-period-basis-20261106/browser-uat.json`과 화면이다.

이 실제 visual run의 JS SHA는 `445bc091847444c1a5cf7027e484d4a8d5b25194e3a68cbddaa309d605cb1c52`다.
그 뒤 rendering/chart/preset을 바꾸지 않고 annual 늦은 실패·inventory loading·비교 준비
상태를 좁게 보완한 최종 JS는 `575f54d96f98334d23001a0f1c002d1192a81b56f56d13d6f8535ed94a73a58a`다.
해당 guard는 focused 검사로 확인했고 ROOT에 해시 차이를 전달했다. CSS는
`1abea5b1fbea7ead347550dc62e38658e8096f3a1df1dd0dbcd962793ee28ae3`로 같다.
이를 새 bytes 전체에 대한 별도 실제/독립 검증 완료로 합치지 않는다.

## 인계

독립 읽기 전용 검증·소스 로컬 인수 뒤 ROOT가 exact asset bytes/SHA를 배포하고 기존
backend PID245090을 유지한 채 frontend만 전환한다. Writer는 push/PR/main/runtime이나
원본 data/catalog/journal을 바꾸지 않는다. 이번 기능의 승인·구현·자체/독립 검증·로컬
인수·운영·병합을 구분하여 후속 결과를 기록한다.


## 2026-11-06 source336 독립 FAIL 후 switch continuation repair

`33625fdeea911b5d1aeb835a5d1acfd566caa6c9` 독립 검토는 `switchExplorerBasis`의
post-await continuation이 basis만 확인하는 결함을 발견해 FAIL했다. TTM→분기의 Q2
요청 중 같은 분기 보기에서 Q3를 고르면 loader가 오래된 Q2를 폐기해도 옛 switch가
정렬을 복원하고 retained Q2 snapshot을 현재Q3 caption 아래 다시 그릴 수 있었다.
Quarterly32가 준비된 뒤 TTM load가 실패해도 그 continuation이 기존32개를 TTM으로
다시 그리는 재현도 있었다. 실패 후보/보고서와 이전 visual 근거는 보존한다.

Repair는 switch가 자기 version, 정확한 dataset+basis+period key와 호출 직후의 load
token을 보유하도록 한다. Await 뒤 이 값이 모두 같고 loading이 끝났으며 자신의 key가
READY인 경우에만 sort 복원/renderer를 실행한다. 기존 `loadExplorer` guard를 줄이거나
다른 rendering/formatter/기능을 바꾸지 않았다.

새3 regression은 Q2가 먼저 끝나는 경우, Q3가 먼저 끝나는 경우와 failed TTM load를
검사한다. Frozen336에서3건 모두 실제 FAIL을 확인한 뒤 repair에서 기존 관련9건을
포함해 **Node12 PASS (52.47ms)**를 확인했다.

```bash
node --test tests/screening/screening_explorer_period_basis.test.cjs
```

JS syntax/diff와 main 대비 Python119/bridge 변경 없음도 확인했다. 이전 wrapper/Display
검사와 실제12 visual/4 guard는 재사용하며 금융/backend/browser 전체를 다시 실행하지
않았다. Repair JS SHA는
`75b311ee02b93f387cffb3943a1747e7d395ff900218e476cc8a34bb8f6637a0`이고 CSS는 그대로다.
새 독립 판단·ROOT의 실제 same-basis race 확인·소스 인수·운영·PR/CI/main은 별도 대기다.
