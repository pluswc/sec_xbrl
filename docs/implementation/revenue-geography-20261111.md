# 공시 매출의 지역 보기와 명시적 보기 등록 — 2026-11-11

최신 상태(2026-11-11): INDEPENDENTLY_VERIFIED / LOCALLY_ACCEPTED / LIVE.
대상 코드 `92876be5b93511c7f96541ecbf82da5a2c049d54`. 운영 인수 당시 main은 미병합이었다.
이후 사용자가 main 반영을 명시 승인했으며 실제 반영 상태는 Git main 포함 관계와 PR로 확인한다.
아래 단계별 대기 기록은 당시 상태이며 마지막 운영 인수 기록이 이를 갱신한다.
본 계약은 기존 50사 준비 데이터의 선택형 매출 보조 발행과 해당 화면만 다룬다.
신규 수집, Raw/Analytical 재생성, Nasdaq 수집 작업은 범위 밖이다.

## 입력과 수락 기준

- `screening-dataset-v3`의 정확한 부모를 재사용한다. 재무 cutoff는 2026-10-25,
  dataset manifest SHA-256은
  `afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4`다.
- 기존 사업부문·제품/서비스·연결 매출·제품 계층·비중/전년비의 공시 선택과 값을
  유지한다. 연간 4개, 분기 8개 실제 준비 기간을 사용한다.
- `srt:StatementGeographicalAxis`의 보고 항목을 지역 보기로 추가한다.
  지역 단독 및 등록된 사업부문·제품 축과의 명시적 조합을 지원한다.
  별도 근거 없는 과거 `us-gaap` 별칭, 사용자 정의 축의 이름 유사성,
  등록되지 않은 재분류 축을 자동으로 활성화하지 않는다.
- `REVENUE_VIEWS`의 명시적 등록이 기본 축, 허용 고정 분류, 보기 우선순위,
  표시 이름을 결정한다. 추가 분류는 계약 검토 후 등록하며 필요하면 분모 정책을
  지정한다. 모든 축을 수용하는 범용 의미 추정기는 아니다.

## 의미와 화면

지역 보기는 병렬 공시 관점이다. 지역 계층, 완전한 세계 분할, 중간 지역,
누락된 소계나 축간 합계를 만들지 않는다. 원래 공시 라벨과 전체 명시적 차원,
매핑 epoch, 원본 fact 계보, 충돌 및 기간 공백을 유지한다. 고정된 다른 축의
member를 함께 표시한다. 지역명만으로 소재지·청구지·배송지·고객 위치를 추정하지
않으며 회사간 같은 기준이라고 주장하지 않는다. AAPL 등의 지역성 사업부문도
사업부문 축에 있으면 기존 사업부문 보기로 유지한다.

지역 단독의 비중 분모는 동일 공시의 연결 매출이다. 다른 축이 고정된 지역은
전체 차원에서 지역 축만 제거한 정확한 scope의 독립적으로 보고된 부모를
기존 준비 행에서 유일하게 확인할 때만 비중을 제공한다. 동일 snapshot·filing·
concept·통화·기간·품질·전체 raw 차원 부분집합 검사를 유지한다. 고정 scope가
다르거나 부모가 없거나 경쟁하면 비중을 보류하며 연결 매출로 대체하지 않는다.
분모 출처 fact ID는 비중 계보에 남긴다. 다른 축을 합산하여 부모를 만들지 않는다.
전년비는 기존 `same-filing-revenue-ratios-v1`의 동일 공시·동일 전체 scope
비교만 사용한다. 기존 제품 계층 정책은 지역 행에 적용하지 않는다.

화면은 기존 워크시트의 native select, 표, 선택형 추이 보드와 원문 링크를
재사용한다. 서버가 발행한 보기 descriptor를 표시하며 이전 payload는 기존
보기에 지역 빈 보기를 더한 fallback으로 읽는다. 빈 payload/누락 그룹은 빈 상태로
표시한다. 보기별 차트 선택과 기간 clamp 정책을 유지한다. Display는 재무 비율을
계산하지 않는다. 기존 ivory/ink/slate/annotation-blue, 4px spacing과 표 계층을
유지하므로 별도 디자인 체계를 도입하지 않는다.

