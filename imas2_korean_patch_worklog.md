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

## 17.7 인게임 확인 + 재줄바꿈/쓰레기 번역 가드 (2026-10-12)

**인게임 테스트 통과**: pac 헤더 수정 후 부팅 다수 회 정상, 씬 진행 정상, 한글 출력 정상.

남은 표시 문제였던 개행 깨짐("아이/돌들은" 어절 쪼개짐, 뒷글자 잘림) 해결:
- 원본 일본어 전수 측정: 대사창 = **전각 26자 × 2줄** (전 대사 1~2줄, 줄당 ≤25~26전각)
- excel2scb에 `rewrap()` 추가: 번역문의 기존 \n을 풀고(어절 중간 분리 복원 휴리스틱:
  앞말 '이' 종결·단음절 조사 어미는 붙임) 폭 26 기준 공백 단위 재줄바꿈
- `is_garbage_translation()` 가드: LLM 사고과정 유출/미번역 영문 행(15행)은 패치 스킵
- 문제 행 전수 보고서: `docs/retranslate_needed.md` (쓰레기 15행 + 3줄 초과 11행 = 26행,
  `tools/scb/report_issues.py`로 재생성 가능) — **재번역/축약 작업 목록**
- 전체 재생성 → 검증 게이트 통과 → 배포 완료

## 17.8 rewrap v3 + translation_2 전환 (2026-10-12)

- rewrap v3: 2줄 분할 시 문장부호 뒤·중앙 균형 지점 선택(구 중간 절단 제거),
  \n 접합부 공백 누락은 Kiwi 형태소 분석으로 복원(접합 지점 한정, 기존 띄어쓰기 불변)
- **미완성 번역 834행 발견**: 원문은 」로 닫히는데 번역이 중간에 끊긴 행
  (Gemini가 둘째 문장 누락, 예: "모두들 아주 기대하고 있으니,"). 전부
  `docs/retranslate_needed.md` §2에 기록 — **일괄 재번역 필요**
- translation_2.xlsx(재추출판: 오프셋 교정 + 신규 미번역 6,121행) 전환:
  excel2scb 최우선 로드, 46,119대사 패치, 매칭 실패 0, 검증·배포 완료

## 17.9 남은 이슈

- [ ] **게임 실기 테스트** (mam_w01_01 = W01 시작 씬이 대표 테스트 지점)
- [x] 폰트 매핑에 없는 한글 6종: 큿(32) 큥(10) 햣(8) 쌰(5) 겍(2) 츗(1) — §18에서 폰트에
      6자 추가(睆睇睚睛睜睟 슬롯), 매핑 2,359자로 갱신. SCB는 excel2scb 재실행 시 반영됨.
- [ ] 구버전 추출기가 누락한 "본문 끝부분 문자열" (파일당 0~수 줄): 올바른 base로
      재추출해서 기존 Excel에 **추가 행만 병합**하면 번역 가능 (기존 번역 보존).
- [ ] 매핑 대상 한자 일부가 원본 일본어 대사에도 등장 → 미번역 일본어 줄에서 해당 한자가
      한글 글리프로 보일 수 있음. 전량 번역되면 자연 해소; 신경 쓰이면 충돌 한자를
      진짜 미사용 한자로 매핑 교체.
- [ ] RPCS3 랜덤 기동 실패: 로그상 치명 단서 없음(세이브데이터/NP 관련 무해 에러뿐,
      rsx::thread 스톨 흔적). 별도 조사 필요 (빌드 업데이트, PPU/셰이더 캐시 삭제 시도 등).

## 18. 폰트 아틀라스 품질 재작업 (2026-10-12)

인게임 증상: ① 일부 글리프 잘림('세'→'서'처럼 보임, "구세주"→"구 서주"), ② 글자
위/아래 검은 픽셀 혼입, ③ 문장부호 품질 저조 — 원인 규명 후 `font_patcher/repatch_fonts.py`
(CLI)로 font/font_l 재생성·배포.

### NFH 레코드 구조 확정 (중국팀 BLJS10083 패치 역분석으로 검증)

레코드 32B big-endian:

| 오프셋 | 의미 |
|---|---|
| +0/+2 | 아틀라스 x, y (잉크 좌상단) |
| +4 | bearingX<<6 |
| +6 | **bearingY<<6** (베이스라인→잉크 상단) — 구 패처가 여기에 advance를 잘못 씀 |
| +8 | **advance<<6** — 구 패처 미갱신(한자 27px 그대로) |
| +10 | -(rect폭/2)<<6 (하프스케일 센터링) |
| +12 | 상단갭/2<<6 | +14 | em(27)<<6 |
| +16 | **(rect폭<<8)\|높이** — 게임이 아틀라스에서 샘플링하는 사각형. 구 패처 미갱신 |
| +18 | code (UTF-16) | +28 | gidx (시트 번호) |

### 증상의 근본 원인

1. **글리프 잘림**: +16 샘플 폭이 원본 한자 값 그대로 → 좁은 한자 슬롯('세'→訁 rect
   14×25, bearingX 7)에선 한글(폭 22)의 오른쪽이 잘리고 bearingX만큼 밀림.
   폭 부족 슬롯 39개, 아틀라스 피치 자체가 부족한 슬롯 im2_font 7개.
2. **상하 픽셀 혼입**: size 26/baseline 20 렌더 시 Noto 어센더(22px)가 셀 위로 2px
   침범(행 피치 27~28). 셀 경계 클리핑도 없었음.
3. **im2_font_l은 통째로 어긋나 있었음**: NUT 레이아웃이 "80B 텍스처 헤더 29개 연속
   (0x10+80i) + 픽셀 데이터 0x920부터 시트별 262144B 연속"인데, 구 패처는
   고정 스트라이드(16+262224i+80)로 읽고 써서 전 시트가 수백 px씩 어긋남.
   (인게임 한글이 그나마 보였던 건 im2_font 덕분)

### repatch 방식 (중국팀과 동일한 균일 셀)

- 순정 백업(`USRDIR\_backup\im2_font*_2026…`, MD5 고정 검증)에서만 읽음
- 타깃 슬롯: 원본 한자 rect+1px(AA 잔픽셀) 클리어 → (x,y) 기준 25×25 셀에 Noto size 26,
  셀 내 베이스라인 y+22로 렌더(셀 밖 클리핑) → +4=0, +6=22<<6, +8=Noto advance,
  +10=-13<<6, +12=0, +16=25<<8|25 갱신
- 이웃 rect와 겹치는 슬롯은 점유 마스크 기반으로 빈 영역 재배치(x,y,gidx 갱신):
  im2_font 7자(괘돋뺑세쌉챈쿰), font_l 10자. 축소 0자
- 매핑에 없던 6자(큿큥햣쌰겍츗)를 희생 풀 직전 6슬롯(睆睇睚睛睜睟)에 추가 → 매핑 2,359자
- 문장부호(、。…「」！？ 등)는 매핑 대상이 아니라 원본 Rodin 글리프 그대로 사용 — 품질
  문제는 렌더 잘림/혼입이 원인이었고 별도 교체 불필요. (번역문의 반각 '~' 2,991회,
  '·' 192회는 SCB 쪽에서 '～'/'・' 정규화 권장)

### 도구/게이트 (레포 font_patcher/)

```
python repatch_fonts.py    # 순정→output/ 재생성 (+ font_mapping_v2.json 2,359자)
python validate_fonts.py   # 전수 검증: 비타깃 레코드/픽셀 불변, 신규 rect 겹침 0, 타깃 잉크 존재
python qa_render.py        # 게임 방식 시뮬레이션 렌더 → output/qa_*.png
python deploy_fonts.py     # 검증 게이트 통과 시: 백업 → loose 교체 + MPC 주입 + 매핑 동기화
```

- 배포 = loose(resource\im2_font*) + **initialFix.mpc(NFH×2)·initialTemp.mpc(NUT×2) 주입**
  (시그니처 탐색, NFH는 폰트명 'Pro DB'로 font_l 식별)
