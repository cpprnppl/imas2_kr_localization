#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
레슨·커뮤니케이션 결과 배너(「バッドレッスン」 등 8종) — 글자 타일 조립식 한글화

배너는 그림 한 장이 아니라 game/les_com.mpc 안 ProResult.swg(플래시 계열 SWG)가
가타카나 한 글자짜리 64x64 타일(4색: 퍼펙트=분홍·굿=주황·노멀=초록·배드=파랑)을
56px 간격 칸에 하나씩 놓아 만든다. 타일은 색마다 레슨/커뮤 두 단어가 같이 쓴다
(ッ는 バッドレッスン 안에서도 두 번). 그래서 텍스처만 바꾸면 한글이 안 된다.

방식(크기·구조 불변, 제자리 교체):
  1) 색 세트마다 두 단어의 한글 음절(공백 = 빈 칸)을 모아, 그 세트의 글자 스프라이트
     (1프레임·타일 1장) 하나에 음절 하나씩 배정하고 그 타일 텍스처를 음절로 다시 그린다.
  2) 단어 스프라이트의 배치 명령(0xFFFFFFF5/4: depth, char, …)의 char id를 칸별
     음절 스프라이트로 바꾼다. 칸 수보다 짧으면 양끝 칸을 빈 타일로(가운데 정렬).
  위치·애니메이션(행렬·프레임)은 손대지 않는다.

SWG(빅엔디언, 'SWG\\0'+해시+이름 0x40) 헤더 +0x54 행렬표(4x4 float) +0x64 비트맵표
(12B: id, w<<16|h, flag — id = 같은 TSK의 nut 텍스처 순번) +0x7C 캐릭터표(8B: 종류,
위치; 0=모양/버튼, 5=스프라이트) +0x80 캐릭터 수. 모양 40B(+16 비트맵 번호),
스프라이트 20B(프레임 수, 라벨, ?, 프레임표, 명령 수), 프레임표 8B(명령 위치, 개수),
명령: F5=배치(depth, char, 행렬, 색) 20B / F4=배치 16B / 그 밖 = 변경 12B.

번역 출처: label_specs.json items["banner_<이름>"].text (webapp_pull image가 채움).
색 세트의 두 단어가 다 번역돼야 그 세트를 적용(타일을 같이 쓰므로).

  python tile_banner.py render     # RELS 파일마다 kr/<경로>/<이름>_NNN.png 타일 + 미리보기(coverage/)
  python tile_banner.py thumbs     # 원본 배너 합성 PNG(웹앱 썸네일용, coverage/banner_jp/)
  (패치는 ps3_res_apply / pcport_apply가 patch_container()를 부른다)
