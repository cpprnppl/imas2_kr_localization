#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
라이브 가사 주입 — dance\\dan_<곡>_{1,3,5}.mpc 내장 XMB 교체 (PC 포트 1순위)

라이브(스테이지) 가사는 songinfo가 아니라 dance pac 안의 XMB에서 읽는다
(2026-10-15 실측: 평문 songinfo 교체로는 인게임 가사가 일본어 그대로였고,
dan_twi_*.mpc 3종 모두에서 가사 문자열 발견, 내용은 songinfo판과 동일 25줄).

pac 구조(dan_* 실측): 헤더 0x40(+0x08 = 엔트리 크기 합) / 엔트리 테이블 32B×n
(+8 size, +12 ofs; ofs는 데이터 시작 기준) / (매니페스트) / 데이터(엔트리별
16바이트 정렬 연속, 꼬리 없음). 데이터 시작은 "entry0 ofs=0" 위치를
'XMB '/'pac\\0' 등 내용으로 역산하지 않고, 첫 엔트리 데이터가 테이블·매니페스트
직후 16정렬이라는 실측(0x340)에 의존하지 않도록 **가사 XMB 위치로 역산**한다.

한국어가 일어보다 길면 엔트리를 키우고 뒤 엔트리를 밀어 재조립한다
(크기 합 헤더·테이블 갱신, 다른 엔트리 바이트 불변 검증).

사용:
  python dance_lyrics.py build  [--songs twi,rdy] # kr 있는 곡 전부(기본) patched_dance/ 생성
  python dance_lyrics.py deploy [--songs ...]     # game_kor 사본에 배포(.orig_kor 백업)
