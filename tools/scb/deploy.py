# -*- coding: utf-8 -*-
"""
deploy.py — 검증 게이트를 통과한 경우에만 output/ 을 게임 폴더에 배포

흐름 (AI-native SDLC의 '자동화된 게이트' 적용):
  1. validate_output.py 실행 → 구조 오류 1건이라도 있으면 배포 중단
  2. 통과 시 tools/output/* → resource/gscript/ 복사
  3. 배포 후 샘플 파일 바이트 비교로 복사 무결성 확인

사용: python deploy.py          (검증 + 배포)
      python deploy.py --check  (검증만)
"""
import os, sys, glob, shutil, subprocess, filecmp

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
GS = os.path.dirname(TOOLS)
OUT = os.path.join(TOOLS, "output")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("=== 1/2 검증 게이트 ===")
r = subprocess.run([sys.executable, os.path.join(HERE, "validate_output.py")])
if r.returncode != 0:
    print("검증 실패 — 배포하지 않음")
    sys.exit(1)
if "--check" in sys.argv:
    sys.exit(0)

print("\n=== 2/2 배포 ===")
n = 0
sample = None
for p in glob.glob(os.path.join(OUT, "**", "*.scb"), recursive=True):
    rel = os.path.relpath(p, OUT)
    dst = os.path.join(GS, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(p, dst)
    sample = (p, dst)
    n += 1
print(f"배포 완료: {n}개")
if sample and not filecmp.cmp(sample[0], sample[1], shallow=False):
    print("❌ 복사 무결성 확인 실패")
    sys.exit(1)
print("✅ 무결성 확인 통과")
