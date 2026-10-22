#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
360 실행 파일(default.xex) 하드코딩 일본어 문구 → 웹앱 'exe' 분류 (2026-10-23, KOR·사용자 "社長 이름표 검색이 힘들었다")

ADV 화자 이름표 표(0xB924C~0xB9388: 審査員…黒井社長·社長·小鳥·Ｐ…春香), 이름 입력·저장 확인·일시정지
메뉴·どっとっぷTV·S4U 설정 저장 등은 리소스가 아니라 실행 파일 안 UTF-16BE 문자열이다.
주입은 별도 작업(실행 파일 패치) — 여기서는 검색·번역 준비용으로 웹 행만 등록한다.

규칙: 데이터 영역 0xB8000~0xD0000의 UTF-16BE 널 종단 문자열 중 일본어가 있고 Shift-JIS 1수준 한자만 쓰는 것.
2자 이상 + 16바이트 안에 2자 이상 문자열이 이웃한 1자(響·真 등). 슬롯 = 다음 문자열 시작까지 바이트.
원본은 읽기만 한다.

  python xex_text.py extract              # exe_texts.json (게임 원문 — 웹 행 원천)
  python xex_text.py seed --code <팀암호>  # ignore-duplicates로 추가
"""
import os
import re
import sys
import json
import argparse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
XEX = r"C:\Users\jackfilm\Desktop\unpack\imas2\default_unpacked.xex"
LO, HI = 0xB8000, 0xD0000
OUT = os.path.join(HERE, "exe_texts.json")
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


def extract():
    d = open(XEX, "rb").read()
    found = []
    i = LO
    while i < HI:
        j, chars = i, []
        while j < HI:
            c = (d[j] << 8) | d[j + 1]
            if c == 0 or not _ok(c):
                break
            chars.append(chr(c))
            j += 2
        if chars and d[j:j + 2] == b"\x00\x00":
            s = "".join(chars)
            if _good(s):
                found.append((i, s))
            i = j + 2
        else:
            i += 2
    multi = [o for o, s in found if len(s) >= 2]
    keep = [(o, s) for o, s in found if len(s) >= 2 or any(abs(o - m) <= 16 for m in multi)]
    offs = [o for o, _s in keep]
    rows = {}
    for k, (o, s) in enumerate(keep):
        slot = (offs[k + 1] - o) if k + 1 < len(offs) else len(s) * 2 + 2
        key = f"0x{o:06X}"
        rows[f"exe:xex360:{key}"] = {
            "cat": "exe", "grp": "xex360", "seq": k, "key": key, "jp": s, "kr": "", "st": 0,
            "meta": {"plat": "x360", "offset": o, "slot": slot, "cap": slot // 2 - 1,
                     "plat_note": "360 실행 파일(default.xex) 하드코딩 — PS3 EBOOT 대응은 미확인",
                     "inject": "주입 경로 준비 중(실행 파일 패치 필요)"}}
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(rows)}개 문자열 → {OUT}")
    for v in list(rows.values())[:5]:
        print("  ", v["key"], repr(v["jp"]), "슬롯", v["meta"]["slot"])
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
