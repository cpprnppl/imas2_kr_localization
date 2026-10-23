#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DLC 메인 메뉴 배너(ad_bg 1280x720)의 의상명 로고 Claude 초벌 (2026-10-23 사용자 "Make draft")

ad_bg 글자는 영문 'Catalog Vol.NN' + 곡명 로고가 대부분이라 초벌 대상이 아니고(곡 로고 제외 방침),
의상명 로고 「エクササイズウェアNEO」 하나만 한글로 다시 쓴다: PS3 cp12 / 360 Vol.08(99F4C8) — 같은 자리·같은 그림.
- 로고: 파랑 채움(2,72,218) + 굵은 흰 외곽 + 얇은 남색 테, 약 11° 기울어짐. 'NEO'·별·마네킹 아이콘은 그대로, 가타카나만 '엑서사이즈 웨어'.
- 방법: 로고 둘레를 잘라 −11° 돌려 수평으로 → 가타카나(파랑+외곽) 통째로 확산 인페인트 →
  Koverwatch로 같은 양식 → 바뀐 화소만 +11° 되돌려 원본에 합성.
출력: kr_dlc_ps3/cp12/ad_bg_000.png, kr_dlc/99F4C8/ad_bg_000.png (dlc_inject 규칙) + tex_kr 'Claude 초벌'(키 = 위치 문자열 md5).

  python adbg_logo.py preview
  python adbg_logo.py write --code …
