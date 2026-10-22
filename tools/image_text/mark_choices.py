#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
웹앱 게임 스크립트 행에 '선택지' 표시(meta.choice=true) — 2026-10-23

선택지 MSG = SCB CMD 스트림의 선택지 명령(0x0103, 인자 4개, 첫 인자 MSG 인덱스) — excel2scb.choice_indices.
빌드(rewrap)는 선택지를 선택지 상자 폭(209px 추정, 2줄)으로 어절 경계에서 감싸고, 웹앱 '게임 표시' 미리보기도
meta.choice가 있는 행에만 같은 규칙을 쓴다. 원본은 순정 백업(gscript - 복사본)에서 읽는다.

  python mark_choices.py --code <팀암호> [--dry-run]
"""
import os
import sys
import json
import glob
import argparse
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scb"))
import excel2scb as E  # noqa: E402
import scb_common as C  # noqa: E402
from extract_image_text import JP_ROOT  # noqa: E402

ORIG = os.path.join(os.path.dirname(JP_ROOT), "gscript - 복사본")
CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))


def choice_keys():
    """{'<rel>:<abs_offset>'} — 웹 script 행 key와 같은 형식."""
    keys = set()
    for p in glob.glob(os.path.join(ORIG, "**", "*.scb"), recursive=True):
        rel = os.path.relpath(p, ORIG)
        if rel.lower().startswith("tools"):
            continue
        d = C.decrypt_scb(open(p, "rb").read())
        secs = C.parse_section_dir(d)
        if "MSG" not in secs:
            continue
        ch = E.choice_indices(d)
        if not ch:
            continue
        for s in E.parse_msg_table(d, secs["MSG"][0])["strings"]:
            if s["index"] in ch:
                keys.add(f"{rel}:{s['abs_offset']}")
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    keys = choice_keys()
    h = {"apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}", "x-team-code": a.code}
    from platform_audit import fetch_rows      # 분류별·재시도 읽기(script 전체 order=id 한 번은 500)
    rows = fetch_rows(cats=("script",))
    todo = [r for r in rows if r["key"] in keys and not (r["meta"] or {}).get("choice")]
    print(f"선택지 MSG {len(keys)}개, 웹 행 일치 {sum(1 for r in rows if r['key'] in keys)}, 새로 표시 {len(todo)}")
    if a.dry_run:
        return
    for i, r in enumerate(todo):
        urllib.request.urlopen(urllib.request.Request(
            CFG["url"] + "/rest/v1/rows?id=eq." + urllib.parse.quote(r["id"], safe=""),
            data=json.dumps({"meta": {**(r["meta"] or {}), "choice": True}}, ensure_ascii=False).encode("utf-8"),
            method="PATCH", headers={**h, "Content-Type": "application/json", "Prefer": "return=minimal"}))
        print(f"  {i + 1}/{len(todo)}", end="\r")
    print(f"\n완료 {len(todo)}행")


if __name__ == "__main__":
    main()
