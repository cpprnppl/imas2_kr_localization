#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IM@S2 한글 폰트 리패처 (CLI, 균일 셀 방식)

기존 font_patcher.py(GUI)의 품질 문제를 해결하는 재작성판.
- 원인 1: NFH 레코드의 +16(샘플 rect 폭<<8|높이)·+4(bearingX)를 갱신하지 않아
  좁은 한자 슬롯(예: '세'→訁 rect 14×25)에서 한글 오른쪽이 잘림.
- 원인 2: +6은 advance가 아니라 bearingY(베이스라인 위 잉크 높이). 기존 패처가
  여기에 advance를 써서 글리프가 1~2px 떠 있었음. 진짜 advance는 +8.
- 원인 3: 글리프를 셀 경계로 클리핑하지 않아 위/아랫줄에 픽셀 혼입.

중국팀 패치(BLJS10083) 분석으로 확정한 레코드 구조(32B, big-endian):
  +0  u16 atlas x        +2  u16 atlas y
  +4  u16 bearingX<<6    +6  u16 bearingY<<6 (베이스라인~잉크 상단)
  +8  u16 advance<<6     +10 s16 -(rect폭/2)<<6 (하프스케일 센터링)
  +12 u16 상단갭/2<<6     +14 u16 em(27)<<6
  +16 u16 rect(w<<8|h)   +18 u16 code        +28 u32 gidx

적용 방식(중국팀과 동일한 균일 셀):
  - 타깃 슬롯마다 아틀라스의 원본 한자 잉크 rect를 지우고, (x,y) 기준 25×25 셀에
    글리프를 렌더(셀 내 베이스라인 = y+22). 셀 밖 잉크는 어떤 경우에도 그리지 않음.
  - 필드: +4=0, +6=22<<6, +8=Noto advance<<6, +10=-(13<<6), +12=0, +16=25<<8|25
  - 이웃 레코드 rect와 겹치면(좁은 슬롯) 아틀라스 빈 영역으로 재배치(x,y/gidx 갱신).
    재배치 불가 시에만 글리프 축소.

