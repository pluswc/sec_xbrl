# Selected FACT 대상 패널 탐색 최적화 (2026-10-24)

## 범위와 결정

이 마일스톤은 이미 전체 검증을 마친 T3 exploration graph 안에서 패널 결과에 도달할 수
없는 branch를 탐색 queue에 넣지 않는다. T4-B가 선택한 정확한
`(source_filing_id, selected_source_fact_id)` FACT만 target으로 삼는다. 회계 선택, root
선택, 공개 `traverse()` 의미, role/targetRole 해석, 패널 ID·순서·lineage, fiscal/History
작성은 바꾸지 않는다.

`ExplorationGraphReader`는 selected-FACT 전용 private iterator를 제공한다. 첫 호출에서만
현재 attested publication의 incoming adjacency를 만들고 target들의 reverse ancestor
closure를 계산한다. 기존 breadth-first, edge-ID 정렬, per-path cycle 검사를 그대로 쓰되
closure 밖 node로 향하는 edge는 enqueue하지 않는다. target FACT에서 끝나는 path만
`_plain_copy`하여 panel builder에 넘긴다. publication object가 바뀌면 outgoing·incoming
cache를 함께 무효화한다.

## 정확성 근거

모든 root→target simple path의 각 node는 해당 target에 도달할 수 있으므로 reverse
ancestor 집합에 속한다. 따라서 closure 밖 branch 제거는 selected FACT path를 없앨 수
없다. cycle이 있는 graph에서는 현재 path와 충돌하는 경로 때문에 실제로는 target에 갈 수
없는 prefix가 보수적으로 남을 수 있지만 결과 누락은 생기지 않는다.

root 순서와 각 node의 edge-ID 정렬 순서를 유지한다. target에 도달할 수 없는 queue entry는
나중에 target entry를 만들 수도 없으므로 이를 제거해도 남은 target path의 상대 BFS 순서는
같다. global visited, 고정 depth 제한, edge/node 병합을 사용하지 않는다. parallel role edge,
`role_uri`, `arcrole`, `target_role_uri`, edge ID와 complete path node/edge lineage는 원본 객체
단위로 유지한다. 반환 시에만 defensive copy하여 reader가 보유한 attested mapping은 외부
수정으로부터 격리한다.

public `traverse()`는 이전과 같이 모든 simple outbound path를 반환한다. invalid root 오류,
unavailable row, graph에 없는 total/orphan root 오류, total과 함께 있어 root가 아닌 missing
dimension selection의 기존 no-output 동작도 유지한다. 동일 fact ID가 다른 filing에 있어도
두 필드 key로 구분한다.

Layer2 계약은 같은 `(source_filing_id, source_fact_id)`를 가진 서로 다른 FACT node ID를
허용한다. root 해석은 기존처럼 node 순서의 마지막 mapping을 사용한다. target 해석은 그
key에 속한 모든 FACT node ID를 포함한다. 고유 key에는 추가 tuple을 만들지 않고 실제 중복
key만 작은 secondary index에 보관한다.

## Attestation 및 물리 읽기 경계

`Layer2PublicationReader.load()`는 여전히 전체 operational Parquet을 읽고 모든 row 계약,
manifest count, node/edge endpoint를 검증한 뒤에만 reader attestation을 부여한다. target과
무관한 branch의 endpoint를 손상한 실제 Parquet도 load 단계에서 거부하는 focused test를
포함했다.

따라서 이번 개선은 **전체 load/검증을 마친 graph 내부의 enqueue와 defensive copy 범위**를
줄인다. 파일 I/O와 full resident graph 크기는 그대로다. 물리 selective read에는 별도
publication-time index/partition, hash/count와 scoped validation proof, 새 reader contract가
필요하므로 이번 범위에서 제외했다.

## 고정 입력 관측

입력은 `cop_fy2025_revenue_component_v2.json`, SHA-256
`2703f0c3478a5ee9e686aaf218cffea4c0b1d0f16e04d953fc69ab871c9922b8`이다.
이는 완료 COP의 FY2025 `LATEST_REPORTED` Revenue에서 파생한 bounded internally-attested
component이며 전체 publication/company 재검증은 아니다.

상세 계측 한 번에서 다음 변화가 확인됐다.

