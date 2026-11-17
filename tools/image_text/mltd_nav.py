#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""밀리시타(MLTD) 웹앱 메뉴 목록 — 서버 rows에 실제로 들어간 mltd_* 분류의 grp를 모아 mltd_nav.json에 쓴다(읽기만).
webapp_build.py가 이 파일을 읽어 meta.nav 뒤에 game:"mltd" 섹션으로 붙인다. MLTD 행을 더 넣은 뒤 다시 실행.
mltd_img는 썸네일(tex/mltd/jp/) 업로드 전이라 메뉴에서 뺀다.

  python mltd_nav.py
"""
import os
import sys
import json
import time
from collections import Counter
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webapp_fill as F  # noqa: E402

SECTIONS = [("mltd_master", "밀리시타 · 마스터 문자열"), ("mltd_birth", "밀리시타 · 생일 대사")]
FIRST = ("CM", "ST")      # 번역 순서(UI 공통 CM → ST → 나머지)


def grps(cat):
    """id 기준 이어 읽기(offset 깊은 페이지는 서버 500)."""
    c, last = Counter(), ""
    while True:
        q = f"/rest/v1/rows?select=id,grp&cat=eq.{cat}&order=id&limit=500" + (f"&id=gt.{quote(last, safe='')}" if last else "")
        for t in range(4):
            try:
                b = F._req("GET", q, "w@ldo")
                break
            except Exception:
                if t == 3:
                    raise
                time.sleep(3)
        c.update(x["grp"] for x in b)
        if len(b) < 500:
            return c
        last = b[-1]["id"]


def main():
    out = []
    for cat, label in SECTIONS:
        c = grps(cat)
        if not c:
            continue
        key = lambda g: (next((i for i, p in enumerate(FIRST) if g.split("_")[0] == p), len(FIRST)), g)
        out.append({"cat": cat, "label": label, "game": "mltd",
                    "groups": [{"g": g, "label": f"{g} ({n:,})"} for g, n in sorted(c.items(), key=lambda kv: key(kv[0]))]})
        print(cat, len(c), "묶음", sum(c.values()), "행")
    json.dump(out, open(os.path.join(HERE, "mltd_nav.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
