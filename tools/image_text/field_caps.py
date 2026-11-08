#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
필드별 TextField 칸(cap) 게이트 (2026-11-08, PS3 S4U 팅김 = DLC 카탈로그 설명 칸 128 넘침 — KOR 지시·사용자 결정)

게임의 TextField::SetText(PS3 01.02 0x353a80 / 360 sub_822B3EC8)는 글자를 buf[줄 수 + i + 1]에 복사하고, 잘리거나 꽉 차면
끝 NUL을 buf[cap](버퍼 끝 2바이트 뒤)에 쓴다 → 다음 힙 청크 헤더가 깨져 나중 free에서 abort(PS3) / 누수(360).
  NUL 위치 m = 줄 수 + 글자(UTF-16, 줄바꿈 1단위 포함) + 1.   안전·안 잘림 상한: 글자 ≤ cap − 2 − 줄 수  (= m ≤ cap − 1)
cap 근거 등급:
  hard  실측·정적(인터페이스 부품 init 0x1b576c의 li r7 상수, RPCS3 화면 잘림 실측) → 빌드 실패 · 웹앱 빨강
  est   정적 추정(같은 부품으로 보임 등)                                        → 빌드 보고 · 웹앱 주황
  jp    모르는 묶음: 원문 m 최대 + 1(원문만큼은 확실히 안전)                      → 빌드 보고 · 웹앱 주황
