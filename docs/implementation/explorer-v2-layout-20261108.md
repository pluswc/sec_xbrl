# 기업 탐색 V2 화면 계약

## 범위와 승인

2026-11-08 사용자 승인 범위는 기업 탐색 기본 화면과 기업 상세의 매출 구성
화면이다. 기준은 `a6d3891fbb`다. 시안의 밝은 원장 배경, 잉크색 본문,
파란색 상태 표시와 표 중심 레이아웃을 실제 발행물에 적용한다. 시안의 회사,
항목, 금액은 디자인 참고 자료다. 작업에는 요청된 모델 대체 고지 규칙 변경도 포함한다.
구현은 사용자가 선택한 GPT-6.1 Sol에 배정하고, 독립 검증은 별도의 GPT-6 Astra에 배정한다.

## 수락 조건

- 왼쪽 내비게이션에서 기업 탐색, 지표 안내, 스크리닝, 저장 이력으로
  이동한다. 탐색 제목과 적용된 배치 기준, 판단일·사용지연·재무 기준일,
  기준 변경과 이 기준으로 스크리닝 기능을 구분한다.
- 기업 검색, 연간·분기·TTM, 회사별 최신·지정 기간, 표시 항목·정렬,
  지표 열과 비교 체크박스를 유지한다. 넓은 표는 자체 영역에서 스크롤한다.
- 기업명을 열면 목록 아래에 인라인 상세를 배치한다. 재무 요약에는 기존
  회사 소개와 출처, 지표 카드, 추이, 기간별 표, 전체 지표를 유지한다.
  매출 구성과 흐름으로 전환할 수 있다. 닫기 또는 상세 내부 Escape로
  기업 행에 포커스를 반환하고, 행이 필터로 사라졌으면 기업 검색으로 반환한다.
  화면 이동이나 배치·기간·빈도 변경 시 이전 상세와 지연 응답을 폐기한다.
- 매출 구성은 넓은 화면에서 표와 항목별 추이를 나란히 두고 좁은 화면에서
  세로로 배치한다. 연간 최대 4회계연도와 분기 최대 8회계분기를 그대로 제공한다.
  TTM 기업 프로필에서도 구성 조회는 연간·분기만 제공한다.
