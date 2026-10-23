#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude 초벌 그림 다시 그리기 — 원본 스타일 보존판 (2026-10-23 사용자 지시)

사용자 지적: 초벌이 글자만 빈 캔버스에 그려서 화살표 같은 비글자 요소가 빠졌고, 이탤릭·외곽선·글로·
좌측 정렬(CV)·흐림(비활성 메뉴) 같은 원본 스타일을 안 따랐다. 글꼴은 Koverwatch로 통일
("네가 이미지 만든거나 만들거는 이 폰트로 하도록 해").

방식:
  - 원본에서 글자 아닌 부분(화살표·'CV:'·DOWN/UP·GET·765·숫자·http 줄)은 원본 픽셀 그대로 남긴다(KEEP 열/행).
  - 바꾸는 부분은 원본 그 자리의 잉크 상자·스타일을 실측(채움 위/아래색, 외곽선 색·두께, 글로/그림자 색·반경·
    방향)해서 같은 층 구조로 Koverwatch 한글을 그린다. 이탤릭 기울기는 항목별(SPEC).
  - 흐린 작은 메뉴 그림(비활성)은 큰 짝을 그린 뒤 같은 비율로 줄이고 원본과 가장 닮은 반경으로 흐린다.
  - kr/ 파일은 manifest의 sha(초벌 그대로)와 같을 때만 덮는다 — 팀이 바꾼 작업본은 건드리지 않는다.

  python claude_art.py preview        # coverage/claude_art_review_N.png (원본 | 이전 초벌 | 새 초벌)
  python claude_art.py write          # kr/ 덮기(sha 일치분만) + manifest 갱신
  python claude_art.py texkr --code … # 웹앱 tex_kr의 'Claude 초벌' 작업본 갱신(팀 업로드분은 건너뜀)
