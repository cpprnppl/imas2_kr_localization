# 아이돌마스터2 한글 패치 작업 정리

작성일: 2026-10-12 (§17 이후: 2026-10-12 Claude 세션에서 갱신)

## 1. 프로젝트 / 기준 레포

- GitHub: https://github.com/cpprnppl/Imas2ToolS
- SCB 관련 레포: https://github.com/spiral6/idolmasterSCBParser

목표:
1. 게임 스크립트(SCB) 번역/패치
2. 한글 폰트 패치
3. MPC 복호화
4. MPC → NUT → DDS 텍스처 구조 처리
5. 텍스처 PNG export/import
6. 최종 게임 테스트

---

## 2. 주요 로컬 경로

### GitHub 작업 레포
```text
C:\Users\jackfilm\Documents\GitHub\Imas2ToolS
```

### 게임 resource 루트
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource
```

### SCB 리소스
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript
```

### SCB 작업 도구
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools
```

### imas2dec
```text
C:\Users\jackfilm\Documents\GitHub\Imas2ToolS\misc\imas2dec\imas2dec.exe
```

---

## 3. SCB 번역

Excel의 주요 열:

- B열: 원문
- C열: 번역문
- E열: 상대 파일 경로
- F열: 절대 오프셋
- G열: 원문 바이트 수

번역이 비어 있는 행은 원문을 유지하는 방향으로 작업한다.

### 번역 Excel 예시
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools\translation_1.xlsx
```

### 진행 로그
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools\translation_progress.txt
```

로그에는 번역 결과가 남지만 Excel 저장이 중간에 누락되는 문제가 있어 로그 기반 복구 스크립트를 별도로 사용했다.

---

## 4. Gemini 번역

무료 Gemini API로 약 4만 줄을 번역했고 이후 quota에 도달했다.

대표 오류:
```text
429 RESOURCE_EXHAUSTED
Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_requests
limit: 5
model: gemini-2.5-flash
```

남은 번역은 약 2천 줄 수준이었다.

번역 완료 후 검수 필요:
- 문장부호 누락
- 번역 오류
- 줄바꿈 제거
- 원문 형식 손실

---

## 5. Excel → SCB

주요 스크립트:
```text
C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools\excel2scb.py
```

방향:
1. Excel 로드
2. 번역문이 있는 행 패치
3. output 폴더에 원본 구조 유지
4. 원본 SCB는 덮어쓰지 않음

### 한글 폰트 매핑

한글은 게임 폰트에 직접 유니코드로 넣는 대신, 폰트에서 한글 글리프로 교체한 기존 한자 슬롯으로 치환한다.

예:
```json
{
  "가": "籀",
  "각": "籃",
  "간": "籌",
  "갈": "籏",
  "감": "籐",
  "강": "籑",
  "갛": "籔",
  "개": "籖",
  "객": "籘"
}
```

폰트 매핑은 약 2058개 문자.

---

## 6. 폰트

패치 대상:
- `font`
- `font_l`

`in2_font`는 별도 처리하지 않고 `font_l`과 같은 방향으로 가기로 했다.

### 문자셋

초성/중성/종성 개수 기반의 문자셋은 실제 사용 효율이 떨어져 폐기.

최종 방향:
- 표준 KS 완성형 2350자 사용
- 추가할 글자는 별도 입력
- 번역 완료 후 실제 필요한 한글을 추가 가능
- 모든 한자를 유지하지 않고, 필요한 한자와 멤버 이름 등은 유지

문자셋:
```text
korean_2350.txt
```

### 폰트 기본값
```text
Font: Noto Sans Medium
Font size: 26
Baseline: 20
X offset: 0
Row height: 29
```

슬라이더 변경값은 설정 파일에 저장.
기본값 리셋 버튼 제공.
이전 사용 NUT/NFH 원본 경로를 저장해 다음 실행 시 자동 로드.
`font_mapping.json`은 별도 경로를 받지 않고 선택한 폰트와 동일한 폴더에 자동 저장.

---

## 7. 폰트 관련 문제

NUT Viewer에서 DDS filesize가 이상하게 표시되는 문제가 있었다.

정상적인 기대값 대신:
```text
4294967295
```
등의 값이 표시되는 경우가 있었다.

`font`는:
```text
단일 이미지
2048 x 4096
```

게임이 두 폰트를 모두 사용할 가능성을 고려하여 둘 다 패치한다.

---

## 8. MPC 복호화

MPC 안에 NUT이 패킹되어 있고, NUT 안에 텍스처가 들어 있는 구조로 작업 중.

복호화 바이너리:
```text
C:\Users\jackfilm\Documents\GitHub\Imas2ToolS\misc\imas2dec\imas2dec.exe
```

### 자동 복호화 규칙

- 파일 시작 3바이트가 `pac`이면 이미 복호화된 것으로 보고 스킵
- 암호화된 MPC만 `imas2dec.exe` 실행
- 결과는 `원본.mpc.dec`
- `.dec` 생성 확인
- 원본 `.mpc` 제거
- `.dec`를 원래 `.mpc` 이름으로 변경
- 다음 파일 처리

imas2dec는 `Finished` 출력 후에도 프로세스가 종료되지 않는 문제가 있다.

또한 `.dec` 출력 위치 문제를 피하기 위해 실행 시 MPC가 있는 폴더를 CWD로 지정한다:

```python
subprocess.Popen(
    [IMAS2DEC_PATH, mpc_path],
    cwd=os.path.dirname(mpc_path)
)
```

전체 MPC 복호화는 완료했다.

---

## 9. MPC / NUT / 텍스처 구조

현재 목표 구조:

```text
MPC
 └─ NUT
     └─ DDS / texture payload