"""
import os
import sys
import json
import struct
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

REL = "game\\les_com.mpc"
# ProResult.swg 사본(SWG·타일 72장 바이트 동일)을 가진 파일. 실제 레슨 결과 화면은 alf_common 쪽을 쓴다
# (2026-10-23 Mac 확인: les_com만 바꿨을 때 배너가 일본어로 남음).
RELS = (REL, "game\\alf\\alf_common.mpc")
SWG_NAME = b"ProResult"
PITCH = 56                      # 칸 간격(px) — 8단어 전부 56px 등간격(배치 행렬 실측)

# 이름 → (원문, 색 세트). 이름은 SWG 심볼(LesBad_mc 등)과 같다.
BANNERS = {
    "LesPer": ("パーフェクトレッスン", "p"), "LesGod": ("グッドレッスン", "o"),
    "LesNor": ("ノーマルレッスン", "g"), "LesBad": ("バッドレッスン", "b"),
    "ComPer": ("パーフェクトコミュニケーション", "p"), "ComGod": ("グッドコミュニケーション", "o"),
    "ComNor": ("ノーマルコミュニケーション", "g"), "ComBad": ("バッドコミュニケーション", "b"),
}
SET_LABEL = {"p": "퍼펙트(분홍)", "o": "굿(주황)", "g": "노멀(초록)", "b": "배드(파랑)"}

# ProResult 비트맵 번호 → (가타카나 타일, 색 세트). 타일 육안 판독(2026-10-23).
# ュ/ョ는 따로 타일이 없고 ユ/ヨ 타일이 그 자리에 쓰인다.
_K = {"p": (1, "ユヨットスシレパニンミクコケフェー"), "g": (18, "ユヨッスシルレノニンミマコケー"),
      "o": (34, "ユヨッスシレニンミコケグドー"), "b": (50, "ヨッスシレユニンミコケドバー")}
KANA = {b0 + i: (ch, s) for s, (b0, chars) in _K.items() for i, ch in enumerate(chars)}
SMALL = str.maketrans("ュョ", "ユヨ")

# 색 세트 스타일(원본 타일 실측): 글로 색, 외곽 1px 색, 채움 위·아래 색
STYLE = {"p": ((255, 123, 225), (255, 45, 181), (255, 212, 239), (255, 198, 234)),
         "g": ((3, 204, 90), (41, 190, 115), (215, 246, 226), (186, 238, 201)),
         "o": ((255, 163, 0), (239, 158, 12), (254, 239, 205), (255, 228, 149)),
         "b": ((0, 77, 200), (54, 109, 211), (159, 218, 240), (212, 230, 252))}
GLOW = [255, 249, 228, 203, 152, 102, 61, 30, 10, 0]     # 외곽에서 거리(px)별 알파(원본 실측)
# 글꼴: Koverwatch(사용자 지시 "네가 이미지 만든거나 만들거는 이 폰트로", 라이선스 미상이라 git 밖 로컬 경로)
FONT = os.path.join(os.path.expanduser("~"), "Desktop", "imas2_image_text", "fonts", "koverwatch", "koverwatch.ttf")
BOX = 54                        # 음절 잉크 높이(원본 가타카나 채움+외곽 ≈ 50px)
BOLD = 0.0                      # 획 굵히기(px, 지름) — Koverwatch는 그대로 굵다(굵히면 뭉개짐)
EDGE = 1.0                      # 외곽선 두께(px)


def _w(b, o):
    return struct.unpack_from(">I", b, o)[0]


# ---------------------------------------------------------------- SWG 해석
def find_swg(plain):
    """ProResult.swg 시작 위치('SWG\\0'). 없으면 None."""
    i = 0
    while True:
        i = plain.find(b"SWG\x00", i)
        if i < 0:
            return None
        if plain[i + 8:i + 8 + len(SWG_NAME) + 1] == SWG_NAME + b"\x00":
            return i
        i += 4


def parse(plain, base):
    """→ dict(bitmaps=[(w,h)], chars=[(kind, ofs)], sprites={char: rec}, shape_bmp={char: bmp})"""
    s = memoryview(plain)[base:]
    bm_ofs, bm_n = _w(s, 0x64), _w(s, 0x68)
    ch_ofs, ch_n = _w(s, 0x7C), _w(s, 0x80)
    mt_ofs = _w(s, 0x54)                                # 행렬표(4x4 float 열우선, +48 = x 이동)
    bitmaps = []
    for i in range(bm_n):
        bid, wh = _w(s, bm_ofs + i * 12), _w(s, bm_ofs + i * 12 + 4)
        if bid != i:
            raise ValueError(f"SWG 비트맵표 순번 불일치 #{i}={bid}")
        bitmaps.append((wh >> 16, wh & 0xFFFF))
    chars, shape_bmp, sprites = [], {}, {}
    for c in range(ch_n):
        kind, ofs = _w(s, ch_ofs + c * 8), _w(s, ch_ofs + c * 8 + 4)
        chars.append((kind, ofs))
        if kind == 0 and _w(s, ofs) == 1:                  # 모양: (1, 0, 다음, 그룹, 비트맵, …, w, h)
            shape_bmp[c] = _w(s, ofs + 16)
        elif kind == 5:
            nf, _lab, _dep, ft, _nr = (_w(s, ofs + k * 4) for k in range(5))
            frames = []
            for f in range(nf):
                p, n = _w(s, ft + f * 8), _w(s, ft + f * 8 + 4)
                cmds, o = [], p
                for _ in range(n):
                    op = _w(s, o)
                    if op in (0xFFFFFFF5, 0xFFFFFFF4):
                        mx = struct.unpack_from(">f", s, mt_ofs + _w(s, o + 12) * 64 + 48)[0]
                        cmds.append((o, _w(s, o + 4), _w(s, o + 8), mx))    # (명령 위치, depth, char, 첫 x)
                        o += 20 if op == 0xFFFFFFF5 else 16
                    else:
                        o += 12
                frames.append(cmds)
            sprites[c] = frames
    return {"bitmaps": bitmaps, "chars": chars, "shape_bmp": shape_bmp, "sprites": sprites}


def analyze(plain):
    """글자 스프라이트·단어 스프라이트 판별 → (base, P, letters{char: bmp}, words{이름: [(depth, [명령위치…], char)]})"""
    base = find_swg(plain)
    if base is None:
        raise ValueError("ProResult.swg 없음")
    P = parse(plain, base)
    letters = {}
    for c, frames in P["sprites"].items():          # 1프레임·배치 1개·KANA 타일 모양
        if len(frames) == 1 and len(frames[0]) == 1:
            sc = frames[0][0][2]
            b = P["shape_bmp"].get(sc)
            if b in KANA:
                letters[c] = b
    words = {}
    for c, frames in P["sprites"].items():
        slots = {}
        for cmds in frames:
            for o, d, ch, mx in cmds:
                if ch in letters:
                    slots.setdefault(d, [[], ch, mx])[0].append(o)
        if len(slots) < 4:
            continue
        # 왼→오른 순서 = 첫 배치 x, 같으면 depth 큰 쪽이 왼쪽(グッド는 한 점에서 펼쳐짐 — 실측).
        # 결과 가타카나가 BANNERS 원문과 맞아야 통과하므로 순서 오판은 여기서 걸린다.
        seq = sorted(slots.items(), key=lambda kv: (round(kv[1][2]), -kv[0]))
        jp = "".join(KANA[letters[v[1]]][0] for _d, v in seq)
        name = next((k for k, (j, _s) in BANNERS.items() if j.translate(SMALL) == jp), None)
        if name is None:
            raise ValueError(f"알 수 없는 배너 스프라이트 #{c}: {jp}")
        if name in words:
            raise ValueError(f"배너 {name} 중복")
        words[name] = [(d, v[0], v[1]) for d, v in seq]     # (depth, [명령 위치…], 원래 글자 스프라이트)
    if set(words) != set(BANNERS):
        raise ValueError(f"배너 8종 중 못 찾음: {sorted(set(BANNERS) - set(words))}")
    return base, P, letters, words


# ---------------------------------------------------------------- 배정
def slot_glyphs(kr, n):
    """한글 문구 → 칸 n개짜리 글자 목록(공백·양끝 패딩 = ''). 넘치면 ValueError."""
    g = ["" if ch == " " else ch for ch in kr.strip()]
    if len(g) > n:
        raise ValueError(f"'{kr}' {len(g)}칸 > {n}칸")
    left = (n - len(g)) // 2
    return [""] * left + g + [""] * (n - len(g) - left)


GAP_SHIFT = 8      # 공백 칸 옆 글자를 타일 안에서 공백 쪽으로 미는 양(px) — 공백이 한 칸(56px)이라 너무 넓다(KOR 지적)


def gap_shift(texts):
    """{(세트, 글자): dx} — 공백 앞 단어 글자는 오른쪽(+), 뒤 단어 글자는 왼쪽(−)으로. 타일은 세트 안에서
    공유되므로 같은 글자가 두 방향에 다 쓰이면 0."""
    out = {}
    for k, (_jp, s) in BANNERS.items():
        t = (texts or {}).get(k, "").strip()
        if " " not in t:
            continue
        a, b = t.split(" ", 1)
        for chs, dx in ((a, GAP_SHIFT), (b.replace(" ", ""), -GAP_SHIFT)):
            for ch in chs:
                key = (s, ch)
                out[key] = dx if out.get(key, dx) == dx else 0
    return out


def kr_texts():
    p = os.path.join(HERE, "label_specs.json")
    items = json.load(open(p, encoding="utf-8")).get("items", {}) if os.path.exists(p) else {}
    return {k: (items.get(f"banner_{k}") or {}).get("text", "").replace("\n", " ").strip() for k in BANNERS}


def plan(plain, texts=None, log=print):
    """→ (tiles{bmp: 글자|''}, repl{명령위치(SWG 기준): 새 char}, base, applied[이름])"""
    texts = kr_texts() if texts is None else texts
    base, P, letters, words = analyze(plain)
    tiles, repl, applied = {}, {}, []
    for s in "pogb":
        names = [k for k, (_j, ss) in BANNERS.items() if ss == s]
        if not all(texts.get(k) for k in names):
            if any(texts.get(k) for k in names):
                log(f"  [보류] {SET_LABEL[s]}: 두 단어({'/'.join(names)})가 다 번역돼야 적용(타일 공유)")
            continue
        lay = {k: slot_glyphs(texts[k], len(words[k])) for k in names}
        need = []
        for k in names:
            for gch in lay[k]:
                if gch not in need:
                    need.append(gch)
        pool = sorted({ch for k in names for _d, _o, ch in words[k]})     # 이 세트 글자 스프라이트
        if len(need) > len(pool):
            raise ValueError(f"{SET_LABEL[s]}: 서로 다른 글자 {len(need)}개 > 타일 {len(pool)}장 — 문구를 줄여야 함")
        spr = dict(zip(need, pool))
        for gch, c in spr.items():
            tiles[letters[c]] = gch
        for k in names:
            for (_d, offs, _ch), gch in zip(words[k], lay[k]):
                for o in offs:
                    repl[o] = spr[gch]
            applied.append(k)
    return tiles, repl, base, applied


def swg_textures(plain, base):
    """SWG 바로 뒤 nut(같은 TSK)의 텍스처 목록 — 비트맵 id = 이 목록 순번. 360 'NTXR'도 처리."""
    from extract_image_text import walk_nuts
    texs = walk_nuts(plain.replace(b"NTXR", b"NTP3"), lambda *a: None)
    after = [t for t in texs if t["nut_off"] > base]
    if not after:
        return []
    first = min(t["nut_off"] for t in after)
    return [t for t in after if t["nut_off"] == first]


def patch_container(plain, texts=None, log=print, orig=None):
    """복호 컨테이너(les_com.mpc)의 SWG 배치 char id만 제자리 교체. 텍스처는 kr/ PNG가 따로 들어간다.
    orig(같은 판의 원본 복호본)를 주면 배정된 타일 텍스처가 전부 바뀌었는지 확인 — 타일 없이 칸만
    바꾸면 가타카나가 뒤섞인 배너가 되므로 그때는 거부. → (새 바이트, 적용 단어 수)"""
    if find_swg(plain) is None:
        return plain, 0
    tiles, repl, base, applied = plan(plain, texts, log)
    if not repl:
        return plain, 0
    if orig is not None:
        tp, to = swg_textures(plain, base), swg_textures(orig, base)
        same = [b for b in tiles if plain[tp[b]["data_off"]:tp[b]["data_off"] + tp[b]["data_size"]]
                == orig[to[b]["data_off"]:to[b]["data_off"] + to[b]["data_size"]]]
        if same:
            raise ValueError(f"배너 타일 텍스처 {len(same)}장이 원본 그대로(비트맵 {same[:6]}…) — "
                             "tile_banner.py render → inject_image_text 순서로 먼저 만들 것")
    out = bytearray(plain)
    for o, c in repl.items():
        struct.pack_into(">I", out, base + o + 8, c)
    # 검증: 다시 해석해서 바뀐 칸 밖 바이트 불변·새 char가 전부 글자 스프라이트인지
    P2 = parse(bytes(out), base)
    letters = {c for c, fr in P2["sprites"].items() if len(fr) == 1 and len(fr[0]) == 1
               and P2["shape_bmp"].get(fr[0][0][2]) in KANA}
    if any(c not in letters for c in repl.values()) or len(out) != len(plain):
        raise ValueError("SWG 패치 검증 실패")
    diff = np.nonzero(np.frombuffer(bytes(out), np.uint8) != np.frombuffer(plain, np.uint8))[0]
    ok = {base + o + 8 + k for o in repl for k in range(4)}
    if any(int(i) not in ok for i in diff):
        raise ValueError("SWG 패치가 배치 char 칸 밖을 바꿈")
    log(f"    배너 {len(applied)}종 SWG 칸 {len(repl)}개 교체 ({', '.join(applied)})")
    return bytes(out), len(applied)


# ---------------------------------------------------------------- 타일 렌더
_FONT = {}


def _font(SS):
    """글자 크기는 음절마다 맞추지 않고 하나로(크기·기준선이 고른 글줄). 기준 음절 '퍼한뷁'의 잉크
    높이가 BOX px이 되는 크기와, 그 잉크를 타일 세로 가운데에 놓는 위쪽 보정값."""
    if SS not in _FONT:
        font_p = FONT
        sz = 40 * SS
        for _ in range(4):
            f = ImageFont.truetype(font_p, sz)
            x0, y0, x1, y1 = f.getbbox("퍼한뷁")
            sz = round(sz * (BOX - BOLD - 2 * EDGE) * SS / (y1 - y0))    # 굵히기·외곽선을 더해 BOX
        f = ImageFont.truetype(font_p, sz)
        _x0, y0, _x1, y1 = f.getbbox("퍼한뷁")
        _FONT[SS] = (f, (y0 + y1) // 2)
    return _FONT[SS]


def render_tile(ch, s, size=64, dx=0):
    """음절 하나 → 원본 가타카나 타일 스타일 RGBA(64x64). ''면 완전 투명."""
    out = np.zeros((size, size, 4), np.uint8)
    if not ch:
        return out
    glow_c, edge_c, top_c, bot_c = (np.array(c, float) for c in STYLE[s])
    SS = 4                                   # 전부 4배 해상도에서 만들고 마지막에 줄인다(외곽선 계단 방지)
    S = size * SS
    f, top = _font(SS)
    tmp = Image.new("L", (S * 2, S * 2), 0)
    ImageDraw.Draw(tmp).text((S // 2, S - top), ch, font=f, fill=255)   # 잉크 세로 중심 = tmp 가운데
    if BOLD:
        tmp = tmp.filter(ImageFilter.MaxFilter(_odd(BOLD * SS)))
    bb = tmp.getbbox()
    ink = tmp.crop((bb[0], 0, bb[2], tmp.height))                      # 가로만 잉크 기준, 세로는 공통 기준선
    if ink.width < 44 * SS:                 # Koverwatch는 좁다 — 가타카나 타일 폭 쪽으로 가로 1.3배까지
        ink = ink.resize((int(min(ink.width * 1.3, 44 * SS)), ink.height), Image.LANCZOS)
    if ink.width > (size - 10) * SS:
        ink = ink.resize(((size - 10) * SS, ink.height), Image.LANCZOS)
    fill_m = Image.new("L", (S, S), 0)
    room = (S - ink.width) // 2 - SS                 # 글자가 타일 밖으로 나가지 않게
    dxs = max(-room, min(room, dx * SS))
    fill_m.paste(ink, ((S - ink.width) // 2 + dxs, -S // 2))
    edge_m = fill_m.filter(ImageFilter.MaxFilter(_odd(2 * EDGE * SS)))     # 채움 + 외곽선 1px
    glow_m = edge_m.filter(ImageFilter.MaxFilter(_odd(2 * 2.5 * SS))).filter(
        ImageFilter.GaussianBlur(2.2 * SS))                                 # 원본 글로(거리 1→8px, 알파 249→10) 근사
    inner_m = fill_m.filter(ImageFilter.MinFilter(_odd(2 * 1.5 * SS))).filter(ImageFilter.GaussianBlur(SS))
    F = np.asarray(fill_m, float)[..., None] / 255
    E = np.asarray(edge_m, float)[..., None] / 255
    G = np.asarray(glow_m, float)[..., None] / 255
    I = np.asarray(inner_m, float)[..., None] / 255
    ys = np.nonzero(np.asarray(fill_m) > 127)[0]
    y0, y1 = (ys.min(), ys.max()) if len(ys) else (0, S - 1)
    ty = np.clip((np.arange(S) - y0) / max(1, y1 - y0), 0, 1)[:, None, None]
    fill = top_c * (1 - ty) + bot_c * ty
    fill = fill + (255 - fill) * 0.4 * I                                   # 획 가운데일수록 밝게(원본 하이라이트)
    # 바깥→안: 글로색 → 외곽색 → 채움 (알파 = 글로∪외곽∪채움)
    rgb = glow_c * (1 - E) + edge_c * E
    rgb = rgb * (1 - F) + fill * F
    a = np.maximum(G[..., 0], E[..., 0])
    prem = np.concatenate([rgb * a[..., None], a[..., None] * 255], -1)    # 프리멀티플라이로 축소
    small = np.asarray(Image.fromarray(np.clip(prem, 0, 255).astype(np.uint8), "RGBA")
                       .resize((size, size), Image.BOX), float)
    al = small[..., 3:4] / 255
    out[..., :3] = np.clip(np.where(al > 0, small[..., :3] / np.maximum(al, 1e-6), 0), 0, 255).round()
    out[..., 3] = small[..., 3].round()
    return out


def _odd(px):
    return int(round(px)) // 2 * 2 + 1


# ---------------------------------------------------------------- CLI
def _ps3_plain(rel=REL):
    from extract_image_text import ps3_src
    from platform_audit import dec_any
    return dec_any(open(ps3_src(rel), "rb").read(), "ps3")


def _tex_base(plain, base):
    """ProResult 비트맵 0번 = les_com 전체 텍스처 순번 몇 번인지(SWG보다 앞 nut의 텍스처 수)."""
    from extract_image_text import walk_nuts
    texs = walk_nuts(plain, lambda *a: None)
    return sum(1 for t in texs if t["nut_off"] < base), texs


def compose(plain, base, P, word, glyph_tex, letters):
    """배너 한 단어 합성(칸 56px). glyph_tex: 칸별 RGBA 64x64 목록."""
    n = len(glyph_tex)
    im = Image.new("RGBA", (PITCH * (n - 1) + 64, 64), (0, 0, 0, 0))
    for i, a in enumerate(glyph_tex):
        im.alpha_composite(Image.fromarray(a), (i * PITCH, 0))
    return im


def cmd_render(_a):
    from extract_image_text import OUT_DEFAULT, decode_texture
    texts = kr_texts()
    shifts = gap_shift(texts)
    made = {}
    for rel in RELS:                     # 같은 ProResult 사본을 가진 파일마다 그 파일 번호로 타일을 낸다
        plain = _ps3_plain(rel)
        tiles, _repl, base, applied = plan(plain, texts, log=(print if rel == RELS[0] else lambda *a: None))
        t0, texs = _tex_base(plain, base)
        _b, P, letters, words = analyze(plain)
        kr_dir = os.path.join(OUT_DEFAULT, "kr", os.path.dirname(rel))
        stem = os.path.splitext(os.path.basename(rel))[0]
        os.makedirs(kr_dir, exist_ok=True)
        for b in KANA:                   # 지난 렌더의 타일 중 이번 계획에 없는 것은 지운다(반쪽 적용 방지)
            p = os.path.join(kr_dir, f"{stem}_{t0 + b:03d}.png")
            if b not in tiles and os.path.exists(p):
                os.remove(p)
                print(f"  이전 타일 삭제: {os.path.basename(p)}")
        for b, gch in sorted(tiles.items()):
            n = t0 + b
            t = texs[n]
            if (t["w"], t["h"]) != tuple(P["bitmaps"][b]) or (t["w"], t["h"]) != (64, 64):
                raise ValueError(f"{rel} 텍스처 #{n} 치수가 SWG 비트맵 #{b}와 다름")
            Image.fromarray(render_tile(gch, KANA[b][1], dx=shifts.get((KANA[b][1], gch), 0))).save(os.path.join(kr_dir, f"{stem}_{n:03d}.png"))
            made[f"{rel}#{n:03d}"] = gch
    plain = _ps3_plain()
    tiles, _repl, base, applied = plan(plain, texts, log=lambda *a: None)
    t0, texs = _tex_base(plain, base)
    _b, P, letters, words = analyze(plain)
    # 미리보기: 단어별 원본 / 한글
    rows = []
    for k in BANNERS:
        if k not in applied:
            continue
        lay = slot_glyphs(texts[k], len(words[k]))
        jp_t = []
        for _d, _o, ch in words[k]:
            t = texs[t0 + letters[ch]]
            jp_t.append(decode_texture(t["fmt"], plain[t["data_off"]:t["data_off"] + t["data_size"]], 64, 64))
        rows.append((compose(plain, base, P, k, jp_t, letters),
                     compose(plain, base, P, k, [render_tile(g, BANNERS[k][1], dx=shifts.get((BANNERS[k][1], g), 0)) for g in lay], letters)))
    if rows:
        W = max(r[0].width for r in rows) + 16
        sheet = Image.new("RGBA", (W, len(rows) * 140 + 8), (70, 60, 50, 255))
        for i, (j, kimg) in enumerate(rows):
            sheet.alpha_composite(j, ((W - j.width) // 2, 8 + i * 140))
            sheet.alpha_composite(kimg, ((W - kimg.width) // 2, 8 + i * 140 + 66))
        p = os.path.join(OUT_DEFAULT, "coverage", "banner_preview.png")
        sheet.save(p)
        print(f"미리보기: {p}")
    print(f"타일 {len(made)}장 ({', '.join(RELS)}) → kr/, 적용 단어 {applied}")
    return made


def cmd_thumbs(_a):
    from extract_image_text import OUT_DEFAULT, decode_texture
    plain = _ps3_plain()
    base, P, letters, words = analyze(plain)
    t0, texs = _tex_base(plain, base)
    d = os.path.join(OUT_DEFAULT, "coverage", "banner_jp")
    os.makedirs(d, exist_ok=True)
    for k, slots in words.items():
        jp_t = []
        for _d, _o, ch in slots:
            t = texs[t0 + letters[ch]]
            jp_t.append(decode_texture(t["fmt"], plain[t["data_off"]:t["data_off"] + t["data_size"]], 64, 64))
        im = compose(plain, base, P, k, jp_t, letters)
        im.save(os.path.join(d, f"banner_{k}.png"))
        print(k, BANNERS[k][0], f"{len(slots)}칸", im.size)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render").set_defaults(fn=cmd_render)
    sub.add_parser("thumbs").set_defaults(fn=cmd_thumbs)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
