# Nasdaq 확장: 동일 생산 소스의 연속성 자료 통합

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

관련 계약: [확장 마일스톤](nasdaq100-expansion-20261111.md),
[전달 절차](delivery-workflow.md),
[분석 데이터 모델](../architecture/analytical-data-model.md).
