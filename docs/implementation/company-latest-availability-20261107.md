# 2026-11-07 회사별 최신 기간·가용성 설계 인터뷰

## 단계와 확정 범위

사용자는 회사별 최신 연간/분기를 기본으로 읽고 fixed FY/quarter도 유지하기를 요청했다.
소비자 정책과 제한된 source compatibility 확장을 승인했고 `my-eng-grill-with-docs`로
배치 기준을 확정했다. 현재 구현은 synthetic 자료로 검증하며 실제 발행·호환 승인 packet·
운영 전환은 ROOT의 별도 단계다.
기준 main은 `d2ccfd214f0960e51ece0b2306bd0150b1089e0b`다.

최종 목표는 임의 과거 날짜 D 조회지만 첫 단계는 **이미 준비된 cutoff**부터다.
최신은 가장 늦게 제출된 과거 정정공시가 아니라 **가장 최근 실제재무기간**이다.
해당 기간을 회사별로 먼저 정하고 모든 지표를 같은 anchor로 읽는다. 최신 기간의
0·UNAVAILABLE·quality blocker를 이전 지표 값으로 대체하지 않는다. TTM도 같은 최신
분기 anchor와 기존 발행 정책만 사용하며 새 산술을 만들지 않는다.

사용자는 일별 배치에서의 **우리 데이터 상태**와 투자 사용 시점에 따른 configurable lag를
구분했다. 사용지연은 **미국 거래일 단위, 기본값 0**으로 확정했다. 실제가용이력은 공개·
수집·분석 준비 기록에 근거하며 과거 준비 시각이 확인되지 않으면 미확인으로 표시한다.
가정에 따라 계산한 가용정보는 실제 이력과 분리한다. 자동 일별 job이나 새 수집·스케줄
설정은 승인된 실행 범위가 아니다. [용어집](../architecture/GLOSSARY.md)을 따른다.

## 확인된 증거와 한계

현재 50사 발행물의 `financial_as_of=2026-10-25`는 재무 선택 cutoff다. 조회기준시점 D와
별개이며 11월 6일에 준비한 이 발행물을 10월 25일에 이미 보유했다는 증거는 없다. Quarter inventory는 실제
period/FY/Q·filed/report date를 제공하고 annual에는 실제 FY 기간과 nested filing 근거가 있다.
그러나 관측 버전마다 과거 최초 사용 가능 시각을 잇는 완전한 이력은 확인되지 않았다.
`collection_operations.py`의 attempt/build `completed_at`만으로 그 이력을 대신하지 않는다.
누락된 최초 준비 시각을 filing date·mtime·나중 rebuild 시각으로 발명하지 않는다.

## 배치 조회와 지연

실제 가용 조회는 지정한 뉴욕 날짜까지 성공적으로 준비된 등록 배치 중 적격 최신을 선택한다.
오늘은 현재 시각까지만 포함한다. 이전 배치를 사용하면 선택된 실제 준비 시각을 표시한다.
공시일·배치 예정 시작·파일 수정시각으로 등록값을 만들지 않는다. 등록이 없으면 실제 조회는
자료 없음으로 표시하며 사용자가 별도로 준비 자료 기준 가정 조회를 고를 수 있다.
가정 조회는 선택한 발행물 자체의 cutoff를 사용하며 그보다 이른 임의 날짜를 복원하지 않는다.

기본 lag 0은 실제 준비 완료 후 즉시 사용한다. 양수 N은 뉴욕 기준 준비일 **이후**부터
판단일 **포함**까지 등록된 미국 거래 세션이 N개 이상인 배치만 허용한다. 거래일 목록의
범위를 명시하고 중복·역순·범위 밖 날짜를 거부한다. 양수에서 범위나 증거가 부족하면
선택을 중단한다. 주중 요일을 거래일로 추정하지 않는다.

