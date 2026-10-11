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
