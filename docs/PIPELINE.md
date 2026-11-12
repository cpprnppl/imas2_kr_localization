# iM@S2 한글화 파이프라인 (AI-native SDLC 적용판)

[Claude AI-native SDLC 플레이북](https://claude.com/ko/resources/articles/the-ai-native-sdlc-playbook)의
제안을 1인 + AI 에이전트 규모의 팬 한글화 프로젝트에 맞게 축소 적용한 것.

핵심 원칙 3개만 가져온다:
1. **단계마다 버전 관리되는 산출물** — 다음 단계(혹은 다음 세션의 AI)가 읽을 수 있게.
2. **사람 리뷰 대신 자동화된 게이트** — 구조 검증을 통과해야만 배포 가능.
3. **같은 실수 2번 반복 금지** — 사고가 나면 CLAUDE.md/워크로그에 교정 내용을 환원.

## 단계와 산출물

| 단계 | 산출물 (버전 관리) | 게이트 |
|---|---|---|
| 번역 추출 | `scb2excel.py` → 번역 Excel (새 버전은 새 파일명) | 기존 번역 보존 확인 |
| 번역 | Excel C열 (Gemini/GPT + 수동 검수) | 검수 체크리스트 (문장부호/줄바꿈/형식) |
| 패치 | `excel2scb.py` → `output/` | 매칭 실패 경고 확인 |
| 검증 | `validate_output.py` 결과 | **구조 오류 0건 (필수)** |
| 배포 | `deploy.py` (검증 내장) | 검증 통과 시에만 복사 + 무결성 확인 |
| 게임 테스트 | 워크로그에 결과 기록 | 대사/화자/음성/컷씬/진행 전부 정상 |

## 가드레일 (훅)
- `gscript - 복사본`(순정 백업) 쓰기 차단 — `.claude/settings.json` PreToolUse 훅.
- 배포는 `deploy.py` 경유만. (수동 cp는 검증을 우회하므로 금지 규칙)

## 단일 원천 (single source of truth)
- SCB 도구: **이 레포 `tools/scb/`가 원천**. `sync_to_game.py`로 게임 폴더에 배포.
- 번역 데이터: 게임 tools 폴더의 Excel (대용량이라 레포 밖, 필요 시 수동 백업).
- 프로젝트 이력: `imas2_korean_patch_worklog.md`.
- PC 리컴프: `Desktop\imas2pc`의 `PROJECT_STATUS.md`가 그쪽 원천.

## 검증 피드백 루프 (에이전트 작업 규칙)
- 패치 코드를 수정하면: 단일 파일 패치 → validate → (가능하면) 무수정 round-trip 테스트까지 돌리고 결과를 보고한다. "코드가 실행된다 ≠ 게임에서 정상 동작".
- 버그 수정 시: 먼저 실패를 재현하는 검사(진단 스크립트)를 만들어 원인을 확정한 뒤 고친다 (이번 pac 헤더 사고의 교훈).
- 인게임 크래시 발생 시: RPCS3 `log\RPCS3.log`의 `·F` 라인부터 확인.

## 반영하지 않은 것 (규모에 안 맞음)
- CI 상의 지속 평가(evals), DORA 지표, 엔터프라이즈 관리형 설정, PR 리뷰 루프
  — 1인 프로젝트라 비용 대비 효과 없음. 협업자가 생기면 재검토.

## 주의: `ps3_res_orig`는 '빌드 기준본'이다 (2026-11-09)
- `Desktop\imas2_image_text\ps3_res_orig`(ps3_res_apply·gamedata_apply --plat ps3의 '순정 사본')는 **텍스트는 순정(한글 0)이지만, initialFix·initialTemp는 우리 폰트(NFH/NUT)가 주입된 상태가 기준**이다(FONT_INJECTED). 폰트를 다시 만들면 이 사본의 initialFix에도 같은 NFH를 넣고 manifest sha를 갱신해야 한다(안 하면 ps3_res_apply validate가 막고, 빌드는 옛 폰트로 되돌린다).
- 진짜 순정: 폰트 원본 = `USRDIR\_backup\im2_font*_20260223_*.nfh/nut`(repatch_fonts PRISTINE, md5 고정). PS3 initialFix 원본 파일은 로컬에 따로 없다(가장 이른 `_backup_fontfix_20261012`도 이미 폰트 패치본) — 원본은 사용자 PSN 패키지/디스크 이미지.

## 그림 주입 규칙 (2026-11-12, 14판부터)
1. **블록 보존 인코드** — 모든 그림 경로(inject_image_text, ps3_res_apply.extra_images, dlc_inject PS3·360, pcport_apply)에서
   작업본과 원본의 차이를 화면 값(RGB×알파 + 알파)으로 비교해 >48(+3px 넓힘)인 곳만 작업본, 나머지는 원본 픽셀로 합성한 뒤 인코드하고,
   원본 디코드를 같은 인코더로 인코드한 결과와 블록이 같은 곳은 **원본 블록 바이트를 그대로** 쓴다. 완전 투명 픽셀의 RGB 차이는 안 센다.
   통째 재인코드는 금지 — 패치 diff에 원본 그림 전체가 실린다.
2. **평문 출력** — PS3에서 그림을 바꾼 암호화 파일(.nut·.s2d·.tsk, DLC 재킷·로고·catalog_info.nut)은 평문으로 낸다.
   원본 key·prefix·풋터로 재암호화한 NUT는 게임이 읽고도 그리지 않는다(빈 재킷, 13판까지의 버그). 글자만 바꾼 암호화 XMB는 재암호화 유지(화면 확인됨).
3. **이미지 게이트(pc-360-dlc)** — 텍스처마다 패치 diff 50% 이하. 예외는 **넓이 16,384px 이하 글자 라벨만**(공유 노트 image_gate_exceptions_{ps3,pc}_*.json).
   그림 위주 텍스처(타이틀, 팬레터 봉투, 스태프롤, 결과 화면, 카탈로그, 재킷·로고)가 블록 보존 뒤에도 50%를 넘으면 예외가 아니라
   **원본 유지**: tools/image_text/image_hold.json에 올리고(이유 포함) 모든 경로가 건너뛴다. JPEG(ad_bg.jpg)는 블록 보존이 안 돼 PS3에서도 원본.
   단 **글자만 있는 칸**(원본 내용도 글자뿐인 텍스처, 예: 스태프롤 크레딧 칸)은 32,768px(예: 512x64)까지 예외로 받는다 — 예외 항목에 `kind=text_cell`. 그림이 섞인 텍스처는 16,384px 그대로.
4. **웹앱 이미지 행 ↔ 주입 대조 게이트**(ps3_res_apply build·validate) — PS3 본편 위치에 행과 kr 작업본이 있는데 주입이 안 된 텍스처 = 실패.
   보류 목록 항목과 '작업본이 원본과 눈에 띄는 차이 없음'은 통과. image_extra.json 파일(index.json 밖)도 빌드 대상.
5. **배포에서 빠진 파일 원복** — ps3_res_apply deploy는 지난 배포에 있었는데 이번 산출에서 빠진 파일을 순정으로 되돌린다. dlc_inject는 restore-ps3 → deploy-ps3 순서.
