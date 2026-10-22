#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
360 실행 파일(default.xex) 하드코딩 일본어 문구 → 웹앱 'exe' 분류 (2026-10-23, KOR·사용자 "社長 이름표 검색이 힘들었다")

ADV 화자 이름표 표(0xB924C~0xB9388: 審査員…黒井社長·社長·小鳥·Ｐ…春香), 이름 입력·저장 확인·일시정지
메뉴·どっとっぷTV·S4U 설정 저장 등은 리소스가 아니라 실행 파일 안 UTF-16BE 문자열이다.
주입은 별도 작업(실행 파일 패치) — 여기서는 검색·번역 준비용으로 웹 행만 등록한다.

규칙: 데이터 영역 0xB8000~0xD0000의 UTF-16BE 널 종단 문자열 중 일본어가 있고 Shift-JIS 1수준 한자만 쓰는 것.
2자 이상 + 16바이트 안에 2자 이상 문자열이 이웃한 1자(響·真 등). 슬롯 = 다음 문자열 시작까지 바이트.
한자만으로 된 것은 웹앱 다른 곳에 같은 글자열이 있거나 32바이트 안에 가나 문자열이 이웃할 때만(기계어 우연 일치 제거).
원본은 읽기만 한다.

그룹 (2026-10-23 전수 조사 확장):
  xex360    360 default.xex 하드코딩. PS3 EBOOT에 같은 문구가 있으면 meta.eboot에 PS3 위치 + plat=common
  eboot_ps3 PS3 EBOOT에만 있는 문구 (0x580000~0x5B0000 UTF-16BE + 그라비아 스테이지명 Shift-JIS 표)
  xdbf360   360 XDBF 문자열표(업적 이름·설명, 접속 상태) — 대시보드용, 게임 화면엔 안 나옴

  python xex_text.py extract              # exe_texts.json (게임 원문 — 웹 행 원천)
  python xex_text.py seed --code <팀암호>  # ignore-duplicates로 추가 + 기존 행 meta.eboot/plat 보강
