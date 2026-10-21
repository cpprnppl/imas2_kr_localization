#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
360 DLC 텍스처 추출 (이미지 텍스트 후보) — PC 포트 주입 대상

360 NUT('NTXR')는 PS3 NTP3와 헤더·레이아웃이 같고 페이로드만 16비트
바이트스왑(워크로그 §26, 폰트로 검증). → swap16 후 기존 decode_texture 재사용.
PS3 DLC zip에는 텍스처가 없고, 중국팀도 DLC 이미지는 수정하지 않았음.

출력: <OUT>/dlc_tex/<패키지6>/<상대경로>_<nnn>.png + dlc_tex/index.json
      (md5 중복 제거 그룹, 파일별 위치·포맷·오프셋)

  python dlc_images.py extract
"""
import os
import sys
import json
import hashlib
import argparse

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT, walk_nuts, decode_texture, FMT_NAMES  # noqa: E402
from dlc_text import stage, X360_ROOT  # noqa: E402

OUT = os.path.join(OUT_DEFAULT, "dlc_tex")
EXTS = (".nut", ".pac")   # ad_bg.ptc = 평문 'PTC+MSHM' 파티클, 텍스처 없음
SKIP_DIRS = ("acce", "dance", "song", "model")   # 3D 모델/모션/음원 — 텍스트 없음


def swap16(b: bytes) -> bytes:
    a = np.frombuffer(b, dtype=np.uint8)
    if len(a) % 2:
        a = a[:-1]
    return a.reshape(-1, 2)[:, ::-1].tobytes()


# 360 전용 16bpp 코드 (2026-10-22 눈검증): 빅엔디언 u16 그대로(스왑 없음)
#   fmt10 = ARGB1555 (카탈로그 1024x512), fmt11 = ARGB4444 (액세서리 아이콘 104x72)
FMT_360 = {10: "ARGB1555", 11: "ARGB4444", 19: "ARGB32_360"}


def decode_360(fmt, raw, w, h):
    """반환: RGBA. DXT/32bpp는 swap16 후 PS3 디코더, 16bpp는 BE 그대로."""
    if fmt == 19:   # 32bpp ARGB 빅엔디언 (PS3 fmt14와 같은 바이트 순서)
        return decode_texture(14, raw, w, h)
    if fmt in FMT_360:
        v = np.frombuffer(raw[:w * h * 2], ">u2").reshape(h, w).astype(np.uint32)
        out = np.zeros((h, w, 4), np.uint8)
        if fmt == 10:
            out[..., 0] = ((v >> 10) & 31) * 255 // 31
            out[..., 1] = ((v >> 5) & 31) * 255 // 31
            out[..., 2] = (v & 31) * 255 // 31
            a = np.where(v >> 15, 255, 0)
            out[..., 3] = a if a.any() else 255
        else:
            out[..., 0] = ((v >> 8) & 15) * 17
            out[..., 1] = ((v >> 4) & 15) * 17
            out[..., 2] = (v & 15) * 17
            out[..., 3] = ((v >> 12) & 15) * 17
        return out
    return decode_texture(fmt, swap16(raw), w, h)


def classify(g):
    """눈검수(2026-10-22) 기준 텍스트 유무.
    텍스트: 카탈로그 페이지 1024x512, 곡 제목 로고 464x48, 곡 재킷 256x256.
    없음: 아이템 그림 300x384, 의상/액세서리 아이콘 104x72, 메일 사진 332x424, 32x32 아이콘."""
    k, w, h = g["kind"], g["w"], g["h"]
    if k == "catalog_info" and (w, h) == (1024, 512):
        return "카탈로그 페이지"
    if k == "songinfo" and (w, h) == (464, 48):
        return "곡 제목 로고"
    if k == "songinfo" and (w, h) == (256, 256):
        return "곡 재킷"
    return None


def extract():
    os.makedirs(OUT, exist_ok=True)
    groups = {}
    fails = []
    n_tex = 0
    for pkg in sorted(os.listdir(X360_ROOT)):
        res = os.path.join(X360_ROOT, pkg, "resource")
        if not os.path.isdir(res):
            continue
        p6 = pkg[:6]
        for dp, dns, fns in os.walk(res):
            rel_dir = os.path.relpath(dp, res)
            if rel_dir.split(os.sep)[0] in SKIP_DIRS:
                dns[:] = []
                continue
            for fn in sorted(fns):
                if not fn.lower().endswith(EXTS):
                    continue
                rel = os.path.normpath(os.path.join(rel_dir, fn))
                try:
                    data = stage(os.path.join(dp, fn), f"tex_{p6}_{rel.replace(os.sep, '_')}")
                except Exception as e:  # noqa: BLE001
                    fails.append(f"{p6}/{rel}: {e}")
                    continue
                scan = data.replace(b"NTXR", b"NTP3")
                is360 = b"NTXR" in data
                texs = walk_nuts(scan, lambda *a: None)
                for i, t in enumerate(texs):
                    raw = data[t["data_off"]:t["data_off"] + t["data_size"]]
                    try:
                        img = decode_360(t["fmt"], raw, t["w"], t["h"]) if is360 \
                            else decode_texture(t["fmt"], raw, t["w"], t["h"])
                    except Exception as e:  # noqa: BLE001
                        fails.append(f"{p6}/{rel}#{i}: {e}")
                        continue
                    md5 = hashlib.md5(raw).hexdigest()
                    stem = rel.replace(os.sep, "_").rsplit(".", 1)[0]
                    png_rel = os.path.join(p6, f"{stem}_{i:03d}.png")
                    g = groups.get(md5)
                    if g is None:
                        dst = os.path.join(OUT, png_rel)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        Image.fromarray(img, "RGBA").save(dst)
                        g = groups[md5] = {
                            "md5": md5, "png": png_rel.replace(os.sep, "/"),
                            "w": t["w"], "h": t["h"],
                            "fmt": (FMT_360.get(t["fmt"]) if is360 else None)
                                   or FMT_NAMES.get(t["fmt"], f"fmt{t['fmt']}"),
                            "kind": rel.split(os.sep)[0] if os.sep in rel else rel.rsplit(".", 1)[0],
                            "locs": []}
                    g["locs"].append({"pkg": pkg, "rel": rel.replace(os.sep, "/"), "n": i,
                                      "data_off": t["data_off"], "data_size": t["data_size"],
                                      "swap16": is360})
                    n_tex += 1
    for g in groups.values():
        g["text"] = classify(g)
    json.dump({"groups": groups, "fails": fails},
              open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    from collections import Counter
    kinds = Counter(g["kind"] for g in groups.values())
    print(f"텍스처 {n_tex}장 → 유니크 {len(groups)} (실패 {len(fails)})")
    for k, v in kinds.most_common():
        print(f"  {k}: {v}")
    tx = Counter(g["text"] for g in groups.values() if g["text"])
    print(f"텍스트 있음 {sum(tx.values())}장: {dict(tx)}")
    for f in fails[:10]:
        print("  [실패]", f)
    print(f"출력: {OUT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract"])
    ap.parse_args()
    extract()


if __name__ == "__main__":
    main()
