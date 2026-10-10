# 회사 설명·외부 프로필 전달 계약

## 1. 승인과 현재 상태

기준일은 **2026-10-10 KST**다. 사용자는 한국어 회사 소개 기능을 추가하고
Investing.com을 우선 기준으로 진행하려는 제품 의도를 승인했다. 다만 콘텐츠
복제·편집·번역·요약·파생물 작성·자동 접근의 이용 방식과 권리 근거는 확정하지
않았다. 따라서 이 계약은 **PROPOSED**, 보호된 Investing.com 본문의 취득·게시는
**RIGHTS_DECISION_PENDING / BLOCKED**다.

2026-10-10 검토한 [Investing.com 이용약관 PDF](https://cdn.investing.com/about-us/terms_and_conditions.pdf)의
section 10(a)는 개인적 이용 범위를, 10(b)는 콘텐츠 복제·편집·파생 이용에 대한
사전 서면 동의를, 10(c)는 자동 추출 제한을 둔다. 이 기록은 법률 판단을 대신하지
않는다. 다만 명시적 사용 근거가 없는 동안 제품이 제공자 본문을 보관·복사·번역·
요약하거나 crawler, scraper, headless browser, API proxy로 수집하지 않게 하는
release gate다.

[Investing.com 공식 API 안내](https://pro.investing-support.com/hc/en-us/articles/4408847632017-Do-You-Offer-API-Access-at-Investing-com)는
2025-05-19 갱신본에서 provider 계약 때문에 public API를 제공하지 않는다고 설명한다.
webmaster widget 안내가 있다는 사실만으로 회사 설명용 widget이나 본문 재사용 권한이
있다고 보지 않는다. 현재 회사 설명 widget은 확인되지 않았다.

현재 사용자에게 제시된 선택지는 다음 세 가지이며 아직 답이 확정되지 않았다.

1. **LINK_ONLY** — 회사별 Investing.com 프로필로 이동하는 검토된 링크만 제공
2. **LICENSED_SUMMARY** — 사용자가 이미 가진 재사용 허가나 별도로 확보한 서면
   허가의 정확한 범위 안에서만 공급된 요약문을 게시
3. **SEC_AUTHORED_REFERENCE** — 별도 승인된 SEC 출처와 작성 규칙으로 자체 설명을
   만들고 Investing.com은 참고 링크로만 표시

선택 전에도 21개 URL과 CIK/security identity의 읽기 전용 수동 확인은 할 수 있다.
보호된 본문 취득·저장·게시와 제품 화면 변경은 보류한다. 사용자가 한 방식을
선택하면 그 선택이 이 계약 범위의 구현 승인이며, lead가 입력·허용 파일·검증을
내부 위임 계약으로 확정한다. 범위가 달라지지 않는 한 반복 사용자 승인을 요구하지
않는다. 이번 작성자 위임은 문서만이며 push, PR, remote CI와 배포는 포함하지 않는다.

lead의 2026-10-10 읽기 전용 점검에서는 기존 backend homepage와 AAPL FY2025
profile이 HTTP 200이었고, 실제 사용자 SQLite SHA-256은
`fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c`로 유지됐다.
이는 기존 제품이 영향을 받지 않았다는 기준선이며 회사 설명 구현·인수를 뜻하지 않는다.

## 2. 데이터 평면과 불변 경계

회사 설명은 재무 Raw·Analytical·Derived Metrics가 아닌 독립적인 **provider
metadata plane**에 둔다. 기존 actual R3 screening publication, 31개 지표, metric
definition/version, SEC source trace와 사용자 screening journal은 읽기 전용 입력이며
새 publication이 이들의 ID·hash·값·결정 기록을 바꾸지 않는다.

흐름은 `verified company master + manually reviewed provider record 또는 authorized
supplied content → immutable company-description publication → read-only consumer`다.

재무 dataset에 설명 열을 덧붙여 새 재무 publication처럼 보이게 하지 않는다.
consumer는 CIK와 명시적 security identity로 두 publication을 연결한다. ticker,
회사명 문자열이나 provider 검색 결과만으로 연결하지 않으며 GOOG/GOOGL 같은
share class, issuer succession, ticker 변경을 보존한다. 설명 누락·권리 보류·stale
link는 재무 값의 품질이나 회사의 screening eligibility를 바꾸지 않는다.

제안하는 publication 최소 구성은 다음 두 파일이다. 권리 근거는 record 안에 두거나
manifest가 선언한 별도 파일로 둘 수 있다.

| 파일·record | 필수 내용 |
| --- | --- |
| `company_description_manifest.json` | schema/publication ID, 생성 시각, 입력 company-master ID·hash, config hash, mode, record 수, records SHA-256과 선언 파일 |
| `company_description_records.json` | CIK, optional security ID·ticker, provider ID/name, canonical URL, `checked_at`, link/status evidence, locale, summary 또는 null, rights basis ID·적용 기간·허용 변형, content hash |

`checked_at`은 사람이 해당 URL과 issuer/security identity를 확인한 시각이지 자동
수집 시각이 아니다. provider 이름과 URL만으로 본문 사용권을 추정하지 않는다.
최신 설명의 `checked_at`은 선택 FY·재무 as-of와 분리하며, 과거 FY 화면에서 현재
설명이나 링크를 당시의 역사적 사실처럼 해석하지 않는다.
허가가 만료되거나 범위가 맞지 않으면 summary를 `RIGHTS_BLOCKED`로 발행하고 이전
publication을 수정하지 않는다. 허가 문서나 비밀 정보는 Git·화면에 넣지 않는다.

## 3. source acquisition 설계

### 3.1 LINK_ONLY

관리자가 21개 회사의 현재 company master에서 CIK와 security identity를 읽고,
브라우저로 확인한 Investing.com company-profile URL을 명시적 입력 파일에 기록한다.
입력은 provider host, HTTPS, URL 정규화, 중복 CIK/security, redirect 목적지와 회사명·
ticker·issuer 불일치를 검토한다. 검색 결과 첫 항목이나 ticker 문자열만으로 URL을
자동 선택하지 않는다.

publication에는 링크와 확인 metadata만 들어가며 page title, description, 표,
수치, 이미지 또는 HTML을 저장하지 않는다. 화면은 “Investing.com에서 회사 정보
보기” 같은 자체 일반 문구와 마지막 확인일을 표시하며 provider label·tagline·logo를
복사하지 않는다. startup과 profile open의 external request는 0이고, 사용자가 링크를
명시적으로 눌렀을 때만 브라우저가 외부 사이트로 직접 이동한다. URL이
없거나 identity가 불확실하면 `LINK_UNAVAILABLE` 또는 `IDENTITY_HOLD`를 보여주며
다른 회사 링크로 대체하지 않는다.

### 3.2 LICENSED_SUMMARY

서면 허가가 확인되면 전달 파일, 수동 입력 또는 허가가 명시적으로 허용한 접근
방식만 사용한다. 원본 바이트 hash·provider·locale·적용 회사·허용된 편집/번역
범위·유효기간을 rights basis와 묶는다. importer는 입력 누락, CIK mismatch, 허가
범위 밖 locale/변형, 중복 record를 fail closed한다. runtime/browser의 on-request
scraping은 하지 않는다. 요약 갱신은 새 publication이며 이전 본문을 덮어쓰지 않는다.

### 3.3 SEC_AUTHORED_REFERENCE

이 선택은 SEC 제출자료에서 확인한 중립적 사실로 자체 문장을 작성하는 방식이다.
사용자가 이 방식을 선택하면 회사명·CIK, 최신 허용 filing/form/section, as-of,
표현 검토와 갱신 규칙을 lead가 구현 범위로 확정한다. 새 회계 정책을 만들지 않으며
SIC만으로 사업을 추측하거나 재무 수치로 서술을 합성하지 않는다. Investing.com
링크는 참고 이동 경로일 뿐 자체 설명의 출처·권리 근거로 위장하지 않는다.

## 4. API와 사용자 흐름 제안

구현이 승인되면 consumer는 재무 dataset과 별도로 description publication을 열고
CIK/security key 및 manifest hash를 검증한다. 일반 화면 응답의 제안 필드는
`company_description.status`, `summary`, `locale`, `provider_name`, `profile_url`,
`checked_at`, `publication_id`다. `summary`는 허용 mode에서만 non-null이다.
unknown mode, 누락된 rights basis, 변조된 파일/hash, foreign CIK 또는 중복 grain은
화면 시작 전에 거절한다. 승인된 catalog/config가 publication 밖에서 expected
manifest SHA-256을 고정하며, reader는 그 digest와 file-set을 함께 검증한다. HTTP
요청 중 provider에 접속하지 않는다.

최소 사용자 시나리오는 다음과 같다.

| ID | 사용자 행동과 기대 결과 | 보존 증거 |
| --- | --- | --- |
| D01 | 현재 21개 회사 프로필을 열고 해당 CIK/security에 검토된 외부 링크가 있으면 새 외부 페이지로 이동한다 | company master hash, source record ID, URL, `checked_at` |
| D02 | GOOG/GOOGL 또는 ticker 변경 회사를 열어도 issuer와 security 관계가 명시되고 다른 회사 설명이 섞이지 않는다 | CIK/security join 결과와 alias evidence |
| D03 | 링크가 없거나 stale/redirect mismatch이면 요약을 꾸미지 않고 unavailable/hold와 마지막 확인일을 보여준다 | status·reason, append-only review record |
| D04 | LINK_ONLY publication의 DOM/API/다운로드에는 provider 본문·번역·요약·HTML 조각이 없다 | response snapshot과 publication file scan |
| D05 | LICENSED_SUMMARY는 유효한 rights basis에 포함된 회사·locale·변형만 표시하고 만료·누락 시 차단한다 | supplied content hash, rights basis ID, review time |
| D06 | description publication을 바꾸어도 R3 재무 manifest와 실제 screening journal의 hash·행 수가 같다 | 전후 digest와 journal table counts |
| D07 | bundle을 함께 rehash하거나 CIK·URL·rights record를 바꾸면 pinned expected manifest hash와 달라 reader가 거절한다 | 독립 tamper fixtures |
| D08 | 외부 사이트 실패·offline에서도 재무 탐색과 screening은 정상이고 설명 영역만 복구 가능한 상태를 보인다 | network-free browser/API scenario |

## 5. 향후 구현·검증 gate

이번 문서 작성 범위는 구현이 아니다. 사용자가 세 mode 중 하나를 선택하면 그
route는 이 계약 범위에서 승인되며, lead가 입력 schema·허용 파일·화면 범위·
provider link 목록과 독립 검증을 구체화한다. 향후 수락 조건은 다음과 같다.

- 21/21 CIK가 정확히 한 상태(`LINK_AVAILABLE`, `LINK_UNAVAILABLE`,
  `IDENTITY_HOLD`, `SUMMARY_AVAILABLE`, `RIGHTS_BLOCKED`)를 가지며 silent omission 0
- provider URL은 수동 identity 검토에서, 본문은 수동·supplied artifact 또는 서면
  허가가 명시한 방식에서만 오며, 허가 없는 automated extraction과 on-request scraping 0
- immutable manifest와 file-set/hash, company-master binding, 중복 grain 및 path/
  URL 안전성 검증
- LINK_ONLY에서 copied text 0; LICENSED_SUMMARY에서 모든 non-null summary가 유효한
  rights basis와 content hash를 가짐
- 네트워크 없는 unit·consumer·HTTP/browser 시험과 별도 읽기 전용 독립 검증
- R3 financial publication과 실제 journal 전후 hash 동일

provider live 페이지의 수동 확인은 별도 evidence로 기록하고 unit test의 전제나
checkout 재현 요건으로 만들지 않는다. 독립 PASS, 로컬 인수, 사용자 직접 확인,
push/PR/main merge는 각각 별도 상태로 남긴다.
