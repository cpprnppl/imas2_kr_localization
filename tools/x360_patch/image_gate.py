"""Image diff-ratio gate (KOR 2026-11-12: no original image data in the patch).

For every diff entry, the share of each texture's data that the diff carries as new (ADD) bytes must stay at or
below the limit (default 50%). Textures are the NTP3 (PS3) / NTXR (360, same header layout, swapped pixel data)
NUTs found anywhere in the plaintext output (nut, s2d, tsk, mpc, pac ...); raw image files (jpg/png/ptc/...) count
as one image. A texture over the limit fails unless ui registered it as fully redrawn in the exceptions file:

  {"exceptions": [{"platform": "pc|ps3|both", "target": "<manifest target>", "pkg": "<PC DLC package, optional>",
                   "tex": <texture index, optional = whole file>, "reason": "..."}]}

The ratio uses output offsets of the KDF1 ADD ops, so it measures what the patch ships, not what changed.
"""
import json
import os
import struct

import kd

LIMIT = 0.5
MIN_TEX = 1024                                    # smaller textures are not judged (icons, 1-block fills)
EXEMPT_MAX_W, EXEMPT_MAX_H = 256, 64              # KOR 11-12: only text labels up to 256x64 may be exempted;
                                                  # larger textures and raw image files never are, whatever the list says
RAW_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".ptc", ".gtf", ".dds")


def textures(data):
    """[(index, data_off, data_size, w, h)] for NTP3/NTXR NUTs in a plaintext buffer (as extract_image_text.walk_nuts)."""
    out, pos = [], 0
    while True:
        cands = [i for i in (data.find(b"NTP3", pos), data.find(b"NTXR", pos)) if i >= 0]
        if not cands:
            return out
        i = min(cands)
        if i + 16 > len(data):
            return out
        ver, cnt = struct.unpack_from(">HH", data, i + 4)
        packed, cur, texs, ok = ver >= 0x0200, i + 16, [], cnt > 0
        for _ in range(cnt):
            if cur + 80 > len(data):
                ok = False
                break
            total, _pal, dsz, hsz = struct.unpack_from(">IIIH", data, cur)
            w, h = struct.unpack_from(">HH", data, cur + 0x14)
            if data[cur + 0x30:cur + 0x34] != b"eXt\x00" or data[cur + 0x40:cur + 0x44] != b"GIDX" \
                    or hsz != 80 or total < 80 + dsz:
                ok = False
                break
            texs.append([cur + 80, dsz, total, w, h])
            cur += 80 if packed else total
        if ok and packed:
            base = cur
            for t in texs:
                t[0] = base
                base += t[2] - 80
            cur = base
        if ok and cur <= len(data):
            out += [(len(out) + k, t[0], t[1], t[3], t[4]) for k, t in enumerate(texs)]
            pos = cur
        else:
            pos = i + 4


def add_intervals(kdbytes):
    """Output-offset intervals [start, end) written by ADD ops."""
    iv, pos = [], 0
    for t, _a, ln in kd.ops(kdbytes):
        if t == 1 and ln:
            iv.append((pos, pos + ln))
        pos += ln
    return iv


def _overlap(iv, lo, hi):
    return sum(max(0, min(b, hi) - max(a, lo)) for a, b in iv if a < hi and b > lo)


class Gate:
    def __init__(self, platform, exceptions_path=None, limit=LIMIT):
        self.platform, self.limit = platform, limit
        self.exc, self.exc_sha = [], None
        if exceptions_path:
            raw = open(exceptions_path, "rb").read()
            import hashlib
            self.exc_sha = hashlib.sha256(raw).hexdigest()
            self.exc = [x for x in json.loads(raw.decode("utf-8"))["exceptions"]
                        if x.get("platform", "both") in ("both", platform)]
        self.checked, self.violations, self.exempted = 0, [], []

    def _exempt(self, target, pkg, tex):
        for x in self.exc:
            if x["target"] == target and x.get("pkg", pkg or None) == (pkg or None) and x.get("tex") in (None, tex):
                return x.get("reason", "")
        return None

    def check(self, target, out_plain, kdbytes, pkg=None):
        """Judge one entry; returns the highest texture ratio (None when the output holds no image data)."""
        if target.lower().endswith(RAW_EXT):
            regions = [(None, 0, len(out_plain), 0, 0)]
        else:
            regions = [r for r in textures(out_plain) if r[2] >= MIN_TEX]
        if not regions:
            return None
        iv = add_intervals(kdbytes)
        worst = 0.0
        for idx, off, size, w, h in regions:
            r = _overlap(iv, off, off + size) / size
            worst = max(worst, r)
            self.checked += 1
            if r > self.limit:
                rec = {"target": target, **({"pkg": pkg} if pkg else {}), "tex": idx, "w": w, "h": h,
                       "data_size": size, "add_ratio": round(r, 3)}
                why = self._exempt(target, pkg, idx)
                if why is not None and (idx is None or w > EXEMPT_MAX_W or h > EXEMPT_MAX_H):
                    rec["exception_refused"] = f"larger than {EXEMPT_MAX_W}x{EXEMPT_MAX_H} or a raw image file"
                    why = None
                if why is None:
                    self.violations.append(rec)
                else:
                    self.exempted.append({**rec, "reason": why})
        return round(worst, 3)

    def summary(self):
        return {"limit": self.limit, "min_texture_bytes": MIN_TEX, "exempt_max": f"{EXEMPT_MAX_W}x{EXEMPT_MAX_H}",
                "exceptions_sha256": self.exc_sha,
                "textures_checked": self.checked, "exempted": self.exempted, "violations": self.violations}

    def report(self, log=print):
        log(f"image gate ({self.platform}): textures checked {self.checked}, over {self.limit:.0%}: "
            f"violations {len(self.violations)}, exempted {len(self.exempted)}")
        for v in self.violations[:30]:
            log(f"  IMAGE {v.get('pkg', '')[:8] + '/' if v.get('pkg') else ''}{v['target']} tex {v['tex']} "
                f"{v['w']}x{v['h']} ADD {v['add_ratio']:.0%} of {v['data_size']:,} B")
        return not self.violations
