#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스태프롤 한자 이름 칸 간격 재배치 — SWG 행렬 제자리 수정 (2026-10-29, 사용자 결정 "틈 0 + 한 줄 이어 쓰기")

이름 칸(64×64 타일)은 칸 번호별 "궤적"(정지 자세 + 날아오는 키프레임 20개의 행렬 묶음)을 이름끼리 공유한다.
같은 궤적을 쓰는 이름은 정지 위치가 같으므로, 궤적마다 dx 하나로 x(행렬 +48)만 옮기면 모든 이름이
"첫 칸 고정, 칸 k = 첫 칸 + PITCH·(k−1)"이 된다. 행렬 값만 바꾸는 같은 크기 수정이라 파일 크기·오프셋 불변.
  · 본편 ProStaffRoll(PS3·360 데이터 동일) / 류구 exep_staff_roll(PS3 전용 — Jupiter 3명은 고정 배치 + 그림자 겹침)
  · 이름 스프라이트 밖에서 쓰는 행렬이면 거부(전수 확인: 없음). 한 궤적에 이동량이 둘 이상이면 거부(충돌 0 확인).

  python staffroll_layout.py check [--pitch 74]      # 순정 캐시로 이동량·충돌·결과 정지 위치 확인(쓰기 없음)
  라이브러리: relayout(plain, kind, pitch) → 새 평문 (ps3_res_apply / pcport_apply 층에서 부름)
