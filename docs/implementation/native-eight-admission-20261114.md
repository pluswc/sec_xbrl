# 신규8개사 native 승인과 기존92 보존 합성

## 승인 범위와 상태

2026-11-14 리드는 기존92 교정 발행물과 모든 개인 기록을 보존하며 이미 준비된
partial7·ISRG의 실제 생산자 승인을 추가하고 100개사를 합성하도록 승인했다.
현재는 구현 중이며 독립 검증·실자료 발행·로컬 인수·운영·main 병합은 별도다.
기준 main은 `ebdbe938d7acef1de2618661934e8e235722e45b`다.

## 불변 경계

기존401 native-v1 및 역사적 source 호환 정책은 유지한다. 새 native-v2는 이름이
고정된882·20ec 생산자의 정확한 전체 source inventory, 네 financial 부모, quality,
storage/routine 보고서와 occurrence 입력51건/23건·checkpoint를 root 승인에 결속한다.
같은 빈 occurrence 내용만으로 범위를 공유하지 않는다. 재수집·Raw/History/quality/
연간분석·완료 financial 재생성이나 source 이름 바꿔치기는 허용하지 않는다.

이미 승인된882 `available-annual-baselines-v1` 처리만 이식한다. 실제 연간0–5개와
표시0–4개를 구분하고 HONA/SPCX는 null annual parent·NO_ANNUAL_BASELINE과 연간
숫자0개를 유지한다. 기존 기본5/4 계약과 회계/산술/보고값 선택은 바꾸지 않는다.

기존92 governed delta는 정확한 옛 manifest·승인·source inventory와 새 inventory를
결속한 별도 reader 전용 root 승인으로만 연다. 생산자나 다른 발행물에는 권한을
주지 않으며 기본 source 검사와 ContextVar 격리를 유지한다.

## 합성

새로운7+1 native 발행·projection을 기존 strict union-v1로8개사 합성한 뒤,
기존 governed-delta producer로 revenue_yoy 정의 버전만 채택한다. 교정 요청은 없고
숫자 계산도 없으며 원래 관측ID·상세 참조를 보존한다. typed union-v2는 정확히 승인된
92·8 delta를 disjoint CIK·동일 cutoff·동일 정의·고정8 spine으로 합성한다.
92의 GOOGL 교정 증거와 WDC 추가 실제 분기/TTM은 공유하며 재생성하지 않는다.
최신 조회만 추가 관측을 전달하고 고정 기간은 그대로다. 기존 catalog와 owner
보조자료 범위를 보존하며 새8의 준비되지 않은 보조자료는 명시적으로 없다.

## 수락

두 실제 생산자와 null annual 경로, 정상 발행/재열기, 잘못된 producer/source/부모/
occurrence 입력·범위, 기본v1 거부 유지, reader 승인 격리, typed union의 중복 CIK·
정의 충돌·WDC 최신 전달·옛 보조자료를 focused 검사한다. 독립 검증 뒤 리드가
정확한 packet/reader 승인을 작성하고 실제 발행·private 인수·운영을 수행한다.

## Operator 인터페이스

최종 소스 동결·독립 검증 뒤에만 실행한다. 현재 입력은
`work/native-eight-admission-20261114/ops/execution-input-plan.json`이며 완료된
네 부모·quality·storage·routine·각 occurrence 입력/checkpoint를 그대로 사용한다.

`financial_native_source.prepare_native_source_packet`의 기존 세 인자 `parents`,
`old_source_root`, `destination`에 다음 명시 인자를 더한다. `parents` 역할 이름은
`identity`, `annual_metrics`, `annual_dataset`, `quarterly_metrics`다.

- `producer_profile`: `partial-annual-882-v1` 또는 `duration-hour-20ec-v1`.
- `consumer_baseline_files`: main `ebdbe938`의 전체 Python 상대경로→SHA256 map.
  canonical digest는 `e38792671c712b1a9167749c41138f1e2d9f64cf70c6c8a226e3735bb8e73a74`이며
  준비된 map은 `work/native-eight-admission-20261114/baseline-inventory.json`이다.
- `occurrence_inputs`: 각 생산자의 기존 `statement-metric-evidence-inputs.json` pin.

이 함수는 제안만 쓴다. 리드는 별도 파일에
`{schema_version: financial-native-source-approval-v2,
status: ROOT_APPROVED_NATIVE_SOURCE_TRANSITION, packet: {path, sha256}}`를 쓴다.
기존 v3 설정의 `native_source: {packet: pin, approval: pin}`과 일반
`prepare-v3`/`project-runtime` 명령으로 새7·1 묶음을 발행한다. 기존 financial
부모를 바꾸지 않는다. 새8 union-v1은 두 projection과 원래 v3 manifest를 pin하고
`expose_auxiliary_owners: true`를 선언한다. 그 union 위 `governed-delta` 설정에는
새 dataset_id·parent pin만 넣어 교정 요청 없이 정의 버전만 채택한다.

기존92 reader의 `reader_source_transition` pin은 root가 작성한 다음 별도 영수증이다.
`schema_version: governed-delta-reader-source-transition-v1`,
`status: ROOT_APPROVED_READER_ONLY_SOURCE_TRANSITION`, 원래 `manifest`·`approval` pins,
`origin_source_root`(불변 fdacea checkout의 `src/sec_xbrl`),
`origin_implementation_sources`(기존92 manifest map), `current_implementation_sources`
(새 소스의 `governed_delta._source_hashes()`), 위 `consumer_baseline_files`를 결속한다.
이는 다른 artifact나 publisher/native 호출에 권한을 전달하지 않는다.

최종 설정은 `schema_version: screening-cohort-union-config-v2`,
`dataset_id: universe-expanded-supported-100-20261025`, `expose_auxiliary_owners: true`,
`members: [{kind: GOVERNED_DELTA, declaration: {manifest: pin, approval: pin,
reader_source_transition: pin}}, ...]`이다. 새8 declaration에는 transition이 필요 없다.
기존 `cohort-union --config FILE --destination NEW` 명령을 사용한다.

Private serve는 기존 catalog/projection/union/delta 옵션을 보존하고 새8 부모union,
새8 delta와 최종100 union을 추가한다. 기존92에는
`--governed-delta-reader-transition DATASET_ID FILE SHA256`를 명시한다. catalog 순서와
무관하게 정확한 부모를 먼저 공유하고 의존성 순환·누락은 거부한다. Windows bridge는
새100 union manifest의 정확한 `--auxiliary-union FILE --auxiliary-union-sha256 SHA`만
추가하며 원래92/부모92·새8의 owner 범위를 발행된 ancestor metadata로 보존한다.
새100을 default로 적용하는 것은 private 저장/재열기·원래92 동일성·최신 WDC와
보조자료 확인 이후 리드의 별도 운영 승인이다.


## 구현 동결 전 자체 확인

새 native/reader/union 경계와 accepted partial coverage의 focused Python13개가
5.68초에 PASS했다. 보조자료 owner Node6개와 Ruff·CJS 문법·diff·baseline 불변
fingerprint도 PASS했다. 이는 합성/소스 검사이며 실제8개사 factory·새 발행·private
runtime·100 운영 인수를 수행했다는 의미가 아니다. 기존 회사 감사는 반복하지 않았다.
