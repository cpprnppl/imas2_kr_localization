#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
PS3 리소스 한글 주입기 (2026-10-23, KOR 결정 — 전수 조사 결과 PS3 게임 폴더 리소스에 한글이 하나도 안 들어가 있었다)

gscript(SCB)·attract(patch_attract)·폰트(deploy_fonts) 밖의 PS3 resource 파일:
  게임 데이터 XMB(gamedata 웹 행)·내장 SCB(멤버 선택 소개 대사 등)·NPC 명단 표·install/ranker 단독 XMB
  + 이미지(inject_image_text.py 산출 patched\ — 같은 순정에서 텍스처 제자리 교체).

원칙 (CLAUDE.md 절대 규칙과 같은 수준)
  1. 원본 = Desktop\imas2_image_text\ps3_res_orig 의 순정 사본. 처음 만들 때 게임 폴더 파일이
     (a) 대상 칸 한글 0자, (b) 추출 캐시(_cache\jp, 별도 시점에 만든 복호화 사본)와 평문 sha256 일치를 확인한다.
     initialFix/initialTemp는 deploy_fonts가 폰트(NFH/NUT)를 제자리 주입한 상태가 기준(텍스트는 순정 — 한글 0 확인).
     게임 폴더 파일은 이후 원본으로 쓰지 않는다(재패치 오염 방지).
  2. 빌드 = 순정 평문 → (이미지 층) → 텍스트 층(gamedata_apply.walk: XMB 재빌드·내장 SCB MSG 재작성·pac 헤더 갱신)
     → 원본이 암호화본이면 같은 키·prefix·풋터로 재암호화하고 복호화 왕복을 비교한다.
  3. 검증 게이트(validate): 구조 재파싱·비대상 칸/항목 불변(gamedata_apply.check)·단독 XMB 비텍스트 불변·
     복호화 왕복·폰트(게임 폴더 NFH 직접 등록판)에 없는 한글 0.
  4. 배포(deploy): 게이트 통과 + RPCS3 미실행일 때만. 바꿀 파일마다 USRDIR\_backup_ps3res_<시각>\ 에 백업 +
     manifest.json(이전/이후 sha256). restore = 마지막(또는 지정) 백업으로 되돌림(현재 sha가 배포본일 때만).
     gscript·순정 SCB 백업(gscript - 복사본)·attract·폰트 파일은 건드리지 않는다.

  python ps3_res_apply.py snapshot                 # 순정 사본 생성·검증 (이미 있으면 검증만)
  python ps3_res_apply.py build --code <팀암호>    # out_ps3res\ (게임 폴더와 같은 형태: 암호화본은 재암호화)
  python ps3_res_apply.py validate
  python ps3_res_apply.py deploy                   # 게이트 → 백업·매니페스트 → 교체
  python ps3_res_apply.py restore [--dir <백업폴더>]
