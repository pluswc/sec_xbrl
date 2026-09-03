# T4-A — Accession Version Ledger

## 사용자 효과

한 기업의 원본 공시와 수정 공시를 시간순으로 열어 보고, 각 공시가 수정본인지,
그 판단에 사용된 DEI 원문 근거가 무엇인지, 원본 공시 연결이 확정인지 검토
후보인지 확인할 수 있다. 이 데이터셋은 어떤 fact를 현재 값으로 선택하지 않는다.

## 운영 Parquet 데이터셋

`accession_version_ledger`는 Layer 1의 immutable snapshot 하나당 한 행이다.
CIK별 `accession_version_ledger/ledger.parquet`로 저장되므로 한 회사의 공시 이력은
다른 CIK를 읽지 않고 조회할 수 있다. 모든 행은 source filing ID, snapshot ID,
accession, form, filed date, report date를 보존한다.

각 행은 다음 수정 근거를 함께 보존한다.

- `amendment_flag_state`와 `dei_amendment_flag_raw`/fact ID: `dei:AmendmentFlag`
- `dei_amendment_description_raw`/fact ID: `dei:AmendmentDescription`
- `amends_accession`, `amendment_linkage_state`, method, review status와 evidence
- description에 실제로 적힌 경우만 `reported_amendment_ordinal`; 없으면
  `NOT_REPORTED`/`NOT_INFERRED`

## 수정 연결 안전 규칙

`LINKED`는 Layer 1 `filing.amends_accession` 또는 설명 안의 명시 accession처럼
직접적인 accession 근거가 있을 때만 사용한다. 같은 CIK, 기본 form(10-Q vs
10-Q/A), report date, 더 이른 filed date가 맞는 원본은 `CANDIDATE`로만 기록하고
`REVIEW_REQUIRED`로 남긴다. 후보가 없거나 여러 개이면 `UNKNOWN`이다.

accession의 숫자 순서, fact 값의 차이, label 변화는 수정 연결이나 수정 차수의
근거가 아니다. 따라서 이 ledger는 amendment selection, as-of selection, recast,
Q4 파생, 또는 분석 피벗을 수행하지 않는다.

## 정렬과 조회

`AccessionVersionLedgerReader`는 `filed_date`를 우선 정렬하고 accession은 같은
날짜에서 재현 가능한 tie-breaker로만 사용한다. accession 번호를 시간 또는
수정 차수로 해석하지 않는다. Reader-attested publication 조회와 CIK 단위의
Parquet fast query 모두 동일한 정렬·행 계약을 검증한다.
