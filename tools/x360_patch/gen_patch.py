"""PC-port Korean patch data: diffs against the user's own 360 files + our own whole files + manifest.

  python gen_patch.py --iso <original.iso> --game <game_kor> --dlc <content> --dlc-kor <content_kor>
                      --table <table360.bin, local dev copy> --out <dir>

Rules (supervisor/KOR 2026-10-24):
- Anything derived from a 360 file ships as a KDF1 diff against the user's file; the source is the raw
  original ("none") or the decrypted original ("xcrypt": game AES, 384-byte table + footer), whichever
  needs fewer ADD bytes. The table is only used here; the manifest carries its rva/len/sha256, never bytes.
- Whole files only for 100% our own data (WHOLE below).
- PC-only backups (.bak*, .orig_kor, _backup*, _kor_backup) are never read.
Output: <out>/manifest.json, <out>/d/<out_sha256>.kd, <out>/w/<name>.
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd
import xdvdfs

FOOTER_360 = 32
TABLE_RVA, TABLE_LEN = 0xB5430, 384           # found once in the dev basefile (unpack\imas2\default.exe)
WHOLE = {                                     # our own files at disc root: name -> origin
    "retry_text.bin": "exe_inject port-texts, webapp row gamedata:system:initialFix#x3:retry_001_pc",
    "difficulty_text.bin": "exe_inject port-texts, webapp row gamedata:system:initialFix#x14:war_144_pc",
    "kor_exe_strings.bin": "exe_inject build360, KXS2 (addr/len/sha256 prefix/new only, no original bytes)",
}
EXCLUDED = {}                                 # held until their rulings land


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def xdecrypt(raw, table):
    """Game AES-192-CBC (as tools/image_text/dlc_inject.Cipher): key = table + 3 footer bytes."""
    sys.path.insert(0, os.path.join(HERE, "..", "image_text"))
    from dlc_inject import Cipher
    plain, _ = Cipher(table, FOOTER_360).decrypt(raw)
    return plain


def diff_entry(target, orig, new, table, out, extra=None):
    cands = [("none", orig)]
    try:
        cands.append(("xcrypt", xdecrypt(orig, table)))
    except Exception:  # noqa: BLE001  (not an encrypted file)
        pass
    best = None
    for name, src in cands:
        d = kd.make(src, new)
        add, flagged = kd.audit(src, d)
        if best is None or add < best[2]:
            best = (name, d, add, flagged, src)
    name, d, add, flagged, src = best
    assert kd.apply(src, d) == new
    osha = sha256(new)
    os.makedirs(os.path.join(out, "d"), exist_ok=True)
    with open(os.path.join(out, "d", osha + ".kd"), "wb") as f:
        f.write(d)
    e = {"target": target, "kind": "diff", "src_sha256": sha256(orig), "src_size": len(orig),
         "src_transform": name, "diff": f"d/{osha}.kd", "out_sha256": osha, "out_size": len(new),
         "add_bytes": add, "add_flagged_runs": len(flagged)}
    if name == "xcrypt":
        e["table_source"] = "TBD"
    if extra:
        e.update(extra)
    return e


def main():
    ap = argparse.ArgumentParser()
    for a in ("--iso", "--game", "--dlc", "--dlc-kor", "--table", "--out"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    table = open(a.table, "rb").read()
    if len(table) != TABLE_LEN:
        sys.exit("table must be 384 bytes")
    os.makedirs(a.out, exist_ok=False)
    man = {"format": "imas2kor-patch/1",
           "image": {"title_id": "4E4D0817"},
           "cipher_table": {"rva": f"0x{TABLE_RVA:X}", "len": TABLE_LEN, "sha256": sha256(table),
                            "table_source": "TBD"},
           "files": [], "whole": [], "dlc": [],
           "excluded": [{"target": k, "reason": v} for k, v in EXCLUDED.items()]}
    with open(a.iso, "rb") as f:
        base = xdvdfs.find_partition(f)
        ents = sorted((p, s, z) for p, s, z, d in xdvdfs.walk(f, base) if not d)
        for p, s, z in ents:
            orig = xdvdfs.read_file(f, base, s, z)
            if p.lower() == "default.xex":
                man["image"]["xex_sha256"] = sha256(orig)
                man["image"]["xex_size"] = len(orig)
            new = open(os.path.join(a.game, *p.split("/")), "rb").read()
            if new != orig:
                man["files"].append(diff_entry(p, orig, new, table, a.out))
    os.makedirs(os.path.join(a.out, "w"), exist_ok=True)
    for name, origin in WHOLE.items():
        b = open(os.path.join(a.game, name), "rb").read()
        open(os.path.join(a.out, "w", name), "wb").write(b)
        man["whole"].append({"target": name, "kind": "whole", "data": f"w/{name}", "out_sha256": sha256(b),
                             "out_size": len(b), "origin": origin})
    sub = os.path.join("4E4D0817", "00000002")
    # explicit list = the files of the user's original packages (extra files in content_kor are never read)
    for pkg in sorted(os.listdir(os.path.join(a.dlc, sub))):
        root_o = os.path.join(a.dlc, sub, pkg)
        if not os.path.isdir(root_o):
            continue
        for d, ds, fs in os.walk(root_o):
            for fn in fs:
                rel = os.path.relpath(os.path.join(d, fn), root_o).replace(os.sep, "/")
                orig = open(os.path.join(d, fn), "rb").read()
                new = open(os.path.join(a.dlc_kor, sub, pkg, *rel.split("/")), "rb").read()
                if new == orig:
                    continue
                if rel.endswith("ad_bg.ptc") and new[:8] == b"IM2PCRAW":
                    man["excluded"].append({"target": f"dlc:{pkg}/{rel}", "reason":
                                            "IM2PCRAW banner = raw pixels incl. original art; needs supervisor ruling"})
                    continue
                man["dlc"].append(diff_entry(rel, orig, new, table, a.out, {"pkg": pkg}))
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allf = man["files"] + man["dlc"]
    print(f"files {len(man['files'])} dlc {len(man['dlc'])} whole {len(man['whole'])} excluded {len(man['excluded'])}")
    print(f"ADD bytes {sum(e['add_bytes'] for e in allf):,} / out {sum(e['out_size'] for e in allf):,}; "
          f"flagged runs {sum(e['add_flagged_runs'] for e in allf)}")
    big = sorted((e["add_bytes"] / max(1, e["out_size"]), e["target"]) for e in allf)[-8:]
    print("highest ADD ratio:", [(round(r, 2), t) for r, t in big])


if __name__ == "__main__":
    main()
