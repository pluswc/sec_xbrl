# History quarter cell delta v1 — 2026-10-25

## 범위와 전달 상태

`HISTORY_QUARTER_CELL_DELTA_V1`은 증명된 History append에서 unchanged final cell을
재사용하고 새 fiscal column 및 파생 dependency closure만 기존 규칙으로 계산하는 opt-in
경로다. public Parquet schema, 값, 타입, ID, 순서, 기간, 단위, 원본 provenance와 불변
publication 계약은 바꾸지 않는다. 기존 full quarter producer는 보수적 fallback과 oracle로
남는다.

제품 source `d5a6a3b0c53187bfefb24fe72ca3e4ec5340e48d`는 2026-10-25 독립 검증
25건 PASS를 받았고 ROOT가 bounded AAPL actual pair 범위에서 로컬 수락했다. 독립 보고서는
`work/quarter_cell_delta_20261025/independent_review_r2/report.json`
(SHA-256 `36651cf59f7016a52cfc8ec44a0a2eb6a9816efb61e113ddeeb7e2fa48c499f2`),
로컬 수락은 `work/quarter_cell_delta_20261025/candidate-r6/lead_acceptance.json`
(SHA-256 `b9328cf9e0cf7fc66a4616dea742a3773e0a6135cc6ba6cfa0b308890d187c0a`)에
기록했다. `main` 병합과 운영 runtime 반영은 아직 수행하지 않았다.

## FAST 입력 증명과 fallback

FAST 경로는 builder가 만든 private capability가 현재 reported manifest SHA-256,
input fingerprint, T1~T4 root, 이전 reported/final publication과 현재 code identity에
정확히 묶일 때만 활성화된다. 다음 조건을 모두 만족해야 한다.

- strictly-later 단일 CIK의 비수정 `10-Q` 한 건이다.
- as-of, view, selector, period, mapping, quarter 정책과 producer code identity가 같다.
- 새 `CURRENT_FOCUS` fiscal key가 이전 key와 겹치지 않고 fiscal chronology 뒤에 온다.
- typed T1 prefix와 T4 prefix가 같고 T3 stage-preserving merge 및 새 filing graph 격리를
  증명한다.
- current reported table의 scalar cell/row/column routing과 multiplicity가 이전 재사용 범위와
  충돌하지 않는다.

`10-K`, amendment, backfill, old fiscal insertion, as-of/view/policy 변경, T3 full fallback,
schema·ID·순서 충돌, stale capability와 증명 범위 밖 입력은 FAST 대상이 아니다. 이 경우
generic nested-payload 비교 prototype을 실행하지 않고 이미 수락된 table-level full quarter
경로로 전환한다. 따라서 고정 as-of·정책의 regular 10-Q append에서 얻은 결과를 모든 운영
refresh에 일반화하지 않는다.

## 처리 방식과 정확성

현재 reported publication의 scalar ID·row·column routing은 한 번 스캔한다. 새 fiscal
column의 payload만 전체 디코드하고 기존 period attestation과 reclassification을 수행한다.
이전 final의 unchanged reported cell은 native Parquet projection으로 스트리밍하며 허용된
`prior_candidate_publication` 경로만 현재 reported publication으로 다시 묶는다.

이전 derived cell은 current reported ordinal에 연결한 row·metric·later-input fiscal key로
정확한 위치를 복원한다. 이전 206개 derived cell을 원래 순서로 carry-forward하고 새 Q3
dependency closure 14개만 기존 규칙으로 계산한다. table/view 범위의 cell identity,
multiplicity, lineage나 ordering을 증명하지 못하면 full fallback한다.

compact metadata guard의 표당 200,000건·64MiB와 estimated output batch 8MiB는 전체
프로세스 RSS 상한이 아니다. 구현은 O(N) scalar/current routing과 선택된 Polars collect,
Arrow/native buffer 및 최종 full publication write를 함께 사용한다. actual 측정은 별도의
4GiB runtime guard 아래 수행했다. unchanged cell도 새 immutable destination에 물리적으로
다시 쓰며 reported builder, canonical mapping, 기존 입력 로드와 T1~T4 증명 비용은 남는다.

파일 hash, count, JSON-field schema, ownership, journal과 atomic publication 검사는 그대로다.
부분 staging이나 capability 오류는 새 output에 섞지 않는다. `QUARTER_CELL_DELTA` 이벤트는
FAST 활성화, scanned/compared/reused/regenerated reported cell과 reused/recomputed/removed
derived cell 수를 0값까지 기록한다.

## 실제 측정과 동등성

accepted historical R6 baseline은 다시 실행하지 않았다. 같은 cached front와 승인된
migration proof를 사용한 AAPL 22→23 candidate-r6 한 회를 비교했다.

| 항목 | 기존 R6 | candidate-r6 | 변화 |
|---|---:|---:|---:|
| quarter publisher | 34.0199초 | 11.2039초 | -67.07% |
| 공통 앞단·준비·build·query 합계 | 92.1615초 | 71.0749초 | -22.88% |
| 20ms 관측 RSS 최대 | 2,092,429,312바이트 | 2,096,906,240바이트 | +0.214% |

RSS는 개선되지 않았으며 20ms 표본은 순간 최대값을 놓칠 수 있다. 전체 시간에는 실제
준비 0.182025초와 공유 cached front 1.539908초를 각각 한 번 포함했다. 단일 historical
pair이고 source가 다르므로 다른 기업이나 반복 append 성능을 주장하지 않는다.

FAST는 1회 활성화됐고 current reported cell 20,676개를 스캔했다. reported cell 19,794개를
재사용하고 882개를 재생성했으며, 기존 derived 206개를 재사용하고 새 derived 14개를
계산했다. 제거된 derived cell은 0개다. 결과는 31개 파일, 한쪽당 31,230개 record이며
accepted full reference와 값·타입·schema·ID·순서·기간·단위·원본 provenance 및 T1~T4가
같았다. 재사용 출처를 나타내는 `prior_candidate_publication` 절대 경로만 명시적으로
정규화했다. 최종 기계 보고서는
`work/quarter_cell_delta_20261025/candidate-r6/final_report.json`
(SHA-256 `e05484b5a3ae8d8b128197f9a50c40125b937d9c9671f0722cb6625649e37961`)이다.

## 후보 이력과 재현

앞선 후보는 채택하지 않았다. R2와 R3의 generic full nested comparison은 proof와
transcode 비용이 재사용 이득보다 컸다. R4는 table/view 범위가 아닌 global cell ID로
인덱싱해 합법적인 중복 ID를 false fallback했다. R5는 이전 derived 206개를 carry-forward하지
않아 record 412개가 빠졌다. 이 실패 증거는 보존하며 최종 성능이나 정확성 근거로 쓰지
않는다. candidate-r6는 dependency-proven native path와 derived carry/order 수리를 포함한
최종 수락 후보다.

실행에는 현재 전체 intake, 비어 있는 output, 이전 publication과 승인된 migration/reuse
evidence가 필요하다. 기본 호출 및 fallback 계약은
[History 증분 append v1](history-incremental-append-20261024.md)에 있다.

```bash
python -m sec_xbrl.history build \
  --intake-manifest CURRENT_INTAKE.json \
  --output-root NEW_OUTPUT_ROOT \
  --previous-history PREVIOUS_HISTORY_ROOT \
  --previous-reuse-evidence APPROVED_REUSE_EVIDENCE.json
```

두 opt-in 인자가 없거나 content pins, source/rule identity, strict suffix, typed prefix,
graph isolation 또는 fixed-policy FAST 조건이 맞지 않으면 기존 full 경로를 사용한다.
