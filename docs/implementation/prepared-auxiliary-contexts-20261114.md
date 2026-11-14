# 준비된100·109 보조자료 context 보존

2026-11-14 현재 **독립 검증·ROOT 로컬 인수·109 LIVE 완료, main 미병합**이다.
아래 최초 구현/운영 전 문구는 각 단계 당시 기록이다. 이 후속 커밋은 문서만 변경한다.

2026-11-14 리드는 수락된 준비 조건100과 새109의 매출 구성/성장률 보조자료 범위를
함께 유지하도록 consumer 전용 확장을 승인했다. 기준은 수락 소스
`d1e74d90c98838431740c0e16408d8b4d2623543`이며 현재 구현 단계다.
독립 검증·실제 연결·main 병합은 별도이며 backend/financial/자료/기록은 변경하지 않는다.

기존 단일 prepared snapshot CLI는 그대로다. 새 상호 배타적 옵션은
`--prepared-changes-contexts HOST_FILE --prepared-changes-contexts-sha256 SHA256`다.
명시적 main auxiliary union이 필요하며 HTTP가 파일이나 경로를 고르지 않는다.

불변 목록 schema는 `prepared-auxiliary-contexts-v1`, `contexts`는 비어 있지 않은
배열이다. 각 항목은 정확히 `parent`, `snapshot`, `verification`, `approval`의
`{path, sha256}` pin이며 모두 host에서 읽을 수 있는 원본과 byte 동일한 복제본이다.
각 부모는 기존 union loader로 검증하고 main과 같은 cutoff·동일 owner인 CIK
부분집합이어야 한다. 기존 bindPreparedAuxiliary의 snapshot/verification/ROOT 승인/
logical manifest 검증을 모두 재사용한다. 그 결과인 prepared 논리 scope와 정확한
부모 CIK 집합만 추가하며 부모의 다른 context를 자동 전파하지 않는다.

기존 main context를 포함한 request dataset/publication/cutoff 충돌과 목록 중복,
잘못된 pin·owner·cutoff·승인은 relay 시작/listen 전에 거부한다. 기존 원시50 직접
응답과 owner payload는 그대로이며 새9가 옛 준비100 범위를 빌려 쓰지 못한다.
검사는 두 prepared scope의 성공/서로 다른 proof hash·CIK 범위와 잘못된 입력/
충돌을 focused Node로 확인한다. 이 기능은 새 회계 계산이나 데이터 발행이 아니다.

## 구현 확인

별도 branch `codex/prepared-auxiliary-contexts-20261114`에서 bridge/기존 owner 검사와
이 계약·계획 링크만 변경했다. focused Node9개가30.57ms에 PASS했고 CJS 문법·diff
검사를 통과했다. 기존7개 경계와 새 두 prepared scope/CIK/proof·pin/승인/owner/
cutoff/충돌을 확인했다. 독립 검증 전이며 실제109 연결·자료 발행·운영 변경은
수행하지 않았다. 원래3fa financial 소스와 d1e 수락 작업 트리는 유지했다.


## 2026-11-14 실제 자료·private 인수 — 운영 전

Consumer bridge `1e7d12fb549701ee67b543d8b6e51687919ce38b`는 별도 독립 Node9 PASS와
ROOT source 수락을 완료했다. Financial source `3fa2ae4fe282933eea2d8a505d007c93a7df635a`의
실제9개사 네 financial 부모·native combined·projection도 수락됐다. 분기8개만
기존401에서538.7초/최대3.30 GiB에 정정했고, 새 financial4개는60.148초/0.98 GiB,
combined/projection은33.382/9.098초였다. 기존 quality/Raw/History 감사는 반복하지 않았다.

기준109 발행물은 `screening-cohort-union-ce87f864397594d8ac8319e4`, 원래 manifest
SHA256 `9734d74e127338ab790a73597b95a4aa1b4210c14561c9f1af5fab1ee0955e11`이다.
새109 consumer read export는20.218초/736,400 KiB였으며, 원래100개 회사 payload의
100/100 SHA가 같았다. 원본을 바꾸지 않는 hardlink 재사용으로826,486,784 physical
bytes를 절약했다. 원래12개 snapshot과 준비된100 발행물은 다시 export/publish하지 않았다.

수락된 d1e producer의 준비 조건27개를 그대로 재사용한 prepared109는
`screening-prepared-changes-62a6bbe37d79543efd2bc7f1`이며102.133초/1,588,892 KiB였다.
원래100개사의 네 view·상세 값/관측ID/이유/계보가 같고, 전체109 owner manifest
metadata만 새 범위를 반영했다. 실제 새 계산 정책이나 빈값 채우기는 없다.

Private API는14 datasets/109개사·연간41/분기59 정의와 저장·재열기·trace·CSV가
PASS했다. 옛21개사 저장 결과2개의 trace/CSV 포함6개 경로도 같았다. Windows
private18885에서 CEG 연간/분기/TTM·AAPL과 비교, 준비된100/109 양쪽 보조자료의
동일 payload를 확인했다. 실제 journal은 바꾸지 않았으며 이 시점 LIVE 전환은 대기다.
근거는 `work/remaining15-recovery-20261114/runtime/composition-acceptance.json`과
`runtime/prepared-changes109/`의 source 승인·private 인수 자료다.

