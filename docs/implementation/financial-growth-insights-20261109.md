# 재무 비교 보드의 전년 대비 변화

## 승인과 범위

2026-11-09 승인. 기준 소스 `8436ee9fa5`. 영업이익, 영업활동 현금흐름,
표준화 FCF의 연간·분기·TTM 전년 대비 비교를 차트에 제공한다. 오프라인
생산기는 고정한 기존 발행물에서 파생 결과를 만든다. Windows 브리지는 해시,
발행 범위와 CIK가 맞는 고정 결과를 조회 전용으로 전달한다. Python 패키지,
원본·부모 발행물, 매출 구성, 배치·스크리닝 카탈로그 및 저장 기록은 기존
경로를 사용한다. 결과는 스크리닝 조건 지표에 추가하지 않는다.

## 계산 및 비교 근거

- 같은 회사, 정의와 버전, USD 및 단위·차원·선택 보기와 재무 기준일이
  일치하는 준비 관측을 쌍으로 사용한다. 의미·매핑·보고 기준이 불명확하거나
  품질 보류, 중복, 누락인 관측은 보류한다. 준비 과정의 산술 보증을 재사용할 때
  재작성 기준의 비교 가능성을 주장하지 않는다.
- 연간은 직전 회계연도, 분기와 TTM은 직전 회계연도 같은 회사 회계분기다.
  연간과 TTM의 양쪽 기간은 364·365·366·371일 중 하나이며, 전년 종료일과
  현재 시작일이 같아야 한다. TTM은 각각 4개씩의
  유일하고 연속적인 분기 다리와 양쪽 실제 기간·기준을 검증한다. 준비 발행물에
  앞선 기간이 없으면 누락 사유를 남긴다.
- 비교 가능한 쌍은 현재−전년의 부호 있는 USD 차이를 발행한다. 전년이 양수이고
  현재가 0 이상이면 `(현재 / 전년 − 1) × 100`을 발행한다. 양수→0은
  −100%와 0 도달 상태를 함께 표시한다.
- 둘 다 음수일 때 일반 전년비는 비어 있으며 `(|전년| − |현재|) / |전년| × 100`의
  규모 축소율과 방향을 별도로 발행한다. 확대의 축소율은 음수다. 요약에는 방향과
  부호 없는 규모를 표시하고, 근거 표에는 공식과 부호 있는 공표값을 보존한다.
  영업손실, 영업현금 순유출, 음수 FCF를
  구분한다. 부호 전환, 전년 0, 음수→0의 상태를 일반 전년비와 구분한다.
- 발행 결과는 양쪽의 정확한 값·관측 ID·실제 기간 및 적용한 정책을 보존한다.
  종료일은 배타적이며 화면에서는 마지막 포함 날짜를 표시한다.
  화면에서 현재 금액·실제 기간과 제공된 관측 ID가 준비 관측과 맞을 때 사용한다. 상태와
  근거는 숫자 선이 없어도 읽을 수 있다. 일반 전년비의 누락에서는 선이 끊긴다.
  기존 매출 전년비와 매출 구성의 같은 공시 비율은 기존 경로를 유지한다.

## 세로축과 검증

