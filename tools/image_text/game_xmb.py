#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
본편 XMB 텍스트 전수 추출 → 웹앱 'gamedata' 분류 (2026-10-22, 사용자 지적으로 누락 발견)

이전까지는 "중국팀이 수정한 파일 + 개별 요청" 범위만 다뤄서 의상·악세서리·곡·업무
설명, 오디션 심사위원/라이브 청중 코멘트, 팬레터, 스태프롤 등 게임 데이터 텍스트가
웹앱에 없었다. 이 도구는 리소스 트리의 **모든 XMB**(평문 .mpc 내장 + 암호화
.tsk 내장(사본 복호화) + 단독 .xmb)를 덤프한다.

규칙:
  - 내용이 같은 XMB(여러 pac에 같은 표가 복제됨)는 1벌만, meta.locs에 전 위치.
  - 이미 웹앱에 있는 것 제외: 곡 가사(dance/songinfo), exep_init NPC 명단,
    install.xmb, ranker_npc.xmb.
  - DB XMB(요소 구조)는 부모 노드 단위로 이름+설명을 카드로 묶음(meta.card/part).
  - 그룹(소분류)은 GROUPS 규칙으로 내용 종류별 분류.

  python game_xmb.py extract   # gamedata_texts.json + 드라이런 보고
  (시딩: webapp_seed.py --only gamedata --code <팀암호>)
