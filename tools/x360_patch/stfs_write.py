"""Rebuild a read-only STFS (LIVE) DLC package with replaced files, for RGH/JTAG hardware (user-approved 2026-10-25).

  python stfs_write.py <original package> <replacement root (files by package path)> <out dir>

Same entry order, names and timestamps as the original; files laid out contiguously after the file table;
level-0/1/2 hash tables and the top hash recomputed; header hash (0x32C = SHA-1 of header 0x344..0xB000) and
content size updated. The RSA signature is NOT updated (consoles that skip content signature checks only).
The output file is named <new content id><original 2-char suffix>, like the originals.
Layout/block math: imas2pc tools/stfs_extract.py (rexglue/Xenia lineage).
"""
import hashlib
import os
import struct
import sys

IMAS2PC_TOOLS = os.environ.get("IMAS2PC_TOOLS", os.path.join(os.path.expanduser("~"), "Desktop", "imas2pc", "tools"))
sys.path.insert(0, IMAS2PC_TOOLS)                 # stfs_extract.py (reader)
BLOCK, L0, L1, END = 0x1000, 170, 170 * 170, 0xFFFFFF
BASE = 0xB000


def block_off(idx):                         # read-only package: one hash table per level
    base, blk = L0, idx
    for _ in range(3):
        blk += (idx + base) // base
        if idx < base:
            break
        base *= L0
    return BASE + (blk << 12)


