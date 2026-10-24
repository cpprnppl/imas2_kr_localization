"""Reference applier for gen_patch.py output (the real installer is the supervisor's C++ core).

  python apply_patch.py --patch <dir> --game <extracted copy of the user's disc> --dlc <copy of user DLC>
                        --table <384-byte table>

Per entry: source sha256/size must match, the result must match out_sha256; otherwise the entry is
reported and nothing is written for it. Works on copies only.
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd
from gen_patch import xdecrypt, sha256


def main():
    ap = argparse.ArgumentParser()
    for a in ("--patch", "--game", "--dlc", "--table"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.patch, "manifest.json"), encoding="utf-8"))
    table = open(a.table, "rb").read()
    if hashlib.sha256(table).hexdigest() != man["cipher_table"]["sha256"]:
        sys.exit("cipher table sha256 mismatch")
    xex = open(os.path.join(a.game, man["image"].get("xex_path", "Default.xex")), "rb").read()
    if sha256(xex) != man["image"]["xex_sha256"]:
        sys.exit("Default.xex is not the expected disc")
    ok, bad = 0, []

    def do(path, e):
        nonlocal ok
        orig = open(path, "rb").read()
        if len(orig) != e["src_size"] or sha256(orig) != e["src_sha256"]:
            bad.append((e["target"], "source hash"))
            return
        src = xdecrypt(orig, table) if e["src_transform"] == "xcrypt" else orig
        out = kd.apply(src, open(os.path.join(a.patch, e["diff"]), "rb").read())
        if sha256(out) != e["out_sha256"]:
            bad.append((e["target"], "result hash"))
            return
        open(path, "wb").write(out)
        ok += 1

    for e in man["files"]:
        do(os.path.join(a.game, *e["target"].split("/")), e)
    for e in man["dlc"]:
        do(os.path.join(a.dlc, "4E4D0817", "00000002", e["pkg"], *e["target"].split("/")), e)
    for e in man["whole"]:
        b = open(os.path.join(a.patch, e["data"]), "rb").read()
        if sha256(b) != e["out_sha256"]:
            bad.append((e["target"], "whole hash"))
            continue
        open(os.path.join(a.game, e["target"]), "wb").write(b)
        ok += 1
    print(f"applied {ok}, failed {len(bad)}")
    for t, why in bad[:20]:
        print("  FAIL", t, why)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
