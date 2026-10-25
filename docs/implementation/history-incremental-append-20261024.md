# History 증분 append v1 — 2026-10-24

## 범위와 상태

이 milestone은 한 회사의 공시가 기존 입력 뒤에 정확히 한 건 추가된 경우에만 이전
History publication을 명시적으로 받아 재사용한다. 기본 `build_history` 동작은 그대로
전체 생성이며, `--previous-history`와 증명 자료가 함께 주어진 호출만 증분 경로를
시도한다. source `a83a3b2…`는 로컬 검사와 실제 AAPL 단일 후보 측정을 완료했고,
2026-10-25 독립 검증 PASS와 ROOT 로컬 수락을 받았다. `main` 병합과 운영 채택은 아직
완료되지 않았다.

이 변경은 Raw 추출이나 원본 Fact 근거, canonical ID, 공시 선택 view, 회계 기간,
Q4/YTD 파생 규칙을 바꾸지 않는다. 과거 50개 회사의 완료 검증과 109단계 독립 감사도
다시 실행하지 않았다.

2026-10-25의 좁은 후속 구현은 고정 as-of·정책의 strictly-later 비수정 `10-Q`에서
dependency proof가 성립할 때 quarter publisher의 unchanged cell과 기존 derived cell을
재사용한다. 최종 수락 상태와 실제 측정은
[History quarter cell delta v1](history-quarter-cell-delta-20261025.md)에 기록한다. 아래의
dirty period class 전체 재생성 설명은 이 FAST 조건을 증명하지 못한 입력에 적용되는
보수적 fallback이며, 이 문서의 기존 append 수락 범위는 그대로다.

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
- T3는 reader-attested T1의 typed observation prefix를 대조하고, cached relationship
  node·edge를 ID로 찾은 뒤 현재 reader-attested T2의 edge 순서에 맞춰 재배열한다.
  따라서 old/new accession이 관계 순서에서 섞여도 exact suffix를 요구하지 않는다.
  ID 충돌, foreign/missing node, endpoint 또는 typed prefix 불일치가 있으면 T3만 기존
  전체 producer로 전환한다.
- History 표는 새 공시의 `CURRENT_FOCUS`가 건드린 period class 전체를 다시 만든다.
  historical comparative 행만으로 table을 dirty 처리하지 않는다. FY/YTD 변화는 QTD
  closure도 dirty로 본다. as-of/view 정책이 바뀌면 History 표는 보수적으로 모두 다시
  만들지만 as-of와 무관한 T1~T4 증분은 유지한다. 깨끗한 표의 파일은 이전 publication의
  선언 hash를 확인한 뒤 복사한다.
- quarter publisher는 모든 source table을 읽어 QTD derivation 입력을 보존하되 dirty
  target만 다시 조립하고 나머지 final table을 같은 방식으로 복사한다.

증명 준비 뒤에는 과거 Raw cohort와 이전 publication/canonical mapping 객체를 새 graph와
panel 생성 전에 해제한다. 남는 상태는 suffix snapshot, 작은 filing/ledger 입력, path,
hash, dirty class와 receipt 자료뿐이다.

## 호출 방법

Python API는 새 input 전체를 가리키는 `intake_manifest`, 비어 있는 새 `output_root`와
함께 이전 publication 및 그 재사용 증명을 명시한다.

```python
build_history(
    intake_manifest=current_intake,
    output_root=new_output,
    previous_history=previous_publication,
    previous_reuse_evidence=approved_evidence,
)
```

같은 호출의 CLI 형태는 다음과 같다.

```bash
python -m sec_xbrl.history build \
  --intake-manifest CURRENT_INTAKE.json \
  --output-root NEW_OUTPUT_ROOT \
  --previous-history PREVIOUS_HISTORY_ROOT \
  --previous-reuse-evidence APPROVED_REUSE_EVIDENCE.json
```

두 opt-in 인자를 주지 않으면 기존 전체 생성 경로다. 이전 publication이 없거나 evidence,
source/rule identity, content pin, strict suffix, typed prefix 또는 graph 무결성 증명이
맞지 않으면 기존 publication을 수정하지 않고 전체 생성으로 전환한다. 기존 output과
충돌하거나 새 output의 scope/input이 맞지 않는 경우에는 오류로 종료한다.

