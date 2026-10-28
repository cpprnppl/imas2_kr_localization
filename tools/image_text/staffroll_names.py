#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스태프롤 한자 이름(64×64 글자 타일 조립) → 웹앱 「스태프롤 이름」 메뉴용 메타 (staffroll_names.json)

이름 하나 = SWG 스프라이트 하나. 칸마다 타일 비트맵 1장(md5 = 웹앱 이미지 행 키 = tex_kr 키).
칸 좌표는 staffroll_layout.py 재배치(틈 0, 첫 칸 고정) 뒤의 정지 자세 — 패치된 게임 화면과 같다.
칸 위치는 스프라이트 마지막 프레임 레코드의 이동 명령이 가리키는 행렬(=정지 자세)에서 읽는다.
  · 본편 ProStaffRoll.tsk 19명(PS3·360 공통 — 데이터 동일), 류구코마치 exep_staff_roll.mpc 7명(PS3 전용)
  · 류구 타일은 본편 타일과 md5가 같아(45/45) 작업 단위는 본편 이름 하나로 묶인다
  · 双海亜美/双海真美는 双·海·美 타일(같은 비트맵)을 공유 — 한쪽 작업이 다른 쪽에도 그대로 뜬다
화면 변환(이름 로컬 → 1280×720)은 360 실화면 frame_006(天海春香, 칸 중심 233/302/405/475)에 맞춘 값.

  python staffroll_names.py            # staffroll_names.json 생성 (webapp_build.py가 META에 내장)