```

사용 레포:
```text
https://github.com/cpprnppl/Imas2ToolS
```

MPC 내부에 NUT이 패킹되는 구조를 레포 코드 기준으로 처리한다.

---

## 10. 텍스처 스캔 결과

복호화 전 스캔에서 확인된 대표 포맷:

```text
DXT5: 16
DXT3: 90
RAW: 9
```

대표 해상도:

```text
512x512   : 87
64x64     : 11
256x256   : 9
2048x4096 : 3
256x512   : 3
32x32     : 2
```

당시:
```text
errors: 173
```

복호화를 완료했으므로 다시 스캔하여 오류가 감소했는지 확인해야 한다.

---

## 11. 텍스처 작업 목표

목적:
- UI 한글화
- 필요한 인게임 이미지 한글화
- 원래 폴더 구조 유지
- MPC → NUT → PNG export
- PNG 수정
- PNG → NUT → MPC import

작업 흐름:
```text
게임 resource
    ↓
MPC
    ↓
NUT
    ↓
PNG export
    ↓
그래픽 수정
    ↓
PNG import
    ↓
NUT
    ↓
MPC
    ↓
게임
```

---

## 12. texpack.py

예정 위치:
```text
C:\Users\jackfilm\Documents\GitHub\Imas2ToolS\tools\texpack.py
```

명령:
```bat
python tools\texpack.py scan <ROOT_DIR> <OUT_JSON>
python tools\texpack.py export <ROOT_DIR> <OUT_DIR>
python tools\texpack.py import <ROOT_DIR> <IN_DIR>
```

### scan
MPC 전체를 순회하여 NUT, 텍스처 포맷, 해상도, 오류를 확인.

### export
예상 구조:
```text
export_png/
└─ 상대경로/
   └─ mpc이름/
      └─ nut이름/
         ├─ manifest.json
         ├─ 000_512x512_DXT3.png
         ├─ 001_512x512_DXT3.png
         └─ ...
