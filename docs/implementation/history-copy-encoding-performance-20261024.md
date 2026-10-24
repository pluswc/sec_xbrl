# History 선택 복사와 typed encoding 성능 관측

## 범위와 상태

- 기준: `2b5dde23c50b6ac0b83459df42777f38f312da0b`
- 상태: **H1 구현·측정 완료, H2 shared-walk 경로만 선택 적용**
- 대상: reported cell 재분류 시 복사 범위, 독립 감사의 private typed hash 구현
- 비대상: 공개 History 형식, schema, 회계 선택, 증명 재사용, 완료 기업 재검증,
  실제 runtime GO와 dispatch

H1 가설은 생산자와 독립 감사기가 cell 전체를 `deepcopy`하지만 실제로 바꾸는 값은
최상위 cell dict와 최상위 `value_lineage` dict뿐이라는 것이다. 두 dict만 복사하고
큰 candidate/evidence tree는 typed serialization이 끝날 때까지 읽기 전용으로 공유하면
출력 의미를 유지하면서 시간과 peak RSS를 줄일 수 있다. 중첩 evidence를 수정하는
호출자는 source 조사에서 발견되지 않았으며, 새 테스트는 원본 불변성과 작은 dict의
분리를 직접 검사한다.

H2 가설은 감사의 동일 typed protocol을 64 KiB 이하 buffer로 내면서 chunk aggregate,
개별 chunk, public aggregate와 행 digest를 같은 walk에서 여러 독립 SHA-256 sink로
보내면 record pair당 tree walk를 5회에서 2회로 줄일 수 있다는 것이다. dict key 순서,
길이 frame, UTF-8, 정확한 int와 float bits, `-0.0`, bool, null, bytes, list/tuple tag와
지원하지 않는 type의 닫힌 실패를 기존 protocol과 동일하게 유지한다.

## 구현 결정

생산자 `_spill_reported_table()`은 최상위 cell과 dict인 `value_lineage`만 복사한다.
`candidate_lineage`는 순서·타입·570개 대안 전체를 그대로 보존하고, 이름을 옮긴 뒤
private spill이 즉시 typed serialization한다. quarter pack/unpack/envelope, journal,
SQLite 및 ownership guard는 바꾸지 않았다. runtime checker도 생산자를 import하지
않는 별도 구현으로 같은 copy-on-write 범위만 적용한다.

`tools/history_audit_typed_hash.py`는 기존 byte protocol의 정확한 buffered encoder와
작은 `update`, `update_many`, mirror interface를 제공한다. 첫 구현은 hash sink마다
작은 fragment를 dispatch해 약 51% 느렸다. 마지막 한 번의 구조 변경에서 한 encoder
buffer가 각 fragment를 한 번만 만들고, 최대 64 KiB chunk가 찰 때 독립 SHA-256
target 3개 또는 2개에 한 번씩 전달하도록 바꿨다. 이 shared-walk 경로는 아래처럼
6~8% 빨랐다. ordinary single-hash는 89~93% 느렸으므로 기존 `logical()` 경로를
유지한다. R16 private chunk/public pair에서만 새 encoder를 사용하고, R15의 기본
FileStream도 기존 경로를 유지한다.

## 측정

승인된 prefix 24건(895,765 B)과 rich 1건(7,838,575 B, candidate 570개)만 사용했다.
각 arm은 별도 Python 3.12 `-B` subprocess에서 3회 교차 실행했고, 실행당 30초와
1 GiB RSS watchdog을 적용했다. prefix는 원본 24건을 38 cycle, rich는 원본 1건을
5 cycle 사용해 약 32 MiB workload를 만들었다. 원본 건수와 exercise iteration을
분리하며 한 rich cell을 기업 전체로 해석하지 않는다. 현재 MRK 작업의 CPU 간섭이
있을 수 있다. H1 시간은 JSON parse, 입력 불변성 확인용 serialization 2회, cell
copy·mutation과 output serialization을 포함하지만 전체 spill, T1 검사, column/row
조회나 SQLite write의 wall time은 아니다.

| 사례 | 비교 | baseline→candidate 중앙값 | 변화 | peak RSS 변화 |
| --- | --- | ---: | ---: | ---: |
| prefix 24건 / 912 iterations | 전체 copy·mutation·canonical serialization | 0.5774→0.3792 s | -34.33% | -2.38% |
| rich 1건 / 5 iterations | 전체 copy·mutation·canonical serialization | 0.8355→0.5169 s | -38.14% | -0.87% |
| prefix | legacy 5 walks→shared 2 walks | 1.4562→1.3642 s | -6.32% | +1.41% |
| rich | legacy 5 walks→shared 2 walks | 2.0932→1.9355 s | -7.53% | -0.13% |
| prefix | ordinary single hash | 0.3518→0.6639 s | +88.73% | 관측만, 미적용 |
| rich | ordinary single hash | 0.4806→0.9288 s | +93.27% | 관측만, 미적용 |

모든 paired arm의 complete ordered fingerprint는 일치했다. H1은 제한 표본에서
유의미한 시간 감소를 보였지만 실제 전체 producer 속도를 보장하지 않는다. H2의
5개 독립 digest fingerprint도 old/new가 완전히 일치했다. 측정된 shared 경로만
선택했고 단일 hash에는 적용하지 않았으며 추가 tuning을 중단했다.

측정 증거:

- `work/.../history_copy_encoding_writer_20261024/prefix24_profile_v2.json`
  (`3cb32b87988f3a6161e5f4af10ae3afc4184df7fe4f51d4ed8e179c1626d8a0c`)
- `work/.../history_copy_encoding_writer_20261024/rich1_profile_v2.json`
  (`82144e188a6acdcccdff203f26d44a0533181302b999b29c4df465a80768634c`)
- `work/.../history_copy_encoding_writer_20261024/prefix24_hash_broadcast.json`
  (`747914d68fb94fed0bdfbb096e7d3dcefed1bae092225bd9b47f7c9692fd9657`)
- `work/.../history_copy_encoding_writer_20261024/rich1_hash_broadcast.json`
  (`4bd114a837e7d789e84858e3eadf87bc531d10288b32be45f6424ef381e08ae4`)

두 runtime 후보는 H1 checker를 사용한다. R16만 private chunk와 public record의
decoded aggregate·row digest를 한 walk에서 계산한다. R15는 optional row digest seam을
포함하지만 기본 single-hash 경로는 이전 구현이다. 두 후보는 각 base의
gate/seal/index/engine/runner 정책을 그대로 유지한다. 새 GO나 실제 실행은 만들지 않았다.

## focused 검증

새 테스트는 frozen legacy oracle과 single/multiple/incremental digest, buffer split,
Unicode·큰 정수·float bits·`-0.0`·NaN·list/tuple·null·unsupported type, 원본 불변성,
570개 candidate 보존, 독립 chunk/public aggregate·row digest 및 mutation 검출을
검사했다. 직접 영향받은 기존 테스트는 대형 streamed repartition 한 건과 derived
quarter ambiguity parameter 4건만 선택했다. 완료 기업, 기존 gate/coverage 전체
suite와 실제 자료는 다시 실행하지 않았다.

```text
새 테스트 + 직접 영향 기존 테스트: 11 passed in 0.62s
R15 source-only runtime 통합: 2 passed in 0.11s
R16 source-only runtime 통합: 2 passed in 0.10s
Ruff format/check, git diff --check: PASS
```
