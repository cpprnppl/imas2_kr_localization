#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
게임 데이터 텍스트(웹앱 'gamedata' 분류) → PC 포트 game_kor 주입 (2026-10-23)

대상: 360판 .mpc(pac) 안 내장 XMB의 _text — game_xmb.py 추출 범위와 같음
(NPC 명단·가사 id 접두는 제외: pcport_apply·dance_lyrics 담당).
+ gscript 밖 pac 속 내장 SCB(멤버 선택 소개 대사·ScheduleSelect·dress_select·mail_produce·attract, 2026-10-23
  전수 조사로 발견 — 웹앱엔 gscript 같은 대사로 있지만 주입기가 없었다): 게임 스크립트 행 번역을 원문 일치로,
  excel2scb와 같은 MSG 재작성 경로·validate_output 게이트.

원칙
  - 기준 파일 = game_kor의 **현재** 파일(폰트 주입된 initialFix·이미지 주입본 보존).
    → pcport_apply deploy 뒤에 돌린다(그 도구는 같은 파일을 원본에서 다시 만든다).
  - 바꿀 칸은 360 원본(unpack\imas2, 메모리 복호화)의 같은 pac 항목·같은 attr 번호로 정한다.
    번역이 있으면 한국어, 없으면 원본 일본어로 되돌림 → 몇 번 돌려도 결과가 같다.
  - 번역 찾기: (id, 원문) 일치 우선, 없으면 같은 원문의 번역(한 원문에 번역이 여럿이면 다수결).
  - XMB 재빌드는 xmb_text.rebuild_xmb(값 섹션 재배치, 비 _text 불변 검증), pac은 pcport_apply.rebuild_pac.

  python gamedata_apply.py roundtrip          # 무수정 왕복: 번역 없이 재빌드 = 기준 파일 바이트 동일
  python gamedata_apply.py build --code <팀암호>   # out_gamedata\ 에 평문 pac + 보고
  python gamedata_apply.py validate           # 구조 게이트(재파싱·비대상 칸/항목 불변·번역 일치)
  python gamedata_apply.py deploy             # 게이트 통과 시에만 game_kor로(백업·매니페스트)
