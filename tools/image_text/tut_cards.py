#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALF 튜토리얼 카드(game/alf/alf_tut_*.nut, 1024x580) — 360판 전용 그림 한글 초벌 (2026-10-23 KOR 지시)

360판 카드는 PS3판과 배치·문구가 같고 버튼 그림(PS3 □△○✕R1 ↔ 360 XYBA RB)과 화면 캡처 인셋만 다르다.
  reuse: PS3판 팀 작업본(kr/)이 있으면 그 한글 그대로 쓰고, 버튼만 360판으로 바꾼다.
    - PS3 원본·360 원본 차이 영역 중 큰 덩어리(인셋 캡처) → 360 원본 픽셀
    - 작은 덩어리(본문 속 버튼 아이콘) → 팀 작업본에서 PS3 아이콘을 형판 일치로 찾아 360 아이콘으로 교체
  결과: kr_x360/game_alf_alf_tut_<이름>_000.png (pcport_apply가 360 텍스처로 주입)

  python tut_cards.py reuse          # 팀 작업본 있는 카드만
"""
import os
import sys
import json

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402

CARDS = ["aud_01", "aud_02", "base_01", "base_02", "fes_01", "fes_02", "liv_01", "liv_02"]


def _p(kind, nm):
    return {"jp": os.path.join(OUT_DEFAULT, "jp", "game", "alf", f"alf_tut_{nm}_000.png"),
            "x": os.path.join(OUT_DEFAULT, "x360_only", f"game_alf_alf_tut_{nm}.nut_000.png"),
            "kr": os.path.join(OUT_DEFAULT, "kr", "game", "alf", f"alf_tut_{nm}_000.png"),
            "out": os.path.join(OUT_DEFAULT, "kr_x360", f"game_alf_alf_tut_{nm}_000.png")}[kind]


def components(mask, gap=3):
    """이진 마스크의 연결 덩어리 bbox 목록(gap px 팽창 후)."""
    from PIL import ImageFilter
    if gap > 0:                       # Pillow MaxFilter(1)은 0 나누기로 인터프리터가 죽는다(2026-10-23)
        a = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * gap + 1))) > 0
    else:
        a = mask.astype(bool)
    seen = np.zeros_like(a)
    out = []
    H, W = a.shape
    for y0, x0 in zip(*np.nonzero(a)):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        ys, xs = [], []
        while stack:
            y, x = stack.pop()
            ys.append(y)
            xs.append(x)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and a[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    stack.append((yy, xx))
        out.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(xs)))
    return out


def find_template(img, tpl, region=None):
    """img(H,W,4)에서 tpl과 가장 닮은 위치(SSD) — (x, y, 평균 오차)."""
    h, w = tpl.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, img.shape[1], img.shape[0])
    best = (None, None, 1e18)
    t = tpl[..., :3].astype(np.float32)
    for y in range(max(0, y0), min(img.shape[0] - h, y1) + 1):
        row = img[y:y + h, :, :3].astype(np.float32)
        for x in range(max(0, x0), min(img.shape[1] - w, x1) + 1):
            e = ((row[:, x:x + w] - t) ** 2).mean()
            if e < best[2]:
                best = (x, y, e)
    return best


# 카드별 예외(눈검수 2026-10-23):
#  KEEP_TEAM: 인셋 안 글자까지 팀이 번역했고 버튼 그림이 없는 카드 — 팀 작업본 그대로(360 인셋을 섞으면 일본어가 되살아남)
#  ICON_SWAPS: 줄 안에서 360 아이콘 뒤로 글줄이 밀려 자동 형판 일치가 안 되는 아이콘 — (PS3 아이콘 상자, 360 아이콘 상자)
KEEP_TEAM = {"aud_01"}
ICON_SWAPS = {"base_02": [((576, 515, 606, 535), (579, 514, 611, 535))]}


def _ink(t):
    """아이콘·글자 픽셀(흰 바탕이 아닌 것)."""
    rgb = t[..., :3].astype(int)
    return (rgb.min(-1) < 225) | ((rgb.max(-1) - rgb.min(-1)) > 40)


def paste_icon(K, x, y, tA, tB):
    """(x,y)에 있던 PS3 아이콘 tA를 360 아이콘 tB로 — 두 아이콘 픽셀만 바꾸고 둘레의 팀 글자는 보존."""
    h, w = max(tA.shape[0], tB.shape[0]), max(tA.shape[1], tB.shape[1])
    reg = K[y:y + h, x:x + w]
    a = np.zeros(reg.shape[:2], bool)
    a[:tA.shape[0], :tA.shape[1]] = _ink(tA)[:reg.shape[0], :reg.shape[1]]
    b = np.zeros(reg.shape[:2], bool)
    bb = np.zeros_like(reg)
    bb[:tB.shape[0], :tB.shape[1]] = tB[:reg.shape[0], :reg.shape[1]]
    b[:tB.shape[0], :tB.shape[1]] = _ink(tB)[:reg.shape[0], :reg.shape[1]]
    bg = np.median(reg[~(a | _ink(reg))].reshape(-1, 4), 0) if (~(a | _ink(reg))).any() else np.array([255, 255, 255, 255])
    reg[a & ~b] = bg            # PS3 아이콘만 있던 자리 → 바탕
    reg[b] = bb[b]              # 360 아이콘


def swap_icon(K, A, B, a_box, b_box, log, nm):
    ax0, ay0, ax1, ay1 = a_box
    bx0, by0, bx1, by1 = b_box
    tA = A[ay0:ay1, ax0:ax1]
    x, y, e = find_template(K, tA, (0, ay0 - 8, K.shape[1], ay0 + 8))
    if x is None or e > 300:
        log(f"  [미해결] {nm} 아이콘 {a_box}: 작업본에서 못 찾음(오차 {e:.0f})")
        return False
    # 360 아이콘을 PS3 아이콘 중심에 맞춘 상자(둘 중 큰 쪽)로 합성
    cx, cy = x + (ax1 - ax0) // 2, y + (ay1 - ay0) // 2
    tB = B[by0:by1, bx0:bx1]
    w, h = max(bx1 - bx0, ax1 - ax0), max(by1 - by0, ay1 - ay0)
    X, Y = cx - w // 2, cy - h // 2
    tA2 = np.full((h, w, 4), 255, np.uint8)
    tA2[(y - Y):(y - Y) + tA.shape[0], (x - X):(x - X) + tA.shape[1]] = tA
    tB2 = np.full((h, w, 4), 255, np.uint8)
    oy, ox = (h - tB.shape[0]) // 2, (w - tB.shape[1]) // 2
    tB2[oy:oy + tB.shape[0], ox:ox + tB.shape[1]] = tB
    paste_icon(K, X, Y, tA2, tB2)
    return True


def reuse(nm, log=print):
    A = np.asarray(Image.open(_p("jp", nm)).convert("RGBA"))
    B = np.asarray(Image.open(_p("x", nm)).convert("RGBA"))
    K = np.array(Image.open(_p("kr", nm)).convert("RGBA"))
    if nm in KEEP_TEAM:
        os.makedirs(os.path.dirname(_p("out", nm)), exist_ok=True)
        Image.fromarray(K).save(_p("out", nm))
        log(f"  {nm}: 팀 작업본 그대로(버튼 그림 없음, 인셋 글자 번역됨) → {_p('out', nm)}")
        return K
    for a_box, b_box in ICON_SWAPS.get(nm, []):
        swap_icon(K, A, B, a_box, b_box, log, nm)
    diff = np.abs(A.astype(int) - B.astype(int)).sum(-1) > 60
    comps = components(diff)
    big = [c for c in comps if (c[2] - c[0]) * (c[3] - c[1]) > 4000]
    small = [c for c in comps if c not in big]
    for x0, y0, x1, y1, _n in list(big):               # 인셋: 팀 작업본도 원본 그대로인 곳만 360 픽셀로
        same = np.abs(K[y0:y1, x0:x1].astype(int) - A[y0:y1, x0:x1].astype(int)).mean()
        if same > 6:
            # 팀이 번역한 글줄(버튼 아이콘이 여러 개 붙어 큰 덩어리로 보인 것) — 덮지 말고 아이콘 단위로 다시 나눈다
            big.remove((x0, y0, x1, y1, _n))
            log(f"  {nm} {x0},{y0}-{x1},{y1}: 팀이 번역한 글줄 — 덮지 않음(아이콘은 ICON_SWAPS로)")
            continue
        K[y0:y1, x0:x1] = B[y0:y1, x0:x1]
    n_icon = 0
    for x0, y0, x1, y1, _n in small:                  # 본문 아이콘: PS3 아이콘을 작업본에서 찾아 360 아이콘으로
        tA, tB = A[y0:y1, x0:x1], B[y0:y1, x0:x1]
        x, y, e = find_template(K, tA, (x0 - 260, y0 - 6, x1 + 260, y0 + 6))
        if x is None or e > 900:
            log(f"  [미해결] {nm} 아이콘 {x0},{y0}: 작업본에서 못 찾음(오차 {e:.0f})")
            continue
        paste_icon(K, x, y, tA, tB)
        n_icon += 1
    os.makedirs(os.path.dirname(_p("out", nm)), exist_ok=True)
    Image.fromarray(K).save(_p("out", nm))
    log(f"  {nm}: 인셋 {len(big)}곳 360판으로, 아이콘 {n_icon}/{len(small)}개 교체 → {_p('out', nm)}")
    return K


# ---------------------------------------------------------------- 초벌(팀 작업본 없는 카드: fes·liv)
# 글자 상자만 확산 인페인트로 지우고 Koverwatch로 다시 쓴다. 버튼 아이콘·화면 캡처 인셋·배지 그림은 원본 그대로.
# 문구 용어는 팀 PS3 카드(기본·오디션 규칙)·웹앱 기존 번역(ハコユレ震度 = 회장 흥분도)을 따른다.
# 본문 줄: (윗줄 y, 런 목록) — 런: (문자열, 색 키 k/p/g) 또는 ("@icon", 순번)
FONT = os.path.join(OUT_DEFAULT, "fonts", "koverwatch", "koverwatch.ttf")
DRAFT = {
    "fes_01": {"title": "페스티벌 규칙 ①",
               "heading": [("라이벌", "p"), ("과 ", "w"), ("스코어", "p"), ("를 겨뤄라!", "w")],
               "body": [(297, [("페스티벌에서는 옆 스테이지에 출연 중인 ", "k"), ("라이벌", "p"), ("과 ", "k"), ("스코어", "p"), ("를 겨룹니다.", "k")]),
                        (316, [("퍼포먼스가 끝났을 때 ", "k"), ("스코어", "p"), ("가 높은 쪽이 ", "k"), ("승리", "p"), ("합니다.", "k")]),
                        (354, [("각 어필은 서로의 퍼포먼스에 영향을 줍니다.", "k")]),
                        (391, [("추억 어필", "g"), ("@icon", 0), (" : 상대의 ", "k"), ("볼티지", "p"), ("를 조금 줄입니다.", "k")]),
                        (410, [("버스트 어필", "p"), ("@icon", 1), (" : 상대의 어필을 잠시 멈추게 하고, ", "k"), ("볼티지", "p"), ("를 크게 줄입니다.", "k")])]},
    "fes_02": {"title": "페스티벌 규칙 ②",
               "heading": [("라이벌 버스트", "p"), ("에 주의하라!", "w")],
               "body": [(423, [("라이벌도 유닛과 똑같이 ", "k"), ("버스트 어필", "p"), ("을 합니다.", "k")]),
                        (442, [("라이벌의 ", "k"), ("버스트 어필", "p"), ("이 발생하면 그동안은 ", "k"), ("어필", "p"), ("을 지시할 수 없게 되고,", "k")]),
                        (462, [("유닛의 ", "k"), ("볼티지", "p"), ("도 크게 줄어듭니다.", "k")]),
                        (500, [("라이벌의 ", "k"), ("볼티지", "p"), ("에 신경 쓰며 라이벌의 ", "k"), ("버스트 어필", "p"), ("을", "k")]),
                        (519, [("막아 내는 것도 페스티벌에서는 중요합니다.", "k")])]},
    "liv_01": {"title": "라이브 규칙 ①",
               "heading": [("회장 흥분도", "p"), ("를 올려라!", "w")],
               "body": [(297, [("회장을 얼마나 달아오르게 하느냐가 라이브 ", "k"), ("성공", "p"), ("의 열쇠입니다.", "k")]),
                        (316, [("스코어", "p"), ("가 오르면 회장이 달아올라 ", "k"), ("회장 흥분도", "p"), ("가 올라갑니다.", "k")]),
                        (335, [("회장 흥분도", "p"), ("가 목표에 도달하면 라이브 성공입니다.", "k")])]},
    "liv_02": {"title": "라이브 규칙 ②",
               "heading": [("회장 흥분도", "p"), ("를 올려라!", "w")],
               "body": [(499, [("회장", "p"), ("이 필요로 하는 ", "k"), ("회장 흥분도", "p"), ("는 ", "k"), ("스케줄 선택 화면", "g"), ("의", "k")]),
                        (518, [("업무 상세에서도 확인할 수 있습니다.", "k")])]},
}
SUBTITLE = [("스테이지 계열 업무", "p")]


def inpaint(img, mask, iters=400):
    """확산 인페인트(평탄한 바탕·옅은 워터마크용): 마스크 픽셀을 이웃 평균으로 반복 채움."""
    out = img.astype(np.float32).copy()
    m = mask.copy()
    known = ~m
    out[m] = 0
    for _ in range(iters):
        acc = np.zeros_like(out)
        cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(out, (dy, dx), (0, 1))
            k = np.roll(known, (dy, dx), (0, 1))
            acc += sh * k[..., None]
            cnt += k
        upd = m & (cnt > 0)
        out[upd] = acc[upd] / cnt[upd][:, None]
        known = known | upd
    return np.clip(out, 0, 255).astype(np.uint8)


def text_mask(img, box, kind):
    x0, y0, x1, y1 = box
    a = img[y0:y1, x0:x1, :3].astype(int)
    lum = a @ np.array([0.299, 0.587, 0.114])
    sat = a.max(-1) - a.min(-1)
    m = (lum > 90) if kind == "dark_bg" else ((lum < 200) | (sat > 60))
    full = np.zeros(img.shape[:2], bool)
    full[y0:y1, x0:x1] = m
    from PIL import ImageFilter
    return np.asarray(Image.fromarray((full * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0


def colors(img, lines=None):
    """원본 카드에서 글자색 실측: 본문 검정(k)·분홍(p)·초록(g)·흰(w). 본문 줄 띠에서만(인셋 색이 섞이지 않게)."""
    rows = [img[y - 2:y + 17, 200:840, :3].reshape(-1, 3) for y in (lines or [])] or [img[285:545, 200:840, :3].reshape(-1, 3)]
    a = np.concatenate(rows).astype(int)
    lum = a @ np.array([0.299, 0.587, 0.114])
    pk = a[(a[:, 0] > 200) & (a[:, 1] < 110) & (a[:, 2] > 100)]
    gr = a[(a[:, 1] > 150) & (a[:, 0] < 170) & (a[:, 2] < 110)]
    dk = a[lum < 80]
    med = lambda x, d: tuple(int(v) for v in (np.median(x, 0) if len(x) > 20 else d))
    return {"k": med(dk, (40, 40, 40)), "p": med(pk, (240, 40, 140)), "g": med(gr, (90, 180, 0)), "w": (255, 255, 255)}


def icons(base, other, lines=None):
    """본문 속 버튼 아이콘(두 판에서 다른 작은 덩어리) — 왼→오, 위→아래 순 (상자, 그림).
    lines: 본문 줄 윗줄 y 목록 — 그 줄 띠 안에서만 찾는다(인셋 차이는 제외, 속도)."""
    d0 = np.abs(base.astype(int) - other.astype(int)).sum(-1) > 60
    # 줄마다 따로(줄 간격 19px — 띠가 겹치면 위아래 아이콘이 한 덩어리가 된다), 팽창 없이 덩어리를 잡고 같은 줄 조각만 합친다
    raw = []
    for y in (lines or []):
        y0, y1 = y - 2, y + 17
        raw += [(c[0] + 195, c[1] + y0, c[2] + 195, c[3] + y0, c[4])
                for c in components(d0[y0:y1, 195:840], gap=0) if (c[2] - c[0]) * (c[3] - c[1]) >= 40]
    comps = []
    for c in sorted(raw, key=lambda c: (c[1], c[0])):
        for i, m in enumerate(comps):
            if abs((c[1] + c[3]) / 2 - (m[1] + m[3]) / 2) < 6 and c[0] <= m[2] + 3 and c[2] >= m[0] - 3:
                comps[i] = (min(c[0], m[0]), min(c[1], m[1]), max(c[2], m[2]), max(c[3], m[3]), c[4] + m[4])
                break
        else:
            comps.append(c)
    comps = [c for c in comps if (c[2] - c[0]) * (c[3] - c[1]) < 2500 and c[3] - c[1] <= 26]
    comps.sort(key=lambda c: (c[1] // 10, c[0]))
    out = []
    for x0, y0, x1, y1, _n in comps:
        # 차이 상자 안에서 아이콘 자체(가장 큰 진한/채도 높은 덩어리)만 — 밀린 글자 조각이 딸려 오지 않게
        crop = base[y0:y1, x0:x1, :3].astype(int)
        lum = crop @ np.array([0.299, 0.587, 0.114])
        pink = (crop[..., 0] > 190) & (crop[..., 1] < 140) & (crop[..., 2] > 90)    # 본문 강조색 글자는 아이콘 아님
        ink = ((lum < 70) | ((crop.max(-1) - crop.min(-1)) > 80)) & ~pink
        blobs = components(ink, gap=0)
        if blobs:
            bx0, by0, bx1, by1, _ = max(blobs, key=lambda b: b[4])
            x0, y0, x1, y1 = x0 + max(0, bx0 - 1), y0 + max(0, by0 - 1), x0 + bx1 + 1, y0 + by1 + 1
        out.append(((x0, y0, x1, y1), base[y0:y1, x0:x1].copy()))
    return out


def draw_runs(img, x, y_top, h, runs, pal, icon_imgs, outline=None):
    """런 목록을 (x, y_top)부터 한 줄로 — 글자 잉크 높이 h(한글 기준)."""
    from PIL import ImageDraw, ImageFont
    ref = ImageFont.truetype(FONT, 100)
    bb = ref.getbbox("한")
    size = max(6, round(100 * h / (bb[3] - bb[1])))
    f = ImageFont.truetype(FONT, size)
    top = f.getbbox("한")[1]
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    cx = x
    for t, c in runs:
        if t == "@icon":
            box, ic = icon_imgs[c]
            ih = ic.shape[0]
            im.paste(Image.fromarray(ic), (int(cx) + 2, int(y_top + h / 2 - ih / 2)), Image.fromarray(ic))
            cx += ic.shape[1] + 4
            continue
        kw = {"stroke_width": outline[0], "stroke_fill": outline[1]} if outline else {}
        dr.text((cx, y_top - top), t, font=f, fill=pal[c], **kw)
        cx += f.getlength(t)
    return np.array(im), cx


def draw_badge(img, text, cx=133, cy=82, h=33, angle=7.0):
    """배지 아랫줄 글자: 검정 Koverwatch, 원본처럼 오른쪽이 올라가게 angle도 회전."""
    from PIL import ImageDraw, ImageFont
    ref = ImageFont.truetype(FONT, 100)
    bb = ref.getbbox("한")
    f = ImageFont.truetype(FONT, max(6, round(100 * h / (bb[3] - bb[1]))))
    tb = f.getbbox(text)
    layer = Image.new("RGBA", (tb[2] - tb[0] + 20, tb[3] - tb[1] + 20), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((10 - tb[0], 10 - tb[1]), text, font=f, fill=(10, 10, 10, 255))
    if layer.width > 236:                      # 배지 안에 맞춤
        layer = layer.resize((236, layer.height), Image.LANCZOS)
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    im = Image.fromarray(img)
    im.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))
    return np.array(im)


def draft(nm, plat, log=print):
    sp = DRAFT[nm]
    if plat == "ps3":
        base = np.array(Image.open(_p("jp", nm)).convert("RGBA"))
        other = np.asarray(Image.open(_p("x", nm)).convert("RGBA"))
    else:
        base = np.array(Image.open(_p("x", nm)).convert("RGBA"))
        other = np.asarray(Image.open(_p("jp", nm)).convert("RGBA"))
    lines = [y for y, _r in sp["body"]]
    pal = colors(base, lines)
    ics = icons(base, other, lines)
    # 지울 상자: 부제·제목(① 포함)·머리띠 글자·본문 줄
    m = text_mask(base, (258, 32, 470, 90), "light")
    m |= text_mask(base, (232, 112, 820, 135), "dark_bg")
    for y, _runs in sp["body"]:
        m |= text_mask(base, (200, y - 3, 838, y + 17), "light")
    for (x0, y0, x1, y1), _ic in ics:                 # 아이콘 자리도 지운다(새 줄 배치에 다시 놓음)
        m[y0 - 1:y1 + 1, x0 - 1:x1 + 1] = True
    # 배지 아랫줄(必勝アドバイス): 줄무늬 판 위 검은 글자 — 검은 픽셀만 지우고 새 글자가 덮는다
    lum = base[..., :3].astype(int) @ np.array([0.299, 0.587, 0.114])
    bm = np.zeros(lum.shape, bool)
    bm[44:113, 14:252] = lum[44:113, 14:252] < 70
    from PIL import ImageFilter
    m |= np.asarray(Image.fromarray((bm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    rgb = inpaint(base[..., :3], m)
    out = base.copy()
    out[..., :3] = rgb
    out = draw_badge(out, "필승 어드바이스")
    out, _ = draw_runs(out, 265, 35, 16, SUBTITLE, pal, ics)
    out, _ = draw_runs(out, 264, 59, 27, [(sp["title"], "k")], {"k": (20, 20, 20)}, ics)
    out, _ = draw_runs(out, 236, 114, 17, sp["heading"], {**pal, "w": (255, 255, 255)}, ics)
    for y, runs in sp["body"]:
        out, end = draw_runs(out, 207, y, 14, runs, pal, ics)
        if end > 836:
            log(f"  [주의] {nm} {plat} y={y}: 줄이 패널을 넘음(x={end:.0f})")
    return out


def cmd_draft():
    for nm in DRAFT:
        for plat in ("ps3", "x360"):
            img = draft(nm, plat)
            dst = _p("kr", nm) if plat == "ps3" else _p("out", nm)
            if plat == "ps3" and os.path.exists(dst):
                print(f"  [건너뜀] {nm} ps3: kr/ 작업본이 이미 있음(팀/이전)")
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            Image.fromarray(img).save(dst)
            print(f"  {nm} {plat} → {dst}")


def cmd_reuse():
    for nm in CARDS:
        if os.path.exists(_p("kr", nm)) and os.path.exists(_p("x", nm)):
            reuse(nm)


if __name__ == "__main__":
    if sys.argv[1:] == ["reuse"]:
        cmd_reuse()
    elif sys.argv[1:] == ["draft"]:
        cmd_draft()
    else:
        sys.exit(__doc__)
