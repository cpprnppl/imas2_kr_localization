#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IM2 Font Auto Patcher (Replace-only, 2350 base charset)
- Drag & Drop .nut files -> auto find matching .nfh in same folder
- Backup originals to _backup (timestamped)
- Patch in-place (write temp then replace)
- Replace-only: sacrifice kanji -> draw Hangul glyphs into same slots
- Charset:
    base = korean_2350.txt (same folder as this script)
    + user extra characters field
- Defaults tuned for NotoSansKR Medium:
    font_size=26, baseline=20, x_offset=0, row_h=29
- Persist settings & last used files to config json (same folder as script)
- Mapping JSON auto-saved to: <font folder>/font_mapping.json
- "Viewer-friendly" header fix for fixed-slot NUT:
    keep stride/file size, but normalize per-slot header fields so common viewers show sane sizes.
"""

import os
import sys
import io
import json
import time
import shutil
import threading
import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import numpy as np

try:
    import freetype
except ImportError:
    freetype = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False


# =============================================================================
# Paths / Config
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "font_patcher_config.json")
BASESET_PATH = os.path.join(SCRIPT_DIR, "korean_2350.txt")

DEFAULTS = {
    "font_size": 26,
    "baseline": 20,
    "x_offset": 0,
    "row_h": 29,
}

# =============================================================================
# UI Colors
# =============================================================================

DARK  = '#12121f'
PANEL = '#1a1a2e'
CARD  = '#16213e'
DEEP  = '#0f3460'
ACC   = '#00d4aa'
FG    = '#dde1e7'
FGDIM = '#7a8090'


# =============================================================================
# Protect kanji (JIS Level1)
# =============================================================================

def get_jis_level1():
    s = set()
    for row in range(16, 48):
        for col in range(1, 95):
            try:
                ch = bytes([row+0xA0, col+0xA0]).decode('euc-jp')
                if '\u4E00' <= ch <= '\u9FFF':
                    s.add(ch)
            except Exception:
                pass
    return s


# =============================================================================
# Charset loading
# =============================================================================

def load_korean_2350(path: str) -> list[str]:
    """
    Loads base charset from korean_2350.txt
    Accepts any whitespace-separated stream, de-dupes while keeping order.
    """
    if not os.path.exists(path):
        return []
    raw = open(path, "r", encoding="utf-8", errors="ignore").read()
    out = []
    seen = set()
    for ch in raw:
        if ch.isspace():
            continue
        # allow Hangul syllables + common punctuation if user includes them
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out

def build_charset(base_chars: list[str], extra_text: str) -> list[str]:
    """
    base + extra (dedupe, keep order)
    extra_text: any characters; whitespace ignored.
    """
    out = []
    seen = set()
    for ch in base_chars:
        if ch.isspace():
            continue
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    for ch in extra_text:
        if ch.isspace():
            continue
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


# =============================================================================
# DXT3 (BC2) alpha decode/encode (direct, stable)
# =============================================================================

def decode_dxt3_alpha(raw: bytes, w: int, h: int) -> np.ndarray:
    alpha = np.zeros((h, w), dtype=np.uint8)
    bi = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            base = bi * 16
            ab = raw[base:base+8]
            for row in range(4):
                v = ab[row*2] | (ab[row*2+1] << 8)  # little-endian
                n0 = (v >> 0) & 0xF
                n1 = (v >> 4) & 0xF
                n2 = (v >> 8) & 0xF
                n3 = (v >> 12) & 0xF
                for col, n in enumerate((n0, n1, n2, n3)):
                    x = bx + col
                    y = by + row
                    if x < w and y < h:
                        alpha[y, x] = n * 17
            bi += 1
    return alpha

def encode_dxt3_alpha_direct(alpha: np.ndarray, w: int, h: int) -> bytes:
    # pad to multiples of 4
    pw = ((w + 3) // 4) * 4
    ph = ((h + 3) // 4) * 4
    if pw != w or ph != h:
        padded = np.zeros((ph, pw), dtype=np.uint8)
        padded[:h, :w] = alpha
        alpha = padded
        w, h = pw, ph

    a4 = (alpha.astype(np.uint16) + 8) // 17  # 0..15
    out = bytearray()

    # DXT1 color block fixed to white (valid BC2)
    color_block = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0])

    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            ab = bytearray(8)
            for row in range(4):
                n0 = int(a4[by+row, bx+0]) & 0xF
                n1 = int(a4[by+row, bx+1]) & 0xF
                n2 = int(a4[by+row, bx+2]) & 0xF
                n3 = int(a4[by+row, bx+3]) & 0xF
                v = (n0) | (n1 << 4) | (n2 << 8) | (n3 << 12)
                ab[row*2 + 0] = v & 0xFF
                ab[row*2 + 1] = (v >> 8) & 0xFF
            out += bytes(ab) + color_block

    return bytes(out)


# =============================================================================
# NUT parsing (standard + fixed-slot)
# =============================================================================

def nut_count(nut: bytes) -> int:
    if len(nut) < 8:
        return 0
    return struct.unpack_from('>H', nut, 6)[0]

def nut_slot0_tsize(nut: bytes) -> int:
    if len(nut) < 20:
        return 0
    return struct.unpack_from('>i', nut, 16)[0]

def nut_is_fixed(nut: bytes) -> bool:
    # im2_font_l style: slot0 tsize <= 0, or subsequent slots have 0
    return nut_slot0_tsize(nut) <= 0

def _plausible_wh(v: int) -> bool:
    return v in (32, 64, 128, 256, 512, 1024, 2048, 4096)

def _read_wh_candidates(nut: bytes, off: int):
    cands = []
    for woff, hoff in ((20, 22), (32, 34), (24, 26)):
        if off + hoff + 2 <= len(nut):
            w = struct.unpack_from('>H', nut, off + woff)[0]
            h = struct.unpack_from('>H', nut, off + hoff)[0]
            cands.append((w, h, woff, hoff))
    return cands

def _choose_wh(nut: bytes, off: int, rawlen_hint: int | None = None):
    cands = _read_wh_candidates(nut, off)
    if rawlen_hint and rawlen_hint > 0:
        for w, h, woff, hoff in cands:
            if w > 0 and h > 0 and (w * h) == rawlen_hint:
                return w, h, (woff, hoff), cands
    for w, h, woff, hoff in cands:
        if _plausible_wh(w) and _plausible_wh(h):
            return w, h, (woff, hoff), cands
    for w, h, woff, hoff in cands:
        if 1 <= w <= 8192 and 1 <= h <= 8192:
            return w, h, (woff, hoff), cands
    return 0, 0, (None, None), cands

def nut_list_fixed(nut: bytes):
    c = nut_count(nut)
    if c <= 0:
        return []

    stride = (len(nut) - 16) // c
    if stride <= 0:
        return []

    off0 = 16
    rawlen_hint = max(0, stride - 80)
    w, h, wh_offs, cands = _choose_wh(nut, off0, rawlen_hint=rawlen_hint)
    if w == 0 or h == 0:
        side = int(max(0, rawlen_hint) ** 0.5)
        for p in (32, 64, 128, 256, 512, 1024, 2048, 4096):
            if abs(side - p) <= 8:
                side = p
                break
        w = h = side

    out = []
    for i in range(c):
        off = 16 + i * stride
        if off + 80 > len(nut):
            break
        gidx = struct.unpack_from('>i', nut, off+72)[0] if off+76 <= len(nut) else i
        out.append({
            "offset": off,
            "gidx": gidx,
            "w": w, "h": h,
            "raw_len": w*h,
            "stride": stride,
            "fixed": True,
            "wh_candidates": cands,
        })
    return out

def nut_list_standard(nut: bytes):
    c = nut_count(nut)
    if c <= 0:
        return []
    off = 16
    out = []
    for i in range(c):
        if off + 80 > len(nut):
            return []
        tsize = struct.unpack_from('>i', nut, off)[0]
        if tsize <= 80 or tsize > (len(nut) - off):
            return []
        rawlen_hint = tsize - 80
        w, h, wh_offs, cands = _choose_wh(nut, off, rawlen_hint=rawlen_hint)
        if (w == 0 or h == 0) and rawlen_hint > 0:
            side = int(rawlen_hint ** 0.5)
            for p in (32, 64, 128, 256, 512, 1024, 2048, 4096):
                if abs(side - p) <= 8:
                    side = p
                    break
            w = h = side
        raw_len = w*h if (w > 0 and h > 0) else rawlen_hint
        gidx = struct.unpack_from('>i', nut, off+72)[0] if off+76 <= len(nut) else i

        out.append({
            "offset": off,
            "gidx": gidx,
            "w": w, "h": h,
            "raw_len": raw_len,
            "tsize": tsize,
            "fixed": False,
            "wh_candidates": cands,
        })

        pad = (off + tsize) % 16
        off += tsize + (16 - pad if pad else 0)

    return out

def nut_list_textures(nut: bytes, force_fixed: bool):
    if force_fixed:
        return nut_list_fixed(nut)
    tex = nut_list_standard(nut)
    if tex:
        return tex
    return nut_list_fixed(nut)


# =============================================================================
# NFH parsing
# =============================================================================

NFH_RB = 0x474
NFH_RS = 32

def nfh_total(nfh: bytes) -> int:
    if len(nfh) < NFH_RB:
        return 0
    return (len(nfh) - NFH_RB) // NFH_RS

def nfh_rec(nfh: bytes, i: int):
    off = NFH_RB + i * NFH_RS
    return {
        "idx": i,
        "off": off,
        "x": struct.unpack_from(">H", nfh, off+0)[0],
        "y": struct.unpack_from(">H", nfh, off+2)[0],
        "adv": struct.unpack_from(">H", nfh, off+6)[0],
        "code": struct.unpack_from(">H", nfh, off+18)[0],
        "gidx": struct.unpack_from(">I", nfh, off+28)[0],
    }


# =============================================================================
# Patch Engine (replace only) with stable mapping across multiple files
# =============================================================================

class PatchEngine:
    def __init__(self, cfg, log):
        self.c = cfg
        self.log = log
        self.mapping = {}  # hangul -> sacrificed kanji char

    def run(self) -> bool:
        c = self.c
        try:
            nfh = bytearray(open(c["nfh_path"], "rb").read())
            nut = bytearray(open(c["nut_path"], "rb").read())
        except Exception as e:
            self.log(f"[오류] 파일 읽기 실패: {e!r}")
            return False

        if freetype is None:
            self.log("[오류] freetype-py 필요: pip install freetype-py")
            return False

        face = freetype.Face(c["font_path"])
        face.set_pixel_sizes(0, c["font_size"])

        charset = c["charset"]
        protect = c["protect"]
        row_h = c["row_h"]
        boff = c["baseline_offset"]
        xoff = c["x_offset"]

        base_name = os.path.basename(c["nut_path"]).lower()
        force_fixed = ("_l" in base_name) or nut_is_fixed(nut)

        tex = nut_list_textures(nut, force_fixed=force_fixed)
        if not tex:
            self.log("[오류] NUT 텍스처 파싱 실패")
            return False

        # load sheets
        sheets = {}
        for t in tex:
            off = t["offset"]
            w, h = t["w"], t["h"]
            raw_len = t["raw_len"]
            raw_off = off + 80

            if w <= 0 or h <= 0 or raw_len <= 0:
                self.log(f"[오류] W/H 감지 실패 @0x{off:X} candidates={t.get('wh_candidates')}")
                return False

            if not t["fixed"]:
                # clamp by tsize-80
                max_raw = max(0, t["tsize"] - 80)
                if max_raw and raw_len > max_raw:
                    raw_len = max_raw
                    side = int(raw_len ** 0.5)
                    for p in (32, 64, 128, 256, 512, 1024, 2048, 4096):
                        if abs(side - p) <= 8:
                            side = p
                            break
                    w = h = side

            if raw_off + raw_len > len(nut):
                self.log(f"[오류] raw 범위 초과: gidx={t['gidx']} need={raw_len} file={len(nut)}")
                return False

            alpha = decode_dxt3_alpha(nut[raw_off:raw_off+raw_len], w, h)
            sheets[t["gidx"]] = {
                "alpha": alpha, "w": w, "h": h,
                "offset": off, "raw_len": raw_len, "fixed": t["fixed"],
                "stride": t.get("stride"),  # for fixed
            }

        # Collect sacrifice records (kanji not protected)
        total = nfh_total(nfh)
        all_kanji = []
        for i in range(total):
            r = nfh_rec(nfh, i)
            code = r["code"]
            if 0x4E00 <= code <= 0x9FFF and chr(code) not in protect:
                all_kanji.append(r)
        all_kanji.sort(key=lambda r: r["idx"])

        if not all_kanji:
            self.log("[오류] 희생 가능한 한자가 없음(보호 설정이 너무 강함?)")
            return False

        # Stable mapping across multiple files:
        # - if cfg provides chosen_codes, use those codes as target slots
        # - else pick from THIS file and store to cfg for subsequent files
        chosen_codes = c.get("chosen_codes")
        if not chosen_codes:
            targets = all_kanji[-len(charset):]
            chosen_codes = [r["code"] for r in targets]
            c["chosen_codes"] = chosen_codes
        else:
            code_to_rec = {r["code"]: r for r in all_kanji}
            targets = []
            missing = 0
            for code in chosen_codes:
                rr = code_to_rec.get(code)
                if rr is None:
                    missing += 1
                else:
                    targets.append(rr)
            if missing:
                self.log(f"[경고] 이 NFH에 없는 희생 한자 code가 {missing}개 있음 → 해당 글자는 스킵될 수 있음")

        self.log(f"  NUT 모드: {'FIXED' if force_fixed else 'STANDARD'} | 텍스처 {len(tex)}개 | 희생슬롯 {len(targets)}/{len(charset)}")

        # Render glyphs
        wrote = 0
        for i, rec in enumerate(targets):
            if i >= len(charset):
                break
            ch = charset[i]
            ox, oy, gidx = rec["x"], rec["y"], rec["gidx"]

            if gidx not in sheets:
                continue
            s = sheets[gidx]
            alpha, w, h = s["alpha"], s["w"], s["h"]

            # clear region
            orig_adv = max(1, rec["adv"] // 64)
            clear_w = min(w - ox, max(orig_adv + 4, 28))
            clear_h = min(h - oy, row_h)
            if clear_w > 0 and clear_h > 0:
                alpha[oy:oy+clear_h, ox:ox+clear_w] = 0

            face.load_char(ch, freetype.FT_LOAD_RENDER)
            m = face.glyph.metrics
            bm = face.glyph.bitmap

            gw, gh = bm.width, bm.rows
            bx = (m.horiBearingX // 64) + xoff
            by = (m.horiBearingY // 64)
            adv = max(1, m.horiAdvance // 64)
            baseline = oy + boff

            if gw > 0 and gh > 0:
                # Python 3.14 + freetype: buffer may be list -> use np.array
                bd = np.array(bm.buffer, dtype=np.uint8).reshape(gh, gw)
                for dy in range(gh):
                    py = baseline - by + dy
                    if not (0 <= py < h):
                        continue
                    row = bd[dy]
                    for dx in range(gw):
                        px = ox + bx + dx
                        if 0 <= px < w:
                            v = int(row[dx])
                            if v and v > alpha[py, px]:
                                alpha[py, px] = v

            # update advance
            struct.pack_into(">H", nfh, rec["off"] + 6, adv * 64)

            # mapping: hangul -> sacrificed kanji
            self.mapping[ch] = chr(rec["code"])
            wrote += 1

        self.log(f"  렌더 완료: {wrote}자 → DXT3 인코딩/저장")

        # Flush sheets back
        for gidx, s in sheets.items():
            raw = encode_dxt3_alpha_direct(s["alpha"], s["w"], s["h"])
            expect = s["w"] * s["h"]
            if len(raw) != expect:
                self.log(f"[오류] 인코딩 크기 불일치 gidx={gidx}: got={len(raw)} expect={expect}")
                return False

            n = min(expect, s["raw_len"])
            off = s["offset"] + 80
            nut[off:off+n] = raw[:n]

        # Viewer-friendly header fix for FIXED NUT:
        # Keep stride and size, but normalize per-slot header fields:
        # - set tsize = 80 + w*h (positive)
        # - set w/h in both (20/22) and (32/34)
        if force_fixed and c.get("viewer_fix", True):
            self._apply_viewer_friendly_headers(nut, tex)

        # Write temp then replace
        try:
            nfh_tmp = c["nfh_path"] + ".tmp"
            nut_tmp = c["nut_path"] + ".tmp"
            with open(nfh_tmp, "wb") as f:
                f.write(nfh)
            with open(nut_tmp, "wb") as f:
                f.write(nut)
            os.replace(nfh_tmp, c["nfh_path"])
            os.replace(nut_tmp, c["nut_path"])
        except Exception as e:
            self.log(f"[오류] 저장 실패: {e!r}")
            return False

        # Save mapping JSON to <font folder>/font_mapping.json
        try:
            font_dir = os.path.dirname(os.path.abspath(c["font_path"]))
            outp = os.path.join(font_dir, "font_mapping.json")
            with open(outp, "w", encoding="utf-8") as f:
                json.dump(self.mapping, f, ensure_ascii=False, indent=2)
            self.log(f"  ✓ 매핑 저장: {outp}")
        except Exception as e:
            self.log(f"[경고] 매핑 저장 실패: {e!r}")

        self.log("  ✓ 완료")
        return True

    def _apply_viewer_friendly_headers(self, nut: bytearray, tex_list: list[dict]):
        # tex_list contains offsets and w/h
        for t in tex_list:
            off = t["offset"]
            w, h = t["w"], t["h"]
            if off + 80 > len(nut):
                continue
            tsize = 80 + (w * h)
            # tsize (int32)
            struct.pack_into(">i", nut, off + 0, tsize)
            # write W/H at both common offsets
            struct.pack_into(">H", nut, off + 20, w)
            struct.pack_into(">H", nut, off + 22, h)
            struct.pack_into(">H", nut, off + 32, w)
            struct.pack_into(">H", nut, off + 34, h)
            # leave gidx at +72 as-is
            # Also set "format flag" at +18 to 1 (seen in some NUTs)
            if off + 20 <= len(nut):
                struct.pack_into(">h", nut, off + 18, 1)


# =============================================================================
# App / GUI
# =============================================================================

class AppUI:
    def __init__(self, root):
        self.root = root
        self.root.title("IM@S2 Font Auto Patcher - TEAM W@LDO")
        self.root.configure(bg=DARK)
        self.root.minsize(920, 700)

        self._jis = get_jis_level1()

        self.font_path = tk.StringVar()
        self.font_size = tk.IntVar(value=DEFAULTS["font_size"])
        self.baseline  = tk.IntVar(value=DEFAULTS["baseline"])
        self.x_offset  = tk.IntVar(value=DEFAULTS["x_offset"])
        self.row_h     = tk.IntVar(value=DEFAULTS["row_h"])

        self.extra_chars = tk.StringVar()

        # last used
        self.last_nut_paths: list[str] = []
        self.last_font_path: str | None = None

        self._style()
        self._ui()

        # load config + baseset
        self.base_chars = load_korean_2350(BASESET_PATH)
        self._load_config()
        self._refresh_charset_count()

        if not self.base_chars:
            self._log(f"⚠ korean_2350.txt를 찾지 못했음: {BASESET_PATH}")
        else:
            self._log(f"기본 문자셋 로드: {len(self.base_chars)}자 (korean_2350.txt)")

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, font=("Consolas", 9), borderwidth=0)
        s.configure("TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("TLabelframe", background=PANEL)
        s.configure("TLabelframe.Label", background=PANEL, foreground=ACC, font=("Consolas", 9, "bold"))
        s.configure("TButton", background=CARD, foreground=ACC, relief="flat", padding=4)
        s.map("TButton", background=[("active", DEEP)])
        s.configure("Run.TButton", background=ACC, foreground=DARK, font=("Consolas", 10, "bold"), padding=6)
        s.map("Run.TButton", background=[("active", "#00b894")])
        s.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=ACC)
        s.configure("TScale", background=PANEL, troughcolor=CARD, sliderrelief="flat", sliderlength=14)

    def _ui(self):
        top = tk.Frame(self.root, bg=DEEP, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="IM@S2 Font Auto Patcher",
                 bg=DEEP, fg=ACC, font=("Consolas", 14, "bold")).pack()
        tk.Label(top, text="Drop .nut files → auto find .nfh → backup → overwrite originals & save char mapping json",
                 bg=DEEP, fg=FGDIM, font=("Consolas", 9)).pack()

        main = tk.Frame(self.root, bg=DARK)
        main.pack(fill="both", expand=True, padx=10, pady=4)

        left = tk.Frame(main, bg=PANEL)
        left.pack(side="left", fill="both", expand=True, padx=(0, 3))

        right = tk.Frame(main, bg=PANEL)
        right.pack(side="right", fill="both", expand=False)

        # Drop zone
        dz = ttk.LabelFrame(left, text="드래그 & 드롭")
        dz.pack(fill="x", padx=10, pady=5)

        self.drop_label = tk.Label(
            dz,
            text="여기에 .nut 파일을 드래그\n\n(같은 폴더의 동일 이름 .nfh 자동 매칭)",
            bg=CARD, fg=ACC, font=("Consolas", 11, "bold"),
            height=5, relief="flat"
        )
        self.drop_label.pack(fill="x", padx=10, pady=5)

        if HAS_DND:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
        else:
            tk.Label(dz, text="(DnD 미지원: pip install tkinterdnd2) → 아래 버튼으로 선택",
                     bg=PANEL, fg=FGDIM).pack(anchor="w", padx=5)
            ttk.Button(dz, text="NUT 파일 선택…", command=self._pick_files).pack(anchor="w", padx=10, pady=(0,10))

        # Last used list
        lf = ttk.LabelFrame(left, text="이전 사용 파일")
        lf.pack(fill="x", padx=10, pady=(0,5))
        self.last_files_var = tk.StringVar(value="(없음)")
        tk.Label(lf, textvariable=self.last_files_var, bg=PANEL, fg=FGDIM, justify="left").pack(anchor="w", padx=10, pady=6)
        ttk.Button(lf, text="이전 파일로 다시 패치", command=self._patch_last_used).pack(anchor="w", padx=10, pady=(0,5))

        # Options
        opt = ttk.LabelFrame(left, text="설정")
        opt.pack(fill="both", expand=True, padx=10, pady=(0,5))

        # Font path
        row = tk.Frame(opt, bg=PANEL)
        row.pack(fill="x", padx=10, pady=6)
        tk.Label(row, text="폰트(.ttf/.otf):", bg=PANEL, fg=FGDIM, width=16, anchor="e").pack(side="left")
        ttk.Entry(row, textvariable=self.font_path, width=54).pack(side="left", padx=6)
        ttk.Button(row, text="…", command=self._browse_font).pack(side="left")

        # reset button
        btnrow = tk.Frame(opt, bg=PANEL)
        btnrow.pack(fill="x", padx=10, pady=(0,6))
        ttk.Button(btnrow, text="기본값으로 리셋", command=self._reset_defaults).pack(side="left", padx=4)

        # sliders
        self._slider(opt, "fontsize(px)", self.font_size, 8, 48)
        self._slider(opt, "baseline(px)", self.baseline, 0, 40)
        self._slider(opt, "x offset(px)", self.x_offset, -8, 8)
        self._slider(opt, "row_h(px)", self.row_h, 18, 60)

        # Charset
        cf = ttk.LabelFrame(opt, text="문자셋 (korean_2350.txt + 추가)")
        cf.pack(fill="x", padx=10, pady=10)

        self.charset_count_var = tk.StringVar(value="")
        tk.Label(cf, textvariable=self.charset_count_var, bg=PANEL, fg=ACC, font=("Consolas", 10, "bold")).pack(anchor="w", padx=8, pady=(6,2))

        tk.Label(cf, text="추가할 글자(공백/개행 무시):", bg=PANEL, fg=FGDIM).pack(anchor="w", padx=8)
        self.extra_box = scrolledtext.ScrolledText(cf, height=3, bg=CARD, fg=FG,
                                                   font=("Malgun Gothic", 10), relief="flat",
                                                   insertbackground=ACC, wrap="char")
        self.extra_box.pack(fill="x", padx=8, pady=(0,8))
        self.extra_box.bind("<<Modified>>", self._on_extra_changed)

        # Protect
        pf = ttk.LabelFrame(left, text="보호 한자(사용할 한자) - 기본 JIS 레벨1")
        pf.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.protect_text = scrolledtext.ScrolledText(pf, height=8, bg=CARD, fg=FG,
                                                      font=("Malgun Gothic", 10), relief="flat",
                                                      insertbackground=ACC, wrap="char")
        self.protect_text.pack(fill="both", expand=True, padx=8, pady=(8,8))
        self.protect_text.insert("1.0", "".join(sorted(self._jis)))

        # Right: log
        logf = ttk.LabelFrame(right, text="로그")
        logf.pack(fill="both", expand=True, padx=10, pady=10)
        self.logbox = scrolledtext.ScrolledText(logf, height=34, bg="#08080f", fg=ACC,
                                                font=("Consolas", 8), state="disabled",
                                                insertbackground=ACC, relief="flat")
        self.logbox.pack(fill="both", expand=True, padx=6, pady=6)

        self._log("준비됨. .nut 파일을 드래그하세요.")

    def _slider(self, parent, label, var, lo, hi):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text=label, bg=PANEL, fg=FGDIM, width=16, anchor="e").pack(side="left")
        scale = ttk.Scale(row, from_=lo, to=hi, variable=var, orient="horizontal",
                          length=300, command=lambda v, vr=var: self._on_slider(vr, v))
        scale.pack(side="left", padx=6)
        tk.Label(row, textvariable=var, bg=PANEL, fg=ACC, width=5, font=("Consolas", 9, "bold")).pack(side="left")

    def _on_slider(self, var, v):
        # snap int + save config
        try:
            var.set(int(float(v)))
        except Exception:
            pass
        self._save_config()

    def _on_extra_changed(self, event=None):
        # Tk sets modified flag; we must reset it
        try:
            self.extra_box.edit_modified(False)
        except Exception:
            pass
        self._refresh_charset_count()
        self._save_config()

    def _log(self, msg: str):
        def _f():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", msg + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.root.after(0, _f)

    def _browse_font(self):
        p = filedialog.askopenfilename(filetypes=[("Font", "*.ttf *.otf"), ("All", "*")])
        if p:
            self.font_path.set(p)
            self._save_config()
            self._log(f"폰트 선택: {p}")

    def _reset_defaults(self):
        self.font_size.set(DEFAULTS["font_size"])
        self.baseline.set(DEFAULTS["baseline"])
        self.x_offset.set(DEFAULTS["x_offset"])
        self.row_h.set(DEFAULTS["row_h"])
        self._save_config()
        self._log("기본값으로 리셋됨.")

    def _refresh_charset_count(self):
        extra = self.extra_box.get("1.0", "end")
        charset = build_charset(self.base_chars, extra)
        self.charset_count_var.set(f"총 문자 수: {len(charset)} (기본 {len(self.base_chars)} + 추가 {len(set(ch for ch in extra if not ch.isspace()))})")
        return charset

    def _get_charset(self):
        return build_charset(self.base_chars, self.extra_box.get("1.0", "end"))

    def _get_protect(self):
        txt = self.protect_text.get("1.0", "end")
        return set(ch for ch in txt if "\u4E00" <= ch <= "\u9FFF")

    def _pick_files(self):
        files = filedialog.askopenfilenames(filetypes=[("NUT", "*.nut"), ("All", "*")])
        if files:
            self._process_files(list(files))

    def _on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        files = [f.strip("{}") for f in files]
        self._process_files(files)

    def _process_files(self, files):
        if freetype is None:
            messagebox.showerror("오류", "freetype-py 필요:\n\npip install freetype-py")
            return
        if not self.font_path.get() or not os.path.exists(self.font_path.get()):
            messagebox.showerror("오류", "폰트(.ttf/.otf)를 먼저 선택하세요.")
            return

        nut_files = [os.path.abspath(f) for f in files if f.lower().endswith(".nut") and os.path.exists(f)]
        if not nut_files:
            self._log("[무시] .nut 파일을 찾지 못했습니다.")
            return

        charset = self._get_charset()
        if not charset:
            messagebox.showerror("오류", "문자셋이 비어있습니다. korean_2350.txt 또는 추가 글자를 확인하세요.")
            return

        protect = self._get_protect()

        # store last used for next launch
        self.last_nut_paths = nut_files
        self.last_files_var.set("\n".join(nut_files))
        self._save_config()

        threading.Thread(target=lambda: self._patch_many(nut_files, charset, protect), daemon=True).start()

    def _patch_last_used(self):
        if not self.last_nut_paths:
            messagebox.showinfo("정보", "이전 사용 파일이 없습니다.")
            return
        self._process_files(self.last_nut_paths)

    def _patch_many(self, nut_files, charset, protect):
        try:
            self._log("─" * 76)
            self._log(f"패치 시작: {len(nut_files)}개 NUT | 문자 {len(charset)} | 보호한자 {len(protect)}")
            self._log(f"기본값: size={self.font_size.get()} baseline={self.baseline.get()} x={self.x_offset.get()} row_h={self.row_h.get()}")
            chosen_codes = None  # ensure identical mapping across all fonts patched in this run

            for nut_path in nut_files:
                base = os.path.splitext(nut_path)[0]
                nfh_path = base + ".nfh"
                if not os.path.exists(nfh_path):
                    self._log(f"[스킵] NFH 없음: {os.path.basename(nfh_path)}")
                    continue

                folder = os.path.dirname(nut_path)
                backup_dir = os.path.join(folder, "_backup")
                os.makedirs(backup_dir, exist_ok=True)

                ts = time.strftime("%Y%m%d_%H%M%S")
                b_nut = os.path.join(backup_dir, os.path.basename(base) + f"_{ts}.nut")
                b_nfh = os.path.join(backup_dir, os.path.basename(base) + f"_{ts}.nfh")

                try:
                    shutil.copy2(nut_path, b_nut)
                    shutil.copy2(nfh_path, b_nfh)
                except Exception as e:
                    self._log(f"[오류] 백업 실패: {e!r}")
                    continue

                self._log(f"▶ {os.path.basename(nut_path)}")
                self._log(f"  백업: {os.path.basename(b_nut)} / {os.path.basename(b_nfh)}")

                cfg = {
                    "nut_path": nut_path,
                    "nfh_path": nfh_path,
                    "font_path": self.font_path.get(),
                    "font_size": int(self.font_size.get()),
                    "baseline_offset": int(self.baseline.get()),
                    "x_offset": int(self.x_offset.get()),
                    "row_h": int(self.row_h.get()),
                    "charset": charset,
                    "protect": protect,
                    "chosen_codes": chosen_codes,   # stable mapping
                    "viewer_fix": True,             # improve viewer sizes for fixed NUT
                }

                ok = PatchEngine(cfg, self._log).run()
                if not ok:
                    self._log(f"[실패] {os.path.basename(nut_path)}")
                else:
                    self._log(f"[완료] {os.path.basename(nut_path)}")

                # carry chosen codes forward if first success created it
                chosen_codes = cfg.get("chosen_codes") or chosen_codes

            self._log("─" * 76)
            self._log("전체 작업 종료.")
        except Exception as e:
            self._log(f"[치명적 예외] {e!r}")

    # ---------------- config ----------------

    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            self._apply_last_files_ui()
            return
        try:
            cfg = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
        except Exception:
            self._apply_last_files_ui()
            return

        # sliders
        self.font_size.set(int(cfg.get("font_size", DEFAULTS["font_size"])))
        self.baseline.set(int(cfg.get("baseline", DEFAULTS["baseline"])))
        self.x_offset.set(int(cfg.get("x_offset", DEFAULTS["x_offset"])))
        self.row_h.set(int(cfg.get("row_h", DEFAULTS["row_h"])))

        # font path
        fp = cfg.get("font_path")
        if fp and os.path.exists(fp):
            self.font_path.set(fp)

        # last files
        last_files = cfg.get("last_nut_paths") or []
        last_files = [p for p in last_files if isinstance(p, str)]
        self.last_nut_paths = last_files

        # extra chars
        extra = cfg.get("extra_chars", "")
        try:
            self.extra_box.delete("1.0", "end")
            self.extra_box.insert("1.0", extra)
        except Exception:
            pass

        self._apply_last_files_ui()

    def _apply_last_files_ui(self):
        if self.last_nut_paths:
            self.last_files_var.set("\n".join(self.last_nut_paths))
        else:
            self.last_files_var.set("(없음)")

    def _save_config(self):
        try:
            cfg = {
                "font_path": self.font_path.get(),
                "font_size": int(self.font_size.get()),
                "baseline": int(self.baseline.get()),
                "x_offset": int(self.x_offset.get()),
                "row_h": int(self.row_h.get()),
                "last_nut_paths": self.last_nut_paths,
                "extra_chars": self.extra_box.get("1.0", "end").rstrip("\n"),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def main():
    if freetype is None:
        print("ERROR: freetype-py missing.  pip install freetype-py")
        return

    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    # style root
    app = AppUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()