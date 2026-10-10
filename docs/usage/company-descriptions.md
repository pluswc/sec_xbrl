# 회사 소개 plain-text 준비와 선택적 표시

기준일은 **2026-10-10 KST**다. 이 기능은 검증된 screening dataset에 CIK·ticker로
묶인 한국어 plain text를 별도 불변 publication으로 준비한다. 재무 dataset과 사용자
journal은 수정하지 않으며, publication을 명시하지 않은 기존 server 동작은 그대로다.

사용자는 비상업적 개인 투자 용도로 Investing.com 기준 텍스트 연결·수집을 원했다.
그러나 비상업적 목적만으로 해당 제공자의 자동 접근·복제·재표시 허가가 확인된 것은
아니다. 일반 `urllib` 연결성 점검도 Apple profile에서 HTTP 403을 받았고 본문을
읽거나 저장하거나 재시도하지 않았다. 그러므로 아래 명령과 schema는 구현되어 있지만,
명시적 권리 근거가 없는 Investing.com plan은 `PENDING`으로 두며 실제 fetch를 실행하지
않는다. anti-bot, CAPTCHA, paywall 우회와 on-request fetch는 지원하지 않는다.

## 입력 plan과 사전 점검

plan은 screening dataset 전체 회사마다 정확히 한 행을 가진다. `AVAILABLE` 행은 CIK,
ticker, HTTPS profile URL, provider, `ko` locale, 확인·관찰 시각, rights reference와
유효기간을 요구한다. 아직 URL이나 권리 근거를 확인하지 않은 회사는 URL·시각을
꾸며내지 않고 `UNAVAILABLE`과 구체적 이유를 기록한다.

`PROVIDED_TEXT`는 `rights_scope=DISPLAY_PLAINTEXT`와 UTF-8 파일을, `AUTHORIZED_FETCH`는
`rights_scope=FETCH_AND_DISPLAY_PLAINTEXT`와 명시적 `#id`, `.class`, `tag#id` 또는
`tag.class` selector를 사용한다. `html`, `head`, `body`와 bare tag처럼 페이지 전체를
가리킬 수 있는 selector는 거절한다. fetch 권한은 `APPROVED`이고 당일 유효해야 한다.

```bash
PYTHONPATH=src /path/to/project/.venv/bin/python -m sec_xbrl.screening \
  descriptions-prepare --plan /path/to/plan.json \
  --dataset /path/to/screening_dataset --dry-run
```

이 점검은 network와 destination write를 수행하지 않는다. 차단 행이 있으면 종료 코드
2와 `blocked_count`를 반환한다. 실제 publication은 모든 available 행이 통과할 때만
새 destination에 원자적으로 작성한다.

```bash
PYTHONPATH=src /path/to/project/.venv/bin/python -m sec_xbrl.screening \
  descriptions-prepare --plan /path/to/plan.json \
  --dataset /path/to/screening_dataset \
  --destination /new/immutable/company_descriptions
```

출력의 `manifest_sha256`을 publication 경로 밖의 승인된 catalog/config에 고정한다.
원본 plan과 supplied text는 생산 증거이며 runtime 의존성이 아니다. 게시 후 원본이
이동·삭제·변경되어도 embedded normalized plan과 두 publication 파일만으로 검증한다.

```bash
PYTHONPATH=src /path/to/project/.venv/bin/python -m sec_xbrl.screening \
  descriptions-status --publication /new/immutable/company_descriptions \
  --manifest-sha256 "$DESCRIPTION_MANIFEST_SHA256" \
  --dataset /path/to/screening_dataset
```

권리가 자연 만료되면 publication 자체를 손상으로 보지 않는다. profile projection은
본문과 source link를 숨기고 `RIGHTS_EXPIRED`를 반환하며 재무 탐색은 계속된다.

## 선택적 local server 연결

두 description 옵션을 생략하면 기존 API·화면이 설명 publication을 읽지 않는다.
사용할 때는 financial catalog가 포함하는 동일 dataset의 publication과 외부 고정 SHA를
함께 지정한다. startup·profile open은 provider에 접속하지 않는다.

```bash
PYTHONPATH=src /path/to/project/.venv/bin/python -m sec_xbrl.screening serve \
  --catalog /path/to/catalog.json --store /tmp/isolated-journal.sqlite \
  --exports /tmp/isolated-exports --host 127.0.0.1 --port 18920 \
  --descriptions /new/immutable/company_descriptions \
  --descriptions-manifest-sha256 "$DESCRIPTION_MANIFEST_SHA256"
```

## 합성 화면 점검

다음 helper는 지정 dataset을 읽기만 하고 AAPL CIK 한 건에 `example.invalid` 출처의
명시적 합성 한국어 설명을 만든다. 나머지 회사는 null URL·null 시각과 이유가 있는
`UNAVAILABLE`이다. 실제 제공자 콘텐츠가 아니며 actual journal이나 127.0.0.1:18765에
연결하지 않는다.

```bash
PYTHONPATH=src /path/to/project/.venv/bin/python \
  examples/screening/prepare_synthetic_company_descriptions.py \
  --dataset /read-only/screening_dataset_r3 \
  --workspace /tmp/company-description-ui-check
```

helper 출력의 publication과 manifest SHA를 위 `serve` 명령에 넣고 새 `/tmp` journal,
새 port로 확인한다. 화면은 본문을 DOM `textContent`로 넣고 `합성 소개 예시`, source,
확인일을 표시한다. source anchor만 사용자의 명시적 클릭으로 열리며 HTTPS와
`noopener noreferrer`를 강제한다. 설명이 없거나 만료된 회사의 일반 profile에는
빈 설명 panel을 만들지 않는다.
