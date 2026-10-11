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
python tools/image_text/xmb_text.py export-xlsx            # 번역팀용 엑셀 (게임 tools/)
python tools/image_text/xmb_text.py import-xlsx            # 엑셀 KR 열 → translations.json
python tools/image_text/xmb_text.py build                  # xmb_translations.json → patched/
```

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
- 번역 워크플로: `export-xlsx` → 게임 tools 폴더 `xmb_translation_1.xlsx`
  (시트 3개 1,030행, 기존 kr 제안은 노란 행) → 번역팀이 '한국어(KR)' 열 작성 →
  `import-xlsx` → `build`. 기존 파일이 있으면 덮지 않고 중단(--path로 새 이름).
- 고유명사 표기는 통용(나무위키/SideM) 기준: 아마가세 토우마·미타라이 쇼타·
  **이쥬인 호쿠토**·주피터. install 22건·ranker 4건 제안 기입 완료.
