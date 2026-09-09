# U4 계속 갱신 — 제안 실행 계획

기준일 2026-09-09. 상태: **기존 U4 제안의 복구·문서 설계**.
이번 승인은 문서 7개와 로컬 커밋뿐이며, U4 코드·수집 실행·회계 승인 재사용·
원격 작업을 승인하지 않는다. 별도 U4 작업트리의 존재도 완료 증거가 아니다.
[계획 등록부](../planning/README.md)와 [U 로드맵](../planning/investor-analysis-roadmap.md)을 따른다.

## 목적과 그대로 지킬 계약

새 분기·새 기업에서도 같은 분석 구조를 유지한다. 회사별 설정, 제한된 검토 규칙
재사용과 예외 검토함, 실제 새 공시의 수집→검토→동일 소비자 갱신이 기존 목적이다.
미보유 입력은 Layer 1 수집부터 처리한다. 이미 있는 경로를 다시 만드는 일이 아니다.

[회사 관리](company-report-administration.md), [투자자 API](investor-analysis-interface.md),
[공시 검토](disclosure-review.md), [발견 입력](accession-contract.md),
[기간](period-rules.md), [Layer 2](layer2-longitudinal.md) 계약을 보존한다.
Raw/기존 발행본/검토 이력은 불변이다. 조회는 준비된 결과만 읽으며 준비 경로만
수집·파싱·계산한다. 설정 변경은 회계 승인이나 의미 연결을 대신하지 않는다.

## 기존 기능과 남은 격차

함수 존재와 검증 범위를 구분한다. 아래 코드는 기준 부모 `32212ca`에서 확인한
기능이며 U4 전체 구현 완료 표시가 아니다. 테스트 파일은 재현 지점이지 이번에
실행한 결과가 아니다.

| 기능 | 현재 함수·계약 근거 | 확인된 범위 / U4에서 남은 검토 |
| --- | --- | --- |
| 일반 기업 등록 | [company_reports.py](../../src/sec_xbrl/company_reports.py): `init_admin`, `register_company`, `_validate_companies`; 회사 관리 계약 | active/기간/publication 설정 존재. 새 기업별 엔진 분기 없이 설정/검토 절차를 연결해 검증 |
| 회사별 분석 설정 | [analysis.py](../../src/sec_xbrl/analysis.py): `prepare_catalog`, `_apply_lens_preferences`; API 계약의 `analysis_profiles.json` | core rows/순서/정확한 Axis/lens 표시 설정 존재. 운영 설정 이력·변경 영향과 예외 처리 UX 범위는 후속 확정; semantic edge 생성 금지 |
| 준비·상태 | `prepare_analysis`, `prepare_catalog`, `read_target_status`, `set_target_status` | prepared-only 조회 및 READY/NOT_PREPARED/REVIEW_REQUIRED/실패 등의 상태 존재. 입력 미보유·실제 미공시·실패가 새 운영 흐름에서도 구분되는지 검증 |
| 수집→Layer 1→분석 | [history.py](../../src/sec_xbrl/history.py): `discover_history`, `ingest_history`, `build_history`; `company_reports.refresh` | 기존 discovery/ingest/build 재사용. 캐시 snapshot 재사용, 캐시 package에서 새 파싱, live 다운로드는 서로 다름. 실제 새 대상은 미보유 단계부터 수행·증명 필요 |
| 갱신·소비자 연결 | `analysis.refresh_analysis` → `company_reports.refresh` → `prepare_catalog`; `open_analysis` | 호출 경로 존재. 새 공시 검토·추가 U3 companion 준비까지 포함한 동일 최종 화면 갱신의 연결된 수락 증거는 별도 필요 |
| 발행 포인터 | `prepare_catalog`의 `.partial-` staging, 성공 후 `analysis_current.json` 원자 교체 | 완성된 consumer bundle 뒤 포인터 교체. `refresh`의 등록표 갱신과 consumer 발행 전체가 하나의 트랜잭션이라는 보장은 없음; 각 실패 지점의 등록/포인터/이전 bundle 보존을 검증 |
| 정확한 검토 재사용·중단 | `company_reports.refresh`, [disclosure_review.py](../../src/sec_xbrl/longitudinal/disclosure_review.py): `ReviewedPublicationReader`, `publish_review` | 기존 exact source/candidate/decision/quality/quarantine 보존 재발행. 새 accession 또는 stale binding이면 `review_refresh_required.json`, 등록 보존 및 검토 중단. 신규 경제적 승인 자동 재사용 없음 |
| 검토 후 재개·예외 | `disclosure_review prepare/publish`, `review_queue`; API 계약의 “Resume a review-stopped refresh” | 명시적 검토·이력 추가·재발행·재등록·`prepare_catalog` 경로 존재. 새 공시를 끝까지 통과시킨 실제 운영 증거와 예외 검토함의 사용성은 후속 과제 |

