#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
게임 데이터 텍스트(웹앱 'gamedata' 분류) → PC 포트 game_kor 주입 (2026-10-23)

대상: 360판 .mpc(pac) 안 내장 XMB의 _text — game_xmb.py 추출 범위와 같음
(NPC 명단·가사 id 접두는 제외: pcport_apply·dance_lyrics 담당).

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
import shutil
import hashlib
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402
from xmb_text import parse_xmb, rebuild_xmb, MAPPING_PATH  # noqa: E402
import game_xmb  # noqa: E402
import platform_audit as PA  # noqa: E402
from pcport_apply import parse_pac, rebuild_pac  # noqa: E402
from dlc_inject import tsk_parse, tsk_build  # noqa: E402

GAME_KOR = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor"
KOR_RES = os.path.join(GAME_KOR, "resource")
LOCK = r"C:\Users\jackfilm\Desktop\imas2pc\gpu_run.lock"
OUT = os.path.join(OUT_DEFAULT, "out_gamedata")
REPORT = os.path.join(OUT, "report.json")


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


def targets():
    """360 원본 트리에서 게임 데이터 XMB가 든 .mpc 상대경로."""
    out = []
    for rel, d in PA.iter_360_sources():
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


def has_scope(d):
    if d[:4] == b"XMB ":
        try:
            return bool(scope_attrs(d))
        except Exception:  # noqa: BLE001
            return False
    return any(has_scope(c) for _i, c in children(d))


def walk(base, orig, tr, st, path=""):
    """기준(game_kor) 버퍼에 원본 구조를 따라 내려가며 대상 XMB를 재빌드. 새 바이트 반환."""
    if orig[:4] == b"XMB ":
        try:
            sc = scope_attrs(orig)
        except Exception:  # noqa: BLE001
            return base
        if not sc:
            return base
        if base[:4] != b"XMB ":
            raise ValueError(f"{path}: game_kor 쪽이 XMB가 아님")
        by_pair, by_jp = tr
        repl = {}
        for ai, tid, jp in sc:
            kr = by_pair.get((tid, jp)) or by_jp.get(jp)
            repl[ai] = kr or jp
            st["kr" if kr else "jp"] += 1
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
    raw = open(os.path.join(KOR_RES, rel), "rb").read()
    d = PA.dec_any(raw, "x360")
    if d is None or d[:4] != b"pac\x00":
        raise ValueError(f"{rel}: game_kor 파일이 pac이 아님")
    return d


def load_orig(rel):
    d = PA.dec_any(open(os.path.join(PA.X360, rel), "rb").read(), "x360")
    if d is None or d[:4] != b"pac\x00":
        raise ValueError(f"{rel}: 360 원본 복호화 실패")
    return d


def translations(code):
    rows = [r for r in PA.fetch_rows() if r["cat"] == "gamedata" and r["kr"]]
    by_pair, by_jp = {}, collections.defaultdict(collections.Counter)
    for r in rows:
        k = r["key"][5:] if r["key"].startswith("x360:") else r["key"]
        tid = k.split(":", 1)[1] if ":" in k else k
        if tid.rsplit(".", 1)[-1].isdigit() and "." in tid:
            tid = tid.rsplit(".", 1)[0]
        by_pair[(tid, r["jp"])] = r["kr"]
        by_jp[r["jp"]][r["kr"]] += 1
    return by_pair, {jp: c.most_common(1)[0][0] for jp, c in by_jp.items()}, len(rows)


def build_file(rel, by_pair, by_jp, stats):
    base, orig = load_base(rel), load_orig(rel)
    st = collections.Counter()
    out = walk(base, orig, (by_pair, by_jp), st, rel)
    stats[rel] = {"kr": st["kr"], "jp": st["jp"], "xmb_changed": st["xmb"], "size": [len(base), len(out)]}
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
    by_pair, by_jp, n = translations(a.code)
    print(f"웹앱 gamedata 번역 {n}행")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    stats = {}
    mapping = set(json.load(open(MAPPING_PATH, encoding="utf-8")).keys())
    for rel in targets():
        _base, out = build_file(rel, by_pair, by_jp, stats)
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(out)
    miss = collections.Counter(ch for v in by_jp.values() for ch in v if "가" <= ch <= "힣" and ch not in mapping)
    rep = {"files": stats, "font_missing": dict(miss.most_common()), "at": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(rep, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for rel, s in stats.items():
        print(f"  {rel}: 한국어 {s['kr']}칸 / 일본어 유지 {s['jp']}칸, XMB {s['xmb_changed']}개, "
              f"{s['size'][0]:,}→{s['size'][1]:,}B")
    print(f"합계 한국어 {sum(s['kr'] for s in stats.values())}칸 → {OUT}")
    if miss:
        print(f"⚠ 폰트 매핑 2,359자에 없는 한글 {len(miss)}자(빈 글리프 가능): {''.join(miss)}")


def check(out, base, orig, path):
    """out(빌드) vs base(game_kor) vs orig(360 원본) 재귀 비교."""
    if orig[:4] == b"XMB ":
        try:
            sc = scope_attrs(orig)
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


def cmd_deploy(_a):
    if os.path.exists(LOCK) or os.system('tasklist /FI "IMAGENAME eq imas2pc.exe" | find /I "imas2pc.exe" >nul') == 0:
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roundtrip")
    b = sub.add_parser("build")
    b.add_argument("--code", required=True)
    sub.add_parser("validate")
    sub.add_parser("deploy")
    a = ap.parse_args()
    {"roundtrip": cmd_roundtrip, "build": cmd_build, "validate": cmd_validate, "deploy": cmd_deploy}[a.cmd](a)


if __name__ == "__main__":
    main()
