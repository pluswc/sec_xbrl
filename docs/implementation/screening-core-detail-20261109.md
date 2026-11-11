# 스크리닝 조회용 관측값과 상세 근거 분리

2026-11-09 사용자는 기존 준비 발행물의 식별자·값·품질·근거와 저장
기록을 유지하면서 조회와 갱신 범위를 줄이는 작업을 승인했다. 기존
발행물을 읽는 경로를 유지하고, 명시적으로 고정한 보조 발행에 한해 새
경로를 사용한다. 이 보조 발행은 지표 계산, 기간 선택, 공시 해석 및
기존 데이터의 쓰기 경로를 바꾸지 않는다.

## 읽기와 저장

보조 매니페스트는 원본 V3 매니페스트의 SHA-256, 데이터셋 ID, 발행 ID를
고정한다. 실제 카탈로그 원본과 모두 일치해야 열린다. 관측값은 회사,
연간·분기, 기간별로 핵심과 근거를 나눈다. 원본의 관측값 순서, 기간,
정의, 단위, 품질 상태, 근거의 키와 값을 보존한다. 탐색 인덱스는 첫
조회에 핵심 자료로 만든다. 조회한 파일의 압축 바이트 및 내용 해시가
맞아야 읽을 수 있으며 파일 누락이나 불일치는 기존 경로로 대체하지 않는다.
읽어서 검증한 핵심 자료와 최근 근거 묶음은 메모리에서 재사용한다.

기존 API 요청의 기본 응답은 상세 근거를 포함한다. 표시 앱의 분기 표와
시험 실행은 `include_evidence=false`를 명시한다. 시험 실행이 돌려준 같은
모드의 해시를 저장 요청에 전달하면, 서비스가 상세 근거를 포함해 한 번
평가하고 그 평가의 핵심 보기로 해시를 확인한다. 저장에는 상세 평가를
그대로 사용하며, 저장 결과의 해시 규칙과 추적 응답은 기존과 같다.
상세 시계열과 비교 등 상세 응답은 해당 회사·기간의 근거를 읽는다.

## 준비와 운영

기본 준비 명령은 기존 검증된 V3 리더로 원본을 연다.

```sh
python -m sec_xbrl.screening project-runtime --dataset ORIGINAL_V3_DIR \
  --destination NEW_PROJECTION_DIR --blob-store SHARED_BLOB_DIR
python -m sec_xbrl.screening serve --catalog CATALOG --store JOURNAL --exports EXPORT_DIR \
  --runtime-projection DATASET_ID PROJECTION_MANIFEST SHA256
```

`serve`의 옵션은 데이터셋마다 지정할 수 있다. 생략한 데이터셋은 기존
리더를 사용한다. 원본이 승인된 과거 Python 소스 전체에 고정된 경우
해당 승인 체크아웃을 별도 프로세스의 `PYTHONPATH`로 사용한다. 그
프로세스에서 아래와 같이 새 파일을 별도 모듈로 불러오면 원본 검증이
승인된 소스를 그대로 읽는다. 새 소스 파일을 과거 패키지에 복사하지 않는다.

```python
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sec_xbrl.financial_source_compatibility import use_source_compatibility
from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader, _share_v3_readers

spec = spec_from_file_location("screening_projection_builder", "/absolute/new/runtime_projection.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)
builder = module.RuntimeProjectionBuilder(Path("/absolute/shared-blobs"))
with use_source_compatibility(approved_pin), _share_v3_readers() as verified:
    for original, destination in sources:
        source = Path(original).resolve()
        reader = verified.get(source) or ScreeningDatasetV3Reader(source)
        print(builder.publish(source, destination, reader=reader))
```

내용 주소가 같은 묶음은 발행 간 같은 파일을 사용한다. 다시 준비할 때도
검증된 입력 행은 순회해 정규화하고 해시를 계산한다. 기존 파일은
재압축하거나 다시 쓰지 않는다. 같은 준비 프로세스에서 이미 검증한
파일은 압축 해시를 대조해 재해제를 피한다. 처음 보는 기존 파일은
압축을 풀어 주소와 맞는지 확인한다. 필요한 파일을 모두 준비한 뒤
매니페스트를 원자적으로 게시한다. 원본 자료의 저장 공간은 계속 사용한다.

구현자 검증은 합성 V3의 공개 응답과 저장·추적 동일성, 손상된 묶음의
접근 범위, 재발행 시 기존 파일 재사용을 확인한다.

```sh
python -m pytest -q tests/screening/test_runtime_projection.py
```

## 2026-11-09 독립 검증과 로컬 인수

별도 검증자가 동결 소스 `254ce37ca6f87268d8bfebfa2c4e7f48f32a17c9`를
검토하고 대상 테스트 3건을 통과시켰다. 실제 카탈로그 6개에서 상세 응답
7종의 해시와 데이터셋 상태가 기존 경로와 일치했다. 기존 조건 4건과
실행 4건의 해시, 별도 복사본에서 새로 저장한 결과의 상세 근거도 일치했다.

