#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹앱(Supabase) 번역 회수 → xmb_translations.json 반영

  python webapp_pull.py --code <팀암호> [--reviewed-only]

- webapp_config.json의 url/anon_key + 팀 암호 헤더로 tr 테이블 전체를 읽어
  kr이 비어 있지 않은 행을 xmb_translations.json에 병합한다.
- --reviewed-only: 검수완료(st=2)만 반영.
- 이후 `python xmb_text.py build` 로 patched/ 생성.
"""
import os
import sys
import json
import argparse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))

SHORT2REL = {"install": "text/install.xmb",
             "ranker": "ranker/ranker_npc.xmb",
             "exep_init": "scene/exep_init.mpc"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="팀 암호 (x-team-code)")
    ap.add_argument("--reviewed-only", action="store_true")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    rows = []
    offset = 0
    while True:
        req = urllib.request.Request(
            f"{cfg['url']}/rest/v1/tr?select=*&order=id&limit=1000&offset={offset}",
            headers={"apikey": cfg["anon_key"],
                     "Authorization": f"Bearer {cfg['anon_key']}",
                     "x-team-code": args.code})
        chunk = json.load(urllib.request.urlopen(req))
        rows += chunk
        if len(chunk) < 1000:
            break
        offset += 1000
    print(f"서버 행 {len(rows)}개")

    tr_path = os.path.join(HERE, "xmb_translations.json")
    tr = json.load(open(tr_path, encoding="utf-8"))
    n = 0
    stat = {0: 0, 1: 0, 2: 0}
    for r in rows:
        stat[r.get("st", 0)] = stat.get(r.get("st", 0), 0) + 1
        if not r.get("kr"):
            continue
        if args.reviewed_only and r.get("st", 0) < 2:
            continue
        rel = SHORT2REL.get(r["f"])
        if rel is None:
            continue
        tid = r["k"].split("#")[0]        # "id#n" 중복 행 키 → 원 id
        ent = tr.setdefault(rel, {}).setdefault(tid, {"jp": "", "cn": "", "kr": ""})
        if ent.get("kr") != r["kr"]:
            ent["kr"] = r["kr"]
            n += 1
    with open(tr_path, "w", encoding="utf-8") as f:
        json.dump(tr, f, ensure_ascii=False, indent=1)
    print(f"반영 {n}건 (상태 분포: 미번역 {stat.get(0,0)} / 번역 {stat.get(1,0)} / 검수 {stat.get(2,0)})")
    print("다음: python xmb_text.py build")


if __name__ == "__main__":
    main()
