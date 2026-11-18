# 공통 CAL 1.0/1.1 추출 및 EPS 구성 검증

## 2026-11-18 최종 소스·자료 인수 상태

문서 상태의 동결 기준 시각은 **2026-11-18T07:47:29.812167+00:00**다.
제품 동결은 `5386cf242b719ce47995bfa84a666cf97e8aac94`다. 별도 읽기 전용 Sol이
해당 소스와 불변 v5 자료를 **PASS_FROZEN_SOURCE_AND_PINNED_DATA**로 검증했고,
ROOT는 `ROOT_ACCEPTED_FINAL_SOURCE_AND_PINNED_DATA_PENDING_OPERATION_CI`를
2026-11-18에 기록했다. 이후 private cold/API/browser와 실제 운영 검증을 마쳐
`ROOT_ACCEPTED_OPERATING_PENDING_PR_CI_MAIN`도 기록했다. 아래 초기 동결·P2 반환·재검증 대기는 당시 기록이며,
최종 source/data 판단은 이 절과 문서 끝의 최종 결과를 따른다.

| 단계 | 현재 근거와 상태 |
| --- | --- |
| IMPLEMENTED | 제품 소스 동결 `5386cf242b719ce47995bfa84a666cf97e8aac94` |
| INDEPENDENTLY_VERIFIED | 별도 Sol의 같은 SHA source/data PASS; 관련 검사 277 PASS / 1 SKIP |
| ROOT source/data 인수 | 같은 SHA로 v5 전체 exact replay 후 기존 artifact/bundle/publication 재사용 승인 |
| private cold/API/browser 및 운영 인수 | ROOT 인수 PASS; 실제 18765 / Native PID57888, 새 publication 적용 |
| PR / 필수 CI / main 병합 | 아직 최종 근거 없음; 별도 영속 receipt로 확정 |

이 문서 후속은 결과 기록만 수정하며 제품·테스트·CLI bytes는 동결 소스와 동일하게
유지한다. 원 artifact의 실제 생산자는 `fa60a629a798e6d25d67b38215f7724a43b42356`,
준비 시각은 `2026-11-18T07:05:17.358761+00:00`다. 더 엄격한 최종 검증 소스로
재사용했다고 생산 SHA나 원 ready timestamp를 5386 시점으로 바꾸지 않는다.

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
   이 inferred basic-to-diluted 경로도 같은 complete Context의 보고 convertible
   interest가 nonzero/uncertain이면 보류한다. 기본 common N에서 이미 signed CAL로
   차감한 preferred dividend를 새 희석 조정으로 다시 차단하지 않는다.
3. 희석 누적 route는 FY와 9M 각각 완전한 유효 CAL share equation을 요구한다.
   공식 basic leg와 양(+)의 source-identified stock award legs를 허용한다.
   Explicit basic-only equation으로 0 증분이 확인되는 경우도 양 기간에서
   compatible scope를 확인한다. Generic incremental child는 정확한 보고 cell의
   공시 row/column label 또는 해당 filing의 EPS treasury-stock 정책으로 구분한다.
   EPS에서 보통주 warrants에 treasury-stock 방식이 적용된다는 해당 절의 공시가
   있으면 함께 허용한다. 별도 historical antidilution 표의 언급으로 판단하지 않는다.
   명시적으로 방법 적용을 부정하거나 제외된 반희석 주식만 설명하는 절은 이
   affirmative 정책 근거가 아니다. 단순한 용어 언급 또는 장래·가정적 방법 적용도
   충분하지 않다. 현재의 계산·포함·방법 적용을 서술한 bounded source 문장이
   필요하며 정상적인 `if/when dilutive` 조건 자체는 장래 가정으로 배제하지 않는다.
   현재 적용 서술은 TSM을 설명하는 해당 절에 있어야 한다. 앞선 basic-EPS 절의
   현재 동사를 빌려 뒤의 hypothetical dilution을 승인하지 않으며, 일반적인
   주식의 `may be issued` 문구를 hypothetical method application과 혼동하지 않는다.
   보고 증분 point가 음수이면 원 decimals 구간이
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

### 등록 metadata부터 실행하는 공통 batch 명령

