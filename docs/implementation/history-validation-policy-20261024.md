# History publication 일상 검증 정책 — 2026-10-24

## 상태와 목적

이 문서는 승인된 구현 범위와 2026-10-24 로컬 인수 상태를 기록한다. 최종 제품
소스는 `e4a9f5426454fe9cb2014452529a6eb1930efc49`다. 독립 검증 r2는 PASS였고
보고서 SHA-256은
`5b2f2cb99a98646453286d240cdb8f8e4a4f1139082fd8783bf431ee5670a0be`다.
Lead는 이 범위를 로컬 수락했다. 원격 push, PR, CI, `main` 병합과 실제 회사 runtime
채택은 수행하지 않았다.

목표는 history publication의 일상 저장 검증에서 모든 nested JSON을 매번 다시
디코드하는 비용을 줄이는 것이다. 재무 계산, 공시 선택, 기간 분류, T1~T4 생산,
Raw guard, 기존 파일 내용과 manifest 형식은 변경하지 않는다. 과거 50개 회사의
완료 검증이나 독립 109단계 의미 감사를 다시 실행해 receipt를 만들지 않는다.

`HistoryPublicationReader.verify_all()`은 모든 선언 파일의 SHA-256, schema/count와
모든 JSON 값을 확인하는 **상세 저장 검증**이다. 이것은 별도의 109단계 의미 감사와
같지 않다. 새 정책은 독립 의미 감사를 호출하거나 완료로 표시하지 않는다.

## 정책 seam과 실제 기본 경로

`src/sec_xbrl/history_validation.py`의 `validate_publication()`이 검증 수준을 한 곳에서
결정한다. `HistoryPublicationReader.validate()`가 이를 노출한다.

- `build_history`의 기존 reported/panels 재사용 확인
- 새 reported staging publication 확인
- `publish_quarter_history`의 입력 및 새 quarter staging 확인
- collection build attestation 생성과 기존 attestation 재사용 확인

위 일상 경로의 기본은 `routine`이다. CLI의 `--validation-mode detailed`와 recovery는
기존 `verify_all()` 상세 경로를 유지한다. Recovery의 capability·ownership·복사·완료
검사는 routine으로 낮추지 않는다.

## ROUTINE_INITIAL과 ROUTINE_CHANGED

신뢰할 외부 state가 없는 새 publication도 `ROUTINE_INITIAL`로 검사한다. 이 상태는
full storage 또는 semantic validation으로 표시하지 않는다.

일상 검사는 다음을 수행한다.

1. manifest의 전체 상대 경로와 실제 regular-file inventory를 대조하고 symlink 및
   비정상 entry를 거부한다.
2. 새 파일이나 metadata identity가 바뀐 파일은 manifest의 SHA-256과 실제 bytes를
   대조한다. `(device, inode, size, mtime_ns, ctime_ns)`는 변경 신호이며 내용 불변의
   강한 증명이 아니다.
3. 새 root의 파일이 이전 state와 같은 declared SHA/count/JSON fields를 가지더라도,
   실제 전체 SHA가 같아야 이전 schema·scalar·참조 증거를 재사용한다.
4. 새·변경 table closure의 모든 파일에서 schema/count를 확인한다. JSON과 native
   scalar는 앞·뒤 합계 최대 8행만 한 번의 bounded scan으로 표본 해독한다.
5. 같은 closure의 row/column/cell ID는 전체 좁은 scalar column을 투영하여 null과
   중복을 검사한다. 모든 cell row/column FK는 native anti-join으로 확인한다.

새 분기나 manifest 입력 변화 자체는 오류가 아니다. 추가·변경 file의 table closure만
검사한다. table 제거는 현재 inventory 전체를 routine 검사한다. 이 작업은 producer의
row 단위 증분 계산이 아니며, 새 run에서 T1~T4와 panel을 만드는 비용은 남는다.

## ROUTINE_UNCHANGED와 외부 state