- 배포 전 상태 백업: `resource\_backup_fontfix_20261012_054216\`
- 매핑 2,359자를 tools\font_mapping.json·resource\im2_font_mapping.json에 동기화 —
  **다음 excel2scb 실행부터 큿큥햣쌰겍츗 인코딩됨**
- 남은 확인: 인게임 스크린샷으로 잘림/혼입 해소 확인 (사용자)

---

## 19. UI 이미지 텍스트 추출 패키지 (2026-10-12)

메뉴·UI·튜토리얼에 비트맵으로 박힌 일본어를 PNG로 추출해 이미지 작업자에게 넘길
패키지 생성. 도구: `tools/image_text/extract_image_text.py` (README 참조).

### 인벤토리/결과

- 대상 = 중국팀 패치(`Desktop\偶像大师2汉化补丁\games\...\resource`)에서
  gscript/·initialFix·initialTemp 제외 전 56파일. JP 원본은 NPJB00337 동일 상대경로.
- 산출: `Desktop\imas2_image_text\` — jp/(작업 대상)·cn_ref/(중국어 참고)·
  _review/(JP|CN 비교 시트)·index.md/json.
- **JP 텍스처 4,758장 중 CN 수정(=payload md5 상이=텍스트 있는) 505장, 유니크 333장.**
  같은 라벨 세트가 여러 pac에 중복(도도부현 라벨 5개 pac, お守りINFO류 4개 pac 등).

### 포맷 지식 (실측 확정)

- NUT 두 레이아웃: ver=0x0100 → `[80B 헤더][데이터]` 인터리브,
  ver=0x0200 → 헤더 연속(16+80i) 후 데이터 연속(폰트 NUT와 동일). 마커 eXt/GIDX 검증.
- 텍스처 fmt(+0x13): 0=DXT1, 1=DXT3, 2=DXT5, 6=RGB565(BE), 7=ARGB4444(BE),
  14/17=ARGB8888(BE). DXT 블록 내부는 표준 LE. 모두 디코드 검증 완료(잔여 오류 0).
- 암호화 파일(.s2d/.nut/.tsk/.xmb)은 평문보다 +80B. imas2dec로 사본만 복호화
  (게임 원본 불변). `.s2d`=TSK 컨테이너, 그 안에 NUT.
- pac 엔트리 테이블 대신 NTP3 시그니처 카빙이 신뢰됨 (워크로그 §8·브리핑 방침 유지).

### 비이미지(텍스트) 후속 과제 — 이미지 작업 범위 아님

- `text/install.xmb`·`scene/exep_init.mpc`(내부 XMB)·`ranker/ranker_npc.xmb`:
  XMB 텍스트 테이블(설치/트로피 메시지, ジュピター 소개, NPC 유닛명).
- `scene/attract.mpc`: **gscript 밖 SCB 2개** 내장 — excel2scb 파이프라인 미커버.
- `game/les_mar.mpc`·`scene/saveLoad.mpc`: CN이 포함했지만 텍스처 차이 0 —
  비텍스처 데이터 수정으로 추정.

### 재주입(다음 단계) 방침

같은 포맷·같은 크기로 재인코딩해 index.json의 data_off에 제자리 덮어쓰기(크기 불변,
pac 헤더 갱신 불필요). 중국팀은 암호화 파일을 전부 복호화 상태로 배포 — 평문 교체가
통하는 것으로 보이나 인게임 1회 검증 후 전체 적용. 치수 변경 금지(배치 좌표 외부).

## 20. scene/attract.mpc 내장 SCB 패치 (2026-10-12, scb-excel 세션)

어트랙트(타이틀 방치) 데모가 gscript 밖 `scene/attract.mpc`에 대사 SCB 사본을
내장하고 있어 excel2scb 파이프라인이 커버하지 못하던 건 처리 (워크로그 §19 후속 과제).

### 구조 (실측 확정)
- `attract.mpc` = 평문 pac (암호화·AES 푸터 없음). 서브파일 2개 = **순정
  `dec(all/all_dem_01.scb)`·`dec(all/all_dem_02.scb)`와 바이트 동일**한 내부 pac.
- 레이아웃: 헤더+MSG 매니페스트(파일명표, 크기 참조 없음) 0x000~0x11F, 데이터 베이스
  0x120, 각 서브파일 뒤 16B 제로 패딩. 크기 참조는 `+0x08`(서브파일 크기 합),
  rec0.size(+0x48), rec1.size(+0x68), rec1.ofs(+0x6C) **4곳뿐** (0x140까지 전수 스캔).

### 도구: `tools/scb/patch_attract.py`
- 순정 SCB → excel2scb와 **동일 코드 경로**(translation_2 로드·rewrap·테이블 리빌드·
  내부 pac 헤더 4필드 갱신)로 패치 dec 생성 → 외곽 pac 재조립(위 4필드 갱신).
- 최초 실행 시 live가 순정인지(내장==순정 dec) 검증 후 `attract.mpc.orig` 백업 생성,
  이후 항상 .orig에서 읽음(재패치 오염 방지). 내장 검증 게이트(외곽 invariant,
  MSG count/문자열 일치, 컷씬 pac 보존) 통과 시에만 `tools/output_scene/`에 저장,
  배포는 `--deploy`로만.
- 교차 검증: 내장 패치 dec == 당일 메인 파이프라인 산출 `tools/output/all/all_dem_01·02.scb`의
  dec와 바이트 동일. 적용 7/8 + 4/4줄 (all_dem_01 index7은 신규추출 미번역 행 —
  번역 후 재실행하면 반영).
- **배포는 보류** — 게임 폴더 배포는 메인 세션 전담 규칙. `output_scene/attract.mpc`
  준비 완료, `python patch_attract.py --deploy`만 남음.

---

## 21. 이미지 재주입 파이프라인 + XMB 텍스트 도구 (2026-10-12, §19 후속)

### inject_image_text.py — 한글 PNG → 텍스처 제자리 주입

- 인코더: DXT1/3/5(range-fit + 최소자승 끝점 정제 2회 — fan_letter 무지개 봉투
  26.6dB→통과), RGB565/ARGB4444/ARGB8888(무손실). 크기·치수·포맷 불변.
- 검증 게이트: ① 파일 크기·주입영역 밖 바이트 불변 ② NUT 재파싱 구조 일치
  ③ 재디코드 vs 입력 PNG(무손실 포맷 완전일치, DXT PSNR≥33dB).
- `--selftest` = CN 수정 텍스처 505장 전량 주입: **50/50 파일 통과**
  (DXT 36.8~61dB). 입력은 `<out>/kr/`, 산출은 `<out>/patched/` — 게임 폴더 배포는
  수동 + 평문 교체(구 암호화 파일) 인게임 1회 검증 먼저.

### xmb_text.py — XMB 텍스트 테이블 (dump/build)

- XMB 구조 확정: 헤더(+4 node/attr/name/id count, +0x14 섹션 ofs×6), 노드 16B
  (nameOfs u32, attrCount/childCount/firstAttr/firstChild/parent u16), 속성 8B
  (nameOfs, valueOfs), 값 섹션 = id ASCII + _text UTF-16BE, id 정렬 색인(바이너리 서치).
- 물량: install.xmb 23(시스템 메시지) / ranker_npc.xmb 5(NPC 유닛명) /
  exep_init.mpc 내장 XMB **1,002**(NPCP 200·NPCU 200·NPCS 601·PROD 1, JP≠CN 867).
- **CN 패치의 XMB 텍스트가 매핑 한자 인코딩으로 저장돼 있음** → XMB도 게임 폰트
  렌더 확정, build는 기본으로 font_mapping(2,359자) 인코딩 적용.
- build 게이트: 파일 크기 불변(값 섹션 초과 시 오류, pac 내장은 세그먼트만 교체),
  재파싱으로 교체 텍스트/id/구조 검증. install 22건·ranker 4건 한국어 제안 기입
  (매핑 미보유 한글 0자) → patched/ 산출 확인.
- 번역 워크플로(사용자 지시: 팀원이 엑셀로 번역): `export-xlsx` →
  게임 tools `xmb_translation_1.xlsx`(1,030행·3시트, 제안 행 노란색) → KR 열 작성 →
  `import-xlsx` → `build`. 고유명사는 통용 표기(나무위키 확인): 아마가세 토우마·
  미타라이 쇼타·**이쥬인 호쿠토**(이주인 아님)·주피터. 반각 '.'은 관례 미확정 —
  인게임 확인 시 체크.

---

## 22. 협업 도구 2종 (2026-10-12, 사용자 제안)

### XMB 번역 협업 웹앱 (팀 공유)

- https://claude.ai/artifact/Y4sPGWzDHu4JfGigo8Bwc5 — 1,030행 내장 + 공유 DB.
  행별 한국어 입력, [번역]→[검수] 단계 체크, 경고(미번역/개행 수 불일치/길이/
  **폰트 매핑 2,359자에 없는 글자** 하이라이트), 파일별 값 섹션 **용량 미터**
  (UTF-16 바이트, 초과 시 빨강 = build가 거부할 상태를 사전 표시).
- 데이터 흐름: 페이지 내장 JP/CN/KR제안(정적) + 아티팩트 DB `tr` 컬렉션(수정분).
  회수는 Claude가 DB를 읽어 xmb_translations.json 반영 → build. 엑셀은 스냅샷
  경로로 유지. 재생성: `webapp_build.py`(값 섹션 예산 자동 계산) + webapp_template.html.
- 편집엔 claude.ai 로그인 + 아티팩트 공유의 편집 권한 필요 (DB rules:
  읽기 view / 쓰기 interact).

### 운영 전환: imas2.buyeo.uk (Vercel + Supabase, 2026-10-12)

- 아티팩트 → **Vercel 정적 배포**(GitHub import, Root=tools/image_text/webapp_deploy,
  도메인 imas2.buyeo.uk) + **Supabase**(프로젝트 ukjckfajjpntqwfwguce, rows/hist,
  RLS 팀 암호 — supabase_setup.sql, 암호는 디스코드 공지)로 전환. guger.buyeo.uk와
  동일 패턴. 푸시 = 자동 재배포.
- UI는 PatternFly 5. 시딩 53,603행 + 텍스처 썸네일 666장(storage tex 버킷 공개).
- 라이브 검증: 입장(오답 거부)·그룹 로드(chi 5,427행/1.2초)·저장→hist 기록·
  썸네일 표시. 수정한 버그: [hidden] 리셋 누락(입장해도 게이트 잔류),
  좁은 화면 사이드바 토글 클래스, 사이드바 목록 잘림(overflow).
- 스프레드시트 UX: 편집 중 Enter/Tab=저장 후 다음 행(Shift+Enter 줄바꿈,
  Alt+↑↓ 이동, Esc 취소), **찾아 바꾸기**(현재 그룹 한국어 열, 미리보기→일괄,
  행별 이력 기록). 이미지 텍스트는 CN 열 제거.

### 웹앱 반복 개선 (2026-10-12, 사용자 피드백 라운드)

- **홈 = 진행 현황 대시보드**: 대분류 합계 + 소분류별 번역/검수 진행바
  (count 쿼리 집계·캐시, "새로 집계"), 소분류 클릭 이동. 표는 colgroup 고정
  폭 + 숫자 우측정렬(tabular)로 정렬 수리.
- **카테고리별 필터 + 건수**: 텍스트 = 전체/미번역/번역됨(검수 대기)/검수
  완료/경고. 이미지 = 전체/문구 미정/번역됨(식질 대기)/**식질됨**(작업본
  있음·검수 대기)/검수 완료/경고. 각 옵션에 해당 건수 표시.
- **이미지 작업본 업로드**: 행별 버튼 + **일괄 다운로드/업로드 모달**.
  다운로드 = 분류 체크박스 → 원본(+선택 시 작업본) ZIP + manifest.csv,
  파일명 `이름__<md5>.png`가 매칭 키. 업로드 = PNG 여러 개/ZIP, md5 자동
  매칭 + **치수 자동 검증**(불일치 거부), 건별 로그. 저장소는 Supabase
  `tex_kr` 테이블(base64, 팀 암호 RLS — delete 정책 없음).
  목록에 원본·작업본 나란히(작업자명), 뷰어에서 둘 다 확대.
- **이미지 뷰어**: 썸네일 클릭 → 1×/2×/4× 확대(픽셀 보존, 체커보드).
  캔버스 근사 미리보기는 오해 소지로 **제거**(정확한 렌더는 label_tool 전담).
  스토리지 썸네일을 480px 축소본 → **원본 해상도로 재업로드**(666장).
- **개행 가시화**: 원문/번역 셀의 개행 위치에 ↵ 마커, 편집 중 "개행 n/m"
  실시간 카운터(불일치 빨강), 경고 문구 "개행 수 다름 (KR n · JP m)".
- 기타: 찾아 바꾸기 미리보기를 표+하이라이트(삭제=빨강 취소선/추가=초록)로,
  검색이 이미지 위치 경로·스크립트 파일명 포함, 활동 뷰 위치 클릭 이동,
  작업자 이름 미입력 시 편집/체크/업로드 차단, `/` = 검색 포커스,
  이미지 상태 버튼 "번역"→"문구".
- **회수 연결**: `webapp_pull.py image`가 tex_kr 작업본을 내려받아 같은 md5의
  모든 위치 kr/ PNG로 복제 → inject 게이트 직결 (E2E 검증: 업로드 1건 →
  5위치 저장). xmb/script 회수도 rows 스키마 기준으로 갱신.

### 이미지 라벨 툴 (label_tool.py, 로컬)

- CN 수정 텍스처 505장을 md5 그룹 333개로 중복 제거해 목록화. 텍스트+프리셋
  스타일(폰트/크기/채움/외곽선/글로우/자간/정렬/자동 맞춤) 지정 → JP/CN/KR
  나란히 실시간 미리보기. 미리보기=내보내기 동일 PIL 렌더러(WYSIWYG).
- 내보내기: 그룹당 1회 렌더 → 같은 md5 전 위치에 PNG 복제(kr/) → inject 게이트.
- 체인 검증: 東京 라벨(5개 pac 공유)에 '도쿄' 렌더 → 5파일 주입 게이트 통과
  (DXT5 39.5dB). 스펙은 label_specs.json(레포)에 저장 — 작업 상태의 원본.
- **다중 영역 모드**(큰 이미지·복수 텍스트용): JP 미리보기에서 드래그로 영역
  추가, 영역별 문구/크기/바탕 덮기. 배경은 clean/<md5>.png(클린 플레이트) 우선,
  없으면 JP 원본 위 합성 — 평평한 배경은 바탕색으로 원문 글자를 덮는다.
  복잡한 배경만 클린 플레이트 1회 포토샵 필요, 이후 문구 수정은 전자동.
- 전면 안내판류 중 합성 불가한 것만 모드 '수동(포토샵)' 지정 → kr/ 직접 투입.

## 23. 문장부호 Noto 재렌더 + 한글 직접 등록 타당성 조사 (2026-10-14)

### 문장부호 베이스라인 수정 (사용자 리포트)

인게임에서 한글(Noto)과 문장부호(원본 Rodin)의 아랫선이 어긋나 보이는 문제.
측정 결과 한글/한자 본체 메트릭은 1px 내 정합이지만, 약물류는 두 폰트의 글리프
디자인 위치가 2~5px 다름(예: 、 Rodin by4/h6 vs Noto by7/h9, ！는 Rodin이 기울임체).

수정: `、。，．！？…‥「」『』～ー・：；（）` 19자를 **자기 슬롯에 코드 유지한 채
Noto로 재렌더**(매핑·SCB 무관, repatch_fonts의 PUNCT_RERENDER). 렌더 대상
2,378자(매핑 2,359 + 문장부호 19), 전수 검증 PASS, font/font_l 재생성·배포 완료.
배포 전 상태 백업: `resource\_backup_fontfix_20261014_135916\`.
미번역 일본어 줄도 이 19자는 Noto 모양으로 보임(형태 차이 미미).
남은 후보(미적용): 전각 영숫자 ０-９Ａ-Ｚ도 Rodin 그대로라 혼용 시 스타일 차이
있음 — 필요 시 PUNCT_RERENDER에 추가만 하면 됨.

### 한글 코드포인트 직접 등록(매핑 치환 폐지) 타당성 — 결론: 실험 필요(가능성 높음)

조사 근거:
- SCB 텍스트는 **UTF-16BE** → 한글 코드포인트(AC00~) 저장 자체는 문제없음.
- NFH 9,802 레코드의 code 필드는 **순증가 정렬**(0001..FFE5) → 탐색 기반 룩업 추정.
- **NFH 헤더 +0x50에 256엔트리 u32 상위바이트 버킷 테이블** 발견: 값 = 해당
  상위바이트의 첫 레코드 인덱스+1, 없으면 0x80000001. CJK 구간은 실측과 정확히
  일치, 기호 구간 80개는 불일치(게임이 버킷을 힌트로만 쓰거나 일부 구간 미사용
  추정). 한글 상위바이트(0xAC~0xD7)는 현재 전부 '없음'.
- 미확정: 게임 룩업이 (a) 전체 이진탐색이면 재정렬+버킷 갱신으로 충분, (b) 버킷
  +선형탐색이면 역시 가능, (c) EBOOT에 코드 범위 하드코딩이 있으면 불가.
  데이터만으로는 (c)를 배제 못 함.

실험 계획(약 1~2시간, 사용자 승인 후):
1. 테스트 폰트: 희생 레코드 1개의 code를 U+AC00(가)으로 바꾸고 레코드 배열
   재정렬 + 버킷 테이블 재생성 → 배포.
2. SCB 한 줄에 매핑 미적용 원시 '가'(AC00)를 넣어 인게임 표시 확인.
3. 성공 시 전환: 2,359 레코드 code를 한글로 교체(+정렬+버킷), excel2scb에서
   font_mapping 치환 제거.

전환 시 트레이드오프: 희생 한자 코드가 폰트에서 사라져 **미번역 일본어 줄의 해당
한자가 "한글 글리프"가 아니라 "빈 글리프"가 됨**(현 상태는 한글로 보임). 전량
번역 완료 후에는 무관. 레코드 "추가"(한자 유지+한글 추가)는 아틀라스 빈 공간이
~1,478셀뿐이라 2,359자 전체는 불가.

360판(imas2pc)은 동일 NFH를 쓰므로 리컴파일 출력에서 글리프 룩업 함수를 찾으면
(a)/(b)/(c)를 정적으로 확정할 수 있음 — imas2pc 세션에 조회 요청 가능.

### §23 후속: 360판 리컴프 정적 분석 결과 (imas2pc 세션, 2026-10-14)

글리프 룩업 = **(b) 버킷 + 이분 탐색 — 코드 범위 하드코딩 없음** (조회 sub_823470C0,
호출 vtable 0x820D56EC+120의 sub_822A3ED8, 로더 sub_82281C30).

게임 기준 레이아웃 교정 (폰트팀 원점 0x474와 4바이트·인덱스 1 차이, 같은 바이트):
- 레코드 i = 0x450+32i, i=0..9803 (헤더 +8 = 0x264C = 9804개, rec0 = U+0000)
- 코드 = rec+22/+23 (상·하위 바이트), **rec+24 = i−그룹시작, rec+25 = 그룹끝−i**
  (하위 바이트 이분 탐색 범위를 정하는 u8 쌍 — 폰트팀 프레이밍의 +20/+21)
- 버킷 공식: bucket[h] = 그룹 첫 레코드 인덱스 − 첫 코드의 하위 바이트, 없으면
  0x80000001. PS3 nfh 2개 전수 검증 불일치 0 ("첫 인덱스+1" 가설은 우연 일치였음)

한글 직접 등록: **룩업 로직상 가능**. 조건 4개 —
1) 코드 정렬 유지 (AC00~D7A3은 0x9F와 0xF9 그룹 사이에 삽입)
2) 헤더 +8 증가, 버킷 0xAC~0xD7 신규 + 인덱스 밀리는 0xF9/FA/FE/FF 재계산
3) 전 레코드 +24/+25 재계산 (그룹당 ≤256, 현 최대 222 → u8 충분)
4) BMP 밖 문자 불가
미확인: 아틀라스 크기 한도, 로더 버퍼 한도, 레코드 번호를 참조하는 다른 테이블
(생성자 +56=-1 캐시 의심). **이 결론은 360판 바이너리 기준** — PS3 EBOOT 구현은
다를 수 있으나 같은 NFH 포맷·버킷 공식이 PS3 파일로 검증돼 동일 가능성 높음.
최종 확정은 인게임 실험(레코드 1개 U+AC00 + SCB 원시 한글 1줄, 사용자 승인 대기).
분석 스크립트: imas2pc 감독 세션 scratchpad\nfh\.

주의(현행 유지보수): 현 치환 방식은 코드를 안 바꾸므로 +24/+25·버킷을 건드릴
필요 없음 — repatch_fonts가 이 필드들을 보존하는 게 올바른 동작.

## 24. 한글 직접 등록: 360 실기 검증 성공 + 전각 영숫자 재렌더 (2026-10-14)

### 전각 영숫자 재렌더 (사용자 승인)
PUNCT_RERENDER에 ０-９Ａ-Ｚ 36자 추가 → 렌더 대상 2,414자, 검증 PASS, 배포 완료
(백업 `_backup_fontfix_20261014_150321`). render_cell에 디센더 초과(Ｑ 꼬리 등) 시
셀 안으로 밀어 넣는 폴백 추가.

### 직접 등록 실기 실험 — 성공 (360 PC 포트, 사용자 승인)
도구: `font_patcher/nfh_convert_direct.py` — 희생 레코드 2,359개의 code를 한글로
교체 → code 순 재정렬 → 전 레코드 그룹 카운터(+20/+21) 재계산 → 버킷 테이블
재생성. 자가 검증(정렬·카운터·버킷 공식·룩업 시뮬레이션) 내장. 산출 `output_direct/`.

실험 방법: 360 포트(build_imas2_o2)의 initialFix.mpc에 직접 등록 NFH만 주입(NUT은
순정 유지)하고 프롤로그 9종(*_w01_01.scb)의 index 0/1을 원시 한글(UTF-16BE,
매핑 미적용)로 교체 → ctrl.py로 새 프로듀스 진입.

결과: **원시 한글 코드포인트가 전부 정상 조회됨.** 한글 레코드가 가리키는 순정
아틀라스 위치의 한자가 표시됐고, 어절 글자 수·개별 글리프가 매핑 기대값과 일치
("한글 직접 등록 실험입니다" → 鵙稻 鍠鈕 耒芬 谿鶺醞縉縣 등). 재정렬 NFH로 기존
일어 UI도 전부 정상 렌더 = 버킷/카운터 재구축 올바름. 종료 후 전부 원복(md5 확인).

부수 확인: 360 엔진도 복호화 평문 pac(initialFix.mpc·scb)을 그대로 수용.

### 전환 절차 (남은 일)
1. (scb-excel/메인) excel2scb에서 font_mapping 치환 제거 → 원시 한글 SCB 전량 재생성
2. (폰트) `python deploy_fonts.py --direct` — output_direct NFH + 동일 NUT 배포,
   매핑 json 동기화 생략. **SCB와 반드시 동시 배포** (서로 비호환: 직접 등록 폰트
   + 매핑 SCB = 한자 코드 소멸로 공백, 치환 폰트 + 원시 SCB = 한글 코드 없음)
3. 사용자 PS3(RPCS3) 인게임 최종 확인 — PS3 EBOOT 룩업이 360과 다를 가능성은
   낮지만(동일 NFH 포맷·버킷 공식 PS3 파일 검증) 이 단계에서 최종 판명
4. 전환 후: 미번역 일어 줄의 희생 한자는 공백(기존엔 한글 글리프) — 고지된 트레이드오프
- 폰트 교체(Noto→다른 폰트) 대비: repatch_fonts.py `--font <경로>` 인자로 교체 가능

## 25. 한글 직접 등록 전환 배포 (2026-10-14)

인게임 실험 성공(§24) 후 전환 핸드셰이크 완료:
1. SCB 측: excel2scb `DIRECT_HANGUL=True` — 매핑 치환 제거, 원시 UTF-16BE 한글 기록.
   gscript 1,121파일 + attract.mpc 재생성·검증 통과. XMB는 --no-font-mapping 재빌드만
   (라이브 순정이라 배포 대상 아님).
2. 폰트 측: `deploy_fonts.py --direct` — loose 4종 + initialFix(NFH×2) + initialTemp(NUT×2)
   직접 등록판 교체. bucket[0xAC]=7222 확인.
3. SCB(deploy.py) + attract(--deploy) 배포 완료.

롤백: 폰트 = `resource\_backup_fontfix_20261014_153131\` 복원,
SCB = excel2scb DIRECT_HANGUL=False 재생성 + deploy.py.
효과: 매핑 테이블 유지보수 소멸, 원본 한자↔한글 글리프 충돌 해소. 인게임 확인 대기.

## 26. PC 포트(360 리컴파일) 배포 대상 추가 (2026-10-14)

사용자 방침("PS3 패치를 PC 리컴프에 적용")에 따라 배포 파이프라인 확장:
- excel2scb `PCPORT_OUTPUT=True`: 재암호화 전 평문 dec를 output_pcport/에 이중 출력
  (360 엔진은 평문 pac 수용 — imas2pc 세션 실기 검증).
- `deploy_pcport.py`: build_imas2_o2\game\resource\gscript에 존재 파일만 교체(1,118개 배포,
  PS3 전용 ryu W01 계열 등 제외), 원본 _backup_kr_orig 백업 + SHA-256 매니페스트.
- 폰트는 폰트 세션이 PC 포트 주입 담당(역할 분담 합의 — SCB는 메인 세션 전담).
- ⚠ PS3 dec ≡ 360 dec 내용 동일성은 가정 — 인게임 검증으로 확정 예정.

## 27. 곡 가사 추출 + 번역툴 '곡 가사' 탭 (2026-10-14, 사용자 지시)

- 가사 위치: `resource\songinfo\<곡>\lyrics_<곡>.xmb` — 22곡, 단독 암호화 XMB,
  기존 XMB 파서로 그대로 파싱됨(id = LYR_001~). 중국 패치에는 songinfo가 없어
  CN 참고역 없음.
- xmb_text.py 확장: dump/build가 가사 22종 자동 포함(캐시 없으면 즉석 복호화),
  번역 틀 병합은 기존 kr 보존. **재주입(build)도 동일 경로** — 파일 크기 불변
  제약이라 한국어가 일본어보다 길면 파일별 오류로 알려줌.
- 웹앱(imas2.buyeo.uk): '곡 가사 (22곡)' 탭 추가, 키 = 곡코드/LYR_nnn,
  Supabase rows에 612행 시딩(기존 행 불변). 푸시 → Vercel 자동 배포 확인.
  팀이 한국어 열을 채우면 `webapp_pull.py` → `xmb_text.py build --no-font-mapping`
  → patched\songinfo\ 산출(직접 등록 체제 기준).
- 참고: 실제 팀 암호는 반각 w@ldo (전각 ＠는 HTTP 헤더 불가).

## 27-2. PC 포트 인게임 한글 검증 성공 + 타깃 전환 (2026-10-14)
(번호 중복 정리: 병렬 세션 동시 기록 — 커밋 메시지의 '§27'은 앞뒤 문맥으로 구분)

- PC 포트(build_imas2_o2) 인게임 검증 성공: 평문 한글 SCB(1,097) + 직접 등록 폰트로
  미키 프롤로그 전체 한국어 출력, GERR 0, 크래시 없음 (스크린샷 imas2pc\ctrl_shots\kor2).
- 폰트 세션의 전일 크래시는 PS3 "AES 재암호화본"을 복사한 것이 원인으로 확정 —
  평문(dec)은 양 플랫폼 호환. "360 베이스 리빌드" 권고는 철회됨.
- **사용자 방침: 이후 작업은 PC 포트 우선** (PS3 배포물은 유지하되 추가 작업 1순위는
  build_imas2_o2\game\resource). twi 가사도 포트에 반영됨(별도 세션 경로).

## 28. 라이브 정지 원인 확정: MSG 116바이트 버퍼 초과 (2026-10-15)

- A/B 이분: 한글 gscript 5/5 정지 vs 원본 3/3 통과 (폰트 무죄 — 폰트 원본+한글 SCB도 정지).
- 원인: 게임 엔진의 대사 버퍼는 116바이트(널 포함) 고정 — 원본 전 파일이 이 값에서
  딱 잘려 있던 이유. 초과 문자열(배포본에 1,553개, 최대 3,072B 비명 대사)이 복사될 때
  힙을 손상시키고, 라이브 시작의 대형 사운드 할당에서 무한 루프 정지로 발현.
  라이브가 읽는 all_liv/aud 계열에 초과 엔트리 존재 확인.
- 수정: rewrap에 하드 캡 3단계(반복 문자 런 6자 압축 → 2줄 재배치 → 경계 절단),
  build에 116B 초과 시 생성 거부 게이트, validate에 116B 초과 = 구조 오류 추가.
- PS3도 동일 엔진 계열이라 같은 캡 적용해 재배포 (테스트 씬이 우연히 108B 이하라
  미발현이었을 뿐).
- **재검증 통과 (2026-10-15)**: 캡 적용 배포로 라이브 시작 정지 소멸 (한글 5/5 정지
  → 0/1, 예전 정지 지점 프레임 ~11,690을 지나 14,610+ 정상 진행) — 원인 확정 종결.

## 28-2. 라이브 가사의 진짜 소스 = dance pac — 한글 가사 인게임 성공 (2026-10-15, PC 포트)

- songinfo\<곡>\lyrics_*.xmb 평문 교체로는 라이브 가사가 일본어 그대로(실측,
  vulkan 세션 덤프 확인) → **라이브 가사는 `dance\dan_<곡>_{1,3,5}.mpc` 내장
  XMB**에서 읽음(내용은 songinfo판과 동일 25줄, 3종 모두에 존재).
- `tools/image_text/dance_lyrics.py`: dance pac 리사이저 — 가사 XMB를
  allow_grow로 재작성 후 pac 재조립(뒤 엔트리 시프트, 테이블 +8/+12와 헤더
  +0x08=크기합 갱신, 비가사 엔트리 바이트 불변·가사 kr 반영 전수 검증).
  pac 상세: 헤더 0x40, 엔트리 32B(+8 size/+12 ofs), 데이터 16정렬 연속,
  data_start는 가사 XMB 위치로 역산(dan_twi_1 = 0x340).
- twi 3종 PC 포트 배포(평문, .orig_kor 백업) → week02 체크포인트 +
  `IMAS2PC_SCENE_OVERRIDE=schedule=stage_viewer` + dance_drive --stage로
  5인 카니발 라이브 진입, **가사 자막 한국어 출력 확인**("능력들을 합쳐서
  빛을 목표하자" 등, ctrl_shots\lyr\). pac 크기 변화(+304B)도 게임이 수용.
- songinfo판은 다른 용도(곡 선택 가사 보기?) 추정 — 배포 유지, 해 없음.
- 남은 21곡은 팀 번역 입력 후 `dance_lyrics.py build && deploy` 두 줄로 반영.
  PS3 쪽은 사용자 방침(PC 포트 집중)에 따라 보류(필요 시 encrypt_to_scb 계열
  재암호화 또는 평문 수용 여부 별도 확인).

---

## 29. 인게임 메일 텍스트 덤프 + 번역 경로 (2026-10-15, 메일 1단계)

- 대상: resource\mail\mail_produce.mpc / mail_viewer.mpc (PC 포트본은 암호화 —
  사본 복호화, dance_lyrics.decrypt_cached 재사용). pac 레이아웃은 dance pac과
  동일(+0x20 count, 0x40 테이블 32B, MSG 파일명 매니페스트, 데이터 연속).
- 텍스트 소재 확정 (도구: tools/image_text/mail_text.py dump):
  - sya_mail_01.xmb 69행(아이돌 메일 sub/body/atc, 최장 본문 1,728B UTF-16)
  - sys_mail_01.xmb 42행(샵·시스템 메일) — produce 전용
  - key_help.xmb 60행(키 도움말), jou XMB 5행(기자명) — viewer 전용
  - produce/viewer의 sya·key_help는 텍스트 완전 동일(md5 일치) → 1회 번역,
    두 파일 주입. **번역 유니크 합계 176행.**
- 메일 수신 연출 대사 = 내장 all_getmail_01.scb(dec 래퍼: SCB 1,472B+컷씬 pac
  64B) 3행 — 이미 gscript 번역 체계(script/all)에 존재. 내장 사본 리빌드는
  patch_attract 패턴(§20) 적용 대상 = build 단계 몫. MSG 116B 캡(§28)도
  그 경로가 처리. **메일 본문(XMB)은 가사와 같은 XMB 경로라 116B 캡 비적용**
  (원본 최장 1,728B 실측).
- 산출: mail_texts.json(위치·오프셋 포함), xmb_translations.json에 mail/* 틀
  176행 합류, 게임 tools에 mail_translation_1.xlsx(4시트) 생성.
- 다음 단계(build): rebuild_xmb(allow_grow)+dance_lyrics.rebuild_pac로 XMB
  엔트리 교체·pac 재조립 → PC 포트 배포(.orig_kor 백업+md5), 내장 SCB는
  patch_attract 패턴. 번역 채우기는 재번역 배치와 함께.

## 29-2. 폰트 크기 상향 + 번짐 할로 (2026-10-15, 사용자 인게임 리포트 3건)

- 리포트: ① 한글이 일어보다 작아 자간이 넓어 보임 ② '차' 등 우측에 인접 셀
  세로선 번짐 ③ 확정 advance·대사창 폭을 excel2scb WRAP 재보정용으로 전달 요청.
- 측정: Noto 28px에서 한글 asc≤24·desc≤3·잉크우측≤25('뺐' 1자만 26) — Rodin
  잉크(24~26)와 동급. 26px 잉크는 ~10% 작았음.
- **im2_font 신규 규격: size 28, 셀 26×27, 베이스라인 24, advance 26px 균일,
  배치 1px 할로**(이웃 rect와 최소 1px 간격 — 바이리니어 번짐(②) 해소).
  재배치 226자/축소 7자, 검증 PASS. 잉크 하단선(베이스라인+desc)은 한자와 동일.
- im2_font_l: 512²×29 시트가 빽빽해 26×27 셀·할로 모두 공간 부족(수백 자 실패
  실측) → **구 규격(26px/25×25/무할로) 유지** — 폰트별 params/halo 옵션화.
  대사는 im2_font라 시각 영향 없음.
- PC 포트 폰트 재배포 완료(직접 등록판). 전후 비교: output/qa_before_after.png.
- **WRAP 재보정 기준값(→ scb-excel)**: 한글 advance = 26px, 대사창 가용 폭 =
  일어 전각 26자 × 27px = 702px → **한글 27자/줄**(27×26=702). MSG 116B 캡과도
  정합: 27자×2줄=54자=108B+개행 ≤ 116B.

## 30. 폰트 1px 하향 + 블리딩 제거 (2026-10-16, 사용자 리포트 — 글리프 줄/baseline)

- 리포트(2070S 플레이 중): 커뮤 검정 대사에 간혹 세로 점선 줄, 라이브 가사(흰+외곽선)
  에서 더 도드라짐("가/자 사이 세로 1px 선", "으 아래 가로 조각"), 커뮤 baseline 낮아
  보임. 사용자 지시 "그냥 폰트를 좀 줄이는게 나을 것 같아".
- 원인 분석: §29-2의 28px는 잉크가 26×27 셀 경계에 닿음(asc≤24→y0=0, 우측≤25) +
  셀 둘레 1px 할로 간격에 원본 아틀라스 잔여 AA 픽셀이 남아 바이리니어가 섭취 →
  점선 줄. baseline 24는 한자 하단선 맞춤이었으나 커뮤에서 낮아 보인다는 체감.
- **im2_font 신규 규격: size 27(안 들어가는 복잡 글자만 자동 축소 — 26×715, 25×9,
  24×1), 셀 26×27 유지, 셀 내부 pad 1px(잉크 ≤24×25), baseline 23(1px 상향),
  배치 시 셀 둘레 1px 링의 비보호 픽셀 클리어.** advance 26 유지 → WRAP(702px,
  27자/줄)·excel2scb 불변. im2_font_l은 구규격 유지(pad 0).
- repatch_fonts.py: params에 pad 추가, render_cell 경계를 pad 기준으로, 링 클리어
  추가. validate/nfh_convert/qa_render PASS.
- 배포: RPCS3(deploy_fonts --direct, 백업 _backup_fontfix_20261016_043732) +
  PC포트 빌드(deploy_pcport --font-only; initialFix be239d29…, initialTemp
  35a61125…) + 2070S(imas2_fonts_v2.zip, sha256 0ec253be…) — 사용자 육안 확인
  대기.
## 30-2. font_l rect 축소판 — 폰트 v3 (2026-10-16, 가사 조각선 잔존 대응)

- §30(폰트 v2) 후에도 라이브 가사 하단 조각선 잔존(720p 업스케일 전 입력에서 확인
  — 글리프 쪽 확정). uitrace로 가사 폰트 식별 실패(화면 복사 텍스처만 잡힘).
  im2_font는 v2에서 전 셀 1px 간격+링 클리어 보장이라 조각선 불가 구조 → 가사는
  im2_font_l로 추정, 실증 투입.
- **im2_font_l 신규 규격: size 25, baseline 21, 잉크 pad 1px, 샘플 rect를 셀보다
  1px 안쪽 23×23으로 축소(rect_inset — NFH x/y+1, bearingY-1, +10/+16 재계산).**
  이웃 rect 0px 간격에서도 rect 경계 바이리니어가 자기 빈 테두리만 읽음. 축소 20자.
- repatch_fonts.py: params rect_inset 추가, NFH 필드 기록을 inset 기준으로.
  validate/qa PASS. im2_font는 v2 그대로.
- 배포: RPCS3(_backup_fontfix_20261016_051133) + PC포트 빌드(initialFix 8cd8e85e…,
  initialTemp b3949936…) + 2070S(imas2_fonts_v3.zip, sha256 50e8e293…).
  판정: 가사 조각선 소멸 → 가사=font_l 확정. 잔존 → uitrace 개선으로 재식별.
## 30-3. 가사 조각선 원인 확정 — 가사 렌더러의 rect 밖 오버샘플링 (2026-10-16)

- drawdump(§6e, 2070S)로 **가사 = im2_font 직접 그리기** 확정(최종 2D 패스가
  2048×4096 DXT2_3 시트 샘플링). font_l 아님 → 폰트 v3는 가사와 무관.
- 아틀라스 재구성 검증(scratchpad sim_lyric.py): 게임에서 조각이 보인 글자(손·을·
  잡·하)의 **셀 밖 정확히 2px**에 이웃 원본 한자 가장자리 잉크(max 255) 존재.
  1px 할로 간격은 깨끗(링 클리어 작동) → **가사 렌더러가 NFH rect 밖 ≥2px 오버샘플링**.
  대사창 렌더러와 쿼드/UV 구성이 다른 것. 순정 컬러 파트는 전면 백색(프리멀티 기각).
- 다음: 리컴파일 세션이 가사 쿼드 UV 추출(오버리치 정확 수치) → 폰트 v4 마진 설계
  (전면 재배치+큰 간격 vs rect 축소).
- 병행 확정: A/V 420ms 정지 = 게임 측 CPU 작업(게스트 체인 확보, GPU 유휴 — 셰이더
  컴파일 아님). FSR2 유화 질감 주원인 = RCAS(sharpness 0 권장, -21%), reactive 4~8.
## 30-4. 폰트 v4 — 가사 외곽선 셰이더 오버리치 대응 재배치 (2026-10-16)

- 글리프 덤프 분석(리컴파일 세션, v13_glyph): 가사 = VS …D1722355 / PS …4C9A614A
  (stride 16) 외곽선 셰이더. 셀 rect 기준 탭 좌표가 우/하로 +2m(m=27/32 텍셀 =
  화면 1px) → **rect 밖 2번째 텍셀까지 bilinear로 읽음**(1번째 0.23, 2번째 0.77).
  좌/상은 K·m(K = VS c255.y, 미확정). 밉맵 미사용. 다른 텍스트(stride 12)는 오버리치 없음.
  → rect 축소로는 안 됨(오버리치가 rect 끝 기준). 재배치로 셀 간격 확보가 해법.
- **repatch_fonts.py 배치 규칙 재설계**: 이웃 종류별 간격 — 보존 글리프 잉크와는
  셀에서 CLR px, 보존 rect·다른 한글 셀과는 CLR-PAD px(양쪽 잉크가 PAD만큼 안쪽).
  재배치는 27px 격자 → 누적합 테이블 기반 픽셀 단위 최상좌 탐색. 공간 부족 시 중단
  (종전: 경고 후 겹침 감수 — 폐기).
- im2_font clearance 2(3은 픽셀 패킹으로도 공간 부족 — 실측). 재배치 1,397자.
  **전 2,414자 rect 밖 2px 링 잉크 0** 검증(3px 링은 이웃 셀 잉크가 3번째 텍셀부터
  시작 — K=3이면 좌/상 문제, v14 glyphdump로 K 확인 예정). validate/qa PASS.
- 배포: RPCS3(_backup_fontfix_20261016_160636) + PC 포트 빌드(initialFix 6572d715…,
  initialTemp 836e5d9b…). 2070S 철수로 2070S 배포는 없음.
- 같은 날 결정(사용자): 2070S 테스트 머신 철수, 이후 테스트는 감독 PC에서 FSR1만.
  그래픽 잠정 방향 = FSR1 또는 내부 해상도 2배(FSR2·DLSS 제외). A/V는 vblank 60Hz
  교정 후 clamp 유무 모두 싱크 정상(블라인드 판정) → 기본 noclamp 유지.- **(추가) 인게임 확인 완료**: 감독 PC(FSR1) 런에서 가사 셰이더 c255 = (1, 2, −1, 0) → **K=2 확정**
  (좌/상도 2번째 텍셀까지 — clearance 2로 충분). 가사 드로우 순간 720p 프레임 3장(서로 다른
  가사 줄) 확대 결과 조각선 없음. 증거: Desktop\imas2pc\_incoming\v15_lyrics_check\.
---

## 30. DLC 번역 대상 추출 → 웹앱 dlc 분류 (2026-10-21, 시딩은 사용자 실행 대기)

- 소스: 360 DLC(Desktop\imas2dlc, PC 포트 주입 대상 = 기준 축) + PS3 DLC zip
  (업로드본, 보조 병합). 원본 불변 — 사본만 imas2dec 복호(_cache\dlc).
  360 파일은 packageInfo.pac(평문 TSK)만 평문, catalog/mail/lyrics XMB는 암호화.
- 도구: tools/image_text/dlc_text.py extract — 전 XMB를 parse_xmb로 덤프,
  파일 내 중복 id(아이템명/설명이 같은 id 상속)는 ".n" 서수,
  catalog/packageInfo는 컨테이너 내 XMB 서수(xN.) 포함 키. PS3↔360은
  jp 전문 일치로 1행 병합(meta.src에 양쪽 위치), 불일치만 "#ps3" 분리.
- 결과 **총 3,242행**: mail 1,657(양플랫폼 1,627) / package 629(병합 282) /
  catalog 586(360 전용 — 카탈로그는 360에만 XMB) / songinfo 364(DLC 신곡
  14곡 가사, 360 전용) / ranker 6(PS3 전용). 플랫폼 간 jp 불일치 14행.
  본편 기번역(jp 전문 일치) 제안 0건 — 전부 신규 텍스트. 폰트 매핑 검사
  이상 없음(제안 kr 없음; 웹앱이 입력 시 2,359자 기준으로 행별 경고).
- 웹앱: webapp_seed에 rows_dlc(--only dlc), webapp_build nav에 DLC 대분류
  (5그룹), webapp_pull dlc(→dlc_translations.json + songinfo는
  xmb_translations의 songinfo/<곡>으로 병합해 dance_lyrics 빌드 재사용 가능).
  **원격 시딩·프런트 재배포는 사용자 실행 대기** (명령:
  `python webapp_seed.py --only dlc --code <팀암호>`, 이후 빌드+푸시=배포).
- PS3 DLC 무수정 왕복 조사: **불가(현재 도구)** — imas2dec는 복호 전용
  (PS3/PS3 DLC/G4U/360 지원 표기), scb_common.decrypt_scb(본편 키 테이블)로는
  DLC가 쓰레기로 풀림 = DLC는 별도 키 체계. 재주입이 필요해지면
  (a) imas2dec의 DLC 키 테이블 확보해 encrypt_to_scb 확장 또는
  (b) PS3도 평문 수용인지 실기 확인. PC 포트(1순위)는 평문이라 무관.

### 30-2. DLC 시딩·뷰 정리·DLC 이미지 (2026-10-22, 사용자 지시로 직접 실행)

- dlc 3,242행 시딩 완료(ignore-duplicates). 사용자 피드백 반영:
  - DLC 신곡 가사를 본편과 같은 **곡 단위 편집 뷰**로 (키 형식 `lyrics_곡:LYR_nnn`
    대응 — songOf가 본편 `곡/LYR`만 알아서 일반 표로 떨어졌던 것).
  - DLC 메일 = **메일 1통 카드**(제목/본문/첨부 한 화면, 838통),
    카탈로그 = 아이템명+설명 카드(296건). 저장은 파트별 행 그대로(이력 유지).
  - 메일 **캐릭터 필터**, 카탈로그/패키지 패키지 필터, 이미지 DLC 종류 필터.
- **DLC 이미지** (tools/image_text/dlc_images.py): 중국팀은 DLC 이미지 미수정,
  PS3 DLC zip엔 텍스처 없음 → 360 DLC만 대상. 663장(유니크 535) 전량 디코드:
  NTXR=NTP3 레이아웃, DXT/32bpp는 swap16, **360 전용 fmt10=ARGB1555,
  fmt11=ARGB4444, fmt19=ARGB32**(모두 BE 그대로, 눈검증). ad_bg.ptc는 평문
  'PTC+MSHM' 파티클(텍스처 없음).
  - 텍스트 있음 108장: 카탈로그 페이지 1024×512 79 / 곡 제목 로고 464×48 14 /
    곡 재킷 256×256 15. 없음: 아이템 그림 300×384, 의상·액세서리 아이콘,
    메일 사진 332×424, 32×32 아이콘.
  - 웹앱 이미지 텍스트 > "DLC" 그룹으로 업로드·시딩(--dlc-thumbs / --only dlcimg).
    회수 시 작업본은 kr_dlc/<패키지6>/ 로 분리(360 주입 시 ARGB1555/4444
    재인코딩 + swap16 규칙 필요 — 재주입 도구는 별도 과제).

## 31. 본편 XMB 텍스트 전수 추출 — 누락분 4,140행 (2026-10-22, 사용자 지적)

- 사용자 지적: 의상·악세서리·곡·업무 설명, 오디션 심사위원/라이브 청중 코멘트가
  웹앱에 없음. 원인: 지금까지 범위를 "중국팀 수정 파일 + 개별 요청"으로만 잡고
  리소스 트리 전체를 텍스트 기준으로 훑은 적이 없었음.
- tools/image_text/game_xmb.py: 평문 .mpc 내장 XMB + interface/game/iface/scene/
  s4u/mail/text의 암호화 .tsk(사본 복호화) 전수. 내용 동일 XMB는 1벌(meta.locs에
  전 위치). 기존 커버(가사·NPC 명단·install·ranker) 제외.
  - 162개 소스, 유니크 XMB 37 → **4,140행**, 웹앱 대분류 "게임 데이터 텍스트" 15그룹:
    업무·스케줄 781 / 스태프롤 746 / 팬레터 722 / 메뉴·도움말·시스템 566 /
    악세서리 330 / 스킬·부적 173 / 고유명사 163 / 의상 152 / 오디션 심사위원 132 /
    캐릭터 프로필 127 / 스테이지 72 / 본편 메일 64 / 곡 정보 50 / 결과 코멘트 40 /
    라이브 청중 22.
  - 게임 DB(initialFix.mpc)는 요소 구조(costume/accessory/song/skill_info/charm/
    stage_info/character)라 부모 노드 단위로 이름+설명 카드(meta.card/part).
- 시딩 완료(ignore-duplicates). 재주입 도구(내장 XMB 교체+pac 재조립)는
  dance_lyrics.rebuild_pac 일반화로 다음 단계 — 특히 initialFix.mpc는 폰트
  주입 대상이기도 해 순서 조율 필요.

## 32. 웹앱 번역분 PC 포트 적용 + 인게임 검증 (2026-10-22, KOR 지시)

### 회수 현황 (imas2.buyeo.uk, 읽기 전용)
| 분류 | 대상 | 번역 | 비율 | 비고 |
|---|---|---|---|---|
| 게임 스크립트 | 52,240 | 46,119 | 88.3% | 웹 편집 0 — 회수 결과 translation_2.xlsx와 변경 0셀(이미 배포본과 동일) |
| XMB | 1,624 | 1,580 | 97.3% | 가사 612(22곡)·NPC 명단 942·install 22·ranker 4 |
| 이미지 | 441 | 167 | 37.9% | 팀 작업본 업로드 167장(모든 위치 복제 321장) |
| 게임 데이터 텍스트 | 4,140 | 0 | 0% | — |
| DLC | 3,242 | 6 | 0.2% | ranker 6(PS3 전용) |
- 폰트 커버리지: 회수 번역문 중 현재 2,359자 밖 한글 **0자** → 폰트 재생성 불필요.
- 스크립트 비교 스냅샷: 게임 tools `translation_webapp_20261022_1104.xlsx`(신규 파일명).

### 적용 경로
- **배포 대상 변경(리컴파일 감독 합의)**: build_imas2_o2\game은 전 세션 회귀 기준선 →
  교체 금지. `imas2pc\game_kor`(통째 사본, 5,337파일)에만 주입, 실행은
  `IMAS2PC_DISC_ROOT=...\game_kor`. 백업·매니페스트 `imas2pc\game_kor_backup_20261022_111951\`.
  산출물·사본은 git/zip/공유노트 금지(저작권).
- `tools/image_text/pcport_apply.py`(신규): 360 원본 사본 복호화 → 텍스처·XMB 주입.
  - 텍스처는 **번호가 아니라 내용으로 짝짓기**(360판은 텍스처 순서·구성이 다른 파일 존재):
    같은 치수 360 텍스처를 후보 디코더로 풀어 PS3 원본과 가장 닮은 것(≥30dB) 선택,
    같은 방식 역변환으로 인코드, 재디코드 게이트(≥33dB). 360 코덱 자동 판별(DXT+swap16 등).
  - NPC 명단 XMB 942칸(ScheduleSelect 등 내장 표) allow_grow + pac 재조립.
  - 결과 33파일 성공/실패 0. **360판에 같은 그림이 없어 미적용 18텍스처**(お守りINFO류
    치수 상이, 튜토리얼 카드 1024×580은 360판 내용 상이(26dB) — Xbox 버튼 그림 추정,
    NationwideRanking 버튼, s4u 일부) → 360 전용 작업 필요.
  - 360 bg2d `.s2d`는 imas2dec 미지원 형식(선두 0F F5 12 ED) → 배경 5장 미적용.
  - install.xmb·ranker_npc.xmb·exep_*·boot는 360판에 파일 자체가 없음.
- 가사: dance_lyrics build → 17곡 38파일(hon·ilh·lmg·nan·rdy 5곡은 360판에선 DLC 곡이라
  본편에 dance pac 없음 → 360 DLC 적용 과제). dance_lyrics deploy 대상도 game_kor로 변경.
- inject_image_text 개선: PSNR을 **보이는 값(알파 곱한 RGB+알파)** 기준으로(투명 픽셀 RGB
  오차 제외), DXT3/5 끝점을 알파 가중으로, PCA 축 후보 추가. 예외는 눈검수 1건만
  (alf_live#007 32.9dB, PSNR_OVERRIDES에 사유 기록). PS3 기준 45파일 게이트 통과.

### 인게임 검증 (PC 포트 1배, gpu_run.lock 준수, 2배 미사용)
week02_start_haruka 체크포인트, 세이브는 검증 전 `kor_patch_before_test`로 백업 후 복원.
- 부팅·타이틀: 로고 부제 **"아이돌마스터" 한글 이미지** 정상.
- 유닛 선택: **"활동 02 주"** 한글, ADV: **한글 대사 정상**("안녕! 음, 자네는…").
- 멤버 선택 제목 **"멤버 선택"** 한글, 일시정지 메뉴 정상.
- Stage For You: 메뉴 전체 한글(스테이지 포 유!·유닛 편집·코디네이트 선택·곡 선택 등).
- 라이브(The world is all one!!): **한글 가사 자막 정상**, 깨짐·정지 없음.
- 아직 일본어: 시스템 다이얼로그(Xbox LIVE 안내 등)·메뉴 설명문·프로필 = 게임 데이터
  텍스트(번역 0%), 팀이 작업본을 안 올린 메뉴 버튼 라벨.
- 스크린샷: `imas2pc\ctrl_shots\kor\`(로컬 전용).

### 발견 사항
- 공유 build_imas2_o2\game\resource\dance\dan_twi_{1,3,5}.mpc가 10-15 가사 실험 때
  넣은 **한글 평문본 그대로**(.orig_kor 옆) — 기준선 규칙과 충돌. 복원 여부는
  리컴파일 감독 판단 사항으로 보고만 함.

### 미적용 / 다음
- PS3: 스크립트는 기배포본과 동일. 이미지·XMB는 PS3용 검증 게이트 배포 경로가 없어 미적용
  (patched/에 게이트 통과본은 있음) — 사용자 방침(PC 집중)상 보류.
- 게임 데이터 텍스트 주입 도구(내장 XMB 일반화) — 번역 시작 전까지 보류.
- 360 DLC 사본 적용(가사 5곡 포함), 360 전용 텍스처 18장, 360 s2d 형식 조사.
- 추가(리컴파일 감독 전수 해시 비교): 공유 build_imas2_o2\game에는 dan_twi뿐 아니라
  10-15 01:04~01:48 배포분 **한글 1,179개**(gscript 1,173·initialFix/initialTemp
  폰트·dan_twi 3·lyrics_twi)가 남아 있음(백업 _backup_kr_orig, *.orig_kor). 복원 여부는
  KOR 결정 대기, 그때까지 공유 폴더 동결. game_kor는 이 상태를 통째 복사했으므로
  1,179개를 이미 포함 → 공유 폴더를 되돌려도 한글판은 game_kor에 온전. 향후 SCB·폰트
  PC 포트 배포도 대상을 game_kor로(deploy_pcport·deploy_fonts 경로 변경 필요).
  initialFix.mpc(게임 데이터 텍스트)는 game_kor의 폰트 주입본을 바탕으로 할 것.
- **KOR 결정(2026-10-22)**: 공유 build_imas2_o2\game은 현 한글 상태(10-15 패치판) 그대로
  유지. 새 번역 배포의 기본 대상은 **game_kor**. 이에 맞춰 배포 도구 변경:
  - tools/scb/deploy_pcport.py: 기본 대상 game_kor\resource\gscript(매니페스트
    pcport_kor_deploy_manifest.json), 공유 game은 `--allow-shared`로만. 게임 tools에 동기화.
  - font_patcher/deploy_pcport.py: `--build-root` → `--game-root`(기본 game_kor),
    공유 game 경로는 `--allow-shared` 없으면 거부(실행 확인).
  - pcport_apply.py·dance_lyrics.py deploy: game_kor 전용(공유 경로 없음).
  - game_kor는 공유 game을 통째 복사해 원본 백업(_backup_kr_orig, _kor_backup)도 포함 →
    "원본에서 빌드" 로직 그대로 동작.
  - 게임 데이터 텍스트를 initialFix.mpc에 넣을 때는 **game_kor의 폰트 주입본**을 기준으로.

## 33. 게임 이모티콘(PUA U+E000~E03F) 웹앱 지원 + XMB 재빌드 버그 수정 (2026-10-23, KOR 지시)

### 이모티콘 정체
- 메일 계열 텍스트에 사설 영역 코드 U+E000~E03F가 섞여 있음(사용 61종, DLC 2,901회·
  게임 데이터 291회·본편 메일 XMB 291회). 웹 폰트에 없어 웹앱에서 ㅁ로 보였음.
- 그림은 본문 폰트(NFH)가 아니라 **initialTemp.mpc 2번째 NUT 텍스처(256x512 DXT5) 상단
  8x8 칸(32x32)**. 코드 U+E000+i = i번째 칸(문맥 대조: E009 おやすみ=zzZ, E025 車,
  E028 飛行機, E03B 朝食=주먹밥, E03C ケーキ, E03E かみつく=강아지).
- 게임 쪽 폰트 슬롯 확인은 폰트 세션 담당(이 절 범위 밖).

### 웹앱
- `tools/image_text/emoji_assets.py`: 시트(256x256 PNG) + 픽셀 윤곽 단색 웹폰트
  imas2emo.ttf(cmap U+E000~E03F) 생성 → Supabase storage `tex/emoji/`에만 업로드
  (게임 자산이라 git 미포함).
- 표시: 일어 원문·검토 셀은 컬러 스프라이트 span, 한국어 입력칸(textarea)은
  `@font-face imas2emo`(unicode-range PUA 한정)로 같은 칸에 그림 표시. 저장값은 PUA 코드 그대로.
- 팔레트: 좌하단 "이모티콘" 버튼 → 64칸, 마지막으로 포커스된 한국어 칸 커서 위치에 삽입
  (mousedown 기본동작 차단으로 편집 상태 유지). PF `page__main` z-index 100에 가려져
  팔레트 z-index 300.
- 경고(차단 아님): 이모티콘 개수 다름 / 종류 다름(순서 무관). 폰트 커버리지 검사는
  원래 한글(가~힣)만 보므로 PUA 자동 제외. Python 쪽 encode_with_mapping도 한글만 치환.

### XMB 재빌드 버그 (일반 버그, PUA와 무관)
- 기존 `rebuild_xmb`는 값 섹션의 "첫 _text 이전"만 보존하고 그 뒤를 _text로 통째 재배치
  → 본편 메일 XMB처럼 ASCII id가 _text 사이에 섞인 파일에서 id 파괴(재파싱 0xff 오류).
  지금까지 쓰던 NPC 표·가사는 id가 앞에 몰려 있어 안 드러났음.
- 수정: _text 문자열 자리만 비우고 나머지 바이트는 제자리 유지, 빈 자리(옛 _text 구간 +
  꼬리 여백)에 순서대로 배치, 모자라면 allow_grow일 때만 꼬리 확장. 원본 특성 두 가지 반영:
  (1) 컴파일러가 같은 문자열을 vofs 공유로 중복 제거 → 공유 유지, 자리 부족 시 동일 내용 재사용,
  (2) UTF-16 _text가 **홀수 오프셋**에도 놓임 → 정렬 패딩 제거(정렬하면 무교체 재빌드가
  자리 부족). 검증에 "비 _text 값 불변" 추가.
- 회귀(캐시 전체 XMB 278개, 단독+pac 내장): 무교체 재빌드 **원본과 바이트 동일 278/278**,
  전 _text 23,560칸을 한국어+원문 이모티콘으로 교체 → 재파싱 일치 278/278(이모티콘 6,802개
  UTF-16BE 원형 유지). 본편 mail_produce PUA 칸 왕복(JSON→재빌드→pac 재조립) 통과.
  pcport_apply build(NPC 942칸)·dance_lyrics build 정상.

### 33-2. 전 분류 PUA 집계·컬러 입력칸·치환 코드 표시 (2026-10-23, KOR·사용자)
- DB 전 61,705행 집계(읽기 전용): 이모티콘 U+E000~E03F는 **dlc mail 795행·2,901회·61종**,
  **gamedata mail 18행·291회·21종**뿐. xmb·script·image 0. 미사용 E027/E033/E039(폰트 세션
  표와 일치). 번역된 PUA 행은 아직 0 → 이모티콘 빠짐/치환 행 0건.
- 범위 밖 PUA U+F001~F020(+F69A)은 **스크립트 치환 코드**(F001 유닛명, F011/F012·F015~F017
  아이돌 이름, F01A~F01C 장소, F01D 숫자 등) — 이모티콘 아님, script 분류에만. 번역된 행에서
  치환 코드가 어긋난 것은 1건(all_omi_01.scb:10192에 정체불명 U+F69A 추가). 목록:
  Desktop\imas2_image_text\pua_check\(pua_census.md, pua_mismatch.xlsx 2시트, json).
- 웹앱: 치환 코드를 보라색 칩(F001 등)으로 표시 + "치환 코드 다름" 경고(빨강). 이모티콘 표시·
  팔레트·경고는 원래 전 분류 공통(fmtText/warns) — 수정 이력 표 2곳도 이모티콘 표시 추가.
- 입력칸 실루엣 → **COLRv0 컬러 폰트**(칸별 24색 양자화 레이어, CPAL 1,320색, 146KB),
  칸 1.125em로 키움. 컬러 미지원 환경은 실루엣 대체. 캐시 회피 `imas2emo.ttf?v=2`.
- 팔레트 토글 버튼: 배경 없는 secondary → 채운 primary + 그림자.
- 엑셀 왕복(openpyxl 저장→읽기)에서 PUA 그대로 유지 확인.

## 34. PC 포트 SCB를 360 원본 기반으로 — 한글 MSG만 이식 (2026-10-23, KOR 지시)

### 배경
- PS3_VS_360.md §2.3-b: 기존 PC 배포(deploy_pcport ← excel2scb output_pcport)는 **PS3 순정 dec에
  한글을 넣은 평문**을 360 트리에 넣었다 → 360 엔진에서 PS3 스크립트 로직·PS3식 음성(BNSF flag 0)이 돎.

### 분류 (pcport360.py classify, 공통 1,158 / 배포 대상 1,097)
| 분류 | 전체 | 배포 대상 |
|---|---|---|
| 음성/서브파일만 다름 (SCB 섹션 전부 동일) | 988 | 927 |
| 로직 다름 (CMD 등) | 113 | 113 |
| MSG만 다름 (PS3 문구 수정) | 57 | 57 |
- 로직 113개 섹션 조합: CMD 22, CMD+LBL+RSC 19, CMD+LBL+LBN+MSG 16, CMD+LBL 16, CMD+LBL+LBN 16,
  CMD+MSG 10, CMD+LBL+LBN+MSG+VCN 5, CMD+RSC 3, CMD+LBL+MSG 3, 기타 3. 이름: arr_11·les_emotion·ni_01 각 10,
  w01_03·w03_07 각 9, mo_01 7, song_chg01 6, scs_*, aud_01, les_tu01, omi_01 등.
- 음성 플래그(BNSF+0x14 u16 = sfmt+8): 배포 대상에서 PS3 0 → 360 2가 999개. **360 원본에도 flag 0
  음성이 있다**(전부 0인 파일 8개, 0·2 혼재 43개) → 360 엔진이 flag 0도 재생할 가능성이 높음(인게임 미확인).
- 보고서: 게임 tools `pcport360_classify.md/.json`.

### 빌드 경로 (tools/scb/pcport360.py)
- 360 원본 dec(table360.bin, **풋터 32B**) + excel2scb의 규칙 그대로: `resolve_translations`(abs_offset 매칭·
  rewrap·116B 캡) → `build_msg_block`(테이블 리빌드, 규칙 3) → `replace_msg_section`(섹션 디렉터리 + pac 헤더
  4필드, 규칙 4). excel2scb는 매칭 루프를 `resolve_translations`로 분리만 함 — 기존 산출물 1,121개를
  메모리 재생성해 **바이트 동일 확인**, validate_output 통과.
- PS3→360 MSG 인덱스: 원문 목록이 같으면 1:1(1,005개), 아니면 difflib 정렬(92개; 같은 길이 replace
  블록은 유사도 ≥0.5 위치 짝, 길이 다르면 ≥0.6 순서 보존 탐욕 짝).
- 결과(translation_2.xlsx): 1,097개 생성, 이식 43,411줄, 원문 달라진 짝 89줄(번역 이식), **버린 PS3 번역 77줄**,
  **360에만 있는 대사 313줄(일본어로 남음)** — 거의 전부 all_omi_01(부적 가게, 360 341줄 vs PS3 138줄로
  PS3에서 재작성) 269줄과 all_les_tu01(360 버튼 튜토리얼 「B ボタン」 등) 32줄. 보고서 `pcport360_build_report.md/.json`.
- 1:1 파일 1,005개의 한글 MSG 섹션은 기존 PS3 기반 산출물과 바이트 동일(차이는 로직·음성뿐).

### 게이트·배포 준비
- `pcport360.py validate`: validate_output.validate_dec(구조, 리팩터로 분리) + 360 원본 대비 MSG 외 섹션·
  서브파일(컷씬/음성)·SCB 헤더(크기 필드 외) 불변, MSG 개수 불변. 1,097/1,097 통과. 음성 바이트·CMD 바이트·
  pac 크기 필드를 일부러 깬 사본은 전부 거부(음성 시험).
- `deploy_pcport.py --src360`: 게이트 통과 시에만, game_kor 전용(공유 game 거부), 매니페스트
  pcport_kor360_deploy_manifest.json. **아직 배포 안 함**(인게임 확인 뒤).
- `pcport360.py stage`: 인게임 확인용 별도 루트 `imas2pc\game_kor360_test`(game_kor 전체 사본 + 360 기반
  SCB 1,097개). game_kor 불변 확인. 실행 `IMAS2PC_DISC_ROOT=...\game_kor360_test`.
- 남은 것: 인게임 1배 확인(음성 커뮤, 로직 다른 파일 대표: les_tu01·w01_03·w02_* 등) — GPU 순서 대기.
  360 전용 313줄 번역 필요(웹앱 추가 여부 KOR 결정).
- **360 전용 313줄 웹앱 등록(KOR 결정)**: script 분류에 id `script:<폴더>:x360:<파일>#<360 인덱스>`,
  meta.x360·x_idx, 그룹 끝(seq 900000+)에 ignore-duplicates로 추가(기존 52,240행·번역 46,119행 불변 확인).
  웹앱: "360 전용" 배지·필터, meta.suggest(같은 파일 PS3 대사 중 유사도 ≥0.5의 기존 번역, 29줄·완전일치 11)를
  참고 줄로 표시(kr에는 안 넣음). 버린 PS3 번역 77줄은 build_report lost[]에 번역문과 함께 보관.
  회수: webapp_pull.py script가 `translation_x360_<날짜>.json`도 생성 → pcport360 build가 최신 파일을 읽어
  360 원문이 같을 때만 적용(rewrap 포함), 다르면 x360_stale로 보고. 메모리 시험: 31 적용·원문 바꾼 1개 거부.

