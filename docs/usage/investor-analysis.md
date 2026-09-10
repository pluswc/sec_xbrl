# 투자자 분석 이용 가이드

이 가이드는 이미 준비된 consumer bundle에서 핵심 표, 구성 Axis, 출처를 조회하고
파일로 저장하는 가장 짧은 경로를 설명한다. API와 오프라인 화면은 준비된 데이터의
소비자다. 조회나 파일 저장은 SEC 수집, XBRL 파싱, 공시 선택, 회계 계산 또는 검토
승인을 자동 실행하지 않는다.

## 준비된 bundle 열기

새 checkout에는 SEC 캐시, 준비된 Parquet bundle 또는 검토 자료가 포함되지 않는다.
Python 3.12와 프로젝트 의존성을 설치하고, 별도로 준비한 bundle이나
`analysis_current.json`이 있는 관리자 catalogue 경로를 지정한다.

```bash
uv sync --extra dev
export SEC_XBRL_READY_BUNDLE=/path/to/prepared/bundle-or-admin-catalog
```

```python
import os
from pathlib import Path

from sec_xbrl.analysis import open_analysis

client = open_analysis(Path(os.environ["SEC_XBRL_READY_BUNDLE"]))
overview = client.overview("NFLX", fiscal_start=2023, fiscal_end=2026)

for row in overview["rows"]:
    cells = [cell for cell in overview["cells"] if cell["row_id"] == row["row_id"]]
    print(row["label"], [(cell["fiscal_year"], cell["fiscal_quarter"], cell["value"])
                         for cell in cells])
```

`overview`가 U1 핵심 요약을 제공한다. `context`에는 view, as-of, review cutoff,
publication과 정확한 기간 범위가 들어 있다. QTD와 INSTANT는 별도 행/기간 종류이며,
null은 0이나 공시 부재를 뜻하지 않는다. `quality_status == "BLOCK"`인 셀은 표시값이
null이고 분석 표시값과 분리된 원값·출처 정보에 보존된다. 예시의 NFLX와
FY2023–2026은 해당 14분기가 실제 준비된 bundle에서 확인한 범위다. 자신의
publication에 준비된 ticker와 기간으로 바꿔 사용한다.

## 구성과 출처 확인

U2/U3 탐색은 overview가 반환한 동일 context를 전달한다. 서로 다른 Axis 또는
basis는 독립 관점이며 합산하지 않는다.

```python
groups = client.list_breakdowns("revenue", context=overview["context"])["groups"]
lens = next(group for group in groups if group["lens_type"] == "DIMENSIONAL_VIEW")
axis = client.axis_timeseries("NFLX", lens["node_id"], context=overview["context"])

reported = next(
    cell for cell in overview["cells"]
    if cell["status"] in {"REPORTED", "DERIVED"}
)
trace = client.trace(reported["cell_id"], context=overview["context"])
```

`axis`는 전체 Member 행, 매핑 epoch, 단위/분모, basis, 경고, 검토 관계와 companion
publication 식별을 보존한다. `trace`는 같은 셀의 filing/fact 또는 공식과 입력 lineage로
돌아가는 경로다. 준비되지 않은 기간은 reason이 있는 `UNAVAILABLE`로 남는다.

## JSON, CSV, HTML, XLSX 저장

```python
from sec_xbrl.consumer.export import export_snapshot

snapshot = client.overview_snapshot(
    "NFLX",
    fiscal_start=2023,
    fiscal_end=2026,
    periods=[(2026, 1), (2026, 2)],
    row_ids=["revenue"],
)
export_snapshot(snapshot, Path("NFLX-revenue-2026H1.xlsx"))

axis_snapshot = client.axis_snapshot(
    "NFLX", lens["node_id"], context=overview["context"]
)
export_snapshot(axis_snapshot, Path("NFLX-revenue-axis.json"))
```

API의 `periods`와 `row_ids` 순서가 부분 export의 순서다. 화면에서는 현재 기업,
핵심 항목 또는 Axis의 전체 준비 표를 네 형식으로 저장한다. 화면의 접기/깊이로 숨긴
행도 저장 파일에 포함된다. 표시 단위는 준비된 원 단위(divisor 1)이며 단위 분자/분모,
경고, null/BLOCK, source와 공식/입력은 snapshot에 함께 보존된다.

오프라인 화면은 hierarchy/Axis companion까지 준비된 bundle에서 새 디렉터리로
명시적으로 만든다. 기본 analytical bundle만 있고 companion이 없으면 먼저 관리자
준비 절차로 hierarchy/Axis publication을 결합해야 한다.

```python
import os
from pathlib import Path

from sec_xbrl.analysis import open_analysis
from sec_xbrl.display.hierarchy import render_hierarchy

client = open_analysis(Path(os.environ["SEC_XBRL_READY_BUNDLE"]))
render_hierarchy(client, destination=Path("local-investor-report"))
```

`local-investor-report/index.html`과 함께 생성된 파일을 같은 디렉터리 구조로 공유한다.
로컬 파일이며 서버나 외부 업로드가 필요하지 않다.

## 새 기업 등록과 준비

등록은 준비 완료가 아니다. 관리자 catalogue에 기업과 이미 준비된 history
publication을 등록한 뒤 별도의 새 목적지에 consumer bundle을 만든다.

```python
import os
from pathlib import Path

from sec_xbrl.analysis import prepare_catalog
from sec_xbrl.company_reports import register_company

admin = Path(os.environ.get("SEC_XBRL_ADMIN", "local-admin"))
history = Path(os.environ["SEC_XBRL_HISTORY_PUBLICATION"])
register_company(admin, ticker="NFLX", publication=history, fiscal_start=2023, fiscal_end=2026)
bundle = prepare_catalog(catalog=admin, destination=Path("prepared-consumer"), tickers=("NFLX",))
```

미보유 SEC 입력을 수집해 갱신하는 U4 `refresh_analysis`는 네트워크, cache/workspace,
as-of와 review-as-of를 명시하는 관리자 작업이다. 조회 중에는 호출되지 않는다.
신규 기업은 등록만으로 `READY`나 `DISCLOSURE_MISSING`이 되지 않는다. consumer가
생기기 전에는 `company_reports.read_target_status(admin, ticker="NFLX")`, 준비된
consumer에서는 `client.target_status("NFLX")`로 상태를 확인한다. 관리자 상세 계약은
[prepared interface](../implementation/investor-analysis-interface.md)와
[U4 전달](../implementation/u4-continuous-refresh-delivery.md)을 따른다.

U1–U5의 정확한 인수 범위와 한계는
[투자자 로드맵](../planning/investor-analysis-roadmap.md), 현재 main 전달 상태는
[U3–U5 main 전달](../implementation/u3-u5-main-delivery.md)에서 확인한다.