## 재현과 인계

필수 입력은 위 exact dataset manifest 및 그 부모 publication이다. bulk 보조
JSON은 Git에 넣지 않는다. 소스 검사는 다음과 같다.

```bash
.venv/bin/python -m pytest tests/screening/test_revenue_breakdowns.py -q
.venv/bin/ruff check examples/screening/prepare_revenue_breakdowns.py tests/screening/test_revenue_breakdowns.py
node tests/screening/screening_revenue_breakdowns.test.cjs
```

실제 발행은 `python -m examples.screening.prepare_revenue_breakdowns`의
`--dataset-manifest`, `--dataset-manifest-sha256`, `--output`으로 수행한다.
실제 결과 크기와 50사 기존 행 동등성, AMZN/MSFT/GOOGL의 기간별 실제 가용성,
새 산출물 해시는 아래 구현 증거에 기록한다. 운영 bridge 전환과 원본 journal
불변·실제 브라우저 검증은 리드가 별도로 수행하며 소스 자체 검사로 추정하지 않는다.


## 구현 증거 — 2026-11-11

명시적 등록표가 축 허용·주 축/member 선택·그룹·우선순위를 결정한다. 테스트에서
별도 고객 축 등록을 추가하여 추가 엔진 분기 없이 준비 행이 새 그룹으로 투영됨을
확인했다. 고객 축은 실제 발행에서는 활성화하지 않는다.

실제 50사 보조 발행은 8,570,993 bytes이며 기존 16MiB asset 한도 안이다.
전체 company 응답(scope 필드 포함) 최대는 DE 815,217 bytes, p95는 319,922
bytes다. DE만 이전 512KiB 한도를 초과했으므로 리드가 정확한 1MiB 매출 응답
한도를 승인했다. 준비기와 bridge가 동일하게 전체 응답 bytes를 검사한다.
일반 JSON을 유지하고 압축 인코딩·페이지 잘림·자료 삭제는 도입하지 않았다.
공통 financial-growth 응답 한도는 기존 512KiB를 유지한다.

기존 보조 발행 SHA-256
`2d461aa7524b38d0143d3e6bd768128ecfd697bbdeb0cbe89ca39ea6df1a71b9`과
모든 50사×연간/분기의 기존 view 필드를 정확히 비교했다. 새 `views` descriptor와
`groups.geography`를 제외하면 기존 사업부문·제품/서비스 행, 연결 매출, 비중·전년비,
계층, 기간, 원본/발행 계보를 포함한 **차이 0건**이다. 기존 asset은 5,420,594 bytes다.
새 발행은 아래 위치에 보존하며 Git에는 넣지 않는다.

- 로컬 산출물: `work/revenue-geography-20261111/revenue-breakdowns-current50.json`
- SHA-256: `187fb9b2fc4ccd64813ddd671576b331aab6497473f4677e0c8c1e9bf37203bb`
- 크기·기존 결과 대조: `work/revenue-geography-20261111/size-and-legacy-comparison.json`

준비된 기간/허용 매출 개념의 실제 지역 가용성은 연간 42사, 분기 28사다. 전체
prepared axis inventory의 범위와 다르므로 이를 최신 SEC 전체 공시 커버리지로
주장하지 않는다. 지역 행은 연간 930개/보고 셀 937개, 분기 678개/보고 셀 877개다.
고정 scope 지역 행은 연간 187개/보고 셀 190개, 분기 302개/보고 셀 313개다.
고정 scope의 비중은 각각 156/218셀에서 확인됐고 나머지는 보고 금액을 보존한 채
보류했다.

| 회사 | 연간 실제 보고 | 분기 실제 보고와 공백 |
| --- | --- | --- |
| AMZN | FY2022–2025 각 5개 항목 | 준비된 8개 기간의 지역 보고 셀 없음 |
| MSFT | FY2023–2026 각 2개 항목 | FY2025/2026 Q1–Q3 각 2개, 두 Q4 공백 |
| GOOGL | FY2022–2025 각 4개 항목 | FY2024 Q3, FY2025 Q1–Q3, FY2026 Q1–Q2 각 4개, 두 Q4 공백 |
| AAPL | FY2022–2025 각 3개 항목 | 준비된 8개 기간의 지역 보고 셀 없음 |