입력: 게임 트리의 dance pac(암호화여도 사본 복호화), xmb_translations.json의
songinfo/<곡>/lyrics_<곡>.xmb 항목(kr). 직접 등록 체제 = 원시 한글(매핑 미적용).
"""
import os
import sys
import json
import glob
import shutil
import struct
import hashlib
import argparse
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT, IMAS2DEC  # noqa: E402
from xmb_text import parse_xmb, find_xmb, collect_texts, rebuild_xmb  # noqa: E402

# 원본 = 360 순정 추출본(읽기 전용, 메모리 복호화). 2026-10-29까지 공유 build_imas2_o2\game을 읽었는데 그 폴더의
# dan_twi_1/3/5·lyrics_twi는 예전 시험 한글판이었다(순정 아님) — pcport_apply와 같이 고침.
PORT_RES = r"C:\Users\jackfilm\Desktop\unpack\imas2\resource"
# 배포는 사본에만 (2026-10-22 리컴파일 감독 합의: 공유 game = 전 세션 회귀 기준선)
KOR_RES = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor\resource"
CACHE = os.path.join(OUT_DEFAULT, "_cache", "dance_x360")     # 순정 복호화본만 (옛 _cache/dance = 공유 game 기준, 쓰지 않음)
PATCHED = os.path.join(OUT_DEFAULT, "patched_dance")


def md5(b):
    return hashlib.md5(b).hexdigest()


def decrypt_cached(rel):
    """360 순정 dance pac을 메모리에서 복호화해 캐시. 이미 평문이면 그대로."""
    import platform_audit as PAU
    dst = os.path.join(CACHE, os.path.basename(rel))
    if os.path.exists(dst):
        return open(dst, "rb").read()
    raw = open(os.path.join(PORT_RES, rel), "rb").read()
    d = raw if raw[:4] == b"pac\x00" else PAU.dec_any(raw, "x360")
    if d is None:
        raise RuntimeError(f"복호화 실패: {rel}")
    os.makedirs(CACHE, exist_ok=True)
    open(dst + ".tmp", "wb").write(d)
    os.replace(dst + ".tmp", dst)
    data = open(dst, "rb").read()
    assert data[:4] == b"pac\x00", rel
    return data


def parse_pac(data):
    cnt = struct.unpack_from(">H", data, 0x20)[0]
    ents = []
    for i in range(cnt):
        off = 0x40 + i * 32
        size, ofs = struct.unpack_from(">II", data, off + 8)
        ents.append({"i": i, "tbl": off, "size": size, "ofs": ofs})
    # 데이터 시작 역산: 가사 XMB('XMB ' + LYR_001)가 든 엔트리로
    xi = data.find(b"XMB ")
    lyr = None
    while xi >= 0:
        seg = data[xi:xi + 4096]
        if b"LYR_001" in seg:
            lyr = xi
            break
        xi = data.find(b"XMB ", xi + 4)
    assert lyr is not None, "가사 XMB 없음"
    cand = [e for e in ents if (lyr - e["ofs"]) > 0x40]
    ds = None
    for e in ents:
        d0 = lyr - e["ofs"]
        if 0x40 <= d0 <= 0x4000 and all(
                e2["ofs"] + d0 + e2["size"] <= len(data) for e2 in ents):
            # 전 엔트리가 파일 안에 들어가고 마지막 엔트리가 파일 끝과 일치하는 ds
            last = max(ents, key=lambda x: x["ofs"])
            if d0 + last["ofs"] + last["size"] == len(data):
                ds = d0
                lyr_ent = e
    assert ds is not None, "data_start 역산 실패"
    lyr_ent = next(e for e in ents if e["ofs"] + ds == lyr)
    return cnt, ents, ds, lyr_ent


def align16(n):
    return (n + 15) & ~15


def rebuild_pac(data, ents, ds, lyr_ent, new_blob):
    """가사 엔트리만 new_blob로 교체해 pac 재조립."""
    parts = []
    pos = 0
    out_tbl = []
    for e in sorted(ents, key=lambda x: x["ofs"]):
        blob = new_blob if e["i"] == lyr_ent["i"] else \
            data[ds + e["ofs"]: ds + e["ofs"] + e["size"]]
        out_tbl.append((e["tbl"], len(blob), pos))
        parts.append(blob)
        pad = align16(len(blob)) - len(blob)
        parts.append(b"\x00" * pad)
        pos += len(blob) + pad
    out = bytearray(data[:ds]) + b"".join(parts)
    # 마지막 엔트리 뒤 패딩은 원본에 없음 → 제거
    last_tbl, last_size, last_pos = max(out_tbl, key=lambda t: t[2])
    out = out[:ds + last_pos + last_size]
    for tbl, size, ofs in out_tbl:
        struct.pack_into(">II", out, tbl + 8, size, ofs)
    struct.pack_into(">I", out, 0x08, sum(s for _, s, _ in out_tbl))
    return bytes(out)


def song_kr(tr, song):
    """xmb_translations.json에서 곡 가사 kr {LYR id: kr}."""
    ents_tr = tr.get(f"songinfo/{song}/lyrics_{song}.xmb", {})
    return {tid: v["kr"] for tid, v in ents_tr.items() if v.get("kr")}


def patch_lyrics(data, kr, rel=""):
    """dance pac 평문의 가사 XMB 엔트리만 kr로 교체 → (새 평문, 교체 attr 수, 없는 id).
    검증: 재파싱 — 가사 kr 반영 + 비가사 엔트리 바이트 불변 + 크기 합 헤더 (PC 포트·PS3 공용, ps3_res_apply가 씀)."""
    cnt, ents, ds, lyr_ent = parse_pac(data)
    seg = data[ds + lyr_ent["ofs"]: ds + lyr_ent["ofs"] + lyr_ent["size"]]
    base = find_xmb(seg)
    by_id = {}
    for t in collect_texts(parse_xmb(seg, base)):
        by_id.setdefault(t["id"], []).append(t["attr"])
    repl, miss = {}, []
    for tid, s in kr.items():
        if tid not in by_id:
            miss.append(tid)
            continue
        for ai in by_id[tid]:
            repl[ai] = s
    if not repl:
        return data, 0, miss
    new_seg = rebuild_xmb(seg, base, repl, lambda *a: None, allow_grow=True)
    out = rebuild_pac(data, ents, ds, lyr_ent, new_seg)
    check_lyrics(data, out, kr, rel)
    return out, len(repl), miss


def check_lyrics(data, out, kr, rel=""):
    cnt, ents, ds, lyr_ent = parse_pac(data)
    cnt2, ents2, ds2, _lyr2 = parse_pac(out)
    assert cnt2 == cnt and ds2 == ds, f"{rel}: pac 구조 변형"
    ids = {t["id"] for t in collect_texts(parse_xmb(
        data[ds + lyr_ent["ofs"]: ds + lyr_ent["ofs"] + lyr_ent["size"]],
        find_xmb(data[ds + lyr_ent["ofs"]: ds + lyr_ent["ofs"] + lyr_ent["size"]])))}
    for e, e2 in zip(sorted(ents, key=lambda x: x["i"]), sorted(ents2, key=lambda x: x["i"])):
        a = data[ds + e["ofs"]: ds + e["ofs"] + e["size"]]
        b = out[ds2 + e2["ofs"]: ds2 + e2["ofs"] + e2["size"]]
        if e["i"] == lyr_ent["i"]:
            got = {t["id"]: t["text"] for t in collect_texts(parse_xmb(b, find_xmb(b)))}
            for tid, s in kr.items():
                if tid in ids:
                    assert got[tid] == s, f"{rel}: {tid} 불일치"
        else:
            assert a == b, f"{rel}: 엔트리 {e['i']} 변형"
    assert struct.unpack_from(">I", out, 8)[0] == sum(e["size"] for e in ents2), f"{rel}: 크기 합 헤더"


def build(songs):
    tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    os.makedirs(PATCHED, exist_ok=True)
    done = []
    for rel_key in sorted(tr):
        if not rel_key.startswith("songinfo/"):
            continue
        song = rel_key.split("/")[1]
        if songs and song not in songs:
            continue
        kr = song_kr(tr, song)
        if not kr:
            continue
        for mpc in sorted(glob.glob(os.path.join(PORT_RES, "dance", f"dan_{song}_*.mpc"))):
            rel = os.path.join("dance", os.path.basename(mpc))
            data = decrypt_cached(rel)
            out, nrep, miss = patch_lyrics(data, kr, rel)
            if miss:
                print(f"  [경고] {rel}: 없는 id {miss[:3]}…")
            repl = range(nrep)
            dst = os.path.join(PATCHED, os.path.basename(mpc))
            open(dst, "wb").write(out)
            print(f"{rel}: 가사 {len(repl)}attr 교체, {len(data):,}→{len(out):,}B → {dst}")
            done.append(os.path.basename(mpc))
    if not done:
        print("kr 번역이 있는 곡이 없습니다")
    return done


def deploy(songs):
    n = 0
    for p in sorted(glob.glob(os.path.join(PATCHED, "dan_*.mpc"))):
        name = os.path.basename(p)
        song = name.split("_")[1]
        if songs and song not in songs:
            continue
        if not os.path.isdir(KOR_RES):
            sys.exit(f"[중단] 사본 없음: {KOR_RES} (공유 game에는 배포하지 않음)")
        dst = os.path.join(KOR_RES, "dance", name)
        bak = dst + ".orig_kor"
        if not os.path.exists(bak):
            shutil.copy2(dst, bak)
        shutil.copy2(p, dst)
        assert md5(open(p, "rb").read()) == md5(open(dst, "rb").read())
        print(f"배포: {dst} ({os.path.getsize(dst):,}B)")
        n += 1
    print(f"{n}개 배포 (복원 = *.orig_kor 되돌리기)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "deploy"])
    ap.add_argument("--songs", help="쉼표 구분 곡코드 (기본: kr 있는 전부)")
    a = ap.parse_args()
    songs = set(a.songs.split(",")) if a.songs else None
    if a.cmd == "build":
        build(songs)
    else:
        deploy(songs)


if __name__ == "__main__":
    main()