### 34-2. 인게임 1배 확인 (game_kor360_test, 2026-10-23 01:36~01:59, KOR GPU 순서)
- 세이브 kor360_before_test 백업 → 빈 세이브(새 게임) → 런 → 복원. 로그상 디스크 루트 game_kor360_test 확인.
- 확인한 흐름: 새 게임 프롤로그(미키, 음성) → 아이돌 선택(하루카) → 첫 만남(har w01, 시간제한 3지선다 선택지)
  → 사무소 all_w01_04(코토리 소개, **360 튜토리얼 질문 「説明をきく/断る」** — PS3는 isTutorialEnable로 건너뛰는 흐름)
  → 스케줄 튜토리얼(선택지 2회) → 스케줄 배정. 대사·선택지 한글, 멈춤·크래시·로그 예외 없음.
- 음성(360 원본 BNSF flag 2): 같은 장면에서 하루카 대사 구간 L/R RMS가 무음성 P 대사 구간의 1.75배(13줄 전부 0.028
  이상, P 중앙값 0.02), 코토리 1.42배 → 음성 재생 확인. 덤프 audio_test\kor360_run.wav(로컬).
- 일본어로 남은 줄: mam_w01_01 #13(프롤로그 P 독백), all_w01_04 #57~59(튜토리얼 질문·선택지) 등 — 전부
  translation_2 미번역(웹앱에 st 0 행 있음, PS3 기반 산출물도 동일). 360 빌드 전체 일본어 잔존 5,643줄 =
  360 전용 311 + translation_2 미번역 5,332.
