# THE iDOLM@STER 2 한글화 정보

아이돌마스터 2 (THE iDOLM@STER 2) 한글 패치 제작을 위한 파일 구조 분석 및 기술 정보 기록용 저장소입니다. 

## 🎮 타겟 플랫폼
본 작업은 **PS3판 (NPJB00337)**을 기준으로 진행됩니다.
* **PS3 (RPCS3):**  Accurate DFMA 비활성화(custom config 사용), liblv2.sprx & libsysutil_np.sprx 로드시 정상 기동 ([The Idolm@ster 2 [NPJB00337]](https://forums.rpcs3.net/thread-202134.html))
* **Xbox 360 (Xenia):** 에뮬레이터에서 오디오가 정상적으로 출력되지 않는 등의 문제로 정상 플레이 불가 ([xenia-project/game-compatibility #19](https://github.com/xenia-project/game-compatibility/issues/19))

---

## 🛠️ 파일 구조 및 진행 상황

### 1. 에셋 언팩/리팩
* 게임 내 에셋들(*.mpc)에 AES 암호화가 적용되어 있습니다. (PS3판과 XBOX판의 복호화용 테이블이 다릅니다)
* 복호화 가능하며, 그 상태로도 게임에 로드됩니다. (참고: [spiral6/idolmasterSCBParser](https://github.com/spiral6/idolmasterSCBParser))
* ([Imas2ToolS](https://github.com/Waldenth/Imas2ToolS))로 복호화된 mpc파일의 수정이 가능합니다. 

### 2. 대사 스크립트
* 복호화된 스크립트 파일은 추출하여 변환되는 것까지 확인되었습니다.

### 3. 글꼴
* 전작과 동일하게 `initialFix`, `initialTemp` 내부에 각각 `.nut` (이미지)과 `.nfh` (메타데이터) 형태로 존재합니다. 
* 큰 이미지 1장으로 구성된 버전과 전작처럼 여러 장의 이미지로 쪼개진 버전이 함께 있습니다. 
* 문자셋 문제로 한글 렌더링을 위해 기존 한자 영역을 덮어씌워야 합니다.
 
### 기타
* 텍스트 필드 글자수 제한 조정 필요 여부 (아이마스1 : \root\widget\system_widget.xml의 m_txt_message)
* 번역 엑셀 시트의 모든 셀 타입은 text로, 유닛명 등을 나타내는 특수문자 **** 와 line break가 번역문에서 사라지지 않도록 체크 필요
* 이미지 번역, 시스템 텍스트 번역 자동화 파이프라인 구상 필요 등
