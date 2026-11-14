# 남은15개사 준비 근거 재사용과 9개사 분리

## 승인·상태

2026-11-14 사용자는 LIVE100·개인 기록을 보존하며 완료 자료를 재사용해 남은
대상을 해결하도록 요청했다. 리드는 우선 CEG/CMCSA/CPRT/CSX/CTAS/DASH/DDOG/DXCM/EXC
9개사의 분리와 109 합성 경계를 승인했다. 기준 main은 `d724c54e24257af9600a6427f83dcea792bea738`다.
현재 구현 단계이며 독립 검증·실자료 발행·운영·main 병합은 별도다.

CRWD는 원래 DEI와 표지 FY 불일치로 같은 묶음을 막았다. 사용자는 정확한 두
accession의 분석 FY 교정2022→2023/2024→2025를 승인했지만 별도 실행은 대기다.
이번9개사에는 포함하지 않으며 부분 연간 정책으로 우회하지 않는다. APP/TER의 inline locator 경계,
PLTR/RKLB의 non-inline ZIP entrypoint, AEP의 History timeout은 후속5개 대상이다.

## 두 단계 승인

기존401 quality10·routine과 빈 occurrence217개 입력의 원본은 바꾸거나 다시
실행하지 않는다. 새 `financial-native-preparation-v1`은 정확한401 source inventory,
새 consumer inventory·d724 기준, 기존 quality manifest/report, 선택9/제외1,
선택9의 storage/routine/History/분석·collection pins와 root 영수증을 결속한다.
이것은 아직 없는 네 financial 부모를 승인한 것으로 취급하지 않는다.

quality scope는 원래10개사 PASS proof를 유지한다. 정상 reader의 불변 기본 proof를
검증하고 선택9의 기존 근거만 확인하며 quality 알고리즘·제외 회사 History를
재실행하지 않는다. identity에는 부모10개사 quality와 명시적 선택 범위를 함께
기록한다. 새9 storage 선언은 원래9개 기록과401 policy pins를 그대로 참조한다.

첫 financial은 정상 public producer를 사용한다. 새 최종 native 계약은 quality/
routine 생산자401과 실제 새 financial 생산자 SHA를 구분하고 네 새 부모·준비
승인을 결속한다. occurrence는 원래217 입력과 그중 선택195 checkpoint의 정확한
metadata 부분집합을 검증한다. 빈 파일 내용만으로 승인 범위를 공유하지 않는다.
기본 native-v1/v2와 역사적 source 호환 정책은 바꾸지 않는다.

## 기존100 보존과 새109

새 reader 전용 source 승인만으로 원래92·8 delta의 manifest/승인/ID를 유지한다.
불변100 union의 source-only 공유 reader 교체도 정확한 이전 declaration과 새
root 영수증에 한정한다. 새109는 원래92 delta+원래8 delta+새9 delta의 세 typed
멤버로 합성하며, 원래100은 catalog와 saved run에서 계속 열린다. pin된
`retained_unions`로 원래100의 보조자료 owner 범위도 보존한다.

회계·산술·보고값 선택·parser/sourcebindings/History/quality 규칙·journal은 바꾸지
않는다. identity의 설정/승인 연결 이외 핵심 함수는 기준 AST fingerprint와 같아야
한다. ContextVar는 중첩·예외·명시적 None에서 격리한다. 승인 없는 caller skip이나
current-main wildcard는 없다.

## 수락

합성 public first-financial 경로, 원래 quality 재실행/제외 History poison 미호출,
정확한 source/부모/범위/생산자/occurrence 거부, 승인 reset과 별도 최종 승인을
검사한다. 109·원래100 재열기·WDC 최신/고정·관측ID·owner 보존도 focused 검사한다.
실제 회사 감사·품질/Raw/History 재생성·완료 작업 반복은 하지 않는다.

## Operator 전달 계약

독립 검증 후에만 새 목적지에 실행한다. 기존401 quality10과 routine은 보존하며,
선택9 storage는 원래 선언에서 companies만 정확히 선택한 새 파일이다. policy와
각 history/acceptance/report/payload_inventory는 원본과 같아야 한다. source 입력은
`work/remaining15-recovery-20261114/ops/nine-input-plan-proposed.json`에서 준비한다.
기존 정상 API의 명시 FY bounds로 새로 준비하는8개 quarterly analysis는 생산자401로,
CPRT quarterly·annual/History/quality도 원래 생산자로 유지한다.

