# 공통 CAL 1.0/1.1 추출 및 EPS 구성 검증

## 승인 범위 및 구현 위임

2026-11-18 사용자가 승인한 M3 관계 추출 수정과 공통 Q4 EPS 준비 확대다.
기준은 PR111 병합 후 main `6b19854550d6ec1ae6efb1433f5cdc27aede745d`와
기존 [Q4 구성 계약 및 인수 기록](common-q4-eps-reconstruction-20261118.md)이다.
2026-11-18 총괄이 아래 공통 회계 규칙의 범위를 확정했다. 독립 검증, 실제
자료 인수, PR/CI, main 병합 여부는 별도로 기록한다.

총괄은 독립 검증·회계 결정·실제 불변 자료 준비 및 인수를 맡는다. 단일 구현자는
`codex/cal-eps-common` 격리 작업트리에서 Layer 1 관계 추출, 계산 네트워크
증거, Q4 작성자/소비 계약 연결, offline 진입점, 관련 테스트 및 계획·계약 문서를
수정한다. 커밋과 동결은 총괄의 전달 지시 후 수행한다. 운영, 네트워크, 원격 Git,
공급자 또는 에이전트 지침은 이 위임 범위 밖이다. 누적 희석 가산성과 조정의
회계 의미는 총괄의 명시적 판단으로 확정한다.

출력은 별도 parser/evidence version을 사용한다. 과거 Raw snapshot, SEC ZIP,
공시·가격 cutoff, 기존 관측과 저장은 원본 위치에서 보존한다. 원본 package와
등록 intake는 고정 SHA로 연결하며 기존 accession discovery를 사용한다.

## 수락 기준

- 두 summation-item arcrole을 실제 URI 그대로 보존한다. Arelle의 유효 관계를
  role, arcrole 및 완전한 link/arc QName별로 별도 추출하고 source 문서·위치를
  유지한다. Wildcard 별칭은 중복을 만들지 않는다.
- CAL은 parent에서 child로만 검증한다. 같은 filing, complete Context, Unit 및
  원본 decimals의 범위에 근거한다. 누락·충돌 fact, 잘못된 단위, 순환 또는 섞인
  role/arcrole에서 유효한 구성 증거가 나오지 않는다.
- 기본과 희석을 각각 검증한다. 서로 다른 공시 빈티지, 주식종류·분할·재작성,
  손실/지배 분자, if-converted 및 참여증권 조정은 원천 증거가 허용하는 범위에서만
  처리한다. 보고 EPS와 비교할 때 원 decimals 범위를 사용한다.
- 실제 등록 집합에서 원래 AMZN 단일 회사보다 적격 범위를 넓힌다. 각 회사에
  동일한 source discovery·검증을 적용하며 직접 Q4 우선, 현재 평가 정책 및
  역사 backfill 금지를 유지한다.
- 네트워크 없는 단위 검사와 등록 실자료 replay를 분리하고, 별도 읽기 전용 검증
  후 총괄이 불변 입력·소비·저장 회귀를 승인한다.

## 승인된 Source 및 회계 규칙

1. 보고 연간 10-K와 그 이전에 제출된 보고 Q3 10-Q를 원 source family로 고른다.
   실제 Context의 FY 시작, Q3 말, FY 말과 실제 calendar-day duration을 쓴다.
   이후의 비교 공시, 다른 filing의 기간 구성값, amendments, 모호한 원 공시,
   다른 등록 주식종류·분할·재작성 basis를 조용히 대체하지 않는다.
