"""Write an XISO (XDVDFS game partition only, as extract-xiso/exiso `-c` makes; the iM@S1 360
patcher ships that form: github.com/rnrmfdlapdlf/xbox360-idolmaster-korean-patcher, MIT).
Written from the format, no code copied.

Layout: sectors 0-31 zero, 32 = volume descriptor, then directory tables, then file data.
Directory entries form a binary search tree ordered by upper-cased name (the console looks
names up by binary search); each entry stays inside one sector, padding is 0xFF.

  python xiso_write.py <file_list.tsv> <out.iso>
  file_list.tsv: "<iso path with />\t<source file>" per line (dirs are implied)
"""
import struct
import sys

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
ATTR_DIR, ATTR_FILE = 0x90, 0x80          # as on the original disc


def build_tree(files):
    """files: {path: source}. Returns nested dict: name -> dict (dir) or source (file)."""
    root = {}
    for path, src in files.items():
        parts = path.split("/")
        d = root
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = src
    return root


def dir_table(names, info):
    """names: entry names of one directory; info(name) -> (start_sector, size, attr).
    Returns the table bytes (multiple of SECTOR) as a balanced BST in pre-order."""
    order = sorted(names, key=lambda n: n.upper())
    nodes = []                                     # pre-order list of (name, left_idx, right_idx)

    def place(lo, hi):
        if lo > hi:
            return None
        mid = (lo + hi) // 2
        idx = len(nodes)
        nodes.append([order[mid], None, None])
        nodes[idx][1] = place(lo, mid - 1)
        nodes[idx][2] = place(mid + 1, hi)
        return idx

    place(0, len(order) - 1)
    offs, pos = [], 0
    for name, _, _ in nodes:                       # offsets, no entry crosses a sector
        size = (14 + len(name) + 3) & ~3
        if pos // SECTOR != (pos + size - 1) // SECTOR:
            pos = (pos // SECTOR + 1) * SECTOR
        offs.append(pos)
        pos += size
    table = bytearray(b"\xff" * (((pos + SECTOR - 1) // SECTOR) * SECTOR or SECTOR))
    for i, (name, l, r) in enumerate(nodes):
        start, size, attr = info(name)
        lo = offs[l] // 4 if l is not None else 0
        ro = offs[r] // 4 if r is not None else 0
        nb = name.encode("ascii")
        struct.pack_into("<HHIIBB", table, offs[i], lo, ro, start, size, attr, len(nb))
        table[offs[i] + 14:offs[i] + 14 + len(nb)] = nb
    return bytes(table)


def write_xiso(files, out_path, filetime=0):
    import os
    tree = build_tree(files)
    # pass 1: sizes of directory tables (depend only on names), assign sectors
    dirs = []                                      # (node, path) in BFS order

    def collect(node, path):
        dirs.append((node, path))
        for name in sorted(node, key=str.upper):
            if isinstance(node[name], dict) and node[name]:
                collect(node[name], path + name + "/")
    collect(tree, "")
    dummy = lambda name: (0, 0, 0)
    next_sec = 33
    dir_sec = {}
    for node, path in dirs:
        n = len(dir_table(list(node), dummy)) // SECTOR
        dir_sec[path] = (next_sec, n * SECTOR)
        next_sec += n
    file_sec = {}
    for path, src in sorted(files.items()):
        size = os.path.getsize(src)
        file_sec[path] = (next_sec, size)
        next_sec += (size + SECTOR - 1) // SECTOR
    # pass 2: write
    with open(out_path, "xb") as o:
        o.write(b"\0" * (32 * SECTOR))
        rs, rz = dir_sec[""]
        vd = bytearray(SECTOR)
        vd[0:20] = MAGIC
        struct.pack_into("<IIQ", vd, 20, rs, rz, filetime)
        vd[0x7EC:0x800] = MAGIC
        o.write(vd)
        for node, path in dirs:
            def info(name, node=node, path=path):
                child = node[name]
                if isinstance(child, dict):
                    s, z = dir_sec.get(path + name + "/", (0, 0))
                    return s, z, ATTR_DIR
                s, z = file_sec[path + name]
                return s, z, ATTR_FILE
            t = dir_table(list(node), info)
            assert o.tell() == dir_sec[path][0] * SECTOR
            o.write(t)
        for path, src in sorted(files.items()):
            assert o.tell() == file_sec[path][0] * SECTOR, path
            with open(src, "rb") as f:
                while True:
                    b = f.read(1 << 24)
                    if not b:
                        break
                    o.write(b)
            pad = (-o.tell()) % SECTOR
            o.write(b"\0" * pad)
    return next_sec


def main():
    lst, out = sys.argv[1], sys.argv[2]
    files = {}
    for line in open(lst, encoding="utf-8"):
        p, s = line.rstrip("\n").split("\t")
        files[p] = s
    n = write_xiso(files, out)
    print(f"{out}: {len(files)} files, {n} sectors ({n * SECTOR:,} bytes)")


if __name__ == "__main__":
    main()