- 미확인: 레슨 튜토리얼 all_les_tu01(스케줄 확정 입력을 못 찾아 진입 못 함), 음성 커뮤 all_kur_01.
- deploy_pcport --src360: 현재 game_kor의 PS3 dec 배포본을 `_backup_ps3dec\gscript`로 보존(최초 1회) 후 교체 — 롤백용.

### 34-3. game_kor에 --src360 배포 (2026-10-23 02:0x, 사용자 승인)
- KOR 승인 후 이 세션 권한 검사에서 한 번 거부 → 사용자 직접 승인("KOR에서 온 명령은 내가 한 명령과 같아")으로 실행.
- game_kor SCB 1,097개 = output_pcport360(해시 일치). 이전 PS3 dec 배포본 1,097개 → `game_kor\resource\_backup_ps3dec\gscript`
  (이전 산출물과 동일). 매니페스트 게임 tools `pcport_kor360_deploy_manifest.json`. 포팅 세션에 game_kor.manifest 재생성 요청.
- 배포 시각 GPU는 포팅 런(공유 build_imas2_o2\game 사용) 중이었음 — game_kor와 무관.

## 35. 웹앱 PS3 / 360 플랫폼 전수 점검·태그 (2026-10-23, 사용자·KOR)
- 도구 `tools/image_text/platform_audit.py` (scan → platform_audit.json, apply). 360 원본은 메모리 복호화
  (table360·풋터32), PS3 DLC는 table 오프셋 0/384/768 시도.
