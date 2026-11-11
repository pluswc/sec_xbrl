# 저장 공간 정리 인수 기록

2026-11-10 사용자가 승인한 정리 범위는 MRK 감사용 임시 SQLite 한 개와
공시 압축 해제 디렉터리 1,109개다. 보존 자료를 확인한 뒤 격리와 삭제를
완료했다. MRK 대상은
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/later45_actual_l4_runtime_r12_full_recovery_coverage/runs/actual-mrk-reported-reuse-r12-full-run/semantic_index.sqlite`다.
압축 해제 디렉터리의 정확한 목록은
`work/storage-retention-audit-20261110/quarantine.json`에 기록했다.

| 실제 측정 | 바이트 |
| --- | ---: |
| 삭제 파일에 할당된 블록 | 70,800,650,240 |
| 정리 전 파일시스템 가용 공간 | 114,135,318,528 |
| 정리 후 파일시스템 가용 공간 | 184,949,923,840 |
| 파일시스템 가용 공간 증가 | 70,814,605,312 |

보존한 ZIP 1,109개의 SHA-256과 Layer 1 스냅샷 존재 확인이 모두
통과했다. NFLX 공시 `0001065280-26-000291`은 보존 ZIP으로 복원했을 때
매니페스트와 Parquet 8개의 바이트가 모두 일치했다. 재현 결과는
`work/storage-retention-audit-20261110/nflx-layer1-restore.json`에 있다.

감사 완료 보고서, 카탈로그, 저장 결과와 값·근거 응답의 전후 해시가
일치했다. 사용자 저널 SHA-256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로
보존됐다. 정리 완료와 보호 대상의 해시는
`work/storage-retention-audit-20261110/reclaim.json`에 있다.
JNJ 감사 DB 약 90.37GB, MRK spill 약 41.05GB와 JNJ partial 약
11.27GB는 이번 삭제 승인 범위에서 제외되어 보존했다.

2026-11-11 Git 준비에서는 루트 `/work/`와 `/reports/`를 제외 규칙에
추가했다. 두 디렉터리에는 추적 파일이 없었다. 실제로 관찰한 임시
감사 DB와 생성 보고서의 대량 검색을 줄이기 위한 규칙이다.
이번 문서·제외 규칙의 PR·CI·main 반영은 별도 대기다.
