# image_text — UI/메뉴 이미지 텍스트 추출·재주입 + XMB 텍스트

메뉴·UI·튜토리얼에 **비트맵 이미지로 박힌 일본어 텍스트**를 PNG로 뽑아
이미지 작업자(포토샵)에게 넘기고, 작업된 한글 PNG를 다시 게임 파일에 주입하는 도구.

```bash
python tools/image_text/extract_image_text.py              # 추출: 전체 (56개 파일)
python tools/image_text/extract_image_text.py --only title # 상대경로 부분일치 필터
python tools/image_text/extract_image_text.py --no-sheets  # 검수 시트 생략
python tools/image_text/extract_image_text.py --reindex    # index.md만 재생성

python tools/image_text/inject_image_text.py --selftest    # CN 텍스처 505장 재주입 자가검증
python tools/image_text/inject_image_text.py               # <out>/kr/의 한글 PNG 주입

python tools/image_text/xmb_text.py dump                   # XMB 3종 텍스트 덤프
python tools/image_text/xmb_text.py export-xlsx            # 번역 엑셀 스냅샷 (게임 tools/)
python tools/image_text/xmb_text.py import-xlsx            # 엑셀 KR 열 → translations.json
python tools/image_text/xmb_text.py build                  # xmb_translations.json → patched/

python tools/image_text/label_tool.py                      # 라벨 한글화 UI (127.0.0.1:8765)
python tools/image_text/label_tool.py --export             # UI 없이 스펙 전체 렌더 → kr/

python tools/image_text/webapp_build.py                    # iM@S2 KOR 웹앱 빌드 → webapp_deploy/
python tools/image_text/webapp_seed.py --code <암호>       # Supabase rows 시딩 (기존 행 보호)
python tools/image_text/webapp_seed.py --thumbs --service-key <sb_secret>  # 썸네일 업로드
python tools/image_text/webapp_pull.py xmb|script|image --code <암호>      # 번역 회수
python tools/image_text/dlc_inject.py build360                       # DLC 한글판 사본 content_kor (PC 포트, 평문)
python tools/image_text/dlc_inject.py coverage                       # DLC 원문 존재율 / kr 적용률 (360·PS3)
python tools/image_text/dlc_inject.py build-ps3 | deploy-ps3 | restore-ps3   # PS3 DLC 재암호화본 (RPCS3)
python tools/image_text/exe_inject.py build360 | deploy360               # 실행 파일 문구 → game_kor\kor_exe_strings.bin (PC 포트)
python tools/image_text/exe_inject.py build-ps3 | install-ps3 | uninstall-ps3   # 실행 파일 문구 → RPCS3 patch.yml (상시 적용)
```

## iM@S2 KOR 번역 플랫폼 (imas2.buyeo.uk)

팀 협업 웹앱. PatternFly UI, 정적 페이지(Vercel) + Supabase(rows/hist, RLS 팀 암호).

- 대분류 3단: **XMB 텍스트**(1,030행) / **게임 스크립트**(translation_2.xlsx 52,240행,
  시트별 소분류) / **이미지 텍스트**(md5 그룹 333건, JP/CN 썸네일 보며 문구 입력)
- 행별 [번역]→[검수] 체크, 미번역·개행·길이·**폰트 매핑 미보유 글자** 경고,
  XMB 용량 미터. 모든 저장은 hist(append-only)에 기록 — 행별 🕘 이력,
  "수정 이력" 메뉴에서 작업자/날짜별 조회.
- 접근: 참여 암호(디스코드 공지) — Supabase RLS가 헤더로 검증, 페이지엔 암호 없음.
- 배포: GitHub push → Vercel 자동 재배포 (Root = tools/image_text/webapp_deploy).
  데이터 흐름: `webapp_seed.py`(시딩, ignore-duplicates) → 팀 작업 →
  `webapp_pull.py`(xmb→translations.json / script→새 xlsx 스냅샷 / image→label_specs).
- 스키마/암호: `supabase_setup.sql` (암호 변경 = team_ok 함수 재실행).