- 태그 meta.plat = common | ps3 | x360 (+ plat_note). apply는 id·cat·grp·seq·key·jp·meta만 보내는 merge 업서트
  → kr/st/ts/by(팀 번역·상태) 불변. 새 행은 ignore-duplicates.
- 분류별 결과(62,634행, 태그 없는 행 0):
  | 분류 | 공통 | PS3 전용 | 360 전용 |
  |---|---|---|---|
  | 게임 스크립트 | 49,201 | 3,039 | 313 |
  | XMB | 557 | 1,085 | 0 |
  | 게임 데이터 텍스트 | 3,594 | 546 | 183 |
  | 이미지 | 327 | 59 | 98 |
  | DLC | 2,189 | 664 | 779 |
  - 스크립트 PS3 전용 = 竜宮小町 엑스트라(ryu) 2,920 + ami/azu/ior/rit_w01_03 20 + 360판에 없는 대사 99. 공통 중 문구가
    다른 103줄은 plat_note에 360 문구(번역은 PS3 행 하나를 360 빌드가 이식하므로 행 분리 안 함).
  - XMB PS3 전용 = exep_init(竜宮 NPC) 1,002, install 23, ranker 5, READY!!(rdy) 34·七彩ボタン(nan) 21. hon·ilh·lmg 가사는
    공통(360은 DLC로 수록) 표시.
  - 게임 데이터: PS3에서 뽑은 4,140행 중 546행이 360에 없음(PS3 확장 표). 360 전용 183행 추가(앨범 저장·Xbox 저장장치
    메시지 68, initialFix 61(Xbox LIVE 안내 등), initialTemp 22, mainmenu 13, staff_roll 10 등) — 키 `x360:...`.
  - 이미지: PS3 텍스처를 360 같은 파일과 내용 대조(pcport_apply 코덱 후보, ≥30dB). 360 미대응 텍스처 108개를 눈검수해
    일본어 글자 있는 14개(튜토리얼 카드 7, お守りGET 2(같은 그림), アップロード·システム設定·服装設定, S4U 가 재킷 2)만
    360 전용 행 13개로 추가(loc `x360:<rel>#nnn`, 회수 시 kr_x360/). 나머지는 버튼 그림·스태프롤 모델 텍스처·영문.
  - DLC: PS3 cp01~18 가사 병합(dlc_text가 빠뜨렸던 것) — 기존 280행에 PS3 위치 추가, 새 390행(PS3 전용 15곡 + iwt 문구 다름 8),
    PS3 전용 곡 재킷·제목 로고 30개 이미지 행. 360 DLC 이미지 108행 태그(카탈로그 등 360 전용 85, PS3에도 있는 곡 23).