"""
import os
import re
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
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402
from xmb_text import parse_xmb, collect_texts, rebuild_xmb  # noqa: E402
import gamedata_apply as G  # noqa: E402
from dlc_inject import Cipher, KEYDIR, MAGIC  # noqa: E402

G.set_plat("ps3")
PS3_ORIG = G.PS3_ORIG
SNAP_MANIFEST = os.path.join(PS3_ORIG, "manifest.json")
CACHE_JP = os.path.join(OUT_DEFAULT, "_cache", "jp")
PATCHED_IMG = os.path.join(OUT_DEFAULT, "patched")          # inject_image_text.py 산출(평문)
OUT = os.path.join(OUT_DEFAULT, "out_ps3res")
REPORT = os.path.join(OUT, "report.json")
USRDIR = os.path.dirname(JP_ROOT)
FONT_INJECTED = {"initialfix.mpc", "initialtemp.mpc"}       # deploy_fonts가 폰트를 제자리 주입한 파일
STANDALONE = {"text\\install.xmb": "text/install.xmb", "ranker\\ranker_npc.xmb": "ranker/ranker_npc.xmb"}
NPC_FILES = ["game\\alf\\alf_common.mpc", "interface\\NationwideRanking.mpc", "interface\\ScheduleSelect.mpc",
             "scene\\produce_etc.mpc", "scene\\exep_init.mpc", "scene\\exep_commu.mpc"]
NEVER = re.compile(r"^(gscript|tools|_)|^scene\\attract\.mpc$|im2_font", re.I)
HANGUL = re.compile("[가-힣]")


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 암호
_TABLE = None


def ciphers():
    global _TABLE
    if _TABLE is None:
        _TABLE = open(os.path.join(KEYDIR, "table.bin"), "rb").read()
    return [Cipher(_TABLE[o:o + 384], 64) for o in (0, 384, 768)]


def open_raw(raw):
    """(평문, (cipher, ctx) 또는 None). 복호화→무수정 재암호화가 원본과 바이트 동일한 표만 인정."""
    if raw[:4] in MAGIC:
        return raw, None
    for c in ciphers():
        try:
            plain, ctx = c.decrypt(raw)
        except Exception:  # noqa: BLE001
            continue
        if Cipher.encrypt(plain, ctx) == raw:
            return plain, (c, ctx)
    raise ValueError("PS3 복호화 실패(왕복 일치하는 표 없음)")


# ---------------------------------------------------------------- 순정 사본
def candidates(rescan=False):
    """텍스트 대상(gamedata 범위·내장 SCB·NPC 표) + 단독 XMB + 이미지 patched 파일.
    순정 사본 매니페스트가 있으면 그 목록이 기준(배포 뒤 게임 폴더를 다시 훑으면 번역된 칸이 범위에서 빠진다) —
    대상이 늘었을 때만 --rescan(배포 전 상태에서)."""
    if os.path.exists(SNAP_MANIFEST) and not rescan:
        rels = set(json.load(open(SNAP_MANIFEST, encoding="utf-8")))
        if os.path.isdir(PATCHED_IMG):
            for dp, _dn, fns in os.walk(PATCHED_IMG):
                rels |= {os.path.relpath(os.path.join(dp, fn), PATCHED_IMG) for fn in fns}
        return sorted(r for r in rels if not NEVER.search(r) and os.path.exists(os.path.join(JP_ROOT, r)))
    rels = set(G.targets()) | set(NPC_FILES) | set(STANDALONE)
    if os.path.isdir(PATCHED_IMG):
        for dp, _dn, fns in os.walk(PATCHED_IMG):
            for fn in fns:
                rels.add(os.path.relpath(os.path.join(dp, fn), PATCHED_IMG))
    return sorted(r for r in rels if not NEVER.search(r) and os.path.exists(os.path.join(JP_ROOT, r)))


def text_has_hangul(plain):
    if plain[:4] == b"XMB ":
        try:
            return any(HANGUL.search(t["text"]) for t in collect_texts(parse_xmb(plain, 0)))
        except Exception:  # noqa: BLE001
            return False
    return G.has_hangul_in_scope(plain)


def cmd_snapshot(a=None, quiet=False):
    man = json.load(open(SNAP_MANIFEST, encoding="utf-8")) if os.path.exists(SNAP_MANIFEST) else {}
    bad = []
    for rel in candidates(getattr(a, "rescan", False)):
        dst = os.path.join(PS3_ORIG, rel)
        if rel in man:
            if not os.path.exists(dst) or man[rel]["sha_raw"] != sha(open(dst, "rb").read()):
                bad.append(f"{rel}: 순정 사본이 없거나 sha가 매니페스트와 다름")
            continue
        # 새 항목: (gamedata_apply --plat ps3가 먼저 만든 무검증 사본이 있으면 그것도) 게임 폴더와 같고 검증 통과해야
        raw = open(os.path.join(JP_ROOT, rel), "rb").read()
        if os.path.exists(dst) and open(dst, "rb").read() != raw:
            bad.append(f"{rel}: 기존 사본과 게임 폴더 파일이 다름 — 수동 확인 필요")
            continue
        plain, enc = open_raw(raw)
        if text_has_hangul(plain):
            bad.append(f"{rel}: 게임 폴더 파일에 이미 한글 — 순정 아님, 사본 거부")
            continue
        c = os.path.join(CACHE_JP, rel)
        cache = sha(open(c, "rb").read()) == sha(plain) if os.path.exists(c) else None
        note = ""
        if rel.lower() in FONT_INJECTED:
            note = "deploy_fonts 폰트 제자리 주입 상태(텍스트 순정) — 폰트 보존을 위해 이 상태가 기준"
        elif cache is False:
            bad.append(f"{rel}: 추출 캐시와 평문 sha 불일치 — 순정 여부 불명, 사본 거부")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(raw)
        man[rel] = {"sha_raw": sha(raw), "sha_plain": sha(plain), "encrypted": enc is not None,
                    "cache_match": cache, "mtime": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(JP_ROOT, rel)))),
                    "at": time.strftime("%Y-%m-%d %H:%M"), "note": note}
    os.makedirs(PS3_ORIG, exist_ok=True)
    json.dump(man, open(SNAP_MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not quiet:
        n_c = sum(1 for v in man.values() if v["cache_match"])
        print(f"순정 사본 {len(man)}개 ({PS3_ORIG}) — 추출 캐시 sha 일치 {n_c}, 폰트 주입 상태 기준 "
              f"{sum(1 for v in man.values() if v['note'])}, 암호화본 {sum(1 for v in man.values() if v['encrypted'])}")
    for b in bad:
        print("  ❌", b)
    if bad:
        sys.exit(1)
    return man


def pristine(rel):
    raw = open(os.path.join(PS3_ORIG, rel), "rb").read()
    return open_raw(raw)


# ---------------------------------------------------------------- 빌드
def image_layer(rel, plain):
    """inject_image_text 산출이 있으면 그 평문(같은 순정 캐시에서 만든 것인지 확인)."""
    p = os.path.join(PATCHED_IMG, rel)
    if not os.path.exists(p):
        return plain, False
    c = os.path.join(CACHE_JP, rel)
    if not os.path.exists(c) or sha(open(c, "rb").read()) != sha(plain):
        raise ValueError(f"{rel}: 이미지 산출의 원본 캐시가 순정 사본과 다름 — inject_image_text 재실행 필요")
    img = open(p, "rb").read()
    if len(img) != len(plain):
        raise ValueError(f"{rel}: 이미지 산출 크기가 원본과 다름(제자리 교체 원칙 위반)")
    return img, True


def standalone(rel, plain, xmb_tr, st):
    """단독 XMB(install·ranker_npc): id·원문 일치 번역만. 값 섹션은 파일 끝이라 확장 허용."""
    ent = xmb_tr.get(STANDALONE[rel], {})
    repl = {}
    for t in collect_texts(parse_xmb(plain, 0)):
        e = ent.get(t["id"])
        if e and e.get("kr") and e.get("jp") in (None, "", t["text"]):
            repl[t["attr"]] = e["kr"]
    st["xmb_kr"] += len(repl)
    if not repl:
        return plain
    return rebuild_xmb(plain, 0, repl, lambda *a: None, allow_grow=True)


def build_one(rel, tr, st):
    orig, enc = pristine(rel)
    base, has_img = image_layer(rel, orig)
    st["img"] += has_img
    if rel in STANDALONE:
        out = standalone(rel, base, tr[3], st)
    elif orig[:4] == b"pac\x00":
        out = G.walk(base, orig, tr, st, rel)
    else:
        out = base
    if enc:
        c, ctx = enc
        raw = Cipher.encrypt(out, ctx)
        back, _ctx = c.decrypt(raw)
        if back[:len(out)] != out or any(back[len(out):]):
            raise ValueError(f"{rel}: 재암호화 왕복 불일치")
        return orig, base, out, raw
    return orig, base, out, out


def translations(code):
    by_pair, by_jp, n, scb_tr = G.translations(code)
    xmb_tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    return (by_pair, by_jp, scb_tr, xmb_tr), n


def cmd_build(a):
    cmd_snapshot(quiet=True)
    tr, n = translations(a.code)
    print(f"웹앱 gamedata 번역 {n}행, 내장 SCB용 대사 원문 {len(tr[2]):,}, XMB 번역 파일 {len(tr[3])}")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    files = {}
    for rel in candidates():
        st = collections.Counter()
        orig, _base, out, raw = build_one(rel, tr, st)
        if out == orig:
            continue
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(raw)
        files[rel] = {k: v for k, v in st.items()} | {"size": [len(orig), len(out)], "sha": sha(raw)}
        print(f"  {rel}: " + ", ".join(f"{k} {v}" for k, v in st.items() if v) + f"  {len(orig):,}→{len(out):,}B")
    json.dump({"at": time.strftime("%Y-%m-%d %H:%M"), "files": files}, open(REPORT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    tot = collections.Counter()
    for v in files.values():
        tot.update({k: v[k] for k in v if isinstance(v[k], int)})
    print(f"{len(files)}개 → {OUT}  합계 {dict(tot)}")


# ---------------------------------------------------------------- 검증
def font_codes():
    """게임 폴더 폰트(직접 등록판) NFH의 코드 집합 — loose im2_font.nfh·im2_font_l.nfh 둘 다."""
    codes = {}
    for fn in ("im2_font.nfh", "im2_font_l.nfh"):
        d = open(os.path.join(JP_ROOT, fn), "rb").read()
        s = set()
        for o in range(0x474, len(d) - 31, 32):
            s.add(int.from_bytes(d[o + 18:o + 20], "big"))
        codes[fn] = s
    return codes


def texts_of(plain):
    out = []
    if plain[:4] == b"XMB ":
        out += [t["text"] for t in collect_texts(parse_xmb(plain, 0))]
    elif G.is_scb_dec(plain):
        out += [s["text"] for s in G.E.parse_msg_table(plain, G.C.parse_section_dir(plain)["MSG"][0])["strings"]]
    else:
        for _i, c in G.children(plain):
            out += texts_of(c)
    return out


def validate_all(log=print):
    rep = json.load(open(REPORT, encoding="utf-8"))
    codes = font_codes()
    # DIRECT_HANGUL(원시 한글) = 게임 폴더 폰트가 직접 등록판이어야 하고, initialFix 내장 NFH도 같은 판이어야 한다
    fix = pristine("initialFix.mpc")[0] if os.path.exists(os.path.join(PS3_ORIG, "initialFix.mpc")) else b""
    same = all(open(os.path.join(JP_ROOT, fn), "rb").read() in fix for fn in ("im2_font.nfh", "im2_font_l.nfh"))
    direct = 0xAC00 in codes["im2_font.nfh"] and same and G.E.DIRECT_HANGUL
    if not same:
        log("❌ initialFix.mpc 내장 NFH가 loose 폰트와 다름(폰트 배포 상태 불일치)")
    bad, used = [], set()
    for rel, v in rep["files"].items():
        try:
            raw = open(os.path.join(OUT, rel), "rb").read()
            if sha(raw) != v["sha"]:
                raise ValueError("산출 sha가 보고서와 다름")
            orig, enc = pristine(rel)
            out = open_raw(raw)[0] if enc else raw
            if enc:
                out = out[:v["size"][1]]
            base, _img = image_layer(rel, orig)
            if rel in STANDALONE:
                pn, po = parse_xmb(out, 0), parse_xmb(orig, 0)
                if [e.get("attrs") for e in pn["entries"]] != [e.get("attrs") for e in po["entries"]]:
                    raise ValueError("단독 XMB 비텍스트 값 변동")
            elif orig[:4] == b"pac\x00":
                G.check(out, base, orig, rel)
            for t in texts_of(out):
                used |= {ch for ch in t if "가" <= ch <= "힣"}
        except Exception as ex:  # noqa: BLE001
            bad.append((rel, str(ex)[:200]))
    miss = sorted(ch for ch in used if ord(ch) not in codes["im2_font.nfh"])
    log(f"검증 대상 {len(rep['files'])}개, 구조 오류 {len(bad)}; 폰트 직접 등록판 {'예' if direct else '아니오'}, "
        f"쓰인 한글 {len(used)}자 중 폰트에 없는 글자 {len(miss)}" + (f": {''.join(miss)}" if miss else ""))
    for b in bad:
        log(f"   {b}")
    return not bad and direct and not miss


def cmd_validate(_a):
    ok = validate_all()
    print("✅ 통과" if ok else "❌ 배포 금지")
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- 배포·복원
def rpcs3_running():
    return os.system('tasklist /FI "IMAGENAME eq rpcs3.exe" | find /I "rpcs3.exe" >nul') == 0


def cmd_deploy(_a):
    if rpcs3_running():
        sys.exit("❌ RPCS3 실행 중 — 배포 거부")
    if not validate_all():
        sys.exit("❌ 검증 게이트 실패 — 배포 중단")
    rep = json.load(open(REPORT, encoding="utf-8"))
    bdir = os.path.join(USRDIR, "_backup_ps3res_" + time.strftime("%Y%m%d_%H%M%S"))
    man = []
    for rel, v in rep["files"].items():
        if NEVER.search(rel):
            sys.exit(f"❌ 금지 대상 {rel}")
        dst = os.path.join(JP_ROOT, rel)
        b = os.path.join(bdir, rel)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(dst, b)
        before = sha(open(b, "rb").read())
        shutil.copyfile(os.path.join(OUT, rel), dst)
        after = sha(open(dst, "rb").read())
        assert after == v["sha"], rel
        man.append({"rel": rel, "before_sha256": before, "after_sha256": after})
    json.dump({"at": time.strftime("%Y-%m-%d %H:%M"), "report_at": rep["at"], "files": man},
              open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(man)}개 배포 → {JP_ROOT}\n백업·매니페스트: {bdir}\n원복: python ps3_res_apply.py restore")


def cmd_restore(a):
    if rpcs3_running():
        sys.exit("❌ RPCS3 실행 중 — 원복 거부")
    bdir = a.dir or max((os.path.join(USRDIR, d) for d in os.listdir(USRDIR) if d.startswith("_backup_ps3res_")),
                        default=None)
    if not bdir:
        sys.exit("백업 없음")
    man = json.load(open(os.path.join(bdir, "manifest.json"), encoding="utf-8"))
    n, skip = 0, []
    for it in man["files"]:
        dst = os.path.join(JP_ROOT, it["rel"])
        cur = sha(open(dst, "rb").read())
        if cur == it["before_sha256"]:
            continue
        if cur != it["after_sha256"] and not a.force:
            skip.append(it["rel"])
            continue
        shutil.copyfile(os.path.join(bdir, it["rel"]), dst)
        n += 1
    print(f"{n}개 원복 ({bdir})" + (f", 배포 뒤 바뀐 파일이라 건너뜀 {len(skip)}: {skip[:5]} (--force로 강제)" if skip else ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--rescan", action="store_true", help="게임 폴더를 다시 훑어 대상 추가(배포 전 상태에서만)")
    b = sub.add_parser("build")
    b.add_argument("--code", required=True)
    sub.add_parser("validate")
    sub.add_parser("deploy")
    r = sub.add_parser("restore")
    r.add_argument("--dir")
    r.add_argument("--force", action="store_true")
    a = ap.parse_args()
    {"snapshot": cmd_snapshot, "build": cmd_build, "validate": cmd_validate, "deploy": cmd_deploy,
     "restore": cmd_restore}[a.cmd](a)


if __name__ == "__main__":
    main()