GOOGL 등의 일부 기간 비중 보류는 동일 공시·개념의 분모 조건을 그대로 적용한
결과이며 다른 매출 개념을 대신 사용하지 않는다. 지역적 명칭의 기존 사업부문은
사업부문에 그대로 남는다.

자체 focused Python 16 PASS, Node 9 PASS, 변경 Python lint PASS,
두 JavaScript syntax 검사와 diff whitespace PASS다. 실제 artifact의 bridge
load에서 50사와 최대 응답 815,217 bytes를 확인했다. 원본 자료 및 서비스에는
쓰기하지 않았다. 별도 브라우저의 실제 화면 검증과 독립 검증·리드 인수·main
병합·live 전환은 이 소스 자체 검사의 범위가 아니다.

## 독립 FAIL 반환과 고정 scope 분모 보완 — 2026-11-11

후보 `ca09c3f5f92d46e7c3763e768adf8819ba1ff87b`는 독립 검증에서 P1 FAIL을 받았다.
동일 고정 scope의 부모 후보를 ratio-bind 성공 여부로 먼저 걸러서, 명시적으로
`COMPETING_PREPARED_SCOPE`인 부모가 사라진 뒤 다른 정상 부모만 선택될 수 있었다.
지역의 고정 scope 부모는 해당 기간에 보고 값이 있거나 명시적인 충돌 상태인
모든 후보를 먼저 세고, 단 하나인 경우에만 기존 ratio-bind를 적용하도록 고쳤다.
기존 제품·사업부문 분모 선택은 변경하지 않았다.

새 회귀 검사는 충돌 부모와 정상 부모가 함께 있을 때 지역 보고 금액과 검증된
동일 공시 전년비를 유지하면서 비중만 보류함을 확인한다. 보완 후 focused Python
17 PASS, 변경 Python lint와 diff whitespace PASS다. 이전 Node 9 PASS는 변경 없는
화면/bridge 근거로 유지한다. 새 소스의 독립 검증과 인수는 별도 대기다.

기존 current50 payload의 고정 scope 보고 503셀과 공표 비중 374셀만 대상으로
부모 후보를 재검사했다. 명시적 충돌 부모 0셀, 복수 활성 부모 0셀, 영향받는
기존 공표 비중 0셀이다. `work/revenue-geography-20261111/fixed-parent-conflict-check.json`에
결과를 보존한다. 이 보완은 실제 artifact 값을 바꾸지 않으므로 deep rebuild나
기존 전체 감사는 반복하지 않았고 위 artifact bytes와 SHA-256을 그대로 유지한다.


## Compact 화면 보완 — 2026-11-11

고정 scope 보완 후보 `92f2079c44ed0f30a787f3d17968eee5de16191b`의 독립
소스 PASS 후 리드가 실제 desktop 및 768px preview를 확인했다. 768px에서 기존
760px breakpoint 밖의 두 열 배치가 유지되어 좁은 plot을 활성 기간으로 자동
스크롤하면서 왼쪽 Y축 숫자 앞부분이 잘렸다. 승인된 최소 보완으로
`app.css`의 매출 보드만 1024px 이하에서 한 열로 쌓는다. 기존 desktop 두 열,
타이포그래피, SVG 최소 크기·축 산술, 다른 재무 보드의 breakpoint는 유지한다.

Focused CSS 검사는 새 breakpoint 범위·선택자·단일 열 선언 및 기존 desktop
기본 선언을 확인하고, 추가 3줄을 제거하면 이전 CSS와 바이트가 같음을 확인했다.
JavaScript·Python·50사 artifact는 변경 없으므로 이전 검사·자료 근거를 재사용한다.
리드의 compact 재촬영과 최종 live 인수는 별도다.

## 실제 운영 UI 보존 통합 — 2026-11-11

리드의 운영 전환 전 guard가 기존 receipt와 실제 18765 프로세스의 차이를 발견해
변경 전에 중지했다. 실제 listener는 PID 52008이며
`explorer-header-sort-20261111/bridge-growth.json` receipt의 모든 기존 인자를
보존해야 한다. 기존 backend는 19070이고 현재 financial-growth artifact는
SHA-256 `a9df827eba4c4570bcfc8ef70d32635535479d0227ed4b0b20dc74c2eef62938`다.
이전 receipt의 프로세스나 growth artifact로 되돌리는 것은 이 작업의 인수 조건이 아니다.