| 항목 | 기준 | 후보 |
|---|---:|---:|
| graph nodes / edges | 120 / 277 | 120 / 277 |
| selected FACT targets | 32 | 32 |
| 방문 path states | 1,700 | 662 |
| plain-copied/emitted paths | 1,700 | 520 |
| panel definitions/bindings/values | 520/520/520 | 520/520/520 |
| traversal plain-copy 시간 | 약 0.0646초 | 약 0.0204초 |
| panel build 시간 | 약 0.1090초 | 약 0.0739초 |

상세 monkeypatch 시간은 inclusive 진단값이므로 전체 시간과 더하지 않는다.

## 397 대비 계측 없는 전체 비교

accepted `3972358c`를 기준으로 동일 fixture의 panel build→fiscal spill→Parquet
stage/finalize→reload→성공 close workload를 fresh subprocess에서 3회 교차 실행했다. 각
실행은 30초/1 GiB watchdog을 적용했고 cold graph index 및 첫 reverse index 비용을
포함했다. 경과 시간은 import와 fixture publication construction 이후부터 측정했으며 process
peak RSS에는 subprocess 시작 비용이 포함된다.

| 항목 | 397 median | 후보 median | 변화 |
|---|---:|---:|---:|
| 전체 경과 | 0.4533초 | 0.4200초 | -7.3% |
| process peak RSS | 232,764 KiB | 232,092 KiB | -0.3% |

부모 watchdog 최대 관측은 기준 243,936 KiB, 후보 250,240 KiB였다. 이 작은 component에서
RSS 차이는 실질적 개선으로 해석하지 않는다. 동시 호스트 작업의 영향도 있으므로 전체
회사에 외삽하지 않는다.

두 arm의 complete decoded fingerprint는
`0b0497946befa8611980982834080dafccd3fc5be966a8d2058083e936980df0`로 같았다.
columns/rows/cells count, JSON fields, artifact bytes와 각 Parquet SHA-256도 byte 단위로
동일했다. 최종 Parquet 합계는 122,490 bytes다.

## 검증과 한계

관련 graph/panel focused unit가 통과했다. diamond, parallel role/targetRole, multiple roots,
cycle, depth 3 경로, empty/no-reachable targets, unavailable, missing root/dimension orphan,
filing-qualified identical fact ID, 동일 filing/fact key의 복수 FACT node, defensive copy, cache
invalidation, target 밖 corrupt endpoint 거부와 public root 입력 진단 보존을 포함한다.

이번 결과는 bounded COP component의 논리 탐색 비용 개선이다. 전체 T3 파일 읽기나 resident
graph memory를 줄였다는 주장은 하지 않는다. screening/detail view 분리, graph 저장 형식,
회계 evidence 의미도 변경하지 않았다.

이 후보는 로컬 소스와 증거만 동결한 상태다. 이미 시작한 LIN 397 실행에는 적용하거나
재시작하지 않았으며, 실제 50개사 처리 완료 또는 운영 적용을 뜻하지 않는다. 독립 검증과
별도의 향후 미시작 generation 바인딩 전에는 배포 후보일 뿐이다.

## 전달 및 수락 상태

2026-10-24 기준 production source `200d230b09e9b98fa814b913d47102140307dd50`를
로컬 수락했다. 독립 검증은 중복 FACT 경계 보정의 직접 영향 4개 delta case를 통과했고,
앞선 traversal/order/lineage 증거를 함께 확인했다. 최초 후보 `7e6a241d`는 같은
`(source_filing_id, source_fact_id)`를 가진 복수 FACT node 중 하나를 누락하는 edge case로
실패했으며, `200d230b`는 중복 key의 모든 node ID를 target에 포함해 이를 고쳤다.

최종 bounded 비교는 397 대비 경과 시간 -7.33%였다. median RSS 차이는 -0.29%이고 부모
watchdog 최대값은 후보가 더 높았으므로 RSS 개선으로 수락하지 않았다. 이 수락은 source와
bounded 결과의 로컬 수락이며 main merge 또는 배포가 아니다.

실제 DUK는 5a source로, LIN은 397 source로 generation을 마쳤다. 둘을 중단하거나 이 후보로
재처리하지 않았다. source-bound final audit 네 건이 남아 있으며, selected-FACT target scope는
향후 아직 시작하지 않은 generation에만 적용할 수 있다.

독립 검증 보고서는 working evidence
`panel_target_scope_independent_r2/report.json`에 있으며 SHA-256은
`34b87a91cafc346858cf8bb4e70ece6665a7545d53f112ca4b27e40e9a2eb191`이다.