로컬 인수 후 프런트엔드 18765에서 백엔드 19070으로 연결했다.
프런트엔드 PID는 44504였다. 재무 비교 보드의 성장률 발행을 계속
사용했고 기존 저널 SHA-256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로
유지됐다. 원격 push·PR·CI는 이 인수에 포함되지 않는다.

| 실제 측정 항목 | 기존 | 새 경로 |
| --- | ---: | ---: |
| 시작 시간 | 1,036.512초 | 4.147초 |
| 시작 단계 RSS | 15,512,532 KiB | 370,316 KiB |
| 분기 시험 실행 첫 응답 | 상세 164ms | 핵심 28.9ms |
| 분기 시험 실행 반복 중앙값 | 상세 173ms | 핵심 6.8ms |
| 분기 상세 첫 응답 | 4.3ms | 138ms |
| 활성 발행의 논리 크기 | 304,460,903바이트 | 17,326,393바이트 |
| 활성 발행의 실제 디스크 사용 | 304,463,872바이트 | 20,090,880바이트 |

기존 활성 관측값 파일과 그에 대응하는 새 조회 발행을 비교했다.
원본 발행은 보존했고, V3 발행 4개에 공용 저장소가 추가로 사용한
실제 디스크 공간은 48,857,088바이트였다. 최초 분기 상세 조회는
필요한 근거를 그때 읽으므로 이전보다 오래 걸렸다.

NFLX 2026Q3 공시 `0001065280-26-000291`의 갱신 쓰기를 재현했다.
기존 전체 분기 관측값 쓰기와 비교해 2.957초에서 2.334초,
16,800행에서 42행, 실제 디스크 쓰기 228,470,784바이트에서
565,248바이트였다. 이미 적재한 행을 물려받은 자식 프로세스의
추가 RSS는 886,524 KiB에서 1,056 KiB였으며 기존 묶음 1,198개를
재사용했다. 전체 입력 순회나 상위 수집·준비 시간은 이 쓰기 재현
측정에 포함되지 않았다.

로컬 증거는 `work/screening-core-detail-20261109`의
`before.json`, `after.json`, `parity.json`, `projection-storage.json`,
`quarter-replay.json`, `backend-live.json`에 있다.


## 2026-11-10 main 기반 PR 준비

PR #82가 반영된 main `9f1c8ba4cb1ce1274a3831ae3994ab70ae91823b` 위로
운영 구현과 인수 기록을 옮겼다. 통합 구현의 Python 패키지 및 표시 자산은
운영 인수 소스 `254ce37ca6`와 바이트가 일치한다. PR #82의 재무 성장률
생산기와 표시 기능도 계승했다. 위 시간과 메모리 수치는 2026-11-09 운영
인수 당시의 측정이다. 이번 PR 준비에서 운영을 재배포하거나 같은 조건의
성능 비교를 반복하지 않았다.

합성 테스트에서는 최신 연간·분기의 핵심 미리보기와 분기 탐색을 기존
리더와 비교하고, 미리보기가 상세 묶음을 열거나 SQLite를 바꾸지 않는지
검사한다. 별도 임시 SQLite에 상세 근거를 저장하고 기존 리더로 다시 연 뒤
선택 내보내기와 추적을 확인한다. 기존 V6 원본을 검증해 다시 준비하는
작업에는 승인된 예전 Python 체크아웃과 해당 호환 패킷을 사용한다.
운영 보조 발행은 이 승인된 원본 검증에서 생성한 핀을 사용한다.

통합 소스로 검증한 실제 카탈로그 6개와 기존 저장 조건·실행 8개의 해시,
기본 상세 API 응답 7종의 해시가 기존 기록과 일치했다. 핵심 연간·분기
미리보기 해시는 동일한 상세 평가를 핵심 형태로 줄인 결과와 일치했다.
별도 저널 복사본에서 분기 결과를 상세 근거와 함께 저장하고 새 서비스에서
재열기, 추적, JSON 내보내기를 확인했다. 원본 저널의 SHA-256은 위 인수
기록과 같았다. 현재 운영 주소의 읽기 전용 브라우저 확인에서 기존 보드
15그룹과 성장률 부호 사례 5건을 검사했다.

실제 통합 검증과 재현 명령은 `work/screening-runtime-pr-20261110/evidence/`의
`integration-verification.json` 및 `verify-real.py`에 있다. 브라우저
보조 증거는 이 작업의 로컬 시각화 디렉터리 `screening-runtime-pr-20261110/`에 있다.

통합 후보의 구현자 검증, 별도 독립 검증, 원격 PR·CI, main 병합은
서로 구분한다. 운영 프로세스, 원본 발행물과 실제 저널은 현재 경로를
계속 사용한다.