남은6개사는 별도다. CRWD는 승인된 두 FY registry와 원래22개 공시를 보존하며
후속 focus 교정/History 준비가 남았다. APP/TER는 optional inline ID 없는21개
source locator 경계, PLTR/RKLB는 확인된 유일한 genuine instance의 ZIP entrypoint,
AEP는 미완료 History timeout 경계다. CEG/EXC 최신 연간 매출의
PRIMARY_STATEMENT_EVIDENCE_MISSING, CPRT의 REQUIRED_ITEM_NOT_IN_PREPARED_DATA는
기존 이유 그대로 빈값이며 추정하거나 backfill하지 않았다. Main 병합은 별도다.


## 2026-11-14 실제109 운영 인수

리드가 실제 전환과 브라우저 인수를 완료했다. 18765(frontend PID23088)는
19078(backend PID1477655)로 연결된다. Consumer Python·앱·스타일은 수락된 d1e
그대로이며 bridge만 `1e7d12fb54`/SHA256
`025bce8bb3e1f361a575b96c1bc445fb4ca5a5391a8fd062f5b2c0ac3afb3150`다.
변화 조건27개 정의를 유지하고, 운영 CMCSA 화면에서 영업이익·영업현금흐름
전년비 연결을 확인했다. 운영에서 확인한 pair는 이 두 개이며 JS 오류는0이었다.
Prepared109 publication은 `screening-prepared-changes-62a6bbe37d79543efd2bc7f1`,
재무 기준일은 원래2026-10-25이며 새 수집일로 바꾸지 않았다.

기존12개 dataset status·실제 History API가 정확히 같고 보호한 원래 파일12개
SHA가 모두 같았다. 실제 journal SHA256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로 유지했다.
이 인수는 private 복제본 저장 검사를 재실행하거나 실제 개인 기록을 쓰지 않았다.
이전 준비된100 backend19079는 rollback으로 보존한다. 리드가 소유 private
19077/19080·Windows18885를 정리했고 LIVE18765/19078과 rollback19079를 유지했다.

실제 근거는 `runtime/prepared-changes109/root-live-acceptance.json`과 Windows
`remaining15-recovery-20261114/current-feature-integration/`의 `live-switch.json`,
`live-smoke.json`, `live-109-cmcsa.png`, `private-ui-acceptance.json` 및 화면2개다.
남은6개 상태는 위 기록대로다. 특히 CRWD는 두 FY 교정 registry 승인만 있으며
History/분석 교정을 아직 적용하지 않았다. Main은 `d724c54e24`이고 이번 변경의
main 병합은 수행하지 않았다. Source `1e7d12fb54`의 독립 수락은 그대로 유지된다.


## 2026-11-14 사용자 승인 main 전달 후보

사용자는109 확장과 상세 연결의 검토·main 병합을 요청했다. 운영 작업 트리는
그대로 두고 별도 `codex/remaining109-main-integration`에서 원래 financial
`3fa2ae4fe282933eea2d8a505d007c93a7df635a`와 PR98 병합 main
`ad877d26beef8287199af2f2d84f978e953d6d4f`를 일반 merge했다. 충돌은 계획 등록부의
추가 항목뿐이었고 양쪽 날짜별 기록을 모두 보존했다. 위 main 미병합/d724 표시는
당시 운영 인수 기록이며 최종 병합 결과·merge SHA는 후속 PR와 Git 이력으로 확인한다.

통합 Python130개(원래129+read_snapshot)는 각 수락 부모의 bytes 그대로이며,
bridge/owner 검사는1e7d, UI·guidance는 최신 main 그대로다. 새 source inventory에는
read_snapshot.py가 추가돼 옛3fa 준비/native·reader source 영수증을 자동 상속하지
않으며 실제 거부를 확인했다. 기존 v1/v2와 qualification 범위를 넓히지 않았다.
정확한 재현에는 원래 승인된3fa financial·d1e consumer·1e7d bridge Git refs와
불변 산출물을 사용한다. 향후 새 main 생산자 qualification은 별도 마일스톤이다.

합성 통합 검사10개가10.41초, owner Node9개가28.12ms에 PASS했다. 정상 승인된
read snapshot 소비·기존 논리ID, 준비 조건 발행/재열기와 구 native 거부를 확인했다.
Ruff·diff·부모별 byte inventory도 PASS다. 이는 통합 코드/read consumer의 수락
근거이며 병합 소스의 financial 생산 승인이 아니다. 완료 회사 감사·전체 pytest·
자료 발행·LIVE109 재시작·journal 쓰기는 수행하지 않았다. 독립 통합 검증과
리드 PR/원격 CI/main 병합은 다음 단계다.

PR99 첫 CI의4개 실패는 합성 legacy-v2 fixture가 현재 source map/baseline을
사용하면서 과거 partial-window 기대 해시만 유지한 불일치였다. 실제 거부 guard가
정상 동작한 것이며 production 승인 범위는 바꾸지 않았다. 두 fixture에서 기존
named 해시 key만 합성 baseline에 결속하고, 실제 현재 inventory가 옛 승인을
상속하지 못하는 무패치 음성 검사를 추가했다. 관련 두 파일6개 검사는6.03초에
PASS했고 Ruff/diff도 통과했다. src/examples는 통합 후보 `dd1d762f9a`와 byte 동일하다.
후속 독립 검토·원격 CI·main 결과는 리드가 별도로 확인한다.
