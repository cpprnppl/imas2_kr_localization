# iM@S2 한글화 프로젝트

PS3판 THE iDOLM@STER 2 (NPJB00337) 한글 패치. 폰트 패치 + SCB 스크립트 번역 + (병행) 360판 PC 리컴파일.

## 경로 (이 레포 밖의 작업 대상)
- 게임: `C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript`
- 실행용 도구: 위 경로의 `tools\` — **원천은 이 레포의 `tools/scb/`**, `sync_to_game.py`로 배포
- 순정 SCB 백업: `...\USRDIR\gscript - 복사본` — **읽기 전용. 절대 수정/삭제 금지**
- 번역 Excel: 게임 tools 폴더의 `translation_1_with_entry.xlsx` (차기: `translation_2.xlsx`)

## 명령 (게임 tools 폴더에서 실행)
```bash
python excel2scb.py                  # 전체 패치 (원본은 항상 순정 백업에서 읽음)
python excel2scb.py <특정.scb>       # 단일 파일 패치
python validate_output.py            # 산출물 전수 구조 검증
python deploy.py                     # 검증 통과 시에만 게임 폴더 배포 (게이트)
```

## 절대 규칙
1. **원본 SCB는 순정 백업에서만 읽는다.** 게임 폴더의 SCB는 패치본일 수 있다 — 거기서 읽어 재패치하면 오염 사고(과거 mam_w01_01 사태).
2. **검증 없이 배포하지 않는다.** `deploy.py`가 게이트. 수동 `cp` 배포 금지.
3. **in-place 문자열 확장 금지.** MSG는 반드시 테이블 리빌드(excel2scb 방식). `expand_text_entry`/`patch_text_entry`는 폐기된 방식.
4. **MSG 크기가 변하면 pac 헤더 4필드도 갱신** (+0x08, +0x88, rec0 size, rec1 ofs) — excel2scb가 처리함. 새 도구를 만들 때도 동일 규칙.
5. 기존 번역 Excel을 덮어쓰지 않는다. 새 산출물은 새 파일명으로.

## 의존성
- Python 패키지: `pycryptodome`, `openpyxl`, `kiwipiepy`(띄어쓰기 교정 — 없어도 동작하나 품질 저하)
- 파이썬이 2개 설치돼 있음: `python` = AppData\Local\Python(작업용, 패키지 여기 설치), `pip` 단독 실행 시 C:\Python314로 갈 수 있으니 **`python -m pip`** 사용

## 자주 틀리는 부분
- MSG 본문 base는 `msg_abs+0x30+count*8+pad16`. 고정 `+0x60` 아님 (구버전 스트림 파서의 오류).
- dec 파일은 `pac` 컨테이너 (SCB + 컷씬 pac). SCB만 있다고 가정하지 말 것.
- 대사 한 줄 원본 최대 116바이트(≈57자) — 게임 고정 버퍼 가능성. 긴 번역문 관련 문제 시 이것부터 의심.
- 폰트 매핑(한글→한자 슬롯) 미적용 한글은 게임에서 빈 글리프. 현재 매핑 2,359자(2026-10-12 큿큥햣쌰겍츗 추가, 워크로그 §18). 폰트 재생성은 `font_patcher/repatch_fonts.py`(구 GUI font_patcher.py는 폐기 — NFH 필드 +8/+16 미갱신·font_l 레이아웃 오해석 버그).
- RPCS3 랜덤 부팅 크래시(NU::Draw::RequestManager)는 게임 스레드 경합 — 패치 문제 아님.

## 작업 이력/계획
- 상세 이력: `imas2_korean_patch_worklog.md` (의미 있는 발견/변경은 반드시 여기 기록)
- 파이프라인/게이트 정의: `docs/PIPELINE.md`
