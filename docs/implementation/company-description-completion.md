# 회사 설명 인프라 완료·로컬 인수

기준일은 **2026-10-10 KST**다. 최종 제품 소스는
`51aeff7665a1f09e4bab2cce562b2250e0f316a0`이며, generic plain-text
collector/importer, 불변 publication, portable reader와 선택적 회사 profile 표시를
구현했다. 별도 독립 검증이 PASS했고 lead는 이 범위를
**LOCALLY_ACCEPTED_INFRA_ONLY**로 인수했다. 이 문서를 담은 docs-only commit은 제품
소스와 별도이며 handoff에서 정확한 SHA를 보고한다.

## 완료 범위

- 관리자가 선언한 CIK·ticker·HTTPS URL·권리 범위·한국어 입력을 network I/O 전에
  검토하고, supplied text 또는 명시적으로 허가된 단발 fetch만 처리한다.
- manifest와 records 두 파일로 원자적 publication을 만들고, 외부 고정 manifest
  SHA와 정확한 R3 dataset/company identity를 검증한다. 게시 뒤 원본 plan·text를
  삭제·변경하거나 publication 디렉터리를 옮겨도 소비자는 embedded snapshot으로
  검증한다.
- raw HTML은 저장하지 않는다. 명시적 id/class selector의 한 요소에서 plain text만
  추출하고 script/style, 선택 영역 밖 문구, broad selector와 중복 id/class 속성을
  거절한다.
- 만료는 재무 service를 중단시키지 않고 설명·링크만 `RIGHTS_EXPIRED`로 숨긴다.
  description 옵션을 생략한 기존 API·UI·journal·export 동작은 유지한다.
- 실제 R3를 읽기 전용으로 사용한 별도 합성 publication은 21사 중 1건을
  `SYNTHETIC_DESCRIPTION_FIXTURE`, 20건을 explicit `UNAVAILABLE`로 표시했다. 이는
  실제 회사 설명이나 provider 허가 evidence가 아니다.

재무 Raw/Analytical/Derived Metrics, screening store schema, 회계·선택 정책과 actual
사용자 journal은 변경하지 않았다.

## 검증과 후보 이력

| 항목 | 결과와 증거 |
| --- | --- |
| 최종 독립 검증 | exact `51aeff7665a1f09e4bab2cce562b2250e0f316a0`, 109 relevant PASS / 0 SKIP. `work/company_descriptions_20261010/verification/51aeff-report.json`, SHA-256 `ca67ec49363777bbd51cbf2541613b4e43b781f8ff73ef6c8a1e6fa48fb59c7e` |
| Native Windows 확인 | 26개 물리 제어 PASS. `work/company_descriptions_20261010/native_final/browser-report.json`, SHA-256 `29c8b1e17686607aad422e9abfb90ff99846803fdbdf252f341b179c1e7aed23`; helper SHA-256 `40a2faf86060d200da363247809357aba32fce3bd0b24855f91b30bf2959af7d` |
| 합성 publication | `company-descriptions-863346570c8c420c515e3493`, manifest SHA-256 `0f4d2d8a0af36266719c08520f8f30345dbd6358d62d21b1049e04e555f0cbc3` |
| 보존 확인 | actual journal SHA-256 `fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c` 유지. 기존 21 profile·651 FY2025 slot·4 historical run 및 CSV/JSON/XLSX 호환 evidence는 변경되지 않은 e98 product blob에 대한 기존 검증을 정확히 재사용 |

Native 확인은 138자 한국어 multiline plain text와 script literal의 비실행, newline,
합성 표시, HTTPS `noopener`, source 새 탭, Tab/Escape/focus return, 1440·1024·768 폭,
draft 불변, POST 0과 page error 0을 확인했다. 첫 native FAIL은 새 화면 준비를 기다리지
않은 lead helper timing 오류였고 `browser-first-draft-helper-fail.json`에 보존했다.
수정된 helper가 같은 제품 소스에서 PASS했으며 제품 결함으로 재분류하지 않는다.

초기 후보 `e98fbf116bd25ad87e880aea37e0dae9742e892c`는 numeric IP의 축약·대체
표기가 private-address guard를 우회하고 HTML 중복 `id`/`class`가 last-wins로
선택되는 두 결함 때문에 독립 FAIL했다. 보고서는
`work/company_descriptions_20261010/verification/e98fbf-report.json`, SHA-256
`272026109925fa53463486919dfa06e08c36089a3ee0170be92ed32bb0079548`다. 최종 후보는
numeric alias를 network 전에 거절하고 selector 관련 중복 속성을 fail closed한다.
초기 작성자 전체 회귀 1,373 PASS / 38 SKIP는 e98 기준선이며 51aeff의 전체-suite
재실행으로 표시하지 않는다.

## 운영 상태와 남은 경계

실제 Investing.com 본문 취득·저장 건수는 **0**이다. 사용자의 비상업적 개인 투자
목적은 provider의 명시적 자동 접근·재표시 허가 evidence가 아니다. Apple profile
연결성 점검은 HTTP 403이었고 응답 본문은 읽거나 저장하지 않았으며 재시도하지
않았다. 따라서 actual 21사 설명 publication, provider 권리 확인과 live enablement는
**RIGHTS_DECISION_PENDING / BLOCKED**다. actual `127.0.0.1:18765` 서비스와 journal은
변경하지 않았다.

사용법과 offline 합성 점검은 [회사 설명 사용 안내](../usage/company-descriptions.md)를
따른다. 사용자 직접 walkthrough, push·PR·remote CI·main 병합은 미수행이다. `main`은
`201acf9aec2f8183acb7dd843579938db14236cd`에 남아 있으며, 독립 PASS와 로컬 인수는
provider 본문 사용 권리나 운영 배포 승인을 대신하지 않는다.