묶음 = field_len_audit.group_of와 같은 문자열(gamedata '파일#XMB · chain', DLC '분류 x<i> · 부모/요소').
근거: KOR 노트 ps3_s4u_textfield_cap_20261108.md, field_limits_t11.csv. PC 기록 훅 실측이 나오면 KNOWN을 갱신.
"""
import collections

# 묶음 → (cap, 등급, 근거)
KNOWN = {
    "dlc catalog x0 · desc/text_node": (128, "hard", "RPCS3 실측: 8줄 문구가 119단위에서 잘림 = 128−1−8, 원문 m 최대 127"),
    "gamedata initialFix#x2 · stage_info/caption": (64, "hard", "StageViewer StageSelect li r7,0x40 + 10-28 n401 실측"),
    "gamedata initialFix#x1 · costume/caption": (64, "hard", "StageViewer CostumSelect li r7,0x40 (S4U 의상 목록 설명)"),
    "gamedata scene_mainmenu#x7 · root/system_message": (128, "hard", "CHelpTicker li r7,0x80, 도움말 m 65 전부 표시"),
    "gamedata scene_mainmenu#x8 · root/system_message": (128, "hard", "CHelpTicker li r7,0x80, op2_002 m 65 전부 표시"),
    "gamedata initialFix#x2 · accessory/text": (64, "est", "CostumSelect 같은 부품으로 추정"),
    "dlc package x1 · text/text_node": (64, "est", "DLC 의상·액세서리 설명 = CostumSelect 추정"),
    "gamedata initialFix#x2 · song/author": (64, "est", "StageViewer SongSelect 추정"),
    "dlc package x1 · author/text_node": (64, "est", "SongSelect 추정"),
    "dlc package x1 · caption/text_node": (128, "est", "원문 m 최대 120, 카탈로그 계열 팝업 추정"),
    "gamedata initialFix#x2 · song/caption": (128, "est", "원문 m 최대 111, 칸 64 아님"),
}
# 한 묶음에 두 종류가 섞인 곳: 원문 m < 기준인 행은 다른 칸. 묶음 → (원문 m 기준, cap, 등급, 근거)
SPLIT = {
    "dlc package x1 · caption/text_node": (64, 64, "hard", "PC SetText 실측(감독 11-08): 짧은 설명 = S4U 의상·스테이지 설명 cap 64"),
}


def u16(s):
    return len((s or "").encode("utf-16-be")) // 2


def m(s):
    """SetText NUL 위치 = 줄 수 + 글자 + 1 (원문 \\r\\n은 게임에서도 2단위)."""
    s = s or ""
    return s.count("\n") + 1 + u16(s) + 1


def limit(cap, s):
    """이 문자열 줄 수에서 허용 글자 수(줄바꿈 포함 UTF-16)."""
    return cap - 2 - ((s or "").count("\n") + 1)


_dch = None


def group_of(r):
    """r: {cat, grp, key, meta} → 묶음 문자열 (field_len_audit.group_of와 같음)."""
    global _dch
    if r["cat"] == "gamedata":
        return f"gamedata {r['key'].rsplit(':', 1)[0]} · {(r.get('meta') or {}).get('chain', '?')}"
    if r["cat"] == "dlc" and r.get("grp") in ("catalog", "package"):
        if _dch is None:
            import field_len_audit as F
            _dch = F.dlc_chains()
        stem, k = r["key"].split(":", 1)
        k = k.split("#")[0]
        return f"dlc {r['grp']} {k.split('.')[0]} · {_dch.get((stem, k), '?')}"
    return None


def caps(rows):
    """묶음 → (cap, 등급, 근거). KNOWN 밖은 원문 m 최대 + 1."""
    jm = collections.defaultdict(int)
    for r in rows:
        g = group_of(r)
        if g and r.get("jp"):
            jm[g] = max(jm[g], m(r["jp"]))
    out = {g: (v + 1, "jp", f"원문 m 최대 {v} + 1") for g, v in jm.items() if not g.endswith("· ?")}
    out.update(KNOWN)
    return out


def violations(rows):
    """→ [(등급, 묶음, key, cap, 줄 수, 글자, 허용, kr)] — m ≥ cap인 번역 행."""
    cs, out = caps(rows), []
    for r in rows:
        if not r.get("kr"):
            continue
        g = group_of(r)
        if g not in cs:
            continue
        cap, lv, _why = cs[g]
        if g in SPLIT and m(r.get("jp")) < SPLIT[g][0]:
            cap, lv = SPLIT[g][1], SPLIT[g][2]
        if m(r["kr"]) >= cap:
            out.append((lv, g, r["key"], cap, r["kr"].count("\n") + 1, u16(r["kr"]), limit(cap, r["kr"]), r["kr"]))
    return out


def gate(rows, label):
    """hard 위반 = 빌드 중단, est/jp = 보고만."""
    v = violations(rows)
    soft = [x for x in v if x[0] != "hard"]
    if soft:
        c = collections.Counter(x[0] for x in soft)
        print(f"[칸 게이트] {label}: 추정 칸 넘침 {len(soft)}행(est {c['est']} · 원문 기준 {c['jp']}) — 보고만, 막지 않음")
    hard = [x for x in v if x[0] == "hard"]
    if hard:
        for lv, g, key, cap, L, n, lim, kr in hard[:20]:
            print(f"  {key}  [{g}] cap {cap} · {L}줄 · {n}/{lim}자  {kr[:40]!r}")
        raise SystemExit(f"[칸 게이트] {label}: 실측·정적 칸 넘침 {len(hard)}행 — 글자 ≤ cap−2−줄 수로 줄여야 함"
                         f"(넘치면 게임이 힙을 깨 튕김, KOR 노트 ps3_s4u_textfield_cap_20261108.md)")
    return v


if __name__ == "__main__":
    import sys
    import json
    sys.stdout.reconfigure(encoding="utf-8")
    rows = json.load(open(sys.argv[1], encoding="utf-8"))      # webapp 행 JSON(cat·grp·key·jp·kr·meta)
    v = violations(rows)
    c = collections.Counter((x[0], x[1]) for x in v)
    for (lv, g), n in sorted(c.items()):
        print(f"{lv:4s} {n:4d}  {g}  (cap {caps(rows)[g][0]})")
    print("합계", len(v), dict(collections.Counter(x[0] for x in v)))
