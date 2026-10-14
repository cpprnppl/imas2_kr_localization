#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NFH 한글 직접 등록 변환기 (워크로그 §23).

입력: output/의 리패치 산출물(한글 글리프가 아틀라스에 이미 있음) + font_mapping_v2.json
동작: 매핑된 희생 한자 레코드의 code를 해당 한글 코드포인트로 교체 →
      레코드 배열을 code 순으로 재정렬 → 전 레코드의 그룹 카운터(+20/+21,
      게임 프레이밍 +24/+25) 재계산 → 헤더 +0x50 버킷 테이블 재생성
      (bucket[h] = 그룹 첫 레코드 인덱스 − 첫 코드 하위바이트, 없으면 0x80000001).
      레코드 수·NUT은 불변. 룩업 구조 근거: imas2pc 360판 정적 분석(sub_823470C0).

산출: output_direct/im2_font.nfh, im2_font_l.nfh (+ NUT은 output/ 것 그대로 복사)
자가 검증: 정렬·카운터·버킷 공식 전수 확인 + 룩업 시뮬레이션(모든 한글 2,359 +
잔존 전 코드 조회 성공, 제거된 한자 코드 조회 실패).

주의: 이 산출물은 "원시 한글 코드포인트" 텍스트와 함께 써야 한다 — 기존 매핑
인코딩 SCB와는 호환되지 않는다(해당 한자 코드가 폰트에서 사라짐).
"""
import os
import sys
import json
import shutil
import struct

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")
DIRECT_DIR = os.path.join(SCRIPT_DIR, "output_direct")

NFH_RB, NFH_RS = 0x474, 32   # 폰트팀 프레이밍(첫 '실글자' 레코드 기준)
GAME_RB = 0x450              # 게임 프레이밍(rec0=U+0000 포함) — 같은 바이트
BUCKET_OFF = 0x50
ABSENT = 0x80000001


def load_records(nfh: bytes):
    """게임 프레이밍으로 전체 레코드(코드 U+0000 rec0 포함)를 읽는다."""
    n = (len(nfh) - GAME_RB) // NFH_RS
    recs = []
    for i in range(n):
        off = GAME_RB + i * NFH_RS
        raw = bytearray(nfh[off:off + NFH_RS])
        code = struct.unpack_from(">H", raw, 22)[0]
        recs.append({"raw": raw, "code": code})
    return recs


def rebuild(recs):
    """정렬 + 그룹 카운터(+24/+25) + 버킷 테이블 재계산. (records, buckets) 반환."""
    recs = sorted(recs, key=lambda r: r["code"])
    # 그룹(상위바이트) 경계
    groups = {}
    for i, r in enumerate(recs):
        hb = r["code"] >> 8
        s, e = groups.get(hb, (i, i))
        groups[hb] = (min(s, i), max(e, i))
    for hb, (s, e) in groups.items():
        if e - s > 255:
            raise ValueError(f"그룹 0x{hb:02X} 크기 {e - s + 1} > 256 — u8 카운터 초과")
        for i in range(s, e + 1):
            recs[i]["raw"][24] = i - s
            recs[i]["raw"][25] = e - i
    buckets = []
    for hb in range(256):
        if hb in groups:
            s, _ = groups[hb]
            first_lo = recs[s]["code"] & 0xFF
            buckets.append((s - first_lo) & 0xFFFFFFFF)
        else:
            buckets.append(ABSENT)
    return recs, buckets


def convert(name, mapping):
    src = os.path.join(OUT_DIR, f"{name}.nfh")
    nfh = bytearray(open(src, "rb").read())
    recs = load_records(bytes(nfh))
    k2h = {ord(k): ord(h) for h, k in mapping.items()}
    changed = 0
    for r in recs:
        h = k2h.get(r["code"])
        if h is not None:
            struct.pack_into(">H", r["raw"], 22, h)
            r["code"] = h
            changed += 1
    if changed != len(mapping):
        raise ValueError(f"{name}: 코드 교체 {changed} != 매핑 {len(mapping)}")
    recs, buckets = rebuild(recs)

    out = bytearray(nfh)
    for hb in range(256):
        struct.pack_into(">I", out, BUCKET_OFF + hb * 4, buckets[hb])
    for i, r in enumerate(recs):
        out[GAME_RB + i * NFH_RS: GAME_RB + (i + 1) * NFH_RS] = r["raw"]
    assert len(out) == len(nfh)

    # ---- 자가 검증 -----------------------------------------------------------
    codes = [r["code"] for r in recs]
    assert all(a < b for a, b in zip(codes, codes[1:])), "코드 정렬 깨짐"
    for i, r in enumerate(recs):   # 카운터 재검
        hb = r["code"] >> 8
        lo = struct.unpack_from(">I", out, BUCKET_OFF + hb * 4)[0]
        assert lo != ABSENT
        s = i - r["raw"][24]
        e = i + r["raw"][25]
        assert (s - (recs[s]["code"] & 0xFF)) & 0xFFFFFFFF == lo, f"버킷 공식 불일치 idx {i}"
        assert recs[s]["code"] >> 8 == hb and recs[e]["code"] >> 8 == hb

    def lookup(code):   # sub_823470C0 모델: 버킷 하한 + 이분 탐색
        hb, lo = code >> 8, code & 0xFF
        b = struct.unpack_from(">I", out, BUCKET_OFF + hb * 4)[0]
        if b == ABSENT or b + lo < 0:
            return None
        import bisect
        i = bisect.bisect_left(codes, code)
        return i if i < len(codes) and codes[i] == code else None

    for h in mapping:
        assert lookup(ord(h)) is not None, f"한글 조회 실패 {h}"
    for k in mapping.values():
        assert lookup(ord(k)) is None, f"제거된 한자가 조회됨 {k}"
    for c in (0x3042, 0x4E00, 0xFF01, ord("…")):
        assert lookup(c) is not None, f"기존 코드 조회 실패 U+{c:04X}"

    os.makedirs(DIRECT_DIR, exist_ok=True)
    dst = os.path.join(DIRECT_DIR, f"{name}.nfh")
    open(dst, "wb").write(out)
    shutil.copy2(os.path.join(OUT_DIR, f"{name}.nut"), os.path.join(DIRECT_DIR, f"{name}.nut"))
    print(f"{name}: 코드 교체 {changed}, 재정렬·카운터·버킷 재생성, 자가 검증 통과 → {dst}")
    hangul_group_sample = struct.unpack_from(">I", out, BUCKET_OFF + 0xAC * 4)[0]
    print(f"  bucket[0xAC]={hangul_group_sample} (이전 0x80000001)")


def main():
    mapping = json.load(open(os.path.join(OUT_DIR, "font_mapping_v2.json"), encoding="utf-8"))
    print(f"매핑 {len(mapping)}자 → 직접 등록 변환")
    for name in ("im2_font", "im2_font_l"):
        convert(name, mapping)
    print("완료. 이 NFH는 원시 한글 텍스트 전용(기존 매핑 SCB와 비호환).")


if __name__ == "__main__":
    main()