## 검증과 측정 경계

bounded cached NVDA 두 공시 fixture에서 이전 한 건 publication, 두 건 전체 생성, 두 건
증분 생성을 비교했다. T1~T4 전체 dataset과 final columns/rows/cells의 값·타입·ID·순서가
같음을 확인했고, `prior_candidate_publication`의 불변 publication 절대 경로만 재사용
출처 차이로 명시적으로 정규화했다. 최종 endpoint membership 수정 뒤 직접 영향 unit
6건이 통과했고, 같은 수정 직전의 cached full-vs-append integration 1건도 통과했다.
마지막 수정은 endpoint마다 node ID 집합을 다시 만들던 O(E·N) 반복을 동일한 단일 집합
조회로 바꾼 것으로 값·순서 판정은 바꾸지 않았다.

실제 AAPL 22→23 공시 append 후보는 독립 검증 전에 한 번만 실행했다. 비교 기준
99.110초/2,183,675,904바이트는 이전 source의 단일 historical baseline이며 같은 source의
동시 paired baseline이 아니다. 후보의 공통 discover·cached ingest 1.540초, migration
proof 준비 0.182초, build 89.833초, query 0.607초를 합친 전체는 92.161초로 7.01%
짧았다. quarter publisher는 38.513초에서 34.020초로 11.67% 짧았다. 20ms 간격 관측
RSS 최대값은 2,092,429,312바이트로 4.18% 낮았으며 순간 최대값을 놓칠 수 있다.

이 실행은 이전 22개 공시와 새 공시 1개를 구분했고, History 10개 표 중 FY와 YTD_6M의
두 view 4개를 재사용하며 INSTANT, QTD_3M, YTD_9M의 6개를 다시 만들었다. T3는
reader-attested T2의 관계 edge 순서를 기준으로 old/new relationship-only node와 edge를
재배열한 `STAGE_PRESERVING_MERGE`를 사용했다.

앞선 R3는 T3 observation stage 대조 방식 때문에 `FULL_FALLBACK`했고 RSS가 51.89%
증가해 미수락으로 보존했다. R4b는 실제 T2 관계 순서가 old/new accession을 섞는다는
사실을 prefix로 잘못 가정해 fallback했다. R5는 endpoint마다 전체 node ID 집합을 다시
만드는 O(E·N) 결함으로 중단했으며 source와 실패 시도 증거를 보존했다. R6는 이 반복만
제거한 뒤 새 후보를 한 번 실행한 결과다.

새 후보와 기존 full reference를 한 번 비교해 History 31개 파일과 한쪽당 31,230개
record, T1 4개 dataset, T2 edge 51,248개, T3 node 53,238개와 edge 107,750개,
T4 ledger 23개가 같음을 확인했다. 값·Python 타입·schema·순서·ID·기간·단위·원본
출처를 보존했고 `prior_candidate_publication` 절대 경로만 명시적으로 정규화했다.
기계 보고서는
`work/actual_quarter_append_20261024/incremental-append-v1-r6/final_report.json`에 있으며
SHA-256은 `6dec17ca5e84e40ff4da552beb9d7dea3b4e33415d1b3775d6833a09f030a262`이다.
단일 회사·공시 pair 결과이므로 반복 append나 다른 회사의 속도를 주장하지 않는다.

독립 검증 보고서는
`work/actual_quarter_append_20261024/incremental-append-v1-r6/independent_review/report.json`
(SHA-256 `b7ce03da44028af71ce4c2bc6e4a6c6433c85e51565cc3488bff6eaf2b3c1c2d`)이며
PASS다. ROOT 로컬 수락은 같은 R6 디렉터리의 `lead_acceptance.json`
(SHA-256 `55319b3cdb8b3f1a333e569046e42067ec2aec258966b8a753b1270a6b4676f8`)에
기록했다. 수락 범위는 opt-in append source와 이 bounded actual pair이며 운영 배포나
`main` 병합을 뜻하지 않는다.

남는 비용은 전체 canonical mapping 계산, 이전 Raw 정상 입력 로드와 prefix 확인, dirty
period class 전체 재생성이다. 이는 행 단위 producer 증분화가 아니다.
