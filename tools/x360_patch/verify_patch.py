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
from gen_patch import WHOLE_SRC  # noqa: E402


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
    run([os.path.join(HERE, "apply_patch.py"), "--patch", patch, "--game", game, "--dlc", dlc, "--table", a.table])
    man = json.load(open(os.path.join(patch, "manifest.json"), encoding="utf-8"))
    excluded = {e["target"] for e in man["excluded"]}
    mism, n = [], 0
    for d, ds, fs in os.walk(game):
        for fn in fs:
            rel = os.path.relpath(os.path.join(d, fn), game).replace(os.sep, "/")
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
    sys.exit(1 if mism or before != after else 0)


if __name__ == "__main__":
    main()
