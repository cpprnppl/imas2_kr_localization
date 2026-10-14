#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 포트(imas2pc, 360판 데이터 사본)에 한글 직접 등록 폰트 + 원시 한글 SCB 배포.

대상: <build_root>\game\resource (기본 build_imas2_o2). 원본 디스크 추출본
(unpack\imas2)은 절대 건드리지 않는다.

360판 포맷 차이 (2026-10-14 역분석, 워크로그 §26):
- 폰트 NUT: PS3 NTP3과 헤더·레이아웃 동일하되 매직 'NTXR', 텍스처 페이로드만
  u16 바이트스왑(8in16). 타일링 없음 (순정 대조로 전 바이트 일치 확인).
- NFH: PS3와 바이트 동일 → output_direct 것 그대로 주입.
- MPC: 게임 폴더 것은 암호화본이지만 엔진은 복호화 평문 pac도 수용
  (initialFix는 실험으로 검증, initialTemp는 이번 배포가 첫 검증).
- SCB: PS3 파이프라인 산출(원시 한글, 복호화 평문)을 그대로 복사.
  360 원본과 PS3 원본은 일부 파일이 미세하게 다르므로(mam_w01_01 확인됨)
  PS3 산출물 배포는 그 차이를 덮는다 — 문제가 보이면 해당 파일만 복원.

