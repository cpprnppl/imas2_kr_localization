"""End-to-end check of the PC patch data on copies.

  python verify_patch.py --iso <original.iso> --game <game_kor> --dlc <content> --dlc-kor <content_kor>
                         --table <table> --work <empty dir>

1. sha256 of the original ISO; 2. gen_patch into <work>/patch; 3. extract the ISO to <work>/game and copy
the original DLC to <work>/dlc; 4. apply_patch on those copies; 5. compare every ISO file (+ whole files)
with game_kor and every DLC file with content_kor (excluded entries listed separately); 6. ISO sha256 again.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd  # noqa: E402
from gen_patch import WHOLE_SRC, xdecompress  # noqa: E402


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def run(args):
    print("$", " ".join(args[:3]), "...", flush=True)
    r = subprocess.run([sys.executable, "-I"] + args)
    if r.returncode:
        sys.exit(f"step failed: {args[0]} (exit {r.returncode})")


def main():
    ap = argparse.ArgumentParser()
    for a in ("--iso", "--game", "--dlc", "--dlc-kor", "--table", "--work"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=False)
    before = sha_file(a.iso)
    patch, game, dlc = (os.path.join(a.work, n) for n in ("patch", "game", "dlc"))
    run([os.path.join(HERE, "gen_patch.py"), "--iso", a.iso, "--game", a.game, "--dlc", a.dlc,
         "--dlc-kor", a.dlc_kor, "--table", a.table, "--out", patch])
    run([os.path.join(HERE, "xdvdfs.py"), "extract", a.iso, game])
    shutil.copytree(a.dlc, dlc)
    man = json.load(open(os.path.join(patch, "manifest.json"), encoding="utf-8"))
    # original-bytes-0: no ADD run of 64+ bytes may share a 32-byte block with the source. gen_patch audits every
    # diff against its transformed source; xcompress entries are re-audited here against both the decompressed
    # and the compressed original (decompressed independently from the extracted disc copy).
    flagged = sum(e["add_flagged_runs"] for e in man["files"] + man["dlc"])
    nx, xbad = 0, []
    for e in man["files"]:
        if e["src_transform"] != "xcompress":
            continue
        nx += 1
        raw = open(os.path.join(game, *e["target"].split("/")), "rb").read()
        plain = xdecompress(raw)
        if hashlib.sha256(plain).hexdigest() != e["src_plain_sha256"] or len(plain) != e["src_plain_size"]:
            xbad.append((e["target"], "decompression mismatch"))
            continue
        d = open(os.path.join(patch, e["diff"]), "rb").read()
        for name, src in (("plain", plain), ("compressed", raw)):
            if kd.audit(src, d)[1]:
                xbad.append((e["target"], f"ADD run shares bytes with the {name} original"))
    print(f"original-bytes check: flagged ADD runs in manifest {flagged}; xcompress entries re-audited {nx}, "
          f"failures {len(xbad)}")
    for t, why in xbad:
        print("  ORIGINAL BYTES", t, why)
    run([os.path.join(HERE, "apply_patch.py"), "--patch", patch, "--game", game, "--dlc", dlc, "--table", a.table])
    excluded = {e["target"] for e in man["excluded"]}
    mism, n = [], 0
    for d, ds, fs in os.walk(game):
        for fn in fs:
            rel = os.path.relpath(os.path.join(d, fn), game).replace(os.sep, "/")
            if rel in excluded:                    # held (e.g. XCompress originals): stays original, not compared
                continue
            n += 1
            ref = WHOLE_SRC.get(rel, os.path.join(a.game, *rel.split("/")))
            if sha_file(os.path.join(d, fn)) != sha_file(ref):
                mism.append(rel)
    nd = 0
    sub = os.path.join("4E4D0817", "00000002")
    for d, ds, fs in os.walk(os.path.join(dlc, sub)):
        for fn in fs:
            rel = os.path.relpath(os.path.join(d, fn), os.path.join(dlc, sub)).replace(os.sep, "/")
            nd += 1
            pkg, _, inner = rel.partition("/")
            if f"dlc:{pkg}/{inner}" in excluded:
                continue
            if sha_file(os.path.join(d, fn)) != sha_file(os.path.join(a.dlc_kor, sub, *rel.split("/"))):
                mism.append("dlc:" + rel)
    after = sha_file(a.iso)
    print(f"game files compared {n}, dlc files compared {nd}, mismatches {len(mism)}, excluded {len(excluded)}")
    for m in mism[:20]:
        print("  MISMATCH", m)
    print(f"original ISO sha256 before {before} after {after} ({'unchanged' if before == after else 'CHANGED'})")
    sys.exit(1 if mism or flagged or xbad or before != after else 0)


if __name__ == "__main__":
    main()