리드는 기존 운영 UI를 보존하는 통합을 승인했다. 자체 revenue branch에 정확한
`codex/financial-summary-readability`의 `42a5785473649a8e33a1d8054ffd2c9cc7d0086e`를
merge하여 이미 인수된 헤더 정렬, 재무 지표 ledger, 표시 자리수, 준비된 전체
MONEY/PERCENT 전년비/%p 비교의 소스·producer·검증기·계약·테스트를 함께 유지한다.
다른 branch/worktree나 main은 수정하지 않았다. 계획 등록부의 동시 추가 충돌만
두 항목을 모두 보존하여 해결했으며 JS/CSS/bridge와 매출 테스트는 자동 병합됐다.
새 재무 계산·수집·backend 변경을 구현하지 않는다.

보존 검사는 base `b1b783d418f99201c73d9eaf388266d8d6c01282`에서 revenue 후보
`150656e20f9b5dea19502a64b6101ec7eb4900dc`까지의 차이만 임시 사본에서 역적용했다.
그 결과 JS/CSS/bridge/매출 테스트 네 파일 전체가 incoming 42a578과 바이트가
같다. 따라서 incoming의 개별 함수/변경 hunk를 수정하거나 누락하지 않았음을
파일 전체로 검증했다. Incoming JS/CSS/bridge는 실제 운영 bundle과도 같다.

| 파일 | incoming/live SHA-256 | 통합 SHA-256 |
| --- | --- | --- |
| app.js | `f72c694332026eb5c27620ed0df2b310d75e90b778f3c5095cdc1cf557e2e3fc` | `543da1e3135caf1aed9b57cdebcd3ebc55cbe54b6cad60c90a7c09de3fb62767` |
| app.css | `dd585102ffefa1761f3a86d437acc86ae929a4324a48c10636e5a56c9d76218b` | `1428c4e963a163b5d8aab5244bf072dcb1d0909e83119b2372b9da4bbc0632b3` |
| windows-loopback-bridge.cjs | `d7d28b41445458519a67f3aa604076847bb14145d3aafed717dcafa3b22f5339` | `64302e4b8e234c8d43b389d5e3feae9308b453d5431e66ba7c0a4bdf24d7baea` |

로컬 `work/revenue-geography-20261111/live-ui-preservation-check.json`에 역적용
대조를 보존한다. 통합 자체 Node 검사는 매출 9, 기간/헤더 33, growth 3,
display 5, 추이 10으로 합계 **60 PASS**다. Display의 loopback 테스트는 최초
sandbox `EPERM` 후 해당 임시 listener의 제한된 escalation으로 재실행해 통과했다.
JavaScript syntax도 통과했다. 통합 bridge가 기존 a9 growth-v2 50사와 신규 지역
artifact 50사를 함께 읽었고, 매출 최대 응답은 기존 확인한 815,217 bytes다.
신규 지역 산출물과 준비기는 변경 없으므로 50사 projection·기존 Python 검사를
반복하지 않았다. Incoming producer 검증은 해당 기존 인수 증거를 유지한다.

92f2079의 이전 독립 소스 PASS/리드 수락 및 이전 실제 UI 검증과 이번 통합의
독립 검증·실제 preview·운영 전환은 구분한다. 이번 통합 commit의 새 검증과
실제 PID/인자에 기초한 운영 전환은 리드가 수행하며 아직 본 기록의 완료가 아니다.


## 최종 독립 검증·로컬 인수·실제 운영 — 2026-11-11

리드는 통합 코드 `92876be5b93511c7f96541ecbf82da5a2c049d54`의 별도 읽기 전용
독립 검증 **PASS**를 수락하고 **LOCALLY_ACCEPTED**로 판단했다. 실제 운영
`http://127.0.0.1:18765/`에 해당 코드의 bundle을 적용했으며 새 Windows bridge는
PID **41344**, 기존 backend **19070**은 유지했다. 소스는 main에 병합하지 않았고
원격 push·PR·CI도 이번 전달에서 수행하지 않았다. 이 문서 후속 commit은 상태
기록만 바꾸며 실제 배포 코드는 위 92876be5로 고정한다.