외부 state는 publication 밖의 caller 지정 company/scope 디렉터리에 원자적으로 쓴다.
State는 policy version, 실제 `sec_xbrl` Python source bytes 전체와 활성 rule identity,
scope, 파일별 declared SHA/count/JSON fields/schema fingerprint 및 마지막 결과를 담는다.
실패하면 기존 정상 state를 보존한다.

파일 증거 재사용은 상대 경로와 SHA/count/JSON fields뿐 아니라 table key, table scope와
role에도 묶인다. 첫 후보 `5db2ec…`은 두 table의 동일한 rows 파일 선언을 서로 바꾸면
이를 무변경으로 잘못 분류하는 결함이 있어 독립 FAIL했다. 최종 `e4a9f5…`는 binding이
바뀐 파일을 변경으로 취급하고 이전·현재 양쪽 table closure를 검사한다. 이 때문에
bytes가 같아도 rows/cells 연결이 끊기면 실패하며 이전 정상 state를 보존한다.

동일 실제 파일 identity와 선언이 유지되면 `ROUTINE_UNCHANGED`는 path/inventory/stat을
확인하고 payload hash·JSON decode를 반복하지 않는다. 이 경로도 stat만으로 암호학적
무결성을 새로 증명했다고 주장하지 않는다. 기존 routine 증거와 immutable publication
운영 계약을 재사용한 결과다.

## 상세 전환과 실패 보존

다음은 기존 상세 저장 검증으로 전환한다.

- state JSON 손상 또는 schema 오류
- validation policy, 실제 관련 source bytes, 활성 rule identity 변경
- 명시적 `detailed` mode

State/code/rule drift는 상세 검증 성공 뒤 새 state로 갱신할 수 있다. 반면 extra file,
unsafe path, SHA 불일치, count/schema/scalar 오류, null·중복 ID, dangling FK처럼 이미
확인된 구조·참조 위반은 상세 검증을 진단 목적으로 실행해도 실패를 유지한다. 기존
`verify_all()`이 extra file이나 FK를 검사하지 않는다는 이유로 이상을 통과시키지 않는다.

## 기본 실행과 상세 opt-in

일상 build의 기본값은 `routine`이다. State는 run마다 사라지는 임시 publication 안이
아니라 회사·scope에 대응하는 안정된 외부 경로를 지정한다.

```bash
python -m sec_xbrl.history build \
  --intake-manifest INPUT/history_intake.json \
  --output-root OUTPUT/history \
  --validation-state-root STATE_ROOT/COMPANY/history-validation
```

상세 저장 검증이 필요한 명시적 실행은 같은 명령에 `--validation-mode detailed`를
추가한다. Quarter publisher도 `--validation-state-root`와 같은 mode를 지원한다.
Collection build는 `OUTPUT_ROOT/COMPANY/history-validation`을 안정 state 위치로 사용한다.
`recover-reported`는 이 option과 무관하게 strict recovery 검증을 유지한다.

## 수락 검사와 측정 계약

최종 focused 검사는 다음을 확인한다.

- 최초 routine, 같은 root 무변경, 같은 SHA의 새 root, 한 table 변경
- 전체 ID/FK 검사로 중간 cell의 dangling reference 검출
- extra file과 dangling FK는 strict callback이 통과해도 실패하며 이전 state 보존
- 손상 state와 code drift의 상세 fallback
- collection attestation이 routine 결과의 declared digest를 사용해 직후 두 번째 full hash를 하지 않음
- table/role/scope binding 교환 시 이전·현재 closure를 검사하고 dangling FK와 state 보존

최종 후보의 관련 정책 검사는 8건 PASS였다. 기존 50개 회사의 완료 검증과 독립
109단계 의미 감사 재실행은 0건이며, 기존 21 UI, 저장 기록과 publication 파일은
변경하지 않았다.

측정은 하나의 작은 nested-provenance fixture에서 fresh serial child 3회로 수행했다.
기존 상세 저장 검증, 최초 routine, 무변경 routine, 한 table 변경 routine, code-change
fallback만 비교했다. 과거 109단계 감사 시간이나 완료 회사 실행 시간과 직접 비교하지
않는다.

