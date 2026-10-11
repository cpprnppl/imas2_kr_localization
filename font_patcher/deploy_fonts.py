#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
리패치 폰트 배포 (게이트: validate_fonts.py PASS 필수).

1. 현재 배포본(resource의 loose 폰트 4종 + initialFix/initialTemp.mpc + 매핑 json 2종)을
   resource\\_backup_fontfix_<ts>\\ 로 백업
2. output/의 im2_font.*, im2_font_l.* 을 loose로 복사
3. MPC 주입:
   - initialFix.mpc 안의 NFH 2개(헤더 폰트명으로 font/font_l 식별) 교체
   - initialTemp.mpc 안의 NTP3 중 크기가 일치하는 font/font_l NUT 교체
4. 매핑 동기화: font_mapping_v2.json → tools\\font_mapping.json, resource\\im2_font_mapping.json
"""
import os
import sys
import time
import shutil
import struct
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")
USR = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR"
RES = os.path.join(USR, "resource")
TOOLS = os.path.join(RES, "gscript", "tools")


def find_all(data, sig):
    out, i = [], 0
    while True:
        j = data.find(sig, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def main():
    # 게이트: 검증 통과 필수
    r = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "validate_fonts.py")])
    if r.returncode != 0:
        print("[중단] validate_fonts.py FAIL — 배포하지 않음")
        sys.exit(1)

    new = {n: open(os.path.join(OUT_DIR, n), "rb").read()
           for n in ("im2_font.nut", "im2_font.nfh", "im2_font_l.nut", "im2_font_l.nfh")}
    mapping_v2 = open(os.path.join(OUT_DIR, "font_mapping_v2.json"), "rb").read()

    ts = time.strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(RES, f"_backup_fontfix_{ts}")
    os.makedirs(bdir, exist_ok=True)
    for f in ("im2_font.nut", "im2_font.nfh", "im2_font_l.nut", "im2_font_l.nfh",
              "initialFix.mpc", "initialTemp.mpc", "im2_font_mapping.json"):
        src = os.path.join(RES, f)
        if os.path.exists(src):
            shutil.copy2(src, bdir)
    shutil.copy2(os.path.join(TOOLS, "font_mapping.json"), os.path.join(bdir, "tools_font_mapping.json"))
    print(f"백업 완료: {bdir}")

    # loose 파일 교체
    for n, blob in new.items():
        dst = os.path.join(RES, n)
        tmp = dst + ".tmp"
        open(tmp, "wb").write(blob)
        os.replace(tmp, dst)
        print(f"loose 교체: {n}")

    # initialFix.mpc: NFH 2개 교체 (헤더 0x10~의 폰트명: 'Pro DB' 포함 → font_l)
    p = os.path.join(RES, "initialFix.mpc")
    data = bytearray(open(p, "rb").read())
    offs = find_all(bytes(data), b"NFH\x00")
    assert len(offs) == 2, f"initialFix.mpc: NFH {len(offs)}개 (2개 기대)"
    plan = {}
    for o in offs:
        hdr = bytes(data[o:o + 0x40])
        which = "im2_font_l.nfh" if b"Pro DB" in hdr else "im2_font.nfh"
        assert which not in plan, "NFH 식별 중복"
        plan[which] = o
    for which, o in plan.items():
        blob = new[which]
        data[o:o + len(blob)] = blob
        print(f"initialFix.mpc @0x{o:X} ← {which}")
    tmp = p + ".tmp"
    open(tmp, "wb").write(data)
    os.replace(tmp, p)

    # initialTemp.mpc: NTP3 중 크기 일치 교체 (텍스처 수 1+w2048 → font, 29 → font_l)
    p = os.path.join(RES, "initialTemp.mpc")
    data = bytearray(open(p, "rb").read())
    offs = find_all(bytes(data), b"NTP3")
    plan = {}
    for o in offs:
        cnt = struct.unpack_from(">H", data, o + 6)[0]
        w = struct.unpack_from(">H", data, o + 16 + 20)[0]
        if cnt == 1 and w == 2048:
            which = "im2_font.nut"
        elif cnt == 29 and w == 512:
            which = "im2_font_l.nut"
        else:
            continue
        assert which not in plan, "NUT 식별 중복"
        plan[which] = o
    assert set(plan) == {"im2_font.nut", "im2_font_l.nut"}, f"NUT 식별 누락: {set(plan)}"
    for which, o in plan.items():
        blob = new[which]
        data[o:o + len(blob)] = blob
        print(f"initialTemp.mpc @0x{o:X} ← {which}")
    tmp = p + ".tmp"
    open(tmp, "wb").write(data)
    os.replace(tmp, p)

    # 매핑 동기화
    for dst in (os.path.join(TOOLS, "font_mapping.json"),
                os.path.join(RES, "im2_font_mapping.json")):
        tmp = dst + ".tmp"
        open(tmp, "wb").write(mapping_v2)
        os.replace(tmp, dst)
        print(f"매핑 갱신: {dst}")

    print("\n배포 완료. RPCS3에서 인게임 확인 후 문제 시 백업 폴더로 복원:")
    print(f"  {bdir}")


if __name__ == "__main__":
    main()