- [매출 구성 계약](investor-analysis-interface.md#2026-11-08-기업-프로필의-매출-구성과-흐름)의 연결 매출,
  실제 범위와 일치하는 부문 소계 및 하위 공시 항목, 비중 분모, 같은 공시의
  전년비, 누락 사유, 공시 근거를 표시한다. 누락 또는 매핑 변경 구간의 선은
  끊는다. 화면에서 겹치는 항목을 합치거나 소계·비중·전년비를 산출하지 않는다.
- 화면 너비 1464px, 1024px, 390px에서 제어·표·상세가 읽히고 문서 전체의
  가로 스크롤이 생기지 않는다. 비교 선택 및 추이, 이력 일괄 작업과 복원,
  저장·다시 열기·내보내기는 기존 API 및 저널 경로를 사용한다.

## 경계와 검증

변경 범위는 표시 컴패니언의 `app.css`와 `app.js`, 해당 화면 검증,
그리고 추적 문서다. Python 내장 화면, 브리지, API, 재무 계산, 발행물과
SQLite 저널은 기존 경로를 사용한다. 브라우저 검증에는 준비된 배치·연간·분기
발행물과 매출 구성 파일을 갖춘 로컬 환경이 필요하다. 같은 회사의 실제 기간과
출처를 사용하며, 개별 항목의 누락·범위 경쟁은 기존 설명을 보존한다.

```sh
node --test tests/screening/*.test.cjs
python -m pytest -q tests/test_screening_display_assets.py tests/screening/test_screening_explorer.py tests/screening/test_revenue_breakdowns.py
```

| 단계 | 상태 |
| --- | --- |
| 제안 | 2026-11-08 V2 시안과 표시 범위 |
| 승인 | 2026-11-08 V2 화면 및 모델 대체 고지 변경 승인 |
| 구현 | 소스 동결 SHA `9a690e664b5603cec0ad74ae2edf89e2d00e54e5`. Node 62개, pytest 17개 통과 |
| 독립 검증 | 2026-11-08 별도 GPT-6 Astra가 동결 SHA를 읽기 전용 검토하고 Node 62개와 pytest 17개를 재실행해 PASS. 브라우저 범위는 리드의 증거를 검토했으며 별도 브라우저 재실행은 미포함 |
| 로컬 인수 | 2026-11-08 리드가 동결 소스를 인수하고 기존 로컬 주소에 배포한 뒤 브라우저와 저널 동일성을 확인 |
| 로컬 main | 인수 문서 검증 후 fast-forward 대기 |
| 원격 push·PR·CI·병합 | 미실행 |

2026-11-08 실제 로컬 발행물 기반 읽기 전용 브라우저 검사는 1464px,
1024px, 390px에서 탐색 및 매출 구성 화면을 확인했다. 연간·분기·TTM은
각각 50개 기업을 표시했고 AAPL과 ADBE 비교, GOOGL 연결 매출·부문 소계·
비중·전년비와 공시 링크를 확인했다. 페이지 오류와 GET 외 요청은 0건이었다.
운영 전후 저널의 SQLite 파일 SHA-256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로
일치했다. 각 테이블 해시도 일치했다. 조건 정의 3개, 개정판 4개, 실행 4개,
수명 주기 이벤트 8개를 보존했고 기존 휴지통 상태가 유지됐다.

## 로컬 운영과 재시작

2026-11-08 `http://127.0.0.1:18765`에서 Windows 프런트엔드 프로세스를
PID 37832에서 31708로 교체했다. 백엔드 포트 19069와 브리지 소스, 저널,
매출 구성 파일을 계속 사용하며, 실행 인자 중 표시 번들 경로만 교체했다.

보조 자료는 Windows 사용자 프로필 아래
`.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/explorer-v2/`에
있다. `before-report.json`, `preview-report.json`, `live-report.json`은
전환 전·미리보기·전환 후 브라우저 결과이고, `journal-before.json`과
`journal-after.json`은 저널 검증 결과다. `bridge-v2.json`에 실제 실행 인자가
있고, `bundle-hashes.json`은 번들 두 파일을 동결 소스 SHA와 연결한다.
`release.cjs`는 최초 전환, 바이트 확인, 실패 시 이전 실행 인자 복구를 기록한다.
이전 실행 인자는 그 스크립트가 읽는 배포 기록에서 찾는다.

기존 프런트엔드가 종료되고 같은 백엔드가 실행 중일 때 Windows PowerShell에서
아래 명령을 실행한다. 기록된 인자를 재사용하고 번들 해시를 검증한다.
프런트엔드 포트에 리스너가 있으면 재시작 명령을 중단하며, 기동 시 새 PID를 출력한다.
최초 전환용 `release.cjs apply`는 기존 배포 기록이 있으면 거절한다.

```powershell
$release = Join-Path $env:USERPROFILE '.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/explorer-v2'
if (Get-NetTCPConnection -LocalPort 18765 -State Listen -ErrorAction SilentlyContinue) {
  throw 'Frontend port 18765 already has a listener.'
}
@'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {spawn} = require('node:child_process');
const directory = process.argv[2];
const {args} = JSON.parse(fs.readFileSync(path.join(directory, 'bridge-v2.json')));
const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'bundle-hashes.json')));
const bundleIndex = args.indexOf('--assets-root');
assert.ok(bundleIndex > 0);
for (const file of ['app.css', 'app.js']) {
  const bytes = fs.readFileSync(path.join(args[bundleIndex + 1], file));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), manifest[file]);
}
const log = fs.openSync(path.join(directory, 'bridge-v2.log'), 'a');
const child = spawn(process.execPath, args, {detached: true, windowsHide: true, stdio: ['ignore', log, log]});
child.once('spawn', () => { console.log(child.pid); child.unref(); });
child.once('error', error => { console.error(error); process.exitCode = 1; });
fs.closeSync(log);
'@ | node - "$release"
```

기동 후 `/api/status`의 응답을 확인하고, 제공되는 `/app.css`와 `/app.js`의
SHA-256을 `bundle-hashes.json`과 대조한다.
