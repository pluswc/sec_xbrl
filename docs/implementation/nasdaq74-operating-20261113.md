# 기존 자료를 보존한 Nasdaq 지원 92개사 운영 연결 — LIVE

2026-11-14(KST) **92개사(기존50+신규42) 로컬 인수·운영 적용 완료**다.
UI `e0c72852f0`/backend `0634eb50fa`, 18765(PID48788)→19072이며 기존19070은
rollback용으로 유지한다. 재무 기준일2026-10-25, 실제 준비 확인은
2026-11-13T14:49:22.469771Z다. 최종 실제 smoke는2026-11-13T15:06:32Z에
92개사·Phase2 이력 필터·JS 오류 없음을 확인했다. 개인 기록은 보존했고 WDC의
최신 발행 범위 밖 분기/TTM 및 나머지23개 추가 대상은 명시적으로 보류한다.
이 확장의 main 병합은 **NOT_MERGED**다. 아래74 승인·후보·중단은 당시 기록이며,
최종 인수 근거는 문서 말미에 구분한다.

## 승인 계약 (2026-11-13)

사용자는 완료한 자료를 재수집·재감사하지 않고 가능한 범위부터 운영에 연결하도록
승인했다. 기존 50개사와 새 회사군 003·004·006의 24개사를 합친 **74개사**가 대상이다.
이는 115개사 전체 완료나 Nasdaq 과거 구성 확정이 아니다. 재무 기준일은
`2026-10-25`, Nasdaq 구성 관찰일은 `2026-11-11`이며, 실제 조회 가능 확인 시각은
새 서비스를 검증한 뒤 등록한다. 옛 배치의 가용 시각을 소급해서 만들지 않는다.

기준 소스는 main `0a89d5cfdaf9bbe5c5d38acf809870ccac4add49`다. 수락된 469 union의
같은 기준일·spine·정의/버전 일치·고유 CIK 소유권 검사를 재사용한다. 기존 50개사의
추가 계산 지표는 유지하며 새 회사군의 없는 지표는 unavailable이다. 소유 부모의
회사/업종 메타데이터를 유지하고 미준비 사본으로 덮어쓰지 않는다.

입력은 기존 여섯 catalog, 기존 50 projection과 6064에서 발행·검증된 세 신규
combined/projection이다. 기존 Raw·History·분석·발행물·승인·저장 기록은 불변이다.
6064/401/882/B 소스도 수정하지 않는다. projection을 읽는 소비자 연결이므로
완료한 부모 reader·수집·회계·품질 검사를 다시 수행하지 않는다.

## 보조자료와 화면

기존 실제 데스크톱 JS/CSS와 여섯 catalog 항목을 보존한다. UI 변경은 보조자료의
정확한 소유 부모 확인뿐이며 CSS/배치 재설계는 하지 않는다. 명시적으로 pin한
union 소유자 연결에서만 기존 50개사 growth/매출 구성 자료를 위임한다. 응답은
union 요청 범위, 원본 `source_scope`, 소유권 증거를 구분하고 원본 header를
재표기하지 않는다. UI는 CIK·발행물·기준일·manifest pin을 검증한다. 새 24개사의
매출 구성이 없으면 명확히 표시한다. 전년 비교는 기존 v2 helper를 기존 projection에
적용할 수 있는 최소 경로만 허용하며, 불가능하면 비교 자료 미준비로 표시한다.

## 변경·전달 범위

`screening/{cohort_union,service,cli,runtime_projection}.py`, loopback bridge,
필요한 기존 financial-comparison/growth helper와 companion JS, focused tests,
이 계약 및 계획 등록부만 변경한다. 새 회계·parser·source compatibility·schema·
journal 정책은 만들지 않는다. 기존 저장/열기/내보내기 동작은 유지한다.

자체 focused 검사 뒤 로컬 commit을 동결하고 별도 읽기 전용 검증과 리드 수락을
받는다. 그 뒤 기존 자료만 읽는 union/catalog·배치 등록·private UAT 및 rollback
명령을 구체화한다. 운영 전환은 리드 GO 이후다. main/push/운영 전환은 현재 미수행이다.
AEP/PLTR/RKLB/APP/TER/CRWD 보류 및 partial7·ISRG 후속 발행은 별도다.

관련: [전달 절차](delivery-workflow.md),
[분석 데이터 모델](../architecture/analytical-data-model.md).

## 완료한 동료 18개사의 추가 진행 승인