동작:
1. 게이트: validate_fonts.py + nfh_convert_direct.py (PS3 배포와 동일)
2. 스크래치에서 복호화한 initialFix/initialTemp에 NFH/NUT 주입본 생성
3. <resource>\_kor_backup\ 에 원본 백업(최초 1회; 이미 있으면 그걸 원본으로 간주)
4. 교체 + 해시 매니페스트(_kor_backup\manifest.json) 기록
사용: python deploy_pcport.py [--build-root C:\...\build_imas2_o2] [--scb-only|--font-only]
"""
import os
import sys
import json
import time
import shutil
import struct
import hashlib
import argparse
import subprocess

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")
DIRECT_DIR = os.path.join(SCRIPT_DIR, "output_direct")
SCRATCH_X360 = os.path.join(os.environ.get("TEMP", "."), "imas2_x360_fontwork")
PS3_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
IMAS2DEC = r"C:\Users\jackfilm\Documents\GitHub\Imas2ToolS\misc\imas2dec\imas2dec.exe"

# 복호화된 initialTemp 내부 오프셋 (pac 데이터 시작 0xA20 기준, 엔트리 테이블 실측)
TEMP_DATA_START = 0xA20
TEMP_NUT = {"im2_font.nut": (0x1CE0, 0x800060, 96), "im2_font_l.nut": (0x821DA0, 0x740920, 0x920)}
FIX_NFH = {"im2_font.nfh": 0x45B40, "im2_font_l.nfh": 0x92920}


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def swap16(b: bytes) -> bytes:
    return np.frombuffer(b, dtype=np.uint8).reshape(-1, 2)[:, ::-1].tobytes()


def decrypt_copy(src, workdir):
    """게임의 암호화 MPC 사본을 workdir에서 imas2dec로 복호화해 bytes 반환."""
    os.makedirs(workdir, exist_ok=True)
    tmp = os.path.join(workdir, os.path.basename(src))
    shutil.copy2(src, tmp)
    pr = subprocess.Popen([IMAS2DEC, tmp], cwd=workdir, stdout=subprocess.DEVNULL)
    try:
        pr.wait(120)
    except subprocess.TimeoutExpired:
        pr.kill()
    dec = open(tmp + ".dec", "rb").read()
    os.remove(tmp)
    os.remove(tmp + ".dec")
    assert dec[:4] == b"pac\x00", f"복호화 실패: {src}"
    return dec


def build_fix(orig_path):
    data = bytearray(decrypt_copy(orig_path, SCRATCH_X360))
    for name, off in FIX_NFH.items():
        blob = open(os.path.join(DIRECT_DIR, name), "rb").read()
        assert data[off:off + 4] == b"NFH\x00", f"{name}: NFH 마커 불일치 @0x{off:X}"
        assert len(blob) == 314832
        data[off:off + len(blob)] = blob
    return bytes(data)


def build_temp(orig_path):
    data = bytearray(decrypt_copy(orig_path, SCRATCH_X360))
    for name, (rel, size, payload_off) in TEMP_NUT.items():
        base = TEMP_DATA_START + rel
        assert data[base:base + 4] in (b"NTXR", b"NTP3"), f"{name}: NUT 마커 불일치 @0x{base:X}"
        ours = open(os.path.join(OUT_DIR, name), "rb").read()
        assert len(ours) == size, f"{name}: 크기 불일치"
        new = bytearray(ours)
        new[0:4] = b"NTXR"
        new[payload_off:] = swap16(bytes(new[payload_off:]))
        data[base:base + size] = new
    return bytes(data)


def backup_once(res, rel, bdir, manifest):
    src = os.path.join(res, rel)
    dst = os.path.join(bdir, rel)
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        manifest.setdefault(rel, {})["orig_md5"] = md5(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-root", default=r"C:\Users\jackfilm\Desktop\imas2pc\build_imas2_o2")
    ap.add_argument("--font-only", action="store_true")
    ap.add_argument("--scb-only", action="store_true")
    a = ap.parse_args()
    res = os.path.join(a.build_root, "game", "resource")
    assert os.path.isdir(res), res
    bdir = os.path.join(res, "_kor_backup")
    os.makedirs(bdir, exist_ok=True)
    mpath = os.path.join(bdir, "manifest.json")
    manifest = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {}

    if not a.scb_only:
        for gate in ("validate_fonts.py", "nfh_convert_direct.py"):
            r = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, gate)])
            if r.returncode != 0:
                print(f"[중단] {gate} FAIL")
                sys.exit(1)
        for rel, builder in (("initialFix.mpc", build_fix), ("initialTemp.mpc", build_temp)):
            backup_once(res, rel, bdir, manifest)
            new = builder(os.path.join(bdir, rel))   # 원본(백업본)에서 빌드
            tgt = os.path.join(res, rel)
            open(tgt + ".tmp", "wb").write(new)
            os.replace(tgt + ".tmp", tgt)
            manifest[rel]["new_md5"] = md5(tgt)
            print(f"폰트 주입: {rel} ({len(new):,}B, 복호화 평문)")

    if not a.font_only:
        # 봉인(2026-10-14): PS3 tools\output은 AES 재암호화본이라 PC 포트(평문 pac
        # 필요)에 넣으면 호스트 AV 크래시 — 실제로 발생해 원복했음. PC 포트 SCB는
        # 메인 세션의 tools\scb\deploy_pcport.py(평문 output_pcport/ 사용)가 담당.
        sys.exit("[중단] SCB 복사 모드는 봉인됨 — tools\\scb\\deploy_pcport.py(평문 출력)를 쓸 것. "
                 "폰트만 배포하려면 --font-only.")
        src_root = os.path.join(PS3_TOOLS, "output")
        assert os.path.isdir(src_root), src_root
        n = skip = 0
        for dp, _, fs in os.walk(src_root):
            for f in fs:
                if not f.lower().endswith(".scb"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), src_root)
                tgt = os.path.join(res, "gscript", rel)
                if not os.path.exists(tgt):
                    skip += 1
                    continue   # 360에 없는 파일은 건너뜀
                brel = os.path.join("gscript", rel)
                backup_once(res, brel, bdir, manifest)
                shutil.copy2(os.path.join(dp, f), tgt)
                manifest[brel]["new_md5"] = md5(tgt)
                n += 1
        print(f"SCB 복사: {n}개 (360에 없어 건너뜀 {skip}개) — PS3 검증 산출물(원시 한글)")

    manifest["_meta"] = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "build_root": a.build_root,
                         "note": "복원 = _kor_backup의 파일을 같은 상대경로로 되돌리기"}
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"매니페스트: {mpath} ({len(manifest) - 1}개 항목)")
    print("복원: _kor_backup 내용물을 resource\\에 같은 경로로 복사")


if __name__ == "__main__":
    main()