def hash_block(idx, level):
    step0, step1 = L0 + 1, L1 + (L0 + 1)
    if level == 0:
        if idx < L0:
            return 0
        blk = (idx // L0) * step0 + (idx // L1) + 1
        return blk if idx < L1 else blk + 1
    if level == 1:
        return step0 if idx < L1 else (idx // L1) * step1 + 1
    return step1


def u24(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))


def rebuild(orig_path, repl_root, out_dir):
    from stfs_extract import Stfs
    s = Stfs(orig_path)
    if not s.read_only:
        raise ValueError("only read-only packages are supported")
    with open(orig_path, "rb") as f:
        header = bytearray(f.read(BASE))
        raw_ft = b""
        blk = s.ft_block
        for _ in range(s.ft_count):
            f.seek(s.block_off(blk))
            raw_ft += f.read(BLOCK)
            blk = s.next_block(blk)
    ents = s.entries
    datas, replaced = [], 0
    for e in ents:
        if e["dir"]:
            datas.append(None)
            continue
        rp = os.path.join(repl_root, *e["path"].split("/"))
        o = io_read_orig(s, e)
        d = open(rp, "rb").read() if os.path.isfile(rp) else o
        replaced += (d != o)
        datas.append(d)
    # layout
    ft_blocks = (len(ents) + 63) // 64
    nxt, chains, starts = ft_blocks, [], []
    for d in datas:
        if d is None:
            starts.append(0)
            continue
        n = (len(d) + BLOCK - 1) // BLOCK
        starts.append(nxt if n else 0)
        nxt += n
    total = nxt
    blocks_next = {}
    for i in range(ft_blocks):
        blocks_next[i] = i + 1 if i + 1 < ft_blocks else END
    for st, d in zip(starts, datas):
        if d:
            n = (len(d) + BLOCK - 1) // BLOCK
            for k in range(n):
                blocks_next[st + k] = st + k + 1 if k + 1 < n else END
    # file table
    ft = bytearray(ft_blocks * BLOCK)
    for i, (e, d, st) in enumerate(zip(ents, datas, starts)):
        r = bytearray(raw_ft[i * 64:(i + 1) * 64])
        n = 0 if d is None else (len(d) + BLOCK - 1) // BLOCK
        r[41:44] = u24(n)
        r[44:47] = u24(n)
        r[47:50] = u24(st)
        struct.pack_into(">I", r, 52, 0 if d is None else len(d))
        ft[i * 64:(i + 1) * 64] = r
    # write data blocks, collect level-0 hashes
    name = os.path.basename(orig_path)
    tmp = os.path.join(out_dir, name + ".tmp")
    os.makedirs(out_dir, exist_ok=True)
    l0 = {}
    with open(tmp, "wb") as o:
        o.write(bytes(header))

        def put(idx, data):
            data = data.ljust(BLOCK, b"\0")
            o.seek(block_off(idx))
            o.write(data)
            l0[idx] = hashlib.sha1(data).digest() + struct.pack(">I", 0x80000000 | blocks_next[idx])

        for i in range(ft_blocks):
            put(i, ft[i * BLOCK:(i + 1) * BLOCK])
        for st, d in zip(starts, datas):
            if d:
                for k in range(0, len(d), BLOCK):
                    put(st + k // BLOCK, d[k:k + BLOCK])
        # level 0 tables
        tables0 = {}
        for g in range((total + L0 - 1) // L0):
            t = bytearray(BLOCK)
            for j in range(L0):
                idx = g * L0 + j
                if idx < total:
                    t[j * 24:(j + 1) * 24] = l0[idx]
            tables0[g] = bytes(t)
            o.seek(BASE + (hash_block(g * L0, 0) << 12))
            o.write(t)
        top = tables0[0]
        if total > L0:
            tables1 = {}
            for g1 in range((total + L1 - 1) // L1):
                t = bytearray(BLOCK)
                for j in range(L0):
                    g = g1 * L0 + j
                    if g in tables0:
                        t[j * 24:j * 24 + 20] = hashlib.sha1(tables0[g]).digest()
                tables1[g1] = bytes(t)
                o.seek(BASE + (hash_block(g1 * L1, 1) << 12))
                o.write(t)
            top = tables1[0]
            if total > L1:
                t = bytearray(BLOCK)
                for g1, tb in tables1.items():
                    t[g1 * 24:g1 * 24 + 20] = hashlib.sha1(tb).digest()
                o.seek(BASE + (hash_block(0, 2) << 12))
                o.write(t)
                top = bytes(t)
        end = o.seek(0, 2)
        # header: volume descriptor, content size, header hash
        vd = 0x379
        struct.pack_into("<H", header, vd + 3, ft_blocks)
        header[vd + 5:vd + 8] = u24(0)
        header[vd + 8:vd + 28] = hashlib.sha1(top).digest()
        struct.pack_into(">II", header, vd + 0x1C, total, 0)
        struct.pack_into(">Q", header, 0x34C, end - BASE)
        header[0x32C:0x340] = hashlib.sha1(bytes(header[0x344:BASE])).digest()
        o.seek(0)
        o.write(bytes(header))
    new_name = header[0x32C:0x340].hex().upper() + name[40:]
    out = os.path.join(out_dir, new_name)
    if os.path.exists(out):
        os.remove(out)
    os.replace(tmp, out)
    return out, replaced, total


def io_read_orig(s, e):
    import io
    buf = io.BytesIO()
    s.read_file(e, buf)
    return buf.getvalue()


def verify(path):
    """Re-read every hash level and the header hash; returns list of problems."""
    from stfs_extract import Stfs
    s = Stfs(path)
    bad = []
    with open(path, "rb") as f:
        h = f.read(BASE)
        if hashlib.sha1(h[0x344:BASE]).digest() != h[0x32C:0x340]:
            bad.append("header hash")
        total = s.total_blocks
        t0s = {}
        for g in range((total + L0 - 1) // L0):
            f.seek(BASE + (hash_block(g * L0, 0) << 12))
            t0s[g] = f.read(BLOCK)
            for j in range(L0):
                idx = g * L0 + j
                if idx >= total:
                    break
                f.seek(block_off(idx))
                if hashlib.sha1(f.read(BLOCK)).digest() != t0s[g][j * 24:j * 24 + 20]:
                    bad.append(f"block {idx}")
        top = t0s[0]
        if total > L0:
            t1s = {}
            for g1 in range((total + L1 - 1) // L1):
                f.seek(BASE + (hash_block(g1 * L1, 1) << 12))
                t1s[g1] = f.read(BLOCK)
                for j in range(L0):
                    g = g1 * L0 + j
                    if g in t0s and hashlib.sha1(t0s[g]).digest() != t1s[g1][j * 24:j * 24 + 20]:
                        bad.append(f"L0 table {g}")
            top = t1s[0]
            if total > L1:
                f.seek(BASE + (hash_block(0, 2) << 12))
                t2 = f.read(BLOCK)
                for g1, tb in t1s.items():
                    if hashlib.sha1(tb).digest() != t2[g1 * 24:g1 * 24 + 20]:
                        bad.append(f"L1 table {g1}")
                top = t2
        if hashlib.sha1(top).digest() != h[0x379 + 8:0x379 + 28]:
            bad.append("top hash")
    return bad


def main():
    orig, repl, out_dir = sys.argv[1:4]
    out, n, total = rebuild(orig, repl, out_dir)
    bad = verify(out)
    print(f"{os.path.basename(out)}: {n} files replaced, {total} blocks, hash check {'OK' if not bad else bad[:5]}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