"""
import os
import re
import sys
import json
import struct
import argparse
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
XEX = r"C:\Users\jackfilm\Desktop\unpack\imas2\default_unpacked.xex"
LO, HI = 0xB8000, 0xD0000
# PS3 EBOOT 복호 사본(rpcs3 --no-gui --decrypt, 읽기 전용 정적 분석용 — 실행 안 함)
EBOOT = os.path.join(os.path.expanduser("~"), "Desktop", "imas2_image_text", "_cache", "EBOOT.elf")
EBOOT_U16 = (0x580000, 0x5B0000)      # 문자열 표가 몰린 데이터 영역 (전수 스캔으로 확인)
EBOOT_SJIS = (0x596400, 0x596520)     # 그라비아 스테이지명 표
OUT = os.path.join(HERE, "exe_texts.json")
JUNK = {"太", "慰慮", "物印散弱", "捨椀", "獣", "湯", "牟", "故", "慧故",
        "・：；。"}   # 마지막은 금칙 문자표(화면 문구 아님)   # 이웃 규칙을 통과하는 기계어 우연 일치 (눈으로 확인)
SNAP = os.path.join(os.path.expanduser("~"), "Desktop", "imas2_image_text", "webapp_snapshot.json")  # find_text.py
CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))


def _ok(c):
    return c == 0x0A or 0x20 <= c < 0x7F or 0x3000 <= c <= 0x30FF or 0x4E00 <= c <= 0x9FFF or \
        0xFF01 <= c <= 0xFF9F or c in (0x2026, 0x2025, 0x2015, 0x301C, 0x2606, 0x2605, 0x266A, 0x00D7)


def _good(s):
    jp = [ch for ch in s if ord(ch) >= 0x3000]
    if not jp or any(0xFF61 <= ord(ch) <= 0xFF9F for ch in s) or "耀" in s:   # 반각 가나·U+8000(=0x8000 값) = 쓰레기
        return False
    for ch in jp:
        try:
            b = ch.encode("cp932")
        except UnicodeEncodeError:
            return False
        if 0x4E00 <= ord(ch) <= 0x9FFF and not (0x88 <= b[0] <= 0x98):
            return False
    return all(ord(ch) >= 0x3000 or ch.isalnum() or ch in " .,!?:%-_/()[]<>\n'\"#+&=" for ch in s)


def scan_u16(d, lo, hi):
    """[(offset, 문자열, 슬롯바이트)] — 규칙은 모듈 docstring."""
    found = []
    i = lo
    while i < hi:
        j, chars = i, []
        while j < hi:
            c = (d[j] << 8) | d[j + 1]
            if c == 0 or not _ok(c):
                break
            chars.append(chr(c))
            j += 2
        s = "".join(chars)
        if chars and d[j:j + 2] == b"\x00\x00":
            # 앞에 붙은 쓰레기 글자(포인터·'_result\0' 같은 ASCII 꼬리가 UTF-16 한자로 읽힌 것)는 떼어낸다 —
            # 통째로 버리면 スピードを上げろ！·ランキングに登録 등이 빠졌다 (2026-10-23 전수 조사)
            # 가나 바로 뒤에서 자르지 않는다(진짜 문자열 중간 절단 방지)
            k = next((k for k in range(len(s)) if _good(s[k:]) and
                      (k == 0 or not 0x3040 <= ord(s[k - 1]) <= 0x30FF)), None)
            if k is not None:
                found.append((i + 2 * k, s[k:]))
            i = j + 2
        else:
            i += 2
    # 한자만으로 된 문자열(慮来·物印散強 등)은 기계어 우연 일치가 많다 — 게임 다른 곳(웹앱 스냅샷)에
    # 같은 글자열이 있을 때만 인정(社長·創刊·楽曲 등). 공백뿐인 것도 버림.
    corpus = ""
    if os.path.exists(SNAP):
        corpus = "\n".join(r["jp"] or "" for r in json.load(open(SNAP, encoding="utf-8"))["rows"]
                           if r["cat"] != "exe")
    def kanji_only(s):
        return all(0x4E00 <= ord(ch) <= 0x9FFF for ch in s)
    kana_at = [o for o, s in found if not kanji_only(s) and any(0x3040 <= ord(ch) <= 0x30FF for ch in s)]
    found = [(o, s) for o, s in found if s.strip("　 \n") not in JUNK and
             any(0x3040 <= ord(ch) <= 0x30FF or 0x4E00 <= ord(ch) <= 0x9FFF or 0xFF10 <= ord(ch) <= 0xFF5A
                 for ch in s) and                                   # ＢＫ·Ｐ(화자명)·ＡＢ(혈액형)은 살림
             (not kanji_only(s) or not corpus or s in corpus or
              any(0 < abs(o - m) <= 32 for m in kana_at))]          # 楽曲情報·詳細不明: 메뉴 표 이웃
    multi = [o for o, s in found if len(s) >= 2]
    keep = [(o, s) for o, s in found if len(s) >= 2 or any(abs(o - m) <= 16 for m in multi)]
    offs = [o for o, _s in keep]
    return [(o, s, (offs[k + 1] - o) if k + 1 < len(offs) else len(s) * 2 + 2)
            for k, (o, s) in enumerate(keep)]


def scan_sjis(d, lo, hi):
    """EBOOT의 Shift-JIS 널 종단 문자열(그라비아 스테이지명 표) — 가나가 있는 2자 이상만."""
    out = []
    for m in re.finditer(rb"(?<=\x00)(?:[\x20-\x7e]|[\x81-\x9f\xe0-\xef][\x40-\xfc])+(?=\x00)", d[lo:hi]):
        try:
            s = m.group().decode("cp932")
        except UnicodeDecodeError:
            continue
        if len(s) >= 2 and any(0x3040 <= ord(ch) <= 0x30FF for ch in s) and _good(s):
            out.append((lo + m.start(), s, -(-(len(m.group()) + 1) // 8) * 8))
    return out


def scan_xdbf(d):
    """360 XDBF(SPA) 문자열표 XSTR — 업적 이름·설명, 접속 상태(Rich Presence). 길이 접두 UTF-8."""
    b = d.find(b"XDBF")
    _m, _v, elen, ecnt, flen, _fc = struct.unpack_from(">4sIIIII", d, b)
    data0 = b + 24 + elen * 18 + flen * 8
    out = []
    for k in range(ecnt):
        ns, eid, ofs, _ln = struct.unpack_from(">HQII", d, b + 24 + k * 18)
        p = data0 + ofs
        if ns != 3 or d[p:p + 4] != b"XSTR" or eid != 2:      # 언어 2 = 일본어
            continue
        cnt = struct.unpack_from(">H", d, p + 12)[0]
        q = p + 14
        for _ in range(cnt):
            sid, sl = struct.unpack_from(">HH", d, q)
            s = d[q + 4:q + 4 + sl].decode("utf-8")
            if any(ord(ch) >= 0x3000 for ch in s) and not s.startswith("テスト用"):
                out.append((q + 4, s, sid))
            q += 4 + sl
    return out


def extract():
    x = open(XEX, "rb").read()
    rows = {}
    for k, (o, s, slot) in enumerate(scan_u16(x, LO, HI)):
        key = f"0x{o:06X}"
        rows[f"exe:xex360:{key}"] = {
            "cat": "exe", "grp": "xex360", "seq": k, "key": key, "jp": s, "kr": "", "st": 0,
            "meta": {"plat": "x360", "offset": o, "slot": slot, "cap": slot // 2 - 1,
                     "plat_note": "360 실행 파일(default.xex) 하드코딩 — PS3 EBOOT 대응은 미확인",
                     "inject": "주입 경로 준비 중(실행 파일 패치 필요)"}}
    by_jp = {}
    for rid, v in rows.items():
        by_jp.setdefault(v["jp"].strip("　"), []).append(rid)
    # PS3 EBOOT: 같은 문구가 xex 행에 있으면 그 행에 EBOOT 위치만 붙이고(공통), 없으면 PS3 전용 행
    n_pair = 0
    if os.path.exists(EBOOT):
        e = open(EBOOT, "rb").read()
        hits = [(o, s, slot, "u16") for o, s, slot in scan_u16(e, *EBOOT_U16)] + \
               [(o, s, slot, "sjis") for o, s, slot in scan_sjis(e, *EBOOT_SJIS)]
        seq = 0
        for o, s, slot, enc in sorted(hits):
            loc = {"offset": o, "slot": slot, "enc": enc}
            if s.strip("　") in by_jp:
                for rid in by_jp[s.strip("　")]:
                    m = rows[rid]["meta"]
                    m.setdefault("eboot", []).append(loc)
                    m["plat"] = "common"
                    m["plat_note"] = "360 xex·PS3 EBOOT 둘 다 하드코딩 (meta.eboot = PS3 위치)"
                n_pair += 1
                continue
            key = f"0x{o:06X}"
            rows[f"exe:eboot_ps3:{key}"] = {
                "cat": "exe", "grp": "eboot_ps3", "seq": seq, "key": key, "jp": s, "kr": "", "st": 0,
                # 표 끝 문자열은 다음 문자열까지가 멀어 슬롯이 부풀므로 256B 넘으면 원문 길이를 상한으로
                "meta": {"plat": "ps3", **loc,
                         "cap": len(s) if slot > 256 else ((slot - 2) // 2 if enc == "u16" else (slot - 1) // 2),
                         "plat_note": "PS3 실행 파일(EBOOT) 하드코딩" +
                                      (" — Shift-JIS(그라비아 스테이지명 표)" if enc == "sjis" else ""),
                         "inject": "주입 경로 준비 중(EBOOT 패치 필요)"}}
            seq += 1
    else:
        print(f"[주의] EBOOT 복호본 없음: {EBOOT} (rpcs3 --decrypt로 만든 사본) — PS3 행 생략")
    for k, (o, s, sid) in enumerate(scan_xdbf(x)):
        key = f"XSTR_{sid}"
        rows[f"exe:xdbf360:{key}"] = {
            "cat": "exe", "grp": "xdbf360", "seq": k, "key": key, "jp": s, "kr": "", "st": 0,
            "meta": {"plat": "x360", "offset": o, "xstr_id": sid,
                     "plat_note": "360 업적·접속 상태 문자열(XDBF) — Xbox 대시보드 표시용, 게임 화면에는 안 나옴",
                     "inject": "PC 포트가 업적 알림을 띄울 때만 사용 (길이 제한 없음, XSTR 재작성)"}}
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = {}
    for v in rows.values():
        c[v["grp"]] = c.get(v["grp"], 0) + 1
    print(f"{len(rows)}행 → {OUT}  {c}  (EBOOT 문구 중 xex 행과 같은 것 {n_pair}개는 그 행에 위치만 추가)")
    return rows


def seed(code):
    rows = json.load(open(OUT, encoding="utf-8"))
    body = [{"id": rid, "ts": 0, "by": "", **v} for rid, v in rows.items()]
    for i in range(0, len(body), 500):
        r = urllib.request.Request(CFG["url"] + "/rest/v1/rows?on_conflict=id",
                                   data=json.dumps(body[i:i + 500], ensure_ascii=False).encode("utf-8"),
                                   method="POST", headers={
                                       "apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}",
                                       "x-team-code": code, "Content-Type": "application/json",
                                       "Prefer": "resolution=ignore-duplicates,return=minimal"})
        urllib.request.urlopen(r)
    print(f"exe 행 {len(body)}개 추가(이미 있으면 무시)")
    # 기존 xex 행에 PS3 EBOOT 위치(meta.eboot)·plat 보강 — 서버 meta에 병합(다른 meta 키·번역 칸 불변)
    hdr = {"apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}", "x-team-code": code}
    cur = {}
    off = 0
    while True:
        ch = json.load(urllib.request.urlopen(urllib.request.Request(
            CFG["url"] + f"/rest/v1/rows?select=id,meta&cat=eq.exe&order=id&limit=1000&offset={off}", headers=hdr)))
        cur.update({x["id"]: x["meta"] or {} for x in ch})
        if len(ch) < 1000:
            break
        off += 1000
    upd = []
    for rid, v in rows.items():
        m = cur.get(rid)
        if m is None or not v["meta"].get("eboot"):
            continue
        new = {**m, **{k: v["meta"][k] for k in ("eboot", "plat", "plat_note")}}
        if new != m:
            upd.append({"id": rid, "meta": new})
    for u in upd:
        urllib.request.urlopen(urllib.request.Request(
            CFG["url"] + "/rest/v1/rows?id=eq." + urllib.parse.quote(u["id"], safe=""),
            data=json.dumps({"meta": u["meta"]}, ensure_ascii=False).encode("utf-8"), method="PATCH",
            headers={**hdr, "Content-Type": "application/json", "Prefer": "return=minimal"}))
    print(f"기존 xex 행 meta 보강(PS3 EBOOT 위치) {len(upd)}개")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "seed"])
    ap.add_argument("--code")
    a = ap.parse_args()
    if a.cmd == "extract":
        extract()
    else:
        seed(a.code)


if __name__ == "__main__":
    main()
