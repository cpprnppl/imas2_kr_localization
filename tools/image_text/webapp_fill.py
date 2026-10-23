#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹앱 빈 행 채우기 (초벌 번역 일괄 입력) — 서버에서 kr이 비어 있는 행만 채운다.

  python webapp_fill.py <입력.json> --code <팀암호> [--dry-run] [--by "Claude 초벌"] [--st 1]

입력: {"<row id>": "<kr>", ...}
- 행마다 조건부 PATCH(id=eq.X & kr=eq.'') — 팀원이 그 사이 입력한 행은 서버가 거부하므로
  기존 번역을 절대 덮지 않는다.
- 채운 행은 hist(수정 이력)에 by 이름으로 남긴다 → 웹앱 '수정 이력'에서 작업자 필터로 조회.
- st 기본 1(번역) → 웹앱 '검수 대기' 필터에 뜬다. 검수는 팀원이 한다.
"""
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))


def _req(method, path, code, body=None, prefer=None):
    h = {"apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}",
         "x-team-code": code, "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(CFG["url"] + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(r) as resp:
        txt = resp.read().decode("utf-8")
        return json.loads(txt) if txt else None


def fetch(ids, code):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 80):
        chunk = ids[i:i + 80]
        # PostgREST in.("…") 안에서는 \ 와 " 를 이스케이프해야 한다(script 행 id에 경로 \ 포함)
        flt = ",".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in chunk)
        q = "id=in.(" + urllib.parse.quote(flt, safe=",") + ")&select=id,cat,grp,key,kr,st,meta"
        for r in _req("GET", "/rest/v1/rows?" + q, code):
            out[r["id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--code", required=True)
    ap.add_argument("--by", default="Claude 초벌")
    ap.add_argument("--st", type=int, default=1, choices=[0, 1])
    ap.add_argument("--src", default="claude", help="meta.src_tr 출처 배지 (빈 문자열이면 안 붙임)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    want = {k: v for k, v in json.load(open(a.input, encoding="utf-8")).items() if v}
    srv = fetch(want, a.code)
    missing = [k for k in want if k not in srv]
    filled = [k for k in want if k in srv and srv[k]["kr"]]
    todo = [k for k in want if k in srv and not srv[k]["kr"]]
    print(f"입력 {len(want)}행 / 서버에 없음 {len(missing)} / 이미 번역 있음(건너뜀) {len(filled)} / 채울 행 {len(todo)}")
    for k in missing[:10]:
        print("  서버에 없음:", k)
    if a.dry_run:
        return
    n = 0
    hist = []
    for k in todo:
        ts = int(time.time() * 1000)
        q = f"/rest/v1/rows?id=eq.{urllib.parse.quote(k, safe='')}&kr=eq."
        body = {"kr": want[k], "st": a.st, "ts": ts, "by": a.by}
        if a.src:                       # 출처 배지(meta.src_tr) — 다른 meta 키는 그대로
            body["meta"] = {**(srv[k].get("meta") or {}), "src_tr": a.src}
        res = _req("PATCH", q, a.code, body, prefer="return=representation")
        if res:
            n += 1
            r = srv[k]
            hist.append({"row_id": k, "cat": r["cat"], "grp": r["grp"], "key": r["key"],
                         "ts": ts, "by": a.by, "kr": want[k], "st": a.st})
        print(f"  {n}/{len(todo)}", end="\r")
    for i in range(0, len(hist), 200):
        _req("POST", "/rest/v1/hist", a.code, hist[i:i + 200], prefer="return=minimal")
    print(f"채움 {n}행 (그 사이 다른 사람이 입력해 건너뜀 {len(todo) - n}), 이력 {len(hist)}건 기록")


if __name__ == "__main__":
    main()