"""
import os
import sys
import json
import time
import base64
import hashlib
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402
from tut_cards import inpaint  # noqa: E402

FONT = os.path.join(OUT_DEFAULT, "fonts", "koverwatch", "koverwatch.ttf")
# (원본, 출력, 웹앱 위치, 가타카나 상자) — 상자는 −11° 수평으로 돌린 잘라낸 그림 좌표, 외곽 포함.
# 오른쪽 끝 = ア|N 틈(파랑 열 최소, 실측): PS3 334, 360 346 — 360 로고가 12px 오른쪽.
JOBS = [
    ("dlc_tex_ps3/cp12/ad_bg_000.png", "kr_dlc_ps3/cp12/ad_bg_000.png", "ps3:cp12/ad_bg.jpg#000", (65, 129, 334, 176)),
    ("dlc_tex/99F4C8/ad_bg_000.png", "kr_dlc/99F4C8/ad_bg_000.png", "360:99F4C8/ad_bg.ptc#000", (65, 128, 346, 176)),
]
CROP = (780, 420, 1280, 650)
ANG = 11.0                       # 글줄이 오른쪽으로 올라가는 각도(PCA 실측 ≈ 11°)
TEXT = "엑서사이즈 웨어"
FILL, EDGE = (2, 72, 218, 255), (12, 22, 70, 255)


def is_blue(a):
    R, G, B = (a[..., i].astype(int) for i in range(3))
    return (B > 150) & (R < 90) & (G < 140) & (B - G > 60)


def logo_layer(w, h, box):
    """양식: 남색 테(1px) ⊃ 흰 외곽(5px) ⊃ 파랑 채움, 원문처럼 기울임(전단 0.18).
    box 높이·폭에 맞춰 가로로 늘림."""
    x0, y0, x1, y1 = box
    th = y1 - y0 - 14                                 # 외곽 두께를 뺀 글자 높이
    f = ImageFont.truetype(FONT, 100)
    bb = f.getbbox("한")
    f = ImageFont.truetype(FONT, max(8, round(100 * th / (bb[3] - bb[1]))))
    tb = f.getbbox(TEXT, stroke_width=6)
    lay = Image.new("RGBA", (tb[2] - tb[0] + 4, tb[3] - tb[1] + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.text((2 - tb[0], 2 - tb[1]), TEXT, font=f, fill=EDGE, stroke_width=6, stroke_fill=EDGE)
    d.text((2 - tb[0], 2 - tb[1]), TEXT, font=f, fill=(255, 255, 255, 255), stroke_width=5,
           stroke_fill=(255, 255, 255, 255))
    d.text((2 - tb[0], 2 - tb[1]), TEXT, font=f, fill=FILL)   # 채움 보강은 받침 속이 막혀 뺌
    sh = 0.18
    lay = lay.transform((lay.width + int(lay.height * sh), lay.height), Image.AFFINE,
                        (1, sh, -lay.height * sh, 0, 1, 0), resample=Image.BICUBIC)
    lay = lay.resize((x1 - x0, y1 - y0), Image.LANCZOS)  # 원문 가타카나 폭에 맞춤(Koverwatch는 좁은 글꼴)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(lay, (x0, y0))
    return out


def render(src, box):
    full = Image.open(os.path.join(OUT_DEFAULT, src)).convert("RGBA")
    crop = full.crop(CROP)
    rot = crop.rotate(-ANG, resample=Image.BICUBIC, expand=True)
    a = np.array(rot)
    x0, y0, x1, y1 = box
    # 지울 곳: 가타카나 범위 안 파랑을 7px 넓힘(흰 외곽·남색 테 포함). 'N'과 위쪽 별은 범위 밖.
    m = np.zeros(a.shape[:2], bool)
    ex0, ey1 = x0 - 10, y1 + 10                     # 옛 글줄은 왼쪽 아래로 더 내려가 있다(외곽 잔여 방지) — 위(별)·오른쪽(N)은 그대로
    m[y0:ey1, ex0:x1] = is_blue(a[y0:ey1, ex0:x1])
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))) > 0
    keep = np.zeros_like(m)
    keep[y0:ey1, ex0:x1] = True
    m &= keep
    lay = logo_layer(rot.width, rot.height, box)
    la = np.array(lay)[..., 3]
    hole = m                                          # 옛 로고 전체를 지운다(새 글자 밑 옛 파랑이 확산 출처가 되면 파란 번짐)
    out = a.copy()
    if hole.any():
        out[..., :3] = inpaint(a[..., :3], hole, iters=400)
    o = Image.fromarray(out)
    o.alpha_composite(lay)
    # 바뀐 화소만(옛 자리 ∪ 새 글자) +ANG로 되돌려 원본 잘라낸 크기 가운데에 맞춰 합성
    chg = Image.fromarray(((m | (la > 0)) * 255).astype(np.uint8))
    chg = chg.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))   # 가장자리 페더(되돌린 회전의 점선 경계 방지)
    patch = o.copy()
    patch.putalpha(chg)
    back = patch.rotate(ANG, resample=Image.BICUBIC, expand=True)
    cx, cy = (back.width - crop.width) // 2, (back.height - crop.height) // 2
    back = back.crop((cx, cy, cx + crop.width, cy + crop.height))
    res = full.copy()
    res.alpha_composite(back, (CROP[0], CROP[1]))
    return res.convert("RGB")


def cmd_preview(_a):
    rows = []
    for src, _dst, _loc, box in JOBS:
        jp = Image.open(os.path.join(OUT_DEFAULT, src)).convert("RGB").crop((700, 380, 1280, 660))
        kr = render(src, box).crop((700, 380, 1280, 660))
        rows += [jp, kr]
    sheet = Image.new("RGB", (580 * 2, 280 * 2))
    for i, im in enumerate(rows):
        sheet.paste(im, ((i % 2) * 580, (i // 2) * 280))
    p = os.path.join(OUT_DEFAULT, "coverage", "adbg_logo_review.png")
    sheet.save(p)
    print("→", p)


def cmd_write(a):
    import urllib.request
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    H = {"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}", "x-team-code": a.code,
         "Content-Type": "application/json"}
    for src, dst, loc, box in JOBS:
        md5 = hashlib.md5(loc.encode()).hexdigest()       # webapp_seed dlc_image_groups와 같은 키
        tk = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{cfg['url']}/rest/v1/tex_kr?md5=eq.{md5}&select=by", headers=H)))
        if tk and tk[0]["by"] != "Claude 초벌":
            print(f"  {loc}: 팀 작업본 있음 — 건너뜀")
            continue
        p = os.path.join(OUT_DEFAULT, dst)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        render(src, box).save(p)
        body = json.dumps([{"md5": md5, "by": "Claude 초벌", "ts": int(time.time() * 1000),
                            "data": base64.b64encode(open(p, "rb").read()).decode()}]).encode()
        urllib.request.urlopen(urllib.request.Request(cfg["url"] + "/rest/v1/tex_kr?on_conflict=md5", data=body,
                                                      method="POST",
                                                      headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"}))
        print(f"  {loc} → {dst}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preview").set_defaults(fn=cmd_preview)
    p = sub.add_parser("write")
    p.add_argument("--code", required=True)
    p.set_defaults(fn=cmd_write)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
