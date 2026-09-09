# 계획 등록부 — 단일 진입점

기준일: **2026-09-09**. 이 등록부는 목적·계약·현 상태·증거의 위치를 연결한다.
규범적 계획은 Git 추적 문서이며, 임시 계획 파일이나 특정 도구를 읽거나 설치할
필요가 없다. 이번 변경은 문서 설계만 승인되었고 U4 기능 구현은 포함하지 않는다.

## 읽기 순서와 문서 소유권

| 문서 | 역할 |
| --- | --- |
| [M 구현 로드맵](../roadmap.md) | Raw/Analytical/Derived/Display 및 Layer 1–3 기반 구축 순서. 현재 완료 목록과 구분 |
| [투자자 U1–U5 로드맵](investor-analysis-roadmap.md) | 사용자 목표, 인수 기준, 현 상태, 남은 작업의 정식 계획 |
| [공통 전달·계획 관리](../implementation/delivery-workflow.md) | 권한·단일 작성자·독립 검증·동결·상태 기록 규칙 |
| [분석 데이터 모델](../architecture/analytical-data-model.md) | 데이터 평면과 소비자 경계 |
| [투자자 API 계약](../implementation/investor-analysis-interface.md) | 이미 존재하는 조회·준비·등록·갱신 계약 |
| [회사 관리](../implementation/company-report-administration.md), [공시 검토](../implementation/disclosure-review.md) | 회사별 설정과 정확한 출처의 검토 결정·재발행 |
| [U3 v1](../implementation/u3-important-items-plan.md), [후속 v2 전달](../implementation/u3-followup-delivery.md), [Axis 전달](../implementation/u3-axis-timeseries-delivery.md) | 승인 정책, 구현·검증 계약과 한계. 로드맵이 수치를 재승인하지 않음 |
| [U3 완료·우선순위](../implementation/u3-closeout-and-followup-priority.md) | 완료 결정과 날짜가 있는 정정 기록 |
| [U4 계속 갱신 제안](../implementation/u4-continuous-refresh-plan.md) | 기존 기능/격차 대조와 후속 실행 수락안. 구현 승인 아님 |
| [기간 규칙](../implementation/period-rules.md), [Layer 2 연결](../implementation/layer2-longitudinal.md), [공시 발견 계약](../implementation/accession-contract.md) | 표시 계획으로 바꿀 수 없는 의미·입력 경계 |

충돌 시 적용되는 사용자 결정과 승인 범위를 먼저 확인하고, 해당 평면의 계약을
따른다. 제안 로드맵은 승인된 회계·검토 정책을 덮어쓰지 않는다. 현재 상태는
아래처럼 별도로 기록하며, 오래된 문서의 “미구현/검증 대기” 문구는 해당 시점의
기록이다. 그 문구를 지우는 대신 후속 결정과 연결한다.

## 상태 등록 — 상태를 서로 대신 쓰지 않는다

| 단계 | 제안 | 승인 | 구현 | 독립 검증 | 로컬 인수 | main 병합 |
| --- | --- | --- | --- | --- | --- | --- |
| U1 핵심 요약 | 기존 제안에서 납품 | 기존 제한 범위 | `9eb37d4`에 존재 | 해당 후보 PASS | 완료 | PR #62, `7f8cc523` |
| U2 단계별 탐색 | 기존 제안에서 납품 | 기존 제한 범위 | `9eb37d4`에 존재 | 해당 후보 PASS | 완료 | PR #62, `7f8cc523` |
| U3 중요도·구조·Axis 시계열 | 승인 범위까지 확장·납품 | 명시적 U3 범위 | `3098be6` | 664 passed / 16 skipped, Ruff, 실제 6사 PASS | 2026-09-09 COMPLETE | **미병합; main에 포함되지 않음** |
| U4 계속 갱신 | **복구된 기존 제안** | 이번에는 문서 설계만; 기능 승인은 별도 범위 확인 필요 | 보조 API 존재; U4 전체 완료 아님 | 기존 부분 경로 증거만; U4 전체 PASS 없음 | 완료 아님 | U4 완료로 표시하지 않음 |
| U5 보관·공유 | **복구된 기존 제안** | 상세 구현 승인은 후속 | CSV/HTML 기반 존재; 선택 상태 보존·Excel 납품 완료 아님 | U5 전체 PASS 없음 | 완료 아님 | U5 완료로 표시하지 않음 |

