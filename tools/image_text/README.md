# image_text — UI/메뉴 이미지 텍스트 추출

메뉴·UI·튜토리얼에 **비트맵 이미지로 박힌 일본어 텍스트**를 PNG로 뽑아
이미지 작업자(포토샵)에게 넘기는 도구. 재주입(PNG→게임)은 다음 단계로, 아직 미구현.

```bash
python tools/image_text/extract_image_text.py              # 전체 (56개 파일)
python tools/image_text/extract_image_text.py --only title # 상대경로 부분일치 필터
python tools/image_text/extract_image_text.py --no-sheets  # 검수 시트 생략
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

## 재주입(다음 단계) 설계 메모

index.md의 "재주입 시 주의점" 참조. 핵심: 같은 포맷·같은 크기로 재인코딩해
`data_off`(index.json)에 그대로 덮으면 pac/NUT 구조를 건드릴 필요가 없다.
중국팀 패치는 암호화 파일을 전부 **복호화 상태로 배포** — 평문 교체가 통하는
것으로 보이나 인게임 1회 검증 후 전체 적용할 것.