산출물: `C:\Users\jackfilm\Desktop\imas2_image_text\` (`--out`으로 변경 가능)

```
jp/<상대경로>/<파일명>_<nnn>.png   일본어 원본 텍스처 = 작업 대상
cn_ref/<상대경로>/...             중국팀 번역본, 같은 번호 = 같은 텍스처 (참고)
_review/<경로플랫>.png            JP|CN 나란히 눈검수 시트 (체커보드 = 알파)
_cache/jp|cn/...                  복호화 사본 (게임 원본은 절대 건드리지 않음)
index.md / index.json             파일별 결과 + 재주입 주의점 / 오프셋 포함 상세
```

## 대상 인벤토리

중국팀 패치 폴더(`Desktop\偶像大师2汉化补丁\games\...\resource`)에서
`gscript/`·`initialFix.mpc`·`initialTemp.mpc`를 제외한 전 파일(56개)
= "중국팀이 수정한 = 이미지 텍스트가 있는 파일" 목록. JP 원본은
`NPJB00337\USRDIR\resource`의 동일 상대경로에서 읽는다 (**읽기 전용**).

## 포맷 요점 (실측 확인)

- 컨테이너: `.mpc`=pac, `.s2d`=TSK(안에 NUT), `.nut`=NTP3 단독, `.tsk`/`.xmb`도
  'NTP3' 시그니처 스캔으로 카빙. pac 엔트리 테이블 해석은 불안정해 쓰지 않는다.
- NUT: `NTP3` 헤더 후 텍스처마다 `[80B 헤더][데이터]` 인터리브 연속.
  NUT 크기 = 16 + Σtotal. 헤더 +0x30 `eXt\0`, +0x40 `GIDX` 마커로 검증.
- 텍스처 헤더: +0 total, +8 dataSize, +0x11 mip, +0x13 fmt, +0x14 w, +0x16 h.
- fmt: 0=DXT1(½B/px), 1=DXT3(1B/px), 2=DXT5(1B/px), 14=ARGB8888 빅엔디언(4B/px).
  DXT 블록 내부는 표준 리틀엔디언.
- 암호화: 선두가 pac/NTP3/TSK/XMB가 아니면 암호화본(+80B 헤더).
  `Imas2ToolS\misc\imas2dec\imas2dec.exe`로 사본만 복호화
  (CWD=파일 폴더, 'Finished' 후 프로세스가 안 죽어 타임아웃 kill — 워크로그 §8).

## 재주입 — inject_image_text.py

이미지 작업자가 한글 PNG를 `<out>/kr/<상대경로>/<파일명>_<nnn>.png`(jp/와 같은
이름)로 넣으면, 같은 포맷·같은 크기로 재인코딩해 `data_off`에 제자리 덮어쓰고
`<out>/patched/`에 산출한다. pac/NUT 구조 불변, 게임 원본 불변.

- 인코더: DXT1/3/5(range-fit + 최소자승 끝점 정제 2회), RGB565, ARGB4444, ARGB8888
- 검증 게이트(실패 시 산출 안 함): ① 크기·주입영역 밖 바이트 불변 ② NUT 재파싱
  구조 일치 ③ 재디코드 vs 입력 PNG (무손실 포맷 완전일치, DXT PSNR≥33dB)
- `--selftest`: CN 수정 텍스처 505장을 전부 주입해 보는 파이프라인 검증.
  2026-10-12 기준 50/50 파일 통과(DXT 36.8~61dB, raw 무손실).
- **배포는 수동**: patched/ 확인 후 게임 폴더에 복사(백업 필수). 암호화였던
  파일(.s2d/.nut/.tsk/.xmb)의 평문 교체 가부는 인게임 1회 검증 먼저
  (중국팀 패치가 전부 평문 배포라 통할 것으로 보임).

## XMB 텍스트 — xmb_text.py

텍스처가 아닌 텍스트 테이블 3종: `text/install.xmb`(설치/트로피 메시지 23),
`ranker/ranker_npc.xmb`(NPC 유닛명 5), `scene/exep_init.mpc` 내장 XMB(NPC
프로듀서/유닛/곡명 등 1,002 — JP≠CN 867). 구조는 xmb_text.py 도크스트링 참조.

- `dump` → `xmb_texts.json`(jp/cn 대조) + `xmb_translations.json`(kr 채우는 틀)
- `build` → kr이 채워진 항목만 교체해 `patched/`에 산출. 파일 크기 불변(값 섹션
  초과 시 오류), 재파싱 검증 내장. 기본으로 **한글→한자 슬롯 폰트 매핑 인코딩**
  적용(`--no-font-mapping`으로 끔) — CN 패치도 매핑 한자로 저장돼 있어 XMB
  텍스트가 게임 폰트로 렌더됨을 확인함.
- **번역 협업은 웹앱이 1차 경로**: https://claude.ai/artifact/Y4sPGWzDHu4JfGigo8Bwc5
  (아티팩트, 1,030행 내장 + 공유 DB). 팀원이 행별로 한국어 입력, [번역]→[검수]
  체크, 미번역/개행 불일치/길이/폰트 매핑 미보유 경고와 파일별 용량 미터 제공.
  편집은 claude.ai 로그인 + 공유에서 편집 권한 필요. 회수는 Claude가 아티팩트
  DB를 읽어 xmb_translations.json에 반영(수정분은 DB가 원본, 페이지 내장값은
  초기 제안). HTML 재생성은 `webapp_build.py` + webapp_template.html.
- `export-xlsx`/`import-xlsx`는 스냅샷·백업 경로로 유지 (게임 tools
  `xmb_translation_1.xlsx`, 기존 파일은 덮지 않음).
- 고유명사 표기는 통용(나무위키/SideM) 기준: 아마가세 토우마·미타라이 쇼타·
  **이쥬인 호쿠토**·주피터. install 22건·ranker 4건 제안 기입 완료.

## 라벨 한글화 — label_tool.py

CN 수정 텍스처를 **md5 그룹(중복 제거, 333개)** 단위로 다루는 로컬 웹 UI.
텍스트·폰트·크기·채움/외곽선/글로우·자간·정렬을 지정하면 JP/CN/KR 미리보기에
즉시 반영되고, 스타일은 프리셋으로 여러 텍스처에 공유한다. '자동 맞춤'이
도도부현처럼 좁은 칸에서 글자 크기를 칸에 맞게 줄인다. 미리보기와 내보내기가
같은 PIL 렌더러라 **보이는 그대로 PNG가 나온다**.

- 스펙: `label_specs.json` (레포 커밋 대상 — 작업 진행 상태의 원본)
- 내보내기: 그룹당 1회 렌더 → 같은 md5의 **모든 위치**에 PNG 복제(kr/) →
  `inject_image_text.py`가 게이트 검증 후 patched/ 생성
- 전면 안내판(튜토리얼 카드, 스케줄 안내판 등) 등 합성이 필요한 텍스처는
  모드를 '수동(포토샵)'으로 표시하고 kr/에 직접 PNG를 넣는다.
