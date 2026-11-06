# 2026-11-06 dashboard 수치·표 표시 개선 전달 계약

## 승인·범위와 현재 상태

사용자는 권장 순서대로 실제 화면에 반영하고 기존 데이터/저장 기록을 보존하며,
수정 전후 숫자·스크롤 screenshot을 확인하고 불필요한 검증 반복을 줄이도록 승인했다.
ROOT는 Display companion 경계를 확정했다. 기준 main은
`737bf145bbc9fe8d599197c72d5f63c5b1a14043`, 구현 branch는
`codex/ui-data-presentation`이다. 기존 branch/worktree와 지침은 삭제·수정하지 않는다.

구현과 자체 focused 검사는 완료했고 ROOT가19065 preview에서 실제 화면을 비교했다.
독립 검증·소스 로컬 인수·18765 운영 반영·PR/CI/main 병합은 별도 대기다.
현재50사 데이터의 금융 의미나 발행 상태를 바꾸는 작업이 아니다.

## 선택한 Display 경계

기존 동결 HTML은 이미 `/app.css`, `/app.js`의 same-origin URL을 참조한다.
선택형 Windows bridge가 명시적 `--assets-root`로 받은 두 파일만 응답하고 HTML/API/
exports는 기존18766 backend로 relay한다. Backend의 document CSP도 그대로 전달한다.
Python119 inventory와 정확한 v2 source packet을 변경하지 않으며 금융 검증기를 확대하거나
우회하지 않는다. 기존 backend PID245090을 유지하고 ROOT만 frontend bridge를 전환한다.

권위 있는 Display companion은 tracked
`examples/screening/display-assets/app.css`, `app.js`다. 이들은 기존
`src/sec_xbrl/screening/ui.py` CSS/JS 문자열의 정확한 baseline 추출에서 출발했다.
이후 표시 formatter/숫자 markup/표 presentation만 수정했다. Threshold 변환, 자료 선택,
API 호출, 실행·저장·export 함수와 버튼 동작은 원본과 같다.

정상 Windows 이용 주소18765가 이 companion을 사용하는 canonical Display다.
Backend18766 직결 및 `--assets-root` 없는 bridge는 기존 동결 UI fallback이다.
Python wheel이나 backend가 자동으로 새 자산을 제공한다고 주장하지 않는다. Bridge와
두 자산은 하나의 frontend release로 복사·해시 기록해 배포하고, CLI 옵션은 Windows의
명시적 absolute local directory를 가리킨다. 자동 탐색이나 원격 자산은 없다.

## 화면 계약과 설계 의도

투자자가 원래 기업·공시 기간을 잃지 않고 숫자를 읽고 비교하도록 회사 식별과 수치를
우선한다. 기존 ledger ivory/filing-paper/ink/slate/annotation blue, 낮은 대비의 경계선,
14px body·11px metadata,9×12px 셀·4px 간격 단위를 유지한다. Evidence drawer만 기존
부유 surface를 사용하며 새 컨트롤이나 대시보드 재디자인을 추가하지 않는다.

- 금액은 기존 백만 달러 scale에서 소수1자리, 비율은 기존 단위 그대로 소수2자리 고정.
  Decimal string과 BigInt로 half-up 반올림하며 음수 tie는0에서 멀어지는 방향이다.
  Scientific/큰 수를 binary floating point 금액으로 변환하지 않는다. 음의0은0으로
  정규화한다. 실제0은 `0.0`/`0.00`, 미제공은 `—`로 구분한다. Ratio 배수 변환은 없다.
- 탐색·결과·시계열·peer·기업 비교의 numeric header/cell은 오른쪽 정렬과 tabular digits를
  사용한다. 값 tooltip은 원래 exact value/unit을 보존한다. 날짜/단위는 보조 줄로 분리한다.
- `thead th`만 위쪽에 고정한다. 비교표 body row label은 왼쪽에만 고정하여 행 이름이
  header 위로 쌓이지 않는다.
- 체크/기업 열은 실제 col width와 sticky offset을 맞추고 불투명 surface와 z-index를
  사용한다. 좁은390px에서는 체크32px·기업112px·기간96px로 고정 폭을 제한한다.
  회사명은 최대2줄, ticker/업종은 보조 정보로 표시한다.
- 부분적으로 가린 숫자의 leading/trailing digits를 온전한 값처럼 보이지 않게 한다.
  숫자가 frozen 영역·cell 또는 viewport 경계에 걸리면 전체 숫자를 숨기고 보이는
  조각에14px `…`를 표시한다. 원래 값 title/접근성 label은 유지한다. `…`는 미제공 `—`와
  다르며 완전히 화면 밖인 숫자를 중복 표시하지 않는다. Scroll/resize/DOM 변경은 rAF로
  현재 보이는 표만 갱신하며 데이터를 다시 조회하거나 계산하지 않는다.

