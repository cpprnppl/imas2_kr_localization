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
