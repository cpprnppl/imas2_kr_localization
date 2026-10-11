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
    },
    "im2_font_l": {
        "nut": os.path.join(USR, r"_backup\im2_font_l_20260223_022937.nut"),
        "nfh": os.path.join(USR, r"_backup\im2_font_l_20260223_022937.nfh"),
        "md5_nut": "e94c9af9db807530e69101542f7139a2",
        "md5_nfh": "d772158afc8fe74a7aa7e12e071fada5",
    },
}

FONT_SIZE = 26
CELL_W, CELL_H = 25, 25
CELL_BASELINE = 22          # 셀 상단에서 베이스라인까지 (원본 한자 bearingY와 동일 레벨)
ADV_FALLBACK = 26

# 매핑에 없어 인게임 공백이던 한글 6자 → 추가 희생 슬롯 (희생 풀에서 기존 2353 바로 앞 6개)
NEW_CHARS = {"큿": "睆", "큥": "睇", "햣": "睚", "쌰": "睛", "겍": "睜", "츗": "睟"}

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
    def __init__(self, font_path, size):
        import freetype
        self.ft = freetype
        self.face = freetype.Face(font_path)
        self.size = size
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
        """CELL_W×CELL_H 셀 비트맵으로 렌더. 셀에 안 들어가면 단계적으로 축소."""
        for size in range(self.size, 15, -1):
            g = self.render(ch, size)
            x0 = g["bx"]
            y0 = CELL_BASELINE - g["by"]
            if x0 < 0:
                x0 = 0
            if (x0 + g["w"] <= CELL_W) and (0 <= y0) and (y0 + g["h"] <= CELL_H):
                cell = np.zeros((CELL_H, CELL_W), np.uint8)
                if g["w"] and g["h"]:
                    cell[y0:y0 + g["h"], x0:x0 + g["w"]] = g["bitmap"]
                return cell, g["adv"] if size == self.size else ADV_FALLBACK, size
            # 세로로 넘치면 베이스라인을 살짝 내려 재시도 (어센더 초과분)
            if y0 < 0 and g["h"] <= CELL_H and x0 + g["w"] <= CELL_W:
                cell = np.zeros((CELL_H, CELL_W), np.uint8)
                cell[0:g["h"], x0:x0 + g["w"]] = g["bitmap"]
                return cell, g["adv"] if size == self.size else ADV_FALLBACK, size
        raise ValueError(f"glyph too large even at size 16: {ch!r}")


# ---------------------------------------------------------------- patch one font

def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def patch_font(name, cfg, mapping, renderer, log):
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
        if (x + CELL_W <= s["w"] and y + CELL_H <= s["h"]
                and not s["occ"][y:y + CELL_H, x:x + CELL_W].any()):
            s["occ"][y:y + CELL_H, x:x + CELL_W] = True
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
            for y in range(2, s["h"] - CELL_H - 1, 27):
                for x in range(2, s["w"] - CELL_W - 1, 27):
                    if not s["occ"][y:y + CELL_H + 1, x:x + CELL_W + 1].any():
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
        sheets[g]["occ"][y:y + CELL_H, x:x + CELL_W] = True
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
        # 새 셀 영역은 샘플링 대상이므로 무조건 비운다 (비타깃 rect와는 이미 비겹침,
        # 이웃의 rect 밖 AA 잔픽셀만 제거됨)
        sheets[g]["alpha"][y:y + CELL_H, x:x + CELL_W] = 0
    for hangul, r, g, x, y in placed:
        s = sheets[g]
        cell, adv, used_size = renderer.render_cell(hangul)
        if used_size != renderer.size:
            shrunk.append((hangul, used_size))
        region = s["alpha"][y:y + CELL_H, x:x + CELL_W]
        np.maximum(region, cell, out=region)

        off = r["off"]
        struct.pack_into(">HH", nfh, off, x, y)                      # x, y
        struct.pack_into(">H", nfh, off + 4, 0)                      # bearingX = 0
        struct.pack_into(">H", nfh, off + 6, CELL_BASELINE * 64)     # bearingY = 22
        struct.pack_into(">H", nfh, off + 8, adv * 64)               # advance
        struct.pack_into(">h", nfh, off + 10, -((CELL_W + 1) // 2) * 64)
        struct.pack_into(">H", nfh, off + 12, 0)
        struct.pack_into(">H", nfh, off + 16, (CELL_W << 8) | CELL_H)
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

    renderer = GlyphRenderer(args.font, FONT_SIZE)

    for name, cfg in PRISTINE.items():
        log(f"▶ {name}")
        patch_font(name, cfg, mapping, renderer, log)

    os.makedirs(OUT_DIR, exist_ok=True)
    map_out = os.path.join(OUT_DIR, "font_mapping_v2.json")
    with open(map_out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    log(f"매핑 저장: {map_out} ({len(mapping)}자)")
    log("완료. 검증/배포는 qa_render.py / deploy_fonts.py 사용.")


if __name__ == "__main__":
    main()