SEC 원본 submissions는 `filingDate`, `reportDate`, `acceptanceDateTime`을 제공한다.
예로 AAPL accession `0000320193-26-000020`의 원본 캐시에서 확인했다. 현재 FilingRef는
날짜를 보존한다. SEC 설명상 EDGAR 접수는 sec.gov 최초 공개와 별개이며 최초 공개의
header timestamp는 제공되지 않는다. [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions) · [FilingRef](../../src/sec_xbrl/filing/contracts.py)

`serve --batch-availability PATH SHA256`로 아래 형식의 증거를 명시한다. 실제 배치는
이미 검증한 catalog 발행물 ID와 일치해야 한다. 시각은 UTC offset 또는 Z가 필요하다.

```json
{
  "schema_version": "screening-batch-availability-v1",
  "registrations": [
    {"dataset_id": "prepared-example", "publication_id": "example-id", "ready_at": "2026-11-06T19:00:00Z"}
  ],
  "sessions": {"from": "2026-11-06", "through": "2026-11-09", "dates": ["2026-11-06", "2026-11-09"]}
}
```

거래일 lag를 쓰지 않으면 `sessions: null`도 허용한다. 예시 시각은 실제 운영 증거가 아니다.

## 구현 경계

공유 resolver는 기존 explorer에 두고 explorer/service/server, compatibility helper/
dataset_v3/CLI 여섯 파일과 companion assets/tests에서 연결한다. CLI의 명시적
bootstrap witness로 기존21·old combined도 원래 publication에 연결하며 path 추정·환경변수·
monkeypatch·별도 병렬 재무 엔진은 쓰지 않는다. 기존 v1/v2 검증을 약화하지 않는 bounded
vNext와 네 financial parent·12 routine report 재사용은 최종 계약·독립 검증이 필요하다.
새 조건은 `LATEST_COMPANY_ANNUAL_V1` 또는 `LATEST_COMPANY_QUARTER_V1`과 선택 발행물·
준비 시각·판단일·lag snapshot을 저장한다. 배치에서 고정 기간을 선택해도 해당 snapshot을
함께 기록한다. 기존 fixed/legacy 조건·결과, 원본 자료와
사용자의 휴지통 DELETE8개를 보존한다. Explorer의 고정 보기와 기존 저장 이력도 열 수 있다.
차트는 실제 FY/calendar 좌표를 유지한다. 새8GB reader·재발행·운영 시작은 하지 않았다.


`serve --source-compatibility PATH SHA256`는 보존된 기존 combined와 새 combined를 같은
catalog에서 검증하는 명시적 scope다. v3 호환 증거는 archived408 v2와 그 v1 선행
증거를 확인하고 이미 고정된 부모 네 개를 그대로 요구한다.

## 구현 검증

합성 Python 집중 검사 77건과 최종 변경 관련 Node 검사 19건이 통과했다. 이전 companion
회귀 검사 38건도 통과했다. 검증 범위에는 날짜/lag·미확인 실제 가용성·최신 결측 유지,
조회·저장·재열기, 고정 기존 API 및 v2/v3 combined 동시 검증이 포함된다.
`uv run ruff check .`와 diff 검사도 통과했다. 실제 준비 timestamp 등록, 새 approved
packet, 독립 검증과 운영 메모리·시작 시간은 ROOT 확인 단계다.

독립 검증에서 같은 달력 버킷 안의 서로 다른 실제 종료일과 같은 FY의 다른 잔액
기준일이 최신 지표로 통과하는 반례를 찾았다. 최신 조회는 회사·기간 좌표·실제
종료일·종료일 규약을 대조하고, FY와 3개월 지표는 시작일도 대조한다. TTM은
별도의 시작일을 유지한다. 불일치와 품질 차단은 해당 값만 보류한다. 같은 규칙을
탐색·비교·조건 실행·프로필과 차트의 최신 점에 적용하며 고정 기간 조회는 기존
규칙을 따른다. 재해시한 합성 분기 파일로 반례를 재현하고 보류를 확인했다.
보완본은 관련 Python 40건, Node 29건, Ruff와 diff 검사를 통과했다. 새 동결 소스의
독립 재검증과 운영 검증은 별도 단계다.
