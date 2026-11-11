# History 정상 발행의 임시 디렉터리 정리

2026-11-11 사용자는 main의 캐시 History 복구 실패를 수정하고 별도 PR로
검증하는 범위를 승인했다. 기준은 `b1b783d418`이다.

## 원인과 변경 범위

성공한 reported History 발행에 빈 `.chunks` 디렉터리가 남았다.
각 표의 spill 결과는 성공 시 자신이 만든 하위 파일과 디렉터리를 정리하지만,
여러 표가 공유하는 spill root는 호출자가 관리한다. 복구기의 정확한 파일·
디렉터리 목록 검사가 이 추가 디렉터리를 거부했다.

History 생산자는 모든 표의 성공 처리가 끝난 후, 매니페스트 작성과 검증·
발행 전에 자신이 만든 빈 `.chunks`만 `rmdir`로 정리한다. 표를 재사용해
디렉터리가 생기지 않았으면 추가 작업이 없다. 디렉터리에 파일이 남거나
심볼릭 링크이면 실패한다. 실패한 표의 spill 진단 자료는 보존한다.

수정은 생산자의 성공 경로에 한정한다. 기존 발행물에 대한 마이그레이션이나
정리를 수행하지 않는다. 복구 입력의 추가 파일·디렉터리·심볼릭 링크 거부,
값·기간·원본 근거와 공시 선택 규칙은 기존 검사를 유지한다.

## 검증과 상태

임시 디렉터리에서 성공 정리, 비어 있지 않은 진단 자료와 링크의 거부,
저장 가드 거부를 검사한다. 실제 NVDA 두 공시 캐시로 새 History를 준비하고
복구 API와 별도 CLI를 통해 reported·derived 값, 순서와 원본 파일 해시를
대조한다. 원본 입력과 실제 저널은 읽기 전용 해시로 전후를 확인한다.

```sh
POLARS_MAX_THREADS=2 PYTHONPATH=src:. python -m pytest -q tests/unit/test_history_workflow.py tests/unit/test_history_recovery.py tests/unit/test_history_storage_performance.py tests/unit/test_history_validation_policy.py tests/integration/test_history_quarters_cached.py
ruff check .
POLARS_MAX_THREADS=2 PYTHONPATH=src:. python -m pytest -q
```

실제 캐시 검사는 기존
`data/processed/history_runs/20260906_five_company/history_intake.json`과
여기서 참조하는 NVDA 두 공시가 필요하다. 캐시가 없는 환경에서는 해당
통합 검사를 건너뛰며, 임시 파일의 안전 경계는 합성 테스트로 검사한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-11 성공 발행의 빈 임시 디렉터리 정리 |
| 구현 | 성공 생산 경로 정리와 안전 경계 테스트. 초기 집중 검사 201개 통과, 추가 공개 생산 경로 검사는 기존 소스에서 실패하고 수정 소스에서 통과 |
| 독립 검증 | 별도 읽기 전용 검증 대상 |
| 로컬 인수 | 별도 판단 |
| PR·CI·main·운영 | 별도 판단 |


수정 전 재현은 main `b1b783d418`에서 9.72초 만에 동일한 복구 목록 오류로
실패했다. 수정 후 초기 집중 검사에는 실제 캐시의 API·CLI 복구가 포함됐다.
캐시 없는 합성 생산 경로에서도 검증과 발행 직전 빈 공유 root의 제거를
확인한다. 기존 복구 입력에 빈 `.chunks`를 추가하는 경우는 계속 거부한다.
로컬 보존 기준의 입력·매니페스트·저널 파일 20개 해시를 대조해 일치했다.
