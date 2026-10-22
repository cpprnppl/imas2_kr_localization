#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
게임 전체 일본어 텍스트 ↔ 웹앱 커버리지 전수 점검 (2026-10-23, 사용자 "누락된 거 다 찾아서 웹앱에 넣어라")

대상(전부 읽기 전용, 암호화본은 메모리 복호화):
  PS3 본편 resource(gscript는 순정 백업), PS3 DLC cp01~18, 360 본편 resource, 360 DLC,
  360 실행 파일(default_unpacked.xex), PS3 EBOOT(복호화 사본 — 실행 안 함, 문자열만 읽음)
방법: 컨테이너 재귀(pac → TSK → 잎). 잎이 XMB면 구조로 _text, SCB면 MSG 표, 텍스처·모델·음성은 건너뜀,
그 외(모르는 표·Lua·실행 파일)는 원시 스캔(UTF-16BE/LE·UTF-8·cp932)으로 일본어 2자 이상 문자열.
대조: find_text.py 스냅샷(웹앱 전 행)과 정규화 일치 → 있음 / 웹 원문의 일부 → 있음(부분) / 없음.
없음 분류: (a) 새 포맷 표  (b) 알려진 포맷인데 추출기가 놓침  (c) 실행 파일  (e) 오탐·개발용(제외, 사유)
          (d) 이미지 속 글자는 텍스트 스캔으로 안 잡힘 → 별도 이미지 점검(텍스처 목록)

주입 커버리지: XMB/SCB 위치(파일×종류)마다 그 판에서 한글을 써 넣는 주입기가 있는지(injector()) —
          웹앱에 문구가 있어도 주입기가 없으면 게임 화면은 일본어 (예: member_select.mpc 속 SCB 소개 대사).

  python coverage_scan.py scan        # Desktop\imas2_image_text\coverage\ 에 report.json/md, missing.json, injection.json
