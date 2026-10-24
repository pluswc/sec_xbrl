# History 증분 append v1 — 2026-10-24

## 범위와 상태

이 milestone은 한 회사의 공시가 기존 입력 뒤에 정확히 한 건 추가된 경우에만 이전
History publication을 명시적으로 받아 재사용한다. 기본 `build_history` 동작은 그대로
전체 생성이며, `--previous-history`와 증명 자료가 함께 주어진 호출만 증분 경로를
시도한다. 구현 후보는 로컬 검사까지 완료했으며 독립 검증, 로컬 수락, `main` 병합,
운영 채택은 아직 완료되지 않았다.

이 변경은 Raw 추출이나 원본 Fact 근거, canonical ID, 공시 선택 view, 회계 기간,
Q4/YTD 파생 규칙을 바꾸지 않는다. 과거 50개 회사의 완료 검증과 109단계 독립 감사도
다시 실행하지 않았다.

## 재사용 계약

재사용은 다음 조건을 모두 증명할 때만 허용한다.

- CIK가 하나이고 현재 Layer 2 입력이 이전 입력의 정확한 한 건 suffix이며 새 공시의
  `(filed_date, accession, snapshot_id)`가 이전 마지막 공시보다 뒤에 있다.
- 이전 final/reported manifest의 plan, view, input fingerprint, source manifest와 T1~T4
  manifest가 서로 맞는다.
- canonical mapping의 이전 prefix가 타입까지 같다. 구조체 schema 확장으로 생긴
  missing/명시적 `null`만 schema union으로 허용하며 `True`, `1`, `1.0`은 같게 보지
  않는다.
- `src/sec_xbrl` 아래 모든 Python producer·policy 바이트의 지문이 이전 증명과 같다.
  기존 publication에는 명시적 migration evidence가 필요하고, 이 구현이 만든 다음
  publication은 외부의 원자적 reuse receipt로 다음 append를 증명한다.
- migration evidence와 다음 receipt는 T1~T4 manifest hash뿐 아니라 각 operational
  payload 파일의 상대 경로와 전체 SHA-256도 고정한다. 첫 legacy adoption evidence는
  이전 source contract와 호환성을 ROOT가 승인한 자료여야 한다. 이는 semantic 감사를
  반복하는 절차가 아니라 재사용할 immutable bytes의 무결성 확인이다.

증명 실패, source/rule 변경, backdated 입력, prefix 변경, receipt 손상은 기존 전체 생성
경로로 전환한다. 이전 publication은 수정하지 않으며 receipt는 output root의 별도
파일이다. receipt는 full/semantic 검증 완료를 뜻하지 않는다.

## 실제 처리 범위

- T1은 이전 observation/exclusion을 재사용하고 새 공시만 materialize한다. 세 canonical
  mapping은 전체 입력에서 한 번 계산하고 이전 prefix를 확인한 뒤 현재 전체 mapping을
  발행한다.
- T2는 이전 edge를 재사용하고 새 공시 edge만 변환한다.
- T4는 이전 ledger를 재사용하고 전체 입력의 작은 amendment evidence를 바탕으로 새
  accession row만 만든다.
- T3는 노드 덮어쓰기와 stage 순서를 정확히 증명할 수 있을 때만 stage-preserving merge를
  쓴다. mapping row 표현이나 relationship stage가 exact suffix가 아니면 T3만 기존 전체
  producer로 전환한다.
- History 표는 새 공시가 건드린 period class 전체를 다시 만든다. FY/YTD 변화는 QTD
  closure도 dirty로 본다. as-of/view 정책이 바뀌면 History 표는 보수적으로 모두 다시
  만들지만 as-of와 무관한 T1~T4 증분은 유지한다. 깨끗한 표의 파일은 이전 publication의
  선언 hash를 확인한 뒤 복사한다.
- quarter publisher는 모든 source table을 읽어 QTD derivation 입력을 보존하되 dirty
  target만 다시 조립하고 나머지 final table을 같은 방식으로 복사한다.

증명 준비 뒤에는 과거 Raw cohort와 이전 publication/canonical mapping 객체를 새 graph와
panel 생성 전에 해제한다. 남는 상태는 suffix snapshot, 작은 filing/ledger 입력, path,
hash, dirty class와 receipt 자료뿐이다.

## 검증과 측정 경계

bounded cached NVDA 두 공시 fixture에서 이전 한 건 publication, 두 건 전체 생성, 두 건
증분 생성을 비교했다. T1~T4 전체 dataset과 final columns/rows/cells의 값·타입·ID·순서가
같음을 확인했고, `prior_candidate_publication`의 불변 publication 절대 경로만 재사용
출처 차이로 명시적으로 정규화했다. 관련 graph 검사와 합쳐 8건이 통과했다.

실제 AAPL 22→23 공시 append 후보 측정은 독립 검증 전 한 번만 수행한다. 비교 기준
99.110초/2,183,675,904바이트는 이전 source의 단일 historical baseline이며 같은 source의
동시 paired baseline이 아니다. migration proof 준비, 이전 파일 hash/prefix 확인을 후보
시간과 RSS에 포함한다. 실제 결과가 나오기 전 steady-state 반복 효과를 추정하지 않는다.

남는 비용은 전체 canonical mapping 계산, 이전 Raw 정상 입력 로드와 prefix 확인, dirty
period class 전체 재생성이다. 이는 행 단위 producer 증분화가 아니다.