재무·매출 보드의 기본 세로축은 현재 표시값의 범위를 사용하며, 사용자가
0을 포함하도록 전환할 수 있다. 0을 생략하면 축에 표시한다. 매출 금액은
선택 시리즈끼리 축을 공유하고, 재무 지표 및 백분율은 각각의 축을 쓴다.
재무 수준은 점이 기본이며 선으로 바꿀 수 있다. 재무 보드의 전년비는
항상 0을 기준으로 양수·음수를 나누어 표시하는 세로 막대다. 발행된 0은
기준선의 짧은 표식으로 표시한다. 금액 축 전환은 이 막대의 기준선을
바꾸지 않는다. 매출 구성의 여러 시리즈는 점과 선을 사용한다. 축 범위
계산은 표시용이다. [ONS 막대 차트 지침](https://service-manual.ons.gov.uk/data-visualisation/chart-types/bar-charts)

오프라인 생산기는 `examples/screening/prepare_financial_growth.py`다.
검증된 기존 combined manifest 경로와 SHA-256, 기존 source compatibility
경로와 SHA-256, 새 출력 경로를 받는다. 파생 결과 정의에는 규칙 버전, 공식,
단위와 적용 조건을 명시한다. Windows 브리지는 `--financial-growth`와
`--financial-growth-sha256`을 쌍으로 받아 `GET /api/financial-growth`의
가용성과 정확한 발행 범위의 기업별 준비 결과를 제공한다.

```sh
PYTHONPATH=src python examples/screening/prepare_financial_growth.py \
  --dataset-manifest "$parent_manifest" --dataset-manifest-sha256 "$parent_sha" \
  --source-compatibility "$compatibility_packet" "$compatibility_sha" --output "$new_growth_asset"
node --test tests/screening/*.test.cjs
python -m pytest -q tests/test_screening_display_assets.py tests/screening/test_screening_explorer.py tests/screening/test_revenue_breakdowns.py tests/screening/test_financial_growth.py
```

부호·0 조합, 작은 값, 의미 및 실제 기간 불일치, TTM 다리 누락·중복,
파일과 조회 범위 검증, 늦은 응답, 자동 축과 0 포함을 검사한다. 실제
부모 발행물의 준비 파일과 브라우저 검증, 운영 반영은 소스 검증과 구분한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-09 차트 전용 파생 지표와 세로축 표시 |
| 구현 | 동결 소스 `aaf4ee32575a8f460bd57d981b35f0191461b7fd`. 구현자 전체 검사 `f4a6dd3c9c`의 Node 73개, 집중 pytest 71개 통과 |
| 독립 검증 | 별도 GPT-6 Astra가 `d0941a967b`의 전체 Node 72개와 집중 pytest 71개, 표시 후속 `f4a6dd3c9c`와 `aaf4ee3257`의 집중 Node 각 27개 및 변경 경계를 검증 |
| 실제 발행과 로컬 인수 | 2026-11-09 리드가 검증된 부모로 부가 발행을 준비하고 운영 주소에서 인수 |
| 로컬 main | 2026-11-09 `aaf4ee32575a8f460bd57d981b35f0191461b7fd`로 fast-forward |
| 원격 push·PR·CI·병합 | 미실행 |

## 실제 발행과 운영 인수

검증된 current50 부모를 여는 데 약 10분이 걸렸다. 기존 원본·분석 재처리
없이 50개 회사, 9개 정의를 발행했다. 별도 Decimal 검사에서 사용 가능한
1,241개 비교를 대조했다. 앞선 관측이 준비되지 않은 구간은 계속 누락이다.
이 발행은 재무 보드에만 연결되며 스크리닝 조건 카탈로그를 확장하지 않는다.

동결 소스 체크아웃에서 재현할 때 기존 프로젝트의 부모 파일과 호환 패킷을
가리키고 새 출력 위치를 사용한다. 기존 검증 데이터와 호환 패킷을 가진
동일한 로컬 환경이 필요하다.

```sh
repo_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
rollout_dir="$repo_root/work/gross-margin-research-audit-20261108/rollout"
growth_dir="$(mktemp -d)"
PYTHONPATH=src python examples/screening/prepare_financial_growth.py \
  --dataset-manifest "$rollout_dir/dataset/screening_dataset_manifest.json" \
  --dataset-manifest-sha256 afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4 \
  --source-compatibility "$rollout_dir/source-v6-final.json" 7976afa222c1784073654a772bf8852c0dc1ce147566c378ec034403c887cfd7 \
  --output "$growth_dir/financial-growth.json"
printf '%s  %s\n' f6a71ca9b8d721f2544819ddbe09722e8f61b493d341b3454ca9672ac5dae2a2 "$growth_dir/financial-growth.json" | sha256sum -c -
```

2026-11-09 기존 로컬 주소 `http://127.0.0.1:18765`의 Windows 프런트엔드를
PID 19940으로 교체했다. 백엔드 19069, 기존 Python 소스와 이력 워커,
PR81 매출 구성 및 기존 배치·스크리닝 카탈로그를 계속 사용한다.
운영 전후 이력 응답이 일치했으며 SQLite 파일 SHA-256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로
동일하다. 검증용 프런트엔드 PID 35844는 종료했다.

보조 증거는 Windows 사용자 프로필 아래
`.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/financial-growth-20261109/`에
있다. `bundle-hashes.json`은 운영 파일 네 개, 생산기와 소스 SHA를 연결한다.
`artifact-check.json`은 1,241개 비교의 대조 결과다. `live-growth-report.json`은
실제 부호 사례 5건을 포함한 전년 비교 검사 3그룹과 AAPL 연간·TTM 및 차트 전환을
기록한다. `live-board-report.json`은 기존 보드 검사 15그룹을 기록하며, 두 검사는
총 18그룹이다. `hierarchy-live.json`은 Apple·Alphabet·Amazon의 공시
계층 검사 결과다. 운영 브라우저 오류, 콘솔 오류 및 차단 요청은 0건이었다.
`live-endpoint-report.json`은 50개사 응답 일치와 잘못된 발행 ID의 409,
누락 범위의 400을 기록한다. `preserved-input-hashes.json`과
`journal-before.json`, `journal-after.json`은 운영 전후 보존 증거다.

## 로컬 재시작

이전 프런트엔드가 종료되고 동일한 백엔드가 실행 중일 때 Windows
PowerShell에서 아래 명령을 실행한다. `bridge-growth.json`에 실제 실행
인자가 있고, 배포 파일 네 개의 해시를 확인한 뒤 같은 인자로 기동한다.
`release.cjs`는 최초 전환과 실패 시 이전 실행 인자 복구에 사용한 기록이다.
기동 후 `/api/status`, `/api/financial-growth`의 가용성 및 두 표시 파일의
해시를 확인한다.

```powershell
$release = Join-Path $env:USERPROFILE '.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/financial-growth-20261109'
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
const {args} = JSON.parse(fs.readFileSync(path.join(directory, 'bridge-growth.json')));
const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'bundle-hashes.json')));
const value = flag => {
  const index = args.indexOf(flag);
  assert.ok(index > 0 && args[index + 1]);
  return args[index + 1];
};
const files = {
  'windows-loopback-bridge.cjs': args[0],
  'app.css': path.join(value('--assets-root'), 'app.css'),
  'app.js': path.join(value('--assets-root'), 'app.js'),
  'financial-growth.json': value('--financial-growth'),
};
assert.equal(value('--financial-growth-sha256'), manifest['financial-growth.json']);
for (const [name, file] of Object.entries(files)) {
  const digest = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  assert.equal(digest, manifest[name], name);
}
const log = fs.openSync(path.join(directory, 'bridge-growth.log'), 'a');
const child = spawn(process.execPath, args, {detached: true, windowsHide: true, stdio: ['ignore', log, log]});
child.once('spawn', () => { console.log(child.pid); child.unref(); });
child.once('error', error => { console.error(error); process.exitCode = 1; });
fs.closeSync(log);
'@ | node - "$release"
```
