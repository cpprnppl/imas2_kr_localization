#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
PS3 실기용 한글 패치 꾸러미 (2026-10-24 KOR 지시: "실기패치도 준비해줘" — EBOOT 제외)

RPCS3에 배포·확인된 상태를 그대로 묶는다. 실행 파일(EBOOT.BIN)은 건드리지 않는다 —
exe 하드코딩 문구 222개는 RPCS3 patch(exe_inject install-ps3)로만 들어가고 실기에서는 일본어로 남는다.

담는 것 (원본과 다른 파일만):
  res    ps3_res_apply 산출 out_ps3res\ (report.json sha) — 배포본 sha와 같아야 함
  scb    resource\gscript\*.scb 중 순정 백업(USRDIR\gscript - 복사본)과 다른 것
  font   resource\im2_font(.nfh/.nut), im2_font_l(.nfh/.nut) — 순정 md5(repatch_fonts 기준)와 다른 것
  attract resource\scene\attract.mpc — attract.mpc.orig와 다른 것
출력: Desktop\imas2_ps3_kr_patch_<날짜>\USRDIR\resource\… + manifest.json + SHA256SUMS.txt (복사 뒤 다시 해시)
      + 설치안내.md (PS3_REAL_HW_GUIDE_KO.md 사본)
게임 폴더·순정 백업은 읽기만 한다.

  python ps3_package.py
"""
import os
import sys
import json
import time
import shutil
import hashlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import JP_ROOT, OUT_DEFAULT  # noqa: E402

USRDIR = os.path.dirname(JP_ROOT)
GS_ORIG = os.path.join(USRDIR, "gscript - 복사본")
OUT_RES = os.path.join(OUT_DEFAULT, "out_ps3res")
FONT_ORIG_MD5 = {"im2_font.nut": "f5451c353daf35d1867bfd16cdd2cc8f", "im2_font.nfh": "da99834ce4a0846f9bdd22b4e584bfee",
                 "im2_font_l.nut": "e94c9af9db807530e69101542f7139a2", "im2_font_l.nfh": "d772158afc8fe74a7aa7e12e071fada5"}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def collect():
    """[(분류, resource 기준 상대경로, 원천 파일)]"""
    items = []
    rep = json.load(open(os.path.join(OUT_RES, "report.json"), encoding="utf-8"))
    for rel, v in rep["files"].items():
        src = os.path.join(OUT_RES, rel)
        if sha(src) != v["sha"]:
            sys.exit(f"❌ {rel}: out_ps3res 파일이 report sha와 다름")
        if sha(os.path.join(JP_ROOT, rel)) != v["sha"]:
            sys.exit(f"❌ {rel}: RPCS3 배포본이 빌드 산출과 다름 — 배포 상태부터 맞출 것")
        items.append(("res", rel, src))
    for dp, _dn, fns in os.walk(GS_ORIG):
        for fn in fns:
            if not fn.lower().endswith(".scb"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), GS_ORIG)
            if rel.lower().startswith("tools"):        # 백업에 딸려 온 excel2scb 산출물(tools\output) — 게임 파일 아님
                continue
            live = os.path.join(JP_ROOT, "gscript", rel)
            if os.path.exists(live) and sha(live) != sha(os.path.join(dp, fn)):
                items.append(("scb", os.path.join("gscript", rel), live))
    for fn, md5 in FONT_ORIG_MD5.items():
        p = os.path.join(JP_ROOT, fn)
        if hashlib.md5(open(p, "rb").read()).hexdigest() != md5:
            items.append(("font", fn, p))
    att = os.path.join(JP_ROOT, "scene", "attract.mpc")
    if os.path.exists(att + ".orig") and sha(att) != sha(att + ".orig"):
        items.append(("attract", os.path.join("scene", "attract.mpc"), att))
    return items


def main():
    items = collect()
    dst_root = os.path.join(os.path.expanduser("~"), "Desktop", f"imas2_ps3_kr_patch_{time.strftime('%Y%m%d')}")
    if os.path.exists(dst_root):
        sys.exit(f"❌ 이미 있음: {dst_root} (덮어쓰지 않음 — 지우거나 이름 바꾼 뒤 다시)")
    man = []
    for cat, rel, src in items:
        d = os.path.join(dst_root, "USRDIR", "resource", rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(src, d)
        h = sha(d)
        if h != sha(src):
            sys.exit(f"❌ 복사 해시 불일치 {rel}")
        man.append({"category": cat, "path": "USRDIR/resource/" + rel.replace(os.sep, "/"), "sha256": h,
                    "size": os.path.getsize(d)})
    json.dump({"at": time.strftime("%Y-%m-%d %H:%M"), "title": "NPJB00337", "eboot": "포함 안 함(원본 그대로 사용)",
               "files": man}, open(os.path.join(dst_root, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(dst_root, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as f:
        for m in man:
            f.write(f"{m['sha256']}  {m['path']}\n")
    shutil.copyfile(os.path.join(HERE, "PS3_REAL_HW_GUIDE_KO.md"), os.path.join(dst_root, "설치안내.md"))
    from collections import Counter
    c = Counter(m["category"] for m in man)
    print(f"{len(man)}개 → {dst_root}  {dict(c)}  합계 {sum(m['size'] for m in man):,}B")


if __name__ == "__main__":
    main()
