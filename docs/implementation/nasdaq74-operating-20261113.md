# 기존 50개사와 신규 24개사 운영 연결

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
