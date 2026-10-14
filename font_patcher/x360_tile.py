#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xenos(360) 텍스처 타일링 — DXT 블록(16B) 단위. imas2pc window.cpp의
GetTiledOffset2D(Xenia texture_util)와 동일 공식, numpy 벡터화."""
import numpy as np


def tiled_block_offsets(wb: int, hb: int):
    """(hb, wb) 각 블록 좌표의 타일드 '블록 인덱스' 배열을 돌려준다.
    bpb=16B(log2=4) 기준: 반환값 * 16 = 바이트 오프셋."""
    bpb_log2 = 4
    x = np.tile(np.arange(wb, dtype=np.int64), (hb, 1))
    y = np.repeat(np.arange(hb, dtype=np.int64)[:, None], wb, axis=1)
    pitch = (wb + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (pitch >> 5)) << (bpb_log2 + 7)
    micro = ((x & 7) + ((y & 0xE) << 2)) << bpb_log2
    offset = macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 1) << 4)
    byte_off = (((offset & ~0x1FF) << 3) + ((y & 16) << 7) + ((offset & 0x1C0) << 2)
                + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (offset & 0x3F))
    return byte_off >> bpb_log2   # 블록 인덱스


def untile_dxt(raw: bytes, w: int, h: int) -> bytes:
    """타일드 DXT(16B/블록) → 선형(블록 행우선)."""
    wb, hb = w // 4, h // 4
    src = np.frombuffer(raw, dtype=np.uint8)
    need = wb * hb * 16
    blocks = src[: ((src.size) // 16) * 16].reshape(-1, 16)
    idx = tiled_block_offsets(wb, hb).reshape(-1)
    out = blocks[idx]               # 선형 (by,bx) 순서로 타일드 위치에서 수집
    return out.reshape(-1).tobytes()[:need]


def tile_dxt(raw: bytes, w: int, h: int, total_blocks: int | None = None) -> bytes:
    """선형 DXT → 타일드. total_blocks로 패딩된 전체 블록 수 지정 가능."""
    wb, hb = w // 4, h // 4
    lin = np.frombuffer(raw, dtype=np.uint8)[: wb * hb * 16].reshape(-1, 16)
    idx = tiled_block_offsets(wb, hb).reshape(-1)
    n = total_blocks if total_blocks else int(idx.max()) + 1
    out = np.zeros((n, 16), dtype=np.uint8)
    out[idx] = lin
    return out.reshape(-1).tobytes()