실행된 fixture는 3 table, table당 8 columns·24 rows·384 cells다. 각 cell은 12개
nested provenance 후보를 가진다. 3회 중앙값은 다음과 같다.

| 경로 | 중앙 시간 | detailed 대비 | 관측 RSS 중앙값 | RSS 변화 | 확인 범위 |
| --- | ---: | ---: | ---: | ---: | --- |
| 기존 detailed | 83.02 ms | 기준 | 87.01 MiB | 기준 | 9파일, 1,248행 전체 decode |
| routine initial | 156.34 ms | +88.31% | 108.99 MiB | +25.26% | 9파일, 72행 JSON 표본 + 전체 ID/FK |
| routine unchanged | 46.71 ms | -43.73% | 54.58 MiB | -37.27% | payload hash/decode 0건 |
| routine changed table | 91.38 ms | +10.07% | 102.26 MiB | +17.53% | 3파일 closure, 24행·JSON 16값 |
| code-change fallback | 90.55 ms | +9.07% | 87.07 MiB | +0.07% | detailed 전체 |

교정 측정은 부모 프로세스에서 동일 fixture와 arm별 격리 state를 준비한 뒤, 각 fresh
child가 `verify_all()` 또는 `validate()` 호출만 수행하게 했다. 부모는 child의
`/proc/<pid>/status` RSS를 5 ms 간격으로 관측했고, 표의 RAM은 arm별 관측 최대값의
3회 중앙값이다. 5 ms보다 짧은 순간 peak를 놓칠 수 있으므로 kernel이 보장한 정확한
peak가 아니다. Child `ru_maxrss`가 모두 147,352 KiB였던 값은 fork 부모의 high-water
mark 영향이므로 “모든 경로의 RAM이 같다”는 근거에서 철회했다.

추적된 `tools/profile_history_validation.py`는 child 안에서 fixture 생성과 state seed까지
수행하므로 위 교정 결과와 같은 측정 경계가 아니다. 같은 조건을 재현하려면 부모에서
fixture를 한 번 만들고 각 arm/회차의 publication과 state를 미리 준비한 뒤, fresh child에는
검증 경로만 실행시키고 외부에서 5 ms RSS를 관측해야 한다.

확인된 이점은 무변경 state 재사용뿐이다. 최초 자료와 변경 table은 이 작은 fixture에서
시간과 관측 RSS가 모두 증가해 개선이 입증되지 않았다. 이 결과를 실제 회사 전체 시간이나
109단계 감사에 외삽하지 않는다. 계산 생산자의 row 단위 증분도 이 범위에 포함되지 않는다.

교정 원시 보고서는 선택적 작업 증거이며 checkout 이해의 전제는 아니다.

- `work/history_validation_measurement_corrected_20261024/corrected_profile.json`, SHA-256
  `4f5bda332f3418f48c4f6652ac187d6f4ecf2352140b9af131fd3fd6d596c041`
- `work/history_validation_measurement_corrected_20261024/memory_summary.json`, SHA-256
  `c1d3e52009e8b9320e467500b0edf8efce03f6d70c13012321ad93e0ddb7f306`

## 남은 범위

이 정책은 기존 history 파일을 다시 쓰거나 row 단위 계산을 증분화하지 않는다. 새 filing의
canonical mapping, selection view, YTD/Q4 파생과 성장률 영향 범위를 추적하는 producer
증분 설계는 별도 마일스톤이다. 완성된 50개 회사의 의미 검증과 21개 UI·저장 기록은
이 변경의 입력이나 migration 대상으로 사용하지 않는다.

이 기능은 로컬 source 및 bounded fixture 범위에서 수락됐다. 실제 회사 전체 시간 개선,
운영 runtime 채택, 원격 전달과 `main` 병합은 별도 결정이며 현재 완료 상태가 아니다.
