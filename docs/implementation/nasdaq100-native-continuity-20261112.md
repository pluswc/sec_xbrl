# Nasdaq 확장: 동일 생산 소스의 연속성 자료 통합

2026-11-13 현재: 명시적 native 전이와 선택 회사군 status 경계를 구현한 후보다.
신규 합성 검사 20개를 포함한 영향 검사 26개와 Ruff·diff 검사를 통과했다.
독립 검증·리드 수락은 대기이며, 실자료 발행 재개·union·운영 반영은 하지 않았다.
이하 날짜가 앞선 제안·보류는 당시 판단 기록이다.

## 범위와 상태 (2026-11-12)

리드는 새 회사군의 정상 생산 자료를 위한 명시적 native 통합 경계를 승인했다.
현재는 **설계 제안·소스 경계 확인** 단계이며, 구현·독립 검증·통합 발행·운영
적용은 완료되지 않았다. 회계식, Raw, 기존 50개사와 저장 기록은 바꾸지 않는다.

입력은 동결 생산 소스 `401be11b04fd203f6e74eda7b34e44ca0e7bc406`에서
정상 검사를 통과한 회사군 003·004·006의 identity, 연간 지표, 연간 V2,
분기 지표와 quality·statement evidence다. 재무 기준일은 `2026-10-25`,
분기 정의는 `quarterly-investor-41-statement-continuity-v3`다. 성공한
앞 단계는 재생성하지 않고, 실패한 통합·projection만 후속 수락 뒤 실행한다.

## 제안하는 명시적 계약

- 버전 있는 native 선언과 별도의 리드 승인 파일을 절대경로·SHA-256으로 고정한다.
- 네 부모 manifest 및 quality·statement evidence의 정확한 경로·해시,
  CIK 집합, 기준일, 정의 버전, 연간 부모 연결과 생산 소스 401을 묶는다.
- 선언 없음, 변조, 다른 부모·회사군·기준일·정의, 역사적 witness와의 혼용은 거부한다.
- 기존 역사적 successor/W4 경로와 선언 없는 동작은 그대로 유지한다.
- catalog 이름만 보고 자동 승인하지 않으며, 과거 predecessor나 빈 proof를 만들지 않는다.
- 통합과 projection 성공도 union 수락·전체 115개사 준비·운영 적용을 뜻하지 않는다.

## 구현 전 확인된 소스 경계

기존 `dataset_v3._configured_compatibility`는 연속성 catalog 모두에 역사적
successor pin과 해당 witness의 기존 연간 부모를 요구한다. 새 회사군에는 그
역사적 부모가 없으므로 설정의 pin 하나를 추가하는 것만으로 통과할 수 없다.

또한 `financial_storage_reuse.current_history_validation_identity`는
`src/sec_xbrl`의 모든 Python 파일을 해시한다. 새 admission 코드만 추가해도
401의 승인된 routine report와 현재 identity가 달라진다. 현재 승인 범위에서는
이 검사나 `financial_source_compatibility`를 넓히거나 기존 보고서를 다시
감사할 수 없다. 따라서 일반 새 소스 프로세스에서 실행하는 단순 수정은 막혀 있다.

**리드 판단을 기다리는 대안:** 정확히 고정한 새 native consumer/builder 파일을
별도 모듈로 명시적으로 읽되, 부모 검증은 동결 401 `PYTHONPATH`의 정상 reader로
실행한다. 승인 파일은 admission 코드와 401 전체 소스 inventory를 함께 묶는다.
암묵적 경로 탐색·환경 덮어쓰기·monkeypatch 없이 공개 native 진입점을 정의하고,
생성한 projection을 후속 union이 읽도록 하는 별도 실행 계약이 필요하다.
이는 아직 선택·구현되지 않았으며 기존 validator 변경의 우회로로 간주하지 않는다.

## 수락·검증과 보류

선택된 경로의 구현 후 독립 검증과 리드 수락이 필요하다. 합성 검사는 정확한
부모/선언/소스 결속, 변조·범위 혼합 거부, 선언 없는 기존 거부, 역사적 경로
불변을 다룬다. 실자료는 기존 성공 자료를 재사용하고 Raw·회사 감사는 반복하지 않는다.

001/005의 APP·TER inline ID locator, 002의 CRWD 실제 FY 범위,
AEP 시간 제한 및 PLTR/RKLB non-inline 진입점 문제는 이 경계의 별도 보류다.
실제 FY를 채우거나 기존 지표·기간·회사 집합을 몰래 줄이지 않는다.

관련 계약: [전달 절차](delivery-workflow.md),
[분석 데이터 모델](../architecture/analytical-data-model.md).

## 승인된 후속 경계 (2026-11-12)

