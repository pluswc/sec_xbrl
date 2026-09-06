# 다기업 운영 검증 팩 (v1) / Multi-company operational validation pack (v1)

이 팩은 처음 제시된 NVDA·AMD·MSFT를 고정 전용 구현으로 만들지 않고,
AAPL·AMZN과 실제 수정공시 사례까지 포함할 수 있도록 만든 **선언형 검증
명세**다. 기계 판독 기준은
[`multicompany-operational-validation-v1.json`](multicompany-operational-validation-v1.json)이다.

## 현재 증거와 상태 / Current evidence and status

| 회사 | CIK | 로컬 Layer 1 | 기준 공시 | 의미 |
| --- | --- | --- | --- | --- |
| NVDA | `0001045810` | AVAILABLE | `0001045810-24-000316` 10-Q | 운영 publication 후보에 포함 가능 |
| AMD | `0000002488` | AVAILABLE | `0000002488-24-000163` 10-Q | 운영 publication 후보에 포함 가능 |
| MSFT | `0000789019` | AVAILABLE | `0000950170-24-118967` 10-Q | 2024-09-30, controlled taxonomy bootstrap 후 offline 재적재 |
| AAPL | `0000320193` | AVAILABLE | `0000320193-24-000123` 10-K | 운영 publication 후보에 포함 가능 |
| AMZN | `0001018724` | AVAILABLE | `0001018724-24-000161` 10-Q | 2024-09-30, 기존 taxonomy cache로 offline 적재 |

AVAILABLE은 각 행에 선언된 로컬 immutable Layer 1 manifest가 실제로 존재한다는
뜻이다. NVDA·AMD·AAPL은 `20260827T051322Z`, MSFT·AMZN은 새 불변 run
`20260906T020000Z_msft_amzn_2024q3`의 증거를 사용한다. MSFT는 처음 기존 cache로
offline 검증했을 때 taxonomy/transform gate가 실패했고, 통제된 bootstrap 후 별도
offline reload에서 성공했다. AMZN은 기존 cache의 offline 적재로 성공했다.

이는 회사별 Raw availability이지, 다섯 회사를 한 operational comparison으로
제공할 수 있다는 뜻은 아니다. 두 input run이 섞여 있고 다섯 CIK를 함께 attest하는
`parquet-operational-v1` T1~T4 root도 없으므로, 공통 비교는 계속 **차단**된다.

## 수정공시 검증 사례 / Amendment validation case

AMD FY2025에는 다음 두 Layer 1 snapshot이 있다.

| 구분 | accession | form | filed date | report date |
| --- | --- | --- | --- | --- |
| 원본 | `0000002488-26-000018` | 10-K | 2026-02-04 | 2025-12-27 |
| 수정본 | `0000002488-26-000021` | 10-K/A | 2026-02-04 | 2025-12-27 |

두 공시는 같은 보고기간·제출일이라도 서로 다른 accession이다. 수정본의 작은
fact 집합을 원본 전체로 확장하거나, 원본 fact를 수정본에 복사해서는 안 된다.
선택 결과에는 언제나 accession·form·filed date·source fact 계보가 남아야 한다.
accession 숫자만으로 “몇 번째 수정”을 추론하지 않는다.

## 발행 게이트 / Publication gate

이 팩은 네 개의 기존 운영 root(T1 reported observations, T2 relationships,
T3 exploration graph, T4 accession ledger)를 읽는 소비자 검증이다. 다섯 CIK가 하나의 immutable Layer 1 input run에 있고,
네 root가 모두 `parquet-operational-v1`, 동일 CIK scope와 fingerprint를 attest할
때만 다섯 회사 비교를 허용한다. 그 전에는 fail-closed로 거절한다.

The same rule prevents a partly available cohort from looking complete: no
consumer may quietly serve NVDA/AMD/AAPL as a five-company answer.

## 재현 가능한 로컬 증거 / Reproducible local evidence

개발 환경에 corpus가 있다면 다음처럼 integration evidence를 실행한다. CI나
새 환경에서 corpus가 없으면 해당 검사는 명시적으로 skip하며, 외부 SEC 접근을
시도하지 않는다.

```bash
SEC_XBRL_DATA_ROOT=/path/to/sec_xbrl \
  .venv/bin/python -m pytest tests/integration/test_multicompany_operational_validation_evidence.py -q
```

이 검사는 JSON에 기록한 CIK, accession, form, fact corpus 수가 실제 Layer 1
manifest와 일치하는지 검증한다. 숫자·원본 SEC package·Parquet 산출물은 이 저장소에 커밋하지 않는다.
