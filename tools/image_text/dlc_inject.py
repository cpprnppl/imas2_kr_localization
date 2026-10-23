#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DLC 한글 주입기 — 360(PC 포트) 한글판 DLC 사본 + PS3(RPCS3) 재암호화본

번역 원천 (읽기만):
  dlc_translations.json   웹앱 dlc 분류 회수본 (webapp_pull.py dlc). 키 "<grp>/<stem>:<tid>",
                          meta.src = 원본 위치 ("360:<pkg6>/<rel>#x<n>", "ps3:cpNN/<rel>#x<n>")
  xmb_translations.json   songinfo/<곡>/lyrics_<곡>.xmb — DLC 신곡 가사 (id 기준)
  이모티콘(PUA U+E000~E03F)·치환 코드(U+F001~)는 손대지 않는다(한글만 변환 대상).

대상 파일 (패키지 resource\\ 아래):
  catalog_info.xmb (단독 XMB) / packageInfo.pac (TSK: XMB 2 + eqp 2) /
  mail\\*.xmb (01호) / ranker\\*.xmb (PS3) / songinfo\\<곡>\\lyrics_<곡>.xmb /
  dance\\dan_<곡>_{1,3,5}.mpc (라이브 가사는 여기서 읽는다 — 워크로그 §28-2)

암호: 게임 자체 AES-192-CBC (IV 0, 선두 16B prefix 블록). 키 = 384B 키표 + 풋터 3바이트.
  360 = table360.bin, 풋터 32B.  PS3 DLC = table.bin[384:768](두 번째 표), 풋터 64B.
  복호화→무수정 재암호화 = 원본과 바이트 동일(360 75개·PS3 148개 전수 확인, 2026-10-23).

  python dlc_inject.py build360            # Desktop\\imas2dlc\\content_kor 생성/갱신 (평문 주입)
  python dlc_inject.py coverage            # 플랫폼·그룹별 웹앱 원문 존재율 / kr 적용률
  python dlc_inject.py roundtrip           # 양 플랫폼 복호화→재암호화 바이트 동일 전수 검사
  python dlc_inject.py build-ps3 [--plain] # 순정 백업 → out_dlc_ps3\\ (기본 재암호화, --plain = 평문)
  python dlc_inject.py deploy-ps3          # 검증 게이트 후 RPCS3 dlc에 교체 (RPCS3 종료 상태)
  python dlc_inject.py restore-ps3         # RPCS3 dlc를 순정 백업으로 되돌림

