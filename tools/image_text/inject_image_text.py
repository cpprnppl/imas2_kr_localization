#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IM@S2 UI 이미지 텍스트 재주입기

이미지 작업자가 수정한 한글 PNG를 원본 텍스처 자리(data_off)에 제자리 덮어쓰기한다.
크기·치수·포맷 불변이 원칙이라 pac/NUT 구조는 전혀 건드리지 않는다.

입력:  <out>/kr/<상대경로>/<파일명>_<nnn>.png   (jp/와 같은 이름 규칙)
원본:  <out>/_cache/jp/<상대경로>              (extract_image_text.py가 만든 복호화 사본)
출력:  <out>/patched/<상대경로>                (게임 원본은 절대 건드리지 않음)

검증 게이트(전수, 실패 시 해당 파일 산출 안 함):
  1. 출력 크기 = 원본 크기, 주입 영역 밖 바이트 전부 동일
  2. NUT 재파싱 성공 + 텍스처 수/치수/포맷 불변
  3. 주입 영역 재디코드 vs 입력 PNG: 무손실 포맷은 완전 일치,
     DXT는 PSNR >= --min-psnr (기본 33dB)

자가 검증(한글 PNG가 나오기 전 파이프라인 신뢰성 확인):
  python inject_image_text.py --selftest
  → cn_ref/의 CN 수정 텍스처 전부를 한글 PNG 대신 주입해 보고 게이트 통과 확인.

배포는 별도: 검증 통과한 patched/ 파일을 수동 확인 후 게임 폴더에 반영한다.
(.s2d/.nut/.tsk/.xmb는 원본이 암호화본이라 평문 교체가 되는지 인게임 1회 검증 먼저 —
 중국팀 패치는 전부 평문 배포이므로 통할 것으로 보임. index.md 주의점 참조)