추적된 `examples/screening/prepare_q4_eps_reconstruction.py`의
`prepare-cal-sources`는 pinned proposal의 `source_filings`/`snapshots`와 source
catalog의 `documents:[{cik, accession, original_package:PIN}]`를 CIK/accession으로
연결한다. 모든 등록 source accession에 같은 `prepare_cal_eps_filing`을 적용해
새 projection root에만 파일을 쓰고 `cal-eps-filing-catalog-v1`을 만든다. 같은
package pin을 가진 복수 문서는 한 accession으로 처리한다. 누락·모호한 package,
모호한 filing/snapshot, 등록되지 않은 source와 준비 실패는 accession별 HOLD로
남긴다. 기존 projection root나 출력 파일은 덮어쓰지 않는다.

```sh
python examples/screening/prepare_q4_eps_reconstruction.py prepare-cal-sources \
  --input /absolute/proposal.json --sha256 PROPOSAL_SHA256 \
  --source-catalog /absolute/source-catalog.json --source-catalog-sha256 SOURCE_CATALOG_SHA256 \
  --taxonomy-cache /absolute/offline-taxonomy-cache \
  --projection-root /absolute/new-cal-projections --output /absolute/new-cal-catalog.json
python examples/screening/prepare_q4_eps_reconstruction.py verify-cal-sources \
  --input /absolute/new-cal-catalog.json --sha256 CAL_CATALOG_SHA256 \
  --taxonomy-cache /absolute/offline-taxonomy-cache
```

`verify-cal-sources`는 catalog의 준비된 projection을 같은 offline verifier로
전부 replay하며 HOLD 수는 별도로 보고한다. 실제 SEC 다운로드나 운영 전환은
수행하지 않는다. 새 회사도 upstream 등록 intake와 불변 ZIP pins를 갖춘 proposal/
source-catalog metadata에 추가한 뒤 이 batch → 같은 global qualification → 빈
current EPS 역할의 append 순서로 처리한다. 회사별 소스 수정이나 세션 임시
orchestration script가 이 공개된 실행 경로의 전제는 아니다. 이번 684 accession
실자료는 같은 provider 함수로 준비됐으며 이 CLI를 검증하려고 760개 source
문서 전체를 다시 준비했다는 의미는 아니다.

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
  tests/screening/test_cal_eps_source_cli.py \
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

첫 동결 `0da4e79ebf72114edbf830a711265232f3595879`의 독립 검토에서 treasury-stock
용어 언급과 hypothetical future 문장이 affirmative 정책으로 승인되는 P2가
반환됐다. 후속은 `cal_eps.py`, 관련 단위 검사와 이 계약만 수정한다. 현재 적용을
요구하는 bounded predicate와 5개 부정·8개 양성 문장 회귀를 추가했고, 이전 실제
v3 probe에서 쓰인 서로 다른 10개 방법 적용 문장은 모두 계속 지원됨을 별도로
확인했다. 후속 기본·호환성 회귀 합계는 **253 PASS / 1 SKIP**(4.75s), Ruff와
diff check PASS다. 최종 SHA의 독립 재검증과 실제 최종 artifact 인수는 별도다.

다음 동결 `fa60a629a798e6d25d67b38215f7724a43b42356`에서도 inferred basic N을
희석 N으로 쓰는 경로가 보고 convertible-interest counterevidence를 검사하지
않는 P2가 반환됐다. 해당 추론 경로에 동일한 diluted-only 검사를 연결하고,
nonzero/uncertain HOLD, explicit zero 및 기본 N에 이미 구성된 preferred leg의
양성 회귀를 추가했다. 총괄이 추가 승인한 위 batch CLI는 회사별 코드 없이 새
등록 metadata를 처리하며, 단위 검사에서는 Arelle provider를 대역으로 사용해
연결·pin·중복·누락·출력 보존 계약을 네트워크 없이 검증한다. 실제 source
projection provider와 parser는 바꾸지 않는다. 이 후속의 기본·호환성 검사
합계는 **265 PASS / 1 SKIP**(3.66s), Ruff와 diff check PASS다. 전체 최종
artifact를 새 코드로 exact replay한 결과에 따라 기존 준비 시각·관측을 재사용할지
총괄이 별도 판단한다. 이전 probe/publication을 이 자체 검사로 인수하지 않는다.

