# -*- coding: utf-8 -*-
"""
sync_to_game.py — 레포(tools/scb/)의 스크립트를 게임 tools 폴더로 동기화

단일 원천(single source of truth) 규칙:
  - SCB 도구의 원천은 이 Git 레포. 수정은 레포에서 하고 이 스크립트로 배포한다.
  - 게임 폴더에서 직접 고쳤다면, 즉시 레포로 복사해 커밋할 것 (이력 유실 방지).

사용: python sync_to_game.py           (레포 → 게임 폴더)
      python sync_to_game.py --pull    (게임 폴더 → 레포; 게임 쪽에서 수정한 경우)
"""
import os, sys, shutil, filecmp

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
FILES = ["scb_common.py", "excel2scb.py", "scb2excel.py", "validate_output.py", "deploy.py",
         "patch_attract.py", "deploy_pcport.py"]

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pull = "--pull" in sys.argv

for f in FILES:
    src = os.path.join(GAME_TOOLS if pull else HERE, f)
    dst = os.path.join(HERE if pull else GAME_TOOLS, f)
    if not os.path.exists(src):
        print(f"  (없음, 건너뜀) {f}")
        continue
    if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
        print(f"  (동일) {f}")
        continue
    shutil.copy2(src, dst)
    print(f"  복사: {f}  {'게임→레포' if pull else '레포→게임'}")
print("완료. (--pull로 가져왔다면 git commit을 잊지 말 것)")
