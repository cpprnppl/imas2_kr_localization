#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구글 스프레드시트(팀이 쓰던 번역 시트) → 웹앱 script 분류 병합 (2026-10-23, 1단계: 드라이런)

  python sheet_merge.py dryrun <시트.xlsx>     # 서버 최신 rows·hist 기준 분류 보고(쓰기 없음)

시트 구조(시트마다 다름 — 머리글로 판별):
  인물명 | 원문 | 번역문(사람) | 비고 ... | Gemini | 파일경로 | 엔트리인덱스(=오프셋) | 원문바이트수
  all·ami·azu·ior·rit·ryu: 비고 4열(경로·오프셋·바이트 수가 비고 2~4열에 들어 있음) 뒤 Gemini
  yuk: Gemini 열 없음.  Gemini 값은 구글 수식(=IFERROR(__xludf...)) → 캐시값(data_only)으로 읽음.
행 대응: (시트 접두, "파일:오프셋") = 웹 script 키 → 원문이 같으면 확정. 안 맞으면 같은 파일 안에서
원문 정렬(difflib)로 재매칭(오프셋 체계 차이: 웹은 translation_2 오프셋 교정판).

분류(정책 초안 = KOR 권고: 웹 팀 편집 > 시트 사람 번역 > 기존 웹 기계번역, 시트 Gemini는 빈칸만):
  same            시트 사람 번역 = 웹 kr
  fill_human      웹 kr 빔 → 시트 사람 번역으로 채움
  overwrite       웹 kr(초기 Gemini API 기계번역) → 시트 사람 번역으로 교체
  conflict        웹에서 팀원이 편집한 행(by/hist) + 시트 사람 번역이 다름 → 덮지 않고 목록
  fill_gemini     사람 번역 없음 + 웹 kr 빔 → 시트 Gemini로 채움(출처 표시)
  gemini_same     시트 Gemini ≈ 웹 kr(문장부호·공백·개행 무시)
  gemini_alt      시트 Gemini ≠ 웹 kr → kr 유지, meta.alt 대안으로만
  unmatched       웹 행을 못 찾음
