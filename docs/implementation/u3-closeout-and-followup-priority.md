# U3 완료 결정과 후속 검토 우선순위

## 2026-09-09 사용자 결정

사용자는 U3를 **COMPLETE — 인수 완료**로 확정했다. 인수 대상은
`3098be6db7622f2ec444a9979732b7dfaa685641`의 로컬 구현과 동결 산출물이다.
기존 `work/u3_axis_timeseries` 작업트리와 `work/u3_axis_timeseries_complete`
산출물을 그대로 보존한다. 이 결정 기록으로 U3를 다시 열거나 범위를 넓히지 않는다.

독립 검증과 리드 인수 근거는 다음과 같다.

- 독립 전체 pytest: **664 passed / 16 skipped**, Ruff **PASS**.
- 실제 6개 회사(NVDA, AMD, MSFT, AMZN, AAPL, NFLX)의 **84개 Axis,
  10,824개 화면 셀** 검증 PASS.
- 위 결과는 인수 대상 `3098be6db7622f2ec444a9979732b7dfaa685641`에 적용된다.
  이 문서를 추가하는 별도 커밋의 테스트 실행 결과로 표시하지 않는다.

## 보존된 인수 및 검증 기록

아래는 원래 프로젝트 루트
`/home/plusbdw/user_work/projects/sec_xbrl` 아래의 로컬 산출물이다.
별도 문서 작업트리에서 재생성하거나 덮어쓰지 않는다.

| 프로젝트 루트 기준 locator | 기록 |
| --- | --- |
| `work/u3_axis_timeseries_complete/LEAD_ACCEPTANCE.md` | [리드 최종 인수](/home/plusbdw/user_work/projects/sec_xbrl/work/u3_axis_timeseries_complete/LEAD_ACCEPTANCE.md) |
| `work/u3_axis_timeseries_complete/independent/VERIFICATION.md` | [독립 검증 PASS 및 한계](/home/plusbdw/user_work/projects/sec_xbrl/work/u3_axis_timeseries_complete/independent/VERIFICATION.md) |
| `work/u3_axis_timeseries_complete/FREEZE.json` | [원본 동결 SHA·산출물 해시](/home/plusbdw/user_work/projects/sec_xbrl/work/u3_axis_timeseries_complete/FREEZE.json) |
| `work/u3_axis_timeseries_complete/html/index.html` | [인수한 최종 화면](/home/plusbdw/user_work/projects/sec_xbrl/work/u3_axis_timeseries_complete/html/index.html) |

동결 당시 작성자 보고서의 독립 검증 대기 문구는 그대로 보존하며,
후속 독립 PASS와 리드 인수 기록으로 완료 판단을 확인한다.

## Missing 표시와 실제 시계열 연결의 분리

Missing은 **0이 아니며**, 화면의 빈 셀만으로 공시 자체의 부재를 단정하지 않는다.
준비된 값의 상태와 출처를 유지하고, 공시 부재를 해결 상태로 해석하지 않는다.
세부 missing reason을 공통 UI와 Excel에서 어떻게 설명할지는 후속 표시 과제로
유보한다. 이는 U3 완료의 차단 사유나 재개 조건이 아니다.

실제 시계열 구간을 연결하는 작업은 표시 개선과 분리된 **Layer 2 근거 검토**다.
그 검토는 주요 분석을 실질적으로 막는 큰 공백에 우선순위를 둔다.
모든 기간이 완성되었다고 주장하지 않으며, 동일 이름만으로 매핑 구간을 잇거나
연결·값을 만들어 채우지 않는다. 기존의 별도 매핑 행, 기간 종류 및 원문 출처
경계를 유지한다. 이 우선순위 기록 자체가 연결 정책이나 구현을 승인하지 않는다.

## 후속 소비자와 미확정 범위

U5 Excel은 준비된 API 데이터를 소비한다. Excel에서 공시 선택, 시계열 연결,
회계 계산 정책을 새로 결정하지 않는다. 세부 missing reason 표시 역시 이후
공통 UI/Excel 관점에서 검토할 사항이며, 이번 기록에서 구현하지 않는다.

U4의 상세 범위는 지속 보존된 문서에서 확인되지 않은 상태다. 이 기록은 U4의
마일스톤 내용, 구현 순서, 커밋 일정 또는 완료 시점을 새로 정의하지 않는다.
U4·U5 또는 다른 후속 기능의 구현 승인은 이번 사용자 결정에 포함되지 않는다.

## 이번 문서 작업의 경계

사용자는 기존 Astra 상향 승인을 유지한 단일 작성자에게 결정 기록과 로컬 커밋만
승인했다. `3098be6db7622f2ec444a9979732b7dfaa685641`에서 만든 별도 작업트리
`work/u3_closeout_records`, 브랜치 `codex/u3-closeout-records`에서 이 문서 하나만
추가한다. main 및 기존 동결 작업트리를 변경하지 않고, 원격 push·PR·merge를
수행하지 않는다.

변경 검증은 정확히 한 문서만 추가되었는지, 내용과 로컬 링크가 맞는지,
`git diff --check`와 커밋 후 clean 상태로 한정한다. 문서만 바뀌므로 테스트를
재실행하지 않는다. 이 기록의 별도 독립 읽기 전용 검토는 후속으로 진행하며,
이미 완료된 U3의 독립 검증과 구분한다.
