#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
화면에서 본 일본어가 웹앱(imas2.buyeo.uk)에 있는지 찾기 — 테스트 세션 공용 (2026-10-23, 사용자 상시 규칙)

  python tools/image_text/find_text.py "サインインしているゲーマー"
  python tools/image_text/find_text.py "社長" --exact          # 정규화 후 완전 일치만
  python tools/image_text/find_text.py "하루카" --kr            # 한국어 번역에서 찾기
  python tools/image_text/find_text.py --refresh --code <팀암호>  # 스냅샷 갱신(팀 암호 필요)

찾는 곳: 로컬 스냅샷 Desktop\\imas2_image_text\\webapp_snapshot.json (웹앱 전 행: script·xmb·gamedata·
image·dlc·exe, 360 전용 행 포함). 팀 암호 없이 돈다. 스냅샷이 오래됐으면 --refresh(암호 필요).
정규화: 전각/반각(NFKC), 공백·개행, 「」『』（）와 문장부호 무시, 부분 일치.
이미지 속 글자는 텍스트로 못 찾는다 — 스크린샷과 화면 위치를 KOR/ui-image-extract 세션에 보내면 이미지 행과 대조한다.
출력: 분류/소분류/키/판/번역 상태. 없으면 'NOT IN WEBAPP' — 화면·문구·추정 파일을 보고할 것.
"""
import os
import re
import sys
import json
import time
import argparse
import unicodedata
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(os.path.expanduser("~"), "Desktop", "imas2_image_text", "webapp_snapshot.json")
CATS = ("script", "xmb", "gamedata", "image", "dlc", "exe")
CAT_LABEL = {"script": "게임 스크립트", "xmb": "XMB 텍스트", "gamedata": "게임 데이터 텍스트", "image": "이미지 텍스트",
             "dlc": "DLC", "exe": "실행 파일 문구"}
PLAT = {"common": "공통", "ps3": "PS3 전용", "x360": "360 전용"}
STRIP = re.compile(r"[\s「」『』（）()【】、。，．,.!！?？…・~～ー\-─—―♪☆★]+")


def norm(s):
    return STRIP.sub("", unicodedata.normalize("NFKC", s or "")).lower()


def refresh(code):
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    rows = []
    for c in CATS:
        off = 0
        while True:
            r = urllib.request.Request(
                f"{cfg['url']}/rest/v1/rows?select=id,cat,grp,key,jp,kr,st,meta&cat=eq.{c}&order=id&limit=1000&offset={off}",
                headers={"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}", "x-team-code": code})
            for tries in range(4):          # meta가 커져 가끔 문장 시간 제한(500) — 잠깐 쉬고 다시
                try:
                    ch = json.load(urllib.request.urlopen(r))
                    break
                except urllib.error.HTTPError as ex:
                    if ex.code != 500 or tries == 3:
                        raise
                    time.sleep(3)
            for x in ch:
                m = x.get("meta") or {}
                rows.append({"id": x["id"], "cat": x["cat"], "grp": x["grp"], "key": x["key"], "jp": x["jp"],
                             "kr": x["kr"], "st": x["st"], "plat": m.get("plat", "common"),
                             "label": (m.get("kind") or "") if x["cat"] == "image" else "",
                             "locs": (m.get("locs") or m.get("src") or [])[:3]})
            if len(ch) < 1000:
                break
            off += 1000
    os.makedirs(os.path.dirname(SNAP), exist_ok=True)
    json.dump({"at": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}, open(SNAP, "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"스냅샷 갱신: {len(rows)}행 → {SNAP}")


def search(q, exact=False, in_kr=False, limit=30):
    if not os.path.exists(SNAP):
        sys.exit(f"스냅샷 없음: {SNAP} — `find_text.py --refresh --code <팀암호>` 필요")
    snap = json.load(open(SNAP, encoding="utf-8"))
    nq = norm(q)
    if not nq:
        sys.exit("검색어가 정규화 후 비었음(문장부호만?)")
    hits = []
    for r in snap["rows"]:
        t = norm(r["kr"] if in_kr else r["jp"])
        if (t == nq) if exact else (nq in t):
            hits.append(r)
    hits.sort(key=lambda r: (len(r["jp"] or ""), r["cat"]))
    print(f"스냅샷 {snap['at']} · '{q}' → {len(hits)}건" + (f" (앞 {limit}건)" if len(hits) > limit else ""))
    if not hits:
        print("NOT IN WEBAPP — 화면(스크린샷 경로)·문구·추정 파일을 KOR에 보고. "
              "스냅샷이 오래됐을 수 있으니 갱신 후 다시 찾아볼 것. 이미지 속 글자면 텍스트로는 안 잡힘.")
        return 1
    for r in hits[:limit]:
        st = "검수 완료" if r["st"] >= 2 else ("번역됨" if r["kr"] else "미번역")
        print(f"- [{CAT_LABEL.get(r['cat'], r['cat'])} › {r['grp']}] {r['key']}  ({PLAT.get(r['plat'], r['plat'])}, {st})")
        print(f"    JP: {(r['jp'] or '').replace(chr(10), '⏎')[:80]}")
        if r["kr"]:
            print(f"    KR: {r['kr'].replace(chr(10), '⏎')[:80]}")
        print(f"    웹: https://imas2.buyeo.uk/#/{r['cat']}/{r['grp']}/{r['key']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--kr", action="store_true", help="한국어 번역에서 찾기")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--code")
    a = ap.parse_args()
    if a.refresh:
        if not a.code:
            sys.exit("--refresh에는 --code <팀암호> 필요")
        refresh(a.code)
        if not a.query:
            return
    if not a.query:
        ap.error("검색어 필요")
    sys.exit(search(a.query, a.exact, a.kr, a.limit))


if __name__ == "__main__":
    main()