리드는 기존 실패한 10개사 scope를 보존한 채 `001-ready9`(APP 제외),
`005-ready9`(TER 제외)의 새 명시적 scope 진행을 승인했다. 각 회사의 기존 401
routine 수락을 재사용하며 Raw·History·분석·occurrence는 다시 만들지 않는다.
아직 완료하지 못한 정상 quality/identity/metrics 단계만 수행하고, 운영 승인은 별도다.
002의 10개사 quality는 이미 완료됐으므로 이를 재실행하거나 9개사로 재표기하지 않는다.

두 새 부모가 6064 native 경계와 별도 리드 수락을 통과하면 **새 92개사 union 발행물**을
선택할 수 있다. 준비가 늦으면 74개사부터 연결하고 이후 새 발행물로 확장한다.
소스/UI의 회사 수는 manifest에서 읽으며 74/92를 엔진의 고정 한계로 두지 않는다.
이 추가 승인은 전체115 준비나 보류한 회사의 해결을 뜻하지 않는다.

## 구현 후보 전달


소스 후보는 엄격한 union과 명시적 owner envelope 연결이다. opt-in union 설정의
`expose_auxiliary_owners: true`만 정확한 고유 부모의 범위를 manifest에 결속한다.
기본 설정의 기존469 의미는 유지한다. `cohort-union --config PATH --destination PATH`로
불변 union을 만들고, `serve --cohort-union DATASET_ID MANIFEST_PATH SHA256`와
기존 네 projection 선언을 함께 사용한다. 기존 여섯 catalog 항목은 바꾸지 않는다.
Bridge의 새 옵션은 `--auxiliary-union ABSOLUTE_MANIFEST_PATH --auxiliary-union-sha256 SHA256`다.
원본 보조자료 bytes·header를 유지하며 union 응답에 요청/출처/소유권 증거를 구분한다.
신규 회사의 없는 보조자료는 명확히 미준비로 표시한다. CSS와 기존 데스크톱 배치는 불변이다.

Focused 검사는 Python 6개(단위/union/service/Node wrapper), Node owner 4개,
관련 explorer 41개·growth 3개·매출 구성 11개 통과, Ruff·diff 통과다. 합성·소비자
검사이며 완료한 실제 회사 감사·수집을 반복하지 않았다. 독립 소스 검증과 리드
수락 전에는 새 union/서버를 실행하지 않는다. 이후 private journal 복제본으로
새 조건 저장·재열기 및 필요한 휴지통 복원만 검증하고 실제 journal은 GET/해시
검사만 한다. 기존 backend19070과 되돌릴 catalog·assets를 유지한 채 별도 포트에서
검증한 뒤 리드 GO로 전환한다. 실제 배치 등록은 서비스 조회 성공을 확인한 현재
시각에 수행하며 기존 등록 이력은 보존한다. 실제 운영 수락은 별도 후속 기록이다.

## 2026-11-13 private 후보 수락과 운영 보류

소스 `77ead1e1f9`는 독립 검증·리드 수락을 통과했다. 2026-10-25 기준 92개사
union 후보와 private19071/preview18881에서 기존 여섯 catalog·보조자료 보존,
조회 및 복제 journal의 저장·재열기·CSV·기존 휴지통 복원을 확인했다. 실제 journal은
불변이다. 이는 private 수락이며 운영92 수락이 아니다. 기존 운영 frontend27800·
backend19070은 유지하고19072 시작과18765 전환은 보류했다.

읽기 전용 조사에서 신규42개사 중39개사의 분기 분석이 현재 FY 중간 분기를
제외했음을 확인했다(ADP/LITE/PANW는 재사용 가능). 기본 `fiscal_years=5`가
완료 연간 FY로 범위를 추론한 결과다. ABNB의 수집 계획에는 2026Q1/Q2 공시가
있지만 분석은 2025Q4까지다. 여기서 `NO_FILING_AS_OF_CUTOFF`는 Raw 공시 부재를
뜻하지 않는다.

**제안·미구현**: 기존 공개 API의 명시적 분기 FY 범위로39개사 새 분기 분석과
이에 결속된 identity·연간 metric 부모 재결속·분기 metrics·native combined·
projection을 발행한다. 기존 연간 분석·Raw·History·완료 감사/quality는 재실행하지
않고 연간 수치 동일성을 확인한다. 일부 과거 분기 materialization은 겹친다.
반복을 없애는 별도 incremental carry 계약은 더 큰 대안이다. 사용자 답변 대기 중이며
수정·재생성·운영 전환은 시작하지 않았다. private 후보는 종료하고 등록을
`CANDIDATE_ONLY_NOT_ACTIVE`로 취급한다. 수정 발행물은 향후 성공 확인 시각을
새로 등록해야 하며 이번 후보의13:16 UTC 관측 시각을 재사용하지 않는다.