```

manifest에는 index, PNG 이름, 포맷, width, height, NUT offset, payload size 등의 정보를 기록.

### import
manifest 기준으로 PNG를 원래 NUT payload 위치에 다시 넣는다.

payload 크기가 원본과 맞지 않으면 오류 처리한다.

---

## 13. 확인된 텍스처 포맷

현재 확인:
```text
DXT3
DXT5
RAW
```

DXT1은 현재 스캔 결과에서 확인되지 않았지만 향후 발견될 수 있으므로 고려 가능.

NUT Viewer가 `4294967295` 같은 잘못된 filesize를 표시할 수 있으므로 Viewer 값만 신뢰하지 않는다.

DXT3/DXT5의 실제 payload 크기는 4x4 블록 기준으로 계산한다.

---

## 14. 현재 상태

### 완료
- [x] 게임 리소스 구조 조사
- [x] SCB 번역/패치 구조 구축
- [x] 한글 폰트 패치
- [x] 한글 → 한자 슬롯 매핑
- [x] Excel → SCB 한글 매핑
- [x] MPC 복호화 자동화
- [x] 이미 복호화된 PAC MPC 스킵
- [x] `.dec` → 원래 `.mpc` 교체
- [x] 전체 MPC 복호화
- [x] 텍스처 포맷/해상도 스캔
- [x] MPC 안에 NUT이 패킹되는 구조 확인

### 진행 중
- [ ] texpack.py 실제 레포 parser와 연결/검증
- [ ] resource 전체 재스캔
- [ ] DXT3 export 검증
- [ ] DXT5 export 검증
- [ ] RAW export 검증
- [ ] PNG → NUT import
- [ ] 게임 round-trip 테스트
- [ ] 잔여 번역
- [ ] 번역문 검수
- [ ] 문장부호/줄바꿈 검수
- [ ] 최종 게임 테스트

---

## 15. 다음 작업 순서

1. `texpack.py`로 resource 전체 scan
2. 오류 목록 확인
3. 대표 MPC 하나 export
4. DXT3 PNG 확인
5. DXT5 PNG 확인
6. RAW PNG 확인
7. PNG 하나 수정
8. import
9. 게임에서 해당 텍스처 확인
10. round-trip 성공 후 전체 배치

처음부터 전체 텍스처를 수정하지 않고, **한 개 텍스처의 export → 수정 → import → 게임 확인**을 먼저 통과시키는 것을 우선한다.

---

## 16. 핵심 작업 원칙

- 원본 파일은 가능하면 직접 덮어쓰지 않는다.
- 복호화 전 원본은 백업한다.
- SCB는 output 폴더에 별도 생성한다.
- 텍스처 import도 원본 MPC 백업을 유지한다.
- NUT Viewer의 비정상 filesize는 실제 payload 구조와 분리하여 판단한다.
- 폰트는 `font`, `font_l`을 모두 패치한다.
- 한글은 font mapping을 통해 게임 폰트의 기존 문자 슬롯으로 치환한다.
- 번역 완료 후 실제 사용된 한글/필요 한자를 기준으로 폰트를 추가 조정한다.

---

# 17. 2026-10-12 세션: "번역 넣으면 게임이 이상해지는" 문제 해결

## 17.1 원인 규명

게임이 깨진 직접 원인은 **구버전 in-place 패처(`patch_text_entry`/`expand_text_entry`)가 만든
손상된 SCB**였다. 증상(화자 ???, 대사 잘림/빈 대사, 음성 사라짐, 컷씬 멈춤, 크래시)은 전부 이것.

핵심 사실 (전체 1183개 원본 SCB 스캔으로 검증):

- MSG 본문 base는 `msg_abs + 0x30 + count*8 + pad16` (spiral6 scb.ksy 방식)이 **전 파일에서 정확**.
- 구버전 `parse_msg_strings_stream`의 고정 base `msg_abs + 0x60`은 **틀렸다**
  (count≠5~6이면 테이블 한복판을 텍스트로 읽음). 이 때문에:
  - Excel 추출 시 각 파일의 **첫 문자열 abs_offset이 틀어짐** (테이블 쓰레기와 병합)
  - 본문 마지막 `count*8+pad-0x30` 바이트 구간의 문자열은 **아예 추출 누락** (영구 미번역분)
- 전 파일에서 **엔트리당 문자열 1개** (멀티 문자열 엔트리 없음) → 테이블 리빌드 안전.
- MSG 내부 크기 필드: `+0x08(u4)` = 섹션크기-32 (1182/1183; `mam_w01_01`만 +16 특이),
  `+36(u4)` = 대사 총 바이트 (상위 2바이트 전 파일 0).
- 원본 대사에 `\n`(0x0A) 개행 정상 사용 → 번역문의 `\n` 그대로 OK.
- 암호화 round-trip 검증 통과 (재암호화 시 첫 16바이트 prefix 블록 차이는 복호화 시 버려져 무해).

## 17.2 excel2scb.py 수정 내용

1. `+0x08` 내부 크기 필드를 delta 방식으로 갱신 (기존: 미갱신 → stale)
2. 대사 총 바이트를 `+36`에 **u4**로 기록 (기존: u2 마스킹)
3. abs_offset 매칭 실패 시 **원문 텍스트(B열) 유일 매칭 fallback** 추가
   → 구버전 추출기가 틀어놓은 "파일당 첫 줄" 구제
4. 원본 SCB를 항상 순정 백업 `USRDIR\gscript - 복사본`에서 읽도록 변경 (`ORIG_DIR`)
   → 패치본을 재패치하는 오염 사고 원천 차단

## 17.3 오염 복구

- 게임 폴더의 4개 파일이 과거 패치로 오염돼 있었음
  (`ami_liv_01_guest`, `ami_liv_02_guest`, `ami_w01_03`, `mam_w01_01`)
  → `gscript - 복사본`에서 순정으로 복원 완료. 나머지 1179개는 백업과 바이트 일치 확인.
- 깨진 구버전 산출물은 `tools\output_old_broken_20260302`로 격리.

## 17.4 재패치 및 배포

- 수정된 excel2scb.py로 1121개 파일 전체 재생성.
- 전수 검증: 구조 문제 **0건** (테이블/본문 정합, 널 종단, 크기 필드, 섹션 경계 모두 통과).
- output을 게임 폴더 `resource\gscript`에 배포 완료 → **게임 테스트 대기**.

## 17.5 크래시 2차 원인: pac 컨테이너 헤더 (해결)

1차 배포 후 인게임에서 무음성 대사 2줄은 정상 출력됐으나 **음성+컷씬 대사 직전에
`VM: Access violation reading 0xff0ce4bf` 크래시**.

원인: dec 파일은 SCB 단독이 아니라 **`pac` 컨테이너** (전 1183파일 공통, 서브파일 2개):

```text
pac 헤더 (0x00~0x80)
 ├─ +0x08 : 전체 콘텐츠 크기 (dec_len - 0x80)
 ├─ +0x0C : 서브파일 수 (항상 2)
 └─ +0x40 + i*0x20 : 서브파일 레코드 (+8=크기, +12=오프셋)