단위 재현 지점:
[관리 검사](../../tests/test_company_reports.py)의 `test_manual_register_validation`,
`test_refresh_reuses_existing_workflow`, `test_report_settings_snapshot_and_new_run`;
[API 검사](../../tests/unit/test_investor_analysis.py)의
`test_refresh_preserves_decisions_or_registration`, `test_refresh_returns_openable_bundle_boundary`,
`test_catalog_bom_registration_and_query_pointer`, target-status 검사.
이들 mock/합성 검사는 새 공시의 실운영 완료를 대신하지 않는다.

## 보유 증거가 말하는 것과 말하지 않는 것

- U1/U2는 PR #62 / `7f8cc5232d0df3d4c184de55827111e599b94dbd`로 병합됐다.
  U3는 `3098be6db7622f2ec444a9979732b7dfaa685641`에서 로컬 인수 완료이며
  main 미포함이다. 664 passed / 16 skipped, Ruff, 캐시 기반 6사/84 Axis/
  10,824 화면 셀 결과는 U3의 증거다. NFLX 등록·준비·기간 갱신도 기존 캐시를
  사용했다. 모든 회사의 live 운영이나 신규 판단 자동화로 일반화하지 않는다.
- 별도 온라인 증거는 AAPL `0000320193-26-000020` 한 10-Q(보고 2026-06-27,
  제출 2026-07-31)의 실제 SEC 수집→새 Layer 1→새 분석 발행→준비 조회다.
  당시 `41e90c66c02cf0e5929b84449a61180612edc3f1` 소스 경로에서 확인했으며,
  기존에 다뤘던 accession의 재수집이다. 새 기업 3개년, 새 accession에 대한
  검토 승인, U3 최종 화면 자동 갱신이나 무인 운영 완료를 증명하지 않는다.
- 온라인 수집을 별도 감사자가 다시 실행한 것으로 기록하지 않는다. 독립 검증은
  생성된 intake/snapshot/분석 결과의 무결성과 조회를 확인했다. 캐시 package로
  새 Layer 1을 파싱한 AMD 증거도 live 다운로드와 별개다.

선택적 원본 보고서 locator는 [등록부](../planning/README.md)에 있다.
이 절이 범위와 한계를 담으므로 해당 로컬 파일이 없어도 계획을 읽을 수 있다.

## 제한된 검토 재사용과 예외 검토함 — 후속 설계 경계

현재 허용되는 exact source/candidate 재사용과 명시적 결정 이력 보존을 우선한다.
검토 규칙 재사용의 후속 제안은 적용 회사·출처/후보·개념·전체 차원·기간 종류·단위·
basis·유효 범위·정책 버전·검토자/실제 결정 시점·증거·철회 효력을 명시해야 한다.
이는 후보 검토의 효율화를 위한 설계 조건이지 새 accession의 경제적 의미를
자동 승인하는 규칙이 아니다. 교차 공시 의미/산식/share/Q4 승인을 넓히려면
구체 사례와 별도 리드 판단이 선행되어야 한다. 이번 문서는 그런 확대를 승인하지 않는다.

예외 검토함에는 새 공시/불일치/입력 부재/철회/미결정 원인, 정확한 원문과 영향
범위, 이전 결정, 다음에 필요한 자료를 남기는 흐름을 제안한다. 기존 A 해석,
B additive-Q4, quality WARN/BLOCK/RELEASE를 서로 대신 쓰지 않는다.
불완전한 근거는 기존 보류를 지키고 검토자로 반환하며 전역 경제 승인으로 묶지 않는다.

## 제안된 최소 실행 순서와 수락 증거

기능 구현과 외부 실행의 별도 승인을 받은 뒤 적용할 수락안이다.

1. **입력 고정:** 지원 SEC filer/form, 기존 성공 bundle/포인터, 회사 설정,
   이전 검토 이력, 실제 source as-of와 review cutoff, 새 대상 accession을 선언한다.
   지금은 대상 공시나 실행 날짜를 임의로 선정하지 않는다.
