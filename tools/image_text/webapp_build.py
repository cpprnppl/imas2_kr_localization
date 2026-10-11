#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iM@S2 KOR 번역 플랫폼 빌더 (Vercel + Supabase + PatternFly)

행 데이터는 전부 Supabase(rows/hist)에 있고(시딩: webapp_seed.py), 페이지에는
메타만 내장한다: 네비 트리(XMB/게임 스크립트/이미지 텍스트 + 소분류), XMB 값
섹션 바이트 예산, 폰트 매핑 2,359자, Supabase 접속 정보(webapp_config.json).

  python webapp_build.py [출력.html]   # 기본: webapp_deploy/index.html
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xmb_text import (  # noqa: E402
    TARGETS, load_file, find_xmb, parse_xmb, collect_texts, MAPPING_PATH, HERE)
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402

XLSX_PATH = os.path.join(JP_ROOT, "gscript", "tools", "translation_2.xlsx")

XMB_GROUPS = [("install", "설치/트로피 메시지", "text/install.xmb"),
              ("ranker", "NPC 유닛명", "ranker/ranker_npc.xmb"),
              ("exep_init", "EXTRA NPC 명단", "scene/exep_init.mpc")]
REL2GRP = {rel: g for g, _l, rel in XMB_GROUPS}

IMAGE_GROUP_LABELS = {
    "bg2d": "배경 (bg2d)", "game": "레슨·ALF·앨범 (game)", "iface": "선택 화면 (iface)",
    "interface": "인터페이스 (interface)", "mail": "메일 (mail)",
    "s4u": "Stage For You (s4u)", "scene": "씬·메뉴 (scene)"}


def xmb_budgets():
    out = {}
    for grp, _label, rel in XMB_GROUPS:
        rel_w = rel.replace("/", "\\")
        data = load_file("jp", rel_w)
        base = find_xmb(data)
        p = parse_xmb(data, base)
        texts = collect_texts(p)
        first_txt = min(p["attrs"][t["attr"]]["vofs"] for t in texts)
        if base:
            o_val = p["o_val"]
            vend = max(p["attrs"][t["attr"]]["vofs"] + 2 * len(t["text"]) + 2
                       for t in texts)
            end = o_val + vend
            while end < len(data) and end % 16 and data[end] == 0:
                end += 1
            avail = end - o_val
        else:
            avail = len(data) - p["o_val"]
        out[grp] = avail - first_txt
    return out


def script_groups():
    from openpyxl import load_workbook
    wb = load_workbook(XLSX_PATH, read_only=True)
    out = []
    for ws in wb.worksheets:
        t = ws.title
        if "(" not in t:        # 목차 등
            continue
        short, label = t.split("(", 1)
        out.append({"g": short, "label": f"{short} · {label.rstrip(')')}"})
    return out


def image_groups():
    idx = json.load(open(os.path.join(OUT_DEFAULT, "index.json"), encoding="utf-8"))
    tops = []
    for rel, r in idx.items():
        if not r.get("cn_modified"):
            continue
        top = rel.split("\\")[0].split("/")[0]
        if top not in tops:
            tops.append(top)
    return [{"g": t, "label": IMAGE_GROUP_LABELS.get(t, t)} for t in sorted(tops)]


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "webapp_deploy", "index.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cfg_path = os.path.join(HERE, "webapp_config.json")
    cfg = None
    if os.path.exists(cfg_path):
        c = json.load(open(cfg_path, encoding="utf-8"))
        cfg = {"url": c["url"], "key": c["anon_key"],
               "texbase": c["url"] + "/storage/v1/object/public/tex"}
    else:
        print("[주의] webapp_config.json 없음 — 오프라인 빌드")

    mapping = json.load(open(MAPPING_PATH, encoding="utf-8"))
    meta = {
        "mapchars": "".join(sorted(mapping.keys())),
        "xmb_budgets": xmb_budgets(),
        "nav": [
            {"cat": "xmb", "label": "XMB 텍스트",
             "groups": [{"g": g, "label": l} for g, l, _r in XMB_GROUPS]},
            {"cat": "script", "label": "게임 스크립트", "groups": script_groups()},
            {"cat": "image", "label": "이미지 텍스트", "groups": image_groups()},
        ],
    }
    tpl = open(os.path.join(HERE, "webapp_template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(meta, ensure_ascii=False))
    html = html.replace("/*__CFG__*/null", json.dumps(cfg))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"생성: {out_path} ({os.path.getsize(out_path)//1024}KB)")
    print("시딩: python webapp_seed.py  /  배포: webapp_deploy를 Vercel로")


if __name__ == "__main__":
    main()