"""
import os
import io
import sys
import json
import base64
import hashlib
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402

FONT = os.path.join(OUT_DEFAULT, "fonts", "koverwatch", "koverwatch.ttf")   # 라이선스 미상 — git 밖 로컬 참조
MAN = os.path.join(OUT_DEFAULT, "kr_claude", "manifest.json")
SS = 4

# 항목별 지정(파일 이름 → runs). run: {"x": [x0, x1]} 열 범위, "keep": 원본 유지 / "text": 그 자리에 그릴 한글,
# "align": left|center|right, "rows": [y0, y1] 행 제한. 지정 없는 항목 = 전체 한 run(행 kr 그대로).
# shear = 이탤릭 기울기(x += shear * 위로 올라간 픽셀).
SPEC = {
    "les_mar_020.png": {"full": "페이스 DOWN 중", "shear": 0.22, "runs": [
        {"x": [0, 37], "text": "페이스", "align": "right"}, {"x": [38, 98], "keep": True},
        {"x": [99, 112], "text": "중"}, {"x": [113, 127], "keep": True}]},
    "les_mar_021.png": {"full": "페이스 UP 중", "shear": 0.22, "runs": [
        {"x": [0, 54], "text": "페이스", "align": "right"}, {"x": [55, 83], "keep": True},
        {"x": [84, 99], "text": "중"}, {"x": [100, 127], "keep": True}]},
    "les_mar_048.png": {"full": "765프로", "runs": [
        {"x": [0, 180], "keep": True}, {"x": [181, 319], "text": "프로", "align": "left"}]},
    "mainmenu_104.png": {"full": "시스템 설정 1", "runs": [
        {"x": [0, 185], "text": "시스템 설정", "align": "right"}, {"x": [186, 255], "keep": True}]},
    "mainmenu_106.png": {"full": "시스템 설정 2", "runs": [
        {"x": [0, 183], "text": "시스템 설정", "align": "right"}, {"x": [184, 255], "keep": True}]},
    "produce_common_099.png": {"full": "부적 GET", "runs": [
        {"x": [0, 73], "text": "부적", "align": "right"}, {"x": [74, 143], "keep": True}]},
    "mainmenu_174.png": {"runs": [
        {"rows": [0, 16], "text_line": 0, "align": "right"}, {"rows": [17, 31], "keep": True}]},
}
for _f in ("exep_staff_roll_012.png", "exep_staff_roll_053.png", "ProStaffRoll_014.png",
           "ProStaffRoll_022.png", "ProStaffRoll_105.png", "ProStaffRoll_127.png"):
    SPEC[_f] = {"cv": True, "runs": [{"x": [0, 136], "keep": True},
                                     {"x": [137, 1023], "text_after": "CV:", "align": "left"}]}
# 흐린 작은 그림(비활성 상태) → 큰 짝
BLUR_PAIR = {"mainmenu_008.png": "mainmenu_009.png", "mainmenu_017.png": "mainmenu_018.png",
             "mainmenu_019.png": "mainmenu_020.png", "mainmenu_024.png": "mainmenu_025.png",
             "mainmenu_026.png": "mainmenu_027.png", "mainmenu_029.png": "mainmenu_030.png",
             "mainmenu_031.png": "mainmenu_032.png", "mainmenu_033.png": "mainmenu_034.png"}


# ---------------------------------------------------------------- 실측
def _erode(m, n=1):
    im = Image.fromarray((m * 255).astype(np.uint8))
    for _ in range(n):
        im = im.filter(ImageFilter.MinFilter(3))
    return np.asarray(im) > 127


def _dilate(m, n=1):
    im = Image.fromarray((m * 255).astype(np.uint8))
    for _ in range(n):
        im = im.filter(ImageFilter.MaxFilter(3))
    return np.asarray(im) > 127


def measure(a):
    """원본 RGBA(부분) → 스타일. a: HxWx4 uint8."""
    A = a[..., 3].astype(float)
    rgb = a[..., :3].astype(float)
    core = A >= 230
    if core.sum() < 8:
        core = A >= 180
    if core.sum() < 4:
        return None
    ys, xs = np.nonzero(core)
    box = (xs.min(), ys.min(), xs.max(), ys.max())
    inner = _erode(core, 2) if _erode(core, 2).sum() > 10 else (_erode(core, 1) if _erode(core, 1).sum() > 5 else core)
    iy = np.nonzero(inner)[0]
    t0, t1 = iy.min(), iy.max()
    third = max(1, (t1 - t0) // 3)
    top = rgb[inner & (np.arange(a.shape[0])[:, None] <= t0 + third)]
    bot = rgb[inner & (np.arange(a.shape[0])[:, None] >= t1 - third)]
    fill_t = top.mean(0) if len(top) else rgb[inner].mean(0)
    fill_b = bot.mean(0) if len(bot) else fill_t
    edge = core & ~_erode(core, 1)
    edge_c = np.median(rgb[edge], 0) if edge.any() else fill_t
    fill_m = (fill_t + fill_b) / 2
    ow = 0
    if np.abs(edge_c - fill_m).sum() > 90:
        ow = 1                               # 바깥 고리부터 외곽선색과 비슷한 고리 수 = 외곽선 두께
        for k in range(1, 4):
            ring = _erode(core, k) & ~_erode(core, k + 1)
            if not ring.any() or np.abs(np.median(rgb[ring], 0) - edge_c).sum() > 80:
                break
            ow = k + 1
        deep = _erode(core, ow + 1)
        if deep.sum() > 10:                  # 채움은 외곽선 안쪽 깊은 곳에서 다시 잰다
            dy = np.nonzero(deep)[0]
            d0, d1 = dy.min(), dy.max()
            th = max(1, (d1 - d0) // 3)
            tp = rgb[deep & (np.arange(a.shape[0])[:, None] <= d0 + th)]
            bt = rgb[deep & (np.arange(a.shape[0])[:, None] >= d1 - th)]
            fill_t = np.median(tp, 0) if len(tp) else np.median(rgb[deep], 0)
            fill_b = np.median(bt, 0) if len(bt) else fill_t
            fill_m = (fill_t + fill_b) / 2
    # 딱딱한 드롭섀도(사용자: "흰 채움, 노란 외곽선 후 블러 없는 어두운 노랑"): 외곽선보다 어두운 불투명 픽셀 덩어리
    shadow, shadow_off = None, [0, 0]
    if ow:
        lum = rgb @ np.array([0.299, 0.587, 0.114])
        e_l = float(np.array(edge_c) @ np.array([0.299, 0.587, 0.114]))
        S = core & (lum < e_l - 30)
        if S.sum() > 0.04 * core.sum():
            F = core & ~S
            best = (0, (0, 0))
            for dy in range(0, 7):
                for dx in range(0, 7):
                    if dx == dy == 0:
                        continue
                    sh = np.zeros_like(F)
                    sh[dy:, dx:] = F[:F.shape[0] - dy, :F.shape[1] - dx]
                    cov = (sh & S).sum() / S.sum()
                    if cov > best[0] + 0.02:
                        best = (cov, (dx, dy))
            if best[0] > 0.5:
                shadow, shadow_off = np.median(rgb[S], 0).tolist(), list(best[1])
            box = (box[0], box[1], box[2] - shadow_off[0], box[3] - shadow_off[1])   # 글자 상자는 그림자 뺀 크기
    halo = (A > 12) & ~core
    st = {"box": [int(v) for v in box], "fill_t": fill_t.tolist(), "fill_b": fill_b.tolist(),
          "shadow": shadow, "shadow_off": shadow_off,
          "outline": edge_c.tolist(), "ow": ow, "glow_r": 0, "glow": [0, 0, 0], "glow_a": 0, "off": [0, 0],
          "stroke": max(0, _stroke(core) - ow)}
    if halo.sum() > 6:
        st["glow"] = np.median(rgb[halo], 0).tolist()
        st["glow_a"] = float(np.percentile(A[halo], 90))
        d, cov = 0, core.copy()
        while d < 10 and (halo & ~cov).sum() > 0.05 * halo.sum():
            cov = _dilate(cov, 1)
            d += 1
        gc = np.array(st["glow"])
        distinct = np.abs(gc - fill_m).sum() > 120 and np.abs(gc - edge_c).sum() > 120
        st["glow_r"] = d if (d >= 2 and distinct) else 0   # 1px 이하·채움/외곽선과 같은 색 = 안티에일리어싱, 글로 아님
        st["halo_ratio"] = float(A[halo].sum() / max(1.0, A[core].sum()))
        w = A / 255.0
        gy, gx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        cy, cx = (gy * core).sum() / core.sum(), (gx * core).sum() / core.sum()
        hy, hx = (gy * w * halo).sum() / max(1e-6, (w * halo).sum()), (gx * w * halo).sum() / max(1e-6, (w * halo).sum())
        if abs(hx - cx) >= 0.8 or abs(hy - cy) >= 0.8:
            st["off"] = [round(hx - cx), round(hy - cy)]
    return st


# 계열별 처방(원본 확대 실측, 2026-10-23). 글자 픽셀은 색으로 고른다(글로를 글자로 잡지 않게).
#  plain: 채움만(はい/いいえ·작은 메뉴·ペース) / pref: 흰 면 + 1px 밝은 회색 외곽 + 옅은 검은 바깥선(도도부현)
#  menu: 거의 검은 글자 + 넓고 부드러운 흰 글로(메인 메뉴 큰 라벨) / 그 밖: measure() 실측(CV·765·부적 GET)
def family(name):
    if name.startswith("exep_commu_"):
        return "pref"
    if name.startswith(("initialFix_", "les_mar_02")):
        return "plain"
    if name.startswith("mainmenu_"):
        n = int(name[9:12])
        return "menu" if n <= 34 else "plain"
    return None


def _lum(a):
    return a[..., :3].astype(float) @ np.array([0.299, 0.587, 0.114])


def family_style(fam, part):
    A = part[..., 3].astype(float)
    L = _lum(part)
    if fam == "pref":
        sel = (A >= 200) & (L >= 235)
    elif fam == "menu":
        sel = (A >= 200) & (L <= 110)
    else:
        sel = A >= 200
    if sel.sum() < 4:
        return None
    ys, xs = np.nonzero(sel)
    rgb = part[..., :3].astype(float)
    y0, y1 = ys.min(), ys.max()
    third = max(1, (y1 - y0) // 3)
    top = rgb[sel & (np.arange(part.shape[0])[:, None] <= y0 + third)]
    bot = rgb[sel & (np.arange(part.shape[0])[:, None] >= y1 - third)]
    st = {"box": [int(xs.min()), int(y0), int(xs.max()), int(y1)],
          "fill_t": (top.mean(0) if len(top) else rgb[sel].mean(0)).tolist(),
          "fill_b": (bot.mean(0) if len(bot) else rgb[sel].mean(0)).tolist(),
          "outline": [0, 0, 0], "ow": 0, "glow": [0, 0, 0], "glow_r": 0, "glow_a": 0, "off": [0, 0]}
    st["stroke"] = 0          # Koverwatch 자체가 굵다 — 굵히기 하면 뭉개짐(사용자 "765숍 카탈로그·앨범 너무 굵어")
    st["jp_w"] = st["box"][2] - st["box"][0] + 1
    if fam == "pref":
        st.update(outline=[181, 178, 181], ow=1, glow=[8, 4, 8], glow_r=2, glow_a=90)
        st["box"] = [st["box"][0] - 1, st["box"][1] - 1, st["box"][2] + 1, st["box"][3] + 1]   # 외곽선 포함 상자
    elif fam == "menu":
        halo = (A > 8) & ~sel
        st.update(glow=[255, 255, 255], glow_r=10, glow_a=200, soft=True,   # 원본: 글자 옆 알파 ~195 → 10px에 걸쳐 0
                  halo_ratio=float(A[halo].sum() / max(1.0, A[sel].sum())))
    return st


def _stroke(mask):
    """획 굵기 지표: 3x3 침식을 몇 번 해야 거의 다 사라지는지(≈ 획 폭의 절반)."""
    n, m, tot = 0, mask.copy(), max(1, mask.sum())
    while m.sum() > 0.03 * tot and n < 20:
        m = _erode(m, 1)
        n += 1
    return n


# ---------------------------------------------------------------- 렌더
_FC = {}


def font(px):
    if px not in _FC:
        _FC[px] = ImageFont.truetype(FONT, px)
    return _FC[px]


def text_mask(text, ink_h, max_w, shear=0.0, want_w=None):
    """Koverwatch 한글 잉크 높이 ink_h(px)짜리 4배 마스크. 폭이 max_w 넘으면 가로로 줄임(1.15배까지 늘림 허용 안 함)."""
    ref = font(100 * SS)
    x0, y0, x1, y1 = ref.getbbox("한글")
    size = max(4, int(100 * SS * ink_h * SS / (y1 - y0)))
    f = font(size)
    bb = f.getbbox(text)
    W, H = bb[2] - bb[0] + 8 * SS, bb[3] - bb[1] + 8 * SS
    im = Image.new("L", (W, H), 0)
    ImageDraw.Draw(im).text((4 * SS - bb[0], 4 * SS - bb[1]), text, font=f, fill=255)
    if shear:
        pad = int(abs(shear) * H) + 2
        im2 = Image.new("L", (W + pad, H), 0)
        im2.paste(im, (0, 0))
        # x_src = x_dst + shear*(y - H)  → 위쪽이 오른쪽으로
        im = im2.transform(im2.size, Image.AFFINE, (1, shear, -shear * H, 0, 1, 0), Image.BICUBIC)
    im = im.crop(im.getbbox())
    if want_w and im.width < want_w * SS:     # Koverwatch는 좁은 글꼴 — 원본 폭 쪽으로 가로 1.3배까지 늘림
        im = im.resize((int(min(im.width * 1.3, want_w * SS)), im.height), Image.LANCZOS)
    if im.width > max_w * SS:
        im = im.resize((max_w * SS, im.height), Image.LANCZOS)
    return im


def render_run(canvas_wh, st, text, box, align, shear):
    """한 run을 4배 해상도 층으로 그려 RGBA(원 해상도)로."""
    W, H = canvas_wh
    x0, y0, x1, y1 = box
    ow = st["ow"]
    ink_h = (y1 - y0 + 1) - 2 * ow
    if ink_h <= 16:                          # 작은 한글은 가나보다 획이 많아 몇 px 키워야 읽힌다(세로 가운데 유지)
        grow = min(3, max(0, H - 2 - (y1 - y0 + 1)) // 2 * 2)
        y0, y1 = y0 - grow // 2, y1 + grow // 2
        ink_h += grow
    m = text_mask(text, max(4, ink_h), max(4, (x1 - x0 + 1) - 2 * ow), shear, st.get("jp_w"))
    M = Image.new("L", (W * SS, H * SS), 0)
    if align == "left":
        px = (x0 + ow) * SS
    elif align == "right":
        px = (x1 + 1 - ow) * SS - m.width
    else:
        px = ((x0 + x1 + 1) * SS - m.width) // 2
    py = ((y0 + y1 + 1) * SS - m.height) // 2
    M.paste(m, (int(px), int(py)))
    # 획 굵기 맞춤(사용자 "페이스·중이 너무 얇다"): 원본 획 지표보다 가늘면 그만큼 키운다
    if st.get("stroke"):
        k = _stroke(np.asarray(M.resize((W, H), Image.BOX)) > 127)
        if st["stroke"] > k:
            M = M.filter(ImageFilter.MaxFilter(_odd(2 * min(1, st["stroke"] - k) * SS)))   # 최대 1px — 더 키우면 획이 뭉친다
    if ink_h <= 16:                          # 작은 글자는 Koverwatch 획이 1px 안팎이라 원본보다 가늘어 보인다
        M = M.filter(ImageFilter.MaxFilter(3))
    O = M.filter(ImageFilter.MaxFilter(2 * ow * SS + 1)) if ow else M
    layers = []
    if st["glow_r"] and st["glow_a"] > 10:
        r = st["glow_r"] * SS
        if st.get("soft"):                   # 넓고 부드러운 글로: 글자 옆 ~0.78 → 반경 끝 0
            G = O.filter(ImageFilter.MaxFilter(_odd(2 * SS))).filter(ImageFilter.GaussianBlur(r * 0.35))
            G = Image.fromarray(np.clip(np.asarray(G, float) * 1.6, 0, 230).astype(np.uint8))
        else:
            G = O.filter(ImageFilter.MaxFilter(_odd(r * 0.6))).filter(ImageFilter.GaussianBlur(r * 0.45))
            G = Image.fromarray(np.maximum(np.asarray(G), np.asarray(O)))      # 글자 바로 옆은 꽉 차게
        if st["off"] != [0, 0]:
            G2 = Image.new("L", G.size, 0)
            G2.paste(G, (st["off"][0] * SS, st["off"][1] * SS))
            G = G2
        ga = np.asarray(G, float) / 255 * (st["glow_a"] / 255)
        layers.append((np.array(st["glow"], float), np.clip(ga * st.get("glow_gain", 1.4), 0, 1)))
    if st.get("shadow"):                     # 블러 없는 드롭섀도 = 외곽선까지 포함한 글자를 어긋나게 한 판
        dx, dy = st["shadow_off"]
        Sh = Image.new("L", O.size, 0)
        Sh.paste(O, (dx * SS, dy * SS))
        layers.append((np.array(st["shadow"], float), np.asarray(Sh, float) / 255))
    if ow:
        layers.append((np.array(st["outline"], float), np.asarray(O, float) / 255))
    Fm = np.asarray(M, float) / 255
    ys = np.nonzero(Fm.max(1) > 0.5)[0]
    a0, a1 = (ys.min(), ys.max()) if len(ys) else (0, H * SS - 1)
    t = np.clip((np.arange(H * SS) - a0) / max(1, a1 - a0), 0, 1)[:, None, None]
    fill = np.array(st["fill_t"], float) * (1 - t) + np.array(st["fill_b"], float) * t
    rgb = np.zeros((H * SS, W * SS, 3))
    al = np.zeros((H * SS, W * SS))
    prem_rgb = np.zeros_like(rgb)                     # 프리멀티플라이 상태로 'over' 합성
    for c, a in layers + [(fill, Fm)]:
        c = np.broadcast_to(c, rgb.shape)
        prem_rgb = c * a[..., None] + prem_rgb * (1 - a[..., None])
        al = a + al * (1 - a)
    prem = np.concatenate([prem_rgb, al[..., None] * 255], -1)
    small = np.asarray(Image.fromarray(np.clip(prem, 0, 255).astype(np.uint8), "RGBA").resize((W, H), Image.BOX), float)
    a = small[..., 3:4] / 255
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = np.clip(np.where(a > 0, small[..., :3] / np.maximum(a, 1e-6), 0), 0, 255).round()
    out[..., 3] = small[..., 3].round()
    return out


def _over(top, bot):
    """RGBA(스트레이트) top을 bot 위에 합성."""
    ta, ba = top[..., 3:4] / 255.0, bot[..., 3:4] / 255.0
    oa = ta + ba * (1 - ta)
    rgb = (top[..., :3] * ta + bot[..., :3] * ba * (1 - ta)) / np.maximum(oa, 1e-6)
    return np.concatenate([np.clip(rgb, 0, 255), oa * 255], -1).round().astype(np.uint8)


def _odd(v):
    return int(round(v)) // 2 * 2 + 1


def _align_of(jp, box):
    W = jp.shape[1]
    x0, _y0, x1, _y1 = box
    if x0 <= 0.06 * W and (W - 1 - x1) > x0 + 4:     # 왼쪽 여백에 붙어 있으면 왼쪽 정렬(カタログをみる — 가운데 근처라도)
        return "left"
    c = (x0 + x1) / 2
    if abs(c - W / 2) <= 0.08 * W:
        return "center"
    return "left" if c < W / 2 else "right"


def redraw(fname, jp, text):
    """원본 RGBA 배열 + 행 텍스트 → 새 RGBA 배열. 실패 시 ValueError."""
    H, W = jp.shape[:2]
    sp = SPEC.get(fname)
    if sp and sp.get("full") and sp["full"] != text:
        raise ValueError(f"행 문구가 지정 분해와 다름('{text}' ≠ '{sp['full']}') — SPEC 갱신 필요")
    shear = (sp or {}).get("shear", 0.0)
    out = np.zeros_like(jp)
    runs = (sp or {}).get("runs") or [{"x": [0, W - 1]}]
    lines = text.split("\n")
    for run in runs:
        xa, xb = run.get("x", [0, W - 1])
        ya, yb = run.get("rows", [0, H - 1])
        part = np.zeros_like(jp)
        part[ya:yb + 1, xa:xb + 1] = jp[ya:yb + 1, xa:xb + 1]
        if run.get("keep"):
            out = np.where(part[..., 3:4] > 0, part, out)
            continue
        fam = family(fname)
        st = family_style(fam, part) if fam else measure(part)
        if st is None:
            continue
        if "text" in run:
            t = run["text"]
        elif "text_line" in run:
            t = lines[run["text_line"]]
        elif "text_after" in run:
            t = text.split(run["text_after"], 1)[-1].strip()
        else:
            t = text
        if "\n" in t:
            raise ValueError("여러 줄 문구는 SPEC으로 줄별 지정 필요")
        al = run.get("align") or _align_of(jp, st["box"])
        if sp is None:                       # 전체 교체: 잉크 상자를 그림 폭 안에서 정렬 방향으로 넓혀 쓴다
            x0, y0, x1, y1 = st["box"]
            if al == "left":
                st["box"] = [x0, y0, W - 2, y1]
            elif al == "right":
                st["box"] = [1, y0, x1, y1]
            else:
                half = min(x0, W - 1 - x1)
                st["box"] = [max(1, x0 - half), y0, min(W - 2, x1 + half), y1]
        layer = render_run((W, H), st, t, st["box"], al, shear)
        # 글로 세기 보정: 새 그림의 (글로 알파 합 / 글자 알파 합)을 원본과 같게(사용자 "글로우도 약하고")
        for _ in range(2):
            if not st["glow_r"] or not st.get("halo_ratio"):
                break
            LA = layer[..., 3].astype(float)
            c_new = LA >= 230
            h_new = (LA > 12) & ~c_new
            r_new = LA[h_new].sum() / max(1.0, LA[c_new].sum())
            if r_new <= 0:
                break
            gain = float(np.clip(st["halo_ratio"] / r_new, 0.5, 3.0))
            if abs(gain - 1) < 0.08:
                break
            st["glow_gain"] = float(np.clip(st.get("glow_gain", 1.4) * gain, 0.3, 6.0))
            layer = render_run((W, H), st, t, st["box"], al, shear)
        out = _over(layer, out)
    return out


def redraw_blurred(small_jp, big_jp, big_text, big_name):
    """비활성(흐린) 작은 그림: 큰 짝 새 그림을 줄이고 원본 짝 관계에 가장 맞는 반경으로 흐림."""
    h, w = small_jp.shape[:2]
    ref = Image.fromarray(big_jp).resize((w, h), Image.LANCZOS)
    best = (1e18, 0)
    for r in [x / 2 for x in range(0, 13)]:
        cand = np.asarray(ref.filter(ImageFilter.GaussianBlur(r)) if r else ref, float)
        e = ((cand - small_jp.astype(float)) ** 2).mean()
        best = min(best, (e, r))
    new_big = redraw(big_name, big_jp, big_text)
    im = Image.fromarray(new_big).resize((w, h), Image.LANCZOS)
    if best[1]:
        im = im.filter(ImageFilter.GaussianBlur(best[1]))
    return np.asarray(im)


# ---------------------------------------------------------------- 작업
def items():
    man = json.load(open(MAN, encoding="utf-8"))
    texts = json.load(open(os.path.join(OUT_DEFAULT, "kr_claude", "texts_now.json"), encoding="utf-8"))
    out = []
    for md5, v in man.items():
        if not v["kr_files"] or not texts.get(md5):
            continue
        out.append((md5, v, texts[md5]))
    return sorted(out, key=lambda x: x[1]["kr_files"][0])


def build_one(md5, v, text, by_name):
    f = v["kr_files"][0]
    name = os.path.basename(f)
    jp = np.asarray(Image.open(os.path.join(OUT_DEFAULT, "jp", f)).convert("RGBA"))
    if name in BLUR_PAIR:
        big = BLUR_PAIR[name]
        bmd5, bv, btext = by_name[big]
        bjp = np.asarray(Image.open(os.path.join(OUT_DEFAULT, "jp", bv["kr_files"][0])).convert("RGBA"))
        return redraw_blurred(jp, bjp, btext, big)
    return redraw(name, jp, text)


def cmd_preview(_a):
    its = items()
    by_name = {os.path.basename(v["kr_files"][0]): (m, v, t) for m, v, t in its}
    rows, errs = [], []
    for md5, v, text in its:
        f = v["kr_files"][0]
        try:
            new = build_one(md5, v, text, by_name)
        except ValueError as e:
            errs.append(f"{f}: {e}")
            continue
        jp = Image.open(os.path.join(OUT_DEFAULT, "jp", f)).convert("RGBA")
        old = Image.open(os.path.join(OUT_DEFAULT, "kr", f)).convert("RGBA")
        rows.append((f, jp, old, Image.fromarray(new)))
    per = 20
    for s0 in range(0, len(rows), per):
        ch = rows[s0:s0 + per]
        RH = 96
        sheet = Image.new("RGB", (1650, RH * len(ch)), (70, 70, 90))
        d = ImageDraw.Draw(sheet)
        for k, (f, *ims) in enumerate(ch):
            y = k * RH
            d.text((2, y + 1), f"{s0 + k} {f}", fill=(255, 255, 0))
            for j, im in enumerate(ims):
                im = im.copy()
                im.thumbnail((530, RH - 16))
                bg = Image.new("RGBA", im.size, (125, 125, 150, 255))
                bg.alpha_composite(im)
                sheet.paste(bg.convert("RGB"), (2 + j * 548, y + 14))
        sheet.save(os.path.join(OUT_DEFAULT, "coverage", f"claude_art_review_{s0 // per}.png"))
    print(f"{len(rows)}장 미리보기 → coverage/claude_art_review_*.png (원본 | 이전 초벌 | 새 초벌)")
    for e in errs:
        print("  [건너뜀]", e)


def cmd_write(_a):
    its = items()
    by_name = {os.path.basename(v["kr_files"][0]): (m, v, t) for m, v, t in its}
    man = json.load(open(MAN, encoding="utf-8"))
    n = skip = 0
    for md5, v, text in its:
        try:
            new = build_one(md5, v, text, by_name)
        except ValueError as e:
            print("  [건너뜀]", v["kr_files"][0], e)
            continue
        buf = io.BytesIO()
        Image.fromarray(new).save(buf, "PNG")
        data = buf.getvalue()
        paths = [os.path.join(OUT_DEFAULT, "kr", f) for f in v["kr_files"]]
        if any(os.path.exists(p) and hashlib.sha256(open(p, "rb").read()).hexdigest() != v["sha256"] for p in paths):
            skip += 1                       # 팀이 바꾼 작업본 — 덮지 않음
            continue
        for p in paths:
            open(p, "wb").write(data)
        man[md5]["sha256"] = hashlib.sha256(data).hexdigest()
        man[md5]["style"] = {"font": "koverwatch.ttf", "tool": "claude_art.py"}
        n += 1
    json.dump(man, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"새 초벌 {n}장 기록(manifest sha 갱신), 팀 작업본이라 건너뜀 {skip}")


def cmd_texkr(a):
    import urllib.request
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    H = {"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}", "x-team-code": a.code,
         "Content-Type": "application/json", "Prefer": "return=representation"}
    man = json.load(open(MAN, encoding="utf-8"))
    n = skip = 0
    for md5, v in man.items():
        if not v["kr_files"] or v.get("style", {}).get("tool") != "claude_art.py":
            continue
        p = os.path.join(OUT_DEFAULT, "kr", v["kr_files"][0])
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        q = f"{cfg['url']}/rest/v1/tex_kr?md5=eq.{md5}&by=eq.{urllib.parse.quote('Claude 초벌')}"
        rq = urllib.request.Request(q, data=json.dumps({"data": b64}).encode(), method="PATCH", headers=H)
        res = json.load(urllib.request.urlopen(rq))
        if res:
            n += 1
        else:
            skip += 1
    print(f"tex_kr 'Claude 초벌' 갱신 {n}개, 대상 아님(팀 업로드·행 없음) {skip}")


def main():
    import urllib.parse  # noqa: F401
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preview").set_defaults(fn=cmd_preview)
    sub.add_parser("write").set_defaults(fn=cmd_write)
    p = sub.add_parser("texkr")
    p.add_argument("--code", required=True)
    p.set_defaults(fn=cmd_texkr)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