2. 기본과 희석은 해당 flavor의 보고 분자·분모·EPS를 따로 검증한다. 정확한
   공식 common numerator는 보고 분자로 사용할 수 있다. Parent net income은
   같은 전체 Context의 공시 EPS, weighted shares와 한 source table에서 연결되고
   보고 EPS 범위와 맞는 경우에 근거로 사용한다. 희석에 parent를 쓸 때는 공시
   기본 EPS와 기본 분모도 같은 source block에 연계한다. 숫자 일치나 태그 부재만으로
   common attribution을 증명할 수 없다. 같은 complete Context에서 보고된 공식
   preferred dividends/accretion, participating allocation, 희석 convertible interest
   조정이 nonzero이거나 원 decimals상 0 여부가 불확실하면 parent fallback은 보류한다.
   명시적인 `[0, 0]` 구간만 보고 조정 0 근거로 기록하며 누락을 0으로 바꾸지 않는다.
   이 공식 조정 개념은 CAL child가 없어도 source projection에 남긴다.
   기존 participating/two-class counterevidence guard의 local-name 판정은 source
   projection과 공유하므로 custom 조정도 CAL 밖에서 유실되지 않는다. 이 보존은
   custom numerator 의미를 승인하지 않는다.
   별도 기본/희석 분자 태그는 동일한 source
   numerator row 또는 동일한 complete signed CAL 구성이 뒷받침해야 한다. 정확한
   희석 분자가 없을 때는 기본 common numerator의 complete CAL parent bridge와
   정상 희석 분모·보고 희석 EPS가 동일한 귀속을 증명하는 경우에 사용한다.
3. 희석 누적 route는 FY와 9M 각각 완전한 유효 CAL share equation을 요구한다.
   공식 basic leg와 양(+)의 source-identified stock award legs를 허용한다.
   Explicit basic-only equation으로 0 증분이 확인되는 경우도 양 기간에서
   compatible scope를 확인한다. Generic incremental child는 정확한 보고 cell의
   공시 row/column label 또는 해당 filing의 EPS treasury-stock 정책으로 구분한다.
   EPS에서 보통주 warrants에 treasury-stock 방식이 적용된다는 해당 절의 공시가
   있으면 함께 허용한다. 별도 historical antidilution 표의 언급으로 판단하지 않는다.
   명시적으로 방법 적용을 부정하거나 제외된 반희석 주식만 설명하는 절은 이
   affirmative 정책 근거가 아니다. 보고 증분 point가 음수이면 원 decimals 구간이
   0을 포함하더라도 정상 희석 증거로 승인하지 않는다.
   미지의 잠재 주식, 전환, 조건부 주식과 미입증 numerator adjustment는 보류한다.
4. 양(+)의 계속영업 지배 분자 범위를 FY, 9M, Q4 및 앞선 세 constituent quarter에서
   확인한다. 계속영업 직접 보고액 또는 공식 pretax continuing − tax 관계를
   확인한다. 세후 equity-method 항목과 귀속 NCI가 있다면 보고된 signed CAL
   경로에서 같은 base set과 동등 Context로 검증한다. 기타 계산 부모와 원천 불명
   분류는 보류한다. Period-local two-class allocation을 CAL로 검산할 수 있어도
   기간 가산성은 별도 증거가 필요하다. 현재 규칙은 nonzero/uncertain allocation을
   누적 Q4로 승격하지 않는다.
5. Q4 numerator는 FY − 9M, Q4 weighted average는 기간별 실제 일수 가중으로
   복원한 뒤 나눈다. 보고 FY와 9M EPS를 각 기간 구성에 대조하고, 직접 Q4 EPS
   reference와 비교할 때 원 decimals interval 교집합을 허용한다. reference와 맞추기
   위한 방식 선택이나 구성값 보정은 하지 않는다. 호환되는 직접 Q4 EPS를 우선하고,
   직접 reference 부재는 다른 회계 조건을 검증한 route의 결측 진단으로 남긴다.
6. 기존 class/split/current binding과 source-vintage 검사를 유지한다. 희석 Q4
   이후 해당 financial anchor까지 연속 네 분기를 확인한 경우에만 빈 current TTM
   입력 역할을 채운다. 기존 입력 ID, observation, timestamps, 증거 pin과 과거
   발행 경로를 보존한다. 관측은 `historical_ready=false`이며 현재 평가의
   `backtest_eligible=false`를 유지한다.

## Offline 준비와 검증

`prepare_cal_eps_filing(snapshot, package, taxonomy_cache=...)`는 하나의 accession에서
기존 Layer 1 fact identities, values, dimensions and provenance와 replay를 대조한다.
`snapshot`은 등록 proposal의 `snapshot_id`, `manifest` pin, `table_sha256` map을
갖는다. `package`는 원 SEC ZIP의 절대경로 및 SHA256 pin이다. Arelle은 기존 offline
loader/cache로 실행하며 별도 임시 디렉터리에만 ZIP을 푼다. `cal-eps-filing-v1`은
원본 package member hash, arc locator, Arelle/관계 parser 버전, 정확한 Raw
endpoint 및 equivalent Context/expanded Unit을 보존한다. `verify_cal_eps_filing`은
필요한 동일 projection을 source부터 replay한다. 두 함수 모두 artifact 파일을
직접 쓰지 않는다.