준비 제안 함수는 `financial_native_source.prepare_native_preparation_packet`이다.
인자는 `identity_config`(정상 identity 설정 dict, 아직 native_preparation 없음),
`old_source_root`(불변401의 src/sec_xbrl), `consumer_baseline_files`(d724 Python map),
`occurrence_inputs`(원래217 입력 pin), `financial_producer_revision`(실제 새 동결 SHA),
새 `destination`이다. d724 map은 `work/remaining15-recovery-20261114/consumer-baseline-d724.json`,
canonical digest `0dc4cbb7a8023e4c8ff0b98cbc69359c7ad343cf8045b255de93ab796f5dfacc`다.
identity의 설정/승인 연결 외 core AST digest는
`f3a52b12234f2574614b18be7283920ce114d93197a2af863bf83b0f90d1d49c`다.

이 함수는 제안만 쓴다. 리드는 별도 파일에
`{schema_version: financial-native-preparation-approval-v1,
status: ROOT_APPROVED_NATIVE_PREPARATION, packet: pin}`을 쓰고,
`declaration={packet: pin, approval: pin}`을 새 identity 설정의 `native_preparation`에
추가한다. 선택9 identity 요청의 나머지 정규화 필드는 packet과 같아야 한다.
`with use_native_preparation(declaration):` 안에서 정상 public identity → metrics →
annual-v2 → quarterly-metrics API를 호출한다. quarterly 설정의 source_commit_sha는
401로 바꾸지 않고 실제 새 financial 생산자 SHA를 쓴다. 이 context는 원래 quality
알고리즘을 실행하거나 제외 회사의 History를 확인할 권한을 주지 않는다.

네 새 부모가 생기면 기존 `prepare_native_source_packet`의 `parents`,
`old_source_root`, 새 `destination`에 `preparation=declaration`만 추가한다.
역할 이름은 identity/annual_metrics/annual_dataset/quarterly_metrics다. 새 v3 packet은
producer_revision401(quality/routine)과 financial_producer_revision(새 실제 SHA)을
분리한다. 리드의 최종 영수증은
`{schema_version: financial-native-source-approval-v3,
status: ROOT_APPROVED_NATIVE_SOURCE_TRANSITION, packet: pin}`이다. 이것을 정상 v3
설정의 native_source에 넣고 combined/projection만 새로 발행한다.

새9의 유일한 V3/projection은 union-v1 설정에 `allow_single_member: true`와
`expose_auxiliary_owners: true`를 명시해 단일-cohort 부모로 참조한다. 기본 v1 최소2개
멤버 계약은 그대로며 typed-v2에 이 flag는 허용하지 않는다. 기존 governed-delta
producer는 그 부모에 빈 교정 요청으로 정의 버전만 채택한다. 두 번째 financial
묶음이나 가짜 회사를 만들지 않는다.

기존92/8 reader의 새 영수증은 `governed-delta-reader-source-transition-v2`다.
이전 v1 영수증 필드(manifest/approval/old source root·inventory/current inventory/
consumer_baseline_files/status ROOT_APPROVED_READER_ONLY_SOURCE_TRANSITION)를 유지하고
`previous_declaration`에 불변100 manifest가 참조하던 정확한 이전 declaration을
추가한다. 원래 manifest/approval은 바꾸지 않는다. 기본 옛 reader 검사는 그대로며
새 영수증은 producer/native 권한을 주지 않는다.

109 설정은 기존 union-v2의 세 GOVERNED_DELTA 멤버와
`retained_unions: [원래100 manifest pin]`, expose_auxiliary_owners를 선언한다.
원래100의 멤버와 owner가 실제 동일한 부분집합이어야 한다. 기존 CLI/serve 옵션과
catalog를 유지하고 92/8에 새 reader transition pin을 명시한다. 새 CLI나 UI 변경은
없다. 원래100의 불변 declaration은 source-only 공유 reader 승인으로만 대체하여
saved run/ID/trace와 보조자료 scope를 보존한다.

## Source 동결 전 확인

새 경계 focused Python5개가 PASS했다(7.29초). 원래100 saved run/trace를 새 reader로
그대로 재열도록 보강한 두 합성 검사도1.19초에 PASS했다. Ruff·diff와 d724 전체
회계/산술 source 및 identity core fingerprint를 확인했다. 실자료 first-financial,
native/projection, private109·운영·main 병합은 아직 하지 않았다.

병행 operator는 기존401의 정상 공개 API로 필요한8 quarterly analysis만 새로
준비했고 CPRT는 그대로 재사용했다. 연간 작은 header/focus 확인에서9개 원래
annual 묶음은 모두 최신5개 10-K 범위를 포함하여 연간 작업은 필요하지 않았다.
CPRT/CTAS는 input2022–2026/display2023–2026, 나머지7개는
input2021–2025/display2022–2025다. source 계약은 특정 연도를 고정하지 않는다.
최종 제안은 `ops/nine-input-plan-coverage-qualified-proposed.json`
(SHA256 `89cff7ddf3d3077512cbdf5942c5c6e273b2cca17184c5ae8d2dba8edebcaaba`)이다.
이는 완료된 상류 자료의 실행/범위 근거이며 새 준비/native 승인이나109 운영을
대신하지 않는다.