서브파일 0 (오프셋 0) = SCB 블록 (스크립트; 0x88에 자체크기-32 필드)
서브파일 1             = 컷씬/모션 데이터 pac (중첩 pac)
```

MSG가 커져도 pac 헤더를 안 고치면 **대사(MSG)는 정상 출력되지만 게임이 서브파일 1
(컷씬/음성 데이터)을 옛 오프셋으로 읽는 순간 크래시**. excel2scb.py의
`replace_msg_section`에 4개 필드 갱신 추가(+0x08, +0x88, rec0 size, rec1 offset),
전수 재생성·검증(불변 체크 포함 0건)·재배포 완료.

## 17.6 AI-native SDLC 플레이북 반영 (2026-10-12)

[플레이북](https://claude.com/ko/resources/articles/the-ai-native-sdlc-playbook) 제안을 1인 규모에 맞게 적용:
- `CLAUDE.md` 신설 — 명령, 절대 규칙, 자주 틀리는 부분 (같은 실수 2번 금지 원칙의 저장소)
- `docs/PIPELINE.md` — 단계별 산출물·게이트 정의, 반영 안 한 항목과 이유
- SCB 도구를 레포 `tools/scb/`로 버전 관리 (단일 원천), `sync_to_game.py`로 게임 폴더 배포
- `validate_output.py` + `deploy.py` — 검증 통과 시에만 배포되는 자동 게이트
- `.claude/` 훅 — 순정 백업 폴더('gscript - 복사본') 쓰기 차단 가드레일

## 17.7 남은 이슈

- [ ] **게임 실기 테스트** (mam_w01_01 = W01 시작 씬이 대표 테스트 지점)
- [ ] 폰트 매핑에 없는 한글 6종: 큿(32) 큥(10) 햣(8) 쌰(5) 겍(2) 츗(1) — 총 58회, 41개 파일.
      게임에선 해당 글자만 빈 글리프. 폰트에 6자 추가하거나 번역문 수정으로 해결.
- [ ] 구버전 추출기가 누락한 "본문 끝부분 문자열" (파일당 0~수 줄): 올바른 base로
      재추출해서 기존 Excel에 **추가 행만 병합**하면 번역 가능 (기존 번역 보존).
- [ ] 매핑 대상 한자 일부가 원본 일본어 대사에도 등장 → 미번역 일본어 줄에서 해당 한자가
      한글 글리프로 보일 수 있음. 전량 번역되면 자연 해소; 신경 쓰이면 충돌 한자를
      진짜 미사용 한자로 매핑 교체.
- [ ] RPCS3 랜덤 기동 실패: 로그상 치명 단서 없음(세이브데이터/NP 관련 무해 에러뿐,
      rsx::thread 스톨 흔적). 별도 조사 필요 (빌드 업데이트, PPU/셰이더 캐시 삭제 시도 등).
