#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
필드 묶음별 "원문 최대 길이 초과" 전수 점검 (2026-10-28, S4U 튕김 후속 — KOR 지시)

S4U 튕김 원인은 스테이지 설명(stage_info/caption)을 원문 최대 길이에 맞춘 고정 버퍼로 복사하다 넘친 것.
같은 방식이 다른 필드에도 있을 수 있으므로, 필드 묶음마다 원문(일본어) 최대 UTF-16 길이를 잡고
한국어가 그보다 긴 행을 뽑는다.

  필드 묶음 = gamedata: (파일#XMB 서수, meta.chain) — 예 initialFix#x2 · stage_info/caption (PS3·360 따로)
              dlc catalog/package: (분류, XMB 서수, 부모 요소/텍스트 요소) — 원본 XMB(_cache/dlc, ps3_dlc_orig)에서 요소 이름을 읽음
  입력 = 웹앱 실데이터(rows 조회, 팀 암호). 출력 = field_len_audit.json + 표

  python field_len_audit.py --code <팀암호> [--only initialFix#x1,initialFix#x2,dlc]
"""
import os
import re
import sys
import json
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webapp_fill as W  # noqa: E402
from xmb_text import parse_xmb  # noqa: E402
from extract_image_text import OUT_DEFAULT  # noqa: E402

DLC_CACHE = os.path.join(OUT_DEFAULT, "_cache", "dlc")
OUT = os.path.join(HERE, "field_len_audit.json")
u16 = lambda s: len((s or "").encode("utf-16-be")) // 2


def fetch(code):
    out = []
    for flt in ("cat=eq.gamedata", "cat=eq.dlc&grp=in.(catalog,package)"):
        off = 0
        while True:
            rows = W._req("GET", f"/rest/v1/rows?{flt}&select=id,cat,grp,key,jp,kr,st,by,meta"
                                 f"&order=id&limit=1000&offset={off}", code)
            out += rows
            if len(rows) < 1000:
                break
            off += 1000
    return out


def dlc_sources():
    """(stem, 평문) — 360·PS3 packageInfo/catalog는 dlc_text 캐시, PS3 catalog_info는 ps3_dlc_orig(암호화면 복호화)."""
    for fn in os.listdir(DLC_CACHE):
        m = re.match(r"(360|ps3)_([^_]+)_(catalog_info\.xmb|packageInfo\.pac)$", fn)
        if m:
            kind = "catalog" if m[3].startswith("catalog") else "package"
            yield f"{kind}_{m[2][:6]}", open(os.path.join(DLC_CACHE, fn), "rb").read()
    orig = os.path.join(OUT_DEFAULT, "ps3_dlc_orig")
    import ps3_res_apply as P
    for cp in sorted(os.listdir(orig)):
        p = os.path.join(orig, cp, "resource", "catalog_info.xmb")
        if os.path.exists(p):
            yield f"catalog_{cp}", P.open_raw(open(p, "rb").read())[0]


def dlc_chains():
    """(stem, 'x<i>.<id>') → '부모/요소' — dlc_text.xmb_texts_all과 같은 id·서수 규칙."""
    out = {}
    for stem, data in dlc_sources():
        p = xi = 0
        while True:
            i = data.find(b"XMB ", p)
            if i < 0:
                break
            try:
                px = parse_xmb(data, i)
                nodes = px["nodes"]
                for nd, e in zip(nodes, px["entries"]):
                    nd["_entry"] = e
                seen = collections.Counter()
                for e in px["entries"]:
                    if "text" not in e:
                        continue
                    from xmb_text import entry_key
                    tid0 = entry_key(e, nodes)
                    seen[tid0] += 1
                    tid = tid0 if seen[tid0] == 1 else f"{tid0}.{seen[tid0]}"
                    par = nodes[nodes[e["node"]]["parent"]]["name"] if nodes[e["node"]]["parent"] != 0xFFFF else ""
                    out[(stem, f"x{xi}.{tid}")] = f"{par}/{e['name']}"
            except Exception:  # noqa: BLE001 — XMB 아닌 우연 일치
                pass
            xi += 1
            p = i + 4
    return out


def group_of(r, dch):
    m = r.get("meta") or {}
    if r["cat"] == "gamedata":
        file = r["key"].rsplit(":", 1)[0]          # 'initialFix#x2' 또는 'x360:initialFix#x2'
        return f"gamedata {file} · {m.get('chain', '?')}"
    stem, k = r["key"].split(":", 1)
    k = k.split("#")[0]
    ch = dch.get((stem, k), "?")
    xi = k.split(".")[0]
    return f"dlc {r['grp']} {xi} · {ch}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--rows", help="이미 받은 rows JSON(조회 생략)")
    a = ap.parse_args()
    rows = json.load(open(a.rows, encoding="utf-8")) if a.rows else fetch(a.code)
    dch = dlc_chains()
    groups = collections.defaultdict(list)
    for r in rows:
        if r.get("jp"):
            groups[group_of(r, dch)].append(r)
    report = []
    for g, rs in sorted(groups.items()):
        jmax = max(u16(r["jp"]) for r in rs)
        over = [r for r in rs if u16(r.get("kr")) > jmax]
        report.append({"group": g, "rows": len(rs), "jp_max": jmax, "over": len(over),
                       "max_over_bytes": max((2 * (u16(r["kr"]) - jmax) for r in over), default=0),
                       "items": [{"id": r["id"], "jp_len": u16(r["jp"]), "kr_len": u16(r["kr"]), "by": r.get("by", ""),
                                  "kr": r["kr"]} for r in sorted(over, key=lambda r: -u16(r["kr"]))]})
    json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    unk = sum(1 for g in groups if g.endswith("· ?"))
    print(f"행 {len(rows)}, 필드 묶음 {len(groups)} (요소 이름 못 찾은 묶음 {unk})")
    print(f"{'필드 묶음':58s} {'행':>5s} {'원문최대':>6s} {'초과행':>5s} {'최대초과B':>8s}")
    for x in report:
        if x["over"]:
            print(f"{x['group'][:58]:58s} {x['rows']:5d} {x['jp_max']:6d} {x['over']:5d} {x['max_over_bytes']:8d}")
    print("합계 초과 행", sum(x["over"] for x in report), "→", OUT)


if __name__ == "__main__":
    main()