- 웹앱: "360 전용" 배지를 일반화(PS3 전용 주황·360 전용 청록·판 차이 회색, 툴팁 plat_note), 판 필터(판: 모두 / 공통 /
  PS3 전용 / 360 전용), 카드·가사 묶음은 판 혼합 표시. script 그룹명 ryu는 시트명 오기(Jupiter) → "竜宮小町 엑스트라 (PS3 전용)".
- 남은 것: 360 .s2d 배경 5장(bg2d_0003·0006·0155·0156·0157) 복호화 미지원 → PS3 행은 "대응 미확인" 메모.
  PS3에만 있는 파일(exep_result·exep_staff_roll·exep_commu·exep_init·boot·logo·install·ranker_npc)은 360 없음.
  360 전용 이미지·게임 데이터 텍스트의 PC 포트 주입 경로(kr_x360 → pcport_apply, gamedata 주입 도구) 미구현.
  PS3 DLC game/cosinfo/exte 텍스처와 jacket_*_s(작은 재킷)는 360 기준과 같이 제외. 시딩 스크립트로 재시딩하면 plat이
  빠지므로 재시딩 뒤에는 `platform_audit.py scan && apply` 재실행.

## 36. DLC 한글 주입기 — 360 한글판 DLC 사본 + PS3 재암호화본 (2026-10-23, KOR 지시)