"""
import os
import re
import sys
import json
import hashlib
import argparse

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_image_text import (  # noqa: E402
    OUT_DEFAULT, decode_texture, walk_nuts)

# 눈검수로 확인한 개별 예외만 (문턱값 자체는 유지). 키 = "상대경로#nnn"
PSNR_OVERRIDES = {
    "game\\alf\\alf_live.mpc#007": {
        "min": 32.5, "why": "회장 흥분도 라벨, 짙은 글로우 — 4배 확대 비교에서 원본과 구분 불가 (2026-10-22)"},
}

FMT_IDS = {"DXT1": 0, "DXT3": 1, "DXT5": 2, "ARGB1555": 6, "RGB565": 6, "ARGB4444": 7,
           "ARGB32": 14, "ARGB32L": 17}


# ---------------------------------------------------------------- encoders

def _to_565(px: np.ndarray) -> np.ndarray:
    """(...,3) float RGB → u16 RGB565."""
    r = np.clip(np.round(px[..., 0] * 31 / 255), 0, 31).astype(np.uint16)
    g = np.clip(np.round(px[..., 1] * 63 / 255), 0, 63).astype(np.uint16)
    b = np.clip(np.round(px[..., 2] * 31 / 255), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def _from_565(c: np.ndarray) -> np.ndarray:
    return np.stack([((c >> 11) & 31) * (255.0 / 31),
                     ((c >> 5) & 63) * (255.0 / 63),
                     (c & 31) * (255.0 / 31)], axis=-1)


def _blocks(img: np.ndarray) -> np.ndarray:
    """(h,w,4) → (N,16,4) 4x4 블록 픽셀."""
    h, w = img.shape[:2]
    return (img.reshape(h // 4, 4, w // 4, 4, 4)
            .transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4).astype(np.float32))


def _pick_indices(rgb, c0, c1, three: bool, opaque):
    """양 끝점에서 팔레트를 만들어 픽셀별 최근접 인덱스 선택."""
    p0, p1 = _from_565(c0), _from_565(c1)
    if three:
        pal = np.stack([p0, p1, (p0 + p1) / 2], axis=1)
    else:
        pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)
    d = ((rgb[:, None, :, :] - pal[:, :, None, :]) ** 2).sum(-1)  # (N,pal,16)
    idx = d.argmin(axis=1)
    if three:
        idx = np.where(opaque, idx, 3)
    else:
        idx = np.where((c0 == c1)[:, None], 0, idx)
    return idx


def _refine_endpoints(rgb, idx, three: bool, opaque, weight=None):
    """인덱스 고정 후 끝점 최소자승 재해(클러스터핏 라이트). 반환 (c0,c1) 565.
    weight: (N,16) 픽셀 가중치(알파) — 안 보이는 픽셀이 끝점을 끌지 않게."""
    wtab = np.array([1.0, 0.0, 0.5, 0.0], np.float32) if three else \
        np.array([1.0, 0.0, 2 / 3, 1 / 3], np.float32)
    w = wtab[idx]                                   # (N,16)
    m = opaque.astype(np.float32) if three else np.ones_like(w)
    if weight is not None:
        m = m * weight
    a00 = (m * w * w).sum(1)
    a01 = (m * w * (1 - w)).sum(1)
    a11 = (m * (1 - w) * (1 - w)).sum(1)
    det = a00 * a11 - a01 * a01
    good = det > 1e-4
    dsafe = np.where(good, det, 1.0)
    b0 = (m[..., None] * w[..., None] * rgb).sum(1)         # (N,3)
    b1 = (m[..., None] * (1 - w[..., None]) * rgb).sum(1)
    e0 = (a11[:, None] * b0 - a01[:, None] * b1) / dsafe[:, None]
    e1 = (a00[:, None] * b1 - a01[:, None] * b0) / dsafe[:, None]
    c0n = _to_565(np.clip(e0, 0, 255))
    c1n = _to_565(np.clip(e1, 0, 255))
    return c0n, c1n, good


def _encode_color_blocks(blk: np.ndarray, dxt1_alpha: np.ndarray | None,
                         weight: np.ndarray | None = None):
    """DXT 컬러 블록: range-fit + 최소자승 끝점 정제 2회.
    blk: (N,16,4). dxt1_alpha: (N,16) bool(불투명) 또는 None(항상 4색 모드).
    weight: (N,16) 가중치(DXT3/5는 알파/255) — 끝점·오차를 보이는 픽셀 위주로."""
    n = len(blk)
    rgb = blk[:, :, :3]
    three = dxt1_alpha is not None
    if three:
        opaque = dxt1_alpha
        w = opaque[..., None].astype(np.float32)
        any_op = opaque.any(axis=1)
        lo = np.where(any_op[:, None],
                      np.min(np.where(w > 0, rgb, 255.0), axis=1), 0.0)
        hi = np.where(any_op[:, None],
                      np.max(np.where(w > 0, rgb, 0.0), axis=1), 0.0)
    else:
        opaque = np.ones(blk.shape[:2], bool)
        if weight is not None:
            vis = (weight > 0.04)[..., None]
            any_v = vis.any(axis=1)
            lo = np.where(any_v, np.min(np.where(vis, rgb, 255.0), axis=1), rgb.min(axis=1))
            hi = np.where(any_v, np.max(np.where(vis, rgb, 0.0), axis=1), rgb.max(axis=1))
        else:
            lo = rgb.min(axis=1)
            hi = rgb.max(axis=1)
    errw = opaque.astype(np.float32) if weight is None else opaque * weight
    c0, c1 = _to_565(hi), _to_565(lo)

    def order(c0, c1):
        if three:  # 3색 모드: c0 <= c1
            return np.minimum(c0, c1), np.maximum(c0, c1)
        return np.maximum(c0, c1), np.minimum(c0, c1)  # 4색 모드: c0 >= c1

    def sse(idx, c0, c1):
        p0, p1 = _from_565(c0), _from_565(c1)
        if three:
            pal = np.stack([p0, p1, (p0 + p1) / 2, np.zeros_like(p0)], axis=1)
        else:
            pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)
        rec = pal[np.arange(n)[:, None], idx]
        err = ((rec - rgb) ** 2).sum(-1)
        return (err * errw).sum(1)

    c0, c1 = order(c0, c1)
    idx = _pick_indices(rgb, c0, c1, three, opaque)
    best = sse(idx, c0, c1)
    bc0, bc1, bidx = c0.copy(), c1.copy(), idx.copy()

    # 후보 2: 가중 주성분(PCA) 축 양 끝 — 대각선 색 분포(글로우·그라데이션)에 강함
    wv = errw[..., None]
    wsum = np.maximum(wv.sum(1), 1e-6)
    mean = (rgb * wv).sum(1) / wsum
    dif = (rgb - mean[:, None, :]) * np.sqrt(wv)
    cov = np.einsum("nki,nkj->nij", dif, dif)
    axis = np.ones((n, 3), np.float32)
    for _ in range(8):
        axis = np.einsum("nij,nj->ni", cov, axis)
        axis /= np.maximum(np.linalg.norm(axis, axis=1, keepdims=True), 1e-6)
    proj = np.einsum("nki,ni->nk", rgb - mean[:, None, :], axis)
    proj_v = np.where(errw > 0.04, proj, np.nan)
    pmin = np.nan_to_num(np.nanmin(np.where(np.isnan(proj_v).all(1, keepdims=True), proj, proj_v), axis=1))
    pmax = np.nan_to_num(np.nanmax(np.where(np.isnan(proj_v).all(1, keepdims=True), proj, proj_v), axis=1))
    e_hi = np.clip(mean + axis * pmax[:, None], 0, 255)
    e_lo = np.clip(mean + axis * pmin[:, None], 0, 255)
    pc0, pc1 = order(_to_565(e_hi), _to_565(e_lo))
    pidx = _pick_indices(rgb, pc0, pc1, three, opaque)
    pcur = sse(pidx, pc0, pc1)
    better = pcur < best
    bc0 = np.where(better, pc0, bc0)
    bc1 = np.where(better, pc1, bc1)
    bidx = np.where(better[:, None], pidx, bidx)
    best = np.minimum(best, pcur)
    c0, c1, idx = bc0.copy(), bc1.copy(), bidx.copy()
    for _ in range(2):
        c0n, c1n, good = _refine_endpoints(rgb, idx, three, opaque, weight)
        c0n, c1n = order(c0n, c1n)
        c0 = np.where(good, c0n, c0)
        c1 = np.where(good, c1n, c1)
        idx = _pick_indices(rgb, c0, c1, three, opaque)
        cur = sse(idx, c0, c1)
        better = cur < best
        bc0 = np.where(better, c0, bc0)
        bc1 = np.where(better, c1, bc1)
        bidx = np.where(better[:, None], idx, bidx)
        best = np.minimum(best, cur)
    c0, c1, idx = bc0, bc1, bidx

    out = np.zeros((n, 8), np.uint8)
    out[:, 0] = c0 & 0xFF
    out[:, 1] = c0 >> 8
    out[:, 2] = c1 & 0xFF
    out[:, 3] = c1 >> 8
    sh = idx.reshape(n, 4, 4).astype(np.uint32)
    rowbits = sh[:, :, 0] | (sh[:, :, 1] << 2) | (sh[:, :, 2] << 4) | (sh[:, :, 3] << 6)
    out[:, 4:8] = rowbits.astype(np.uint8)
    return out


def _encode_dxt5_alpha(a: np.ndarray) -> np.ndarray:
    """a: (N,16) float → (N,8) uint8."""
    n = len(a)
    a0 = a.max(axis=1)
    a1 = a.min(axis=1)
    flat = a0 <= a1
    a0 = np.where(flat, np.minimum(a0 + 1, 255), a0)  # a0>a1 보장(8스텝 모드)
    pal = np.zeros((n, 8), np.float32)
    pal[:, 0], pal[:, 1] = a0, a1
    for k in range(2, 8):
        pal[:, k] = ((8 - k) * a0 + (k - 1) * a1) / 7
    d = np.abs(a[:, None, :] - pal[:, :, None])  # (N,8,16)
    idx = d.argmin(axis=1).astype(np.uint64)     # (N,16)
    v = np.zeros(n, np.uint64)
    for p in range(16):
        v |= idx[:, p] << np.uint64(3 * p)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0] = np.round(a0).astype(np.uint8)
    out[:, 1] = np.round(a1).astype(np.uint8)
    for i in range(6):
        out[:, 2 + i] = ((v >> np.uint64(8 * i)) & np.uint64(0xFF)).astype(np.uint8)
    return out


def encode_texture(fmt_name: str, img: np.ndarray) -> bytes:
    """(h,w,4) uint8 RGBA → 해당 포맷 payload (상위 밉 1장)."""
    h, w = img.shape[:2]
    if fmt_name in ("ARGB32", "ARGB32L"):
        return img[..., [3, 0, 1, 2]].tobytes()
    if fmt_name in ("ARGB1555", "RGB565"):   # fmt 6 — 'RGB565'는 옛 index 이름(실제 1555)
        f = img.astype(np.float32)
        r, g, b = (np.clip(np.round(f[..., c] * 31 / 255), 0, 31).astype(np.uint16) for c in range(3))
        a = (img[..., 3] >= 128).astype(np.uint16)
        return ((a << 15) | (r << 10) | (g << 5) | b).astype(">u2").tobytes()
    if fmt_name == "ARGB4444":
        q = np.clip(np.round(img.astype(np.float32) / 17), 0, 15).astype(np.uint16)
        v = (q[..., 3] << 12) | (q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]
        return v.astype(">u2").tobytes()
    if w % 4 or h % 4:
        raise ValueError(f"DXT인데 4배수 아님: {w}x{h}")
    blk = _blocks(img)
    if fmt_name == "DXT1":
        opaque = blk[:, :, 3] >= 128
        use3 = ~opaque.all(axis=1)  # 블록에 투명 픽셀이 있으면 3색 모드
        out = np.empty((len(blk), 8), np.uint8)
        if use3.any():
            out[use3] = _encode_color_blocks(blk[use3], opaque[use3])
        if (~use3).any():
            out[~use3] = _encode_color_blocks(blk[~use3], None)
        return out.tobytes()
    if fmt_name in ("DXT3", "DXT5"):
        color = _encode_color_blocks(blk, None, weight=blk[:, :, 3] / 255.0)
        if fmt_name == "DXT3":
            q = np.clip(np.round(blk[:, :, 3] / 17), 0, 15).astype(np.uint16)
            q = q.reshape(-1, 4, 4)
            vrow = q[:, :, 0] | (q[:, :, 1] << 4) | (q[:, :, 2] << 8) | (q[:, :, 3] << 12)
            ab = np.zeros((len(blk), 8), np.uint8)
            ab[:, 0::2] = (vrow & 0xFF).astype(np.uint8)
            ab[:, 1::2] = (vrow >> 8).astype(np.uint8)
        else:
            ab = _encode_dxt5_alpha(blk[:, :, 3])
        return np.concatenate([ab, color], axis=1).tobytes()
    raise ValueError(f"미지원 포맷: {fmt_name}")


# ---------------------------------------------------------------- inject

def psnr(a: np.ndarray, b: np.ndarray) -> float:
    """화면에 보이는 값 기준 PSNR: RGBA면 RGB에 알파를 곱해(premultiplied) 비교.
    완전 투명 픽셀의 RGB는 렌더에 안 나오므로 오차로 세지 않는다."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if a.ndim == 3 and a.shape[-1] == 4:
        a = np.concatenate([a[..., :3] * a[..., 3:] / 255.0, a[..., 3:]], axis=-1)
        b = np.concatenate([b[..., :3] * b[..., 3:] / 255.0, b[..., 3:]], axis=-1)
    mse = np.mean((a - b) ** 2)
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def inject_file(rel: str, texmap: dict, jobs: list, out_root: str,
                dst_dir: str, min_psnr: float, log) -> bool:
    """jobs: [(n, png_path)]. 성공 시 patched/<rel> 생성."""
    src_path = os.path.join(out_root, "_cache", "jp", rel)
    data = bytearray(open(src_path, "rb").read())
    orig = bytes(data)
    results = []
    for n, png in jobs:
        t = texmap.get(n)
        if t is None:
            log(f"    [실패] #{n:03d}: index에 없는 텍스처 번호")
            return False
        if "error" in t:
            log(f"    [실패] #{n:03d}: 추출 시점 디코드 실패였던 텍스처")
            return False
        img = np.asarray(Image.open(png).convert("RGBA"), np.uint8)
        if img.shape[:2] != (t["h"], t["w"]):
            log(f"    [실패] #{n:03d}: 치수 불일치 PNG {img.shape[1]}x{img.shape[0]}"
                f" != 원본 {t['w']}x{t['h']} (치수 변경 금지)")
            return False
        if t["mip"] != 1:
            log(f"    [실패] #{n:03d}: mip={t['mip']} — 밉맵 텍스처는 미지원")
            return False
        enc = encode_texture(t["fmt"], img)
        if len(enc) != t["data_size"]:
            log(f"    [실패] #{n:03d}: 인코드 크기 {len(enc)} != data_size {t['data_size']}")
            return False
        data[t["data_off"]:t["data_off"] + t["data_size"]] = enc
        results.append((n, t, img))

    # ---- 게이트 1: 크기/영역 밖 불변
    if len(data) != len(orig):
        log("    [실패] 게이트1: 파일 크기 변동")
        return False
    mask = np.ones(len(orig), bool)
    for n, t, _ in results:
        mask[t["data_off"]:t["data_off"] + t["data_size"]] = False
    oa = np.frombuffer(orig, np.uint8)
    na = np.frombuffer(bytes(data), np.uint8)
    if not (oa[mask] == na[mask]).all():
        log("    [실패] 게이트1: 주입 영역 밖 바이트 변동")
        return False
    # ---- 게이트 2: 구조 재파싱
    texs0 = walk_nuts(orig, lambda *_: None)
    texs1 = walk_nuts(bytes(data), lambda *_: None)
    sig = lambda ts: [(t["tex_off"], t["fmt"], t["w"], t["h"], t["data_size"]) for t in ts]  # noqa: E731
    if sig(texs0) != sig(texs1):
        log("    [실패] 게이트2: NUT 구조 변동")
        return False
    # ---- 게이트 3: 재디코드 일치
    for n, t, img in results:
        raw = bytes(data[t["data_off"]:t["data_off"] + t["data_size"]])
        dec = decode_texture(FMT_IDS[t["fmt"]], raw, t["w"], t["h"])
        if t["fmt"] in ("ARGB32", "ARGB32L"):
            if not (dec == img).all():
                log(f"    [실패] 게이트3: #{n:03d} 무손실 재디코드 불일치")
                return False
        else:
            p = psnr(dec, img)
            ov = PSNR_OVERRIDES.get(f"{rel}#{n:03d}")
            limit = ov["min"] if ov else min_psnr
            if ov and p >= limit:
                log(f"    [예외] #{n:03d} {p:.1f}dB — 눈검수 허용: {ov['why']}")
            if p < limit:
                log(f"    [실패] 게이트3: #{n:03d} {t['fmt']} PSNR {p:.1f}dB < {limit}")
                return False
    dst = os.path.join(dst_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)
    qual = ", ".join(
        f"#{n:03d} 무손실" if t["fmt"] in ("ARGB32", "ARGB32L") else
        f"#{n:03d} {psnr(decode_texture(FMT_IDS[t['fmt']], bytes(data[t['data_off']:t['data_off']+t['data_size']]), t['w'], t['h']), img):.1f}dB"
        for n, t, img in results[:8])
    log(f"    OK {len(results)}장 주입 → patched\\{rel}  ({qual}{'…' if len(results) > 8 else ''})")
    return True