정확한 식별:

- U1/U2 검증 후보: `9eb37d4715640ef7b8255d806b5ffc1c030653dd`.
  PR #62 merge: `7f8cc5232d0df3d4c184de55827111e599b94dbd`.
- U3 인수: `3098be6db7622f2ec444a9979732b7dfaa685641`.
  문서 closeout: `32212caba5daf8273663d70ba3075db5d1d56fc7`.
  문서 커밋은 제품 테스트 결과의 대상 SHA를 바꾸지 않는다.
- 이번 계획 설계의 기준 부모는 위 `32212ca`다. 단일 작성자 로컬 문서 커밋 후
  별도 읽기 전용 검증을 받는다. 독립 검증·인수·병합을 미리 완료로 표시하지 않는다.

미래 수락 조건의 작성은 사용자 승인이나 일정 약속이 아니다. 소스 함수나
작업 세션/브랜치의 존재도 전체 기능 승인·완료·배포를 증명하지 않는다.

## 증거와 재현 — 임시 디렉터리에 의존하지 않는 인계

필수 계약과 검증 절차는 위 추적 문서 및 U4 계획의 입력/검증 절에 있다.
실행자는 승인된 범위에서 별도 입력·출력 위치를 제공한다. 대용량 공시 자료나
과거 실행 보고서가 없는 checkout에서도 계획을 이해할 수 있어야 한다.

선택적 보존 증거 locator(원래 프로젝트 루트 기준; 현재 계획의 실행 의존성 아님):

- `work/consumer_focused_analysis_20260908/verification.md`: U1/U2 후보 독립
  526 passed / 9 skipped, PR #62 병합 및 병합 후 관련 33건 기록.
- `work/consumer_focused_analysis_20260908/online_pipeline_verification.md`:
  AAPL 한 공시의 실제 SEC→새 Layer 1→분석→조회 증거. 제한은 U4 계획에 복사했다.
- `work/u3_axis_timeseries_complete/LEAD_ACCEPTANCE.md`,
  `independent/VERIFICATION.md`, `FREEZE.json`, `html/index.html`
  (뒤 세 경로도 같은 `work/u3_axis_timeseries_complete/` 아래): U3 최종 증거.
  독립 6사/84 Axis/10,824 화면 셀; 합성·캐시·live 구분과 유실 임시 목록의 한계 유지.

이 파일들을 과거 상태 그대로 보존한다. 검증 수치는 해당 SHA의 과거 결과이고,
이번 문서 변경에서 pytest/browser를 실행했다는 뜻이 아니다.

## 역사 자료의 출처 — 선택적 정보

복구에 참고한 원본은 `.omx/plans/investor-focused-progressive-analysis-20260907.md`
(2026-09-07 제안)이다. 일반 파일로 읽었으며 스킬·명령·워크플로로 실행하지 않았다.
원래 위치의 바이트를 이동·편집하지 않고 보존한다.
SHA-256: `7e88f7c50e7d9cbacb4994e58bd8542c837cb17d98fe1fa2da4d0e57d65a8911`.

이 provenance는 과거 기록의 식별 정보일 뿐 규범적 지시가 아니다. 원본을 다시
읽을 필요 없이 이 등록부, U 로드맵과 실행 계약만으로 업무를 인계한다.
`.omx/`, `.codex/`, `work/`에서 만든 후속 계획도 같은 원칙을 따른다.