"""
import os
import sys
import struct
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tile_banner as TB  # noqa: E402
import staffroll_names as SN  # noqa: E402

_w = TB._w
PITCH = 64                     # 64px 칸, 틈 0 — 이름을 원본 높이로 한 줄에 이어 쓴다(10px 안은 음절이 좁아져 기각, 10-29)
SPRITES = {"main": [n[0] for n in SN.MAIN], "ryu": [n[0] for n in SN.RYU]}


def _tracks(s, sprites):
    """(sprite, depth) → 행렬 번호 순서(연속 중복 제거)와 각 행렬 번호 위치 목록."""
    ch_ofs = _w(s, 0x7C)
    tr = {}
    for sp in sprites:
        ofs = _w(s, ch_ofs + sp * 8 + 4)
        _nf, _lab, _dep, ft, nrec = (_w(s, ofs + k * 4) for k in range(5))
        ptr_depth, pending, seq = {}, [], collections.defaultdict(list)
        for f in range(nrec):
            p, n = _w(s, ft + f * 8), _w(s, ft + f * 8 + 4)
            o = p
            for _ in range(n):
                op = _w(s, o)
                if op in (0xFFFFFFF5, 0xFFFFFFF4):
                    d, mi = _w(s, o + 4), _w(s, o + 12)
                    pending.append(d)
                    seq[d].append(mi)
                    o += 20 if op == 0xFFFFFFF5 else 16
                else:
                    key = op >> 2
                    if key not in ptr_depth and pending:
                        ptr_depth[key] = pending.pop(0)
                    mi = _w(s, o + 4) if op & 3 == 3 else _w(s, o + 8)
                    d = ptr_depth.get(key)
                    if d is not None and mi < _w(s, 0x58):
                        seq[d].append(mi)
                    o += 12
        for d, ms in seq.items():
            tr[(sp, d)] = tuple(m for i, m in enumerate(ms) if i == 0 or ms[i - 1] != m)
    return tr


def plan(plain, kind, pitch=PITCH):
    """{행렬 번호: dx}, 결과 표. 이름마다 층(y)별로 칸을 x순 정렬, 첫 칸 고정."""
    base = plain.find(b"SWG\x00")
    s = memoryview(plain)[base:]
    mt = _w(s, 0x54)
    tr = _tracks(s, SPRITES[kind])
    mx = lambda i: struct.unpack_from(">f", s, mt + i * 64 + 48)[0]
    my = lambda i: struct.unpack_from(">f", s, mt + i * 64 + 52)[0]
    need = collections.defaultdict(set)
    rows = []
    for sp in SPRITES[kind]:
        layers = collections.defaultdict(list)
        for (p, d), t in tr.items():
            if p == sp:
                layers[round(my(t[-1]))].append(d)
        for y, ds in sorted(layers.items()):
            ds.sort(key=lambda d: mx(tr[(sp, d)][-1]))
            x0 = round(mx(tr[(sp, ds[0])][-1]))
            for k, d in enumerate(ds):
                cur = round(mx(tr[(sp, d)][-1]))
                dx = x0 + pitch * k - cur
                need[tr[(sp, d)]].add(dx)
                rows.append((sp, y, k, cur, x0 + pitch * k, dx))
    conflicts = {t: dxs for t, dxs in need.items() if len(dxs) > 1}
    if conflicts:
        raise ValueError(f"궤적 이동량 충돌 {len(conflicts)}건")
    track_dx = {t: next(iter(dxs)) for t, dxs in need.items()}
    # 같은 칸 번호의 궤적들은 출발 키프레임(x273·배율 0.2 등)을 행렬째 공유한다. 이동량이 다른 궤적과 공유하는
    # 행렬은 0으로 두고(출발 자세 그대로), 그 뒤 키프레임에서 0 → dx로 선형으로 늘려 정지 자세에서 dx가 되게 한다.
    users = collections.defaultdict(set)
    for t, dx in track_dx.items():
        for m in t:
            users[m].add(dx)
    per_matrix = {}
    for t, dx in track_dx.items():
        fixed = [i for i, m in enumerate(t) if len(users[m]) > 1]
        if fixed and fixed != list(range(len(fixed))):
            raise ValueError(f"공유 행렬이 궤적 앞쪽이 아님: {fixed}")
        p, n = len(fixed) - 1, len(t)
        # 늘리는 비율은 원래 궤적의 진행도(x가 출발점에서 정지점까지 간 비율)를 따른다 — 키프레임 수에 선형으로 늘리면
        # 원래 움직임이 감속하는 끝 구간에서 더한 이동만 남아 정지 직전 ~10px 되밀림이 생겼다(10-29 PC 1배 확인 중 발견).
        xs = [mx(m) for m in t]
        span = xs[-1] - xs[p] if p >= 0 else 0.0
        for i, m in enumerate(t):
            if i <= p:
                off = 0.0
            elif p < 0:
                off = dx
            elif abs(span) > 1.0:
                off = dx * (xs[i] - xs[p]) / span
            else:
                off = dx * (i - p) / (n - 1 - p)
            if m in per_matrix and abs(per_matrix[m] - off) > 1e-6:
                raise ValueError(f"행렬 {m} 오프셋 불일치 {per_matrix[m]} / {off}")
            per_matrix[m] = off
    return base, mt, per_matrix, rows


def relayout(plain, kind, pitch=PITCH):
    base, mt, per_matrix, _rows = plan(plain, kind, pitch)
    out = bytearray(plain)
    for m, dx in per_matrix.items():
        if dx:
            o = base + mt + m * 64 + 48
            struct.pack_into(">f", out, o, struct.unpack_from(">f", out, o)[0] + dx)
    out = bytes(out)
    # 결과 검증: 같은 크기, 정지 위치가 목표대로
    assert len(out) == len(plain)
    _b, _m, again, rows = plan(out, kind, pitch)
    if any(r[5] for r in rows):
        raise ValueError("재배치 결과가 목표 정지 위치와 다름")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--pitch", type=int, default=PITCH)
    a = ap.parse_args()
    names = {(k, n["sprite"]): n["jp"] for n in __import__("json").load(open(SN.OUT, encoding="utf-8"))["names"]
             for k in (("main",) if n["plat"] == "both" else ("ryu",))}
    for kind, rel in (("main", os.path.join("swg", "ProStaffRoll.tsk")), ("ryu", "exep_staff_roll.mpc")):
        plain = open(os.path.join(SN.CACHE, rel), "rb").read()
        _b, _m, per_matrix, rows = plan(plain, kind, a.pitch)
        new = relayout(plain, kind, a.pitch)
        changed = sum(1 for i in range(0, len(plain), 4) if plain[i:i + 4] != new[i:i + 4])
        print(f"== {rel}: 행렬 {len(per_matrix)}개(이동 {sum(1 for v in per_matrix.values() if v)}), 바뀐 4바이트 워드 {changed}, 크기 {len(new)} 동일")
        by = collections.defaultdict(list)
        for sp, y, k, cur, tgt, dx in rows:
            by[(sp, y)].append((cur, tgt, dx))
        for (sp, y), v in by.items():
            print(f"   {names.get((kind, sp), sp)}{' (그림자)' if kind == 'ryu' and y == 2 else ''}: "
                  + " / ".join(f"{c}→{t}" for c, t, _d in v))


if __name__ == "__main__":
    main()