근거는 `work/nasdaq100-expansion-20261111/` 아래
`quarter-coverage-readonly-20261113.json`,
`operating92-77ead1e1f9/private-uat-acceptance.json`,
`operating-source-root-acceptance.json`, `operator-latest-checkpoint.json`이다.

## 2026-11-13 분기 범위 정정 승인

사용자는 기존 API의 명시적 FY 범위로39개사 분기 분석을 새로 준비하고 관련
identity·연간 metric 재결속·분기/native/projection을 새로 발행하는 안을 승인했다.
Raw·History·quality·연간 분석과 ADP/LITE/PANW 분기 분석은 재사용한다. 연간 수치와
원본 출처 동일성을 확인하고,39개사의 최신 분기 coverage 통과 후 새 발행물의 실제
조회 성공 시각을 등록한다. 기존 후보·실패 기록·journal은 보존한다.

`tools/nasdaq100_quarter_window.py`는 pin된 단일 회사 입력의 AVAILABLE QTD
header에서 최근5개 FY 범위를 확인하고 동결401의 공개 `prepare_analysis`에 명시적
범위를 전달하는 worker다. 기존 분기 기본 profile·공시 근거 옵션은 유지한다.
자원 제한·heavy lock·재개·진행 표시는 기존 운영 driver를 재사용한다. 도구 동결과
독립 검증·리드 GO 이전에는 실제39개사 실행을 시작하지 않는다. 운영 연결은
후속 coverage/연간 동일성/private 검증 및 리드 GO를 별도로 요구한다.

도구 CLI는 `python /ABS/operating-source/tools/nasdaq100_quarter_window.py --plan
/ABS/plan.json --plan-sha256 SHA --ticker TICKER --result /ABS/new-result.json`이다.
실행 환경의 `PYTHONPATH`는 동결401의 `src`와 root를 사용한다. 계획은
`nasdaq100-quarter-window-v1` 및 정확한401 commit/source root, 회사별 History·연간·
분기 manifest pin, 새 destination과 명시적 FY bounds를 담는다. worker는 기존
출력에 덮어쓰지 않으므로 재개 여부는 기존 driver의 완료 receipt 검증으로 결정한다.
합성 focused3개(현재 FY 선택·pin 변조·공개 API 인자/중복 실행 거부), 해당 Ruff·diff
검사를 통과했다. 실제39개사 준비와 독립 검증은 아직 수행하지 않았다.

## 최신 실제 분기가 발행 범위 밖인 경우

39개사 명시적 분기 준비는 완료했다. 일부 회사의 최신 실제 분기 종료일은 기존
8개 달력분기 발행 범위 밖일 수 있다. 리드는 범위를 넓히거나 이전 분기를 최신으로
표시하는 대신, 해당 회사의 최신 분기/TTM 조회를 명시적으로 미준비 처리하는
공통 소비자 경계를 승인했다. 연간·고정 분기와 기존 여섯 catalog 의미는 유지한다.

새 union의 선택적 `latest_source_coverage: {path, sha256}`는
`screening-latest-source-coverage-v1`, `financial_as_of`, `records`를 담는다.
각 record는 `cik`, `owner_manifest` pin, `analysis_manifest` pin 및 `latest_qtd`
(`fiscal_year`, `fiscal_quarter`, `period_start`, `period_end`,
`end_convention: EXCLUSIVE`)다. 고유 소유 부모의 정확한 quarterly manifest/config와
분석 manifest·AVAILABLE QTD header의 최신 실제 기간을 hash로 결속한다.
중복·불일치·변조는 거부하며 실제 범위 밖 anchor만
`LATEST_SOURCE_PERIOD_NOT_PUBLISHED` / ‘최신 분기 조회 자료 미준비’로 처리한다.
이때 최신 탐색·비교는 값 없음, 최신 시계열은 빈 관측과 실제 anchor/사유,
스크리닝은 UNDETERMINED다. 숫자/재무 관측을 만들거나8분기 정책을 변경하지 않는다.
이 경계는 후보 구현이며 실제 교정 발행물·coverage 검증·운영 수락은 별도다.