"""
import os
import sys
import json
import time
import struct
import shutil
import hashlib
import argparse
import subprocess
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import re  # noqa: E402
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402
from xmb_text import parse_xmb, rebuild_xmb, MAPPING_PATH  # noqa: E402
import game_xmb  # noqa: E402
import platform_audit as PA  # noqa: E402
from pcport_apply import parse_pac, rebuild_pac, NPC_PREFIX  # noqa: E402
from dlc_inject import tsk_parse, tsk_build  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scb"))
import scb_common as C  # noqa: E402
import excel2scb as E  # noqa: E402
import validate_output as V  # noqa: E402

FONT_MAP = E.load_font_mapping()     # 직접 한글 모드면 {} (gscript 빌드와 같은 규칙)

GAME_KOR = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor"
KOR_RES = os.path.join(GAME_KOR, "resource")
LOCK = r"C:\Users\jackfilm\Desktop\imas2pc\gpu_run.lock"
OUT = os.path.join(OUT_DEFAULT, "out_gamedata")
REPORT = os.path.join(OUT, "report.json")
PLAT = "x360"
PS3_ORIG = os.path.join(OUT_DEFAULT, "ps3_res_orig")          # PS3 리소스 순정 사본(대상 파일만, 읽기 전용 취급)
PS3_SKIP = {"scene\\attract.mpc"}                            # tools/scb/patch_attract.py 담당(§20)
HANGUL = re.compile("[가-힣]")


def anc_id(nodes, entries, ni):
    while ni != 0xFFFF:
        a = entries[ni].get("attrs", {})
        if a.get("id"):
            return a["id"]
        ni = nodes[ni]["parent"]
    return None


def scope_attrs(seg):
    """XMB 한 개에서 게임 데이터 대상 _text attr: [(attr_idx, tid, text)] (game_xmb와 같은 범위)."""
    p = parse_xmb(seg, 0)
    nodes, ents = p["nodes"], p["entries"]
    out = []
    for e in ents:
        if "text" not in e or not e["text"] or not game_xmb.JP.search(e["text"]):
            continue
        ni = e["node"]
        field_ni = nodes[ni]["parent"]
        owner_ni = nodes[field_ni]["parent"] if field_ni != 0xFFFF else 0xFFFF
        field = nodes[field_ni]["name"] if field_ni != 0xFFFF else "text"
        tid = anc_id(nodes, ents, ni) or f"n{owner_ni}.{field}"
        if tid.split("_")[0] in game_xmb.EXCLUDE_IDPFX:
            continue
        out.append((e["_text_attr"], tid, e["text"]))
    return out


def set_plat(plat):
    """--plat ps3: 원본·기준 = PS3 순정 사본(ps3_res_orig — 첫 실행 때 게임 폴더에서 한글 없음 확인 후 복사),
    산출 out_gamedata_ps3. PS3 .mpc는 평문 pac이라 재암호화 불필요. 배포는 KOR 승인 전까지 막아 둔다."""
    global PLAT, OUT, REPORT
    PLAT = plat
    OUT = os.path.join(OUT_DEFAULT, "out_gamedata_ps3" if plat == "ps3" else "out_gamedata")
    REPORT = os.path.join(OUT, "report.json")


def targets():
    """원본 트리에서 게임 데이터 XMB·내장 SCB가 든 .mpc 상대경로."""
    out = []
    src = ((rel, d) for rel, d in game_xmb.iter_sources()) if PLAT == "ps3" else PA.iter_360_sources()
    for rel, d in src:
        if PLAT == "ps3" and rel.lower() in PS3_SKIP:
            continue
        if d is None or not rel.lower().endswith(".mpc") or d[:4] != b"pac\x00":
            continue
        if has_scope(d):
            out.append(rel)
    return out


def children(d):
    """컨테이너 항목 [(index, bytes)] — pac(헤더 +0x38 기준)·TSK. 그 외는 []."""
    if d[:4] == b"pac\x00":
        ents, ds = parse_pac(d)
        return [(e["i"], d[ds + e["ofs"]:ds + e["ofs"] + e["size"]]) for e in ents]
    if d[:4] == b"TSK ":
        _n, ents = tsk_parse(d)
        return [(i, d[o:o + sz]) for i, (sz, o) in enumerate(ents)]
    return []


def is_scb_dec(d):
    """gscript 밖 pac 속에 든 대사 묶음(member_select 소개 대사·ScheduleSelect·dress_select·mail_produce·attract).
    구조는 gscript dec 파일과 같다: pac(데이터 0x80) → [SCB, 컷씬 pac]."""
    if d[:4] != b"pac\x00" or len(d) < 0x100 or struct.unpack_from(">I", d, 0x38)[0] != 0x80:
        return False
    return d[0x80:0x84] == b"SCB\x00"


def scb_rebuild(base, orig, scb_tr, st, path):
    """내장 SCB의 MSG를 excel2scb와 같은 경로(rewrap·MSG 표 재작성·pac 헤더 4필드)로 다시 만든다.
    기준은 360 원본(orig) — 번역 없는 줄은 원문 그대로라 몇 번 돌려도 같다. game_kor 쪽(base)은
    MSG 말고는 원본과 같아야 한다(컷씬 pac 등 다른 주입이 없음을 확인)."""
    secs = C.parse_section_dir(orig)
    msg_abs, msg_size = secs["MSG"]
    pp = E.parse_msg_table(orig, msg_abs)
    if base != orig:
        bk, ok = children(base), children(orig)
        if len(bk) != len(ok) or bk[1][1] != ok[1][1]:
            raise ValueError(f"{path}: game_kor 쪽 내장 SCB의 컷씬 pac이 원본과 다름 — 다른 주입과 겹침")
    new = {}
    choices = E.choice_indices(orig)
    for s in pp["strings"]:
        kr = scb_tr.get(s["text"])
        if kr and not E.is_garbage_translation(kr):
            new[s["index"]] = E.rewrap(kr, s["index"] in choices)
    st["scb_kr"] += len(new)
    st["scb_jp"] += sum(1 for s in pp["strings"] if s["text"].strip() and s["index"] not in new)
    if not new:
        return orig
    out, _delta = E.replace_msg_section(orig, msg_abs, msg_size, E.build_msg_block(pp, new, FONT_MAP, msg_size))
    st["scb"] += 1
    return out


def npc_scope(seg):
    """NPC 명단 XMB의 [(attr, id, text)] — PS3 리소스 주입(--plat ps3)에서만 대상. 360은 pcport_apply 담당."""
    if PLAT != "ps3":
        return []
    from xmb_text import collect_texts
    ts = collect_texts(parse_xmb(seg, 0))
    if not any(t["id"].startswith(NPC_PREFIX) for t in ts):
        return []
    return [(t["attr"], t["id"], t["text"]) for t in ts if t["id"].startswith(NPC_PREFIX)]


def has_scope(d):
    if is_scb_dec(d):
        return True
    if d[:4] == b"XMB ":
        try:
            return bool(scope_attrs(d)) or bool(npc_scope(d))
        except Exception:  # noqa: BLE001
            return False
    return any(has_scope(c) for _i, c in children(d))


def walk(base, orig, tr, st, path=""):
    """기준(game_kor) 버퍼에 원본 구조를 따라 내려가며 대상 XMB·내장 SCB를 재빌드. 새 바이트 반환."""
    if is_scb_dec(orig):
        return scb_rebuild(base, orig, tr[2], st, path)
    if orig[:4] == b"XMB ":
        try:
            sc = scope_attrs(orig)
            npc = npc_scope(orig) if len(tr) > 3 and tr[3] else []
        except Exception:  # noqa: BLE001
            return base
        if not sc and not npc:
            return base
        if base[:4] != b"XMB ":
            raise ValueError(f"{path}: game_kor 쪽이 XMB가 아님")
        by_pair, by_jp = tr[:2]
        repl = {}
        for ai, tid, jp in sc:
            kr = by_pair.get((tid, jp)) or by_jp.get(jp)
            repl[ai] = kr or jp
            st["kr" if kr else "jp"] += 1
        if npc:     # PS3 NPC 명단 표(360은 pcport_apply 담당) — 원문 일치 규칙은 360과 같은 npc_kr_for
            from pcport_apply import npc_kr_for
            krs = npc_kr_for([{"id": t, "text": j, "attr": a} for a, t, j in npc], tr[3])
            for ai, tid, jp in npc:
                repl[ai] = krs.get(tid) or jp
                st["npc_kr" if krs.get(tid) else "npc_jp"] += 1
        new = rebuild_xmb(base, 0, repl, lambda *a: None, allow_grow=True)
        st["xmb"] += new != base
        return new
    oc, bc = children(orig), children(base)
    if not oc:
        return base
    if len(oc) != len(bc) or orig[:4] != base[:4]:
        raise ValueError(f"{path}: 컨테이너 구조 다름(game_kor {len(bc)} / 원본 {len(oc)})")
    blobs = {}
    for (i, o), (_j, b) in zip(oc, bc):
        nb = walk(b, o, tr, st, f"{path}/{i}")
        if nb != b:
            blobs[i] = nb
    if not blobs:
        return base
    if base[:4] == b"pac\x00":
        ents, ds = parse_pac(base)
        return rebuild_pac(base, ents, ds, blobs)
    return tsk_build(base, blobs)


def load_base(rel):
    if PLAT == "ps3":            # PS3 리소스엔 아직 다른 주입이 없다(2026-10-23 확인) — 기준 = 순정
        return load_orig(rel)
    raw = open(os.path.join(KOR_RES, rel), "rb").read()
    d = PA.dec_any(raw, "x360")
    if d is None or d[:4] != b"pac\x00":
        raise ValueError(f"{rel}: game_kor 파일이 pac이 아님")
    return d


def has_hangul_in_scope(d):
    if is_scb_dec(d):
        return any(HANGUL.search(s["text"]) for s in
                   E.parse_msg_table(d, C.parse_section_dir(d)["MSG"][0])["strings"])
    if d[:4] == b"XMB ":
        try:
            return any(HANGUL.search(t) for _a, _t, t in scope_attrs(d))
        except Exception:  # noqa: BLE001
            return False
    return any(has_hangul_in_scope(c) for _i, c in children(d))


def ps3_pristine(rel):
    """PS3 순정 사본. 없으면 게임 폴더 파일을 복사하되, 대상 칸에 한글이 이미 있으면(패치본) 거부."""
    dst = os.path.join(PS3_ORIG, rel)
    if not os.path.exists(dst):
        d = open(os.path.join(JP_ROOT, rel), "rb").read()
        if has_hangul_in_scope(d):
            raise ValueError(f"{rel}: PS3 게임 폴더 파일에 이미 한글 — 순정이 아님, 사본 생성 거부")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(d)
    return open(dst, "rb").read()


def load_orig(rel):
    if PLAT == "ps3":
        d = ps3_pristine(rel)
        if d[:4] != b"pac\x00":
            raise ValueError(f"{rel}: PS3 파일이 평문 pac이 아님")
        return d
    d = PA.dec_any(open(os.path.join(PA.X360, rel), "rb").read(), "x360")
    if d is None or d[:4] != b"pac\x00":
        raise ValueError(f"{rel}: 360 원본 복호화 실패")
    return d


def translations(code):
    allr = PA.fetch_rows(cats=("gamedata", "script"))
    rows = [r for r in allr if r["cat"] == "gamedata" and r["kr"]]
    by_pair, by_jp = {}, collections.defaultdict(collections.Counter)
    for r in rows:
        k = r["key"][5:] if r["key"].startswith("x360:") else r["key"]
        tid = k.split(":", 1)[1] if ":" in k else k
        if tid.rsplit(".", 1)[-1].isdigit() and "." in tid:
            tid = tid.rsplit(".", 1)[0]
        by_pair[(tid, r["jp"])] = r["kr"]
        by_jp[r["jp"]][r["kr"]] += 1
    # 내장 SCB(소개 대사 등)는 gscript 대사와 같은 원문 — 게임 스크립트 행 번역을 원문 일치로 쓴다(다수결)
    scb = collections.defaultdict(collections.Counter)
    for r in allr:
        if r["cat"] == "script" and r["kr"]:
            scb[r["jp"]][r["kr"]] += 1
    scb_tr = {jp: c.most_common(1)[0][0] for jp, c in scb.items()}
    by_jp1 = {jp: c.most_common(1)[0][0] for jp, c in by_jp.items()}
    # initialTemp 라이벌 유닛 프리셋(producer·unit·title)은 NPC 명단과 같은 이름 — 게임 데이터 행에 없으면
    # NPC 명단(웹 XMB exep_init, 360 전용 x360: 포함) 번역을 원문 일치로 쓴다 (2026-10-23 전수 조사)
    xt = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    for k in ("scene/exep_init.mpc", "scene/exep_init.mpc@x360"):
        for v in xt.get(k, {}).values():
            if v.get("kr") and v.get("jp") and v["jp"] not in by_jp1:
                by_jp1[v["jp"]] = v["kr"]
    return by_pair, by_jp1, len(rows), scb_tr


def build_file(rel, by_pair, by_jp, stats, scb_tr=None):
    base, orig = load_base(rel), load_orig(rel)
    st = collections.Counter()
    out = walk(base, orig, (by_pair, by_jp, scb_tr or {}), st, rel)
    stats[rel] = {"kr": st["kr"], "jp": st["jp"], "xmb_changed": st["xmb"], "size": [len(base), len(out)],
                  "scb_kr": st["scb_kr"], "scb_jp": st["scb_jp"], "scb_changed": st["scb"]}
    return base, out


def cmd_roundtrip(_a):
    """번역 없이(대상 칸 전부 원본 일본어로) 재빌드 → game_kor 현재 파일과 바이트 동일해야 한다
    (game_kor에 아직 게임 데이터 주입이 없는 상태에서 의미 있음)."""
    bad = []
    rels = targets()
    for rel in rels:
        st = {}
        base, out = build_file(rel, {}, {}, st)
        if out != base:
            bad.append(rel)
        print(f"  {rel}: {'동일' if out == base else '다름'} (대상 {st[rel]['jp']}칸)")
    print(f"무수정 왕복: {len(rels) - len(bad)}/{len(rels)} 바이트 동일")
    sys.exit(1 if bad else 0)


def cmd_build(a):
    by_pair, by_jp, n, scb_tr = translations(a.code)
    print(f"웹앱 gamedata 번역 {n}행, 내장 SCB용 게임 스크립트 번역 원문 {len(scb_tr):,}개")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    stats = {}
    mapping = set(json.load(open(MAPPING_PATH, encoding="utf-8")).keys())
    for rel in targets():
        _base, out = build_file(rel, by_pair, by_jp, stats, scb_tr)
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(out)
    miss = collections.Counter(ch for v in by_jp.values() for ch in v if "가" <= ch <= "힣" and ch not in mapping)
    rep = {"files": stats, "font_missing": dict(miss.most_common()), "at": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(rep, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for rel, s in stats.items():
        print(f"  {rel}: 한국어 {s['kr']}칸 / 일본어 유지 {s['jp']}칸, XMB {s['xmb_changed']}개"
              + (f", 내장 대사 한국어 {s['scb_kr']}줄 / 일본어 {s['scb_jp']}줄" if s["scb_kr"] or s["scb_jp"] else "")
              + f", {s['size'][0]:,}→{s['size'][1]:,}B")
    print(f"합계 한국어 {sum(s['kr'] for s in stats.values())}칸 → {OUT}")
    if miss:
        print(f"⚠ 폰트 매핑 2,359자에 없는 한글 {len(miss)}자(빈 글리프 가능): {''.join(miss)}")


def check(out, base, orig, path):
    """out(빌드) vs base(game_kor) vs orig(360 원본) 재귀 비교."""
    if is_scb_dec(orig):
        # 내장 SCB: gscript 산출물과 같은 게이트(validate_output.validate_dec) + 컷씬 pac 불변 + 줄 수 불변
        issues, _h = V.validate_dec(out, orig)
        if issues:
            raise ValueError(f"{path}: 내장 SCB {issues[:3]}")
        if children(out)[1][1] != children(orig)[1][1]:
            raise ValueError(f"{path}: 내장 SCB 컷씬 pac 변동")
        po = E.parse_msg_table(orig, C.parse_section_dir(orig)["MSG"][0])
        pn = E.parse_msg_table(out, C.parse_section_dir(out)["MSG"][0])
        if po["count"] != pn["count"]:
            raise ValueError(f"{path}: 내장 SCB 줄 수 변동")
        return
    if orig[:4] == b"XMB ":
        try:
            sc = scope_attrs(orig) + npc_scope(orig)
        except Exception:  # noqa: BLE001
            sc = []
        if not sc:
            if out != base:
                raise ValueError(f"{path}: 대상 아닌 XMB 변동")
            return
        pn, pb = parse_xmb(out, 0), parse_xmb(base, 0)
        if len(pn["attrs"]) != len(pb["attrs"]) or any(a["name"] != b["name"] for a, b in zip(pn["attrs"], pb["attrs"])):
            raise ValueError(f"{path}: attr 구조 변동")
        scope = {ai for ai, _t, _j in sc}
        for en, eb in zip(pn["entries"], pb["entries"]):
            if en.get("attrs") != eb.get("attrs"):
                raise ValueError(f"{path}: 비 _text 값 변동")
            if "text" in eb and eb["_text_attr"] not in scope and en.get("text") != eb.get("text"):
                raise ValueError(f"{path}: 대상 아닌 _text 변동")
        return
    oc, bc, nc = children(orig), children(base), children(out)
    if not oc:
        if out != base:
            raise ValueError(f"{path}: 대상 아닌 항목 변동")
        return
    if not (len(oc) == len(bc) == len(nc)):
        raise ValueError(f"{path}: 항목 수 변동")
    for (i, o), (_j, b), (_k, n) in zip(oc, bc, nc):
        check(n, b, o, f"{path}/{i}")


def validate_all(log=print):
    rep = json.load(open(REPORT, encoding="utf-8"))
    bad = []
    for rel in rep["files"]:
        try:
            check(open(os.path.join(OUT, rel), "rb").read(), load_base(rel), load_orig(rel), rel)
        except Exception as ex:  # noqa: BLE001
            bad.append((rel, str(ex)))
    log(f"검증 대상 {len(rep['files'])}개, 구조 오류 {len(bad)}")
    for b in bad:
        log(f"   {b}")
    return not bad


def cmd_validate(_a):
    ok = validate_all()
    print("✅ 통과" if ok else "❌ 배포 금지")
    sys.exit(0 if ok else 1)


def cmd_deploy(a):
    if a.other_disc_ok:
        from pcport_apply import game_kor_busy
        why = game_kor_busy(True)
        if why:
            sys.exit(f"❌ {why} — 배포 보류")
    elif os.path.exists(LOCK) or "imas2pc.exe" in subprocess.run(["tasklist"], capture_output=True, text=True,
                                                                  errors="replace").stdout.lower():
        sys.exit("❌ 게임 실행 중(gpu_run.lock 또는 imas2pc.exe) — 배포 보류")
    if not validate_all():
        sys.exit("❌ 구조 검증 실패 — 배포 중단")
    rep = json.load(open(REPORT, encoding="utf-8"))
    bak = GAME_KOR + "_backup_gamedata_" + time.strftime("%Y%m%d_%H%M%S")
    man = {}
    for rel in rep["files"]:
        src, dst = os.path.join(OUT, rel), os.path.join(KOR_RES, rel)
        os.makedirs(os.path.dirname(os.path.join(bak, rel)), exist_ok=True)
        shutil.copy2(dst, os.path.join(bak, rel))
        shutil.copyfile(src, dst)
        man[rel.replace("\\", "/")] = hashlib.sha256(open(dst, "rb").read()).hexdigest()
    json.dump({"at": rep["at"], "files": man}, open(os.path.join(bak, "manifest.json"), "w"), indent=1)
    print(f"{len(man)}개 배포 → {KOR_RES}\n이전 파일 백업: {bak}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plat", choices=["x360", "ps3"], default="x360",
                    help="ps3 = PS3 리소스(순정 사본 기준, 빌드·검증만 — 배포는 KOR 승인 대기)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roundtrip")
    b = sub.add_parser("build")
    b.add_argument("--code", required=True)
    sub.add_parser("validate")
    d = sub.add_parser("deploy")
    d.add_argument("--other-disc-ok", action="store_true",
                   help="gpu_run.lock 주인이 game_kor가 아닌 디스크로 돌 때(KOR 확인 후)만")
    a = ap.parse_args()
    set_plat(a.plat)
    if a.plat == "ps3" and a.cmd == "deploy":
        sys.exit("PS3 리소스 배포 경로는 KOR 승인 전 — 빌드·검증만 (out_gamedata_ps3)")
    {"roundtrip": cmd_roundtrip, "build": cmd_build, "validate": cmd_validate, "deploy": cmd_deploy}[a.cmd](a)


if __name__ == "__main__":
    main()
