# 기존 자료를 보존한 Nasdaq 준비 회사군 운영 연결

2026-11-13 현재 구성 목표는 **92개사(기존50+완료24+추가18)**다. 아래74개사는
최초 승인 범위의 기록이다. 추가18의 native 통합/projection 완료를 리드가 확인했고,
새92 구성은 아직 union 발행·운영 완료를 뜻하지 않는다.

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