## Bridge의 제한

`--assets-root`가 없으면 기존 relay 동작을 유지한다. 옵션이 있으면 listener/relay
시작 전에 고정 map의 `app.css`, `app.js`를 함께 메모리에 읽는다. 명시 absolute root,
부모/파일 symlink alias 거부, nonempty regular file, 각2MiB 한도와 읽기 중 변경 여부를
확인한다. 이후 파일이 바뀌어도 실행 중 bytes는 바뀌지 않는다.

기존 Host/Origin/method/request body 한도를 먼저 적용한 뒤 고정 두 URL의 GET만
정적으로 응답한다. HTTP 입력으로 filesystem 경로를 만들지 않는다. MIME은 CSS/JS,
cache는 no-store, nosniff를 적용하고 startup log에 두 SHA-256을 남긴다.
HTML/API/export의 응답/CSP·CSRF 경계는 기존 relay를 그대로 사용한다. 외부 URI,
inline injection, CSP 해제, Python runtime override나 금융 verifier 변경은 없다.

## 검사와 실제 preview 근거

```bash
node --test tests/screening/screening_display_assets.test.cjs
python -m pytest -q -p no:cacheprovider tests/test_screening_display_assets.py
node --check examples/screening/windows-loopback-bridge.cjs
node --check examples/screening/display-assets/app.js
```

Node focused5건은 string 반올림/큰 수/0·미제공, 기존 non-presentation 함수·workflow
byte 불변, 부분 숫자 경계, asset alias/size 및 bridge 보안/MIME/CSP/fallback을 검사한다.
Pytest wrapper **1 PASS**로 같은5건이 기존 CI 진입점에 포함된다(Node/POSIX 필요).
별도 일회성 main737 blob 비교에서 **119 Python source bytes 동일 PASS**를 확인했다.
이 전체 inventory 비교를 향후 모든 Python 변경을 막는 상시 UI 단위 테스트로 두지는 않는다.
Wrapper lint·Node 구문·diff 검사를 수행했다. 기존 금융/회사 audit/발행 검사는 반복하지 않았다.

ROOT actual preview는 frozen18766 backend에 연결한19065 companion으로 수행했다.
수정 전9장·후10장의1464/1024/390px 화면에서 탐색, 프로필, 비교, 분기 결과/상세를
확인했다. AAPL operating margin31.97, ADI standardized FCF4,278.7 표시, 모든 표 numeric
right alignment,1024/390 회사 x좌표 고정 및 비교 header 위치가 PASS다.
첫 profile preview에서 metadata span의 CSS specificity가 clipping ellipsis를 노출한
실제 결함은 figure wrapper/number-text/ellipsis의 display·font 규칙을 좁게 보완했다.
영향 profile 재확인에서8개 summary 숫자와 ellipsis 기본숨김이 PASS였다.
추가 edge 검사에서 horizontal scroll13px로 실제 FCF 숫자가 부분 가려졌을 때
number-text 숨김/`…` 노출이 PASS였고 scroll 중 API 추가 요청은0건이었다.
시계열 마지막 label 열을 수치 열로 읽던 audit selector는 ROOT가 실제 numeric 열로
정정했고 잘못된 selector를 위한 product 수정은 하지 않았다.

원본 journal definitions3/revisions4/runs4는 유지됐다. Actual preview의 POST는
비저장 `/api/preview`1건뿐이고 saved-record API 내용은 전후 같다. 근거는 Windows
visualizations의 `dashboard-display-release-20261106/{before,after}/audit.json`과 각
screenshot, 수정 전후 `index.html` 비교다. 이는 preview 결과이며 독립 검증이나18765 운영 배포를 뜻하지 않는다.

## 전달과 남은 실행

ROOT는 동결된 bridge와 두 자산의 exact bytes를 Windows local release directory에
복사하고 SHA를 기록한 뒤, 독립 검증·소스 수락 후 frontend bridge만 바꾼다. 원본
journal/catalog·backend process·기존4발행과 financial packet은 보존한다. Writer는 실제
운영 전환, push, PR, main 병합을 수행하지 않는다.

운영 전후 screenshot/숫자/scroll 확인과 사용자 기록 보존 결과, 독립 판단, 로컬 인수,
배포와 main 반영 상태는 후속에서 별도로 기록한다. Preview 통과를 전체 출시로 간주하지 않는다.
