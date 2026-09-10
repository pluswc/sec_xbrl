# U4 로컬 검증과 다음 단계

기준일 2026-09-09. 상태: **LOCAL_CODE_AND_CACHE_PASS / FULL U4 NOT COMPLETE**.
검증한 제품 코드 SHA는 `e2b68935a2f1eb9e340b3eb8c8e891c878ce8498`이다.
이 문서 커밋은 제품 테스트 대상이 아니며 소스·테스트·원격 상태를 바꾸지 않는다.

**2026-09-10 후속 정정:** 이 문서의 local-only 결론과 아래 gap은 2026-09-09
시점 기록이다. 후속 사용자 승인, 제품 SHA `3236778e57872b8ea41e421534e4a9d9ea0d58ff`,
실제 신규 2공시→최종 14공시 증거, quality materialization 및 독립 검증으로 bounded
U4는 로컬 인수됐다. 최신 범위는 [U4 완료·인수](u4-completion-and-acceptance.md)를
따른다. 과거 두 FAIL과 이 문서의 원래 판정은 삭제하지 않는다.

## 독립 검증 결과

별도 읽기 전용 검증자는 동결된 코드 SHA에서 다음 결과를 확인했다.

- 전체 pytest: **671 passed / 37 skipped**, Ruff: **PASS**.
- 기존 6사 cached hierarchy/Axis 회귀: **21 passed**.
- cached NFLX: **12 filings / 913 source tables**, 모든 filing은
  `REUSED_SOURCE_RUN`; prepared API와 HTML 모두 **16 Axes / 1,356 cells**.
- 원래 U3 동결본: **1,483 hashes** 일치.
- NFLX final companion의 50 Analytical dataset checksum, 48 base file과 209
  hierarchy file 보존, 210 final file을 확인했다. consumer query에서는 producer와
  socket을 차단했고 HTML 검사는 HTTP(S) 요청 0건이었다.

Source-derived NFLX 결과는 앞선 구현 SHA
`99a0bfd74e28f9d49dbf24139a96edada4b32e8f`에서 생성됐다. 최종 코드 SHA의
변경은 quality 판단을 exact settings snapshot에서 읽도록 고친 것이며 cached
입력의 effective decision은 비어 있었다. 독립 검증자는 최종 SHA에서 sealed
publication을 다시 열어 checksum/API를 검증하고 최종 SHA가 기록된 동일 renderer
HTML을 검사했다. 최종 SHA에서 SEC 수집·materialization을 새로 실행했다고
기록하지 않는다.

## 두 번의 실패와 수정

첫 후보 `2b1ba3e4328695dcf5292de82cbcb4bd79fdd5c2`는 기존
`admin/runs/*/decisions.csv`를 private admin으로 전달하지 않아 과거 발행 decision의
삭제·수정을 refresh 안에서 놓칠 수 있었다. 다음 후보
`99a0bfd74e28f9d49dbf24139a96edada4b32e8f`는 이력 보존을 추가했지만 live
preflight와 settings capture 사이에 BLOCK이 추가되면 stale한 빈 판단으로 발행할
race가 남았다. 최종 SHA는 effective quality와 append-only 검사를 byte-exact
private snapshot과 copied/hash-bound histories에서 다시 계산한다. 과거 FAIL
보고서와 artifact는 지우거나 PASS로 바꾸지 않는다.

## 현재 구현 경계

현재 로컬 코드는 기존 discovery/history/review/consumer/U3 companion/renderer를
명시적으로 연결하고 실패 시 이전 registration과 pointer를 보존한다. 설정 이력,
stage provenance, exact reviewed-parent 재개, pointer-last commit과 crash recovery를
검증했다. 현재 연도의 Q1/Q2도 legacy complete-year HTML gate 없이 prepared
consumer로 전달할 수 있으며 빈 Q4를 만들지 않는다.

일반 관리자 quality `WARN`/`BLOCK`을 최종 Analytical cell에 materialize하는
overlay는 구현되지 않았다. wrapper는 그런 유효 결정이 있으면 정확한 범위와 함께
`REVIEW_REQUIRED`로 중단한다. 이는 quality overlay 완료가 아니다.

live 신규 accession의 수집→검토→같은 consumer 발행도 실행하지 않았다.
`SEC_USER_AGENT`가 없고 사용자가 정확한 대상 filing을 아직 선택하지 않았다.
후보로 조사된 NFLX `0001065280-26-000212`는 report 2026-06-30, filed
2026-07-17이며 accepted baseline에는 없지만, 이 문서에서 최신 filing이라고
확정하거나 실행 대상으로 선택하지 않는다.

## U4 완료까지 필요한 작업

1. 일반 관리자 quality overlay의 범위와 materialization 계약을 승인하고 reported
   provenance를 보존한 producer와 final consumer 검증을 추가한다.
2. 지원 filer/form, exact accession, source `as_of`, review cutoff, 이전 성공 범위,
   `SEC_USER_AGENT`를 명시한다.
3. 기존 collector로 live intake를 수행하고 live/cache/reused 단계를 분리해 기록한다.
4. 새 accession이나 stale binding을 exact source review로 처리한다. 새 경제 의미,
   Q4, share, hierarchy/Axis 식을 이전 승인에서 자동 추론하지 않는다.
5. 모든 companion과 동일 renderer가 완성된 뒤 pointer를 발행하고 이전 consumer와
   새 consumer를 독립 검증한다.

이 증거가 없으므로 U4는 로컬 코드와 cached 범위에서만 PASS이며, 로컬 인수 완료,
main 병합, live 운영 완료로 표시하지 않는다.
