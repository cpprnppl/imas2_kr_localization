"""Minimal read-only ISO 9660 reader (PS3 disc images: PS3_GAME/USRDIR/...). No code copied; written from
ECMA-119. Multi-extent files (same name repeated with the 0x80 flag) are joined.

  python iso9660.py list <iso>
  python iso9660.py sha256 <iso> <out.json> [prefix]   # sha256/size of every file under prefix
"""
import hashlib
import json
import struct
import sys

SECTOR = 2048


def records(f, lba, size):
    f.seek(lba * SECTOR)
    data = f.read(size)
    i = 0
    while i < len(data):
        ln = data[i]
        if ln == 0:                                     # pad to next sector
            i = (i // SECTOR + 1) * SECTOR
            continue
        r = data[i:i + ln]
        ext, sz = struct.unpack_from("<I", r, 2)[0], struct.unpack_from("<I", r, 10)[0]
        flags, nlen = r[25], r[32]
        name = r[33:33 + nlen]
        yield ext, sz, flags, name
        i += ln


def walk(f):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[1:6] != b"CD001":
        raise ValueError("no ISO 9660 primary volume descriptor")
    root = pvd[156:190]
    stack = [(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")]
    while stack:
        lba, size, prefix = stack.pop()
        files = {}
        for ext, sz, flags, name in records(f, lba, size):
            if name in (b"\x00", b"\x01"):
                continue
            n = name.decode("ascii", "replace").split(";")[0]
            if flags & 2:
                stack.append((ext, sz, prefix + n + "/"))
            else:
                files.setdefault(n, []).append((ext, sz))      # multi-extent: keep order
        for n, parts in files.items():
            yield prefix + n, parts


def read_parts(f, parts):
    for ext, sz in parts:
        f.seek(ext * SECTOR)
        left = sz
        while left:
            b = f.read(min(left, 1 << 22))
            yield b
            left -= len(b)


def main():
    cmd, iso = sys.argv[1], sys.argv[2]
    with open(iso, "rb") as f:
        if cmd == "list":
            n = tot = 0
            for p, parts in sorted(walk(f)):
                sz = sum(s for _, s in parts)
                n += 1
                tot += sz
                print(f"{sz:>12} {p}")
            print(f"# {n} files, {tot:,} bytes")
        elif cmd == "sha256":
            out, prefix = {}, sys.argv[4] if len(sys.argv) > 4 else ""
            for p, parts in sorted(walk(f)):
                if not p.startswith(prefix):
                    continue
                h = hashlib.sha256()
                for b in read_parts(f, parts):
                    h.update(b)
                out[p[len(prefix):]] = {"sha256": h.hexdigest(), "size": sum(s for _, s in parts)}
            json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
            print(f"{len(out)} files hashed -> {sys.argv[3]}")


if __name__ == "__main__":
    main()