`cd92849253713b343daa7b6f3254a9ed30145ed9`에서는 기존 v5 artifact 전체의 자연스러운
fresh-process exact verifier replay가 PASS했다(6,928 quarter rows / 11 observations,
98.723s). 그 뒤 별도 basic-EPS 현재 절에서 미래 warrant 절로 동사를 빌릴 수 있는
인접 source 문장 사례를 총괄에 반환했다. 승인된 마지막 수정은 절 경계를 분리하고
method-application modal을 검사하며, `may be issued`와 정상 `if/when dilutive`
양성은 유지한다. 네 개 절·modal 회귀를 더한 합계는 **269 PASS / 1 SKIP**,
Ruff/diff check PASS이고 기존 v5의 서로 다른 실제 양성 절 10개가 모두 그대로
지원된다. 최종 동결의 전체 artifact exact replay와 독립 판단은 새 SHA를 기준으로
다시 수행하며 위 cd928 replay는 그 이전 단계의 근거다.

그 수정 전 시작한 로컬 전체 pytest는 **3,385 PASS / 39 SKIP / 14 FAIL**
(333.57s)이므로 최종 소스의 전체 PASS 근거가 아니다. 알려진 cached NVDA
recovery inventory 실패 1건, sandbox의 Python HTTP socket 권한 실패 8건,
Node bridge 검사 2건, 작업트리 `.venv` 부재 1건 및 별도 재실행에서 통과한
financial/native 검사 2건이었다. 기존 환경을 가리키는 ignored `.venv` 연결 후
관련 재실행은 25 PASS / Node wrapper 2 FAIL이다. 두 Node 파일의 직접 실행에서
loopback `listen EPERM`을 확인했고 history wrapper에는 unavailable worker도
관찰했다. 검사 비활성화나 관련 없는 history/bridge 수정은 하지 않았다.
동결 소스의 전체 회귀 판단은 독립 검증과 필수 PR CI 결과로 별도 확정한다.

## 최종 source/data 결과 — 2026-11-18

### 동일 소스 재현, 원본 보존 및 기업 추가 경로

최종 5386 동결의 작성자 검사는 **269 PASS / 1 SKIP**, 독립 Sol의 관련 검사는
**277 PASS / 1 SKIP**이며 두 역할 모두 Ruff와 diff check PASS다. 독립 검증자는
반환된 preferred/convertible numerator, participating counterevidence 및 현재
TSM 적용 절의 반례 수정도 확인했다. 최종 소스의 전체 pytest PASS를 주장하지
않으며 앞 절의 로컬 환경·cached-history 한계와 필수 CI 대기는 그대로 구분한다.

최종 catalog는 **107회사 / 684 accessions / 179,346 duration facts**다. 독립 검증은
fact identity·값·Context·dimensions와 원 immutable Raw의 일치, ZIP 및 snapshot
보존, CAL 밖의 조정 counterevidence 보존을 확인했다. 두 CAL arcrole, role,
link/arc QName, Arelle 유효 priority/prohibition과 원 lexical weight/order는 서로
섞이지 않는다. 기존 source replay v3의 FAIL은 과거 기록이며 최종 PASS로
바꾸지 않는다. 최종 catalog/Raw 대조와 별도 실제 HD offline CLI 준비·replay의
byte 일치가 후속 독립 근거다.

5386의 fresh-process `verify_q4_eps`는 v5의 **6,928 quarter rows와 11 observations
전체를 exact 재현**했다. 작성자 실행은 97.913s이며 독립 검증도 같은 전체 결과를
확인했다. 따라서 ROOT는 v5, augmented financial bundle과 가격 publication의
기존 bytes·원 producer·ready 시각을 그대로 재사용하도록 승인했다. 새 10개 TTM
외 기존 **326 observations**, AMZN **12.37**의 값·원천·ready, 기존 **100 grant
coordinates**, financial anchors 및 다른 상위 필드는 보존됐다. 기존에 비어 있던
10개 current EPS 역할과 그 추가 evidence만 연결했다.

기업 추가는 등록된 intake/snapshot과 원 ZIP pins를 metadata로 연결한 뒤 위의
`prepare-cal-sources` → `verify-cal-sources` → 동일 global qualification → 빈
current EPS append 순서다. 구현은 CIK/ticker별 분기를 두지 않는다. 단위 검사의
임의 신규 CIK와 입력 순서·중복·누락 검증에 더해 독립 검증자는 실제 HD accession을
같은 CLI로 준비·replay해 최종 catalog와 byte 일치를 확인했다. 이 자동 경로는
미해석 회계 유형까지 자동 승인한다는 뜻이 아니며 필요한 source/basis가 닫히지
않으면 회사별로 HOLD를 남긴다.

### 109회사 현재 평가의 적격 확대