"""
import os
import sys
import json
import math
import struct
import hashlib
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tile_banner as TB  # noqa: E402
from extract_image_text import OUT_DEFAULT  # noqa: E402

CACHE = os.path.join(OUT_DEFAULT, "_cache", "jp", "interface")     # 순정 복호화 캐시
OUT = os.path.join(HERE, "staffroll_names.json")

# (파일, SWG, 스프라이트, 일본어 이름, 역할) — 스프라이트 번호는 staffroll Phase 0 조사(워크로그)
MAIN = [(231, "天海春香", "아이돌"), (244, "星井美希", "아이돌"), (251, "如月千早", "아이돌"),
        (258, "高槻やよい", "아이돌"), (265, "萩原雪歩", "아이돌"), (272, "菊地真", "아이돌"),
        (279, "双海真美", "아이돌"), (286, "四条貴音", "아이돌"), (293, "我那覇響", "아이돌"),
        (300, "水瀬伊織", "아이돌"), (306, "双海亜美", "아이돌"), (311, "三浦あずさ", "아이돌"),
        (318, "秋月律子", "아이돌"), (328, "天ヶ瀬冬馬", "Jupiter"), (336, "御手洗翔太", "Jupiter"),
        (341, "伊集院北斗", "Jupiter"), (347, "音無小鳥", "사무원"), (354, "高木順二朗", "765 사장"),
        (361, "黒井崇男", "961 사장")]
RYU = [(124, "水瀬伊織", "竜宮小町"), (137, "双海亜美", "竜宮小町"), (144, "三浦あずさ", "竜宮小町"),
       (151, "秋月律子", "竜宮小町 프로듀서"),
       (159, "伊集院北斗", "Jupiter"), (160, "御手洗翔太", "Jupiter"), (162, "天ヶ瀬冬馬", "Jupiter")]
FILES = {"main": "swg\\ProStaffRoll.tsk", "ryu": "exep_staff_roll.mpc"}

# 이름 로컬 좌표 → 화면: 칸 중심(로컬 x+32, y+32)을 frame_006 실측 중심에 맞춘 회전+이동(배율 1.0)
CALIB_LOCAL = [(204, 7), (273, 7), (377, 7), (447, 7)]
CALIB_SCREEN = [(233, 168), (302, 174), (405, 183), (475, 189)]


def fit_similarity(src, dst):
    """최소제곱 닮음변환 (a, b, tx, ty): x' = a·x − b·y + tx, y' = b·x + a·y + ty"""
    n = len(src)
    mx = sum(p[0] for p in src) / n; my = sum(p[1] for p in src) / n
    nx = sum(p[0] for p in dst) / n; ny = sum(p[1] for p in dst) / n
    sxx = sxy = ss = 0.0
    for (x, y), (u, v) in zip(src, dst):
        x -= mx; y -= my; u -= nx; v -= ny
        sxx += x * u + y * v; sxy += x * v - y * u; ss += x * x + y * y
    a, b = sxx / ss, sxy / ss
    return a, b, nx - (a * mx - b * my), ny - (b * mx + a * my)


def name_slots(plain, base, sprite):
    """스프라이트의 정지 자세: [(깊이, 비트맵, 행렬[6])] — 마지막 프레임 레코드 기준."""
    s = memoryview(plain)[base:]
    _w = TB._w
    ch_ofs, mt = _w(s, 0x7C), _w(s, 0x54)
    bm_ofs = _w(s, 0x64)

    def shape_bmp(c):
        kind, ofs = _w(s, ch_ofs + c * 8), _w(s, ch_ofs + c * 8 + 4)
        if kind == 0 and _w(s, ofs) == 1:
            return _w(s, ofs + 16)
        if kind == 5:            # 타일 하나를 감싼 스프라이트(류구 제피터 이름)
            ft = _w(s, ofs + 12)
            p, n = _w(s, ft), _w(s, ft + 4)
            if n == 1 and _w(s, p) in (0xFFFFFFF5, 0xFFFFFFF4):
                return shape_bmp(_w(s, p + 8))
        return None

    def mat(i):
        m = struct.unpack_from(">16f", s, mt + i * 64)
        return [m[0], m[1], m[4], m[5], m[12], m[13]]

    kind, ofs = _w(s, ch_ofs + sprite * 8), _w(s, ch_ofs + sprite * 8 + 4)
    assert kind == 5, (sprite, kind)
    _nf, _lab, _dep, ft, nrec = (_w(s, ofs + k * 4) for k in range(5))
    placed = {}            # depth -> [bitmap, matrix idx]
    ptr_depth = {}         # 이동 명령의 대상 포인터 → 깊이 (배치 직후 처음 나오는 순서)
    pending = []
    for f in range(nrec):
        p, n = _w(s, ft + f * 8), _w(s, ft + f * 8 + 4)
        o = p
        for _ in range(n):
            op = _w(s, o)
            if op in (0xFFFFFFF5, 0xFFFFFFF4):
                d, ch, mi = _w(s, o + 4), _w(s, o + 8), _w(s, o + 12)
                b = shape_bmp(ch)
                if b is not None:
                    placed[d] = [b, mi]
                    pending.append(d)
                o += 20 if op == 0xFFFFFFF5 else 16
            else:
                key = op >> 2
                if key not in ptr_depth and pending:
                    ptr_depth[key] = pending.pop(0)
                d = ptr_depth.get(key)
                mi = _w(s, o + 4) if op & 3 == 3 else _w(s, o + 8)
                # 류구 제피터 3명은 정지 배치(이동 명령 형식이 달라 행렬 번호가 아님) — 범위 밖이면 무시
                if d in placed and mt + mi * 64 + 64 <= len(s):
                    placed[d][1] = mi
                o += 12
    out = []
    for d in sorted(placed):
        b, mi = placed[d]
        out.append((d, b, mat(mi) if mi != 0xFFFFFFFF else [1, 0, 0, 1, 0, 0]))
    return out


def tile_md5s(plain, base):
    return {b: hashlib.md5(plain[t["data_off"]:t["data_off"] + t["data_size"]]).hexdigest()
            for b, t in enumerate(TB.swg_textures(plain, base))}


def md5_locs():
    """md5 → 그 그림이 들어가는 모든 위치(image_extra + 추출 index) — webapp_pull이 md5 키 작업본을 뿌리는 범위"""
    out = collections.defaultdict(set)
    for it in json.load(open(os.path.join(HERE, "image_extra.json"), encoding="utf-8"))["items"]:
        out[it["md5"]].update(it["locs"])
    idx = json.load(open(os.path.join(OUT_DEFAULT, "index.json"), encoding="utf-8"))
    for rel, r in idx.items():
        for t in r["jp"]["textures"]:
            if "md5" in t:
                out[t["md5"]].add(f"{rel}#{t['n']:03d}")
    return out


def main():
    a, b, tx, ty = fit_similarity([(x + 32, y + 32) for x, y in CALIB_LOCAL], CALIB_SCREEN)
    names = []
    for tag, rel in FILES.items():
        plain = open(os.path.join(CACHE, rel), "rb").read()
        md5 = tile_md5s(plain, plain.find(b"SWG\x00"))      # 타일 키 = 순정 텍스처 md5
        import staffroll_layout as SL                       # 칸 위치는 한글 패치의 재배치(틈 0) 뒤 기준
        plain = SL.relayout(plain, tag)
        base = plain.find(b"SWG\x00")
        for ent in (MAIN if tag == "main" else RYU):
            sp, jp = ent[0], ent[1]
            slots = name_slots(plain, base, sp)
            # 류구 제피터 3명은 같은 타일을 (+2,+2) 그림자로 한 번 더 깐다 — 칸은 앞쪽(그림자 아님)만
            seen, uniq = set(), []
            for d, bm, m in sorted(slots, key=lambda v: (v[2][4], v[2][5])):
                if bm in seen:
                    continue
                seen.add(bm)
                uniq.append({"md5": md5[bm], "loc": f"interface\\{rel}#{bm:03d}",
                             "x": round(m[4], 2), "y": round(m[5], 2)})
            assert len(uniq) == len(jp), (tag, sp, jp, len(uniq))
            approx = uniq[0]["x"] != 204 or uniq[0]["y"] != 7
            if approx:   # 정지 배치 이름(류구 제피터): 이름 원점이 달라 본편 첫 칸(204,7)에 맞춰 옮겨 미리보기
                dx, dy = 204 - uniq[0]["x"], 7 - uniq[0]["y"]
                for sl in uniq:
                    sl["x"] += dx; sl["y"] += dy
            names.append({"id": f"{tag}{sp}", "file": rel.split("\\")[-1], "sprite": sp, "jp": jp,
                          "role": ent[2], "plat": "ps3" if tag == "ryu" else "both",
                          "slots": uniq, "shadow": len(slots) > len(uniq), "approx": approx})
    # 류구 이름 → 칸 md5가 전부 같은 본편 이름 (작업 단위는 본편 쪽)
    for nm in names:
        nm["same_as"] = ""
        if nm["plat"] == "ps3":
            sig = [s["md5"] for s in nm["slots"]]
            for o in names:
                if o["plat"] == "both" and [s["md5"] for s in o["slots"]] == sig:
                    nm["same_as"] = o["id"]
    # 위치 묶음: 본편 칸 ↔ 같은 류구 칸, 그리고 같은 비트맵을 쓰는 칸(쌍둥이 双·海·美)은 같은 위치라 자동으로 묶임
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_id = {nm["id"]: nm for nm in names}
    for nm in names:
        for k, sl in enumerate(nm["slots"]):
            find(sl["loc"])
            if nm["same_as"]:
                parent[find(sl["loc"])] = find(by_id[nm["same_as"]]["slots"][k]["loc"])
    groups = collections.defaultdict(set)
    for x in list(parent):
        groups[find(x)].add(x)
    loc_names = collections.defaultdict(set)
    for nm in names:
        for sl in nm["slots"]:
            loc_names[sl["loc"]].add(nm["id"])
    ml = md5_locs()
    per_loc = 0
    for nm in names:
        for sl in nm["slots"]:
            grp = sorted(groups[find(sl["loc"])])
            allm = ml[sl["md5"]]
            assert set(grp) <= allm, (nm["id"], sl, grp, allm)
            # md5 키 = 그 그림의 모든 위치에 들어감. 같은 그림을 다른 이름 칸이 따로 쓰면(海·井·月) 위치 키로 분리
            if set(grp) == allm:
                sl["keys"] = [sl["md5"]]
            else:
                sl["keys"] = [f"{sl['md5']}@{lc}" for lc in grp]
                per_loc += 1
            sl["affects"] = sorted({i for lc in grp for i in loc_names[lc]} - {nm["id"], nm["same_as"]}
                                   - {o["id"] for o in names if o["same_as"] == nm["id"]})
    meta = {"_doc": "staffroll_names.py 생성 — 웹앱 「스태프롤 이름」 메뉴. 칸 x,y = 이름 로컬(정지 자세, 64×64 좌상단), "
                    "keys = 저장할 tex_kr 키(md5 또는 md5@위치 — webapp_pull이 위치 키를 그 위치에만 씀), "
                    "affects = 같이 바뀌는 다른 이름, screen = 로컬→1280×720 닮음변환 [a,b,tx,ty] (frame_006 天海春香 실측)",
            "screen": [round(a, 5), round(b, 5), round(tx, 2), round(ty, 2)],
            "names": names}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    ang = math.degrees(math.atan2(b, a))
    print(f"화면 변환: 배율 {math.hypot(a, b):.4f}, 각도 {ang:.2f}°, 이동 ({tx:.1f},{ty:.1f})")
    for nm in names:
        xs = " ".join(f"{s['x']:.0f}" + ("@" if len(s["keys"][0]) > 32 else "") +
                      (f"→{'/'.join(s['affects'])}" if s["affects"] else "") for s in nm["slots"])
        extra = (f" = {nm['same_as']}" if nm["same_as"] else "") + (" (위치 근사)" if nm["approx"] else "")
        print(f"  {nm['id']:8s} {nm['jp']:6s} [{xs}]{extra}")
    print(f"생성: {OUT} ({len(names)}명, 위치 키 칸 {per_loc})")


if __name__ == "__main__":
    main()