사용자 원문: "암호화 안하면 dlc 텍스트는 못넣냐?" / "없으면 만들어 넣어야지."
도구: `tools/image_text/dlc_inject.py` (build360 / coverage / roundtrip / build-ps3 / deploy-ps3 / restore-ps3).

### 암호 (실측)
- 게임 자체 AES-192-CBC, IV 0, 선두 16B prefix 블록. 키 = 384B 키표 + 풋터 3바이트(풋터 끝-32 위치 +1~+3).
  - 360 DLC: `table360.bin`, 풋터 32B.
  - PS3 DLC: `table.bin[384:768]`(두 번째 표), 풋터 64B. `licenses\*.edat`은 NPDRM이라 대상 아님.
- 복호화 → 무수정 재암호화(원 prefix·패딩·풋터 유지) = **원본과 바이트 동일**: 360 75개, PS3 136개(주입 대상 전부), imas2dec.exe 없이 메모리에서.
- 360 DLC에서 평문인 것은 `packageInfo.pac`(TSK)뿐이고, catalog_info / mail / lyrics xmb와 dance mpc는 암호화돼 있다. PC 포트 엔진은 평문을 수용하므로 360 한글판은 평문으로 넣는다.

### 컨테이너
- `packageInfo.pac` = TSK: 'TSK ', u32 개수, (u32 size, u32 ofs)×n, 엔트리 0x40 정렬, 꼬리 0x40 정렬. XMB 2개(resource.xmb·텍스트) + eqp 2개. 무수정 재조립 = 원본 동일을 매번 검사.
- 라이브 가사는 `dance\dan_<곡>_{1,3,5}.mpc` 내장 XMB(§28-2)이고, songinfo 가사 XMB도 함께 바꾼다. dance pac 재조립은 dance_lyrics.parse_pac/rebuild_pac를 재사용한다(비가사 엔트리 바이트 불변 검증).

### 번역 매칭
- `dlc_translations.json`의 meta.src(파일·XMB 번호) + id 서수로 찾되, **원문(jp)이 일치할 때만** 교체한다. 없으면 같은 그룹의 같은 원문 번역을 쓴다(원문일치).
- 가사는 xmb_translations `songinfo/<곡>` + dlc songinfo 행을 id로 찾고, jp가 다르면 건너뛴다. PS3 iwt 8줄이 360과 원문이 달라 일본어로 남는다.
- 360(PC 포트) = 원시 한글(직접 등록 폰트). PS3 = font_mapping 인코딩(가사 한글 633자 전부 매핑 있음). PUA 이모티콘·치환 코드는 그대로 둔다.

### 결과 (10-23 02:27 회수분 기준)
- 360: `Desktop\imas2dlc\content_kor`(원본 content 전체 사본, 원본 불변). 49개 파일, 가사 1,220칸. 카탈로그·메일·패키지는 웹앱 번역 0행이라 미적용.
- PC 포트 인게임(1배, gpu_run.lock): `IMAS2PC_DLC_ROOT=content_kor` + `IMAS2PC_DISC_ROOT=imas2pc\game_kor`(한글 폰트)로 S4U Little Match Girl 라이브 가사가 한국어로 나온다("어른이 되지 못한 채 얼어붙은 나날은" 등). game_kor 없이 기준선 game으로 띄우면 글리프가 없어 `???`로 나온다.
- PS3: 순정 백업 `Desktop\imas2_image_text\ps3_dlc_orig`(대상 136개, sha 매니페스트, 이후 build는 여기서만 읽음) → 재암호화본 `out_dlc_ps3`(46개: 가사 954칸 + ranker 6). 재복호화 = 주입 평문 게이트 통과. **RPCS3 dlc에는 아직 배포 안 함**(RPCS3 인게임 확인과 평문 수용 시험은 사용자 실행 필요).

### 원천 공백 (coverage)
- PS3 catalog_info 916칸 중 385칸(43%)과 PS3 전용 15곡 가사(age ali daz ful gm2 ki2 mah mlt omo pm9 pos pre sh2 wat wim)는 웹앱에 원문 행이 없다. dlc_text.py가 PS3에서 packageInfo·mail·ranker만 추출했기 때문이다. 추출 보강은 ui-image-extract 쪽 과제다.

## 36. 웹앱 플랫폼 표시 사양(KOR) + 전체 검색 + 치환 코드 입력 (2026-10-23, 로컬 커밋 — 배포는 사용자 OK 대기)
- 배지: 공통 없음 / PS3 파랑 "PS3" / 360 초록 "360", 표는 상태 열 위, 카드·가사는 제목 줄 오른쪽 끝(툴팁 plat_note).
  필터 "플랫폼: 전체 / 공통 / PS3 전용 / 360 전용". 사이드바 소분류 옆 "PS3 n · 360 n"(platform_audit.py counts →
  platform_counts.json → webapp_build META.plat_counts).
- 다른 판: meta.pair(platform_audit.py pair) — gamedata 83쌍(같은 파일·같은 id, 판별 문구 다름), DLC '#ps3'↔본 행 22쌍,
  이미지 7쌍(튜토리얼 카드). "다른 판 보기" 토글 → 상대 판 원문·번역, 상대 번역이 있으면 "그 번역 가져오기"(누를 때만 저장).
  script의 문구만 다른 공통 103줄은 행 하나(360 문구만 표시, 번역 공유) — 360 빌드가 PS3 행 번역을 이식하므로 분리 안 함(KOR에 제안).
- 그림 짝은 한 파일에 PS3 미대응 1장·360 전용 1장·같은 치수일 때만. 축소 흑백 상관 짝짓기는 짧은 라벨에서 오답
  (システム設定2↔システム設定, つづきから↔アップロード, お守りINFO↔お守りGET) → 폐기, DB의 잘못된 4쌍 제거.
  짝 그림은 PS3판 행 바로 밑에 360판 행을 붙여 한 묶음(배경색), 작업본은 판별로 따로, 치수 같으면 "○판 작업본 복사".