가격 session과 공시 정보 cutoff는 **2026-11-13**, 현재 평가일은 **2026-11-18
Asia/Seoul**이다. 같은 가격·정의 정책으로 준비된 publication의 직접 조회 결과는
다음과 같다. 이 표는 준비 자료의 결과이며 API/browser/운영 인수 완료를 대신하지
않는다. 이후 ROOT는 동일한 109회사 count를 실제 운영 API에서도 확인했고,
별도 API/browser 및 운영 인수를 아래처럼 완료했다.

| current metric | 기존 | 최종 준비 자료 | 변화 |
| --- | ---: | ---: | ---: |
| PER AVAILABLE | 13 | 22 | +9 |
| Earnings yield AVAILABLE | 13 | 23 | +10 |
| PBR AVAILABLE | 75 | 75 | 0 |
| BPS 경로 PBR AVAILABLE | 60 | 60 | 0 |

추가 current diluted TTM은 **AMAT, AMGN, HD, LRCX, ADBE, IDXX, GILD, ROP,
SNPS, ALAB** 10회사다. 이 중 9회사의 양수 EPS로 PER/EY 및 고정 10/15/20배
band가 적격이 됐다. **GILD EPS −3.1564351879986456805…**는 보존하며 PER는
기존 `EPS_NONPOSITIVE` 정책으로 UNAVAILABLE, earnings yield는
**−1.8779361932488141069…%**다. 기존 AVAILABLE current 값은 모두 exact
유지됐다. Historical/series의 status·value 순서도 모두 같고 109회사 중 99개
파일 hash가 동일하며 나머지 10개는 metadata만 달라졌다.

신규 관측은 `historical_ready=false`, `backtest_eligible=false`다. 이번 현재 평가
준비로 과거 가격 날짜에 EPS가 이미 준비됐다고 인증하지 않는다. 역사 backfill과
historical ready 승격은 **0건**이다.

### 남은 PER 87회사: 준비·구현 범위와 회계 보류의 분리

회사별 CSV는 109회사의 실제 prepared query를 보존한다. PER UNAVAILABLE 87은
아래 **8개 source/자료·회계 그룹의 86회사**와, 위 **GILD 음수 PER 정책 1회사**다.
요약 JSON의 literal labels는 GILD 정책까지 포함하면 9개다.

| source/자료·회계 그룹 | 회사 수 | 현재 해석 |
| --- | ---: | --- |
| 기업·주식 기준 근거 연결 미준비 | 25 | 기존 grant 20개 부재, class/scope binding 4개 및 common-class cover 1개 미확정 |
| 공통 구성 유형·원문 연결 검증 미지원 | 35 | 현재 공통 규칙에서 N 귀속·희석 population·continuing/source-table 증명이 닫히지 않음; 모두 단순 미구현으로 단정하지 않음 |
| CAL 구성의 Context·단위·값 연결 미확정 | 4 | 같은 complete Context의 CAL child 3개, Unit 1개 연결 미확정 |
| 구성값 추출·표준 태그 매핑 보완 필요 | 4 | 필요한 N/W/EPS component 해소 미완료; 공시 자체의 부재 판정 아님 |
| 별도 회계 유형·기간 가산성 미확정 | 8 | participating/two-class 5개, diluted-N 조정 2개, continuing-loss control 1개 보류 |
| 공시 EPS와 구성 검산 불일치 | 4 | 원 precision 범위에서도 누적 보고 EPS 검산 불일치 |
| 분할·공시 버전 기준 불일치 또는 미확정 | 3 | split/window 2개 및 comparative basis 1개 미확정 |
| 보존된 재무 추출·기간 범위 미준비 | 3 | HONA·IBM·SPCX의 보존 FY/9M context window 미확보 |

이 분류는 남은 87회사를 전부 엔진 미구현, 전부 실제 자료 부재 또는 전부 회계상
불가능으로 합치지 않는다. CSV의 `source_disclosure_absence_certified`는 109회사
모두 **False**다. 필요한 component가 현재 준비 자료에서 해소되지 않았다는
사실로 SEC 원 공시에 해당 disclosure가 없다고 인증하지 않는다.

### 최종 근거와 아직 분리된 단계

