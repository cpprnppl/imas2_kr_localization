"""XDVDFS (Xbox 360 game partition) reader.

Layout follows the public XDVDFS description (also used by extract-xiso / exiso,
which the iM@S1 360 patcher bundles: github.com/rnrmfdlapdlf/xbox360-idolmaster-korean-patcher).
No code copied; written from the format.

  python xdvdfs.py list <iso>            # files with size
  python xdvdfs.py extract <iso> <dir>   # extract everything (dir must not exist)
"""
import os
import struct
import sys

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
# game partition offsets: plain XISO, XGD3, XGD2, XGD1
PARTITIONS = (0, 0x2080000, 0xFD90000, 0x18300000)


def find_partition(f):
    for base in PARTITIONS:
        f.seek(base + 32 * SECTOR)
        if f.read(20) == MAGIC:
            return base
    raise ValueError("XDVDFS volume descriptor not found")


def walk(f, base=None):
    """Yield (path, start_sector, size, is_dir) for every entry; path uses '/'."""
    if base is None:
        base = find_partition(f)
    f.seek(base + 32 * SECTOR + 20)
    root_sector, root_size = struct.unpack("<II", f.read(8))

    def read_dir(sector, size, prefix):
        if size == 0:
            return
        f.seek(base + sector * SECTOR)
        table = f.read(size)
        seen = set()
        stack = [0]
        while stack:
            off = stack.pop()
            if off in seen or off + 14 > len(table):
                continue
            seen.add(off)
            left, right, start, length, attr, nlen = struct.unpack_from("<HHIIBB", table, off)
            if left == 0xFFFF and right == 0xFFFF and start == 0xFFFFFFFF:
                continue                                   # padding
            name = table[off + 14:off + 14 + nlen].decode("ascii")
            path = prefix + name
            is_dir = bool(attr & 0x10)
            yield path, start, length, is_dir
            if is_dir:
                yield from read_dir(start, length, path + "/")
            if left not in (0, 0xFFFF):
                stack.append(left * 4)
            if right not in (0, 0xFFFF):
                stack.append(right * 4)

    yield from read_dir(root_sector, root_size, "")


def read_file(f, base, start, size):
    f.seek(base + start * SECTOR)
    return f.read(size)


def main():
    cmd, iso = sys.argv[1], sys.argv[2]
    with open(iso, "rb") as f:
        base = find_partition(f)
        if cmd == "list":
            n = tot = 0
            for path, start, size, is_dir in walk(f, base):
                if not is_dir:
                    print(f"{size:>12} {path}")
                    n += 1
                    tot += size
            print(f"# partition 0x{base:X}: {n} files, {tot:,} bytes")
        elif cmd == "extract":
            out = sys.argv[3]
            os.makedirs(out)
            for path, start, size, is_dir in sorted(walk(f, base)):
                dst = os.path.join(out, *path.split("/"))
                if is_dir:
                    os.makedirs(dst, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                f.seek(base + start * SECTOR)
                with open(dst, "wb") as o:
                    left = size
                    while left:
                        chunk = f.read(min(left, 1 << 24))
                        o.write(chunk)
                        left -= len(chunk)
        else:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
