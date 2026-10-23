#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
게임 스크립트 미번역 행 일괄 초벌 (2026-10-23 사용자 승인 "미번역대사 최대한 저렴히 ㄱ", KOR 지시)

비용 순서:
  1) 번역 메모리(무료): 같은 원문(공백·「」·개행 무시) 번역 재사용 — 사람(팀·시트) > 표기/오류 수정된 행 > 기계 초기본 > Claude.
     「」 유무와 개행 수는 대상 원문에 맞춘다. 라벨 규칙(お守り屋さん → 부적 가게 주인).
  2) 남은 고유 원문만 모델 번역(서브에이전트 배치) — 원문 하나 = 한 번, 같은 원문 행에 복제.
  3) 검증은 스크립트로만(check): 개행 수, 줄 폭 702px·전체 57자(116바이트), 「」 짝, 치환 코드·이모티콘(PUA) 보존,
     폰트 2,359자, 가나·한자 잔재. 걸린 줄만 다시 고치고 그래도 안 되면 빈칸.
  4) fill: webapp_fill(빈 행만 조건부, src_tr=claude, st 1, hist "Claude 초벌(일괄)").

  python bulk_draft.py fetch                      # 서버 script 행 → bulk/script_rows.json
  python bulk_draft.py prep [--batch 340]         # bulk/tm_fill.json + bulk/batch_NN.json(모델 입력)
  python bulk_draft.py check bulk/out_NN.json     # 배치 결과 검증(실패 목록 출력, 종료코드 1)
  python bulk_draft.py merge                      # out_*.json 합쳐 검증 통과분 → bulk/model_fill.json(같은 원문 행 복제)
