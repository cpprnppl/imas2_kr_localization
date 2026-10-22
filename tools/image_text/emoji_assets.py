#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
게임 메일 이모티콘(PUA U+E000~U+E03F) 웹앱 자산 생성 (2026-10-23)

이모티콘은 본문 폰트(NFH)에 없고, initialTemp.mpc의 2번째 NUT 텍스처
(256x512 DXT5) 상단 8x8 칸(32x32)에 있다. 코드 U+E000+i = i번째 칸
(문맥 대조로 확인: E009 おやすみ=zzZ, E025 車=자동차, E028 飛行機=비행기,
E03B 朝食=주먹밥, E03C ケーキ=케이크, E03E かみつく=강아지).

출력 (<OUT>/emoji/, 게임 자산이므로 git에 넣지 않음 — Supabase storage에만):
  emoji_sheet.png  256x256 컬러 스프라이트 (웹앱 표시용 span 배경)
  imas2emo.ttf     픽셀 윤곽 단색 웹폰트, PUA 코드 그대로 (textarea 입력칸용)

  python emoji_assets.py build
  python emoji_assets.py upload --service-key <sb_secret>
"""
import os
import io
import sys
import json
import argparse
import urllib.request

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT, JP_ROOT, walk_nuts, decode_texture  # noqa: E402

OUT = os.path.join(OUT_DEFAULT, "emoji")
SRC = os.path.join(JP_ROOT, "initialTemp.mpc")   # 읽기 전용
CELL, COLS, N = 32, 8, 64
UPM, PX = 1024, 32                                # 1픽셀 = 32 units
ASC, DESC = 896, 128


def build_sheet():
    d = open(SRC, "rb").read()
    ts = walk_nuts(d, lambda *a: None)
    t = ts[1]
    assert (t["w"], t["h"]) == (256, 512), f"예상과 다른 텍스처 {t['w']}x{t['h']}"
    img = decode_texture(t["fmt"], d[t["data_off"]:t["data_off"] + t["data_size"]], t["w"], t["h"])
    return img[:CELL * (N // COLS), :CELL * COLS]   # 256x256


def rects_of(mask):
    """행 단위 런 → 세로로 같은 런이 이어지면 병합한 사각형 목록 (x0,y0,x1,y1)."""
    out, open_ = [], {}
    for y in range(mask.shape[0]):
        runs, x = [], 0
        row = mask[y]
        while x < len(row):
            if row[x]:
                x0 = x
                while x < len(row) and row[x]:
                    x += 1
                runs.append((x0, x))
            else:
                x += 1
        nxt = {}
        for r in runs:
            if r in open_:
                nxt[r] = open_.pop(r)
            else:
                nxt[r] = y
        for (x0, x1), y0 in open_.items():
            out.append((x0, y0, x1, y))
        open_ = nxt
    for (x0, x1), y0 in open_.items():
        out.append((x0, y0, x1, mask.shape[0]))
    return out


def build_font(sheet):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    names = [".notdef"] + [f"uniE{i:03X}" for i in range(N)]
    cmap = {0xE000 + i: f"uniE{i:03X}" for i in range(N)}
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    glyphs, metrics = {}, {}
    pen = TTGlyphPen(None)
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (UPM, 0)
    for i in range(N):
        cx, cy = (i % COLS) * CELL, (i // COLS) * CELL
        a = sheet[cy:cy + CELL, cx:cx + CELL, 3] >= 128
        pen = TTGlyphPen(None)
        for x0, y0, x1, y1 in rects_of(a):
            X0, X1 = x0 * PX, x1 * PX
            Y0, Y1 = ASC - y1 * PX, ASC - y0 * PX      # 아래→위 좌표
            pen.moveTo((X0, Y0)); pen.lineTo((X0, Y1)); pen.lineTo((X1, Y1)); pen.lineTo((X1, Y0))
            pen.closePath()
        glyphs[f"uniE{i:03X}"] = pen.glyph()
        metrics[f"uniE{i:03X}"] = (UPM, 0)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASC, descent=-DESC)
    fb.setupNameTable({"familyName": "imas2emo", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASC, sTypoDescender=-DESC, usWinAscent=ASC, usWinDescent=DESC)
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def build():
    os.makedirs(OUT, exist_ok=True)
    sheet = build_sheet()
    Image.fromarray(sheet, "RGBA").save(os.path.join(OUT, "emoji_sheet.png"))
    ttf = build_font(sheet)
    open(os.path.join(OUT, "imas2emo.ttf"), "wb").write(ttf)
    print(f"시트 256x256, 폰트 {len(ttf):,}B → {OUT}")


def upload(key):
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    for fn, ct in (("emoji_sheet.png", "image/png"), ("imas2emo.ttf", "font/ttf")):
        data = open(os.path.join(OUT, fn), "rb").read()
        r = urllib.request.Request(f"{cfg['url']}/storage/v1/object/tex/emoji/{fn}", data=data,
                                   method="POST", headers={"apikey": key, "Authorization": f"Bearer {key}",
                                                           "x-upsert": "true", "Content-Type": ct})
        print(fn, urllib.request.urlopen(r).status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "upload"])
    ap.add_argument("--service-key")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    else:
        upload(a.service_key or os.environ["IMAS2_SB_SERVICE"])


if __name__ == "__main__":
    main()