- 적용 범위: 편집칸·카드 아래 "이 번역이 들어가는 곳: PS3 한글 패치 / PC 포트(360)".
- DLC 가사 '#ps3' 줄은 "곡 (PS3판 문구)" 별도 카드(같은 곡 카드에 섞이면 줄 수가 어긋남).
- 전체 검색(사이드바 "전체 검색"): 모든 분류 jp/kr ilike, 분류 선택, 300건 상한, 배지·키 표시, 누르면 해당 소분류+키로 이동.
- 치환 코드 입력: 원문에 든 코드만 칩 버튼(편집칸·카드 아래), 누르면 같은 칸 입력칸 커서 위치에 삽입.
- 주소 딥링크 #/<분류>/<소분류>[/<검색어>][!open](다른 판 펼침).
- 스크린샷: KOR 노트 webapp_platform_image_pair.png / webapp_platform_text_pair.png (로컬 빌드, headless Edge).
- PS3 DLC catalog_info 원문 보강(KOR·pc-360-dlc): dlc_inject coverage에서 PS3 catalog 916칸 중 385칸 원문 없음 →
  catalog 그룹에 없는 고유 원문 295개를 행으로 추가(키 catalog_cpNN:x0.<id>, meta.src 해당 원문이 나오는 cp 위치 전부,
  plat ps3). 같은 원문은 한 행(주입기의 원문 일치 적용으로 전 칸 커버). dlc_texts.json 295 + DB 신규 104(191은 앞 단계에서
  먼저 추가, ignore-duplicates). coverage 재확인: PS3 catalog 916/916(100%), 전 플랫폼·그룹 원문 100%.

## 37. 웹앱 번역 회수 → game_kor 반영 + 게임 데이터 텍스트 주입기 (2026-10-23 03:0x~03:23, 사용자 지시)
- 회수: script(translation_webapp_20261023_0311.xlsx, translation_2 대비 1셀 변경, 360 전용 번역 0), xmb(변경 0),
  image(작업본 167개 → PNG 321장), gamedata(웹앱에서 직접, 번역 2,251행 — 시스템 메시지 초벌 711행 포함).
- 스크립트: pcport360 build `--excel` 옵션 추가 → 회수본으로 1,097개 빌드 → deploy_pcport --src360(게이트 통과) → game_kor.
- 이미지·NPC XMB·가사: pcport_apply build/deploy 71개 → game_kor(백업 game_kor_backup_20261023_031600).
- **게임 데이터 텍스트 주입기 tools/image_text/gamedata_apply.py** (새):
  - 기준 = game_kor 현재 파일(폰트 주입 initialFix·이미지 보존), 칸 결정 = 360 원본의 같은 구조 위치.
    번역 있으면 한국어, 없으면 원본 일본어 → 반복 실행해도 같은 결과. NPC·가사 id 접두는 제외(다른 도구 담당).
  - 컨테이너 재귀: pac → TSK(dlc_inject.tsk_parse/tsk_build) → XMB(rebuild_xmb). alf_audi·PauseMenu·initialTemp 등은
    XMB가 TSK 안에 있음.
  - 무수정 왕복 19/19 파일 바이트 동일 → 빌드 한국어 2,658칸(일본어 유지: staff_roll 674·fan_letter 722 등 미번역) →
    검증(비대상 항목·칸·attr 구조 불변) 통과, 폰트 매핑 밖 한글 0 → game_kor 배포(백업 game_kor_backup_gamedata_20261023_032308).
  - initialFix 10,602,976→10,604,016B(+1,040B) — 부팅 로드 영향은 인게임 확인 필요.
- **pcport_apply.parse_pac 버그 수정**: 데이터 시작을 (파일 길이 − 마지막 항목 끝)으로 구해, 꼬리 패딩(4~28B)이 있는
  360 pac 53개(전 155개 중)에서 어긋났음 → 헤더 +0x38 사용. rebuild_pac은 원본 꼬리 바이트 보존. (이전 배포의 NPC 표 파일은
  꼬리 0이라 영향 없었음 — 당시 비대상 항목 불변 검증 통과.)
- 순서 규칙: pcport_apply deploy는 같은 파일을 원본에서 다시 만들므로, 그 뒤에는 gamedata_apply를 다시 돌린다(deploy 끝에 안내 출력).

## 38. 구글 시트 → 웹앱 병합 드라이런 (2026-10-23, KOR 전달·사용자 질문, DB 쓰기 없음)
- 도구 tools/image_text/sheet_merge.py dryrun: 시트별 열 구조 차이를 머리글로 판별(번역문·Gemini, 경로는 .scb 값으로 탐지,
  Gemini 수식은 캐시값). 대응: (시트 접두, 파일:오프셋)+원문 일치 45,504 / 파일 안 원문 정렬 재매칭 419 / 못 찾음 572.
- 서버 최신 기준 분류(사람 9,958·Gemini 41,249행): 사람 = 웹과 같음 6,272(완전 동일 966, 부호·개행만 다름 5,306),
  기계→사람 교체 후보 3,309, 충돌 1(팀 편집 행), 빈칸 채움 0 / Gemini = 웹과 같음 2,250, 대안 29,211, 빈칸 채움 0.
  못 찾음 572(사람 376·Gemini만 196) 중 192는 구 추출기 경계로 잘린 조각(웹 원문의 일부).
- 교체 후보 중 「」 빠짐 607, 개행 빠짐 1,768. excel2scb rewrap이 개행을 풀고 다시 감싸므로 개행은 빌드에 무해,
  「」는 자동 보정 안 됨. 시트 화자 라벨 '○○達' 666행(사람 번역 107).
- 시트 공개 내보내기(export?format=xlsx) 로그인 없이 받아짐 → 단방향 정기 가져오기 가능. 보고서 Desktop\imas2_image_text\sheet_merge\dryrun.json.
- **실행 반영(03:38, KOR 전달 사용자 승인 "암튼 ㅇㅇ")**: sheet_merge.py sync — 기계→사람 교체 3,309(「」 자동 보정 607,
  meta.merge_note), 이전 kr은 meta.prev_kr + hist(by "기계번역(교체 전)") 3,309줄로 보존, 새 kr hist(by "구글시트") 3,309줄.
  Gemini 대안 29,211행 meta.alt(kr 불변), 문장부호·개행만 다른 5,306행은 웹 유지, 충돌 1(팀 편집)·못 찾음 572·재매칭 419는
  Desktop\imas2_image_text\sheet_merge\conflicts.json / unmatched_manual.json / realigned.json. 재실행 드라이런 = 변경 0(멱등).
  출처 meta.src_tr: script 전 행(human_sheet / machine_init 42,809 / team) + 다른 분류(team / claude 711 / seed).
  sync는 공유 링크 xlsx를 직접 받아 같은 규칙으로 증분 반영(스케줄러는 미설정 — 시트 계속 사용 여부 미정).
- 웹 UI(로컬 커밋, 배포는 사용자 OK 후): 출처 배지·필터, Gemini 대안 보기·가져오기, script '개행' 경고를 회색 안내로
  (빌드 rewrap), '「」 다름' 경고, 웹 편집 시 src_tr=team. platform_audit.fetch_rows는 분류별 읽기(meta 커진 뒤 전체 order=id 500).

## 39. 실행 파일 하드코딩 문구 → 웹앱 'exe' 분류 (2026-10-23, KOR·사용자 "社長 이름표 검색이 힘들었다")
- tools/image_text/xex_text.py: 360 default_unpacked.xex 0xB8000~0xD0000의 UTF-16BE 문자열(Shift-JIS 1수준 한자 필터,
  1자는 이웃 문자열이 있을 때만, U+8000·반각 가나 쓰레기 제외) 201개 → exe_texts.json → 웹 행(cat exe, grp xex360,
  meta offset·slot·cap·plat x360, "주입 경로 준비 중(실행 파일 패치 필요)"). 화자 이름표 0xB924C~0xB9388(審査員…社長·小鳥·Ｐ…春香),
  이름 입력·저장·일시정지·どっとっぷTV·S4U 설정 저장·지역명 등. 개발용 더미 문구(だみーゆにっと 등)도 포함.
- 웹: 사이드바 '실행 파일 문구', 슬롯 초과 경고(cap = 다음 문자열까지 바이트 기준 추정), 전체 검색에 포함('社長' → exe 행 검색됨).

## 40. 누락 일본어 전수 조사 + 웹앱 등록 + 주입 커버리지 (2026-10-23 04~05시, KOR "누락된 거 다 찾아서 웹앱에 넣어라")
- tools/image_text/coverage_scan.py: PS3 본편(gscript는 순정 백업)·PS3 DLC·360 본편·360 DLC·xex·PS3 EBOOT(rpcs3 --decrypt
  사본, 정적 읽기만) 전부를 pac/TSK 재귀 → XMB·SCB는 구조로, 나머지는 원시 스캔. find_text 스냅샷과 대조.
  결과: 고유 56,099 = 웹앱에 있음 53,118 + 웹 원문의 일부 91 + 제외 2,890(이름 입력 키보드 사전 2,051, 기계어 조각 823,
  디버그 라벨 16), **미분류 0**. 게임 폴더 작업 사본(attract.mpc.orig, PauseMenu.mpc1)은 스캔 제외.
- 추가된 웹 행(ignore-duplicates, 팀 번역 불변):
  - 360 대사 중 원문이 PS3와 조금 다른 짝 103줄(○→A ボタン, Ｌ１→LB, 문구 수정) — 지금까지 PS3 번역이 그대로 들어갔다.
    script 행 x360:<파일>#<idx>, meta.approx·suggest(PS3 원문/번역). pcport360 build는 이 행 번역이 있으면 우선 적용.
  - 360 NPC 명단에서 같은 id에 PS3와 다른 이름이 든 43칸(NPCP_123 フィガロ→リョウコ姫 등) → xmb:exep_init:x360:<id>.
    **버그 수정**: pcport_apply가 id만 보고 PS3 번역을 넣어 game_kor에 엉뚱한 이름이 들어가 있었다 → npc_kr_for
    (원문 일치 PS3 번역 > 360 전용 번역 > 같은 원문 번역 > 일본어 유지). webapp_pull xmb는 x360: 키를 'scene/exep_init.mpc@x360'로.
  - 실행 파일(xex_text.py 확장): PS3 EBOOT 전용 56행(eboot_ps3 — 세이브 사용자 불일치 오류, 새 세이브 생성, PSN 상태,
    그라비아 스테이지명 SJIS 표 등), 360 XDBF 업적·접속 상태 171행(xdbf360, 화면 미표시), xex 누락 7행(앞 바이트가 붙어
    통째로 버려지던 スピードを上げろ！·ランキングに登録 등 — 앞 쓰레기 글자만 떼도록 수정). 기존 xex 행 157개에 같은 문구의
    PS3 EBOOT 위치(meta.eboot)를 붙여 plat=common.
- 이미지: CN 패치가 안 건드려 행이 없던 텍스트형 텍스처 414장을 시트로 육안 점검 → 일본어 33장(exep_commu 현 이름 24,
  스태프롤 'CV:성우명' 6, les_mar ペースUP中·DOWN中·765プロ) → image_extra.json, webapp_seed.image_index가 포함.
  행 등록은 썸네일 업로드(서비스 키) 후.
- **주입 커버리지**(coverage_scan injection.json): 웹앱에 문구가 있어도 그 위치를 쓰는 주입기가 없으면 화면은 일본어.
  2,570곳 중 30곳 4,637문구가 주입기 없음:
  1. PS3 게임 데이터 XMB 20파일 약 4,200문구(initialFix 1,367·fan_letter 694·ScheduleSelect 626·staff_roll 357…) —
     gamedata_apply는 360(game_kor) 전용이라 PS3 패치엔 아예 안 들어가 있었다.
  2. gscript 밖 pac 속 내장 SCB(구조는 gscript dec와 같음: pac 데이터 0x80 → [SCB, 컷씬 pac]) — member_select 소개 대사 9개
     45줄, ScheduleSelect 120, dress_select 42, mail_produce 2, attract(360). PS3 attract만 patch_attract.py(§20)로 처리돼 있었다.
     → gamedata_apply에 내장 SCB 주입 추가(게임 스크립트 행 번역을 원문 일치, excel2scb rewrap·MSG 재작성, validate_dec 게이트,
     컷씬 pac 불변 검사). 360만. PS3는 리소스 주입 경로 신설 필요(1번과 함께).
  3. 360 initialTemp.mpc 라이벌 유닛 프리셋 26문구 — 확인 결과 gamedata_apply.targets()가 원문 일치로 이미 처리(22칸 한국어).
- 360 내장 SCB 시험 빌드: member_select 45/45, ScheduleSelect 107/121, dress_select 36/41, attract 10/12, mail_produce 3/3
  한국어(나머지는 같은 원문의 게임 스크립트 번역이 없음).