"""
import os
import re
import sys
import json
import time
import argparse
import collections
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402

B = os.path.join(OUT_DEFAULT, "bulk")
ROWS = os.path.join(B, "script_rows.json")
LABELS = {"お守り屋さん": "부적 가게 주인"}
MAX_U16 = 57                     # MSG 한 줄(문자열) 원본 최대 116바이트 ≈ 57자(CLAUDE.md)
LINE_PX = 702                    # excel2scb rewrap 줄 폭
PUA = re.compile(r"[-]")
KANA_KANJI = re.compile(r"[぀-ヿ一-鿿㐀-䶿]")


def norm(s):
    return re.sub(r"[\s「」『』（）()　]", "", s or "")


def wpx(s):
    w = 0.0
    for ch in s:
        if "가" <= ch <= "힣":
            w += 26
        elif ord(ch) < 0x80 or "｡" <= ch <= "ﾟ":
            w += 13.5
        else:
            w += 27
    return w


def mapchars():
    from xmb_text import MAPPING_PATH
    return set(json.load(open(MAPPING_PATH, encoding="utf-8")))


# ---------------------------------------------------------------- fetch
def cmd_fetch(_a):
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    out, off = [], 0
    while True:
        u = (f"{cfg['url']}/rest/v1/rows?cat=eq.script&select=id,grp,key,jp,kr,st,by,meta"
             f"&order=id&limit=1000&offset={off}")
        rq = urllib.request.Request(u, headers={"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}",
                                                "x-team-code": _a.code})
        for t in range(6):
            try:
                ch = json.load(urllib.request.urlopen(rq))
                break
            except urllib.error.HTTPError as ex:
                if ex.code != 500 or t == 5:
                    raise
                time.sleep(3)
        out += ch
        off += len(ch)
        if len(ch) < 1000:
            break
    os.makedirs(B, exist_ok=True)
    json.dump(out, open(ROWS, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(out)}행 → {ROWS} (빈 행 {sum(1 for r in out if not r['kr'])})")


# ---------------------------------------------------------------- TM 맞춤
def clean(kr, jp):
    """기계 초기본 잔재 정리: 원문에 없는 ASCII 따옴표, 줄 머리 쉼표(⏎, → ,⏎)."""
    if '"' not in jp and "”" not in jp:
        kr = kr.replace('"', "")
    kr = re.sub(r"\s*\n\s*([,，、])\s*", r"\1\n", kr)
    return kr


def fit_brackets(kr, jp):
    jq = jp.strip().startswith("「") and jp.strip().endswith("」")
    kq = kr.strip().startswith("「") and kr.strip().endswith("」")
    if jq and not kq:
        return "「" + kr.strip() + "」"
    if kq and not jq:
        return kr.strip()[1:-1]
    return kr


def fit_lines(kr, n_nl):
    """개행 수를 n_nl로: 줄을 합쳐 폭 기준으로 어절 경계에서 다시 나눈다."""
    if kr.count("\n") == n_nl:
        return kr
    words = re.sub(r"\s*\n\s*", " ", kr).split(" ")
    if n_nl == 0:
        return " ".join(words)
    total = wpx(" ".join(words))
    target = total / (n_nl + 1)
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and wpx(cand) > target and len(lines) < n_nl:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    lines.append(cur)
    while len(lines) < n_nl + 1:          # 어절이 모자라면 끝에서 쪼갠다(드묾)
        s = lines.pop()
        h = len(s) // 2
        lines += [s[:h], s[h:]]
    return "\n".join(lines)


# ---------------------------------------------------------------- 검증
def check_one(jp, kr, chars):
    errs = []
    if not kr.strip():
        return ["빈칸"]
    if kr.count("\n") != jp.count("\n"):
        errs.append(f"개행 {kr.count(chr(10))}/{jp.count(chr(10))}")
    u16 = len(kr.encode("utf-16-le")) // 2
    if u16 > MAX_U16:
        errs.append(f"길이 {u16}>{MAX_U16}")
    for ln in kr.split("\n"):
        if wpx(ln) > LINE_PX:
            errs.append(f"줄폭 {int(wpx(ln))}>{LINE_PX}")
    jq = jp.strip().startswith("「") and jp.strip().endswith("」")
    kq = kr.strip().startswith("「") and kr.strip().endswith("」")
    if jq != kq or kr.count("「") != kr.count("」"):
        errs.append("「」")
    if sorted(PUA.findall(jp)) != sorted(PUA.findall(kr)):
        errs.append("치환코드/PUA")
    miss = sorted({ch for ch in kr if "가" <= ch <= "힣" and ch not in chars})
    if miss:
        errs.append("폰트없음 " + "".join(miss))
    if KANA_KANJI.search(PUA.sub("", kr)):
        errs.append("가나/한자 잔재")
    return errs


# ---------------------------------------------------------------- prep
SPEAKER_KO = {"天海春香": "하루카", "如月千早": "치하야", "萩原雪歩": "유키호", "高槻やよい": "야요이",
              "秋月律子": "리츠코", "三浦あずさ": "아즈사", "水瀬伊織": "이오리", "菊地真": "마코토",
              "双海亜美": "아미", "双海真美": "마미", "星井美希": "미키", "我那覇響": "히비키", "四条貴音": "타카네"}


def prio(r):
    s = (r.get("meta") or {}).get("src_tr")
    if s in ("team", "human_sheet"):
        return 0
    if r.get("by") and r["by"] != "Claude 초벌":
        return 1
    if s == "machine_init":
        return 2
    return 3


def cmd_prep(a):
    rows = json.load(open(ROWS, encoding="utf-8"))
    tm = {}
    for r in rows:
        if r["kr"]:
            k = norm(r["jp"])
            if k and (k not in tm or prio(r) < prio(tm[k])):
                tm[k] = r
    chars = mapchars()
    emp = [r for r in rows if not r["kr"] and r["jp"].strip()]
    tm_fill, bad_tm, todo = {}, 0, collections.OrderedDict()
    for r in sorted(emp, key=lambda r: ((r.get("meta") or {}).get("file", r["key"]), (r.get("meta") or {}).get("off", 0), r["id"])):
        k = norm(r["jp"])
        if r["jp"].strip() in LABELS:
            tm_fill[r["id"]] = LABELS[r["jp"].strip()]
            continue
        if not KANA_KANJI.search(r["jp"]) and not re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", r["jp"]):
            tm_fill[r["id"]] = r["jp"]                # 「……」 같은 부호만 있는 줄은 원문 그대로
            continue
        if k in tm:
            kr = fit_lines(fit_brackets(clean(tm[k]["kr"], r["jp"]), r["jp"]), r["jp"].count("\n"))
            if not check_one(r["jp"], kr, chars):
                tm_fill[r["id"]] = kr
                continue
            bad_tm += 1                       # 재사용본이 검증에 걸리면 모델로
        todo.setdefault(k, []).append(r)
    json.dump(tm_fill, open(os.path.join(B, "tm_fill.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    # 화자별 말투 예시(사람 번역 우선, 짧은 것 3줄)
    ex = collections.defaultdict(list)
    for r in sorted((r for r in rows if r["kr"] and prio(r) <= 1), key=lambda r: len(r["jp"])):
        sp = (r.get("meta") or {}).get("sp", "")
        if 12 <= len(r["jp"]) <= 40 and len(ex[sp]) < 3:
            ex[sp].append({"jp": r["jp"], "kr": r["kr"]})
    # 배치: 파일 순서 유지, 고유 원문 a.batch개씩
    items = []
    for k, rs in todo.items():
        r = rs[0]
        m = r.get("meta") or {}
        it = {"i": len(items), "sp": m.get("sp", ""), "jp": r["jp"]}
        if m.get("suggest"):
            it["hint"] = m["suggest"].get("kr", "")
        items.append(it)
    for f in os.listdir(B):
        if re.match(r"batch_\d+\.json$", f):
            os.remove(os.path.join(B, f))
    idmap = {}
    nb = 0
    for s in range(0, len(items), a.batch):
        chunk = items[s:s + a.batch]
        sps = {c["sp"] for c in chunk}
        json.dump({"examples": {sp: ex.get(sp, []) for sp in sps if ex.get(sp)}, "items": chunk},
                  open(os.path.join(B, f"batch_{nb:02d}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        nb += 1
    for k, rs in todo.items():
        pass
    idmap = {str(i): [r["id"] for r in rs] for i, (k, rs) in enumerate(todo.items())}
    srcmap = {str(i): rs[0]["jp"] for i, (k, rs) in enumerate(todo.items())}
    json.dump({"ids": idmap, "jp": srcmap}, open(os.path.join(B, "idmap.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"빈 행 {len(emp)} → 메모리 재사용·라벨 {len(tm_fill)}행 (재사용본 검증 탈락 {bad_tm}) / "
          f"모델 대상 고유 원문 {len(items)}개({sum(len(v) for v in todo.values())}행) → 배치 {nb}개")


# ---------------------------------------------------------------- check / merge
def cmd_check(a):
    src = json.load(open(os.path.join(B, "idmap.json"), encoding="utf-8"))["jp"]
    out = json.load(open(a.file, encoding="utf-8"))
    chars = mapchars()
    bad = {}
    for i, kr in out.items():
        if i not in src:
            bad[i] = ["알 수 없는 번호"]
            continue
        e = check_one(src[i], kr, chars)
        if e:
            bad[i] = e
    if a.batch_file:
        want = {str(it["i"]) for it in json.load(open(a.batch_file, encoding="utf-8"))["items"]}
        for i in sorted(want - set(out), key=int):
            bad[i] = ["누락"]
    for i, e in bad.items():
        print(f"{i}\t{'; '.join(e)}\tJP={src.get(i, '').replace(chr(10), '⏎')}\tKR={out.get(i, '').replace(chr(10), '⏎')}")
    print(f"검사 {len(out)} / 실패 {len(bad)}")
    sys.exit(1 if bad else 0)


def cmd_merge(_a):
    im = json.load(open(os.path.join(B, "idmap.json"), encoding="utf-8"))
    chars = mapchars()
    fill, ok, bad = {}, 0, []
    for f in sorted(os.listdir(B)):
        if not re.match(r"out_\d+\.json$", f):
            continue
        for i, kr in json.load(open(os.path.join(B, f), encoding="utf-8")).items():
            if i not in im["jp"]:
                continue
            if check_one(im["jp"][i], kr, chars):
                bad.append(i)
                continue
            ok += 1
            for rid in im["ids"][i]:
                fill[rid] = kr
    missing = [i for i in im["jp"] if not any(rid in fill for rid in im["ids"][i]) and i not in bad]
    json.dump(fill, open(os.path.join(B, "model_fill.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"모델 번역 통과 고유 {ok} → {len(fill)}행 / 검증 실패 {len(bad)} / 결과 없음 {len(missing)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--code", required=True)
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("prep")
    p.add_argument("--batch", type=int, default=340)
    p.set_defaults(fn=cmd_prep)
    p = sub.add_parser("check")
    p.add_argument("file")
    p.add_argument("--batch-file")
    p.set_defaults(fn=cmd_check)
    sub.add_parser("merge").set_defaults(fn=cmd_merge)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