원칙: DLC 원본(content, RPCS3 순정 백업)은 읽기 전용. 결과물·백업은 git·공유 폴더 금지.
360은 평문(PC 포트 엔진이 평문 pac/XMB 수용) + 원시 한글(직접 등록 폰트).
PS3도 직접 등록 한글(§25, 2026-10-14 전환) — font_mapping 한자 슬롯은 쓰지 않는다.
"""
import os
import sys
import json
import time
import glob
import shutil
import struct
import hashlib
import argparse
from collections import Counter, defaultdict

from Crypto.Cipher import AES

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402
from xmb_text import parse_xmb, collect_texts, rebuild_xmb, encode_with_mapping, MAPPING_PATH  # noqa: E402
import dance_lyrics  # noqa: E402  (parse_pac / rebuild_pac — dance pac 가사 엔트리)

X360_SRC = r"C:\Users\jackfilm\Desktop\imas2dlc\content"          # 읽기 전용 원본
X360_KOR = r"C:\Users\jackfilm\Desktop\imas2dlc\content_kor"      # 한글판 사본 (dlc_root)
X360_SUB = os.path.join("4E4D0817", "00000002")
PS3_DLC = os.path.join(os.path.dirname(JP_ROOT), "dlc")           # RPCS3 NPJB00337\USRDIR\dlc
PS3_ORIG = os.path.join(OUT_DEFAULT, "ps3_dlc_orig")               # 순정 백업 (대상 파일만)
PS3_OUT = os.path.join(OUT_DEFAULT, "out_dlc_ps3")
REPORT_DIR = os.path.join(OUT_DEFAULT, "out_dlc")
KEYDIR = os.path.join(JP_ROOT, "gscript", "imas2dec", "imas2dec")
MAGIC = (b"pac\x00", b"XMB ", b"TSK ", b"NTP3", b"NTXR")


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 암호

class Cipher:
    def __init__(self, table, foot):
        self.table, self.foot = table, foot

    def _key(self, d):
        fp = len(d) - 32
        n1, n2, n3 = d[fp + 1], d[fp + 2], d[fp + 3]
        o0, o1 = ((n1 >> 4) & 0xF) * 24, (n1 & 0xF) * 24
        i0, i1 = n2 % 24, n3 % 24
        k = bytearray(24)
        for i in range(24):
            k[i] = self.table[o0 + i0] ^ self.table[o1 + i1]
            i0, i1 = (i0 + 1) % 24, (i1 + 1) % 24
        return bytes(k)

    def decrypt(self, raw):
        """(평문, ctx). 이미 평문이면 ctx=None. 평문은 prefix 뒤 전체(원 패딩 포함)."""
        if raw[:4] in MAGIC:
            return raw, None
        body = raw[:len(raw) - self.foot]
        if len(body) % 16:
            raise ValueError("암호 본문이 16바이트 배수가 아님")
        key = self._key(raw)
        full = AES.new(key, AES.MODE_CBC, b"\x00" * 16).decrypt(body)
        if full[16:20] not in MAGIC:
            raise ValueError("복호화 결과 시그니처 없음")
        return full[16:], {"key": key, "prefix": full[:16], "footer": raw[len(raw) - self.foot:]}

    @staticmethod
    def encrypt(plain, ctx):
        """원본 prefix·풋터 유지. 길이가 변하면 0 패딩(게임 디코더는 컨테이너 크기를 따름)."""
        buf = ctx["prefix"] + plain
        buf += b"\x00" * ((-len(buf)) % 16)
        return AES.new(ctx["key"], AES.MODE_CBC, b"\x00" * 16).encrypt(buf) + ctx["footer"]


def ciphers():
    t = open(os.path.join(KEYDIR, "table.bin"), "rb").read()
    t3 = open(os.path.join(KEYDIR, "table360.bin"), "rb").read()
    return {"360": Cipher(t3, 32), "ps3": Cipher(t[384:768], 64)}


# ---------------------------------------------------------------- 텍스트 열거 (dlc_text.py와 같은 번호 체계)

def xmb_offsets(data):
    out, p = [], 0
    while (i := data.find(b"XMB ", p)) >= 0:
        out.append(i)
        p = i + 4
    return out


def texts_of(data):
    """[(xi, base, tid, attr, text)] — xi는 버퍼 안 'XMB ' 출현 순번(파싱 실패도 번호 소비),
    tid는 XMB 안 중복 id에 '.n' 서수(dlc_text.xmb_texts_all과 동일)."""
    out = []
    for xi, base in enumerate(xmb_offsets(data)):
        try:
            ts = collect_texts(parse_xmb(data, base))
        except Exception:  # noqa: BLE001
            continue
        seen = Counter()
        for t in ts:
            seen[t["id"]] += 1
            tid = t["id"] if seen[t["id"]] == 1 else f"{t['id']}.{seen[t['id']]}"
            out.append((xi, base, tid, t["attr"], t["text"]))
    return out


# ---------------------------------------------------------------- 컨테이너

def tsk_parse(d):
    n = struct.unpack_from(">I", d, 4)[0]
    ents = [struct.unpack_from(">II", d, 8 + i * 8) for i in range(n)]   # (size, ofs)
    return n, ents


def tsk_build(d, blobs):
    """blobs: {entry_index: 새 바이트}. 헤더(첫 엔트리 ofs까지)·정렬 0x40 유지."""
    n, ents = tsk_parse(d)
    head = ents[0][1]
    out = bytearray(d[:head])
    for i, (size, ofs) in enumerate(ents):
        b = blobs.get(i, d[ofs:ofs + size])
        out += b"\x00" * ((-len(out)) % 0x40)
        struct.pack_into(">II", out, 8 + i * 8, len(b), len(out))
        out += b
    out += b"\x00" * ((-len(out)) % 0x40)
    return bytes(out)


def kind_of(rel):
    r = rel.replace("\\", "/")
    if r.endswith("packageInfo.pac"):
        return "package"
    if r.endswith("catalog_info.xmb"):
        return "catalog"
    if r.startswith("mail/"):
        return "mail"
    if r.startswith("ranker/"):
        return "ranker"
    if r.startswith("songinfo/") and "/lyrics_" in r:
        return "lyrics"
    if r.startswith("dance/dan_") and r.endswith(".mpc"):
        return "dance"
    return None


def song_of(rel):
    r = rel.replace("\\", "/")
    if r.startswith("songinfo/"):
        return r.split("/")[1]
    return os.path.basename(r)[len("dan_"):].rsplit("_", 1)[0]


def targets(res_root):
    out = []
    for pat in ("catalog_info.xmb", "packageInfo.pac", os.path.join("mail", "*.xmb"),
                os.path.join("ranker", "*.xmb"), os.path.join("songinfo", "*", "lyrics_*.xmb"),
                os.path.join("dance", "dan_*.mpc")):
        out += [os.path.relpath(p, res_root) for p in glob.glob(os.path.join(res_root, pat))]
    return sorted(out)


# ---------------------------------------------------------------- 번역 색인

class Translations:
    def __init__(self):
        from exe_inject import font_set
        self.mapping = font_set()   # 직접 등록 폰트 한글 집합(폰트 세션 기준 파일)
        tr = json.load(open(os.path.join(HERE, "dlc_translations.json"), encoding="utf-8"))
        self.by_src = defaultdict(list)    # (plat, pkg, rel) → [(xi|None, tid, jp, kr)]
        self.jp_by_grp = defaultdict(lambda: defaultdict(Counter))
        self.n_rows = 0
        for key, v in tr.items():
            kr = v.get("kr")
            if not kr:
                continue
            grp, rest = key.split("/", 1)
            tid = rest.split(":", 1)[1]
            if tid.startswith("x") and "." in tid and tid[1:].split(".", 1)[0].isdigit():
                tid = tid.split(".", 1)[1]           # catalog/package 키의 x<n>. 접두
            self.n_rows += 1
            self.jp_by_grp[grp][v["jp"]][kr] += 1
            for src in v.get("meta", {}).get("src", []):
                plat, loc = src.split(":", 1)
                pkg, rel = loc.split("/", 1)
                xi = None
                if "#x" in rel:
                    rel, x = rel.split("#x")
                    xi = int(x)
                self.by_src[(plat, pkg, rel)].append((xi, tid, v["jp"], kr))
        # 가사: xmb_translations의 songinfo/<곡> (webapp_pull dlc가 병합) + dlc 행 songinfo 그룹
        x = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
        self.lyrics = defaultdict(dict)
        for k, ents in x.items():
            if k.startswith("songinfo/"):
                song = k.split("/")[1]
                for tid, e in ents.items():
                    if e.get("kr"):
                        self.lyrics[song][tid] = (e.get("jp", ""), e["kr"])
        for key, v in tr.items():
            if key.startswith("songinfo/lyrics_") and v.get("kr"):
                stem, tid = key.split("/", 1)[1].split(":", 1)
                self.lyrics[stem[len("lyrics_"):]].setdefault(tid.split(".")[0], (v["jp"], v["kr"]))
        self.missing = set()

    def enc(self, s, _plat):
        """양 플랫폼 모두 직접 등록 폰트(§25, PS3도 2026-10-14부터) = 원시 한글.
        font_mapping의 한자 슬롯은 PS3 폰트에서 이미 한글 코드로 바뀌어 없다 → 쓰면 '?'.
        폰트에 없는 한글(매핑 키 2,359자 밖)만 기록한다."""
        self.missing |= {c for c in s if "가" <= c <= "힣" and c not in self.mapping}
        return s

    def plan(self, plat, pkg, rel, texts):
        """{(xi, attr): kr} + 통계. 원문(jp)이 일치할 때만 교체한다."""
        kind = kind_of(rel)
        rel_s = rel.replace("\\", "/")
        repl, st = {}, Counter()
        if kind in ("lyrics", "dance"):
            lyr = self.lyrics.get(song_of(rel), {})
            for xi, _b, tid, attr, text in texts:
                hit = lyr.get(tid.split(".")[0])
                if not hit:
                    continue
                jp, kr = hit
                if jp and jp != text:
                    st["jp불일치"] += 1
                    continue
                repl[(xi, attr)] = kr
                st["가사"] += 1
            return repl, st
        grp = kind
        srcs = self.by_src.get((plat, pkg[:6] if plat == "360" else pkg, rel_s), [])  # 360 src = 패키지 6자리
        idx = defaultdict(list)
        for xi, tid, jp, kr in srcs:
            idx[tid].append((xi, jp, kr))
        for xi, _b, tid, attr, text in texts:
            kr = None
            for sxi, jp, k in idx.get(tid, []):
                if (sxi is None or sxi == xi) and jp == text:
                    kr = k
                    st["키"] += 1
                    break
            if kr is None and text in self.jp_by_grp[grp]:
                kr = self.jp_by_grp[grp][text].most_common(1)[0][0]
                st["원문일치"] += 1
            if kr is not None:
                repl[(xi, attr)] = kr
        return repl, st


# ---------------------------------------------------------------- 적용

def apply(data, plan_repl, plat, tr):
    """평문 data에 {(xi, attr): kr} 적용 → (새 평문, 교체 수). 재파싱 검증 포함."""
    if not plan_repl:
        return data, 0
    offs = xmb_offsets(data)
    by_xi = defaultdict(dict)
    for (xi, attr), kr in plan_repl.items():
        by_xi[xi][attr] = tr.enc(kr, plat)
    if data[:4] == b"XMB ":
        assert set(by_xi) == {0}, "단독 XMB에 xi≠0"
        out = rebuild_xmb(data, 0, by_xi[0], lambda *a: None, allow_grow=True)
    elif data[:4] == b"TSK ":
        n, ents = tsk_parse(data)
        assert tsk_build(data, {}) == data, "TSK 무수정 재조립이 원본과 다름"
        blobs = {}
        for i, (size, ofs) in enumerate(ents):
            xs = [xi for xi, o in enumerate(offs) if ofs <= o < ofs + size]
            for xi in xs:
                if xi in by_xi:
                    assert offs[xi] == ofs, f"TSK 엔트리 {i} 선두가 XMB가 아님"
                    blobs[i] = rebuild_xmb(data[ofs:ofs + size], 0, by_xi[xi], lambda *a: None,
                                           allow_grow=True)
        out = tsk_build(data, blobs)
    elif data[:4] == b"pac\x00":
        cnt, ents, ds, lyr_ent = dance_lyrics.parse_pac(data)
        lo = ds + lyr_ent["ofs"]
        xs = [xi for xi, o in enumerate(offs) if o == lo]
        assert xs and set(by_xi) == {xs[0]}, "dance pac: 가사 XMB 외 교체 시도"
        seg = data[lo:lo + lyr_ent["size"]]
        new = rebuild_xmb(seg, 0, by_xi[xs[0]], lambda *a: None, allow_grow=True)
        out = dance_lyrics.rebuild_pac(data, ents, ds, lyr_ent, new)
        _c, ents2, ds2, _l = dance_lyrics.parse_pac(out)
        for e, e2 in zip(sorted(ents, key=lambda x: x["i"]), sorted(ents2, key=lambda x: x["i"])):
            if e["i"] != lyr_ent["i"]:
                assert data[ds + e["ofs"]:ds + e["ofs"] + e["size"]] == \
                    out[ds2 + e2["ofs"]:ds2 + e2["ofs"] + e2["size"]], "dance pac 비가사 엔트리 변형"
    else:
        raise ValueError("알 수 없는 컨테이너")
    # 검증: 교체 대상은 새 문자열, 나머지 _text는 원문 그대로
    before = {(xi, attr): text for xi, _b, _t, attr, text in texts_of(data)}
    after = {(xi, attr): text for xi, _b, _t, attr, text in texts_of(out)}
    assert before.keys() == after.keys(), "XMB/텍스트 개수 변동"
    for k, t in before.items():
        want = tr.enc(plan_repl[k], plat) if k in plan_repl else t
        assert after[k] == want, f"재파싱 불일치 {k}"
    return out, len(plan_repl)


# ---------------------------------------------------------------- 그림 (카탈로그 페이지·곡 로고·재킷·PS3 ad_bg)
# 입력: 한글 PNG(원본과 같은 치수)
#   360: <OUT>/kr_dlc/<pkg6>/<stem>_<nnn>.png       (webapp_pull image의 360: DLC 규칙)
#   PS3: <OUT>/kr_dlc_ps3/<cpNN>/<stem>_<nnn>.png   (stem = rel의 / → _, 확장자 제외)
# NUT 텍스처는 같은 포맷·같은 크기로 제자리 인코드(밉 이하 원본 유지) + 재디코드 게이트.
# 360 NTXR: DXT/32bpp는 16비트 스왑, fmt10/11(ARGB1555/4444)은 BE 그대로(dlc_images.decode_360).
# PS3 ad_bg.jpg(1280x720 메인 메뉴 배경+카탈로그 배너): JPEG 재인코드(길이 가변) 후 재암호화.
# 360 ad_bg.ptc는 PTC 코덱이라 미지원(인코더 없음, 워크로그 §42).

KR_360 = os.path.join(OUT_DEFAULT, "kr_dlc")
KR_PS3 = os.path.join(OUT_DEFAULT, "kr_dlc_ps3")


def image_targets(res_root, plat):
    pats = ["catalog_info.nut", os.path.join("songinfo", "*", "jacket_*.nut")]
    pats.append("ad_bg.jpg" if plat == "ps3" else "ad_bg.ptc")
    out = []
    for pat in pats:
        out += [os.path.relpath(p, res_root) for p in glob.glob(os.path.join(res_root, pat))]
    return sorted(out)


def kr_images(plat, pkg, rel):
    """{n: png 경로} — 이 파일에 대한 한글 작업본."""
    stem = rel.replace("\\", "/").replace("/", "_").rsplit(".", 1)[0]
    d = os.path.join(KR_360, pkg[:6]) if plat == "360" else os.path.join(KR_PS3, pkg)
    out = {}
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.startswith(stem + "_") and fn.endswith(".png") and fn[len(stem) + 1:-4].isdigit():
                out[int(fn[len(stem) + 1:-4])] = os.path.join(d, fn)
    return out


def _codecs(plat, fmt):
    """(dec(raw,w,h)->RGBA, enc(RGBA)->bytes, 무손실?)"""
    from extract_image_text import decode_texture, FMT_NAMES
    from inject_image_text import encode_texture
    from dlc_images import swap16, decode_360
    if plat == "360":
        if fmt == 10:
            from pcport_apply import _enc_1555
            return (lambda r, w, h: decode_360(10, r, w, h)), _enc_1555, False
        if fmt == 11:
            return (lambda r, w, h: decode_360(11, r, w, h)), (lambda im: encode_texture("ARGB4444", im)), False
        if fmt == 19:
            return (lambda r, w, h: decode_360(19, r, w, h)), (lambda im: encode_texture("ARGB32", im)), True
        nm = FMT_NAMES[fmt]
        return (lambda r, w, h: decode_360(fmt, r, w, h)), (lambda im: swap16(encode_texture(nm, im))), False
    if fmt == 6:
        # PS3 DLC 카탈로그 페이지: FMT_NAMES는 RGB565라 하지만 실제는 ARGB1555 BE(360 fmt10과 같은 비트).
        # 565로 풀면 포스터화·마젠타 번짐(2026-10-23 cp01 #019 비교로 확인).
        from pcport_apply import _enc_1555
        return (lambda r, w, h: decode_360(10, r, w, h)), _enc_1555, False
    nm = FMT_NAMES[fmt]
    return (lambda r, w, h: decode_texture(fmt, r, w, h)), (lambda im: encode_texture(nm, im)), nm == "ARGB32"


def apply_images(plat, pkg, rel, plain, jobs, log):
    """NUT 평문에 jobs {n: png} 적용 → (새 평문, 교체 수). 게이트: 치수·크기 일치, 재디코드 PSNR."""
    import numpy as np
    from PIL import Image
    from extract_image_text import walk_nuts
    from inject_image_text import psnr
    data = bytearray(plain)
    texs = walk_nuts(bytes(data).replace(b"NTXR", b"NTP3"), lambda *a: None)
    done = 0
    for n, png in sorted(jobs.items()):
        if n >= len(texs):
            raise ValueError(f"{rel}#{n:03d}: 텍스처 없음(파일에 {len(texs)}장)")
        t = texs[n]
        img = np.asarray(Image.open(png).convert("RGBA"), np.uint8)
        if img.shape[:2] != (t["h"], t["w"]):
            raise ValueError(f"{rel}#{n:03d}: 치수 {img.shape[1]}x{img.shape[0]} != {t['w']}x{t['h']}")
        dec, enc, lossless = _codecs(plat, t["fmt"])
        raw = bytes(data[t["data_off"]:t["data_off"] + t["data_size"]])
        new = enc(img)
        if len(new) < t["data_size"]:           # 밉 레벨은 원본 유지
            new = new + raw[len(new):]
        if len(new) != t["data_size"]:
            raise ValueError(f"{rel}#{n:03d}: 인코드 {len(new)}B != {t['data_size']}B")
        q = psnr(dec(new, t["w"], t["h"]), img)
        lim = 60.0 if lossless else (28.0 if t["fmt"] in (10, 11) else 33.0)   # 16bpp는 양자화 손실 감안
        if q < lim:
            raise ValueError(f"{rel}#{n:03d}: 재디코드 {q:.1f}dB < {lim}")
        data[t["data_off"]:t["data_off"] + t["data_size"]] = new
        done += 1
        log(f"    #{n:03d} {t['w']}x{t['h']} fmt{t['fmt']} 재디코드 {q:.1f}dB")
    return bytes(data), done


def jpeg_plain(raw_dec):
    """복호화 평문에서 JPEG 본체(FFD8..FFD9)와 꼬리 패딩 길이."""
    end = raw_dec.rfind(b"\xff\xd9") + 2
    if raw_dec[:2] != b"\xff\xd8" or end < 4:
        raise ValueError("JPEG 아님")
    return raw_dec[:end]


def ps3_decrypt_any(c, raw):
    """dlc_inject.Cipher.decrypt는 알려진 매직만 허용 — JPEG(ad_bg.jpg)용."""
    body = raw[:len(raw) - c.foot]
    key = c._key(raw)
    full = AES.new(key, AES.MODE_CBC, b"\x00" * 16).decrypt(body)
    return full[16:], {"key": key, "prefix": full[:16], "footer": raw[len(raw) - c.foot:]}


# 360 ad_bg.ptc는 MS PTC 코덱이라 다시 인코드할 수 없다. imas2pc 배너 훅(src/kernel/ps3feat.cpp,
# main 5bfa82c)이 'IM2PCRAW' + w,h(BE u32) + A,R,G,B 원시 픽셀을 받아 그대로 복사한다.
RAW_MAGIC = b"IM2PCRAW"
AD_BG_360 = (1280, 720)


def _argb(img):
    import numpy as np
    return np.asarray(img.convert("RGBA"))[..., [3, 0, 1, 2]].tobytes()


def im2pcraw(img):
    import struct
    w, h = img.size
    return RAW_MAGIC + struct.pack(">II", w, h) + _argb(img)


def im2pcraw_check(data, img):
    import struct
    assert data[:8] == RAW_MAGIC, "매직 불일치"
    w, h = struct.unpack(">II", data[8:16])
    assert (w, h) == img.size and 1 <= w <= 4096 and 1 <= h <= 4096, f"치수 {w}x{h}"
    assert len(data) == 16 + w * h * 4, "길이 불일치"
    assert data[16:] == _argb(img), "픽셀 불일치"


def build_images(plat, src_root_iter, write, log):
    """src_root_iter: [(pkg, res_dir, raw_reader)]. write(pkg, rel, new_bytes, info). 반환 (교체 파일 수, 실패)."""
    import io
    from PIL import Image
    c = ciphers()[plat]
    nfile, fails = 0, []
    for pkg, res, read in src_root_iter:
        for rel in image_targets(res, plat):
            jobs = kr_images(plat, pkg, rel)
            if not jobs:
                continue
            raw = read(rel)
            try:
                if rel.endswith(".ptc"):
                    img = Image.open(jobs[0]).convert("RGBA")
                    if img.size != AD_BG_360:
                        raise ValueError(f"{rel}: 치수 {img.size} != {AD_BG_360}")
                    new = im2pcraw(img)
                    im2pcraw_check(new, img)
                    log(f"  {pkg[:6]}/{rel}: PTC {len(raw):,}→IM2PCRAW {len(new):,}B")
                    write(pkg, rel, new, {"im2pcraw": True})
                elif rel.endswith(".jpg"):
                    dec, ctx = ps3_decrypt_any(c, raw)
                    jp = jpeg_plain(dec)
                    orig = Image.open(io.BytesIO(jp))
                    png = jobs.get(0)
                    img = Image.open(png).convert("RGB")
                    if img.size != orig.size:
                        raise ValueError(f"{rel}: 치수 {img.size} != {orig.size}")
                    # 원본의 양자화 표·크로마 샘플링으로 시작해 화질을 원본 수준으로 유지하되,
                    # 게임 쪽 버퍼가 원본 크기 기준일 수 있으므로 원본보다 커지면 표를 조금씩 거칠게 한다.
                    from PIL import JpegImagePlugin
                    samp = JpegImagePlugin.get_sampling(orig)
                    samp = samp if samp >= 0 else 0
                    for k in range(40):
                        f = 1.0 + 0.05 * k
                        qt = {i: [min(255, max(1, round(v * f))) for v in t] for i, t in orig.quantization.items()}
                        buf = io.BytesIO()
                        img.save(buf, "JPEG", qtables=qt, subsampling=samp)
                        out = buf.getvalue()
                        if len(out) <= len(jp):
                            break
                    else:
                        raise ValueError(f"{rel}: 원본 크기 {len(jp):,}B 이하로 못 줄임")
                    new = Cipher.encrypt(out, ctx)
                    back, _ = ps3_decrypt_any(c, new)
                    assert jpeg_plain(back) == out, "재암호화 검증 실패"
                    log(f"  {pkg}/{rel}: JPEG {len(jp):,}→{len(out):,}B (양자화 ×{f:.2f})")
                    write(pkg, rel, new, {"jpeg": True})
                else:
                    plain, ctx = c.decrypt(raw)
                    out, n = apply_images(plat, pkg, rel, plain, jobs, log)
                    if plat == "360":
                        new = out                                  # PC 포트: 평문
                    else:
                        new = Cipher.encrypt(out, ctx) if ctx else out
                        if ctx:
                            back, _ = c.decrypt(new)
                            assert back[:len(out)] == out, "재암호화 검증 실패"
                    log(f"  {pkg[:6] if plat == '360' else pkg}/{rel}: 텍스처 {n}장")
                    write(pkg, rel, new, {"tex": n})
                nfile += 1
            except Exception as e:  # noqa: BLE001
                fails.append(f"{pkg}/{rel}: {e}")
                log(f"  [실패] {pkg}/{rel}: {e}")
    return nfile, fails


# ---------------------------------------------------------------- 360

def build360(_args):
    tr = Translations()
    cph = ciphers()["360"]
    src_root = os.path.join(X360_SRC, X360_SUB)
    dst_root = os.path.join(X360_KOR, X360_SUB)
    if not os.path.isdir(dst_root):
        print(f"사본 생성: {X360_SRC} → {X360_KOR} (최초 1회, 2.1GB)")
        shutil.copytree(X360_SRC, X360_KOR)
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": tr.n_rows, "files": [], "fail": []}
    tot = Counter()
    for pkg in sorted(os.listdir(src_root)):
        res = os.path.join(src_root, pkg, "resource")
        if not os.path.isdir(res):
            continue
        for rel in targets(res):
            raw = open(os.path.join(res, rel), "rb").read()
            dst = os.path.join(dst_root, pkg, "resource", rel)
            try:
                plain, ctx = cph.decrypt(raw)
                repl, st = tr.plan("360", pkg, rel, texts_of(plain))
                out, n = apply(plain, repl, "360", tr)
            except Exception as e:  # noqa: BLE001
                report["fail"].append(f"{pkg[:6]}/{rel}: {e}")
                print(f"  [실패] {pkg[:6]}/{rel}: {e}")
                continue
            new = out if n else raw                     # 미번역 파일은 원본 바이트 그대로(사본 원복)
            if not os.path.exists(dst) or open(dst, "rb").read() != new:
                open(dst, "wb").write(new)
            if n:
                tot.update(st)
                tot["파일"] += 1
                report["files"].append({"pkg": pkg[:6], "rel": rel, "repl": n, "how": dict(st),
                                        "plain": True, "size": len(new), "sha256": sha(new)})
                print(f"  {pkg[:6]}/{rel}: {n}칸 ({dict(st)}) {len(raw):,}→{len(new):,}B")
    # 그림: 작업본 있는 파일만 평문 주입, 없는 파일은 원본 바이트로 원복
    pkgs = [p for p in sorted(os.listdir(src_root)) if os.path.isdir(os.path.join(src_root, p, "resource"))]
    touched = set()

    def w360(pkg, rel, new, info):
        dst = os.path.join(dst_root, pkg, "resource", rel)
        open(dst, "wb").write(new)
        touched.add((pkg, rel))
        report["files"].append({"pkg": pkg[:6], "rel": rel, "image": info, "plain": True,
                                "size": len(new), "sha256": sha(new)})
    it = [(p, os.path.join(src_root, p, "resource"),
           (lambda rel, p=p: open(os.path.join(src_root, p, "resource", rel), "rb").read())) for p in pkgs]
    ni, fi = build_images("360", it, w360, print)
    report["fail"] += fi
    for p in pkgs:
        res = os.path.join(src_root, p, "resource")
        for rel in image_targets(res, "360"):
            if (p, rel) not in touched:
                dst = os.path.join(dst_root, p, "resource", rel)
                raw = open(os.path.join(res, rel), "rb").read()
                if open(dst, "rb").read() != raw:
                    open(dst, "wb").write(raw)
    tot["그림파일"] = ni
    os.makedirs(REPORT_DIR, exist_ok=True)
    json.dump(report, open(os.path.join(REPORT_DIR, "report_360.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n360 한글판: 번역 {tr.n_rows}행 + 가사 {sum(len(v) for v in tr.lyrics.values())}행 → "
          f"파일 {tot['파일']}개 교체 {dict(tot)} / 실패 {len(report['fail'])}")
    print(f"dlc_root = {X360_KOR}  (원본 {X360_SRC} 불변)")
    return 1 if report["fail"] else 0


# ---------------------------------------------------------------- 진척

def coverage(_args):
    """플랫폼·그룹별 대상 텍스트(비ASCII _text 칸) 중 웹앱 원문 존재 / kr 적용 가능 칸."""
    tr = Translations()
    rows = json.load(open(os.path.join(HERE, "dlc_texts.json"), encoding="utf-8"))
    jp_src = defaultdict(set)
    for v in rows.values():
        jp_src[v["grp"]].add(v["jp"])
    audit_p = os.path.join(HERE, "platform_audit.json")   # 웹앱에 추가된 PS3 행(platform_audit apply)
    if os.path.exists(audit_p):
        for v in json.load(open(audit_p, encoding="utf-8")).get("dlc", {}).get("add_lyrics", {}).values():
            jp_src["songinfo"].add(v["jp"])
    nosrc = []
    c = ciphers()
    for plat, root, pat in (("360", os.path.join(X360_SRC, X360_SUB), "*"),
                            ("ps3", PS3_ORIG if os.path.isdir(PS3_ORIG) else PS3_DLC, "cp*")):
        tot, src, done = Counter(), Counter(), Counter()
        nosrc_songs = set()
        for res in sorted(glob.glob(os.path.join(root, pat, "resource"))):
            pkg = os.path.basename(os.path.dirname(res))
            for rel in targets(res):
                plain, _ = c[plat].decrypt(open(os.path.join(res, rel), "rb").read())
                texts = [t for t in texts_of(plain) if t[4] and not t[4].isascii()]
                kind = kind_of(rel)
                g = "songinfo" if kind in ("lyrics", "dance") else kind
                repl, _st = tr.plan(plat, pkg, rel, texts)
                for xi, _b, tid, attr, text in texts:
                    tot[g] += 1
                    if g == "songinfo":
                        has = text in jp_src["songinfo"] or tid.split(".")[0] in tr.lyrics.get(song_of(rel), {})
                        if not has:
                            nosrc_songs.add(song_of(rel))
                    else:
                        has = text in jp_src[g]
                    if not has and g != "songinfo":
                        nosrc.append({"plat": plat, "pkg": pkg[:6] if plat == "360" else pkg, "file": rel,
                                      "grp": g, "xi": xi, "id": tid, "jp": text})
                    src[g] += has
                    done[g] += (xi, attr) in repl
        print(f"== {plat}")
        for g in sorted(tot):
            print(f"  {g:9s} 칸 {tot[g]:5d} | 웹앱 원문 {src[g]:5d} ({100 * src[g] // tot[g]}%) | "
                  f"kr 적용 {done[g]:5d} ({100 * done[g] // tot[g]}%)")
        if nosrc_songs:
            print(f"  웹앱에 가사 원문이 없는 곡: {' '.join(sorted(nosrc_songs))}")
    if nosrc:
        os.makedirs(REPORT_DIR, exist_ok=True)
        p = os.path.join(REPORT_DIR, "coverage_nosrc.json")
        json.dump(nosrc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"웹앱 원문 없는 칸 {len(nosrc)}개 목록 → {p}")


# ---------------------------------------------------------------- 왕복 검사

def roundtrip(_args):
    c = ciphers()
    bad = 0
    stat = Counter()
    for plat, root, pat in (("360", os.path.join(X360_SRC, X360_SUB), "*"),
                            ("ps3", PS3_ORIG if os.path.isdir(PS3_ORIG) else PS3_DLC, "cp*")):
        for res in sorted(glob.glob(os.path.join(root, pat, "resource"))):
            for rel in targets(res):
                raw = open(os.path.join(res, rel), "rb").read()
                plain, ctx = c[plat].decrypt(raw)
                if ctx is None:
                    stat[(plat, "평문")] += 1
                    continue
                ok = Cipher.encrypt(plain, ctx) == raw
                stat[(plat, "동일" if ok else "불일치")] += 1
                if not ok:
                    bad += 1
                    print(f"  [불일치] {plat} {res}\\{rel}")
    for k, v in sorted(stat.items()):
        print(f"  {k[0]} {k[1]}: {v}")
    print("왕복 검사:", "통과" if not bad else f"실패 {bad}")
    return 1 if bad else 0


# ---------------------------------------------------------------- PS3

def ps3_snapshot():
    """대상 파일의 순정 백업을 한 번만 만든다(이후 build는 항상 여기서 읽음)."""
    mani_p = os.path.join(PS3_ORIG, "manifest.json")
    if os.path.exists(mani_p):
        return json.load(open(mani_p, encoding="utf-8"))
    c = ciphers()["ps3"]
    mani = {}
    for res in sorted(glob.glob(os.path.join(PS3_DLC, "cp*", "resource"))):
        cp = os.path.basename(os.path.dirname(res))
        for rel in targets(res):
            raw = open(os.path.join(res, rel), "rb").read()
            c.decrypt(raw)                                  # 순정 = 복호화되는 원본이어야 함
            dst = os.path.join(PS3_ORIG, cp, "resource", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(raw)
            mani[f"{cp}/{rel}"] = sha(raw)
    json.dump(mani, open(mani_p, "w", encoding="utf-8"), indent=1)
    print(f"PS3 순정 백업 {len(mani)}개 → {PS3_ORIG}")
    return mani


def ps3_snapshot_img():
    """그림 대상(카탈로그·재킷·로고 NUT, ad_bg.jpg) 순정 백업 — 텍스트와 별도 매니페스트."""
    mani_p = os.path.join(PS3_ORIG, "manifest_img.json")
    if os.path.exists(mani_p):
        return json.load(open(mani_p, encoding="utf-8"))
    mani = {}
    for res in sorted(glob.glob(os.path.join(PS3_DLC, "cp*", "resource"))):
        cp = os.path.basename(os.path.dirname(res))
        for rel in image_targets(res, "ps3"):
            raw = open(os.path.join(res, rel), "rb").read()
            dst = os.path.join(PS3_ORIG, cp, "resource", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(raw)
            mani[f"{cp}/{rel}"] = sha(raw)
    json.dump(mani, open(mani_p, "w", encoding="utf-8"), indent=1)
    print(f"PS3 그림 순정 백업 {len(mani)}개 → {PS3_ORIG}")
    return mani


def ps3_manifest():
    m = dict(json.load(open(os.path.join(PS3_ORIG, "manifest.json"), encoding="utf-8")))
    pi = os.path.join(PS3_ORIG, "manifest_img.json")
    if os.path.exists(pi):
        m.update(json.load(open(pi, encoding="utf-8")))
    return m


def build_ps3(args):
    tr = Translations()
    c = ciphers()["ps3"]
    mani = ps3_snapshot()
    if os.path.isdir(PS3_OUT):
        shutil.rmtree(PS3_OUT)
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "plain": args.plain, "files": [], "fail": []}
    tot = Counter()
    for key in sorted(mani):
        cp, rel = key.split("/", 1)
        raw = open(os.path.join(PS3_ORIG, cp, "resource", rel), "rb").read()
        assert sha(raw) == mani[key], f"순정 백업 변형: {key}"
        try:
            plain, ctx = c.decrypt(raw)
            repl, st = tr.plan("ps3", cp, rel.replace("\\", "/"), texts_of(plain))
            out, n = apply(plain, repl, "ps3", tr)
        except Exception as e:  # noqa: BLE001
            report["fail"].append(f"{key}: {e}")
            print(f"  [실패] {key}: {e}")
            continue
        if not n:
            continue
        new = out if (args.plain or ctx is None) else Cipher.encrypt(out, ctx)
        if not args.plain and ctx is not None:      # 게이트: 재복호화 = 주입 평문
            back, _ = c.decrypt(new)
            assert back[:len(out)] == out and not back[len(out):].strip(b"\x00"), f"재암호화 검증 실패 {key}"
        dst = os.path.join(PS3_OUT, cp, "resource", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(new)
        tot.update(st)
        tot["파일"] += 1
        report["files"].append({"key": key, "repl": n, "how": dict(st), "orig_sha256": mani[key],
                                "new_sha256": sha(new), "size": len(new)})
        print(f"  {key}: {n}칸 ({dict(st)}) {len(raw):,}→{len(new):,}B")
    mimg = ps3_snapshot_img()

    def wps3(cp, rel, new, info):
        dst = os.path.join(PS3_OUT, cp, "resource", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(new)
        report["files"].append({"key": f"{cp}/{rel}", "image": info, "orig_sha256": mimg[f"{cp}/{rel}"],
                                "new_sha256": sha(new), "size": len(new)})
    cps = sorted({k.split("/", 1)[0] for k in mimg})
    it = []
    for cp in cps:
        res = os.path.join(PS3_ORIG, cp, "resource")

        def rd(rel, cp=cp):
            raw = open(os.path.join(PS3_ORIG, cp, "resource", rel), "rb").read()
            assert sha(raw) == mimg[f"{cp}/{rel}"], f"그림 순정 백업 변형: {cp}/{rel}"
            return raw
        it.append((cp, res, rd))
    ni, fi = build_images("ps3", it, wps3, print)
    report["fail"] += fi
    tot["그림파일"] = ni
    report["font_missing"] = "".join(sorted(tr.missing))
    os.makedirs(PS3_OUT, exist_ok=True)
    json.dump(report, open(os.path.join(PS3_OUT, "_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nPS3 {'평문' if args.plain else '재암호화'}본: 파일 {tot['파일']}개 {dict(tot)} / "
          f"실패 {len(report['fail'])} → {PS3_OUT}")
    if tr.missing:
        print(f"[경고] 폰트 매핑에 없는 한글 {len(tr.missing)}자: {''.join(sorted(tr.missing))}")
    return 1 if report["fail"] else 0


def rpcs3_running():
    import subprocess
    out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout.lower()
    return "rpcs3.exe" in out


def deploy_ps3(_args):
    if rpcs3_running():
        sys.exit("[중단] RPCS3 실행 중 — 종료 후 다시")
    rep = json.load(open(os.path.join(PS3_OUT, "_report.json"), encoding="utf-8"))
    if rep["fail"]:
        sys.exit("[중단] build-ps3 실패 항목 있음")
    mani = ps3_manifest()
    for it in rep["files"]:                       # 게이트: 대상이 순정이거나 이전 배포본일 것
        live = os.path.join(PS3_DLC, it["key"].split("/", 1)[0], "resource", it["key"].split("/", 1)[1])
        cur = sha(open(live, "rb").read())
        src = os.path.join(PS3_OUT, it["key"].split("/", 1)[0], "resource", it["key"].split("/", 1)[1])
        assert sha(open(src, "rb").read()) == it["new_sha256"], f"산출물 변형 {it['key']}"
        if cur != mani[it["key"]]:
            print(f"  (이전 배포본 교체) {it['key']}")
    for it in rep["files"]:
        cp, rel = it["key"].split("/", 1)
        shutil.copy2(os.path.join(PS3_OUT, cp, "resource", rel), os.path.join(PS3_DLC, cp, "resource", rel))
    json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "files": rep["files"], "plain": rep["plain"]},
              open(os.path.join(PS3_ORIG, "deployed.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(rep['files'])}개 배포 → {PS3_DLC} (되돌리기: restore-ps3)")


def restore_ps3(_args):
    if rpcs3_running():
        sys.exit("[중단] RPCS3 실행 중 — 종료 후 다시")
    mani = ps3_manifest()
    n = 0
    for key, h in mani.items():
        cp, rel = key.split("/", 1)
        live = os.path.join(PS3_DLC, cp, "resource", rel)
        if sha(open(live, "rb").read()) != h:
            shutil.copy2(os.path.join(PS3_ORIG, cp, "resource", rel), live)
            n += 1
    print(f"순정 복원 {n}개")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build360", "coverage", "roundtrip", "build-ps3", "deploy-ps3", "restore-ps3"])
    ap.add_argument("--plain", action="store_true", help="build-ps3: 재암호화 대신 평문 산출")
    a = ap.parse_args()
    return {"build360": build360, "coverage": coverage, "roundtrip": roundtrip, "build-ps3": build_ps3,
            "deploy-ps3": deploy_ps3, "restore-ps3": restore_ps3}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
