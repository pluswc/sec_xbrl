# 근거가 있는 매출 성장률과 최신 실제 분기 교정

## 승인 범위

2026-11-14 사용자는 기존92개사 자료·기록을 보존하면서 가능한 공통 규칙으로
Alphabet의 보고 항목 전환과 WDC의 최신 실제 분기 누락을 해결하도록 승인했다.
기존 정의/발행물·8개 완료 달력분기·native/source 호환 승인과 parser/History는 바꾸지 않는다.

새 `screening-governed-delta-v1`은 정확한92개사 union manifest를 부모로 공유한다.
새 정의 버전의 `revenue_yoy` 관측을 발행하며 기존 값은 원래 관측 ID와 출처를
계보에 보존해 version adoption한다. 같은 현재 공시의 직접 보고된 전년 비교 값이
원래 선택한 전년 값·실제 기간·USD·연결 범위와 정확히 같고, 현재 매출과 같은 raw
concept인 typed primary IS 근거가 있어야 새 연속성 경로를 허용한다. 태그만 같거나
금액만 우연히 같은 근거, 재작성 금액 차이·충돌·기준일 이후 증거는 거부한다.

최신 실제 분기 추가는 pin된 회사 분석의 rows/cells/trace와 기존 public
`build_quarterly_company_records`를 사용한다. 실제 종료·공시가 기준일 이내인
회사 완료 분기만 추가하고 TTM은 기존4분기 정책을 그대로 적용한다. 기존 고정
8분기는 그대로 조회하며 최신 경로만 추가 관측을 사용한다. 없는 값은 만들지 않는다.

Producer가 계산/증거를 확정해 불변 artifact를 만들고 reader는 root가 승인한
정확한 artifact·부모·source pin과 발행값만 읽는다. 현재 main을 옛 native packet으로
허용하지 않는다. 기존 projection/부모 reader와 auxiliary owner를 공유하며
저장·비교·출처·최신 시계열이 같은 새 발행물에 결속돼야 한다.

## 전달 상태

격리 branch `codex/governed-latest-revenue-delta`, 기준 main `3cfe1b79fc`에서 구현 중이다.
합성 focused 검사·소스 동결·독립 검증 뒤 리드가 실제 후보 발행/운영을 수행한다.
기존 회사 감사·Raw/History 재생성·network·개인 journal 쓰기·운영 전환은 수행하지 않는다.

## 병행하는 보류 대상의 실행 경계

리드는 partial7(ALAB/CRWV/GEHC/HONA/SHOP/SNDK/SPCX)의882 소스와 ISRG의B20ec
소스로 정상 quality8개 완료를 수락했다. 누락된 현재 FY 분기는 ALAB/CRWV/GEHC/
SHOP/ISRG 다섯 회사만 기존 공개 API의 명시적 범위로 새로 준비한다. Raw·History·
연간 분석·완료 quality는 다시 실행하지 않는다. 이들 native source qualification은
기존401 전용 경계와 별도이며 이번 delta 코드에서 자동 허용하지 않는다.

cohort002 열 회사는 CRWD의 실제 연간 공시5개가 있으나 History FY label 충돌이
있어 미발행 동료9개와 함께 보류한다. APP/TER는 optional inline ID를 locator가
필수 취급하는 경계, AEP는 승인된1시간 History timeout, PLTR/RKLB는 non-inline
ZIP entrypoint 경계로 보류한다. 이 원인들을 해소하는 코드·재처리는 이번 범위가 아니다.

## 발행·실행 인터페이스

후보 준비는 `python -m sec_xbrl.screening governed-delta --config /ABS/config.json
--destination /ABS/new-publication`이다. 설정schema는 `screening-governed-delta-config-v1`,
`dataset_id`, 부모union의 `parent: {path, sha256}`, `annual_bridges`,
`latest_quarters`다. 실제 설정 제안은
`work/governed-latest-revenue-delta-20261114/candidate-config-proposed.json`에 두며
Alphabet FY2022/FY2025 원래 Raw manifest/8개 table pins·entry·원래 prior snapshot,
WDC owner/분석/quarter manifest pins를 선언한다. 설정만 만들었으며 실제 발행은 미실행이다.

Publisher는 바뀌지 않은 growth를 compact core+원래 ID 참조로 유지하고 필요한
상세만 부모reader에서 가져온다. 새 완전한 증거는 실제 교정 관측에만 저장한다.
바뀐 growth의 support 건수는 producer가 발행값으로 만들며 다른 support는 보존한다.

리드는 독립 검증 뒤 새 manifest pin과 전체 Python source/bridge hashes를 확인해
별도 파일에 `{schema_version: screening-governed-delta-approval-v1,
status: ROOT_APPROVED_GOVERNED_DELTA, manifest: {path, sha256},
implementation_sources: <manifest와 같은 map>}`을 쓴다. 무승인·source 차이는 거부한다.
실행 시 기존 catalog/projection/union 지정에
`--governed-delta DATASET_ID MANIFEST_PATH SHA256 APPROVAL_PATH APPROVAL_SHA256`
을 더하고 catalog에 정확한 부모union을 유지한다. 같은 부모reader를 공유하며
회사 감사를 다시 열지 않는다.

Bridge는 새delta의 명시적 pin 외에 `--auxiliary-union-parent HOST_FILE
--auxiliary-union-parent-sha256 SHA256`을 요구한다. Windows의 HOST_FILE은 원래
Linux 부모union과 byte 동일한 복제본이고 SHA는 delta.parent와 같아야 한다.
원래 Linux 참조는 바꾸지 않는다. 기존union 호출은 그대로다.

최신 profile/비교 차트는 API의 공표된 `latest_company_periods`만 정확한
dataset/publication/cutoff로 검증해 좌표에 더하고 최근8점을 표시한다. 고정8분기
선택지는 보존한다. 연간 매출성장률 board는 profile API 발행값과 새 definition/
proof metadata를 사용하며 UI 재계산·기존 보조자료 fallback은 하지 않는다.
기존dataset과 다른 지표의 보조자료는 보존한다.

나머지8개사의 병행 준비는 quality2·분기5·occurrence2·financial8의 총17개 신규
실행을 완료했다. 근거는 `work/nasdaq100-expansion-20261114/remaining23/` 아래
`completed-first-financial-output-inventory.json`, `financial-followup2-full-v2-summary.json`이다.
native882/B20ec qualification은 제안 단계이며 운영92를 확대한 것은 아니다.
