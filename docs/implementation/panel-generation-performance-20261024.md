# 패널 생성 성능 관측 및 단일 조립 개선 (2026-10-24)

## 범위와 가설

이 마일스톤은 패널 생성부터 fiscal spill, History Parquet 작성·재로딩, 성공 종료
검증까지 한 프로세스로 측정한다. 회계 선택, 그래프 의미, 공개 스키마, ID, 후보 순서,
원본 spill 저널과 소유권 검사는 바꾸지 않는다.

첫 가설은 그래프 탐색 중 선택되지 않은 경로의 복사가 지배 비용이라는 것이었다. 실제
측정에서는 그래프 검색 자체가 약 0.0014초였고, 1,700개 경로의 방어적 복사가 약
0.0647초였다. 반면 cells staging은 0.1749초였고 그 안에서 원본 spill 무결성 검사와
동일 cell 재구성이 반복됐다. 따라서 그래프 가지치기는 근거가 부족해 구현하지 않았다.

선택한 개선은 `_SpilledRecordSequence`에만 적용한다. 첫 schema 탐색 때 재구성한 typed
record를 체크섬이 있는 임시 spool에 한 번 기록하고, 전역 JSON field와 schema가 정해진
뒤 그 spool을 읽어 Parquet을 만든다. 일반 `Sequence` 경로는 기존 구현을 유지한다.
columns는 실제 History 호출처럼 tuple로 물질화하므로 임시 spool을 쓰지 않는다.

## 측정 입력과 한계

입력은 완료된 COP 산출물에서 projected column/filter로 추출한 FY2025
`LATEST_REPORTED` Revenue root의 완전한 도달 component이다. fixture는
`cop_fy2025_revenue_component_v2.json`, SHA-256
`2703f0c3478a5ee9e686aaf218cffea4c0b1d0f16e04d953fc69ab871c9922b8`이다.
관측 수 698개, 선택 fact 32개, node 120개, edge 277개, simple path 1,700개다.
source filing ID와 source fact ID를 함께 사용했고 원본 파일 상대 경로·크기·SHA와
레코드 순서를 고정했다.

이 fixture는 내부적으로 attested된 파생 component다. 전체 COP publication이나 회사
완료 검증을 다시 수행한 것이 아니며, 한 component의 결과를 전체 회사 시간으로
외삽하지 않는다. 실행 중 DUK 작업과 같은 호스트 자원 경합이 있어 절대 시간보다 같은
입력의 교차 실행 차이를 판단 근거로 사용한다.

## 상세 프로파일

교정된 기준 상세 프로파일은 generator가 consumer에게 yield한 대기 시간을 제외하고
`next()` 안의 실제 작업만 센다. 주요 값은 다음과 같다.

- 전체 0.5065초, peak RSS 245,276 KiB
- panel build 0.1104초, fiscal spill build 0.1066초
- columns/rows/cells staging 0.0300/0.0276/0.1749초
- cell 재구성 active 0.1099초, `_resolve_cell` 0.0868초
- spill unpack 0.0191초, 원본 spill 무결성 검사 7회 합계 0.0796초
- JSON encoding 0.0418초, native Parquet write 0.0202초

후보 상세 프로파일에서는 rows/cells 원본을 한 번만 읽었다. cells 재구성 active는
0.0549초, 원본 spill 무결성 검사는 5회 합계 0.0549초였다. 상세 monkeypatch 계측값은
포함 관계가 있으므로 서로 더하지 않는다.

## 계측 없는 교차 비교

동일 import, fixture constructor, panel→spill→write→reload 경로를 별도 fresh subprocess로
3회 교차 실행했다. 상세 monkeypatch는 전혀 설치하지 않았고 성공 `close(True)`까지
경과 시간에 포함했다.

| 항목 | 기준 median | 후보 median | 변화 |
|---|---:|---:|---:|
| 전체 경과 | 0.5262초 | 0.4652초 | -11.6% |
| peak RSS | 228,080 KiB | 233,316 KiB | +2.3% |

