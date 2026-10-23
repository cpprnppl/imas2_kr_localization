# iM@S2 360 실기 한글 패치 (데이터판)

원본 360 ISO에서 **한글 게임 데이터·폰트를 넣은 새 ISO**를 만든다. 원본 ISO는 읽기만 한다.

## 전제 (가정)
- **실기 = RGH/JTAG 개조 360**으로 가정한다. 이 PC에서는 실기 시험을 할 수 없고, 실기 확인은 사용자가 한다.
- 디스크 데이터 파일은 서명 대상이 아니다. `Default.xex`는 **원본 그대로** 둔다(복호화·재서명 없음).
- 출력 형식은 XISO(게임 파티션만)다. iM@S1 360 패처(아래 출처)가 만드는 형식과 같다.

## 이번 판에 들어가지 않는 것 (사용자 결정 대기)
- **실행 파일(xex) 안의 문자열**(화자 이름표, 일시정지 메뉴, 스케줄·지역명 등)은 **일본어로 남는다.**
  - PC 포트에서는 실행 중에 패치한다(`kor_exe_strings.bin`). 실기용으로 xex에 고정하려면 xex를 복호화하고 서명 없이 다시 써야 한다. 그 처리 방식을 사용자가 결정하기 전까지 보류한다.
- **한글 DLC**(카탈로그 페이지, 곡 가사): 실기용 DLC 패키지(STFS)를 다시 만들어야 하므로 같은 이유로 보류한다. DLC는 원본을 그대로 쓰면 일본어로 나온다.
- **Vol.08 메인 메뉴 배너의 한글 로고**: PC 포트 전용 형식(IM2PCRAW)이라 실기에서는 쓸 수 없다. 원본 그림 그대로 나온다.

## 만드는 법 (이 PC)
```bash
python -I tools/x360_patch/build_iso.py "C:\Users\jackfilm\Desktop\imas2_360\Idolmaster 2, The (Japan).iso" "C:\Users\jackfilm\Desktop\imas2pc\game_kor" "C:\Users\jackfilm\Desktop\imas2_360_kor\Idolmaster 2, The (Japan) [KOR].iso"
```
- 원본 ISO의 파일 목록(3,136개)을 그대로 쓰고, 내용은 `game_kor`에서 가져온다. `game_kor`에만 있는 PC 포트 전용 파일·백업(`kor_exe_strings*`, `_backup*`, `_kor_backup`, `.orig_kor`)은 넣지 않는다.
- 다른 세션이 `game_kor`에 배포하는 중일 수 있어서, 먼저 `<출력>.stage\`로 사본을 뜬 뒤 그 사본으로 만든다.
- **검증**: 새 ISO에서 파일을 전부 다시 읽어 사본과 sha1을 비교한다(불일치 0이어야 종료 코드 0). 원본 ISO의 sha1은 전후로 비교한다.
  - 결과는 `<출력>.manifest.json`에 남는다: 파일별 sha1·출처, 원본 sha1 전/후, 출력 sha1.
- 무거운 작업이므로 GPU 측정 런이 `gpu_run.lock`을 쥐고 있을 때는 돌리지 않는다.

## 실기에 넣는 법 (사용자)
1. 만든 `[KOR].iso`를 평소 쓰는 방식으로 실기에 올린다.
   - 예: 가지고 있는 ISO→GOD 변환 도구로 GOD로 바꿔 HDD `Content\0000000000000000\4E4D0817\00007000\`에 넣는다.
   - 또는 ISO 내용을 풀어 HDD 폴더에 두고 대시보드/런처에서 `default.xex`를 실행한다.
2. 원본 디스크/원본 ISO와 세이브는 그대로 쓸 수 있다. 데이터만 바뀌고 세이브 형식은 같다.
3. 되돌리기: 원본 ISO(또는 원본 디스크)로 실행하면 된다. 원본 ISO는 패처가 수정하지 않는다.

## 파일
- `xdvdfs.py`: XDVDFS 읽기(목록/풀기). XGD1/2/3과 XISO의 파티션 위치를 자동으로 찾는다.
- `xiso_write.py`: XISO 쓰기. 디렉터리 항목은 대문자 이름 순 이진 트리로 만들고, 항목이 섹터 경계를 넘지 않게 한다. 속성값은 원본과 같다(파일 0x80, 폴더 0x90).
- `build_iso.py`: 위 두 개로 한글 ISO를 만들고 검증한다.

## 출처
- 방식 참고: iM@S1 360 한글 패처 https://github.com/rnrmfdlapdlf/xbox360-idolmaster-korean-patcher (MIT, © 2026 Gideon). 원본 ISO → `_repacked` ISO를 만드는 흐름과 XISO(exiso `-c`) 출력 형식을 참고했다. 코드는 복사하지 않았다.
- XDVDFS 형식: 공개된 형식 설명(extract-xiso 등이 쓰는 것)을 보고 새로 작성했다.
