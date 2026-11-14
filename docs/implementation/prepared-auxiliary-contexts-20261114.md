# 준비된100·109 보조자료 context 보존

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
