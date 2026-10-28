#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹앱 회수분 → PC 포트(360 리소스) 적용: 이미지 작업본 + 내장/단독 XMB 번역

360 파일은 PS3와 다르다(텍스처 'NTXR' 바이트스왑·360 전용 포맷 코드) → PS3
patched/ 산출물을 복사하면 안 됨(§26: PS3 산출물 복사 = 크래시 전례).
이 도구는 PC 포트 원본(암호화)의 **사본을 복호화**해서 직접 주입한다.

텍스처: PS3 jp/<rel>_<n>.png(원본 덤프)와 360 원 페이로드를 후보 디코더로 풀어
가장 일치하는 방식(바이트스왑/포맷)을 텍스처마다 자동 판별(원본 일치 PSNR≥30
필수) → 같은 방식의 역변환으로 kr/ 작업본 인코드 → 재디코드 게이트(≥33dB,
inject_image_text.PSNR_OVERRIDES 예외 공유). 크기·치수 불변, 제자리 덮기.
XMB: xmb_translations.json의 키(text/install.xmb, ranker/ranker_npc.xmb,
scene/exep_init.mpc=NPC 명단 — 360에선 여러 pac에 같은 표가 복제)를 원시 한글
(직접 등록 체제, 매핑 미적용)로. 내장 XMB가 커지면 pac 재조립(엔트리 시프트,
테이블·헤더 크기합 갱신, 비대상 엔트리 바이트 불변 검증).
가사(dance pac)는 dance_lyrics.py가 따로 담당.

  python pcport_apply.py build     # out_pcport/ 생성 + 검증 (게임 폴더 불변)
  python pcport_apply.py deploy    # **game_kor 사본에만** 교체 (+patched_dance 가사)