"""
import os
import re
import sys
import json
import hashlib
import argparse
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from xmb_text import parse_xmb  # noqa: E402
from extract_image_text import JP_ROOT  # noqa: E402
from dlc_text import stage  # noqa: E402  (사본 복호화 캐시 재사용)

JP = re.compile(r"[぀-ヿ一-鿿！-～]")
TSK_DIRS = ("interface", "game", "iface", "scene", "s4u", "mail", "text")
SKIP_DIRS = ("dance", "songinfo", "gscript", "tools", "chara", "acce", "stage",
             "motion", "bg2d", "song")

# (그룹키, 라벨, 판정함수(src, chain, tid) → bool) — 위에서부터 첫 일치
GROUPS = [
    ("costume", "의상 (이름·설명)", lambda s, c, t: c.startswith("costume/")),
    ("accessory", "악세서리 (이름·설명)", lambda s, c, t: c.startswith("accessory/")),
    ("song", "곡 정보 (제목·설명·작가)", lambda s, c, t: c.startswith("song/")),
    ("skill", "스킬·부적", lambda s, c, t: c.startswith(("skill_info/", "charm/"))),
    ("stage", "스테이지·오디션 정보", lambda s, c, t: c.startswith("stage_info/")),
    ("profile", "캐릭터 이름·프로필", lambda s, c, t: c.startswith(("character/", "agency/"))),
    ("job", "업무·스케줄 설명", lambda s, c, t: t.split("_")[0] in ("job", "SCHE", "sch")),
    ("audition", "오디션 심사위원 코멘트", lambda s, c, t: "alf_audi" in s and t[:1] == "t"),
    ("live", "라이브 청중 코멘트", lambda s, c, t: "alf_live" in s and t[:1] == "t"),
    ("fanletter", "팬레터", lambda s, c, t: "fan_letter" in s),
    ("mail", "메일 (본편)", lambda s, c, t: c.startswith("mail/") or "_mail_" in s),
    ("result", "결과·평가 코멘트",
     lambda s, c, t: t.split("_")[0] in ("scr", "dan", "mim", "act")),
    ("names", "고유명사 목록 (방송국·지역·기자·칭호)",
     lambda s, c, t: t.split("_")[0] in ("tvs", "pre", "jou", "PLV", "gai")),
    ("staffroll", "스태프롤", lambda s, c, t: "staff_roll" in s),
    ("system", "메뉴·도움말·시스템 메시지", lambda s, c, t: True),
]
EXCLUDE_IDPFX = ("NPCP", "NPCU", "NPCS", "PROD", "LYR")   # 기존 웹앱 커버


def iter_sources():
    """(rel, bytes) — 평문 mpc, interface 등 tsk(복호화 사본), 단독 xmb."""
    for dp, dns, fns in os.walk(JP_ROOT):
        rel_dir = os.path.relpath(dp, JP_ROOT)
        top = rel_dir.split(os.sep)[0]
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith("_")]
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            low = fn.lower()
            if low.endswith(".mpc") and ".dec" not in low:
                data = open(p, "rb").read()
                if data[:4] == b"pac\x00":
                    yield rel, data
            elif low.endswith(".tsk") and top in TSK_DIRS:
                try:
                    yield rel, stage(p, "gx_" + rel.replace(os.sep, "_"))
                except Exception as e:  # noqa: BLE001
                    print(f"  [복호화 실패] {rel}: {e}")


def xmb_entries(data):
    """버퍼 내 XMB마다 (xi, [(tid, chain, parent_idx, field, text)])."""
    pos = 0
    xi = 0
    while True:
        i = data.find(b"XMB ", pos)
        if i < 0:
            return
        pos = i + 4
        try:
            p = parse_xmb(data, i)
        except Exception:  # noqa: BLE001
            continue
        nodes = p["nodes"]
        for nd, e in zip(nodes, p["entries"]):
            nd["_e"] = e

        def anc_id(ni):
            while ni != 0xFFFF:
                a = nodes[ni]["_e"].get("attrs", {})
                if a.get("id"):
                    return a["id"]
                ni = nodes[ni]["parent"]
            return None

        out = []
        for e in p["entries"]:
            if "text" not in e or not e["text"] or not JP.search(e["text"]):
                continue
            ni = e["node"]
            field_ni = nodes[ni]["parent"]           # text_node의 부모 = 필드 요소
            owner_ni = nodes[field_ni]["parent"] if field_ni != 0xFFFF else 0xFFFF
            field = nodes[field_ni]["name"] if field_ni != 0xFFFF else "text"
            owner = nodes[owner_ni]["name"] if owner_ni != 0xFFFF else "root"
            chain = f"{owner}/{field}"
            tid = anc_id(ni) or f"n{owner_ni}.{field}"
            out.append((tid, chain, owner_ni, field, e["text"]))
        yield xi, out
        xi += 1


def extract():
    sig_map = {}      # 내용 해시 → {"src": 첫 위치, "locs": [...], "ents": [...]}
    n_src = 0
    for rel, data in iter_sources():
        n_src += 1
        for xi, ents in xmb_entries(data):
            if not ents:
                continue
            if all(t[0].split("_")[0] in EXCLUDE_IDPFX for t in ents):
                continue
            h = hashlib.md5(json.dumps([(t[0], t[4]) for t in ents],
                                       ensure_ascii=False).encode()).hexdigest()
            loc = f"{rel.replace(os.sep, '/')}#x{xi}"
            if h in sig_map:
                sig_map[h]["locs"].append(loc)
            else:
                sig_map[h] = {"src": loc, "locs": [loc], "ents": ents}
    rows = {}
    seq = Counter()
    seen_tid = Counter()
    for h, x in sorted(sig_map.items(), key=lambda kv: kv[1]["src"]):
        tag = x["src"].replace("/", "_").replace(".mpc", "").replace(".tsk", "")
        for tid, chain, owner, field, text in x["ents"]:
            if tid.split("_")[0] in EXCLUDE_IDPFX:
                continue
            grp = next(g for g, _l, f in GROUPS if f(x["src"], chain, tid))
            key = f"{tag}:{tid}"
            seen_tid[key] += 1
            if seen_tid[key] > 1:
                key = f"{key}.{seen_tid[key]}"
            seq[grp] += 1
            meta = {"locs": x["locs"], "chain": chain}
            if chain.split("/")[0] not in ("root", "system_message", "text_node"):
                meta["card"] = f"{tag}:{chain.split('/')[0]}{owner}"
                meta["part"] = field
            rows[f"gamedata:{grp}:{key}"] = {
                "cat": "gamedata", "grp": grp, "seq": seq[grp], "key": key,
                "jp": text, "kr": "", "st": 0, "meta": meta}
    json.dump(rows, open(os.path.join(HERE, "gamedata_texts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    labels = {g: l for g, l, _f in GROUPS}
    print(f"\n소스 {n_src}개 파일, 유니크 XMB {len(sig_map)}개 → 총 {len(rows)}행")
    for g, _l, _f in GROUPS:
        if seq[g]:
            ex = next(v for v in rows.values() if v["grp"] == g)
            print(f"  {g:10s} {seq[g]:5d}  {labels[g]}  예: {ex['jp'][:28]!r}")
    print("\n시딩: python webapp_seed.py --only gamedata --code <팀암호>")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract"])
    ap.parse_args()
    extract()


if __name__ == "__main__":
    main()