이미 인수된 `42a5785473649a8e33a1d8054ffd2c9cc7d0086e`의 헤더 정렬·재무 요약
ledger·표시 자리수·growth-v2 기능을 보존했다. Financial-growth는 기존 a9df827e
artifact, 새 매출 artifact는 위 187fb9b2 해시를 그대로 사용한다. 기존
history-worker, 원본 journal 경로 및 다른 프로세스 인자도 실제 직전 receipt를
기준으로 유지했다. 오래된 PID 44504 receipt는 전환에 사용하지 않았다.

최종 GET-only 실제 브라우저 검사는 한 회사의 지역 보기·헤더 클릭 정렬,
1440px 두 열과 768px 한 열 배치에서 PASS했다. 768px의 Y축 여섯 눈금
`0 / 50,000 / 100,000 / 150,000 / 200,000 / 250,000`이 모두 완전히 보였고
가로 페이지 overflow·브라우저 오류가 없었다. 기존 AMZN/MSFT/GOOGL × 연간/분기
6개 실제 검증과 전체 50사 기존 필드 동등성은 변경 없는 데이터 근거로 재사용했다.

원본 journal은 기존 **10개 테이블·22개 행**의 모든 row digest와 DB bytes를
보존했다. SHA-256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`다.
실제 검사 과정에서 사용자 기록을 추가하지 않았다.

이 tracked 계약의 승인 범위·수락 판단·코드 SHA·산출물 pin·운영 사실이 인계의
기준이다. 아래 로컬 receipt/이미지는 선택적 세부 증거이며 새 checkout 이해의
전제 조건이 아니다.

- 통합 소스 독립 PASS/로컬 인수: `work/revenue-geography-20261111/local-acceptance-integrated.json`
- Journal 보존: `work/revenue-geography-20261111/journal-after-check.json`
- 운영 전환·최종 GET-only 검사·화면:
  `/mnt/c/Users/plusbdw/.codex/visualizations/2026/10/07/01a118cd-05d7-7842-b035-32b40d7c2817/revenue-geography-20261111/`
  아래 `frontend-switch.json`, `live-report.json`, `live-desktop.png`, `live-768.png`.

위 운영 인수 시점의 snapshot은 **INDEPENDENTLY_VERIFIED + LOCALLY_ACCEPTED + LIVE / MAIN_NOT_MERGED**다.
이는 당시 기록이며 이후 main·원격 상태를 고정하는 주장이 아니다.


## 사용자 main 반영 승인 — 2026-11-11

사용자는 현재 기능의 main 반영을 명시 승인했다. 범위는 수락된 지역 매출 보기와
고정 scope 정책·보조 발행 연결, 실제 운영 UI 보존을 위해 포함한 기존 42a578
헤더 정렬·재무 요약/growth-v2 변경 및 관련 계약·테스트다. Nasdaq 수집 소스는
포함하지 않는다. 이 준비는 문서만 바꾸며 수락된 실행 코드는 92876be5와 같다.
리드는 branch push 후 PR·CI·main 병합을 진행한다. 이 기록 자체는 MERGED
선언이 아니며 실제 병합은 main의 commit 포함 관계와 해당 PR/검사 결과로 판단한다.


## PR87의 새 main 문서 통합 — 2026-11-11

PR87의 기존 head `5d9b221fe06b43a11cc2960ae29cbb58b7c6e084`는 원격 CI
`43031031603`에서 SUCCESS였다. 그동안 PR86이 main
`d58e90ec87e2d51fbabc9b9ca49e983bcef0d80f`에 병합되어, 이 정확한 main을
현재 branch에 통합하고 계획 등록부의 두 전달 기록을 모두 보존했다. Incoming은
이미 포함한 42a578 이후의 전달 문서만 추가하며 수락된 92876be5의 실행 코드와
테스트는 바이트가 같다. 기존 검사·산출물·운영 근거를 재사용하고 새 head의 원격
CI와 PR87 병합 판단은 리드가 수행한다. PR87의 병합 완료 선언은 아니다.