"""
import os
import re
import sys
import json
import difflib
import argparse
import collections
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402

CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
OUT = os.path.join(OUT_DEFAULT, "sheet_merge")      # 게임 원문 포함 — git 밖
SCB_RE = re.compile(r"^[a-z]{3}\\.+\.scb$", re.I)
PUNCT = re.compile(r"[\s「」『』（）()、。，．,.!！?？…~～・\-─—]+")


def norm_jp(s):
    return (s or "").replace("\r", "").strip().rstrip("\n").strip()


def loose(s):
    return PUNCT.sub("", s or "")


def read_sheet(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        if "(" not in ws.title:
            continue
        grp = ws.title.split("(", 1)[0]
        rows = ws.iter_rows(values_only=True)
        head = [str(h).strip() if h is not None else "" for h in next(rows)]
        c_jp, c_hu = head.index("원문"), head.index("번역문")
        c_gem = head.index("Gemini") if "Gemini" in head else None
        c_path = None
        for i, row in enumerate(ws.iter_rows(min_row=2, max_row=40, values_only=True)):
            for j, v in enumerate(row):
                if isinstance(v, str) and SCB_RE.match(v.strip()):
                    c_path = j
                    break
            if c_path is not None:
                break
        for n, row in enumerate(rows):
            row = list(row) + [None] * 30
            jp = row[c_jp]
            path = row[c_path]
            if jp is None and path is None:
                continue
            off = row[c_path + 1]
            gem = row[c_gem] if c_gem is not None else None
            if isinstance(gem, str) and (gem.startswith("=") or gem.startswith("#")):
                gem = None
            out.append({"grp": grp, "n": n, "sp": row[0], "jp": str(jp or ""), "hu": str(row[c_hu] or "").strip(),
                        "gem": str(gem or "").strip(), "file": str(path or "").strip(),
                        "off": int(float(off)) if off not in (None, "") else None})
    return out


def fetch(path_q):
    rows, off = [], 0
    while True:
        r = urllib.request.Request(f"{CFG['url']}/rest/v1/{path_q}&limit=1000&offset={off}", headers={
            "apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}", "x-team-code": "w@ldo"})
        ch = json.load(urllib.request.urlopen(r))
        rows += ch
        if len(ch) < 1000:
            return rows
        off += 1000


def match(sheet, web):
    """시트 행 → 웹 행. 1) 키+원문 일치 2) 파일별 원문 정렬 재매칭."""
    by_key = {}
    by_file = collections.defaultdict(list)
    for r in web:
        base = r["key"].split("#")[0]
        by_key.setdefault((r["grp"], base), r)
        by_file[(r["grp"], (r.get("meta") or {}).get("file", base.rsplit(":", 1)[0]))].append(r)
    pairs, used, how = {}, set(), {}
    rest = collections.defaultdict(list)
    for i, s in enumerate(sheet):
        w = by_key.get((s["grp"], f"{s['file']}:{s['off']}"))
        if w and norm_jp(w["jp"]) == norm_jp(s["jp"]) and w["id"] not in used:
            pairs[i], how[i] = w, "key"
            used.add(w["id"])
        else:
            rest[(s["grp"], s["file"])].append(i)
    for fk, idxs in rest.items():
        ws = [w for w in sorted(by_file.get(fk, []), key=lambda r: r["seq"]) if w["id"] not in used]
        a = [norm_jp(sheet[i]["jp"]) for i in idxs]
        b = [norm_jp(w["jp"]) for w in ws]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for k in range(i2 - i1):
                    pairs[idxs[i1 + k]], how[idxs[i1 + k]] = ws[j1 + k], "realign"
                    used.add(ws[j1 + k]["id"])
    return pairs, how


def classify(sheet, pairs, team):
    cls = collections.defaultdict(list)
    for i, s in enumerate(sheet):
        w = pairs.get(i)
        if w is None:
            if s["hu"] or s["gem"]:
                cls["unmatched"].append((s, None))
            continue
        kr = w["kr"] or ""
        if s["hu"]:
            if loose(kr) == loose(s["hu"]):
                cls["same"].append((s, w))
            elif w["id"] in team:
                cls["conflict"].append((s, w))
            elif not kr:
                cls["fill_human"].append((s, w))
            else:
                cls["overwrite"].append((s, w))
        elif s["gem"]:
            if not kr:
                cls["fill_gemini"].append((s, w))
            elif loose(kr) == loose(s["gem"]):
                cls["gemini_same"].append((s, w))
            else:
                cls["gemini_alt"].append((s, w))
    return cls


def cmd_dryrun(a):
    sheet = read_sheet(a.xlsx)
    web = fetch("rows?select=id,grp,seq,key,jp,kr,st,by,ts,meta&cat=eq.script&order=id")
    hist = fetch("hist?select=row_id,by&cat=eq.script&order=row_id")
    team = {h["row_id"] for h in hist if h.get("by") and "초벌" not in h["by"]} | \
           {r["id"] for r in web if r.get("by") and "초벌" not in r["by"]}
    pairs, how = match(sheet, web)
    cls = classify(sheet, pairs, team)
    n_hu = sum(1 for s in sheet if s["hu"])
    n_gem = sum(1 for s in sheet if s["gem"])
    hu_rows = [s for s in sheet if s["hu"]]
    stat = {
        "sheet_rows": len(sheet), "human": n_hu, "gemini": n_gem,
        "web_script_rows": len(web), "web_team_edited": len(team),
        "matched_key": sum(1 for v in how.values() if v == "key"),
        "matched_realign": sum(1 for v in how.values() if v == "realign"),
        "classes": {k: len(v) for k, v in cls.items()},
        "human_by_sheet": dict(collections.Counter(s["grp"] for s in hu_rows)),
        "human_missing_newline": sum(1 for s in hu_rows if "\n" in norm_jp(s["jp"]) and "\n" not in s["hu"]),
        "human_missing_kagi": sum(1 for s in hu_rows if s["jp"].lstrip().startswith("「") and not s["hu"].lstrip().startswith("「")),
        "speaker_label_rows": sum(1 for s in sheet if re.fullmatch(r".{1,6}達", norm_jp(s["jp"]) or "")),
    }
    os.makedirs(OUT, exist_ok=True)
    ex = {k: [{"key": w["key"] if w else f"{s['file']}:{s['off']}", "grp": s["grp"], "jp": norm_jp(s["jp"])[:80],
               "web_kr": (w or {}).get("kr", "")[:80], "sheet_human": s["hu"][:80], "sheet_gemini": s["gem"][:80]}
              for s, w in v[:300]] for k, v in cls.items()}
    json.dump({"stat": stat, "examples": ex}, open(os.path.join(OUT, "dryrun.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(stat, ensure_ascii=False, indent=1))
    for k in ("fill_human", "overwrite", "conflict", "fill_gemini", "gemini_alt", "unmatched"):
        for s, w in cls.get(k, [])[:2]:
            print(f"[{k}] {s['grp']} {norm_jp(s['jp'])[:30]!r} | 웹 {(w or {}).get('kr', '')[:30]!r} | "
                  f"사람 {s['hu'][:30]!r} | Gemini {s['gem'][:30]!r}")
    print(f"→ {os.path.join(OUT, 'dryrun.json')}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dryrun")
    d.add_argument("xlsx")
    a = ap.parse_args()
    {"dryrun": cmd_dryrun}[a.cmd](a)


if __name__ == "__main__":
    main()