리드는 외부 모듈 실행 대안을 선택하지 않고, 정상 package 안의 명시적인 native
source-transition을 승인했다. `financial_native_source.py`가 별도 버전 packet과
리드 receipt의 정확한 SHA를 검증하고, 해당 scope에서만 storage reuse의 정확한
401 routine report·policy identity 차이를 인정한다. 기존 normal 파일·stat·scope·
rule 검사는 유지한다. `dataset_v3`는 opt-in native 선언만 이 경로로 보내며
역사적 successor validator는 수정하지 않는다. ContextVar token은 정상·예외·중첩
종료 모두 reset하고, 명시적 선언 없음은 외부 scope를 상속하지 않는다.

Packet은 네 부모·quality·statement evidence·회사 범위·기준일·401 전체 Python
inventory·후속 전체 inventory·정확한 native routine report와 그 규칙을 결속한다.
변경 허용은 이미 수락된 A/B 여섯 파일과 native helper, storage reuse, V3,
source closure의 지정 파일뿐이다. 회계 모듈·역사적 compatibility helper는 불변이며
A/B 여섯 파일도 수락된 정확한 bytes와 같아야 한다. source closure는 이 명시적
packet/receipt/소스와 control을 기존 방식으로 검증 전후 및 승격 전에 확인한다.
신규 사실, 다른 report·부모·source 또는 승인 없는 선언은 인정하지 않는다.

구현 허용 파일은 새 helper, `financial_storage_reuse.py`, `screening/dataset_v3.py`,
`screening/verified_source_closure.py`, 관련 focused tests와 이 계약이다. 독립 검증과
리드 수락 전에는 기존 세 회사군의 실패 단계를 재개하지 않는다.

### 구현 중 추가 확인 (2026-11-13)

신규 native 경계의 합성 공개 통합·재열기, 파일/stat·소스·scope 변조,
컨텍스트 격리와 승격 전 검사는 통과했다. 영향 범위 합성 검사 21개와 Ruff를
실행했으며, 실자료 발행이나 기존 감사는 재실행하지 않았다.

다만 실제 65개사 부모에서는 identity reader가 선택 회사군 외 모든 회사에도
collection status의 `History.validate`를 호출한다. 새 소스에서 이 호출은
무관한 401 보고서의 상세 fallback을 일으킬 수 있다. 현재 native 승인은
선택된 부모의 정확한 보고서만 대상으로 하므로 다른 회사로 넓히지 않는다.
이 미해결 소비자 범위 문제를 리드에게 반환했으며, 별도 결정 전 소스 동결·
실자료 단계 재개는 보류한다. 한 회사 합성 통과를 실제 65개사 검증으로 주장하지 않는다.


### 승인된 선택 범위 보완과 전달 (2026-11-13)

리드는 `collection_operations.read_universe_status(assessed_ciks=...)`의 명시적
선택 범위와 identity·quality의 두 호출부를 승인했다. 기본 `None`은 기존 전체
검사를 유지한다. native 호출은 봉인된 packet의 정확한 CIK·collection·storage
선언만 전달한다. 다른 회사는 discovery/Raw 메타데이터를 유지하면서
`NOT_ASSESSED_OUTSIDE_SCOPE`이며 재무 READY를 주장하거나 History를 검증하지 않는다.
두 회사 합성 회귀에서 제외 회사의 `History.validate`를 금지한 상태로 공개 통합과
재열기를 통과했고, 기본 전체 경로는 여전히 그 호출을 수행함을 확인했다.
따라서 위 추가 보류 경계는 구현에서 해결했으며 실제 발행 수락으로 확대하지 않는다.

Quality 변경은 수락된 B bytes에서 정확한 native status import/호출만 추가한 것임을
역변환 SHA로 검증한다. 변경 허용 목록에는 collection/status 및 identity consumer를
추가했으며, 회계식·정의·B profile/quality 규칙·역사적 compatibility helper는 불변이다.

운영 API는 `financial_native_source.prepare_native_source_packet(parents=..., old_source_root=...,
 destination=...)`다. `parents`의 키는 `identity`, `annual_metrics`, `annual_dataset`,
`quarterly_metrics`이며 값은 절대경로·SHA pin이다. factory는 제안만 만든다.
별도의 receipt는 정확히 다음 세 필드를 가지며 리드가 검토 후 작성한다.

```json
{"schema_version":"financial-native-source-approval-v1","status":"ROOT_APPROVED_NATIVE_SOURCE_TRANSITION","packet":{"path":"/absolute/packet.json","sha256":"..."}}
```

새 V3 설정에 `native_source={"packet": pin, "approval": pin}`을 명시한다.
`source_compatibility`/`quarterly_successor`와 혼용하지 않는다. 소스 후보의 독립 검증과
리드 수락 후, 기존 003·004·006의 성공한 다섯 단계를 보존하고 새 설정으로 실패한
combined/projection만 재개한다. partial7·ISRG의 후속 발행, APP/TER·CRWD·AEP·
PLTR/RKLB 보류와 전체 union/보조 화면/UAT는 별도다. 기존 detached supervisor와
단계 완료·실패 receipt로 재개할 수 있지만 현재 실행 중인 데이터 worker는 없다.
