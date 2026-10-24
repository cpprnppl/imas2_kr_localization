"""KDF1 binary diff: new file = COPY ranges of the source + ADD runs of new bytes.

  "KDF1" | u32 src_size | u32 out_size | ops...       (little-endian)
  op 0 COPY: u32 src_off, u32 len      (must stay inside the source)
  op 1 ADD : u32 len, len bytes        (only our new bytes)

make(src, dst) finds matches through a dict of src blocks (BLOCK bytes at every BLOCK-aligned
offset) and extends each match forwards and backwards. Any common substring of 2*BLOCK bytes
contains an aligned src block, so it is always found: ADD never carries 64+ source bytes.
apply(src, kd) is the reference applier; audit(src, kd) re-checks the ADD runs independently.
"""
import struct

BLOCK = 32
MAGIC = b"KDF1"
HDR = 12


def _index(src):
    index = {}
    for off in range(0, len(src) - BLOCK + 1, BLOCK):
        index.setdefault(src[off:off + BLOCK], off)
    return index


def make(src: bytes, dst: bytes) -> bytes:
    index = _index(src)
    ops = []
    lit_start = 0
    i = 0
    n = len(dst)
    while i + BLOCK <= n:
        s = index.get(dst[i:i + BLOCK])
        if s is None:
            i += 1
            continue
        b = 0                                      # extend backwards into the pending literal
        while i - b > lit_start and s - b > 0 and dst[i - b - 1] == src[s - b - 1]:
            b += 1
        i0, s0 = i - b, s - b
        e = BLOCK                                  # extend forwards: big steps, then smaller
        step = 4096
        while step:
            while i + e + step <= n and s + e + step <= len(src) and dst[i + e:i + e + step] == src[s + e:s + e + step]:
                e += step
            step //= 8
        if i0 > lit_start:
            ops.append((1, dst[lit_start:i0]))
        ops.append((0, s0, e + b))
        i = i + e
        lit_start = i
    if lit_start < n:
        ops.append((1, dst[lit_start:]))
    out = bytearray(MAGIC + struct.pack("<II", len(src), n))
    for op in ops:
        if op[0] == 0:
            out += struct.pack("<BII", 0, op[1], op[2])
        else:
            out += struct.pack("<BI", 1, len(op[1])) + op[1]
    return bytes(out)


def ops(kd: bytes):
    if kd[:4] != MAGIC:
        raise ValueError("not a KDF1 diff")
    p = HDR
    while p < len(kd):
        t = kd[p]
        if t == 0:
            off, ln = struct.unpack_from("<II", kd, p + 1)
            yield 0, off, ln
            p += 9
        elif t == 1:
            ln = struct.unpack_from("<I", kd, p + 1)[0]
            yield 1, kd[p + 5:p + 5 + ln], ln
            p += 5 + ln
        else:
            raise ValueError(f"bad op {t}")


def apply(src: bytes, kd: bytes) -> bytes:
    src_size, size = struct.unpack_from("<II", kd, 4)
    if len(src) != src_size:
        raise ValueError(f"source size {len(src)} != {src_size}")
    out = bytearray()
    for t, a, ln in ops(kd):
        if t == 0:
            if a + ln > len(src):
                raise ValueError("COPY out of range")
            chunk = src[a:a + ln]
        else:
            chunk = a
        if len(out) + len(chunk) > size:
            raise ValueError("output exceeds out_size")
        out += chunk
    if len(out) != size:
        raise ValueError("size mismatch")
    return bytes(out)


def audit(src: bytes, kd: bytes):
    """(total ADD bytes, ADD runs of 64+ bytes that share a 2*BLOCK substring with the source)."""
    index = _index(src)
    total, flagged = 0, []
    pos = 0
    for t, a, ln in ops(kd):
        if t == 1:
            total += ln
            if ln >= 2 * BLOCK and any(a[j:j + BLOCK] in index for j in range(ln - BLOCK + 1)):
                flagged.append((pos, ln))
        pos += ln
    return total, flagged
