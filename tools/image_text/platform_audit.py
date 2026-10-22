#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹앱 번역 대상의 PS3 / 360 플랫폼 전수 점검 (2026-10-23, KOR·사용자 "360/ps3용 다 들어가 있어? 구분도")

웹앱 rows 전부(script·xmb·gamedata·image·dlc)를 PS3 원본·360 원본과 대조해
  - 각 행의 플랫폼 태그 meta.plat = "common" | "ps3" | "x360" (+ meta.plat_note)
  - 웹앱에 빠진 번역 대상(360 전용 XMB 텍스트, PS3 전용 DLC 가사, 360 전용 텍스처 등)
을 계산한다. 원본은 전부 읽기 전용(360은 메모리 복호화, PS3는 기존 추출 캐시).

  python platform_audit.py scan            # platform_audit.json + 보고(쓰기 없음)
  python platform_audit.py apply --code <팀암호> [--service-key <sb_secret>]
        # meta.plat 갱신(kr/st/ts/by는 보내지 않음 → 팀 번역 보존) + 빠진 행 추가(ignore-duplicates)
        # service key는 새 이미지 썸네일 업로드에만 사용, 저장 안 함
"""
import os
import re
import sys
import json
import struct
import hashlib
import argparse
import collections
import urllib.request
import urllib.error

import numpy as np
from Crypto.Cipher import AES

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scb"))
from extract_image_text import JP_ROOT, OUT_DEFAULT  # noqa: E402
from xmb_text import parse_xmb, collect_texts  # noqa: E402
import game_xmb  # noqa: E402

CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
X360 = r"C:\Users\jackfilm\Desktop\unpack\imas2\resource"          # 360 원본 추출본(읽기 전용)
X360_DLC = r"C:\Users\jackfilm\Desktop\imas2dlc\content\4E4D0817\00000002"
PS3_DLC = os.path.join(os.path.dirname(JP_ROOT), "dlc")              # NPJB00337\USRDIR\dlc
TABLE360 = os.path.join(JP_ROOT, "gscript", "imas2dec", "imas2dec", "table360.bin")
TABLE_PS3 = os.path.join(JP_ROOT, "gscript", "imas2dec", "imas2dec", "table.bin")
AUDIT = os.path.join(HERE, "platform_audit.json")
MAGIC = (b"pac\x00", b"XMB ", b"TSK ", b"NTXR", b"NTP3", b"NUS3", b"\x1bLua", b"S2D ", b"MPK ")

_T = {}


def _table(p):
    if p not in _T:
        _T[p] = open(p, "rb").read()
    return _T[p]


def _derive(t, a, b, c):
    o0, o1, i0, i1 = ((a >> 4) & 15) * 24, (a & 15) * 24, b % 24, c % 24
    k = bytearray(24)
    for i in range(24):
        k[i] = t[o0 + i0] ^ t[o1 + i1]
        i0, i1 = (i0 + 1) % 24, (i1 + 1) % 24
    return bytes(k)


def dec_any(raw, plat):
    """평문이면 그대로, 아니면 AES(360: table360·풋터32 / PS3: table·풋터64, DLC는 표 오프셋 변형).
    알려진 매직이 나오면 반환, 아니면 None(예: 360 .s2d)."""
    if raw[:4] in MAGIC:
        return raw
    tries = [(_table(TABLE360), 32)] if plat == "x360" else \
        [(_table(TABLE_PS3)[o:o + 384], 64) for o in (0, 384, 768)]
    n = len(raw)
    for t, foot in tries:
        try:
            key = _derive(t, raw[n - 31], raw[n - 30], raw[n - 29])
            body = raw[:n - foot]
            body = body[:len(body) - len(body) % 16]
            out = AES.new(key, AES.MODE_CBC, b"\x00" * 16).decrypt(body)[16:]
        except Exception:  # noqa: BLE001
            continue
        if out[:4] in MAGIC:
            return out
    return None


def fetch_rows(cats=("script", "xmb", "gamedata", "image", "dlc", "exe")):
    """분류별로 나눠 읽는다(전체 order=id 한 번은 meta가 커진 뒤 문장 시간 제한으로 500)."""
    rows = []
    for c in cats:
        off = 0
        while True:
            r = urllib.request.Request(
                f"{CFG['url']}/rest/v1/rows?select=*&cat=eq.{c}&order=id&limit=1000&offset={off}",
                headers={"apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}",
                         "x-team-code": "w@ldo"})
            for attempt in range(3):
                try:
                    ch = json.load(urllib.request.urlopen(r))
                    break
                except urllib.error.HTTPError:
                    if attempt == 2:
                        raise
                    import time
                    time.sleep(3)
            rows += ch
            if len(ch) < 1000:
                break
            off += 1000
    return rows


# ---------------------------------------------------------------- 360 XMB 텍스트

def iter_360_sources():
    """game_xmb.iter_sources와 같은 범위(평문/암호 mpc, TSK_DIRS의 tsk)를 360 트리에서."""
    for dp, dns, fns in os.walk(X360):
        rel_dir = os.path.relpath(dp, X360)
        top = rel_dir.split(os.sep)[0]
        dns[:] = [d for d in dns if d not in game_xmb.SKIP_DIRS and not d.startswith("_")]
        for fn in sorted(fns):
            low = fn.lower()
            if not (low.endswith(".mpc") or (low.endswith(".tsk") and top in game_xmb.TSK_DIRS)):
                continue
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            d = dec_any(open(os.path.join(dp, fn), "rb").read(), "x360")
            if d is None:
                yield rel, None
            else:
                yield rel, d


def scan_gamedata(rows):
    """웹앱 gamedata 행(PS3에서 추출) ↔ 360 XMB 텍스트."""
    ents360 = {}          # (tid, text) → [loc]
    by_tid = collections.defaultdict(set)
    texts360 = set()
    undec = []
    for rel, d in iter_360_sources():
        if d is None:
            undec.append(rel)
            continue
        for xi, ents in game_xmb.xmb_entries(d):
            for tid, chain, owner, field, text in ents:
                if tid.split("_")[0] in game_xmb.EXCLUDE_IDPFX:
                    continue
                loc = f"{rel.replace(os.sep, '/')}#x{xi}"
                ents360.setdefault((tid, text), {"locs": [], "chain": chain, "owner": owner,
                                                 "field": field})["locs"].append(loc)
                by_tid[tid].add(text)
                texts360.add(text)
    plat, notes = {}, {}
    web_texts = set()
    gd = [r for r in rows if r["cat"] == "gamedata"]
    for r in gd:
        web_texts.add(r["jp"])
        tid = r["key"].split(":", 1)[1].rsplit(".", 1)[0] if ":" in r["key"] else r["key"]
        if r["jp"] in texts360:
            plat[r["id"]] = "common"
        elif tid in by_tid:
            plat[r["id"]] = "ps3"
            notes[r["id"]] = "360판은 문구가 다름(360 전용 행 참조)"
        else:
            plat[r["id"]] = "ps3"
    all_web = {r["jp"] for r in rows}
    add = []
    for (tid, text), v in sorted(ents360.items(), key=lambda kv: kv[1]["locs"][0]):
        if text in all_web:
            continue
        add.append({"tid": tid, "jp": text, **v})
    return plat, notes, add, undec


def scan_script(rows):
    """script 행: PS3 SCB MSG 인덱스 → 360 대응(pcport360.align). x360 행은 이미 360 전용."""
    import pcport360 as P
    import excel2scb as E
    import scb_common as C
    xr = P.scb_rels(P.X360_ORIG)
    plat, notes = {}, {}
    by_file = collections.defaultdict(list)
    for r in rows:
        if r["cat"] != "script":
            continue
        m = r.get("meta") or {}
        if m.get("x360"):
            plat[r["id"]] = "x360"
            continue
        by_file[m.get("file", "")].append(r)
    for f, rs in by_file.items():
        if not f or f.lower() not in xr:
            for r in rs:
                plat[r["id"]] = "ps3"
                notes[r["id"]] = "PS3 전용 파일(360판에 없음)"
            continue
        p, x = P.load_ps3(f), P.load_360(f)
        sp, sx = C.parse_section_dir(p), C.parse_section_dir(x)
        pp = E.parse_msg_table(p, sp["MSG"][0])
        px = E.parse_msg_table(x, sx["MSG"][0])
        tp = [s["text"] for s in pp["strings"]]
        tx = [s["text"] for s in px["strings"]]
        mapping, approx = P.align(tp, tx)
        idx = {s["abs_offset"]: s["index"] for s in pp["strings"]}
        for r in rs:
            off = (r.get("meta") or {}).get("off")
            i = idx.get(int(off)) if off is not None else None
            if i is None:                       # 엑셀 오프셋이 MSG 문자열 시작과 다른 행 → 원문으로
                i = next((s["index"] for s in pp["strings"] if s["text"] == r["jp"]), None)
            if i is None or i not in mapping:
                plat[r["id"]] = "ps3"
                notes[r["id"]] = "PS3판에만 있는 대사(360판에 해당 대사 없음)"
            else:
                plat[r["id"]] = "common"
                if i in approx:
                    notes[r["id"]] = "360판 문구: " + tx[mapping[i]]
    return plat, notes


def scan_xmb(rows):
    """xmb 분류: install·ranker·exep_init은 PS3 전용 파일, 가사는 곡별로 360 본편/DLC와 대조."""
    plat, notes = {}, {}
    lyr360 = {}
    for d0 in [os.path.join(X360, "songinfo")]:
        for dp, _dn, fns in os.walk(d0):
            for fn in fns:
                if fn.startswith("lyrics_") and fn.endswith(".xmb"):
                    d = dec_any(open(os.path.join(dp, fn), "rb").read(), "x360")
                    if d:
                        lyr360[fn[7:-4]] = ("본편", [t["text"] for t in collect_texts(parse_xmb(d, 0))])
    dlc_songs = set()
    for r in rows:
        if r["cat"] == "dlc" and r["grp"] == "songinfo":
            if any(s.startswith("360:") for s in (r.get("meta") or {}).get("src", [])):
                dlc_songs.add(r["key"].split(":")[0].replace("lyrics_", ""))
    for r in rows:
        if r["cat"] != "xmb":
            continue
        if r["grp"] in ("install", "ranker", "exep_init"):
            plat[r["id"]] = "ps3"
            notes[r["id"]] = {"install": "PS3 설치·트로피 문구", "ranker": "PS3 S4U 랭커 NPC",
                              "exep_init": "PS3 竜宮小町 엑스트라 에피소드"}[r["grp"]]
            continue
        song = r["key"].split("/")[0]
        if song in lyr360:
            plat[r["id"]] = "common" if r["jp"] in lyr360[song][1] else "ps3"
            if plat[r["id"]] == "ps3":
                notes[r["id"]] = "360판 가사에 없는 줄"
        elif song in dlc_songs:
            plat[r["id"]] = "common"
            notes[r["id"]] = "360판은 DLC로 수록(DLC 분류에도 같은 곡)"
        else:
            plat[r["id"]] = "ps3"
            notes[r["id"]] = "PS3 전용 곡"
    return plat, notes


def scan_image(rows, log=print):
    """PS3 이미지 행(텍스트 있는 텍스처 md5 그룹) ↔ 360 같은 파일의 텍스처를 **내용으로** 대조
    (pcport_apply와 같은 360 코덱 후보·≥30dB). 같은 파일에서 PS3 어느 텍스처와도 안 맞는
    360 텍스처는 360 전용 후보(예: Xbox 버튼 튜토리얼)로 PNG를 뽑는다."""
    from PIL import Image
    from extract_image_text import walk_nuts
    import pcport_apply as PA
    idx = json.load(open(os.path.join(OUT_DEFAULT, "index.json"), encoding="utf-8"))
    md5_rows = {r["key"]: r for r in rows if r["cat"] == "image" and r["grp"] != "dlc"}
    loc_ok = {}                 # "rel#nnn" → True(360에 같은 그림) / False
    add, undec, missing = [], [], []
    outdir = os.path.join(OUT_DEFAULT, "x360_only")
    os.makedirs(outdir, exist_ok=True)
    for rel, v in sorted(idx.items()):
        texts = set(v.get("cn_modified", []))
        p360 = os.path.join(X360, rel)
        if not os.path.exists(p360):
            missing.append(rel)
            for n in texts:
                loc_ok[f"{rel}#{n:03d}"] = False
            continue
        d = dec_any(open(p360, "rb").read(), "x360")
        if d is None:
            undec.append(rel)
            continue
        tx = walk_nuts(d.replace(b"NTXR", b"NTP3"), lambda *a: None)
        ps3 = {}
        for t in v["jp"]["textures"]:
            if "error" in t:
                continue
            pp = os.path.join(OUT_DEFAULT, "jp", os.path.dirname(rel), t["png"])
            if os.path.exists(pp):
                ps3[t["n"]] = (t["w"], t["h"], pp)
        cache = {}

        def img(n):
            if n not in cache:
                cache[n] = np.asarray(Image.open(ps3[n][2]).convert("RGBA"), np.uint8)
            return cache[n]
        used360, dec_win = {}, collections.Counter()
        for k, t in enumerate(tx):
            same = [n for n, (w, h, _p) in ps3.items() if (w, h) == (t["w"], t["h"])]
            if not same:
                continue
            raw = d[t["data_off"]:t["data_off"] + t["data_size"]]
            decs = []
            for name, dec, _enc in PA.candidates(t["fmt"]):
                try:
                    decs.append((name, dec(raw, t["w"], t["h"])))
                except Exception:  # noqa: BLE001
                    pass
            best = None
            for n in sorted(same, key=lambda n: (n not in texts, n)):
                for name, im in decs:
                    q = PA.psnr(im, img(n))
                    if best is None or q > best[0]:
                        best = (q, n, name)
                if best and best[0] >= 40:
                    break
            if best and best[0] >= 30:
                used360[k] = best[1]
                dec_win[best[2]] += 1
        matched_ps3 = set(used360.values())
        for n in texts:
            loc_ok[f"{rel}#{n:03d}"] = n in matched_ps3
        # 360 전용 후보: PS3 텍스트 텍스처가 360에서 안 맞은 파일에서, 어떤 PS3 텍스처와도 안 맞은 360 텍스처
        if not any(n not in matched_ps3 for n in texts):
            continue
        for k, t in enumerate(tx):
            if k in used360:
                continue
            raw = d[t["data_off"]:t["data_off"] + t["data_size"]]
            cands = PA.candidates(t["fmt"])
            order = sorted(cands, key=lambda c: -dec_win.get(c[0], 0))
            im = None
            for name, dec, _enc in order:
                try:
                    im = dec(raw, t["w"], t["h"])
                    break
                except Exception:  # noqa: BLE001
                    continue
            if im is None:
                continue
            md5 = hashlib.md5(im.tobytes()).hexdigest()
            fn = f"{rel.replace(os.sep, '_')}_{k:03d}.png"
            Image.fromarray(im, "RGBA").save(os.path.join(outdir, fn))
            add.append({"rel": rel, "n": k, "w": t["w"], "h": t["h"], "fmt": f"360 fmt{t['fmt']}/{name}",
                        "md5": md5, "png": fn})
        log(f"  {rel}: PS3 텍스트 {len(texts)} 중 360 일치 {sum(n in matched_ps3 for n in texts)}, "
            f"360 미대응 텍스처 {sum(1 for x in add if x['rel'] == rel)}")
    plat, notes = {}, {}
    for md5, r in md5_rows.items():
        locs = (r.get("meta") or {}).get("locs", [])
        oks = [loc_ok.get(L.replace("/", "\\")) for L in locs]
        if any(oks):
            plat[r["id"]] = "common"
        elif all(o is None for o in oks):
            plat[r["id"]] = "ps3"
            notes[r["id"]] = "360판 파일 복호화 미지원(s2d) — 대응 미확인"
        else:
            plat[r["id"]] = "ps3"
            notes[r["id"]] = "360판에 같은 그림 없음(360판은 그림이 다르거나 없음)"
    return plat, notes, add, undec, missing


# 360 미대응 텍스처 108개를 눈으로 검토(2026-10-23)해 일본어 글자가 있는 것만 등록.
# 나머지는 컨트롤러 버튼 그림(LB/RB/A/B…), 스태프롤 캐릭터 모델 텍스처, 영문(PRESS>>RB, UNIT) — 번역 대상 아님.
KEEP_X360 = {
    "game\\alf\\alf_common.mpc#242",            # お守りGET
    "game\\alf\\alf_tut_aud_01.nut#0", "game\\alf\\alf_tut_base_01.nut#0",
    "game\\alf\\alf_tut_base_02.nut#0", "game\\alf\\alf_tut_fes_01.nut#0",
    "game\\alf\\alf_tut_fes_02.nut#0", "game\\alf\\alf_tut_liv_01.nut#0",
    "game\\alf\\alf_tut_liv_02.nut#0",           # 튜토리얼 카드(360 버튼 표기)
    "game\\les_com.mpc#106",                     # お守りGET
    "s4u\\s4u_fullpack.mpc#182", "s4u\\s4u_fullpack.mpc#187",   # 가(仮) 재킷(곡 제목)
    "scene\\mainmenu.mpc#6", "scene\\mainmenu.mpc#98", "scene\\mainmenu.mpc#100",  # アップロード·システム設定·服装設定
}


def scan_dlc(rows):
    plat = {}
    for r in rows:
        if r["cat"] != "dlc":
            continue
        src = (r.get("meta") or {}).get("src", [])
        a, b = any(s.startswith("360:") for s in src), any(s.startswith("ps3:") for s in src)
        plat[r["id"]] = "common" if a and b else ("x360" if a else "ps3")
    return plat


def scan_dlc_lyrics(rows):
    """PS3 DLC(cp01~18) 곡 가사를 dlc_text와 같은 규칙으로 병합:
    같은 id·같은 문구 → 기존 행 meta.src에 ps3 위치 추가, 문구 다름 → '#ps3' 행, 새 곡 → 새 행."""
    from dlc_text import xmb_texts_all
    by_key = {r["key"]: r for r in rows if r["cat"] == "dlc" and r["grp"] == "songinfo"}
    src_add = collections.defaultdict(list)   # row id → [ps3 src]
    new = {}
    for cp in sorted(os.listdir(PS3_DLC)):
        si = os.path.join(PS3_DLC, cp, "resource", "songinfo")
        if not os.path.isdir(si):
            continue
        for song in sorted(os.listdir(si)):
            ly = os.path.join(si, song, f"lyrics_{song}.xmb")
            if not os.path.exists(ly):
                continue
            d = dec_any(open(ly, "rb").read(), "ps3")
            if d is None:
                continue
            src = f"ps3:{cp}/songinfo/{song}"
            for _xi, tid, tx in xmb_texts_all(d):
                if not tx or tx.isascii():
                    continue
                key = f"lyrics_{song}:{tid}"
                r = by_key.get(key)
                if r is not None and r["jp"] == tx:
                    if src not in (r.get("meta") or {}).get("src", []):
                        src_add[r["id"]].append(src)
                    continue
                k2 = key if r is None else key + "#ps3"
                if k2 in by_key and by_key[k2]["jp"] == tx:
                    src_add[by_key[k2]["id"]].append(src)
                    continue
                new.setdefault(k2, {"jp": tx, "src": []})["src"].append(src)
    return dict(src_add), new


def _post(path, body, code, prefer):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(CFG["url"] + path, data=data, method="POST", headers={
        "apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}",
        "x-team-code": code, "Content-Type": "application/json", "Prefer": prefer})
    return urllib.request.urlopen(r).status


def apply(code, service_key=None):
    """scan 결과 반영.
    1) 기존 행: meta.plat/plat_note(+DLC 가사 PS3 src)만 갱신. 보내는 열은 id·cat·grp·seq·key·jp·meta
       — kr/st/ts/by는 보내지 않으므로 merge-duplicates여도 팀 번역·상태는 그대로.
    2) 빠진 행 추가: ignore-duplicates(이미 있으면 건드리지 않음)."""
    if not code:
        sys.exit("--code 필요")
    A = json.load(open(AUDIT, encoding="utf-8"))
    rows = {r["id"]: r for r in fetch_rows()}
    plat, notes = {}, {}
    for cat in ("gamedata", "script", "xmb", "image", "dlc"):
        plat.update(A[cat]["plat"])
        notes.update(A[cat].get("notes", {}))
    upd = []
    for rid, p in plat.items():
        r = rows.get(rid)
        if r is None:
            continue
        m = dict(r.get("meta") or {})
        m["plat"] = p
        if rid in notes:
            m["plat_note"] = notes[rid]
        if rid in A["dlc"]["src_add"]:
            m["src"] = list(m.get("src", [])) + [s for s in A["dlc"]["src_add"][rid] if s not in m.get("src", [])]
        if m != (r.get("meta") or {}):
            upd.append({k: r[k] for k in ("id", "cat", "grp", "seq", "key", "jp")} | {"meta": m})
    for i in range(0, len(upd), 500):
        _post("/rest/v1/rows?on_conflict=id", upd[i:i + 500], code,
              "resolution=merge-duplicates,return=minimal")
        print(f"  meta 갱신 {min(i + 500, len(upd))}/{len(upd)}", end="\r")
    print(f"  meta 갱신 {len(upd)}행 (번역·상태 열은 보내지 않음)        ")

    new = []
    labels_grp = lambda src, chain, tid: next(g for g, _l, f in game_xmb.GROUPS if f(src, chain, tid))
    seen = collections.Counter()
    for i, x in enumerate(A["gamedata"]["add"]):
        src = x["locs"][0]
        tag = src.replace("/", "_").replace(".mpc", "").replace(".tsk", "")
        key = f"x360:{tag}:{x['tid']}"
        seen[key] += 1
        if seen[key] > 1:
            key += f".{seen[key]}"
        grp = labels_grp(src, x["chain"], x["tid"])
        new.append({"id": f"gamedata:{grp}:{key}", "cat": "gamedata", "grp": grp, "seq": 900000 + i,
                    "key": key, "jp": x["jp"], "kr": "", "st": 0, "ts": 0, "by": "",
                    "meta": {"locs": ["360:" + L for L in x["locs"]], "chain": x["chain"],
                             "plat": "x360", "plat_note": "360판(PC 포트)에만 있는 문구"}})
    base = 1000
    for i, (k, v) in enumerate(sorted(A["dlc"]["add_lyrics"].items())):
        new.append({"id": f"dlc:songinfo:{k}", "cat": "dlc", "grp": "songinfo", "seq": base + i,
                    "key": k, "jp": v["jp"], "kr": "", "st": 0, "ts": 0, "by": "",
                    "meta": {"src": v["src"], "plat": "ps3",
                             "plat_note": "PS3판 DLC에만 있는 가사" if not k.endswith("#ps3")
                             else "PS3판 DLC 가사(360판과 문구 다름)"}})
    by_md5 = {}
    for x in A["image"]["add"]:
        if f"{x['rel']}#{x['n']}" not in KEEP_X360:
            continue
        by_md5.setdefault(x["md5"], []).append(x)
    for i, (md5, xs) in enumerate(by_md5.items()):
        x = xs[0]
        top = x["rel"].split("\\")[0]
        new.append({"id": f"image:{top}:{md5}", "cat": "image", "grp": top, "seq": 900000 + i,
                    "key": md5, "jp": "", "kr": "", "st": 0, "ts": 0, "by": "",
                    "meta": {"w": x["w"], "h": x["h"], "fmt": x["fmt"],
                             "locs": [f"x360:{y['rel'].replace(os.sep, '/')}#{y['n']:03d}" for y in xs],
                             "mode": "", "plat": "x360",
                             "plat_note": "360판(PC 포트)에만 있는 그림 — PS3판과 그림이 다름"}})
    by_md5p = {}
    for x in A["dlc"].get("add_images", []):
        by_md5p.setdefault(x["md5"], []).append(x)
    for i, (md5, xs) in enumerate(sorted(by_md5p.items(), key=lambda kv: kv[1][0]["png"])):
        x = xs[0]
        new.append({"id": f"image:dlc:{md5}", "cat": "image", "grp": "dlc", "seq": 900000 + i,
                    "key": md5, "jp": "", "kr": "", "st": 0, "ts": 0, "by": "",
                    "meta": {"w": x["w"], "h": x["h"], "fmt": x["fmt"], "kind": x["kind"], "mode": "",
                             "locs": [f"ps3:{y['cp']}/{y['rel']}#{y['n']:03d}" for y in xs],
                             "plat": "ps3", "plat_note": "PS3판 DLC에만 있는 곡"}})
    for i in range(0, len(new), 500):
        _post("/rest/v1/rows?on_conflict=id", new[i:i + 500], code,
              "resolution=ignore-duplicates,return=minimal")
    print(f"  새 행 {len(new)}개 추가 시도(이미 있으면 무시)")
    if by_md5 or by_md5p:
        if not service_key:
            print("  ⚠ 새 이미지 썸네일 업로드 생략(--service-key 없음)")
            return
        n = 0
        ups = [("x360_only", xs[0]) for xs in by_md5.values()] + \
              [("ps3_dlc_only", xs[0]) for xs in by_md5p.values()]
        for sub, x in ups:
            data = open(os.path.join(OUT_DEFAULT, sub, x["png"]), "rb").read()
            r = urllib.request.Request(f"{CFG['url']}/storage/v1/object/tex/jp/{x['md5']}.png",
                                       data=data, method="POST",
                                       headers={"apikey": service_key, "Authorization": f"Bearer {service_key}",
                                                "x-upsert": "true", "Content-Type": "image/png"})
            urllib.request.urlopen(r)
            n += 1
        print(f"  새 이미지 썸네일 {n}장 업로드 (360 전용 {len(by_md5)}, PS3 DLC {len(by_md5p)})")


def scan_ps3_dlc_images(new_lyrics):
    """PS3 전용 DLC 곡(가사가 새로 들어온 곡)의 재킷·제목 로고 — dlc_images.classify와 같은 기준
    (곡 제목 로고 464x48, 곡 재킷 256x256). PNG는 OUT/ps3_dlc_only/에."""
    from PIL import Image
    from extract_image_text import walk_nuts, decode_texture
    songs = {k.split(":")[0].replace("lyrics_", "") for k in new_lyrics if not k.endswith("#ps3")}
    outdir = os.path.join(OUT_DEFAULT, "ps3_dlc_only")
    os.makedirs(outdir, exist_ok=True)
    out = []
    for cp in sorted(os.listdir(PS3_DLC)):
        si = os.path.join(PS3_DLC, cp, "resource", "songinfo")
        if not os.path.isdir(si):
            continue
        for song in sorted(os.listdir(si)):
            if song not in songs:
                continue
            for fn in sorted(os.listdir(os.path.join(si, song))):
                if not fn.endswith(".nut"):
                    continue
                d = dec_any(open(os.path.join(si, song, fn), "rb").read(), "ps3")
                if d is None:
                    continue
                for k, t in enumerate(walk_nuts(d, lambda *a: None)):
                    kind = {(464, 48): "곡 제목 로고", (256, 256): "곡 재킷"}.get((t["w"], t["h"]))
                    if not kind:
                        continue
                    im = decode_texture(t["fmt"], d[t["data_off"]:t["data_off"] + t["data_size"]], t["w"], t["h"])
                    md5 = hashlib.md5(im.tobytes()).hexdigest()
                    png = f"{cp}_{song}_{fn[:-4]}_{k:03d}.png"
                    Image.fromarray(im, "RGBA").save(os.path.join(outdir, png))
                    out.append({"cp": cp, "rel": f"songinfo/{song}/{fn}", "n": k, "w": t["w"], "h": t["h"],
                                "fmt": f"PS3 fmt{t['fmt']}", "kind": kind, "md5": md5, "png": png})
    return out


def pair(code, apply_=True):
    """같은 대상인데 두 판에서 다른 행을 서로 연결(meta.pair = 상대 행 id).
    - gamedata: PS3 행(360에 같은 id가 다른 문구로 있음) ↔ x360 행(같은 파일·같은 id)
    - dlc: '<키>#ps3' ↔ '<키>'
    - image: PS3 전용 그림 ↔ 같은 파일의 360 전용 그림(축소 흑백 상관으로 짝, 같은 치수 우선)"""
    from PIL import Image
    rows = fetch_rows()
    by_id = {r["id"]: r for r in rows}
    pairs = {}

    def link(a, b):
        if a not in pairs and b not in pairs:
            pairs[a], pairs[b] = b, a
    gd = [r for r in rows if r["cat"] == "gamedata"]
    x360 = collections.defaultdict(list)
    for r in gd:
        if r["key"].startswith("x360:"):
            tag, tid = r["key"][5:].split(":", 1)
            x360[(tag.split("#")[0], tid.rsplit(".", 1)[0] if re.search(r"\.\d+$", tid) else tid)].append(r["id"])
    for r in gd:
        m = r.get("meta") or {}
        if m.get("plat") == "ps3" and "문구가 다름" in m.get("plat_note", ""):
            tag, tid = r["key"].split(":", 1)
            tid = tid.rsplit(".", 1)[0] if re.search(r"\.\d+$", tid) else tid
            for cand in x360.get((tag.split("#")[0], tid), []):
                if cand not in pairs:
                    link(r["id"], cand)
                    break
    for r in rows:
        if r["cat"] == "dlc" and r["key"].endswith("#ps3"):
            base = f"dlc:{r['grp']}:{r['key'][:-4]}"
            if base in by_id:
                link(r["id"], base)

    def thumb(path):
        im = Image.open(path).convert("L").resize((64, 32))
        a = np.asarray(im, np.float32)
        a -= a.mean()
        return a / (np.linalg.norm(a) + 1e-6)
    img_ps3 = collections.defaultdict(list)
    img_x = collections.defaultdict(list)
    for r in rows:
        if r["cat"] != "image" or r["grp"] == "dlc":
            continue
        m = r.get("meta") or {}
        for L in m.get("locs", []):
            if m.get("plat") == "x360" and L.startswith("x360:"):
                rel, n = L[5:].rsplit("#", 1)
                p = os.path.join(OUT_DEFAULT, "x360_only", f"{rel.replace('/', '_')}_{int(n):03d}.png")
                img_x[rel.replace("/", "\\")].append((r["id"], m, p))
            elif m.get("plat") == "ps3" and "같은 그림 없음" in m.get("plat_note", ""):
                rel, n = L.replace("/", "\\").rsplit("#", 1)
                stem = os.path.splitext(os.path.basename(rel))[0]
                p = os.path.join(OUT_DEFAULT, "jp", os.path.dirname(rel), f"{stem}_{int(n):03d}.png")
                img_ps3[rel].append((r["id"], m, p))
    # 그림 짝은 엄격하게: 한 파일에 PS3 미대응 1장·360 전용 1장이고 치수가 같을 때만(튜토리얼 카드).
    # 축소 흑백 상관은 짧은 글자 라벨에서 엉뚱한 짝을 냄(システム設定2↔システム設定, お守りINFO↔お守りGET) — 2026-10-23 눈검수.
    for rel, xs in img_x.items():
        ps = img_ps3.get(rel, [])
        if len(xs) == 1 and len(ps) == 1:
            (xid, xm, _xp), (pid, pm, _pp) = xs[0], ps[0]
            if (xm["w"], xm["h"]) == (pm["w"], pm["h"]):
                link(xid, pid)
    upd = []
    for r in rows:
        m = dict(r.get("meta") or {})
        want = pairs.get(r["id"])
        if m.get("pair") == want:
            continue
        if want:
            m["pair"] = want
        else:
            m.pop("pair", None)          # 이전 실행의 잘못된 짝 제거
        upd.append({k: r[k] for k in ("id", "cat", "grp", "seq", "key", "jp")} | {"meta": m})
    c = collections.Counter(a.split(":")[0] for a in pairs)
    print(f"연결 {len(pairs) // 2}쌍 {dict((k, v // 2) for k, v in c.items())}, meta 갱신 {len(upd)}")
    for a, b in pairs.items():
        if a.startswith("image:") and by_id[a]["meta"].get("plat") == "x360":
            print("  그림 짝:", by_id[a]["meta"]["locs"][0], "↔", by_id[b]["meta"]["locs"][0])
    if apply_ and upd:
        for i in range(0, len(upd), 500):
            _post("/rest/v1/rows?on_conflict=id", upd[i:i + 500], code,
                  "resolution=merge-duplicates,return=minimal")


def counts():
    """사이드바 표시용 분류별 PS3·360 전용 건수 → platform_counts.json (webapp_build가 META에 넣음)."""
    out = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in fetch_rows():
        out[r["cat"]][r["grp"]][(r.get("meta") or {}).get("plat", "common")] += 1
    data = {c: {g: {k: v for k, v in cnt.items() if k in ("ps3", "x360")} for g, cnt in gs.items()}
            for c, gs in out.items()}
    json.dump(data, open(os.path.join(HERE, "platform_counts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("platform_counts.json 저장")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "apply", "pair", "counts"])
    ap.add_argument("--code")
    ap.add_argument("--service-key")
    a = ap.parse_args()
    if a.cmd == "apply":
        return apply(a.code, a.service_key)
    if a.cmd == "pair":
        return pair(a.code, apply_=bool(a.code))
    if a.cmd == "counts":
        return counts()
    rows = fetch_rows()
    print(f"웹앱 {len(rows)}행")
    out = {}
    plat, notes, add, undec = scan_gamedata(rows)
    out["gamedata"] = {"plat": plat, "notes": notes, "add": add, "undec": undec}
    print("gamedata:", dict(collections.Counter(plat.values())), "| 360 전용 추가 후보", len(add))
    plat, notes = scan_script(rows)
    out["script"] = {"plat": plat, "notes": notes}
    print("script:", dict(collections.Counter(plat.values())),
          "| 문구 다른 공통", sum(1 for v in notes.values() if v.startswith("360판 문구")))
    plat, notes = scan_xmb(rows)
    out["xmb"] = {"plat": plat, "notes": notes}
    print("xmb:", dict(collections.Counter(plat.values())))
    plat, notes, add, undec, missing = scan_image(rows)
    out["image"] = {"plat": plat, "notes": notes, "add": add, "undec": undec, "missing": missing}
    print("image:", dict(collections.Counter(plat.values())), "| 360 전용 후보", len(add),
          "| 복호화 안 됨", undec, "| 360에 없는 파일", missing)
    plat = scan_dlc(rows)
    src_add, new_ly = scan_dlc_lyrics(rows)
    for rid in src_add:
        plat[rid] = "common"
    for k, v in new_ly.items():
        plat[f"dlc:songinfo:{k}"] = "ps3"
    out["dlc"] = {"plat": plat, "src_add": src_add, "add_lyrics": new_ly,
                  "add_images": scan_ps3_dlc_images(new_ly)}
    print(f"dlc 가사: 기존 행에 PS3 위치 추가 {len(src_add)}, 새 행 {len(new_ly)} "
          f"(곡 {len({k.split(':')[0] for k in new_ly})})")
    print("dlc:", dict(collections.Counter(plat.values())))
    json.dump(out, open(AUDIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