def main():
    ap = argparse.ArgumentParser(description="한글 PNG → 게임 텍스처 재주입 (검증 게이트 포함)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--src", default=None, help="주입 PNG 폴더 (기본 <out>/kr)")
    ap.add_argument("--only", help="상대경로 부분 일치 필터")
    ap.add_argument("--min-psnr", type=float, default=33.0)
    ap.add_argument("--exclude-src", choices=["claude"],
                    help="claude = Claude 초벌 그림(웹앱 '이미지 텍스트' 빈 라벨 자동 렌더)을 빼고 주입(배포판용). 기본은 전부")
    ap.add_argument("--selftest", action="store_true",
                    help="cn_ref/의 CN 수정 텍스처를 주입해 파이프라인 검증")
    args = ap.parse_args()
    log = print

    idx = json.load(open(os.path.join(args.out, "index.json"), encoding="utf-8"))

    if args.selftest:
        src_root = os.path.join(args.out, "cn_ref")
        dst_dir = os.path.join(args.out, "patched_selftest")
        jobs_by_rel = {
            rel: [(n, os.path.join(
                src_root, os.path.dirname(rel),
                r["cn"]["textures"][n]["png"])) for n in r.get("cn_modified", [])]
            for rel, r in idx.items() if r.get("cn_modified")}
    else:
        src_root = args.src or os.path.join(args.out, "kr")
        dst_dir = os.path.join(args.out, "patched")
        jobs_by_rel = {}
        pat = re.compile(r"^(.+)_(\d{3})\.png$", re.I)
        for dirpath, _dirs, files in os.walk(src_root):
            for fn in files:
                m = pat.match(fn)
                if not m:
                    continue
                reldir = os.path.relpath(dirpath, src_root)
                reldir = "" if reldir == "." else reldir
                stem, n = m.group(1), int(m.group(2))
                hit = next(
                    (rel for rel in idx
                     if os.path.dirname(rel) == reldir
                     and os.path.splitext(os.path.basename(rel))[0] == stem), None)
                if hit is None:
                    log(f"[경고] 대응 원본 파일 없음: {os.path.join(reldir, fn)}")
                    continue
                jobs_by_rel.setdefault(hit, []).append(
                    (n, os.path.join(dirpath, fn)))

    if args.only:
        jobs_by_rel = {k: v for k, v in jobs_by_rel.items()
                       if args.only.lower() in k.lower()}
    # Claude 초벌 그림(kr_claude/manifest.json — 팀이 kr/ 파일을 바꿨으면 sha가 달라 초벌로 안 셈)
    man_p = os.path.join(args.out, "kr_claude", "manifest.json")
    claude = {}
    if os.path.exists(man_p) and not args.selftest:
        for v in json.load(open(man_p, encoding="utf-8")).values():
            for f in v["kr_files"]:
                claude[os.path.normcase(os.path.join(src_root, f))] = v["sha256"]

    def is_claude(png):
        h = claude.get(os.path.normcase(png))
        return bool(h) and hashlib.sha256(open(png, "rb").read()).hexdigest() == h
    n_cl = sum(1 for v in jobs_by_rel.values() for _n, p in v if is_claude(p))
    if args.exclude_src == "claude":
        jobs_by_rel = {k: [(n, p) for n, p in v if not is_claude(p)] for k, v in jobs_by_rel.items()}
        jobs_by_rel = {k: v for k, v in jobs_by_rel.items() if v}
        log(f"Claude 초벌 그림 {n_cl}장 제외(--exclude-src claude)")
    else:
        log(f"Claude 초벌 그림 {n_cl}장 포함 (배포판에서 빼려면 --exclude-src claude)")
    if not jobs_by_rel:
        log("주입할 PNG가 없습니다. <out>/kr/ 에 jp/와 같은 이름 규칙으로 넣으세요.")
        return 1

    ok = fail = 0
    for rel in sorted(jobs_by_rel):
        log(f"▶ {rel} ({len(jobs_by_rel[rel])}장)")
        texmap = {t["n"]: t for t in idx[rel]["jp"]["textures"]}
        if inject_file(rel, texmap, sorted(jobs_by_rel[rel]), args.out,
                       dst_dir, args.min_psnr, log):
            ok += 1
        else:
            fail += 1
    log(f"\n완료: {ok}파일 성공, {fail}파일 실패 → {dst_dir}")
    log("배포는 patched/ 내용을 확인한 뒤 수동으로 (게임 원본 백업 필수, index.md 주의점 참조)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
