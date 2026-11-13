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

## 2026-11-14 최신 main 통합·PR85 갱신 승인

PR94 병합 후 main `df694e4a88e5b5aeb7f68ac3590205989bc0b37c`를 기존
`codex/history-recovery-inventory`에 일반 merge한다. 초기 소스 `b94b751a8b`의
빈 공유 spill root 정리와 엄격한 recovery 경계는 그대로 유지한다. 최신 Nasdaq/UI/
producer/기간 규칙은 main과 동일하게 보존하며 새 회계 의미를 추가하지 않는다.
기존 승인 fallback과 단일 writer/별도 독립 reviewer 역할을 유지한다.

사용자는 최신 통합과 private 복제본 검증 및 PR85 업데이트를 승인했다. PR85
병합은 승인하지 않았다. 실제 Raw/cache/발행물/journal 수정과 runtime 재시작은
금지한다. 실제 NVDA 입력은 읽기 전용이며 cached API·CLI recovery 출력은 pytest
tmp에만 생성한다. 복제 journal의 저장/재열기/휴지통 복원은 리드가 수행한다.

수락: focused221·cached API/CLI·전체pytest·전체Node·Ruff/diff, 기존20파일 hash와
SQLite readonly 전체 논리 dump 전후 동일성, 합성 생산경로에서 검증/공개 전 정리,
nonempty/link/storage guard fail-closed·실패 진단 보존. 최신 통합의 독립 검증과
리드 인수·원격 CI는 각각 별도로 기록한다.

읽기 전용 보존 확인은 기존 `work/history-recovery-inventory-20261111/evidence/`의
`preservation-before.json` 20개 경로를 그대로 재해시하고 journal을 `mode=ro`로
열어 `sha256("\n".join(db.iterdump()).encode())`를 비교한다. 이번 사전 결과는
`evidence/refresh-20261114/preservation-before.json`에 보관했고 원래 baseline과
정확히 같다. 이 경로는 선택적 검증 근거이며 계약의 필수 소스는 이 문서다.

최신 통합 자체 검사: focused 222개(cached NVDA API+CLI 포함), 전체 Node 122개,
Ruff/diff PASS. 전체 pytest는 실행 중이며 아직 통과를 주장하지 않는다.
로그는 `/tmp/pr85-refresh-focused.log`, `/tmp/pr85-refresh-node.log`,
`/tmp/pr85-refresh-full.log`다. focused 종료 후20파일 SHA와 journal 전체 논리
dump는 사전 및2026-11-11 원래 baseline과 동일했다
(`evidence/refresh-20261114/preservation-after-focused.json`). 최신 독립 검증/
복제 journal UAT/리드 인수/원격 CI와 병합 상태는 후속 단계다.
