# 스크리닝 준비된 변화 조건 v1

2026-11-14 승인. 기존 native100 소스 `5a8fe55775`를 보존한 별도 branch
`codex/screening-prepared-changes`에 main `deb074bc49`를 일반 merge한다.
단일 writer·별도 독립 reviewer와 기존 승인 모델 fallback을 유지한다. PR85
History 수정은 별도이며 이 작업에서 고치거나 병합하지 않는다.

## 입력과 권한 경계

실제 부모는 `universe-expanded-supported-100-20261025`, publication
`screening-cohort-union-c69e55ff570fce6fd927f1bb`, manifest SHA256
`8983258d3b6314feba883dc05d21ef535c2f139f8811bf0e006cad0daa025075`,
재무 기준일2026-10-25다. 원소스·manifest·approval·reader transition receipt는
변경하지 않는다. 전체 Python source hash와 native qualification의 기존 검사도
완화하지 않는다. 새 소스에서 구 receipt를 다시 쓰거나 자동 latest로 대체하지 않는다.

별도 프로세스가 **원래 수락 소스**로 기존 reader를 완전히 검증해 read snapshot을
export한다. exporter는 원소스 밖 도구이고 입력 source/artifact/pin을 전후 검사한다.
회사별 작은 단위로 기존 관측뿐 아니라 정의·버전·단위·기간·품질·결측·입력 참조·
trace·owner·회사 metadata·support·spine·latest를 그대로 보존한다. fixed rows와
latest_rows를 분리해 WDC의 최신 보충 분기를 유지한다. 새 물리 snapshot ID와
파일별/전체 논리 hash, 원래 logical dataset/publication/관측 ID를 구분한다.
ROOT의 정확한 별도 승인 전에는 reader가 이를 받지 않는다. 같은 logical ID/pub에
다른 snapshot 내용의 중복 등록도 거부한다. snapshot은 원 데이터 재생성이 아니다.

기존 catalog의 source-bound publication도 필요에 따라 같은 명시적 snapshot으로
읽어 과거 저장 결과를 유지한다. 변경된 native/producer 권한을 old reader에
전파하지 않는다. root가 실제 export·승인·파생 발행·복제 UAT·운영 전환을
수행하며 writer는 합성/명시적 cached 검사만 수행한다. 실제 Raw/cache/financial/
기존 Derived/journal 쓰기, live 서버·원격 작업은 금지한다.

## 새27개 정의와 계산 정책

일반 numeric YoY9개: operating_income, cfo, standardized_fcf 각각의 연간·
분기·TTM. ID는 각 원래 ID에 `_yoy`를 붙인 명시 목록이다. 비율 %p18개는
아래 원래 ID에 `_yoy_pp`를 붙인다.

- 연간7: gross_margin, operating_margin, net_margin, fcf_margin, current_ratio,
  liabilities_to_equity, liabilities_to_assets.
- 분기7: 위7의 명시적 quarter_ ID.
- TTM4: ttm_gross_margin, ttm_operating_margin, ttm_net_margin, ttm_fcf_margin.

revenue_yoy·quarter_revenue_qoq/yoy의 재차 %p와 실제 RATIO의 임의 %p는 제외한다.
목표 catalog는 연간41개·분기/TTM59개지만 실제 관측 가용성은 따로 집계한다.
현재 보드의50개사 보조자료만 복사하지 않고 부모100개사의 준비된 입력 전체를
대상으로 하되, 없는 이전 FY/TTM8 legs·연간 baseline·계보를 만들거나 backfill하지 않는다.

기존 v1/v2 비교 엔진과 정확한 Decimal 연산을 재사용하고 같은 계산을 복제하지
않는다. 연간은 직전 FY, 분기/TTM은 전년 같은 회계분기다. 기존 동일 회사/
정의·버전·단위·차원·기준·품질·날짜/연속성·재귀 입력·분모 검사를 유지한다.
금액은 prior>0/current>=0일 때만 일반 YoY이며 양수→0은 -100%다. 부호 전환,
prior0, 둘 다 음수, 음수→0은 numeric YoY UNDETERMINED와 원래 구체 state/
reason을 유지한다. 전환형/음수 축소율 조건은 추가하지 않는다.
비율은 공표 PERCENT 현재−전년의 정확한 percentage points이며 비율의 성장률이
아니다. 단위 PERCENT와 PERCENTAGE_POINT, definition version·input lineage를
명시하고 UI 기준값도 같은 단위를 사용한다.

새 catalog에는 comparison_of/comparison_kind/기간 관계를 명시한다. 상세·
다중 보드도 같은 새 공표 pair를 쓰고 조건 등록 표시로 연결한다. 새 변화 지표
자체에서 다시 변화 쌍을 만들지 않는다. old publication은 기존 aux 비교를 유지한다.

## 검증·인수

합성 단위/통합, Node와 Ruff/diff 및 가능하면 전체 pytest를 수행한다. 원소스
전후 변조/승인 누락·receipt mismatch·행/trace/owner/pub/기간/missing file 변조,
중복 logical scope 거부를 검사한다. sign9·정확 %p·작은 값·0·정의/분모/계보·
TTM gap/duplicate·fixed/latest 구분, 등록/조회/evaluation/threshold/export/저장/
재열기/휴지통 복제본을 검증한다. old50 aux의 같은 좌표 전수 값/상태를 대조해
차이가 있으면 source/gate 원인을 설명하기 전 발행을 보류한다. 회사×지표×기간의
가용/미준비 사유를 집계하고 전체100 준비를 추정하지 않는다.

리드는 실제 모든 catalog publication별 재열기 동등성, 대표 과거 saved run의
행/정렬/판정/ID/trace/CSV와 journal 원형을 private 복제본에서 대조한다.
현재 main의 cached History 실패가 나타나면 baseline으로 분리하고 이번 scope에
포함하지 않는다. 소스 동결·독립 검증·리드 승인·운영 반영은 각각 별도다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-14 명시 범위 GO |
| 구현 | 진행 |
| 실제 export/ROOT 승인/발행 | 리드 수행, 아직 미수행 |
| 독립 검증/로컬 인수/운영 | 대기 |
| 원격 전달 | 이번 새 기능은 미요청·미수행 |
