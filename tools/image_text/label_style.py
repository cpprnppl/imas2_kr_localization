#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
원본 라벨 텍스처에서 글자 스타일을 재서 label_tool 렌더 스타일로 (2026-10-23, KOR "초벌 라벨을 원본처럼")

  measure(jp_png) → {"skip": 사유} 또는 label_tool 스타일 dict
    - 불투명 핵(alpha≥200) 중 글자 색: 어두운/밝은 쪽 다수결 → fill = 그쪽 중앙값 색
    - 글로우: 반투명(20<alpha<200) 화소의 중앙값 색과 핵 테두리 바깥 폭(거리 변환 근사) → glow, glow_r
    - 외곽선: 핵 안에 글자와 반대 밝기 화소가 테두리에 몰려 있으면 stroke(폭 1~2)
    - 정렬: 잉크 bbox의 좌우 여백 비 → left/center/right, 크기: bbox 높이 기준
    - 배경 도형이 있는 것(배지·버튼: bbox 안 불투명 비율 > 0.6)은 글자만 다시 그릴 수 없어 skip
  python label_style.py <jp_png>...   # 측정값 출력
"""
import sys
import numpy as np
from PIL import Image, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def measure(png):
    im = np.asarray(Image.open(png).convert("RGBA")).astype(np.int32)
    h, w = im.shape[:2]
    a = im[..., 3]
    ink = a > 20
    if not ink.any():
        return {"skip": "빈 그림"}
    ys, xs = np.where(ink)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    core = a >= 200
    lum = (im[..., 0] * 299 + im[..., 1] * 587 + im[..., 2] * 114) // 1000
    box = core[y0:y1 + 1, x0:x1 + 1]
    # 배지 판별: 행마다 가장 긴 불투명 연속 구간 / bbox 폭의 중앙값 — 배지는 한 덩어리(0.89), 글자는 자간에서
    # 끊긴다(굵은 CV 글자도 0.16, 도도부현 0.25~0.42). 불투명 비율만으로는 굵은 글자와 구분 안 됨.
    runs = []
    for row in box:
        m = cur = 0
        for v in row:
            cur = cur + 1 if v else 0
            m = max(m, cur)
        runs.append(m / box.shape[1])
    if float(np.median(runs)) > 0.6:
        return {"skip": "배경 도형(배지·버튼) — 글자만 다시 그릴 수 없음(영역 모드/수작업)"}
    cl = lum[core]
    dark = (cl < 128).mean() >= 0.5 if cl.size else True
    sel = core & ((lum < 128) if dark else (lum >= 128))
    fill = np.median(im[sel][:, :3], axis=0) if sel.any() else (np.array([20, 20, 20]) if dark else np.array([255] * 3))
    # 글자와 반대 밝기의 불투명 화소 = 외곽선(핵 안)
    opp = core & ((lum >= 128) if dark else (lum < 128))
    stroke_w = 0
    stroke = None
    if opp.sum() > 0.15 * max(1, sel.sum()):
        stroke = np.median(im[opp][:, :3], axis=0)
        stroke_w = 2 if opp.sum() > 0.5 * sel.sum() else 1
    # 글로우 = 핵 바깥 반투명 화소
    semi = (a > 20) & (a < 200)
    glow_r, glow, glow_a = 0, None, 0
    gc = np.median(im[semi][:, :3], axis=0) if semi.any() else None
    # 반투명 화소 색이 글자 색과 비슷하면 안티앨리어싱 가장자리일 뿐 — 글로우 아님
    if semi.sum() > 0.3 * max(1, core.sum()) and abs(int(gc @ [299, 587, 114]) // 1000 -
                                                     int(fill @ [299, 587, 114]) // 1000) > 60:
        glow = gc
        glow_a = int(np.median(a[semi]) * 1.6)
        m = Image.fromarray((core * 255).astype(np.uint8))
        for r in range(1, 6):
            grown = np.asarray(m.filter(ImageFilter.MaxFilter(2 * r + 1))) > 0
            if (semi & ~grown).sum() < 0.1 * semi.sum():
                glow_r = r
                break
        else:
            glow_r = 5
    lm, rm = x0 / w, (w - 1 - x1) / w
    align = "left" if lm < 0.08 and rm > lm + 0.1 else ("right" if rm < 0.08 and lm > rm + 0.1 else "center")
    st = {"font": "malgunbd.ttf", "fill": _hex(fill), "align": align, "fit": True,
          "size": max(8, int((y1 - y0 + 1) * 1.25)),       # 잉크 높이 → 맑은 고딕 em(한글 글리프가 em보다 작음), 넘치면 fit "margin": max(1, int(min(x0, w - 1 - x1, y0, h - 1 - y1))),
          "stroke_w": stroke_w, "stroke": _hex(stroke) if stroke is not None else "#000000",
          "glow_r": glow_r, "glow": _hex(glow) if glow is not None else "#ffffff", "glow_a": min(255, glow_a),
          "dy": int(((y0 + y1) / 2) - h / 2)}
    return st


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, measure(p))