원본은 순정 백업에서만 읽고(MD5 검증), 산출물은 output/ 에 쓴다. 배포는 deploy_fonts.py.
"""
import os
import sys
import json
import struct
import hashlib
import argparse

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")

USR = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR"
FONT_PATH = r"C:\Users\jackfilm\Desktop\xenia\NotoSansCJKjp-Medium.otf"
MAPPING_PATH = os.path.join(USR, r"resource\gscript\tools\font_mapping.json")

# 순정 백업 (읽기 전용) — 타임스탬프 백업 전체가 동일 해시임을 확인한 원본
PRISTINE = {
    "im2_font": {
        "nut": os.path.join(USR, r"_backup\im2_font_20260223_023134.nut"),
        "nfh": os.path.join(USR, r"_backup\im2_font_20260223_023134.nfh"),
        "md5_nut": "f5451c353daf35d1867bfd16cdd2cc8f",
        "md5_nfh": "da99834ce4a0846f9bdd22b4e584bfee",
        # 2048×4096 단일 시트 — 공간 여유가 있어 대형 셀 사용 (대사창 폰트)
        "params": {"size": 27, "cell": (26, 27), "baseline": 23, "pad": 1},
    },
    "im2_font_l": {
        "nut": os.path.join(USR, r"_backup\im2_font_l_20260223_022937.nut"),
        "nfh": os.path.join(USR, r"_backup\im2_font_l_20260223_022937.nfh"),
        "md5_nut": "e94c9af9db807530e69101542f7139a2",
        "md5_nfh": "d772158afc8fe74a7aa7e12e071fada5",
        # 512×512 ×29 시트 — 밀도가 높아 26×27 셀·할로는 공간 부족(실측). 셀 25×25
        # 유지하되, 2026-10-16 가사 하단 조각선 리포트(폰트 v2 후에도 잔존 — 가사가
        # 이 폰트로 추정) 대응: 잉크 pad 1px + 샘플 rect를 셀보다 1px 안쪽 23×23으로
        # 축소(rect_inset). 이웃 rect가 0px 간격으로 붙어도 rect 경계 바이리니어가
        # 자기 빈 테두리만 읽게 된다. 크기 26→25(pad 수용), 베이스라인 22→21.
        "params": {"size": 25, "cell": (25, 25), "baseline": 21, "halo": False,
                   "pad": 1, "rect_inset": 1},
    },
}

# 2026-10-15 상향(26→28) 후 2026-10-16 사용자 리포트로 1px 하향(28→27):
# 28px는 잉크가 셀 경계에 닿아 글자 옆 점선 줄(이웃/잔여 픽셀 블리딩)이 보이고
# 커뮤에서 baseline이 낮아 보임 → size 27 + 셀 내부 pad 1px(잉크 ≤24×25) +
# 베이스라인 23(1px 상향) + 배치 시 셀 둘레 1px 링 클리어.
# 셀 26×27, advance 26px 균일은 유지 → excel2scb WRAP(702px, 한글 27자/줄) 불변.
FONT_SIZE = 27
CELL_W, CELL_H = 26, 27
CELL_BASELINE = 23          # 셀 상단에서 베이스라인까지
ADV_PX = 26                 # 균일 전진폭(px) — excel2scb WRAP 재보정의 기준값
ADV_FALLBACK = ADV_PX

# 매핑에 없어 인게임 공백이던 한글 6자 → 추가 희생 슬롯 (희생 풀에서 기존 2353 바로 앞 6개)
NEW_CHARS = {"큿": "睆", "큥": "睇", "햣": "睚", "쌰": "睛", "겍": "睜", "츗": "睟"}

# 한글(Noto)과 원본 Rodin 문장부호의 글리프 디자인 위치가 2~5px 달라(예: 、
# Rodin by4/h6 vs Noto by7/h9) 혼용 시 아랫선이 어긋나 보인다 → 이 문장부호는
# "자기 슬롯에"(코드 유지, 매핑·SCB 무관) Noto로 재렌더해 한글과 같은 메트릭으로
# 통일한다. 미번역 일본어 줄도 같은 글리프를 쓰지만 모양 차이는 미미.
# 전각 영숫자(０-９Ａ-Ｚ)도 한글 문장에 자주 섞여(ＴＶ, Ｓ４Ｕ…) 같이 재렌더
# (2026-10-14 사용자 승인).
PUNCT_RERENDER = ("、。，．！？…‥「」『』～ー・：；（）"
                  + "".join(chr(c) for c in range(0xFF10, 0xFF1A))    # ０-９
                  + "".join(chr(c) for c in range(0xFF21, 0xFF3B)))   # Ａ-Ｚ

NFH_RB, NFH_RS = 0x474, 32


# ---------------------------------------------------------------- DXT3 alpha

def dxt3_alpha_decode(raw: bytes, w: int, h: int) -> np.ndarray:
    bw, bh = w // 4, h // 4
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(bh * bw, 16)[:, :8]
    v = arr.reshape(bh * bw, 4, 2).astype(np.uint16)
    v = v[:, :, 0] | (v[:, :, 1] << 8)
    nib = np.stack([(v >> (4 * i)) & 0xF for i in range(4)], axis=-1)
    return (nib * 17).astype(np.uint8).reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(h, w)


def dxt3_alpha_encode(alpha: np.ndarray, orig: bytes) -> bytes:
    """알파만 교체하고 각 블록의 컬러 파트(8B)는 원본 블록 것을 유지한다."""
    h, w = alpha.shape
    bw, bh = w // 4, h // 4
    a4 = ((alpha.astype(np.uint16) + 8) // 17).astype(np.uint16)
    blocks = a4.reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(bh * bw, 4, 4)
    v = blocks[:, :, 0] | (blocks[:, :, 1] << 4) | (blocks[:, :, 2] << 8) | (blocks[:, :, 3] << 12)
    out = np.frombuffer(orig, dtype=np.uint8).copy().reshape(bh * bw, 16)
    out[:, 0:8:2] = (v & 0xFF).astype(np.uint8)
    out[:, 1:8:2] = (v >> 8).astype(np.uint8)
    return out.tobytes()


# ---------------------------------------------------------------- NUT / NFH

def nut_textures(nut: bytes):
    """NTP3 NUT 파싱 — 이 게임 폰트의 실제 레이아웃:
    80바이트 텍스처 헤더 count개가 0x10부터 연속 배치되고(헤더 i의 GIDX=i),
    픽셀 데이터는 0x10+80*count부터 각 텍스처의 dataSize만큼 연속.
    (im2_font: count=1이라 '헤더 바로 뒤 데이터'와 동일. im2_font_l: count=29 —
    구버전 고정 스트라이드 해석은 틀린 것으로 판명: 시트가 전부 어긋나게 읽힘)"""
    cnt = struct.unpack_from(">H", nut, 6)[0]
    out = []
    for i in range(cnt):
        off = 16 + i * 80
        total, pal, data, hdr_size = struct.unpack_from(">IIIH", nut, off)
        w = struct.unpack_from(">H", nut, off + 20)[0]
        h = struct.unpack_from(">H", nut, off + 22)[0]
        if nut[off + 48:off + 52] != b"eXt\x00" or nut[off + 64:off + 68] != b"GIDX":
            raise ValueError(f"texture header {i} @0x{off:X}: eXt/GIDX 마커 없음")
        gidx = struct.unpack_from(">I", nut, off + 72)[0]
        if gidx != i:
            raise ValueError(f"texture header {i}: GIDX={gidx} 불일치")
        if w == 0 or h == 0 or data != w * h:
            raise ValueError(f"texture header {i}: w={w} h={h} data={data} 불일치")
        out.append({"header": off, "w": w, "h": h, "raw": data})
    base = 16 + cnt * 80
    for t in out:
        t["raw_off"] = base
        base += t["raw"]
    if base != len(nut):
        raise ValueError(f"NUT 크기 불일치: 계산 {base} != 실제 {len(nut)}")
    return out


def nfh_records(nfh: bytes):
    n = (len(nfh) - NFH_RB) // NFH_RS
    recs = []
    for i in range(n):
        off = NFH_RB + i * NFH_RS
        x, y = struct.unpack_from(">HH", nfh, off)
        wh = struct.unpack_from(">H", nfh, off + 16)[0]
        code = struct.unpack_from(">H", nfh, off + 18)[0]
        gidx = struct.unpack_from(">I", nfh, off + 28)[0]
        recs.append({"idx": i, "off": off, "x": x, "y": y,
                     "w": wh >> 8, "h": wh & 0xFF, "code": code, "gidx": gidx})
    return recs


# ---------------------------------------------------------------- rendering

class GlyphRenderer:
    def __init__(self, font_path, size, cell_w=None, cell_h=None, baseline=None, pad=0):
        import freetype
        self.ft = freetype
        self.face = freetype.Face(font_path)
        self.size = size
        self.cw = cell_w or CELL_W
        self.ch = cell_h or CELL_H
        self.bl = baseline or CELL_BASELINE
        self.pad = pad          # 셀 내부 잉크 금지 테두리(px) — 블리딩 방지
        self.face.set_pixel_sizes(0, size)

    def render(self, ch, size=None):
        if size and size != self.size:
            self.face.set_pixel_sizes(0, size)
        try:
            self.face.load_char(ch, self.ft.FT_LOAD_RENDER)
        finally:
            if size and size != self.size:
                self.face.set_pixel_sizes(0, self.size)
        g = self.face.glyph
        m = g.metrics
        bmp = g.bitmap
        bd = np.array(bmp.buffer, dtype=np.uint8).reshape(bmp.rows, bmp.width) \
            if bmp.rows and bmp.width else np.zeros((0, 0), np.uint8)
        return {
            "bx": m.horiBearingX // 64,
            "by": m.horiBearingY // 64,
            "w": bmp.width, "h": bmp.rows,
            "adv": max(1, m.horiAdvance // 64),
            "bitmap": bd,
        }

    def render_cell(self, ch):
        """cw×ch 셀 비트맵으로 렌더. pad 테두리 안에 안 들어가면 단계적으로 축소."""
        p = self.pad
        for size in range(self.size, 15, -1):
            g = self.render(ch, size)
            x0 = max(p, g["bx"])
            y0 = self.bl - g["by"]
            if (x0 + g["w"] <= self.cw - p) and (p <= y0) and (y0 + g["h"] <= self.ch - p):
                cell = np.zeros((self.ch, self.cw), np.uint8)
                if g["w"] and g["h"]:
                    cell[y0:y0 + g["h"], x0:x0 + g["w"]] = g["bitmap"]
                return cell, ADV_PX, size
            # 세로로 넘치면 셀 안으로 밀어 넣어 재시도 (어센더는 위, 디센더는 아래)
            if g["h"] <= self.ch - 2 * p and x0 + g["w"] <= self.cw - p:
                y0c = min(max(y0, p), self.ch - p - g["h"])
                cell = np.zeros((self.ch, self.cw), np.uint8)
                cell[y0c:y0c + g["h"], x0:x0 + g["w"]] = g["bitmap"]
                return cell, ADV_PX, size
        raise ValueError(f"glyph too large even at size 16: U+{ord(ch):04X} {ch!r}")


# ---------------------------------------------------------------- patch one font

def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def patch_font(name, cfg, mapping, renderer, log):
    CW, CH, BL = renderer.cw, renderer.ch, renderer.bl
    HALO = cfg.get("params", {}).get("halo", True)
    # 샘플 rect를 셀보다 INS px 안쪽으로 줄인다(잉크는 pad로 그 안에 들어 있음).
    # rect 경계의 바이리니어가 항상 자기 셀의 빈 테두리를 읽게 되어, 이웃 rect가
    # 0px 간격으로 붙은 시트(font_l)에서도 번짐이 없다.
    INS = cfg.get("params", {}).get("rect_inset", 0)
    assert md5(cfg["nut"]) == cfg["md5_nut"], f"{name}: 순정 NUT 해시 불일치 — 중단"
    assert md5(cfg["nfh"]) == cfg["md5_nfh"], f"{name}: 순정 NFH 해시 불일치 — 중단"

    nut = bytearray(open(cfg["nut"], "rb").read())
    nfh = bytearray(open(cfg["nfh"], "rb").read())

    texs = nut_textures(bytes(nut))
    recs = nfh_records(bytes(nfh))
    bycode = {r["code"]: r for r in recs}

    sheets = {}
    for gi, t in enumerate(texs):
        raw = bytes(nut[t["raw_off"]: t["raw_off"] + t["raw"]])
        sheets[gi] = {
            "alpha": dxt3_alpha_decode(raw, t["w"], t["h"]),
            "orig_raw": raw,
            "w": t["w"], "h": t["h"], "raw_off": t["raw_off"],
            "occ": np.zeros((t["h"], t["w"]), bool),
        }

    targets = {}
    for hangul, kanji in mapping.items():
        r = bycode.get(ord(kanji))
        if r is None:
            log(f"  [경고] {name}: 한자 {kanji} 레코드 없음 → {hangul} 스킵")
            continue
        targets[r["idx"]] = (hangul, r)

    # 점유 마스크: 비타깃 레코드의 원본 rect 스탬프
    # (protect 마스크는 클리어 시 이웃 글리프 픽셀 보존용 — 순정 font_l은
    #  시트 가장자리에서 rect가 서로 겹치는 레코드가 있어, 타깃 rect를 통째로
    #  지우면 겹친 비타깃 글리프가 손상된다)
    for r in recs:
        if r["idx"] in targets:
            continue
        s = sheets.get(r["gidx"])
        if s is None:
            continue
        s["occ"][r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]] = True
    for s in sheets.values():
        s["protect"] = s["occ"].copy()

    # 1차: 제자리 배치 시도
    placed, pending = [], []
    for idx in sorted(targets):
        hangul, r = targets[idx]
        s = sheets[r["gidx"]]
        x, y = r["x"], r["y"]
        # HALO: 이웃 rect와 최소 1px 간격(바이리니어 번짐 방지). 공간이 빽빽한
        # font_l은 끌 수 있다(종전 로직 — 겹침 없음은 그대로 보장, 간격만 0 허용).
        lo = 1 if HALO else 0
        if (x + CW + lo <= s["w"] and y + CH + lo <= s["h"]
                and not s["occ"][max(0, y - lo):y + CH + lo,
                                 max(0, x - lo):x + CW + lo].any()):
            s["occ"][y:y + CH, x:x + CW] = True
            placed.append((hangul, r, r["gidx"], x, y))
        else:
            pending.append((hangul, r))

    # 2차: 겹치는 슬롯은 빈 영역으로 재배치 (27px 그리드 탐색)
    relocated = []
    for hangul, r in pending:
        spot = None
        order = [r["gidx"]] + [g for g in sheets if g != r["gidx"]]
        for g in order:
            s = sheets[g]
            for y in range(2, s["h"] - CH - 1, 27):
                for x in range(2, s["w"] - CW - 1, 27):
                    if not s["occ"][y - (1 if HALO else 0):y + CH + 1,
                                    x - (1 if HALO else 0):x + CW + 1].any():
                        spot = (g, x, y)
                        break
                if spot:
                    break
            if spot:
                break
        if spot is None:
            log(f"  [경고] {name}: {hangul} 재배치 공간 없음 → 제자리 유지(이웃 겹침 감수)")
            spot = (r["gidx"], r["x"], r["y"])
        g, x, y = spot
        sheets[g]["occ"][y:y + CH, x:x + CW] = True
        placed.append((hangul, r, g, x, y))
        relocated.append((hangul, r["gidx"], r["x"], r["y"], g, x, y))

    # 아틀라스 갱신: 원본 한자 잉크 제거 → 셀 렌더 블릿 → NFH 필드 갱신
    shrunk = []
    for hangul, r, g, x, y in placed:
        # 원본 한자 rect는 타이트 bbox라 경계 밖 1px에 희미한 AA 픽셀이 남는다
        # → 1px 마진 포함해 클리어 (겹쳐 있는 비타깃 rect 픽셀은 보존)
        s_old = sheets[r["gidx"]]
        y0, y1 = max(0, r["y"] - 1), min(s_old["h"], r["y"] + r["h"] + 1)
        x0, x1 = max(0, r["x"] - 1), min(s_old["w"], r["x"] + r["w"] + 1)
        region = s_old["alpha"][y0:y1, x0:x1]
        keep = s_old["protect"][y0:y1, x0:x1]
        region[~keep] = 0
    for hangul, r, g, x, y in placed:
        # 새 셀 영역은 샘플링 대상이므로 무조건 비우고, 둘레 1px 링(바이리니어가
        # 넘겨 보는 구간)의 잔여 픽셀도 지운다 — 링에서는 비타깃 글리프 픽셀만 보존.
        # (2026-10-16: 글자 옆 점선 세로줄 = 링에 남아 있던 잔여 AA 픽셀로 추정)
        s = sheets[g]
        ry0, ry1 = max(0, y - 1), min(s["h"], y + CH + 1)
        rx0, rx1 = max(0, x - 1), min(s["w"], x + CW + 1)
        ring = s["alpha"][ry0:ry1, rx0:rx1]
        ring[~s["protect"][ry0:ry1, rx0:rx1]] = 0
        s["alpha"][y:y + CH, x:x + CW] = 0
    for hangul, r, g, x, y in placed:
        s = sheets[g]
        cell, adv, used_size = renderer.render_cell(hangul)
        if used_size != renderer.size:
            shrunk.append((hangul, used_size))
        region = s["alpha"][y:y + CH, x:x + CW]
        np.maximum(region, cell, out=region)

        off = r["off"]
        rw, rh = CW - 2 * INS, CH - 2 * INS
        struct.pack_into(">HH", nfh, off, x + INS, y + INS)          # rect x, y
        struct.pack_into(">H", nfh, off + 4, 0)                      # bearingX = 0
        struct.pack_into(">H", nfh, off + 6, (BL - INS) * 64)        # bearingY (rect 기준)
        struct.pack_into(">H", nfh, off + 8, adv * 64)               # advance
        struct.pack_into(">h", nfh, off + 10, -((rw + 1) // 2) * 64)
        struct.pack_into(">H", nfh, off + 12, 0)
        struct.pack_into(">H", nfh, off + 16, (rw << 8) | rh)
        struct.pack_into(">I", nfh, off + 28, g)                     # gidx

    # 시트 재인코딩 (컬러 블록은 원본 유지)
    for gi, s in sheets.items():
        enc = dxt3_alpha_encode(s["alpha"], s["orig_raw"])
        assert len(enc) == len(s["orig_raw"]), f"sheet {gi}: encode size mismatch"
        o = s["raw_off"]
        nut[o:o + len(enc)] = enc

    os.makedirs(OUT_DIR, exist_ok=True)
    nut_out = os.path.join(OUT_DIR, f"{name}.nut")
    nfh_out = os.path.join(OUT_DIR, f"{name}.nfh")
    open(nut_out, "wb").write(nut)
    open(nfh_out, "wb").write(nfh)

    log(f"  {name}: 글리프 {len(placed)}자 (재배치 {len(relocated)}, 축소 {len(shrunk)})")
    for hangul, g0, x0, y0, g1, x1, y1 in relocated:
        log(f"    재배치 {hangul}: sheet{g0}({x0},{y0}) → sheet{g1}({x1},{y1})")
    for hangul, sz in shrunk:
        log(f"    축소 {hangul}: size {sz}")
    return nut_out, nfh_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=FONT_PATH)
    ap.add_argument("--mapping", default=MAPPING_PATH)
    args = ap.parse_args()

    log = print
    mapping = json.load(open(args.mapping, encoding="utf-8"))
    log(f"기존 매핑 {len(mapping)}자 로드")
    for h, k in NEW_CHARS.items():
        if h not in mapping:
            mapping[h] = k
    log(f"신규 6자 추가 → 총 {len(mapping)}자")

    # 렌더 대상 = 매핑(한글→한자 슬롯) + 문장부호(자기 슬롯에 Noto 재렌더).
    # 문장부호는 font_mapping_v2.json에는 넣지 않는다 (SCB 치환 대상이 아님).
    render_map = dict(mapping)
    for p in PUNCT_RERENDER:
        render_map[p] = p
    log(f"문장부호 재렌더 {len(PUNCT_RERENDER)}자 포함 → 렌더 대상 {len(render_map)}자")

    for name, cfg in PRISTINE.items():
        pr = cfg["params"]
        renderer = GlyphRenderer(args.font, pr["size"], pr["cell"][0], pr["cell"][1],
                                 pr["baseline"], pr.get("pad", 0))
        log(f"▶ {name} (size {pr['size']}, cell {pr['cell'][0]}x{pr['cell'][1]}, "
            f"baseline {pr['baseline']}, pad {pr.get('pad', 0)})")
        patch_font(name, cfg, render_map, renderer, log)

    os.makedirs(OUT_DIR, exist_ok=True)
    map_out = os.path.join(OUT_DIR, "font_mapping_v2.json")
    with open(map_out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    log(f"매핑 저장: {map_out} ({len(mapping)}자)")
    log("완료. 검증/배포는 qa_render.py / deploy_fonts.py 사용.")


if __name__ == "__main__":
    main()
