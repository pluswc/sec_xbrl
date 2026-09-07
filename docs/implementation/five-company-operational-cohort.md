# 5개사 운영 Cohort Release / Five-company operational cohort release

`five-company-reference-2024q3-v1`는 NVDA, AMD, MSFT, AAPL, AMZN의 **선언된
reference filing 다섯 건**을 하나의 Layer 2 입력으로 검증해 T1--T4 운영
Parquet을 발행하는 재현 가능한 cohort다. 이는 원본 Layer 1을 새 run으로 복사하거나
기존 source run을 수정하는 작업이 아니다.

## 효과 / Outcome

- 두 source run에 있던 다섯 immutable snapshot을 정확한 accession 단위로 함께
  attest한다.
- T1 reported observations, T2 filing relationships, T3 exploration graph,
  T4 accession ledger가 같은 Layer 1 fingerprint와 CIK scope를 갖는다.
- `OperationalAnalyticsQueryService`가 이 네 root만 읽어 개별 회사 panel을
  제공할 수 있다. cross-company 동치화 정책은 여전히 T8의 fail-closed 규칙을
  그대로 따른다.

## 입력 선언 / Declared inputs

| CIK | accession | source run |
| --- | --- | --- |
| `0001045810` | `0001045810-24-000316` | `20260827T051322Z` |
| `0000002488` | `0000002488-24-000163` | `20260827T051322Z` |
| `0000320193` | `0000320193-24-000123` | `20260827T051322Z` |
| `0000789019` | `0000950170-24-118967` | `20260906T020000Z_msft_amzn_2024q3` |
| `0001018724` | `0001018724-24-000161` | `20260906T020000Z_msft_amzn_2024q3` |

`CohortReleaseAdapter`는 각 선언 경로의 Layer 1 manifest, 정확히 8개 raw
Parquet table, table count와 byte hash, filing provenance 및 cross-table reference를
기존 Layer 1 gate로 재검증한다. 이 검증을 통과한 snapshot만 Layer 2 run inputs로
들어간다.

## 실제 발행 증거 / Actual publication evidence

로컬 data cache에서 발행한 결과의 shared fingerprint는
`7b46a0848bb41ff136f54e1efa21619b3e400845ed248a3e65ec0ce7f46ff166`다.
생성 Parquet은 커밋하지 않으며, 아래는 manifest가 기록한 row count다.

| root | datasets / rows |
| --- | --- |
| T1 | reported observations 5,477; concept map 6,695; axis map 134; member map 363 |
| T2 | filing relationship edge 15,487 |
| T3 | exploration node 14,569; exploration edge 30,188 |
| T4 | accession version ledger 5 |

발행 함수는 `publish_five_company_reference_cohort(data_root=..., output_root=...)`다.
`tests/integration/test_five_company_operational_cohort_cached.py`는 cache가 있을 때
다섯 CIK admission, 네 root fingerprint, 그리고 NVDA의 non-empty operational
company panel query를 실제로 검증한다. cache나 raw SEC 접근을 CI에서 요구하지
않으며, cache가 없으면 명시적으로 skip한다.

## 제한 / Limits

이 cohort는 다섯 reference filing의 availability release이지, 달력상 완전히 같은
분기나 모든 역사 filing의 cross-company panel이 아니다. AAPL은 선언된 10-K이며,
회사별 회계연도/분기는 query scope에 명시해야 한다. custom QName과 서로 다른
standard QName은 이 release만으로 동치가 되지 않는다.
