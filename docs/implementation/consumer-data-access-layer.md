# Consumer Data Access Layer / 소비자 데이터 접근 계층

## Purpose / 목적

Consumer Data Access Layer는 분석 데이터의 **공통 조회 규격**이다. 이는 HTTP
API나 MCP 서버를 뜻하지 않으며, Excel 전용 인터페이스도 아니다. Python
라이브러리, DB/Parquet 어댑터, 대시보드, 리서치 도구, 그리고 필요할 경우의
전송 계층이 같은 의미의 조회 결과를 사용하게 하는 경계다.

현재의 구현체는 `sec_xbrl.analytics.ConsumerDataAccess` 계약과 이를 구현한
`AnalyticalRepository`다. C2에서는 `Layer2PublicationReader`가 원자적으로
발행된 canonical JSONL Layer 2 run을 manifest·run fingerprint·row count·canonical
content SHA-256까지 검증한 뒤 Repository를 구성한다. 각 row에는 run version,
fingerprint, contract version, manifest SHA-256로 이루어진 publication identity가
남는다. 이는 JSONL publication adapter이며 DB 또는 Parquet adapter는 아직
구현되지 않았다. 이후 DB 또는 Parquet 구현체도 이 계약을
충족하면 소비자는 저장 위치를 알 필요가 없다.

```text
Raw Layer 1 → Analytical plane → Derived Metrics plane
                                      ↓
                       Consumer Data Access Layer
                                      ↓
        Excel | dashboard | research library | future transport adapter
```

## What it is not / 하지 않는 일

- SEC ZIP, Inline XBRL, Arelle 또는 parser 객체를 읽지 않는다.
- 재제시 여부, 비교가능 basis, 기간, mapping 또는 Metric 공식을 새로 판단하지
  않는다.
- Excel의 레이아웃, 들여쓰기, 색상, 합계 같은 표시 정책을 만들지 않는다.
- HTTP endpoint, 인증, MCP tool 등록 또는 wire format을 정의하지 않는다.

따라서 Excel만을 위해 별도 데이터를 만드는 것이 아니라, 분석적으로 의미
있는 값·기간·차원·상태·근거를 공통 형식으로 전달한다.

## Contract / 계약

모든 구현체는 읽기 전용이며 입력 데이터와 결과를 공유 가변 객체로 노출하지
않는다. 회사 selector는 CIK, ticker, canonical ID 또는 정규화된 정확한 이름을
해결한다. 의미 유사성(label similarity)으로 Concept나 Metric을 추정하지 않는다.

| Method | Query purpose | Critical commitment |
| --- | --- | --- |
| `resolve_company(selector)` | 한 회사를 명시적으로 식별 | 없거나 모호하면 오류; 임의 선택 금지 |
| `get_fact_series(...)` | Analytical Fact 시계열 | QTD/YTD/FY/INSTANT 혼합 금지 |
| `get_analytical_facts(...)` | 검증된 L2 `analytical_fact` 직접 조회 | 명시적 view, exact filter, publication identity 보존 |
| `discover_capabilities(...)` | 실제 적재된 Concept/Axis/Member 탐색 | M5 관측 상태와 원천 근거 보존 |
| `discover_metrics(...)` | 회사의 검증된 Derived Metric 후보 탐색 | 계산·as-of 선택·basis 대체 금지 |
| `get_metric_series(...)` | view/as-of를 명시한 Metric 시계열 | 검증된 M1→M2 발행본만 사용 |
| `trace_fact(...)`, `trace_metric(...)` | 한 값의 근거 추적 | Filing/Fact/입력/발행본 lineage 보존 |
| `compare_companies(...)` | Layer 3 비교 panel 조회 | similarity를 accounting equivalence로 승격 금지 |

각 일반 조회 결과는 가능한 범위에서 회사, 기간·frequency, `view`,
`as_of_date`, `basis_version`, full dimension signature, unit/scaling,
status/unavailable reason, source type 및 원천 lineage를 그대로 보존한다.
없는 항목은 채우거나 추정하지 않는다.

## Metric discovery / Metric 탐색

`discover_metrics(company, *, metric_id=None, definition_version=None,
frequency=None, view=None)`는 이미 해시 검증을 통과하여 Repository에 적재된
M2 candidate만 탐색한다. 요청 필터는 모두 정확 일치다.

반환 row의 grain은 다음 변형을 절대 합치지 않는 Metric discovery variant다.

- CIK, Metric ID, Metric definition ID와 version, formula/version
- view와 `basis_version`
- full company canonical dimension key
- input/output unit semantics, series type와 period class
- calculation status, unavailable reason, source type, mapping versions

동일한 variant의 여러 기간·as-of revision은 `observed_period_classes`,
`observed_period_keys`, `observed_as_of_dates`로 표시한다. 모든 후보의 완전한
사본은 `observed_metric_records`에 남고, `derived_metric_ids`, series candidate
IDs, source run fingerprint/manifest identity도 함께 반환된다. 그러므로
dimensional, basis, definition 또는 unavailable 변형이 “gross margin이 있다”는
넓은 주장 뒤에 숨지 않는다.

관측 후보가 없을 때에는 `NOT_REPORTED` query row를 반환할 수 있다. 이는
`SUPPLIED_VERIFIED_METRIC_PUBLICATIONS_ONLY` 범위에서 정확한 요청에 맞는
candidate가 없다는 뜻일 뿐, SEC 공시 전체에 해당 Metric이 없다는 주장이
아니다. 이 제한은 M5 capability discovery의 `NOT_REPORTED` 원칙과 같다.

## Adapter obligations / 어댑터 의무

향후 DB/Parquet adapter는 물리 저장소가 달라도 다음을 보장해야 한다.

1. 검증된 publication/root 또는 동등한 immutable release identity를 확인한다.
2. Raw, Analytical, Derived Metrics의 경계를 유지하고 reported 값을 변경하지
   않는다.
3. complete dimension, period class, view, as-of date, basis, status와 lineage를
   손실 없이 반환한다.
4. Metric 조회에서 현재 basis나 값을 새로 선택하지 않고, upstream governed
   selection만 전달한다.
5. 동일 요청은 저장 순서와 무관한 결정적 결과를 돌려주며 복사본을 반환한다.
6. 불명확하거나 충돌한 immutable Metric identity는 fail closed 한다.

DB adapter는 SQL을 사용할 수 있고 Parquet adapter는 파일을 읽을 수 있다.
그 차이는 구현 세부 사항이며, 소비자 contract 또는 분석 정책의 차이가 아니다.
현재 C2 JSONL adapter를 DB/Parquet adapter로 표현해서는 안 된다.

## Current boundary and future work / 현재 범위와 후속 작업

현재 `AnalyticalRepository`는 publication-backed in-process 구현체다. DB,
Parquet, HTTP, MCP는 아직 이 계약의 구현체가 아니다. 실제 Excel migration은
이 계약을 읽는 표시 consumer를 만드는 별도 작업이며, Excel만의 계산 또는
selection rule을 추가하는 작업이 아니다.

계약을 확장할 때는 먼저 Raw/Analytical/Derived plane에서 필요한 값이
governed publication으로 존재하는지 확인한다. 부족하다면 소비자에서
우회하지 않고 앞선 plane의 적재·mapping·metric 정의를 개선한다.