"""
import os
import re
import sys
import json
import time
import struct
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scb"))
from extract_image_text import JP_ROOT, OUT_DEFAULT, ps3_src  # noqa: E402
from xmb_text import parse_xmb, collect_texts  # noqa: E402
import platform_audit as PA  # noqa: E402
import find_text as FT  # noqa: E402

OUT = os.path.join(OUT_DEFAULT, "coverage")
PS3_GS = os.path.join(os.path.dirname(JP_ROOT), "gscript - 복사본")
EBOOT_ELF = os.path.join(OUT_DEFAULT, "_cache", "EBOOT.elf")   # rpcs3 --decrypt 사본 (xex_text.EBOOT와 같음)
XEX = r"C:\Users\jackfilm\Desktop\unpack\imas2\default_unpacked.xex"
MEDIA = (b"NTP3", b"NTXR", b"NUT ", b"BNSF", b"NUS3", b"NDP3", b"NDXR", b"RIFF", b"MPK ", b"PAMF", b"OggS")
RAW_MAX = 2 << 20                       # 원시 스캔은 2MB 이하 잎만(모델·모션 덩어리 오탐 방지)
SKIP_DIRS = ("chara", "acce", "motion", "stage", "dance", "song", "bg2d", "movie", "model")
MEDIA_EXT = (".nub2", ".pam", ".wmv", ".nut", ".png", ".at3", ".xma", ".edat", ".sdat", ".rap", ".sfo", ".trp")
JPCH = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
DEV = re.compile(r"ダミー|だみー|テスト|デバッグ|仮$|仮文|未使用|ほげ|ホゲ|XXX|test|debug|dummy", re.I)

U16BE = re.compile(rb"(?:[\x30][\x00-\xff]|[\x4e-\x9f][\x00-\xff]|\xff[\x01-\x5e]|\x00[\x20-\x7e]|\x00\x0a){2,}")
U16LE = re.compile(rb"(?:[\x00-\xff][\x30]|[\x00-\xff][\x4e-\x9f]|[\x01-\x5e]\xff|[\x20-\x7e]\x00|\x0a\x00){2,}")
U8 = re.compile(rb"(?:[\xe3-\xe9][\x80-\xbf]{2}|\xef\xbc[\x81-\xbf]|[\x20-\x7e\x0a]){2,}")
SJ = re.compile(rb"(?:[\x81-\x9f\xe0-\xef][\x40-\x7e\x80-\xfc]|[\x20-\x7e\x0a]){2,}")


# 디버그 표시용 라벨·폰트명·Lua 경고 (원본 확인: album_common 選択ＩＤ, end_result キャラＩＤ, ProSongTitleAll フェード…)
DEV2 = re.compile(r"ＩＤ：|ゴシック|ロダン|\[lua\]|フェード(イン|アウト)[始終]|のデータ：|ニュー表示：")
STRAY = re.compile(r"\.(orig|bak)$|\.mpc\d+$", re.I)     # 게임 폴더에 남은 작업 사본(attract.mpc.orig, PauseMenu.mpc1)
RARE = re.compile(r"[ゐゑヰヱヴヵヶヮゎ]")


def plausible(s, raw):
    """원시 스캔 문자열의 진짜 텍스트 판정(코드·데이터 바이트 오탐 거르기).
    원시 스캔은 2수준 한자·옛 가나가 섞이면 오탐으로 본다(바이트 우연 일치의 전형)."""
    jp = JPCH.findall(s)
    if len(jp) < 2:
        return False
    if raw:
        if RARE.search(s):
            return False
        for ch in jp:
            if "\u4e00" <= ch <= "\u9fff":
                try:
                    b = ch.encode("cp932")
                except UnicodeEncodeError:
                    return False
                if not (0x88 <= b[0] <= 0x98):
                    return False
    if raw and not KANA.search(s):                 # 한자만이면 1수준 한자·짧은 이름만
        for ch in jp:
            try:
                b = ch.encode("cp932")
            except UnicodeEncodeError:
                return False
            if not (0x88 <= b[0] <= 0x98):
                return False
        if len(s) > 12:
            return False
    try:
        s.encode("cp932")
    except UnicodeEncodeError:
        return False
    junk = sum(1 for ch in s if ord(ch) < 0x80 and not (ch.isalnum() or ch in " .,!?:%-_/()[]<>\n'\"#+&=@*"))
    return junk <= max(1, len(s) // 6)


def raw_scan(blob, lua=False):
    out = []
    # PS3·360 모두 빅엔디언 — UTF-16LE는 제외(오탐만 늘어남)
    pats = [("u8", U8, "utf-8"), ("sjis", SJ, "cp932")] if lua else \
        [("u16be", U16BE, "utf-16-be"), ("u8", U8, "utf-8"), ("sjis", SJ, "cp932")]
    for name, pat, enc in pats:
        for m in pat.finditer(blob):
            b = m.group()
            if enc.startswith("utf-16"):
                # 진짜 문자열: 2바이트 정렬 + 널 종단 + 앞이 널(또는 버퍼 시작)
                if m.start() % 2 or blob[m.end():m.end() + 2] != b"\x00\x00" or \
                        (m.start() >= 2 and blob[m.start() - 2:m.start()] not in (b"\x00\x00", b"\xcd\xcd")):
                    continue
                b = b[:len(b) - len(b) % 2]
            elif blob[m.end():m.end() + 1] != b"\x00":
                continue
            try:
                s = b.decode(enc)
            except UnicodeDecodeError:
                continue
            s = s.strip("\x00 \n")
            if plausible(s, True):
                out.append((name, m.start(), s))
    return out


def scb_msgs(scb):
    import scb_common as C
    import excel2scb as E
    fake = b"\x00" * 0x80 + scb
    secs = C.parse_section_dir(fake)
    if "MSG" not in secs:
        return []
    return [s["text"] for s in E.parse_msg_table(fake, secs["MSG"][0])["strings"]]


def children(d):
    if d[:4] == b"pac\x00" and len(d) > 0x40:
        try:
            cnt = struct.unpack_from(">H", d, 0x20)[0]
            ds = struct.unpack_from(">I", d, 0x38)[0]
            out = []
            for i in range(cnt):
                sz, of = struct.unpack_from(">II", d, 0x40 + i * 32 + 8)
                if ds + of + sz <= len(d):
                    out.append((i, d[ds + of:ds + of + sz]))
            return out
        except struct.error:
            return []
    if d[:4] == b"TSK " and len(d) > 16:
        try:
            n = struct.unpack_from(">I", d, 4)[0]
            if n > 4096:
                return []
            out = []
            for i in range(n):
                sz, of = struct.unpack_from(">II", d, 8 + i * 8)
                if of + sz <= len(d):
                    out.append((i, d[of:of + sz]))
            return out
        except struct.error:
            return []
    return []


def walk(d, path, emit, stat):
    m = d[:4]
    if m == b"XMB ":
        try:
            p = parse_xmb(d, 0)
            npc = any(t["id"].startswith(("NPCP_", "NPCU_", "NPCS_", "PROD_")) for t in collect_texts(p))
            for e in p["entries"]:
                t = e.get("text")
                if t and JPCH.search(t):
                    emit("xmb:npc" if npc else "xmb", path, t)
            stat["xmb"] += 1
        except Exception:  # noqa: BLE001
            stat["xmb_bad"] += 1
            for name, off, s in raw_scan(d):
                emit("raw:" + name, f"{path}@{off:#x}", s)
        return
    if m == b"SCB\x00":
        try:
            for t in scb_msgs(d):
                if JPCH.search(t):
                    emit("scb", path, t)
            stat["scb"] += 1
        except Exception:  # noqa: BLE001
            stat["scb_bad"] += 1
        return
    kids = children(d)
    if kids:
        stat["container"] += 1
        for i, k in kids:
            walk(k, f"{path}/{i}", emit, stat)
        return
    if m in MEDIA:
        stat["media"] += 1
        return
    if m == b"\x1bLua":
        stat["lua"] += 1
        for name, off, s in raw_scan(d, lua=True):
            emit("lua:" + name, f"{path}@{off:#x}", s)
        return
    if len(d) > RAW_MAX:
        stat["raw_skip_big"] += 1
        return
    stat["raw"] += 1
    for name, off, s in raw_scan(d):
        emit("raw:" + name, f"{path}@{off:#x}", s)


NPC_TABLE_FILES = {"game/alf/alf_common.mpc", "interface/nationwideranking.mpc", "interface/scheduleselect.mpc",
                   "scene/produce_etc.mpc", "scene/exep_commu.mpc", "scene/exep_init.mpc"}


def injector(src, rel, kind, gd_files):
    """구조 텍스트(XMB/SCB) 위치 → 그 판에서 이 위치를 한글로 쓰는 주입기 (없으면 '')."""
    r = rel.replace("\\", "/").lower()
    ps3 = src.startswith("ps3")
    if src == "ps3_scb":
        return "excel2scb"
    if src == "x360_res" and r.startswith("gscript/") and r.endswith(".scb"):
        return "pcport360"
    if src == "ps3_res" and r == "scene/attract.mpc" and kind == "scb_embedded":
        return "patch_attract"                           # tools/scb/patch_attract.py (워크로그 §20, PS3만)
    if src.endswith("_dlc"):
        return "dlc_inject" if re.search(r"(^|/)(mail|ranker|songinfo)/|catalog|package", r) else ""
    # PS3 리소스는 xmb_text가 patched\에 빌드만 하고 게임 폴더 배포 경로가 없다(2026-10-23 확인: PS3 게임 폴더
    # install.xmb·NPC 표·initialFix 등 한글 0) → PS3는 '미배포'로 표시하고 주입기 없음으로 센다
    if r in ("text/install.xmb", "ranker/ranker_npc.xmb") or (r.startswith("songinfo/") and "lyrics_" in r):
        return "xmb_text(빌드만·PS3 미배포)" if ps3 else "pcport_apply"
    if r in NPC_TABLE_FILES and kind == "npc":
        return ("xmb_text(빌드만·PS3 미배포)" if r == "scene/exep_init.mpc" else "") if ps3 else "pcport_apply"
    if r in gd_files and kind == "xmb":
        return "" if ps3 else "gamedata_apply"          # gamedata_apply는 360(game_kor) 전용
    if kind == "scb_embedded" and not ps3:
        return "gamedata_apply"                          # 내장 SCB (2026-10-23 추가)
    return ""


def sources():
    """(출처 태그, 판, 루트, 상대경로 필터)"""
    return [("ps3_res", "ps3", JP_ROOT, lambda rel: not rel.lower().startswith(("gscript", "tools", "_"))),
            ("ps3_scb", "ps3", PS3_GS, lambda rel: rel.lower().endswith(".scb") and not rel.lower().startswith("tools")),
            ("ps3_dlc", "ps3", PA.PS3_DLC, lambda rel: True),
            ("x360_res", "x360", PA.X360, lambda rel: True),
            ("x360_dlc", "x360", PA.X360_DLC, lambda rel: True)]


def scan():
    t0 = time.time()
    snap = json.load(open(FT.SNAP, encoding="utf-8"))
    web = {}
    for r in snap["rows"]:
        web.setdefault(FT.norm(r["jp"]), r)
    big = "\x00".join(web.keys())
    found = collections.OrderedDict()            # norm → {text, hits:[(src, fmt, path)]}
    stat = collections.Counter()
    locs = collections.defaultdict(set)          # (src, 파일, 종류) → 구조 텍스트 norm 집합 (주입 커버리지)

    def emit_for(src):
        def emit(fmt, path, text):
            n = FT.norm(text)
            if len(n) < 2:
                return
            if fmt.startswith(("xmb", "scb")):
                rel = path.split(":", 1)[1].split("/")[0]
                kind = "npc" if fmt == "xmb:npc" else fmt
                if kind == "scb" and not rel.lower().endswith(".scb"):
                    kind = "scb_embedded"            # gscript 밖 pac 속 SCB (member_select 등)
                locs[(src, rel, kind)].add(n)
            ent = found.setdefault(n, {"text": text, "hits": []})
            if len(ent["hits"]) < 6:
                ent["hits"].append((src, fmt, path))
            stat["strings"] += 1
        return emit
    undec = []
    for tag, plat, root, ok in sources():
        if not os.path.isdir(root):
            undec.append((tag, "루트 없음", root))
            continue
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root)
                if not ok(rel) or fn.lower().endswith(MEDIA_EXT) or ".dec" in fn.lower() or "_orig" in fn.lower() \
                        or STRAY.search(fn):
                    continue
                if any(part.lower() in SKIP_DIRS for part in rel.replace("/", "\\").split("\\")[:-1]):
                    stat["skip_dir"] += 1
                    continue
                if os.path.getsize(p) > 64 << 20:
                    stat["skip_big"] += 1
                    continue
                raw = open(ps3_src(rel) if tag == "ps3_res" else p, "rb").read()   # PS3 배포본 말고 순정 사본
                if tag == "ps3_scb":
                    import scb_common as C
                    try:
                        d = C.decrypt_scb(raw)
                    except Exception:  # noqa: BLE001
                        d = None
                else:
                    d = PA.dec_any(raw, plat)
                if d is None:
                    if raw[:4] in MEDIA:
                        continue
                    undec.append((tag, rel, f"복호화 안 됨({raw[:4].hex()})"))
                    continue
                stat["files"] += 1
                walk(d, f"{tag}:{rel}", emit_for(tag), stat)
        print(f"  {tag}: 누적 문자열 {stat['strings']:,} · 고유 {len(found):,} · {time.time() - t0:.0f}s", flush=True)
    for tag, p in (("x360_xex", XEX), ("ps3_eboot", EBOOT_ELF)):
        if os.path.exists(p):
            d = open(p, "rb").read()
            for name, off, s in raw_scan(d):
                emit_for(tag)("exe:" + name, f"{tag}@{off:#x}", s)
        else:
            undec.append((tag, "파일 없음", p))
    # 대조·분류
    res = collections.Counter()
    missing = []
    for n, ent in found.items():
        if n in web:
            res["있음"] += 1
            continue
        if n in big:
            res["있음(웹 원문의 일부)"] += 1
            continue
        src, fmt, path = ent["hits"][0]
        t = ent["text"]
        if src in ("x360_xex", "ps3_eboot"):
            cls = "c 실행 파일"
        elif fmt.startswith(("xmb", "scb")):
            cls = "b 알려진 포맷인데 누락"
        else:
            cls = "a 새 포맷/비XMB 표"
        if "ime_keyboard" in path:
            cls = "e 이름 입력 키보드 사전(변환 후보 — 화면 문구 아님)"
        elif DEV.search(t) or DEV2.search(t):
            cls = "e 개발용·더미"
        elif fmt.startswith(("raw", "exe", "lua")) and not KANA.search(t):
            cls = "e 오탐 의심(한자만·원시 스캔)"
        elif fmt.startswith("exe"):
            # 실행 파일 문구는 xex_text.py가 구조적으로 뽑아 웹앱 exe 행으로 넣는다 — 원시 스캔에만 걸린 건 기계어
            cls = "e 오탐(실행 파일 원시 스캔 — 구조 추출 xex_text.py 결과에 없음)"
        elif fmt.startswith(("raw", "lua")) and len(FT.norm(t)) < 6:
            cls = "e 오탐 의심(짧은 원시 스캔 조각)"
        elif fmt.startswith(("raw", "lua")) and (sum(ord(ch) < 0x3000 for ch in t) * 10 >= len(t) * 3 or
                                                 any(0x3300 <= ord(ch) <= 0x33FF for ch in t)):   # ㌫ 등 조합 문자
            cls = "e 오탐 의심(ASCII 섞인 기계어 조각)"
        res[cls] += 1
        missing.append({"class": cls, "text": ent["text"], "hits": ent["hits"]})
    # 주입 커버리지: 웹앱에 문구가 있어도 그 위치를 쓰는 주입기가 없으면 게임에선 일본어 그대로다
    gd = json.load(open(os.path.join(HERE, "gamedata_texts.json"), encoding="utf-8"))
    gd_files = {l.split("#")[0].lower() for v in gd.values() for l in v["meta"]["locs"]}
    gd_files.add("initialtemp.mpc")      # gamedata_apply.targets()가 원문 일치로 함께 처리(웹 행 locs엔 없음)
    inj_rows = []
    for (src, rel, kind), ns in sorted(locs.items()):
        inj = injector(src, rel, kind, gd_files)
        inweb = sum(1 for n in ns if n in web or n in big)
        inj_rows.append({"src": src, "file": rel, "kind": kind, "strings": len(ns), "in_web": inweb,
                         "injector": inj})
    no_inj = [r for r in inj_rows if (not r["injector"] or "미배포" in r["injector"]) and r["in_web"]]
    os.makedirs(OUT, exist_ok=True)
    json.dump(inj_rows, open(os.path.join(OUT, "injection.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = {"at": time.strftime("%Y-%m-%d %H:%M"), "snapshot": snap["at"], "stat": dict(stat),
           "unique_strings": len(found), "result": dict(res), "undecryptable": undec,
           "injection": {"locations": len(inj_rows), "with_injector": len(inj_rows) - len(no_inj),
                         "web_but_no_injector": len(no_inj),
                         "strings_web_but_no_injector": sum(r["in_web"] for r in no_inj)}}
    json.dump(rep, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(missing, open(os.path.join(OUT, "missing.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    by = collections.Counter((m["class"], m["hits"][0][0], m["hits"][0][2].split("/")[0].split("@")[0]) for m in missing)
    lines = [f"# 커버리지 {rep['at']} (스냅샷 {snap['at']})", "", f"고유 일본어 문자열 {len(found):,}", ""]
    lines += [f"- {k}: {v:,}" for k, v in sorted(res.items())]
    lines += ["", "## 누락 — 분류·출처·파일 상위", ""] + [f"- {c} | {s} | {f}: {v}" for (c, s, f), v in by.most_common(80)]
    ij = rep["injection"]
    lines += ["", "## 주입 커버리지 (웹앱엔 있어도 주입기가 없으면 게임에선 일본어)", "",
              f"구조 텍스트 위치(파일×종류) {ij['locations']:,}곳 — 주입기 있음 {ij['with_injector']:,}, "
              f"**웹앱엔 있으나 주입기 없음 {ij['web_but_no_injector']:,}곳 · {ij['strings_web_but_no_injector']:,}문구**", ""]
    lines += [f"- {r['src']} | {r['file']} | {r['kind']} | 문구 {r['strings']} (웹 {r['in_web']})"
              + (f" | {r['injector']}" if r["injector"] else "")
              for r in sorted(no_inj, key=lambda r: -r["in_web"])[:120]]
    lines += ["", "## 복호화·접근 불가", ""] + [f"- {a} {b} {c}" for a, b, c in undec[:60]]
    open(os.path.join(OUT, "report.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
    print(f"→ {OUT}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    scan()