ROOT는 `2026-11-18T07:44:25.555946+00:00`에 운영 인수를 기록했다. 실제
18765는 **5386 archive / Native PID57888**, publication은
`screening-price-metrics-e7c87930507d959b8bb07f86`이다. 직전 실제 운영은 별도
채팅이 이미 main `6b19854550` integrated source로 교체한 **PID57508**임을 다시
확인한 뒤 전환했다. 그 UI/bridge의 hash와 원 args/DB를 유지하며 승인된
5386 worker와 새 publication만 연결했다. 초기 조사 **PID60968 / coverage404**는
당시의 역사 baseline이고 이번 전환 직전·직후 운영 상태로 해석하지 않는다.

실제 API에서 109회사 PER22/EY23/PBR75/BPS60 count와 신규 양수 EPS **9회사
각각의 PER**, GILD 음수 정책을 확인했다. Live CAL 원천 근거·bands 및 browser
export 검증은 **HD 대표 1회사**다. 9회사 bands 전체의 exact 대조는 앞 절의
독립 publication 계산 검증이며 9회사 각각을 live에서 시험했다고 기록하지 않는다.
History backfill 부재와 Coverage endpoint **200**, MSFT timeline·interpretation도
PASS다. Native Chrome
**1440px / 14 datasets**에서 HD **PER24.41**, Q4 구성 근거, KST ready 표시,
export exact와 browser errors **0건**을 확인했다. 관련 screenshot은
`operating-cal-eps-evidence.png`로 보존한다.

사적 18819에서는 기존 저장 **15개 + 신규 저장 3개**를 cold restart 후 exact
재열기했고 검증 후 해당 private instance를 종료했다. 이 사적 저장과 운영 저장은
구분하며 **운영 시험 쓰기는 0건**이다. 활성화 후 보호 파일 **1,675개**, 기존
architecture assets **17개**, 원 taxonomy-cache pins **182개**, 원 journal **2개**의
hash가 모두 같고 DB integrity는 `ok`다. 원 금융 journal hash
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`와 가격 journal
hash `ba18bf81059b4de96e5028dd1e9a320c37100aa8366fd4b09299d9be7131e8b0`도 그대로다.
기존 Python backend19078의 PID1477655 LISTEN 상태와 별도 18766의 원
`screening-price-metrics-577ab236eef320385d98bd71` publication도 보존했다.

최종 선택적 로컬 증거는 `work/cal-eps-common-20261118/evidence/`에 보존한다.
새 checkout은 위 계약·명령·값·보류 의미만으로 실행 경계와 현 상태를 이해할 수
있으며 이 임시 경로가 제품 실행의 필수 설정은 아니다.

| 증거 | SHA256 |
| --- | --- |
| `final-source-data-root-acceptance-v1.json` | `d368e5afe4aa7cd2b03d7d3ecaaf67f72767703a17dba12adb9af8f4d45ceb90` |
| `cal-eps-independent-sol61-final-5386-PASS.json` | `f0ff0ed657c3e6c8c9b7cd54c13b7c7463298a3235803c95d74806cc8d1c3432` |
| `writer-local-validation-v4.json` | `88fbafe607443cd6ae76c136b67aee26d19d1b1b75794c669853bb1fa51fc1b1` |
| `writer-v5-exact-replay-5386-v1.json` | `1b449d9a3d10d254e7455dc62a366bc832eb89eb143b71215e9fe1e6940d4efa` |
| `company-query-summary-v1.json` | `58100abdaffdf52cfc06e7c7418c7bcc109e507dc0f5ec985705a5f5187dc522` |
| `company-query-results-v1.csv` | `17ff0bd6a6de0c675614523c86cebeb692783005c5167a123b2c67c994c8fa9c` |
| `root-operating-acceptance-v1.json` | `d6e7b1fa3b0b724d828c4e82b1383ac90485256dac6c29f62d859d46b8822033` |
| `post-activation-preservation-v1.json` | `0068cb559239a85929f8a05fa9d6d95e67cea26ce745f6dee8609901102d43d6` |
| `private-cold-qa.json` | `e2dc2c1d7014292684c18cd65481896b8231434b22a49565042a39d529d5c3ae` |
| `operating-browser-qa.json` | `56af3115cdc1317f0c44d0dc9a30fc4c63d116417da6b654c118c7ebcb3795de` |

PR 필수 CI, main merge와 병합 후 CI는 이 문서 상태 동결 시점에 **PENDING**이다.
이후 최종 전달 상태는 해당 PR의 정확한 head/merge SHA에 대한 실제 CI와 ROOT의
별도 delivery receipt에서 확인한다. 운영 PASS가 원격 전달 PASS를 의미하지 않으며,
미래 CI·병합 결과를 이 문서에서 미리 추정하지 않는다.
