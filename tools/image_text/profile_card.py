#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
멤버 선택 카드(PERSONAL DATA) 이름 글자 크기 30 → 26 — SWG 텍스트 상자 레코드 제자리 수정 (2026-10-29, 사용자 "풀네임으로 바꾸고")

iface\\member_select.mpc 안 ProCharaSelect.swg(PS3·360 바이트 동일, 파일 0x960). 캐릭터표 종류 3 = 텍스트 상자 32B 레코드
(+0 id, +8 글자 크기 px, +20 폭<<16|높이, +24 RGBA). 이름 TEXT1 = 크기 30, 상자 420×40, SWG +0x15c10(파일 +0x16570).
크기만 26으로 바꾸면 풀네임 8자(키사라기 치하야)가 배경 그림 속 "(" 앞에 들어간다(PS3 격리 RPCS3 10-29 확인).
같은 크기 4바이트 수정이라 파일 크기·오프셋 불변. 첫 SWG에서 그 칸이 크기 30·상자 420×40이 아니면 거부.
근거: 공유 노트 profile_name_box_research.md

  라이브러리: name_size(plain) → 새 평문 (ps3_res_apply / pcport_apply 층에서 부름)
"""
import struct
import hashlib

REL = "iface\\member_select.mpc"
SIZE = 26
_REC = 0x15C10                 # SWG 시작 기준 TEXT1 레코드 +8(글자 크기); +12 뒤가 폭<<16|높이


def _swg_at(plain):
    i = plain.find(b"SWG\x00")
    if i < 0:
        raise ValueError("member_select: SWG 없음")
    return i


def name_size(plain, size=SIZE):
    base = _swg_at(plain)
    o = base + _REC
    cur = struct.unpack_from(">I", plain, o)[0]
    if cur == size:
        return plain
    if cur != 30:
        raise ValueError(f"member_select: 이름 크기 칸 값 {cur} (30 아님) — 위치가 다르다, 수정 거부")
    if struct.unpack_from(">I", plain, o + 12)[0] != (420 << 16 | 40):
        raise ValueError("member_select: 이름 상자 420×40이 아님 — 수정 거부")
    return plain[:o] + struct.pack(">I", size) + plain[o + 4:]


if __name__ == "__main__":
    import os
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from extract_image_text import OUT_DEFAULT
    p = open(os.path.join(OUT_DEFAULT, "_cache", "jp", "iface", "member_select.mpc"), "rb").read()
    new = name_size(p)
    diff = [i for i in range(0, len(p), 4) if p[i:i + 4] != new[i:i + 4]]
    print(f"SWG @0x{_swg_at(p):X}, 바뀐 워드 {[hex(i) for i in diff]}, 크기 {len(new)} 동일: {len(new) == len(p)}",
          hashlib.md5(p[_swg_at(p):_swg_at(p) + 256]).hexdigest()[:8])
