#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DLC 카탈로그 페이지(360 catalog_info.nut, 1024x512) 글자 Claude 초벌 (2026-10-23 KOR 지시)

페이지 구성: 위 'CHECK!' 배지 뒤 한 줄(lead) · 굵은 제목 한 줄(head) · 품목 이름 막대(검은 둥근 막대 + 왼쪽 아이콘, 흰 글자).
vol 배지·쪽수·품목 그림은 그대로. 글자만 지우고(머리 두 줄은 확산 인페인트, 막대는 막대색으로 메움) Koverwatch로 다시 쓴다.
문구: dlc_cat/out_NN.json (서브에이전트가 그림에서 읽고 번역 — 품목명은 웹앱 의상·액세서리 번역 용어집 우선, 곡명은 null = 그대로).
출력: kr_dlc/<pkg6>/catalog_info_NNN.png (webapp_pull 규칙, dlc_inject 이미지 경로가 읽음) + tex_kr 'Claude 초벌'(팀 작업본은 덮지 않음).

  python dlc_catalog.py preview [--ps3]          # coverage/dlc_cat[_ps3]_review_N.png (원본 | 초벌)
  python dlc_catalog.py write --code … [--ps3]   # kr_dlc/(PS3: kr_dlc_ps3/cpNN/) 쓰기 + tex_kr 'Claude 초벌' 업서트