RSS 차이는 실행 잡음 범위라 개선으로 해석하지 않는다. 부모 watchdog이 본 전체 프로세스
최대치는 기준 244,912 KiB, 후보 244,280 KiB였고, 각 실행에 1 GiB/30초 제한을 적용했다.
후보 임시 spool peak는 cells
3,109,678 bytes였고 rows는 154,831 bytes, columns는
0 bytes였다. 최종 columns/rows/cells count, 전역 JSON fields, 전체 decoded fingerprint,
각 Parquet byte 수와 SHA-256은 모든 기준·후보 실행에서 완전히 같았다. 최종 artifact는
122,490 bytes였다.

## 정확성 및 실패 계약

임시 spool은 기존 비실행 typed `_spill_pack`/`_spill_unpack` 계약을 그대로 사용한다.
각 frame 길이와 payload SHA-256, 전체 순서 chain digest, 개수·파일 크기, inode/device
소유권을 확인한다. header/payload 변경, frame 순서 변경, truncation, trailing append를
fail closed로 거부한다. 생성/open/header write 실패에서는 소유 FD를 닫고, 현재 pathname의
device/inode가 그 FD에 고정한 identity와 일치할 때만 소유 spool을 제거한다. guard가 생성을
거부했거나 `O_EXCL` 충돌이 났거나 pathname이 교체된 경우에는 기존 파일·symlink target·
교체 파일을 삭제하지 않는다. 정상 인코딩 뒤에는 동일한 identity 확인 후 spool을 최종
chunk inventory를 반환하기 전에 삭제한다.

History storage guard의 path 인자는 exclusive create 직전에만 전달한다. 이미 소유권을
고정한 spool의 seal/read/delete 검사는 인자 없는 guard check와 fd/path inode 비교를 함께
사용한다. 기존 파일을 overwrite로 간주해 거부하는 recovery guard에서도 정상 spool이
오탐 없이 동작하고, 모든 생성 경로가 소유 root 안인지 focused test로 확인했다.
guard가 활성화된 실패 경로에서는 기존 History 정책대로 workspace와 진단 artifact를
보존한다. 따라서 모든 임시 directory를 삭제한다고 주장하지 않는다. 일반 경로에서도
foreign pathname 교체가 보이면 workspace finalizer를 분리해 외부 파일을 지우지 않는다.

소유권 예외 보정은 성공 경로를 바꾸지 않으므로 위 3회 성능 수치는 그대로 계승했다.
보정 뒤에는 guard 거부, regular file·symlink `O_EXCL` 충돌, header write 중 pathname 교체,
소유 FD close와 외부 내용 보존을 별도 focused test로 검증했고 성능 측정을 반복하지 않았다.

late nested field가 앞선 bool/int/큰 정수/Decimal/date/Unicode/null 값을 전역 JSON으로
승격하는 기존 동작과 schema를 eager 기준과 byte 단위로 비교했다. 입력 provenance도
변하지 않는다. 첫 verified pass 뒤 원본 SQLite를 바꾸면 최종 성공 close의 기존 저널·SQL
무결성 검사가 실패하며 publication은 만들지 않는다. 실패한 원본 spill 진단 파일은
보존한다.

## 재현 명령

Python 3.12 가상환경에서 `PYTHONDONTWRITEBYTECODE=1`, `python -B`를 사용했다.

```text
python -B tools/profile_panel_generation.py compare \
  --fixture .../panel_generation_writer_20261024/cop_fy2025_revenue_component_v2.json \
  --baseline-source .../history-copy-encoding/sec_xbrl/src \
  --candidate-source .../panel-scope-performance/sec_xbrl/src \
  --output .../panel_generation_writer_20261024/paired_uninstrumented_bounded_final.json \
  --rotations 3
```

전체 완료 회사 재검증이나 SEC/Raw 재수집은 실행하지 않았다.