합성 경계2개와 관련 최신 조회9개를 통과했다(HTTP 한 건은 sandbox 소켓 제한으로
host에서 단독 확인). owner/header 변조·최신 tuple 불일치·중복 CIK 거부와 분기/TTM
시계열·비교·탐색·스크리닝 보류, 기존 연간/고정 분기·다른 회사 보존을 검사했다.
해당 Ruff, JS syntax, diff 검사 통과이며 실제 재무 발행/운영 검증은 별도다.

실제 header의 과거 AVAILABLE 행 중 날짜가 없는 경우에는 날짜를 만들지 않는다.
완전한 날짜가 있는 최신 QTD만 사용하며, 같은 FY/Q 이상인 미확정 날짜 행이나
날짜 있는 최신 후보의 충돌·부재는 거부한다. 해당 경계 합성 검사1개를 추가 통과했다.

## 동시 적용된 Phase2 화면 보존

운영 전환 직전 PID/명령 검증에서 별도로 수락·적용된 Phase2 화면을 확인해 전환을
중단했다. `745bc76e3a`의 JS/CSS·관련 테스트와 Phase2 계약만 선택적으로 통합했다.
CSS는 해당 운영 자산과 byte 동일하며, JS는 기존 owner/최신 미준비 경계만 추가로
유지한다. backend0634·교정 재무 발행물·private 저장/재열기/CSV 검증은 재사용하고
재시작·재계산하지 않는다. Phase2 8개·owner 4개·display 5개 검사와 JS syntax·diff
검사를 통과했다. 새 표시 자산의 독립 검증·preview와 운영 전환은 별도다.

## 2026-11-14(KST) 실제 운영 인수

리드는 독립 검증된 UI `e0c72852f01ea47ed452982de548d9ff99db720b`와 backend
`0634eb50fa22b3635a59ad5067f2930c93b090a6`의 Python 동일성을 확인하고,
Phase2를 보존한 18765(PID48788)→19072(PID1347405/start54415707) 연결을 수락했다.
기존19070은 rollback용으로 유지한다. 이 확장의 main 병합은 **NOT_MERGED**다.

교정 발행물은 `universe-expanded-supported-92-corrected-20261025`, publication
`screening-cohort-union-d2758cfe339736fa18366711`, manifest SHA
`b6e8c28d0025ff3abbbadcaeaf26a5f69db11755c3be169ab8c7c01c01c93b31`다.
재무 기준일은2026-10-25이며, 최신 기간 조회 성공 후 실제 준비 확인을
2026-11-13T14:49:22.469771Z에 새로 등록했다. 앞선 부정확한 후보와13:16 등록은
역사 자료로 보존하고 활성화하지 않았다.

39개 분기 분석을 정정하고 ADP/LITE/PANW 세 분석은 재사용했다. 연간72개 파일은
byte 동일하며 Raw·History·연간 분석·quality 및 완료한 깊은 감사를 반복하지 않았다.
실제39개 최신 기간 일치, ABNB2026Q2 매출3,608,000,000 USD와 WDC 최신 분기/TTM
명시적 미준비·고정 분기 유지, 기존 여섯 catalog/보조자료를 확인했다. Private 복제본의
교정 발행물 저장·재열기·CSV는 통과했고 이전 휴지통 복원 증거는 재사용했다.
동시 적용된 Phase2의 지표/이력 필터·92개사/ABNB/WDC 화면은 오류 없이 확인했다.
개인 journal hash `3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`와
기존 이력 응답을 보존했다. Private19071은 소유권 확인 후 종료했다.

92개사 안에서도 준비되지 않은 지표·신규 기업의 보조자료는 미준비로 표시한다.
WDC는 포함되지만 기존8분기 발행 범위 밖 최신 기간은 보류한다. 별도23개 추가 대상
(APP/TER/CRWD와 그 미발행 동료, partial7, ISRG, AEP/PLTR/RKLB)은 기존 보류를
유지하며, 전체115 완료를 주장하지 않는다.

운영 근거는 `work/nasdaq100-expansion-20261111/operating92-corrected-b13fc5/`의
`union-publication.json`, `batch-registration.json`, `private-uat-acceptance.json`,
`live-backend-ready.json`, `private-backend-final-stop.json`과 Windows
`nasdaq-operating-20261113/quarter-corrected/phase2-integrated/live-switch.json`이다.
최종 smoke(2026-11-13T15:06:32Z)와 backend PID/start 및 보호 파일5개·개인 journal
보존은 같은 운영 근거 폴더의 `root-final-preservation.json`으로 확인했다.
독립/로컬 수락·운영 연결·향후 main/CI 상태는 별개로 유지한다.