배포 대상 (2026-10-22 리컴파일 감독 합의): build_imas2_o2\\game은 모든 세션의
회귀 기준선이므로 절대 교체하지 않는다. imas2pc\\game_kor(통째 사본)에만 주입하고
실행은 IMAS2PC_DISC_ROOT=...\\game_kor 로 한다. 읽기 원본은 공유 game(불변).
산출물·사본은 git/zip/공유노트에 넣지 않는다(저작권).
"""
import os
import sys
import json
import time
import shutil
import struct
import hashlib
import argparse
import subprocess

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT, IMAS2DEC, walk_nuts, decode_texture  # noqa: E402
from inject_image_text import encode_texture, psnr, PSNR_OVERRIDES  # noqa: E402
from xmb_text import parse_xmb, collect_texts, rebuild_xmb  # noqa: E402
from dlc_images import swap16  # noqa: E402
import tile_banner as TB  # noqa: E402

PORT = r"C:\Users\jackfilm\Desktop\imas2pc\build_imas2_o2\game\resource"   # 읽기 전용 원본
KOR_ROOT = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor"                    # 배포 대상 사본
KOR_RES = os.path.join(KOR_ROOT, "resource")
LOCK = r"C:\Users\jackfilm\Desktop\imas2pc\gpu_run.lock"
PATCHED_DANCE = os.path.join(OUT_DEFAULT, "patched_dance")
CACHE = os.path.join(OUT_DEFAULT, "_cache", "pcport")
OUT = os.path.join(OUT_DEFAULT, "out_pcport")
KR = os.path.join(OUT_DEFAULT, "kr")
JPD = os.path.join(OUT_DEFAULT, "jp")
NPC_PREFIX = ("NPCP_", "NPCU_", "NPCS_", "PROD_")
SR_LAYOUT = {"interface\\swg\\ProStaffRoll.tsk": "main"}     # 360판엔 류구 스태프롤(exep_staff_roll) 없음


def sha(b):
    return hashlib.sha256(b).hexdigest()


def decrypt_port(rel):
    """PC 포트 원본 사본을 복호화(캐시). 원본 불변."""
    src = os.path.join(PORT, rel)
    dst = os.path.join(CACHE, rel.replace("\\", "__"))
    if not os.path.exists(dst):
        os.makedirs(CACHE, exist_ok=True)
        shutil.copy2(src, dst)
        if open(dst, "rb").read(4) not in (b"pac\x00", b"XMB ", b"TSK ", b"NTXR", b"NTP3"):
            pr = subprocess.Popen([IMAS2DEC, dst], cwd=CACHE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            for _ in range(1200):
                if os.path.exists(dst + ".dec") and os.path.getsize(dst + ".dec") > 0:
                    time.sleep(0.5)
                    break
                time.sleep(0.1)
            try:
                pr.kill()
            except OSError:
                pass
            if not os.path.exists(dst + ".dec"):
                raise RuntimeError(f"복호화 실패: {rel}")
            os.replace(dst + ".dec", dst)
    return open(dst, "rb").read()


# ---------------------------------------------------------------- 텍스처 코덱 후보

def _dec_1555(raw, w, h):
    v = np.frombuffer(raw[:w * h * 2], ">u2").reshape(h, w).astype(np.uint32)
    o = np.zeros((h, w, 4), np.uint8)
    o[..., 0] = ((v >> 10) & 31) * 255 // 31
    o[..., 1] = ((v >> 5) & 31) * 255 // 31
    o[..., 2] = (v & 31) * 255 // 31
    a = np.where(v >> 15, 255, 0)
    o[..., 3] = a if a.any() else 255
    return o


def _enc_1555(img):
    f = img.astype(np.float32)
    r = np.clip(np.round(f[..., 0] * 31 / 255), 0, 31).astype(np.uint16)
    g = np.clip(np.round(f[..., 1] * 31 / 255), 0, 31).astype(np.uint16)
    b = np.clip(np.round(f[..., 2] * 31 / 255), 0, 31).astype(np.uint16)
    a = (img[..., 3] >= 128).astype(np.uint16)
    return ((a << 15) | (r << 10) | (g << 5) | b).astype(">u2").tobytes()


def candidates(fmt):
    """(이름, dec(raw,w,h), enc(img)) — 360 헤더 fmt 코드별."""
    out = []
    ps3 = {0: "DXT1", 1: "DXT3", 2: "DXT5"}
    if fmt in ps3:
        nm = ps3[fmt]
        out.append((f"{nm}+swap16",
                    lambda r, w, h, f=fmt: decode_texture(f, swap16(r), w, h),
                    lambda im, nm=nm: swap16(encode_texture(nm, im))))
        out.append((f"{nm}",
                    lambda r, w, h, f=fmt: decode_texture(f, r, w, h),
                    lambda im, nm=nm: encode_texture(nm, im)))
    if fmt in (14, 17, 19):
        out.append(("ARGB32", lambda r, w, h: decode_texture(14, r, w, h),
                    lambda im: encode_texture("ARGB32", im)))
        out.append(("ARGB32+swap16", lambda r, w, h: decode_texture(14, swap16(r), w, h),
                    lambda im: swap16(encode_texture("ARGB32", im))))
        out.append(("BGRA32",
                    lambda r, w, h: np.frombuffer(r[:w * h * 4], np.uint8)
                    .reshape(h, w, 4)[..., [2, 1, 0, 3]].copy(),
                    lambda im: im[..., [2, 1, 0, 3]].tobytes()))
        out.append(("RGBA32",
                    lambda r, w, h: np.frombuffer(r[:w * h * 4], np.uint8).reshape(h, w, 4).copy(),
                    lambda im: im.tobytes()))
    if fmt in (6, 10):
        out.append(("ARGB1555", _dec_1555, _enc_1555))   # PS3 fmt 6도 1555(RGB565 후보는 오판이라 뺌)
    if fmt in (7, 11):
        out.append(("ARGB4444", lambda r, w, h: decode_texture(7, r, w, h),
                    lambda im: encode_texture("ARGB4444", im)))
    return out


def kr_jobs():
    """kr/<reldir>/<stem>_<nnn>.png → {rel: [(n, path)]} (PS3 상대경로 = 포트 상대경로)."""
    import re
    idx = json.load(open(os.path.join(OUT_DEFAULT, "index.json"), encoding="utf-8"))
    by = {}
    pat = re.compile(r"^(.+)_(\d{3})\.png$")
    for dp, _d, fns in os.walk(KR):
        reldir = os.path.relpath(dp, KR)
        reldir = "" if reldir == "." else reldir
        for fn in fns:
            m = pat.match(fn)
            if not m:
                continue
            hit = next((rel for rel in idx if os.path.dirname(rel) == reldir
                        and os.path.splitext(os.path.basename(rel))[0] == m.group(1)), None)
            if hit:
                by.setdefault(hit, []).append((int(m.group(2)), os.path.join(dp, fn)))
    # index.json 밖 파일의 그림(image_extra.json — initialFix 확인창 はい/いいえ 등). jp/·kr/ 이름 규칙은 같다.
    ex = os.path.join(HERE, "image_extra.json")
    if os.path.exists(ex):
        for it in json.load(open(ex, encoding="utf-8"))["items"]:
            if it["rel"] in idx:
                continue
            stem = os.path.splitext(os.path.basename(it["rel"]))[0]
            p = os.path.join(KR, os.path.dirname(it["rel"]), f"{stem}_{it['n']:03d}.png")
            if os.path.exists(p) and (it["n"], p) not in by.get(it["rel"], []):
                by.setdefault(it["rel"], []).append((it["n"], p))
    return by


def apply_textures(rel, data, jobs, log, unmatched):
    """PS3 텍스처 n ↔ 360 텍스처는 **번호가 아니라 내용으로** 짝짓는다(360판은 텍스처
    순서·구성이 다른 파일이 있음). 같은 치수의 360 텍스처 전부를 후보 디코더로 풀어
    PS3 원본 덤프와 가장 닮은 것(≥30dB)을 고른다. 없으면 360판 내용이 다른 것
    (예: 튜토리얼의 Xbox 버튼 그림) → 적용하지 않고 unmatched에 기록."""
    data = bytearray(data)
    t360 = walk_nuts(bytes(data).replace(b"NTXR", b"NTP3"), lambda *a: None)
    stem = os.path.splitext(os.path.basename(rel))[0]
    used = set()
    done = 0
    for n, png in sorted(jobs):
        jp_png = os.path.join(JPD, os.path.dirname(rel), f"{stem}_{n:03d}.png")
        ref = np.asarray(Image.open(jp_png).convert("RGBA"), np.uint8)
        best = None
        for k, t in enumerate(t360):
            if k in used or (t["h"], t["w"]) != ref.shape[:2]:
                continue
            raw = bytes(data[t["data_off"]:t["data_off"] + t["data_size"]])
            for name, dec, enc in candidates(t["fmt"]):
                try:
                    p = psnr(dec(raw, t["w"], t["h"]), ref)
                except Exception:  # noqa: BLE001
                    continue
                if best is None or p > best[0]:
                    best = (p, name, dec, enc, k, t, raw)
        if best is None or best[0] < 30:
            why = "같은 치수 텍스처 없음" if best is None else f"최고 일치 {best[0]:.1f}dB"
            unmatched.append(f"{rel}#{n:03d} ({ref.shape[1]}x{ref.shape[0]}): 360판에 같은 그림 없음 — {why}")
            log(f"    [미적용] PS3 #{n:03d}: 360판 대응 없음 ({why})")
            continue
        _p, name, dec, enc, k, t, raw = best
        used.add(k)
        img = np.asarray(Image.open(png).convert("RGBA"), np.uint8)
        if img.shape[:2] != (t["h"], t["w"]):
            raise ValueError(f"{rel}#{n}: 작업본 치수 불일치")
        new = enc(img)
        if len(new) < t["data_size"]:          # 밉 없는 상위 1장만 — 나머지(밉)는 원본 유지
            new = new + raw[len(new):]
        if len(new) != t["data_size"]:
            raise ValueError(f"{rel}#{n}: 인코드 크기 {len(new)} != {t['data_size']}")
        q = psnr(dec(new, t["w"], t["h"]), img)
        ov = PSNR_OVERRIDES.get(f"{rel}#{n:03d}")
        lim = ov["min"] if ov else 33.0
        if q < lim:
            raise ValueError(f"{rel}#{n}: 재디코드 {q:.1f}dB < {lim}")
        data[t["data_off"]:t["data_off"] + t["data_size"]] = new
        done += 1
        log(f"    PS3#{n:03d}→360#{k:03d} fmt{t['fmt']}/{name} 원본일치 {_p:.0f}dB, 작업본 {q:.1f}dB")
    return bytes(data), done


KR_X360 = os.path.join(OUT_DEFAULT, "kr_x360")
X360_ONLY = os.path.join(OUT_DEFAULT, "x360_only")


def x360_jobs():
    """360판 전용 그림 작업본(kr_x360/<경로_밑줄>_<nnn>.png, webapp_pull) → {rel: [(360 텍스처 번호, png)]}.
    번호는 360판 텍스처 순번 그대로(PS3 짝 없음). 경로는 포트 원본 트리에서 밑줄 이름이 같은 파일로 찾는다."""
    import re
    if not os.path.isdir(KR_X360):
        return {}
    under = {}
    for dp, _d, fns in os.walk(PORT):
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), PORT)
            under[rel.replace("\\", "_").rsplit(".", 1)[0]] = rel
    by = {}
    for fn in os.listdir(KR_X360):
        m = re.match(r"^(.+)_(\d{3})\.png$", fn)
        if m and m.group(1) in under:
            by.setdefault(under[m.group(1)], []).append((int(m.group(2)), os.path.join(KR_X360, fn)))
    return by


def apply_x360(rel, data, jobs, log):
    """360 전용 그림 주입: 원본 덤프(x360_only/)와 360 원 페이로드가 ≥30dB로 맞는 코덱으로 인코드, 재디코드 ≥33dB."""
    data = bytearray(data)
    t360 = walk_nuts(bytes(data).replace(b"NTXR", b"NTP3"), lambda *a: None)
    done = 0
    for n, png in sorted(jobs):
        t = t360[n]
        ref_p = os.path.join(X360_ONLY, f"{rel.replace(os.sep, '_')}_{n:03d}.png")
        ref = np.asarray(Image.open(ref_p).convert("RGBA"), np.uint8)
        raw = bytes(data[t["data_off"]:t["data_off"] + t["data_size"]])
        best = None
        for name, dec, enc in candidates(t["fmt"]):
            try:
                p = psnr(dec(raw, t["w"], t["h"]), ref)
            except Exception:  # noqa: BLE001
                continue
            if best is None or p > best[0]:
                best = (p, name, dec, enc)
        if best is None or best[0] < 30:
            raise ValueError(f"{rel}#{n}: 360 원본과 덤프가 맞는 코덱 없음")
        _p, name, dec, enc = best
        img = np.asarray(Image.open(png).convert("RGBA"), np.uint8)
        if img.shape[:2] != (t["h"], t["w"]):
            raise ValueError(f"{rel}#{n}: 360 작업본 치수 불일치")
        new = enc(img)
        new = new + raw[len(new):] if len(new) < t["data_size"] else new
        if len(new) != t["data_size"]:
            raise ValueError(f"{rel}#{n}: 인코드 크기 {len(new)} != {t['data_size']}")
        q = psnr(dec(new, t["w"], t["h"]), img)
        if q < 33:
            raise ValueError(f"{rel}#{n}: 재디코드 {q:.1f}dB < 33")
        data[t["data_off"]:t["data_off"] + t["data_size"]] = new
        done += 1
        log(f"    360전용#{n:03d} fmt{t['fmt']}/{name} 원본일치 {_p:.0f}dB, 작업본 {q:.1f}dB")
    return bytes(data), done


# ---------------------------------------------------------------- XMB

def parse_pac(data):
    cnt = struct.unpack_from(">H", data, 0x20)[0]
    ents = []
    for i in range(cnt):
        off = 0x40 + i * 32
        size, ofs = struct.unpack_from(">II", data, off + 8)
        ents.append({"i": i, "tbl": off, "size": size, "ofs": ofs})
    # 데이터 시작은 헤더 +0x38. (파일 길이 - 마지막 항목 끝)으로 구하면 꼬리 패딩(4~28B)이 있는
    # 파일에서 어긋난다 — 360 원본 pac 155개 중 53개(2026-10-23 확인).
    ds = struct.unpack_from(">I", data, 0x38)[0]
    return ents, ds


def rebuild_pac(data, ents, ds, repl_blobs):
    parts, tbl, pos = [], [], 0
    for e in sorted(ents, key=lambda x: x["ofs"]):
        blob = repl_blobs.get(e["i"], data[ds + e["ofs"]: ds + e["ofs"] + e["size"]])
        tbl.append((e["tbl"], len(blob), pos))
        pad = (-len(blob)) % 16
        parts += [blob, b"\x00" * pad]
        pos += len(blob) + pad
    out = bytearray(data[:ds]) + b"".join(parts)
    lt = max(tbl, key=lambda t: t[2])
    old_end = ds + max(e["ofs"] + e["size"] for e in ents)
    out = out[:ds + lt[2] + lt[1]] + data[old_end:]      # 원본 꼬리 바이트 보존
    for t, size, ofs in tbl:
        struct.pack_into(">II", out, t + 8, size, ofs)
    struct.pack_into(">I", out, 0x08, sum(s for _, s, _ in tbl))
    return bytes(out)


def xmb_repl_for(texts, kr_by_id):
    repl = {}
    for t in texts:
        s = kr_by_id.get(t["id"])
        if s:
            repl[t["attr"]] = s
    return repl


NPC_X360_KEY = "scene/exep_init.mpc@x360"   # 360판에서 같은 id에 다른 이름이 든 칸 (웹앱 키 x360:<id>)


def npc_kr_for(texts, tr):
    """NPC 명단 표 → {id: kr}. 360판은 43개 id의 원문이 PS3와 다르다(NPCP_123 フィガロ→リョウコ姫 등) —
    id만 보고 PS3 번역을 넣으면 엉뚱한 이름이 된다. 원문 일치 PS3 번역 > 360 전용 번역(원문 일치) >
    같은 원문의 다른 id 번역(다수결) 순, 없으면 일본어 그대로 둔다."""
    ps3 = tr.get("scene/exep_init.mpc", {})
    x360 = tr.get(NPC_X360_KEY, {})
    byjp = {}
    for v in ps3.values():
        if v.get("kr"):
            byjp.setdefault(v.get("jp"), {}).setdefault(v["kr"], 0)
            byjp[v.get("jp")][v["kr"]] += 1
    out = {}
    for t in texts:
        p, x = ps3.get(t["id"], {}), x360.get(t["id"], {})
        if p.get("kr") and p.get("jp") == t["text"]:
            out[t["id"]] = p["kr"]
        elif x.get("kr") and x.get("jp") == t["text"]:
            out[t["id"]] = x["kr"]
        elif t["text"] in byjp:
            c = byjp[t["text"]]
            out[t["id"]] = max(c, key=c.get)
    return out


def apply_xmb(rel, data, tr, log):
    """단독 XMB면 그대로, pac이면 NPC 명단 XMB(들)를 교체."""
    if data[:4] == b"XMB ":
        key = rel.replace("\\", "/")
        kr = {k: v["kr"] for k, v in tr.get(key, {}).items() if v.get("kr")}
        repl = xmb_repl_for(collect_texts(parse_xmb(data, 0)), kr)
        if not repl:
            return data, 0
        return rebuild_xmb(data, 0, repl, lambda *a: None, allow_grow=True), len(repl)
    if data[:4] != b"pac\x00":
        return data, 0
    ents, ds = parse_pac(data)
    blobs, npcs, n = {}, {}, 0
    for e in ents:
        seg = data[ds + e["ofs"]: ds + e["ofs"] + e["size"]]
        if seg[:4] != b"XMB ":
            continue
        try:
            texts = collect_texts(parse_xmb(seg, 0))
        except Exception:  # noqa: BLE001
            continue
        if not any(t["id"].startswith(NPC_PREFIX) for t in texts):
            continue
        npc = npc_kr_for(texts, tr)
        npcs[e["i"]] = npc
        repl = xmb_repl_for(texts, npc)
        if repl:
            blobs[e["i"]] = rebuild_xmb(seg, 0, repl, lambda *a: None, allow_grow=True)
            n += len(repl)
    if not blobs:
        return data, 0
    out = rebuild_pac(data, ents, ds, blobs)
    # 검증: 비대상 엔트리 바이트 불변 + 대상 재파싱
    ents2, ds2 = parse_pac(out)
    for e, e2 in zip(sorted(ents, key=lambda x: x["i"]), sorted(ents2, key=lambda x: x["i"])):
        a = data[ds + e["ofs"]: ds + e["ofs"] + e["size"]]
        b = out[ds2 + e2["ofs"]: ds2 + e2["ofs"] + e2["size"]]
        if e["i"] in blobs:
            got = {t["id"]: t["text"] for t in collect_texts(parse_xmb(b, 0))}
            for tid, s in npcs[e["i"]].items():
                if tid in got:
                    assert got[tid] == s, f"{rel}: {tid} 불일치"
        else:
            assert a == b, f"{rel}: 엔트리 {e['i']} 변형"
    log(f"    XMB NPC 명단 {len(blobs)}개 표, {n}칸 교체 ({len(data):,}→{len(out):,}B)")
    return out, n


# ---------------------------------------------------------------- build / deploy

def build():
    tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    jobs = kr_jobs()
    xjobs = x360_jobs()                    # 360판 전용 그림(kr_x360/) — 2026-10-23 전까지 주입 경로가 없었다
    targets = set(jobs) | set(xjobs)
    targets |= {"text\\install.xmb", "ranker\\ranker_npc.xmb"}
    # 곡 정보 가사 XMB(songinfo/<곡>/lyrics_<곡>.xmb) — 레슨(가사 미니게임)이 dance pac이 아니라 이 사본을 읽는다
    # (2026-10-23 ps3-360-pc 확인: 360 레슨 가사가 일본어). xmb_translations.json에 키가 있는 곡만.
    import glob as _g
    for p in _g.glob(os.path.join(PORT, "songinfo", "*", "lyrics_*.xmb")):
        rel = os.path.relpath(p, PORT)
        if rel.replace("\\", "/") in tr:
            targets.add(rel)
    # NPC 명단 표가 들어있는 pac (PS3 전수 조사 기준 위치)
    targets |= {"game\\alf\\alf_common.mpc", "interface\\NationwideRanking.mpc",
                "interface\\ScheduleSelect.mpc", "scene\\produce_etc.mpc",
                "scene\\exep_commu.mpc", "scene\\exep_init.mpc"}
    targets |= set(TB.DIRECT)            # 레슨 결과 배너 상주 사본(gscript\adv_common.mpc)
    targets |= set(SR_LAYOUT)            # 스태프롤 이름 칸 간격(staffroll_layout.py, SWG 행렬 제자리)
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    report = {"ok": [], "skip": [], "fail": [], "unmatched": []}
    for rel in sorted(targets):
        if not os.path.exists(os.path.join(PORT, rel)):
            report["skip"].append(f"{rel}: PC 포트에 없음(360판 미포함)")
            continue
        if rel.lower().endswith(".s2d"):
            # 360판 s2d는 imas2dec 미지원 형식(선두 0F F5 12 ED — 압축 추정). 별도 과제.
            report["skip"].append(f"{rel}: 360 s2d 복호화 미지원(별도 조사 필요)")
            continue
        print(f"▶ {rel}")
        try:
            data = decrypt_port(rel)
            orig = data
            n_tex = n_x = n_b = 0
            if rel in jobs:
                data, n_tex = apply_textures(rel, data, jobs[rel], print, report["unmatched"])
            if rel in xjobs:
                data, n_xt = apply_x360(rel, data, xjobs[rel], print)
                n_tex += n_xt
            if rel in TB.RELS:      # 레슨·커뮤 결과 배너: 타일은 위 텍스처로, 칸 배정은 SWG(tile_banner.py)
                data, n_b = TB.patch_container(data, orig=orig, log=print, with_tiles=rel in TB.DIRECT)
            n_l = 0
            if rel in SR_LAYOUT:    # 스태프롤 이름 칸 간격 10px(행렬 x만, 같은 크기)
                import staffroll_layout as SL
                new = SL.relayout(data, SR_LAYOUT[rel])
                n_l, data = int(new != data), new
                print(f"    스태프롤 칸 간격 재배치 {'적용' if n_l else '변경 없음'}")
            data, n_x = apply_xmb(rel, data, tr, print)
            if n_tex + n_x + n_b + n_l == 0:
                report["skip"].append(f"{rel}: 적용할 번역 없음")
                continue
            dst = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
            report["ok"].append({"rel": rel, "tex": n_tex, "xmb": n_x, "size": len(data),
                                 "sha256": sha(data)})
        except Exception as e:  # noqa: BLE001
            print(f"    [실패] {e}")
            report["fail"].append(f"{rel}: {e}")
    json.dump(report, open(os.path.join(OUT, "_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n성공 {len(report['ok'])} / 스킵 {len(report['skip'])} / 실패 {len(report['fail'])}"
          f" / 360판 대응 없는 텍스처 {len(report['unmatched'])}")
    for s in report["unmatched"]:
        print("  [미적용]", s)
    for s in report["skip"]:
        print("  [스킵]", s)
    for s in report["fail"]:
        print("  [실패]", s)
    return report


def game_kor_busy(other_disc_ok=False):
    """game_kor를 쓰는 게임이 돌고 있으면 사유 문자열, 아니면 None.
    other_disc_ok: gpu_run.lock이 있어도 잠금 주인의 로그·실행 중 프로세스 명령줄·환경 어디에도 game_kor가 없으면
    허용(다른 디스크로 도는 런 — KOR 판단으로만 쓴다, 2026-10-23)."""
    if os.path.exists(LOCK) and not other_disc_ok:
        return f"{LOCK} 존재 — 게임 실행 중"
    if os.path.exists(LOCK) and "game_kor" in open(LOCK, encoding="utf-8", errors="replace").read():
        return "잠금 주인이 game_kor 사용"
    out = os.popen('powershell -NoProfile -Command "Get-CimInstance Win32_Process | '
                   'Where-Object { $_.CommandLine -match \'game_kor\' -and $_.Name -notmatch \'python|powershell|cmd|conhost|bash\' } | '
                   'ForEach-Object { $_.Name }"').read().strip()
    if out:
        return f"game_kor를 명령줄에 쓰는 프로세스: {out}"
    return None


def deploy(other_disc_ok=False):
    why = game_kor_busy(other_disc_ok)
    if why:
        sys.exit(f"[중단] {why}. 끝난 뒤 다시.")
    if not os.path.isdir(KOR_RES):
        sys.exit(f"[중단] 사본 없음: {KOR_RES} — build_imas2_o2\\game을 통째 복사 먼저")
    rep = json.load(open(os.path.join(OUT, "_report.json"), encoding="utf-8"))
    if rep["fail"]:
        sys.exit("[중단] build 실패 항목 있음")
    items = [dict(it, src=os.path.join(OUT, it["rel"])) for it in rep["ok"]]
    for p in sorted(os.listdir(PATCHED_DANCE)) if os.path.isdir(PATCHED_DANCE) else []:
        b = open(os.path.join(PATCHED_DANCE, p), "rb").read()
        items.append({"rel": os.path.join("dance", p), "sha256": sha(b),
                      "src": os.path.join(PATCHED_DANCE, p)})
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(os.path.dirname(KOR_ROOT), f"game_kor_backup_{stamp}")
    mani = []
    for it in items:
        rel = it["rel"]
        src = it["src"]
        dst = os.path.join(KOR_RES, rel)
        b = os.path.join(bdir, rel)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(dst, b)
        orig_sha = sha(open(b, "rb").read())
        shutil.copy2(src, dst)
        assert sha(open(dst, "rb").read()) == it["sha256"]
        mani.append({"rel": rel, "orig_sha256": orig_sha, "new_sha256": it["sha256"]})
        print(f"배포: {rel}")
    json.dump(mani, open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8"), indent=1)
    print(f"{len(mani)}개 배포 → {KOR_RES}\n백업·매니페스트: {bdir}")
    print("실행: IMAS2PC_DISC_ROOT=" + KOR_ROOT + " (공유 game은 불변)")
    print("⚠ 이 도구는 대상 파일을 360 원본에서 다시 만든다 — 게임 데이터 텍스트가 빠질 수 있으니 "
          "이어서 `python gamedata_apply.py build --code <팀암호>` → validate → deploy를 다시 실행")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "deploy"])
    ap.add_argument("--other-disc-ok", action="store_true",
                    help="gpu_run.lock 주인이 game_kor가 아닌 디스크로 돌 때(KOR 확인 후)만")
    a = ap.parse_args()
    build() if a.cmd == "build" else deploy(a.other_disc_ok)


if __name__ == "__main__":
    main()