2. **수집/준비:** 기존 발견 계약으로 이전 성공 범위에 없던 공시를 확인한다.
   Layer 1 미보유이면 package/index 수집·Arelle 추출부터 진행한다. 단계마다
   live/cache/reused 여부와 accession/package/snapshot/manifest 해시를 기록한다.
   실패하면 입력과 실패 원인을 보존하고 가짜 값·DISCLOSURE_MISSING으로 성공하지 않는다.
3. **검토:** 새/변경 후보를 기존 검토함과 명시적 검토 경로로 처리한다. 이전
   decision·quality·quarantine을 유지하고 실제 검토 시각을 기록한다. 불일치는
   exception으로 남겨 이전 소비자를 보존한다. 자동 경제 승인은 사용하지 않는다.
4. **동일 소비자 갱신:** 유효한 준비/검토 결과로 새 immutable bundle과 필요한
   U3 hierarchy/Axis companion을 명시적으로 준비한다. 기존 `refresh_analysis`만으로
   모든 companion이 자동 갱신된다고 가정하지 않는다. 모든 필요한 결과의 무결성을
   확인한 후 발행 연결을 갱신하고 동일 API/화면의 새 기간·source/decision 식별을 확인한다.
5. **검증/동결:** 실제 새 공시 한 건의 연결된 수집→검토→같은 소비자 갱신 증거,
   이전 성공 발행본 재조회, 실패 지점별 등록/포인터 보존, 설정/period 변화,
   exact 재사용과 새/철회/불일치 검토의 중단·재개를 분리하여 검증한다.
   합성 경계·캐시 6사 회귀·live 한 건을 각각 보고하고 별도 검증자가 후보 SHA를 검증한다.

새 경제적 판단이 필요 없는 공시라면 검토 결과와 “왜 추가 승인이 불필요한지”를
기록한다. 그 사례만으로 신규 경제 승인 재사용까지 완료되었다고 주장하지 않는다.
필요한 재사용/예외 시나리오가 검증되지 않으면 잔여 범위를 명시한다.

## 실행자가 사용할 입력·재현 지점

정확한 함수 인자는 추적 [API 계약](investor-analysis-interface.md) 및 위 소스에서
확인한다. 등록은 `register_company`; 미보유 입력의 명시적 갱신은
`refresh_analysis(admin, workspace, as_of, review_as_of, tickers, ...)`;
검토 중단 후 재개는 공시 검토의 `prepare`/`publish`와 이전 publication 이력,
이후 `register_company`/`prepare_catalog`를 사용한다. 이 문서 검토에서는 실행하지 않는다.

필수 실행 입력: Python 3.12 환경, 별도 admin/settings/decision 파일, 이전
publication 및 정확한 새 filing 선언, 수집 권한/SEC_USER_AGENT와 필요한 캐시,
새 출력 위치. unit 검사는 네트워크 없이, actual 검사는 명시한 cached fixture로,
live 단계는 승인된 네트워크 작업으로 따로 수행한다. checkout에 특정 `work/`나
도구 임시 계획이 있어야 한다는 전제는 없다.

후속 검증 명령의 출발점은 `python -m pytest tests/test_company_reports.py
 tests/unit/test_investor_analysis.py -q`(한 줄 명령) 및
`python -m ruff check --no-cache .`다. 실제 6사 회귀 입력/명령은
[U3 Axis 전달 계약](u3-axis-timeseries-delivery.md)에 명시되어 있다. 새 live 승인 흐름의
연결된 수락 검사는 미래 구현 범위에서 추가해야 하며 기존 unit 명령만으로 대체하지 않는다.
보고서에는 입력 선언, SHA/설정/검토/발행 해시, 단계별 live/cache 구분, 명령,
값/상태/출처 대조, 미실행/실패/미결정 사항을 담고 이전 증거를 덮어쓰지 않는다.

## 제외 및 인계

코드 변경, live 수집, 예약 자동화, 승인 범위 확대, U5 Excel, 원격 작업은 이번
문서 작업에서 수행하지 않는다. 상세 missing reason UX는 U3 재개 조건이 아니며,
실제 series bridge는 주요 분석 공백에 한정해 별도 Layer 2 근거 검토로 다룬다.
검토자는 구체 실행 범위와 회계 판단·발행 경계를 확정한 뒤 구현을 위임한다.
