# -*- coding: utf-8 -*-
"""
빌드 상태 표식 — '이전 빌드 배포' 방지 (2026-10-23: 360 대본 빌드가 끝나기 전에 deploy_pcport --src360이
돌아 이전 산출물을 배포한 사고. KOR: "배포는 빌드 완료를 확인한 뒤에만").

빌드(excel2scb·pcport360)는 시작할 때 running, 끝날 때 done(+엑셀 이름·시각)을 남긴다.
배포(deploy·deploy_pcport --src360)는 check()로:
  - 표식 없음 / running → 거부 (빌드 중이거나 중간에 죽은 산출물)
  - 빌드에 쓴 엑셀보다 새 translation_webapp_*.xlsx가 있음 → 거부 (회수만 하고 빌드 안 한 상태)
  --allow-stale 로만 우회.
"""
import os
import glob
import json
import time

TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"


def _path(name):
    return os.path.join(TOOLS, f"build_state_{name}.json")


def mark_running(name, excel):
    json.dump({"status": "running", "excel": os.path.abspath(excel), "started": time.time()},
              open(_path(name), "w", encoding="utf-8"), ensure_ascii=False)


def mark_done(name, ok=True):
    p = _path(name)
    st = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    st.update(status="done" if ok else "failed", finished=time.time())
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False)


def check(name, argv):
    """배포 전 확인. 문제면 사유 문자열, 괜찮으면 None."""
    if "--allow-stale" in argv:
        return None
    p = _path(name)
    if not os.path.exists(p):
        return f"빌드 상태 표식 없음({os.path.basename(p)}) — 빌드를 다시 돌릴 것"
    st = json.load(open(p, encoding="utf-8"))
    if st.get("status") != "done":
        return f"빌드가 끝나지 않음(status={st.get('status')}) — 빌드 완료 뒤 배포"
    newest = max(glob.glob(os.path.join(TOOLS, "translation_webapp_*.xlsx")), key=os.path.getmtime, default=None)
    used = st.get("excel", "")
    if newest and os.path.getmtime(newest) > os.path.getmtime(used) + 1 \
            and os.path.normcase(newest) != os.path.normcase(used):
        return f"더 새 회수본이 있음({os.path.basename(newest)}) — 빌드는 {os.path.basename(used)} 기준"
    return None