PS3판(--ps3): pc-360-dlc가 디코드한 dlc_tex_ps3/cpNN/catalog_info_NNN.png, 문구 dlc_cat/ps3/out_*.json.
배치는 360과 같고(lead y47~62, head y70~90, 점선 y96~97, 막대 y128/208) 글자·막대색만 진홍(#830000) — 원문에서 색을 뽑는다.
웹앱 행 키 = md5("ps3:cpNN/catalog_info.nut#NNN") (webapp_seed dlc_image_groups와 같게).
품목명 웹 텍스트 행(cat=dlc catalog/package)은 같은 한국어로 webapp_fill(빈 행만) — 그림과 글이 어긋나지 않게.
"""
import os
import sys
import json
import glob
import time
import base64
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402
from tut_cards import inpaint, components  # noqa: E402

FONT = os.path.join(OUT_DEFAULT, "fonts", "koverwatch", "koverwatch.ttf")
CAT = os.path.join(OUT_DEFAULT, "dlc_cat")
_FC = {}


def font_for(h):
    if h not in _FC:
        ref = ImageFont.truetype(FONT, 100)
        bb = ref.getbbox("한")
        _FC[h] = ImageFont.truetype(FONT, max(6, round(100 * h / (bb[3] - bb[1]))))
    return _FC[h]


def specs(ps3=False):
    out = {}
    for p in sorted(glob.glob(os.path.join(CAT, "ps3" if ps3 else "", "out_*.json"))):
        for it in json.load(open(p, encoding="utf-8")):
            out[it["page"].replace("\\", "/")] = it
    acc = os.path.join(CAT, "acc_labels.json")      # 액세서리 쪽 막대(y≈208)는 첫 판독 범위 밖 — 따로 읽은 품목명
    if os.path.exists(acc):
        for page, labs in json.load(open(acc, encoding="utf-8")).items():
            if page in out and not out[page].get("labels"):
                out[page]["labels"] = labs
    # 메일 쪽은 막대가 두 줄(5 + 4, 둘째 줄 y≈302) — 판독은 첫 줄만 했으므로 둘째 줄은 고정 명단
    # (2026-10-23 pc-360-dlc 지적: 真/真美/貴音/響のメール이 일본어로 남음)
    for it in out.values():
        labs = it.get("labels") or []
        if len(labs) == 5 and all(l["jp"].endswith("のメール") for l in labs) and not it.get("labels2"):
            it["labels2"] = [{"jp": j + "のメール", "kr": k + "의 메일"}
                             for j, k in (("真", "마코토"), ("真美", "마미"), ("貴音", "타카네"), ("響", "히비키"))]
    return out


def plat(ps3):
    """(쪽 목록 [{page, md5, loc}], 원본 루트, 출력 루트). PS3: pc-360-dlc 디코드본, 키 = 위치 문자열 md5(webapp_seed와 같게)."""
    if not ps3:
        pages = json.load(open(os.path.join(CAT, "pages.json"), encoding="utf-8"))
        for p in pages:
            p["loc"] = f"360:{p['page'].split('/')[0]}/catalog_info.nut#{p['page'][-3:]}"
        return pages, os.path.join(OUT_DEFAULT, "dlc_tex"), os.path.join(OUT_DEFAULT, "kr_dlc")
    import hashlib
    pages = json.load(open(os.path.join(CAT, "ps3", "pages.json"), encoding="utf-8"))
    for p in pages:
        p["loc"] = f"ps3:{p['page'].split('/')[0]}/catalog_info.nut#{p['page'][-3:]}"
        p["md5"] = hashlib.md5(p["loc"].encode()).hexdigest()
    return pages, os.path.join(OUT_DEFAULT, "dlc_tex_ps3"), os.path.join(OUT_DEFAULT, "kr_dlc_ps3")


def lum_of(a):
    return a[..., :3].astype(int) @ np.array([0.299, 0.587, 0.114])


def draw_fit(img, text, x0, x1, y_top, h, fill, align="left", stroke=0, target_w=0):
    """[x0, x1) 안에 한 줄 — 넘치면 가로로 줄인다(최대 0.7배), 그래도 넘치면 글자 크기를 줄인다.
    target_w: 원문 글줄 폭 — Koverwatch는 좁은 글꼴이라 원문 폭 쪽으로 가로 최대 1.3배까지 늘린다.
    stroke: 원문이 굵은 고딕이라 같은 색 외곽선으로 굵기 보강."""
    f = font_for(h)
    bb = f.getbbox(text, stroke_width=stroke)
    w = bb[2] - bb[0]
    top = f.getbbox("한")[1]
    layer = Image.new("RGBA", (w + 4, h + 8 + 2 * stroke), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((2 - bb[0], 2 + stroke - top), text, font=f, fill=fill,
                               stroke_width=stroke, stroke_fill=fill)
    avail = x1 - x0
    if layer.width > avail:
        sx = avail / layer.width
        if sx < 0.7:
            return draw_fit(img, text, x0, x1, y_top + 1, h - 1, fill, align, stroke, target_w)
        layer = layer.resize((avail, layer.height), Image.LANCZOS)
    elif target_w > layer.width:
        layer = layer.resize((min(avail, int(target_w), int(layer.width * 1.3)), layer.height), Image.LANCZOS)
    y_top -= stroke
    x = x0 if align == "left" else x0 + (avail - layer.width) // 2
    im = Image.fromarray(img)
    im.alpha_composite(layer, (int(x), int(y_top - 2)))
    return np.array(im)


def find_bars(a, n=0):
    """품목 이름 막대: y 100~420에서 검은 덩어리 중 폭 80+·높이 10~30 — 가장 위 줄의 것들 (x0, y0, x1, y1) 왼→오.
    의상 쪽은 y≈128, 액세서리 쪽은 y≈208에 한 줄.
    행 문턱 160px로 먼저 찾고, 막대 하나짜리 쪽(PS3 무료 액세서리, 폭 220)처럼 글자 행이 문턱 밑으로 떨어져
    개수가 안 맞으면 90px로 다시(처음부터 90이면 메일 쪽 막대가 아래 액자 테두리까지 6px 늘어남)."""
    bars = _find_bars(a, n, 160)
    if n and len(bars) != n:
        bars = _find_bars(a, n, 90) or bars
    return bars


def _find_bars(a, n, thr, y_from=100, y_to=420):
    L = lum_of(a)
    blk = (L < 45) & (a[..., 3] > 200)
    # 막대 안 흰 글자가 행을 끊으므로: 행 투영으로 막대 줄(y) → 그 줄의 열 투영으로 막대들(x)
    rows = blk[y_from:y_to].sum(1) >= thr
    y0 = None
    for y in range(len(rows) + 1):
        on = y < len(rows) and (rows[y] or (y + 1 < len(rows) and rows[y + 1] and y0 is not None))
        if on and y0 is None:
            y0 = y
        elif not on and y0 is not None:
            if 10 <= y - y0 <= 30:
                break
            y0 = None
    else:
        return []
    if y0 is None:
        return []
    y1 = y
    col = blk[y_from + y0:y_from + y1].mean(0) > 0.3
    xs = np.nonzero(col)[0]
    out = []
    for x in xs:
        if out and x - out[-1][1] <= 16:
            out[-1][1] = x
        else:
            out.append([x, x])
    bars = [(int(a_), y_from + y0, int(b_) + 1, y_from + y1) for a_, b_ in out if b_ - a_ >= 80]
    if n and len(bars) == 1 and n > 1:
        # 막대 사이 틈(5~13px)을 아이콘 원이 덮어 한 덩어리로 보임 — 막대는 등간격이라 n등분(틈 12px 가정)
        x0, y0_, x1, y1_ = bars[0]
        pitch = (x1 - x0 + 12) / n
        bars = [(round(x0 + i * pitch), y0_, round(x0 + (i + 1) * pitch) - 12, y1_) for i in range(n)]
    return bars


def ink(a, L, y0, y1, x0, x1, dflt):
    """원문 글자색(360 검정 / PS3 진홍 #830000) — 진한 화소 중앙값."""
    reg = a[y0:y1, x0:x1, :3][L[y0:y1, x0:x1] < 100]
    return tuple(int(v) for v in np.median(reg, 0)) + (255,) if len(reg) > 20 else dflt


def render(page, sp, root=None):
    a = np.array(Image.open(os.path.join(root or os.path.join(OUT_DEFAULT, "dlc_tex"), page + ".png")).convert("RGBA"))
    L = lum_of(a)
    sat = a[..., :3].max(-1) - a[..., :3].min(-1)
    # CHECK! 배지 오른쪽 끝(검은 덩어리, y 40~62)
    blk = (L < 45)
    badge = [c for c in components(blk[38:64, 150:320], gap=0) if c[2] - c[0] > 30]
    lead_x0 = 150 + max(c[2] for c in badge) + 6 if badge else 262
    m = np.zeros(L.shape, bool)
    # lead 글줄 y 47~62, head 글줄 y 70~90(쪽수 아이콘 x≥895 제외), 그 아래 y 96~97 점선 — 실측(0569AF·2C2886)
    m[43:64, lead_x0:1000] = (L[43:64, lead_x0:1000] < 235) | (sat[43:64, lead_x0:1000] > 40)
    m[67:95, 196:895] = (L[67:95, 196:895] < 235) | (sat[67:95, 196:895] > 40)

    def extent(y0, y1, x0, x1):
        xs = np.nonzero((L[y0:y1, x0:x1] < 128).any(0))[0]
        return (x0 + xs.max() + 1) if len(xs) else x0
    lead_w = extent(46, 63, lead_x0, 1000) - lead_x0
    lead_col = ink(a, L, 46, 63, lead_x0, 1000, (30, 30, 30, 255))
    head_col = ink(a, L, 69, 92, 196, 895, (20, 20, 20, 255))
    head_w = extent(69, 92, 196, 895) - 200
    from PIL import ImageFilter
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    m[:43] = False                                      # CHECK! 배지·위 띠는 건드리지 않음
    m[65:67, 196:lead_x0] = False
    dots = np.zeros_like(m)                             # 점선은 확산 출처에서 빼고(회색 번짐 원인) 뒤에 원본으로 복원
    dots[95:99, 196:895] = True
    out = a.copy()
    out[30:100, :, :3] = inpaint(a[30:100, :, :3], (m | dots)[30:100], iters=300)   # 머리 두 줄 띠만(속도)
    out[dots] = a[dots]
    notes = []
    if sp.get("lead", {}).get("kr"):
        out = draw_fit(out, sp["lead"]["kr"], lead_x0, 1000, 46, 16, lead_col, target_w=lead_w)
    if sp.get("head", {}).get("kr"):
        out = draw_fit(out, sp["head"]["kr"], 200, 890, 68, 23, head_col, target_w=head_w)
    labels = sp.get("labels") or []
    bars = find_bars(a, len(labels))
    rows = [(bars, labels)]
    labels2 = sp.get("labels2") or []
    if labels2 and bars:                               # 둘째 줄(메일 쪽): 첫 줄 아래부터 다시 찾는다
        n2 = len(labels2)
        b2 = _find_bars(a, n2, 160, bars[0][3] + 20, 470)
        if len(b2) != n2:
            b2 = _find_bars(a, n2, 90, bars[0][3] + 20, 470) or b2
        rows.append((b2, labels2))
    for bars, labels in rows:
        if labels and len(bars) != len(labels):
            notes.append(f"막대 {len(bars)}개 ≠ 문구 {len(labels)}개 — 품목명 그대로")
            continue
        for (x0, y0, x1, y1), lab in zip(bars, labels):
            if not lab.get("kr"):
                continue                       # 곡명(팀 결정 대기) 등 — 그대로
            tx0 = x0 + 26                      # 왼쪽 아이콘 원 다음부터
            reg = out[y0 + 2:y1 - 1, tx0:x1 - 9]
            Lr = lum_of(reg)
            barcol = np.median(reg[Lr < 45].reshape(-1, 4), 0) if (Lr < 45).any() else np.array([10, 10, 10, 255])
            reg[:] = barcol.astype(np.uint8)                 # 막대 안은 단색 — 글자(안티에일리어싱 포함) 통째로 막대색
            out[y0 + 2:y1 - 1, tx0:x1 - 9] = reg
            h = max(9, (y1 - y0) - 8)               # 원문 흰 글자 y0+4~y0+19
            out = draw_fit(out, lab["kr"], tx0 + 4, x1 - 10, y0 + ((y1 - y0) - h) // 2, h, (255, 255, 255, 255))
    return out, notes


def cmd_preview(a):
    sps = specs(a.ps3)
    pages, root, _dst = plat(a.ps3)
    rows, allnotes = [], []
    for p in pages:
        sp = sps.get(p["page"])
        if not sp:
            continue
        img, notes = render(p["page"], sp, root)
        allnotes += [f"{p['page']}: {n}" for n in notes]
        jp = Image.open(os.path.join(root, p["page"] + ".png")).convert("RGBA")
        rows.append((jp, Image.fromarray(img)))
    per = 6
    for s0 in range(0, len(rows), per):
        ch = rows[s0:s0 + per]
        sheet = Image.new("RGB", (1024, 180 * len(ch)), (40, 40, 60))
        for k, (jp, kr) in enumerate(ch):
            for j, im in enumerate((jp, kr)):
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                bg.alpha_composite(im)
                sheet.paste(bg.convert("RGB").crop((0, 0, 1024, 170)).resize((512, 85)), (j * 512, k * 180))
        sheet.save(os.path.join(OUT_DEFAULT, "coverage", f"dlc_cat{'_ps3' if a.ps3 else ''}_review_{s0 // per:02d}.png"))
    print(f"{len(rows)}쪽 미리보기 → coverage/dlc_cat_review_*.png")
    for n in allnotes:
        print("  [주의]", n)


def cmd_write(a):
    import urllib.request
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    H = {"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}", "x-team-code": a.code,
         "Content-Type": "application/json"}
    sps = specs(a.ps3)
    pages, root, out_root = plat(a.ps3)
    locs, off = {}, 0                        # md5 → 위치 전부(같은 그림이 여러 패키지에 — pc-360-dlc는 패키지별로 찾음)
    while True:
        ch = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{cfg['url']}/rest/v1/rows?cat=eq.image&grp=eq.dlc&select=key,meta&limit=1000&offset={off}", headers=H)))
        for r in ch:
            locs[r["key"]] = (r.get("meta") or {}).get("locs", [])
        if len(ch) < 1000:
            break
        off += 1000
    n = skip = files = 0
    only = set(a.only.split(",")) if a.only else None
    for p in pages:
        sp = sps.get(p["page"])
        if not sp or (only and p["page"] not in only and not ("mail" in only and sp.get("labels2"))):
            continue
        tk = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{cfg['url']}/rest/v1/tex_kr?md5=eq.{p['md5']}&select=by", headers=H)))
        if tk and tk[0]["by"] != "Claude 초벌":
            skip += 1
            continue
        img, _notes = render(p["page"], sp, root)
        dsts = []
        for loc in locs.get(p["md5"]) or [p["loc"]]:
            rel, nn = loc.rsplit("#", 1)       # webapp_pull 규칙과 같게: kr_dlc(_ps3)/<pkg6|cpNN>/<경로 / → _, 확장자 제외>_<n>.png
            pkg, path = rel.split(":", 1)[1].split("/", 1)
            dsts.append(os.path.join(out_root, pkg,
                                     f"{path.replace('/', '_').rsplit('.', 1)[0]}_{nn}.png"))
        for dst in dsts:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            Image.fromarray(img).save(dst)
        files += len(dsts)
        dst = dsts[0]
        body = json.dumps([{"md5": p["md5"], "by": "Claude 초벌", "ts": int(time.time() * 1000),
                            "data": base64.b64encode(open(dst, "rb").read()).decode()}]).encode()
        urllib.request.urlopen(urllib.request.Request(cfg["url"] + "/rest/v1/tex_kr?on_conflict=md5", data=body,
                                                      method="POST",
                                                      headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"}))
        n += 1
    print(f"카탈로그 페이지 초벌 {n}장 → {os.path.basename(out_root)}/ {files}개 위치 (팀 작업본이라 건너뜀 {skip})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preview")
    p.add_argument("--ps3", action="store_true", help="PS3판 카탈로그(dlc_tex_ps3 → kr_dlc_ps3)")
    p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("write")
    p.add_argument("--code", required=True)
    p.add_argument("--ps3", action="store_true")
    p.add_argument("--only", help="쉼표로 쪽 이름(예: cp01/catalog_info_019), 또는 mail = 메일 쪽(막대 두 줄)만")
    p.set_defaults(fn=cmd_write)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
