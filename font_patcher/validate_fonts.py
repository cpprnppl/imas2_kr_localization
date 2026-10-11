#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
리패치 산출물 전수 검증 (배포 게이트).

1. 파일 크기/헤더 불변, NFH는 타깃 레코드만 수정됐는지
2. 모든 레코드 rect가 서로 겹치지 않는지 (시트별)
3. 비타깃 레코드의 rect 픽셀이 순정과 동일한지 (DXT3 4bit 양자화 기준)
4. 타깃 레코드 rect에 잉크가 실제로 존재하는지
실패 시 exit 1 — deploy_fonts.py가 이 결과를 게이트로 사용.
"""
import os
import sys
import json
import struct

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "output")
sys.path.insert(0, SCRIPT_DIR)
from repatch_fonts import (PRISTINE, NFH_RB, NFH_RS, dxt3_alpha_decode,
                           nut_textures, nfh_records, md5)  # noqa: E402

ok = True


def fail(msg):
    global ok
    ok = False
    print(f"[FAIL] {msg}")


def q(a):
    return (a.astype(np.uint16) + 8) // 17


def main():
    mapping = json.load(open(os.path.join(OUT_DIR, "font_mapping_v2.json"), encoding="utf-8"))
    kanji_codes = {ord(v) for v in mapping.values()}

    for name, cfg in PRISTINE.items():
        print(f"▶ {name}")
        assert md5(cfg["nut"]) == cfg["md5_nut"] and md5(cfg["nfh"]) == cfg["md5_nfh"], "순정 해시 불일치"
        p_nut = open(cfg["nut"], "rb").read()
        p_nfh = open(cfg["nfh"], "rb").read()
        o_nut = open(os.path.join(OUT_DIR, f"{name}.nut"), "rb").read()
        o_nfh = open(os.path.join(OUT_DIR, f"{name}.nfh"), "rb").read()

        if len(p_nut) != len(o_nut):
            fail(f"{name}.nut 크기 변동 {len(p_nut)} -> {len(o_nut)}")
        if len(p_nfh) != len(o_nfh):
            fail(f"{name}.nfh 크기 변동")
        if p_nfh[:NFH_RB] != o_nfh[:NFH_RB]:
            fail(f"{name}.nfh 헤더 변조")

        p_recs = nfh_records(p_nfh)
        o_recs = nfh_records(o_nfh)
        n_target = n_mod_nontarget = 0
        for pr, orr in zip(p_recs, o_recs):
            changed = p_nfh[pr["off"]:pr["off"] + 32] != o_nfh[pr["off"]:pr["off"] + 32]
            if pr["code"] in kanji_codes:
                if changed:
                    n_target += 1
            elif changed:
                n_mod_nontarget += 1
                fail(f"비타깃 레코드 수정됨 idx={pr['idx']} code={pr['code']:04X}")
        print(f"  타깃 수정 {n_target} / 비타깃 수정 {n_mod_nontarget}")

        # NUT 텍스처 헤더 불변 확인 + 시트 디코드
        p_tex = nut_textures(p_nut)
        o_tex = nut_textures(o_nut)
        sheets_p, sheets_o = {}, {}
        for gi, (tp, to) in enumerate(zip(p_tex, o_tex)):
            if (tp["raw_off"], tp["w"], tp["h"]) != (to["raw_off"], to["w"], to["h"]):
                fail(f"텍스처 {gi} 헤더 상이")
            if p_nut[tp["header"]:tp["header"] + 80] != o_nut[to["header"]:to["header"] + 80]:
                fail(f"텍스처 {gi} 슬롯 헤더 변조")
            sheets_p[gi] = dxt3_alpha_decode(p_nut[tp["raw_off"]:tp["raw_off"] + tp["raw"]], tp["w"], tp["h"])
            sheets_o[gi] = dxt3_alpha_decode(o_nut[to["raw_off"]:to["raw_off"] + to["raw"]], to["w"], to["h"])

        # rect 겹침 검사: 순정에 이미 있던 겹침 쌍은 허용, 새로 생긴 겹침만 FAIL
        def overlap_pairs(recs_):
            pairs = set()
            buckets = {}
            for r in recs_:
                if r["w"] == 0 or r["h"] == 0:
                    continue
                for by_ in range(r["y"] // 64, (r["y"] + r["h"]) // 64 + 1):
                    for bx_ in range(r["x"] // 64, (r["x"] + r["w"]) // 64 + 1):
                        buckets.setdefault((r["gidx"], by_, bx_), []).append(r)
            for lst in buckets.values():
                for i in range(len(lst)):
                    a = lst[i]
                    for j in range(i + 1, len(lst)):
                        b = lst[j]
                        if (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                                and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]):
                            pairs.add((min(a["idx"], b["idx"]), max(a["idx"], b["idx"])))
            return pairs

        new_ov = overlap_pairs(o_recs) - overlap_pairs(p_recs)
        if new_ov:
            for a, b in sorted(new_ov):
                fail(f"신규 rect 겹침: idx {a} <-> {b}")
        else:
            print(f"  신규 rect 겹침 없음 ({len(o_recs)} 레코드, 순정 기존 겹침은 허용)")

        bad_pix = empty_ink = 0
        for pr, orr in zip(p_recs, o_recs):
            if pr["code"] in kanji_codes:
                cell = sheets_o[orr["gidx"]][orr["y"]:orr["y"] + orr["h"], orr["x"]:orr["x"] + orr["w"]]
                if not (cell > 32).any():
                    empty_ink += 1
                    fail(f"타깃 잉크 없음 code={pr['code']:04X}")
            else:
                a = sheets_p[pr["gidx"]][pr["y"]:pr["y"] + pr["h"], pr["x"]:pr["x"] + pr["w"]]
                b = sheets_o[orr["gidx"]][orr["y"]:orr["y"] + orr["h"], orr["x"]:orr["x"] + orr["w"]]
                if not np.array_equal(q(a), q(b)):
                    bad_pix += 1
                    if bad_pix <= 5:
                        fail(f"비타깃 글리프 픽셀 변동 code={pr['code']:04X} ({pr['x']},{pr['y']})")
        if bad_pix == 0:
            print("  비타깃 글리프 픽셀 보존 확인")
        if empty_ink == 0:
            print("  타깃 전체 잉크 존재 확인")

    print("\n결과:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
