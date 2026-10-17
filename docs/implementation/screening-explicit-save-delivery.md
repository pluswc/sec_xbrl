# 스크리닝 명시적 저장·다시 열기 전달 계약

## 승인과 상태 — 2026-10-17

사용자는 조건과 실행 결과 모두 저장 버튼을 누르지 않아도 이력이 쌓이고,
저장한 항목을 다시 열기 어렵다는 문제의 수정을 승인했다. Sol 구현 세션의
capacity 중단 후 2026-10-17 사용자가 Astra 대체 구현을 승인했다. 단일 구현자와
별도 읽기 전용 검증자를 유지한다. 모델 대체는 이 기능 구현 범위에 한정된다.

상태는 **IMPLEMENTED / 자체 검증 완료**이다. 독립 검증, 리드 로컬 인수,
실제 운영 서버 적용, main 병합 및 원격 작업은 아직 이 문서로 주장하지 않는다.
금융 지표, 원본 자료, 기간·회계 정책과 50개사 변환은 변경하지 않는다.

## 사용자 계약

- 편집과 시험 실행은 screen/revision/universe/run/decision/export에 기록하지 않는다.
- 조건 저장은 조건만 저장한다. 같은 최신 내용과 데이터 문맥의 재저장은 revision을 늘리지 않는다.
  같은 조건이라도 다른 데이터 문맥을 명시 저장하면 새 revision을 만든다.
- 모든 저장 조건 버전을 목록에 표시하고 `불러오기`를 눌러 복원한다.
  목록 선택만으로 현재 편집 내용을 바꾸지 않는다.
- 결과 저장은 시험 실행한 조건, 데이터 publication, 기간, 지표 버전과 전체
  결과를 보존한다. 이력에서 다시 열 때 재실행하지 않고 저장된 결과를 읽는다.
- 조건 저장 없이 결과만 저장할 수 있다. 필요한 내부 조건과 universe는 run과
  한 트랜잭션으로 기록하며 결과용 내부 조건은 저장 조건 목록에서 제외한다.
- 현재 조건을 수정하면 이전 preview의 결과 저장은 비활성화한다. 저장 작업과
  문맥 전환 중에는 중복 클릭 및 편집 경쟁을 막는다.
- 시험 결과에서 기업 상세·출처·시계열은 읽을 수 있다. 다운로드와 관심 판단
  기록은 결과를 명시적으로 저장한 뒤 가능하다.

## API·데이터 경계

`POST /api/preview`는 기존 evaluator를 순수 조회로 재사용한다. 반환한
`preview_hash`는 dataset ID, 전체 조건과 평가 결과의 canonical JSON digest다.
`POST /api/results`는 같은 입력을 **한 번** 평가해 digest를 확인하고 바로 그
평가 산출물을 저장한다. 검증 뒤 두 번째 평가를 저장하지 않는다. 데이터나
조건/결과가 달라지면 stale 오류로 거부하고 journal을 쓰지 않는다.
재시작 후에도 동일한 불변 publication이면 preview digest를 검증할 수 있다.

기존 `POST /api/runs`는 명시적으로 저장하는 legacy API로 보존한다.
브라우저의 시험 실행은 이를 호출하지 않는다. 기존 screen/run ID, 내용, 해시와
revision 연결은 보존한다. `screen_save_kinds`와 `revision_contexts` 테이블을 추가하며 기존 marker 없는
조건은 기존 저장 조건으로 표시한다. 과거 자동 저장 기록은 임의로 삭제하지 않는다.
새 숨김 조건은 `RESULT_BACKING`, 명시 조건은 `EXPLICIT_CONDITION`이다.
backup/restore와 integrity 검사는 두 테이블도 보존한다.

새 조건 저장은 revision별 dataset ID, publication ID, canonical manifest digest를
별도 불변 context로 기록한다. 조건의 기존 content/hash는 변경하지 않는다.
`GET /api/saved-conditions/{revision_id}`는 현재 publication과 대조하여 불일치하면
거부한다. legacy 조건은 연결된 run의 dataset/publication이 단일할 때만 과거 실행
문맥으로 연다. 연결 run이 없거나 복수 문맥이면 현재 선택 자료로 연다는 안내를
보이며 과거 문맥을 안다고 주장하거나 추론한 문맥을 저장하지 않는다.
`GET /api/screen-revisions`는 전체 명시 저장 버전 조회이며 읽기만 수행한다.

## 재현·검증 및 인계

```bash
PYTHONPATH=src /absolute/project/.venv/bin/python -m pytest tests/screening -q
PYTHONPATH=src /absolute/project/.venv/bin/python -m ruff check src/sec_xbrl/screening tests/screening
```

`test_explicit_save.py`는 DB 해시·전 테이블 수의 preview 전후 동일성, 조건 no-op,
이전 버전, 결과 재열기, backup/restore, legacy migration, stale 거부,
검증한 평가의 단일 저장, run insert 실패 시 전체 rollback 및 HTTP 경계를 검사한다.
최종 자체 검증: screening suite **393 passed (10.11s)**, Ruff·JavaScript 문법·diff 검사 PASS.
실자료 21사 자체 Chromium 검사에서 시험 실행, 상세 열기, 조건 v1/v2 저장과 v1
불러오기, 결과 저장, 브라우저 재시작 후 결과 열기를 확인했다. 1440/1024 폭에서
겹침을 확인했다. Linux의 한글 폰트 미설치로 글리프 품질 및 native 클릭 안정성은
Windows 독립 검증에서 확인해야 한다(headless 클릭은 force 옵션 사용).
실자료 검증은 **복사한 journal**과 별도 loopback 서버에서 수행했다.
원본 journal 변경·운영 재시작은 독립 검증 후 리드의 별도 로컬 반영 판단에 따른다.

UI는 기존 `.interface-design/system.md`의 투자자 작업대 방향, 색·간격·타입을
유지한다. 행렬을 중심에 두고 시험 실행/조건 저장/결과 저장의 역할을 텍스트로
구분한다. 화면 검증은 1440/1024 폭, 오류·빈 상태·중복 클릭·다시 열기를 포함한다.

### Publication 교체 시 경계

저장 run의 dataset ID가 현재 다른 publication을 가리키면 재열기를 거부한다.
오류는 저장 결과가 보존되어 있고 당시 publication 등록을 복구하면 다시 열 수
있음을 안내한다. frozen rows·embedded trace·export 기록은 변경하거나 재실행하지
않는다. 이미 열린 상세 화면의 연간/분기 시계열과 peer 조회도 당시 publication
ID를 보내며 서버가 불일치 요청을 거부한다. 독립적인 현재 자료 탐색은 영향을
받지 않는다. 이 최소 구현은 교체된 publication 아래서 과거 결과 화면을 여는
기능까지 제공하지 않으며, 저장된 embedded trace 자체는 계속 읽을 수 있다.

이 브라우저 검증은 기존 고정 21사 snapshot의 저장 동작만 검증하며 재무 수치나
50사 데이터 파이프라인 전체의 정확성 인수가 아니다. 최종 검증 후 복사 journal
전용 서버를 종료했다. 운영 서버나 원본 journal은 수정하지 않았다.