`common-q4-eps-cal-run-v1`의 SHA256 pins는 `proposal`, 기존
`source_projection_acceptance`, `filing_catalog`, `policy`, `base_financial_bundle`,
`evaluation_decision`이다. `cal-eps-filing-catalog-v1`의 `filings` 항목은
`cik`, `accession`, `projection`을 포함한다. ROOT의 일괄
`common-q4-eps-cal-policy-v1`은 `APPROVED_GLOBAL_RULE`, 승인 시각, 룰
`common-q4-eps-effective-cal-v1`와 정확한 catalog pin을 가진다. 회사별 규칙은 없다.

기존 `examples/screening/prepare_q4_eps_reconstruction.py`의 `qualify`, `verify`,
`augment`는 확장 run을 지원한다. `governed-common-q4-eps-v2`는 원 Q4 artifact
pin을 보존하여 과거 관측을 byte-equivalent payload로 가져오고 새 관측만 append한다.
Consumer의 prepared query는 두 artifact schema를 읽는다. 원 공시·archive 재실행은
offline 준비/검증 단계에 둔다.
새 TTM 관측은 기존 구성 formula/definition version과 함께
`source_validation_rule_version=common-q4-eps-effective-cal-v1`을 직접 기록한다.
가져온 기존 관측의 payload, ID, 실제 ready time과 원 evidence pins는 바꾸지 않는다.

기본 회귀 명령은 아래와 같다.

```sh
pytest -q tests/unit/test_relationship_layer1.py tests/unit/test_layer1_ingestion.py \
  tests/unit/test_calculation11.py tests/screening/test_cal_eps.py \
  tests/screening/test_q4_eps_reconstruction.py tests/screening/test_reported_quarter_eps.py \
  tests/screening/test_liability_statement_evidence.py \
  tests/integration/test_calculation_arcrole_ingestion.py
ruff check .
git diff --check
```

## 구현자 자체 검증 및 전달 상태

기준 main에서 분리한 단일 구현 작업트리의 소스와 계약을 구현했다. 명시적인
CAL source-validation lineage, 부정된 treasury-stock 문장, 반올림 구간이 0을
넘는 음수 보고 증분, preferred 조정과 source lexical order를 포함한 네트워크
없는 검사를 같은 변경에 둔다.
동결 SHA의 독립 검증, 실제 자료의 최종 적격 artifact, 로컬·운영 인수,
원격 CI와 main 병합은 총괄의 별도 근거가 필요하며 이 자체 검사로 추정하지 않는다.

2026-11-18 최종 parent-adjustment/order 수정 후 위 기본 회귀는 **167 PASS /
1 SKIP**, Ruff와 `git diff --check`는 PASS다. CAL 단위, 원천 격리, rounding,
기존 Q4 경로, immutable append와 Arelle의 두 arcrole별 priority/prohibition을
포함한다. 실제 684 accession의 최종 projection replay와 적격 발행물은 총괄이
별도 불변 자료로 준비·판단한다.

그 수정 전 시작한 로컬 전체 pytest는 **3,385 PASS / 39 SKIP / 14 FAIL**
(333.57s)이므로 최종 소스의 전체 PASS 근거가 아니다. 알려진 cached NVDA
recovery inventory 실패 1건, sandbox의 Python HTTP socket 권한 실패 8건,
Node bridge 검사 2건, 작업트리 `.venv` 부재 1건 및 별도 재실행에서 통과한
financial/native 검사 2건이었다. 기존 환경을 가리키는 ignored `.venv` 연결 후
관련 재실행은 25 PASS / Node wrapper 2 FAIL이다. 두 Node 파일의 직접 실행에서
loopback `listen EPERM`을 확인했고 history wrapper에는 unavailable worker도
관찰했다. 검사 비활성화나 관련 없는 history/bridge 수정은 하지 않았다.
동결 소스의 전체 회귀 판단은 독립 검증과 필수 PR CI 결과로 별도 확정한다.
