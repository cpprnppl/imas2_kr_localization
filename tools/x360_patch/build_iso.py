"""Korean XISO for the 360: original ISO file list, contents from game_kor (Korean data + fonts),
Default.xex unchanged. Original ISO is only read; its sha1 is recorded before and after.

  python build_iso.py <original.iso> <game_kor dir> <out.iso>
Writes <out.iso>, <out.iso>.manifest.json (per-file sha1 + source, ISO hashes) and keeps the
snapshot it was built from in <out.iso>.stage/.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xdvdfs
import xiso_write


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 24)
            if not b:
                return h.hexdigest()
            h.update(b)


def main():
    iso, game, out = sys.argv[1:4]
    if os.path.exists(out):
        sys.exit(f"{out} exists")
    iso_sha_before = sha1_file(iso)
    with open(iso, "rb") as f:
        base = xdvdfs.find_partition(f)
        f.seek(base + 32 * 2048 + 28)
        filetime = int.from_bytes(f.read(8), "little")
        paths = [p for p, s, z, d in xdvdfs.walk(f, base) if not d]
    # snapshot: other sessions deploy into game_kor while we run, so copy the file set first
    import shutil
    stage = out + ".stage"
    files = {}
    for p in paths:
        src = os.path.join(game, *p.split("/"))
        if not os.path.isfile(src):
            sys.exit(f"missing in {game}: {p}")
        dst = os.path.join(stage, *p.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        files[p] = dst
    n = xiso_write.write_xiso(files, out, filetime)
    # verify: read every file back from the new ISO and compare with its source
    man = {"original_iso": iso, "original_sha1_before": iso_sha_before, "files": {}}
    bad = []
    with open(out, "rb") as f:
        got = {p: (s, z) for p, s, z, d in xdvdfs.walk(f, 0) if not d}
        for p, src in sorted(files.items()):
            want = sha1_file(src)
            have = hashlib.sha1(xdvdfs.read_file(f, 0, *got[p])).hexdigest() if p in got else None
            man["files"][p] = {"sha1": want, "source": os.path.join(game, *p.split("/"))}
            if have != want:
                bad.append(p)
    man["extra_in_iso"] = sorted(set(got) - set(files))
    man["mismatch"] = bad
    man["out_sha1"] = sha1_file(out)
    man["original_sha1_after"] = sha1_file(iso)
    json.dump(man, open(out + ".manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{out}: {len(files)} files, {n} sectors; read-back mismatch {len(bad)}, extra {len(man['extra_in_iso'])}")
    print(f"original sha1 before {iso_sha_before} after {man['original_sha1_after']} "
          f"({'unchanged' if iso_sha_before == man['original_sha1_after'] else 'CHANGED'})")
    print(f"out sha1 {man['out_sha1']}")
    sys.exit(1 if bad or man["extra_in_iso"] or iso_sha_before != man["original_sha1_after"] else 0)


if __name__ == "__main__":
    main()
