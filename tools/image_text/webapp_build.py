#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XMB 번역 협업 웹앱 빌더 (Vercel + Supabase)

xmb_texts.json(JP/CN) + xmb_translations.json(KR 제안) + font_mapping.json(2,359자)
+ 파일별 값 섹션 바이트 예산 + Supabase 접속 정보(webapp_config.json)를 내장한
단일 index.html을 webapp_deploy/ 에 생성한다. 배포는 그 폴더에서 `vercel deploy`.

  python webapp_build.py [출력.html]   # 기본: webapp_deploy/index.html

webapp_config.json: {"url": "https://xxxx.supabase.co", "anon_key": "..."}
(anon key는 공개용 키. 접근 통제는 Supabase RLS의 팀 암호 — supabase_setup.sql)
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xmb_text import (  # noqa: E402
    TARGETS, load_file, find_xmb, parse_xmb, collect_texts, MAPPING_PATH, HERE)


def budgets():
    """파일별 UTF-16 값 섹션 가용 바이트와 고정(ASCII id) 프리픽스 계산."""
    out = {}
    for rel in TARGETS:
        data = load_file("jp", rel)
        base = find_xmb(data)
        p = parse_xmb(data, base)
        texts = collect_texts(p)
        first_txt = min(p["attrs"][t["attr"]]["vofs"] for t in texts)
        if base:
            o_val = p["o_val"]
            vend = max(p["attrs"][t["attr"]]["vofs"]
                       + 2 * len(t["text"]) + 2 for t in texts)
            end = o_val + vend
            while end < len(data) and end % 16 and data[end] == 0:
                end += 1
            avail = end - o_val
        else:
            avail = len(data) - p["o_val"]
        key = rel.replace("\\", "/")
        out[key] = {"avail": avail - first_txt}  # UTF-16 텍스트 영역 몫
    return out


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "webapp_deploy", "index.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cfg_path = os.path.join(HERE, "webapp_config.json")
    cfg = None
    if os.path.exists(cfg_path):
        c = json.load(open(cfg_path, encoding="utf-8"))
        cfg = {"url": c["url"], "key": c["anon_key"]}
    else:
        print("[주의] webapp_config.json 없음 — 오프라인 미리보기용으로 생성")
    texts = json.load(open(os.path.join(HERE, "xmb_texts.json"), encoding="utf-8"))
    tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    mapping = json.load(open(MAPPING_PATH, encoding="utf-8"))
    buds = budgets()

    files = []
    for rel, rows_ in texts.items():
        short = {"text/install.xmb": "install",
                 "ranker/ranker_npc.xmb": "ranker",
                 "scene/exep_init.mpc": "exep_init"}[rel]
        label = {"install": "설치/트로피 메시지",
                 "ranker": "NPC 유닛명",
                 "exep_init": "EXTRA NPC 명단"}[short]
        rows = []
        seen = {}
        for r in rows_:
            tid = r["id"]
            # 같은 id가 여러 _text에 걸릴 수 있음 → 行 키는 id+등장순
            k = seen.get(tid, 0)
            seen[tid] = k + 1
            key = tid if k == 0 else f"{tid}#{k}"
            kr = (tr.get(rel, {}).get(tid) or {}).get("kr", "")
            rows.append({"k": key, "id": tid, "jp": r["jp"], "cn": r["cn"],
                         "kr": kr, "st": 1 if kr else 0})
        files.append({"f": short, "rel": rel, "label": label,
                      "avail": buds[rel]["avail"], "rows": rows})

    payload = {
        "files": files,
        "mapchars": "".join(sorted(mapping.keys())),
    }
    tpl = open(os.path.join(HERE, "webapp_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    html = html.replace("/*__CFG__*/null", json.dumps(cfg))
    html = ('<!doctype html>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            + html)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    n = sum(len(f_["rows"]) for f_ in files)
    print(f"생성: {out_path} ({n}행, {os.path.getsize(out_path)//1024}KB)")


if __name__ == "__main__":
    main()
