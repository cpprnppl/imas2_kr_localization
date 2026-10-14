#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
리패치 산출물 QA 렌더러.

output/의 NUT+NFH만 사용해 게임과 같은 방식으로 문자열을 렌더한다:
  pen_x += 0        → 잉크를 (pen + bearingX(+4), baseline - bearingY(+6))에
  아틀라스 rect(x,y,+16 w/h)에서 샘플링해 블릿, pen += advance(+8).

산출: output/qa_*.png (흰 배경, 검정 글리프, 4배 확대)
"""
import os
import sys
import json
import struct

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")
NFH_RB, NFH_RS = 0x474, 32

sys.path.insert(0, SCRIPT_DIR)
from repatch_fonts import dxt3_alpha_decode, nut_textures  # noqa: E402

SAMPLES = [
    "구세주라니, 안녕하세요!",          # 원래 증상 재현 문구
    "괘돋뺑세쌉챈쿰 재배치 확인",        # 재배치 글리프
    "큿큥햣쌰겍츗 신규 추가",            # 신규 6자
    "한글과日本語あいう混在ー테스트",     # 비타깃(원본 유지) 혼합
    "말줄임표…느낌표！물음표？끝。",      # 문장부호(Noto 재렌더)
    "「한글、음…。」～ー・（좋아！）",    # 베이스라인 정렬 확인용 혼용
]


def load(name):
    nut = open(os.path.join(OUT_DIR, f"{name}.nut"), "rb").read()
    nfh = open(os.path.join(OUT_DIR, f"{name}.nfh"), "rb").read()
    sheets = {}
    for gi, t in enumerate(nut_textures(nut)):
        sheets[gi] = dxt3_alpha_decode(nut[t["raw_off"]: t["raw_off"] + t["raw"]],
                                       t["w"], t["h"])
    recs = {}
    n = (len(nfh) - NFH_RB) // NFH_RS
    for i in range(n):
        off = NFH_RB + i * NFH_RS
        x, y, bx, by, adv, half, gap, em, wh, code = struct.unpack_from(">10H", nfh, off)
        gidx = struct.unpack_from(">I", nfh, off + 28)[0]
        recs[code] = {"x": x, "y": y, "bx": bx // 64, "by": by // 64, "adv": adv // 64,
                      "w": wh >> 8, "h": wh & 0xFF, "gidx": gidx}
    return sheets, recs


def render_line(sheets, recs, text, baseline=30, height=44):
    mapping = json.load(open(os.path.join(OUT_DIR, "font_mapping_v2.json"), encoding="utf-8"))
    canvas = np.zeros((height, 40 + len(text) * 28), np.uint8)
    pen = 4
    for ch in text:
        ch = mapping.get(ch, ch)   # 한글 → 희생 한자 슬롯 (게임과 동일)
        r = recs.get(ord(ch))
        if r is None or r["w"] == 0:
            pen += 13 if ord(ch) < 0x2000 else 26
            continue
        glyph = sheets[r["gidx"]][r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
        gx, gy = pen + r["bx"], baseline - r["by"]
        h, w = glyph.shape
        if gy < 0 or gy + h > height or gx + w > canvas.shape[1]:
            pen += r["adv"]
            continue
        region = canvas[gy:gy + h, gx:gx + w]
        np.maximum(region, glyph, out=region)
        pen += r["adv"]
    return canvas[:, :pen + 8]


def main():
    for name in ("im2_font", "im2_font_l"):
        sheets, recs = load(name)
        lines = [render_line(sheets, recs, t) for t in SAMPLES]
        w = max(l.shape[1] for l in lines)
        gap = 6
        H = sum(l.shape[0] + gap for l in lines)
        canvas = np.zeros((H, w), np.uint8)
        y = 0
        for l in lines:
            canvas[y:y + l.shape[0], :l.shape[1]] = l
            y += l.shape[0] + gap
        img = Image.fromarray(255 - canvas)
        img = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
        p = os.path.join(OUT_DIR, f"qa_{name}.png")
        img.save(p)
        print("saved", p)


if __name__ == "__main__":
    main()
