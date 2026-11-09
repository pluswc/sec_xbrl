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

실제 데이터 측정, 독립 검증, 로컬 인수와 운영 적용은 별도 단계다.
