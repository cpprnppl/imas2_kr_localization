#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대사 치환 문자열 31단위 게이트 (2026-10-29, ps3-360-pc PS3 EBOOT 정적 분석 → KOR 지시)

produce_etc.mpc의 Lua가 setScriptReplaceString(idx 1..5 = 대사 이름 코드 F01D~F021)으로 곡명·라이벌 유닛 이름·게스트 호칭·
IA 노미네이트 유닛 문구를 넣는다. 그 바인딩은 UTF-8 문자열을 길이 검사 없이 64B 스택 버퍼로 바꾼다(PS3 0x224540, 360 sub_822662C0):
32단위 이상이면 저장 레지스터, 56단위 이상이면 복귀 주소를 덮어 멈춘다. → 그 칸에 들어갈 수 있는 번역 문자열은 31단위 이하.

대상(번역된 행만 — 원문은 원래 게임 길이라 안전, DLC 곡명은 번역 행 없음):
  gamedata  song.name(곡명) / system.unit·title(프리셋 유닛) / profile.*name*(캐릭터 이름·호칭 — 게스트 호칭)
  xmb       exep_init·ranker NPCU_*·NPCP_*(NPC 유닛·프로듀서 — 라이벌·노미네이트 유닛)
  dlc       ranker rankU_*·rankP_*
근거: 공유 노트 ps3feat_dialogue_buffer_ps3.md "Name codes on PS3".
"""
import re

RS_MAX = 31


def is_rs_field(cat, grp, key):
    key = (key or "").split("#")[-1]
    field = re.split(r"[.:/]", key)[-1]
    if cat == "gamedata":
        return (grp == "song" and field == "name") or (grp == "system" and field in ("unit", "title")) or \
               (grp == "profile" and "name" in field)
    if cat == "xmb":
        return grp in ("exep_init", "ranker") and re.match(r"NPC[UP]_", field) is not None
    if cat == "dlc":
        return grp == "ranker" and re.match(r"rank[UP]_", field) is not None
    return False


def units(s):
    return len((s or "").encode("utf-16-le")) // 2


def violations(items):
    """items: [(cat, grp, key, kr)] → 31단위를 넘는 [(cat, grp, key, kr, 단위)]."""
    return [(c, g, k, kr, units(kr)) for c, g, k, kr in items if kr and is_rs_field(c, g, k) and units(kr) > RS_MAX]


_XMB_GRP = {"ranker/ranker_npc.xmb": "ranker", "scene/exep_init.mpc": "exep_init", "scene/exep_init.mpc@x360": "exep_init"}


def xmb_items(xt):
    """xmb_translations.json {rel: {tid: {jp, kr}}} → items."""
    return [("xmb", _XMB_GRP[rel], tid, v.get("kr")) for rel, d in xt.items() if rel in _XMB_GRP for tid, v in d.items()]


def dlc_items(dt):
    """dlc_translations.json {"<grp>/<stem>:<tid>": {kr, ...} 또는 kr} → items."""
    out = []
    for k, v in dt.items():
        kr = v.get("kr") if isinstance(v, dict) else v
        out.append(("dlc", k.split("/", 1)[0], k.split(":", 1)[-1], kr))
    return out


def gate(items, where):
    """넘는 행이 있으면 목록을 찍고 빌드 중단(SystemExit)."""
    bad = violations(items)
    if bad:
        for c, g, k, kr, u in bad[:30]:
            print(f"  ✗ {c}/{g} {k}: {u}단위 — {kr}")
        raise SystemExit(f"[중단] {where}: 대사 치환 문자열(곡명·유닛 이름 등) {len(bad)}개가 {RS_MAX}단위 초과 — "
                         f"게임 스택 버퍼(64B)를 넘어 멈춤. 웹앱에서 줄인 뒤 다시")
    return 0
