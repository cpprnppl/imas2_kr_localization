"""PS3 (RPCS3) Korean patch data: KDF1 diffs against the user's own PS3 files + our own files + manifest.

  python gen_patch_ps3.py gen    --pristine <USRDIR> --pristine-dlc <dlc dir> --deployed <USRDIR> \
                                 --table <table.bin, local dev copy> --exe-yml <imas2_kor_exe.yml> --out <dir>
                                 [--disc-hashes <disc USRDIR sha256 json from iso9660.py> --disc-offset 0x...
                                  --disc-yml <disc RPCS3 patch yml>]       # adds the disc edition BLJS10083
  python gen_patch_ps3.py verify --pristine <USRDIR> --pristine-dlc <dlc dir> --deployed <USRDIR> \
                                 --table <table.bin> --patch <dir> --work <empty dir>

Targets = every file of the pristine install whose *content* differs in the deployed install (files that are
only a plaintext copy of the encrypted original are skipped; files absent from the pristine install, e.g. backups,
tool outputs and the loose fonts, are never read).
Manifest format imas2kor-ps3-patch/1 (shape agreed with the imas2pc installer core, 2026-10-25). Per file the
generator picks the transforms that reproduce the deployed bytes exactly:
  src_transform  none | xcrypt_ps3:<n>  (game AES; 384-byte slice n of the 1,152-byte key table)
  out_transform  none | xcrypt_ps3      (re-encrypt with the source file's key/footer; out_prefix orig | zero)
The diff runs plaintext -> plaintext, so ADD carries only our new bytes. The table itself is never written to
the output: key_table names its length/sha256 and where it sits in the user's decrypted EBOOT.elf.
User decision 2026-10-25 ("B"): PS3 patch ships as diffs; PSN NPJB00337 now, disc BLJS10083 slot empty.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd  # noqa: E402

FOOTER = 64
MAGIC = (b"pac\x00", b"XMB ", b"TSK ", b"NTXR", b"NTP3", b"NUS3", b"\x1bLua", b"S2D ", b"MPK ",   # platform_audit.MAGIC
         b"\xff\xd8\xff")                                           # + JPEG (DLC ad_bg.jpg)
TABLE_OFF, TABLE_LEN = 0x575698, 1152                           # in the decrypted PSN EBOOT.elf
SKIP_DIRS = ("_backup", "gscript - 복사본", "/tools/", "fontwork/")


def sha256(b):
    return hashlib.sha256(b).hexdigest()


class Cipher:                                                    # as tools/image_text/dlc_inject.Cipher
    def __init__(self, table):
        self.t = table

    def key(self, d):
        fp = len(d) - 32
        n1, n2, n3 = d[fp + 1], d[fp + 2], d[fp + 3]
        o0, o1, i0, i1 = ((n1 >> 4) & 0xF) * 24, (n1 & 0xF) * 24, n2 % 24, n3 % 24
        k = bytearray(24)
        for i in range(24):
            k[i] = self.t[o0 + i0] ^ self.t[o1 + i1]
            i0, i1 = (i0 + 1) % 24, (i1 + 1) % 24
        return bytes(k)

    def decrypt(self, raw):
        from Crypto.Cipher import AES
        body = raw[:len(raw) - FOOTER]
        if len(body) % 16 or len(body) < 32:
            raise ValueError("not encrypted")
        full = AES.new(self.key(raw), AES.MODE_CBC, b"\x00" * 16).decrypt(body)
        return full[16:], full[:16]

    def encrypt(self, plain, src_raw, prefix):
        from Crypto.Cipher import AES
        buf = prefix + plain
        buf += b"\x00" * ((-len(buf)) % 16)
        return AES.new(self.key(src_raw), AES.MODE_CBC, b"\x00" * 16).encrypt(buf) + src_raw[len(src_raw) - FOOTER:]


def decrypt_any(raw, table):
    """[(slice, plain, prefix)] for every table slice that decrypts to a known signature."""
    out = []
    for s in (0, 384, 768):
        try:
            p, pre = Cipher(table[s:s + 384]).decrypt(raw)
        except Exception:  # noqa: BLE001
            continue
        if any(p.startswith(m) for m in MAGIC):
            out.append((s, p, pre))
    return out


def plan(orig, new, table):
    """Choose transforms that rebuild `new` from `orig`. Returns dict or None if content is unchanged."""
    od = decrypt_any(orig, table)
    nd = decrypt_any(new, table)
    o_plain = od[0][1] if od else orig
    n_plain = nd[0][1] if nd else new
    if o_plain == n_plain:
        return None                                              # plaintext copy of the same content
    cands = []
    src_opts = [("none", None, orig)] + [("xcrypt", s, p) for s, p, _ in od]
    for sname, sl, src in src_opts:
        if not nd:
            cands.append((sname, sl, src, "none", None, new))
        else:
            for s2, p2, pre2 in nd:
                if sname != "xcrypt" or s2 != sl:
                    continue
                c = Cipher(table[sl:sl + 384])
                for pname, pre in (("orig", od[0][2]), ("zero", b"\x00" * 16)):
                    if c.encrypt(p2, orig, pre) == new:
                        cands.append((sname, sl, src, "xcrypt", pname, p2))
    fallback = not cands
    if fallback:
        cands = [("none", None, orig, "none", None, new)]          # raw diff: reported, verify fails on it
    best = None
    for sname, sl, src, dname, pname, out in cands:
        d = kd.make(src, out)
        add, flagged = kd.audit(src, d)
        if best is None or add < best["add_bytes"]:
            best = {"src_transform": sname, "table_slice": sl, "dst_transform": dname, "dst_prefix": pname,
                    "_src": src, "_out": out, "_diff": d, "add_bytes": add, "add_flagged_runs": len(flagged),
                    "raw_fallback": fallback}
    return best


def rebuild(orig, e, kdbytes, table):
    """Reference applier for one manifest entry (imas2kor-ps3-patch/1)."""
    src, c = orig, None
    if e["src_transform"].startswith("xcrypt_ps3:"):
        s = int(e["src_transform"].split(":")[1]) * 384
        c = Cipher(table[s:s + 384])
        src, _ = c.decrypt(orig)
    out = kd.apply(src, kdbytes)
    if e.get("out_transform", "none") == "xcrypt_ps3":
        pre = c.decrypt(orig)[1] if e["out_prefix"] == "orig" else b"\x00" * 16
        out = c.encrypt(out, orig, pre)
    return out


def _yml_key_names(path, text):
    lines = text.splitlines()
    keys = [l[:-1] for l in lines if l.startswith("PPU-") and l.endswith(":")]
    names = [l.strip()[1:-2] for l in lines if l.startswith('  "') and l.endswith('":')]
    if len(keys) != 1 or not names:
        sys.exit(f"{path}: expected one PPU key and patch names")
    return keys[0], names


def yml_entry(path, edition, out, variant=None, extras=()):
    """Our RPCS3 patch file for one edition: copied to w/, hash key and patch names read from the yml.
    extras: more patch ymls for the same EBOOT (e.g. the dialogue box 136 cap); each must carry the same PPU key,
    and its patches are appended under that key as further patch names (kor_patch_rpcs3 enables every name)."""
    y = open(path, "rb").read()
    text = y.decode("utf-8")
    key, names = _yml_key_names(path, text)
    eol = "\r\n" if "\r\n" in text else "\n"
    merged = []
    for xp in extras:
        xb = open(xp, "rb").read()
        xt = xb.decode("utf-8")
        xkey, xnames = _yml_key_names(xp, xt)
        if xkey != key:
            sys.exit(f"{xp}: PPU key {xkey} is not the {edition} EBOOT key {key}")
        if set(xnames) & set(names):
            sys.exit(f"{xp}: patch name already present: {sorted(set(xnames) & set(names))}")
        lines = xt.splitlines()
        block = lines[lines.index(xkey + ":") + 1:]
        while block and not block[-1].strip():
            block.pop()
        text = text.rstrip("\r\n") + eol + eol.join(block) + eol
        names += xnames
        merged.append({"file": os.path.basename(xp), "sha256": sha256(xb), "patch_names": xnames})
    y = text.encode("utf-8")
    assert _yml_key_names(path, text) == (key, names)
    name = f"imas2_kor_exe_{edition}{'_' + variant if variant else ''}.yml"
    open(os.path.join(out, "w", name), "wb").write(y)
    e = {"edition": edition, **({"variant": variant} if variant else {}),
         "file": f"w/{name}", "sha256": sha256(y), "size": len(y), "schema": "Version: 1.2",
         "hash_key": key, "patch_names": names, "origin": "exe_inject build-ps3: new values only"}
    if merged:
        e["origin"] += "; + " + ", ".join(f"{m['file']} ({', '.join(m['patch_names'])})" for m in merged)
        e["merged"] = merged
    return e


def add_ymls(a, edition):
    out = []
    for v in a.add_yml:
        ed, _, path = v.partition("=")
        if ed not in ("psn", "disc", "disc_upd") or not path:
            sys.exit(f"--add-yml {v}: expected psn|disc|disc_upd=PATH")
        if ed == edition:
            out.append(path)
    return out


def files_of(root):
    out = {}
    for d, ds, fs in os.walk(root):
        for f in fs:
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
            out[rel] = os.path.join(d, f)
    return out


def gen(a):
    table = open(a.table, "rb").read()
    if len(table) != TABLE_LEN:
        sys.exit("table must be 1152 bytes")
    os.makedirs(a.out, exist_ok=False)
    os.makedirs(os.path.join(a.out, "d"))
    pr = files_of(a.pristine)
    marker = "resource/game/comueff/eff_com_rain.tsk"             # small, present in the PKG, never patched
    man = {"format": "imas2kor-ps3-patch/1", "target": "ps3_rpcs3",
           "image": [{"edition": "psn", "title_id": "NPJB00337", "pkg_content_id": "JP0700-NPJB00337_00-IMAS2HDDBOOT0000",
                      "usrdir_marker": marker, "marker_sha256": sha256(open(pr[marker], "rb").read())}],
           "key_table": {"source": "eboot_elf", "len": TABLE_LEN, "sha256": sha256(table),
                         "offset_hints": {"psn": f"0x{TABLE_OFF:X}"},
                         "table_source": "the user's own RPCS3-decrypted EBOOT.elf: 1152 B at the edition's offset hint "
                                         "or found by scan, accepted only on a sha256 match; never cached or shipped"},
           "dlc_roots": ["<NPJB00337 USRDIR>/dlc", "<dev_hdd0/game>/BLJS10083/USRDIR/dlc"],
           "files": [], "whole": [],
           "excluded": [{"target": "resource/im2_font*.nut|nfh (loose)",
                         "reason": "not in the PKG and not read by the game (ui 2026-10-25: no open in RPCS3.log; "
                                   "the fonts used are the ones injected into initialFix.mpc/initialTemp.mpc)"}]}
    pr_dlc = files_of(a.pristine_dlc)
    de = files_of(a.deployed)

    def add(rel, orig_path, new_path, extra):
        orig, new = open(orig_path, "rb").read(), open(new_path, "rb").read()
        if orig == new:
            return
        p = plan(orig, new, table)
        if p is None:
            return
        osha = sha256(new)
        open(os.path.join(a.out, "d", osha + ".kd"), "wb").write(p["_diff"])
        e = {"edition": "psn", "target": rel, "src_sha256": sha256(orig), "src_size": len(orig),
             "src_transform": "none" if p["src_transform"] == "none" else f"xcrypt_ps3:{p['table_slice'] // 384}",
             "diff": f"d/{osha}.kd", "out_sha256": osha, "out_size": len(new),
             "out_transform": "none" if p["dst_transform"] == "none" else "xcrypt_ps3"}
        if p["dst_transform"] != "none":
            e["out_prefix"] = p["dst_prefix"]
        e.update(add_bytes=p["add_bytes"], add_flagged_runs=p["add_flagged_runs"], raw_fallback=p["raw_fallback"])
        e.update(extra)
        assert rebuild(orig, e, p["_diff"], table) == new, rel
        man["files"].append(e)

    for rel in sorted(pr):
        if rel in de and not any(s in "/" + rel for s in SKIP_DIRS):
            add(rel, pr[rel], de[rel], {})
    for rel in sorted(pr_dlc):
        if "dlc/" + rel in de:
            add("dlc/" + rel, pr_dlc[rel], de["dlc/" + rel],
                {"src_origin": "THE iDOLM@STER 2 ALL DLC.pkg (BLJS10083 DLC; package provided by the dev team, "
                               "not a PSN retail download)"})
    os.makedirs(os.path.join(a.out, "w"))
    man["rpcs3_patch"] = [yml_entry(a.exe_yml, "psn", a.out, extras=add_ymls(a, "psn"))]
    if a.disc_hashes:                                             # disc edition BLJS10083 (same data as PSN)
        disc = {k.lower(): v for k, v in json.load(open(a.disc_hashes, encoding="utf-8")).items()}
        dm = disc[marker]["sha256"]
        if dm != man["image"][0]["marker_sha256"]:
            sys.exit("disc marker differs from PSN - the disc data is not the PSN data")
        man["image"].append({"edition": "disc", "title_id": "BLJS10083", "app_ver": "01.00", "usrdir_marker": marker,
                             "marker_sha256": dm, "label": "BLJS10083 (disc, VERSION 01.01 / APP_VER 01.00)"})
        man["key_table"]["offset_hints"]["disc"] = a.disc_offset
        both = 0
        for e in man["files"]:
            t = e["target"].lower()
            if t.startswith("dlc/") or disc.get(t, {}).get("sha256") == e["src_sha256"]:
                e["edition"] = "both"                             # DLC: one BLJS10083 package for both editions
                both += 1
        print(f"disc: {both}/{len(man['files'])} entries have the same source in the disc USRDIR")
        man["rpcs3_patch"].append(yml_entry(a.disc_yml, "disc", a.out, extras=add_ymls(a, "disc")))
        if a.update_yml:              # disc + HDD update 01.02: same game data, own EBOOT (dev_hdd0/game/BLJS10083)
            man["image"].append({"edition": "disc_upd", "title_id": "BLJS10083", "app_ver": "01.02",
                                 "usrdir_marker": marker, "marker_sha256": dm,
                                 "label": "BLJS10083 (disc + HDD update, APP_VER 01.02)"})
            man["key_table"]["offset_hints"]["disc_upd"] = a.update_offset
            man["rpcs3_patch"].append(yml_entry(a.update_yml, "disc_upd", a.out, extras=add_ymls(a, "disc_upd")))
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allf = man["files"]
    from collections import Counter
    print(f"files {len(allf)} (dlc {sum(1 for e in allf if e['target'].startswith('dlc/'))}) "
          f"rpcs3_patch {[(r['edition'], r['size']) for r in man['rpcs3_patch']]}")
    print("transforms:", Counter((e["src_transform"], e["out_transform"], e.get("out_prefix")) for e in allf))
    print(f"ADD bytes {sum(e['add_bytes'] for e in allf):,} / out {sum(e['out_size'] for e in allf):,}; "
          f"flagged runs {sum(e['add_flagged_runs'] for e in allf)}")


def verify(a):
    table = open(a.table, "rb").read()
    man = json.load(open(os.path.join(a.patch, "manifest.json"), encoding="utf-8"))
    if sha256(table) != man["key_table"]["sha256"]:
        sys.exit("table mismatch")
    work = a.work
    os.makedirs(work, exist_ok=False)
    shutil.copytree(a.pristine, os.path.join(work, "USRDIR"))
    shutil.copytree(a.pristine_dlc, os.path.join(work, "USRDIR", "dlc"))
    m = man["image"][0]
    if sha256(open(os.path.join(work, "USRDIR", *m["usrdir_marker"].split("/")), "rb").read()) != m["marker_sha256"]:
        sys.exit("edition marker mismatch")
    ok, bad = 0, []
    for e in man["files"]:
        p = os.path.join(work, "USRDIR", *e["target"].split("/"))
        orig = open(p, "rb").read()
        if sha256(orig) != e["src_sha256"]:
            bad.append((e["target"], "source hash"))
            continue
        out = rebuild(orig, e, open(os.path.join(a.patch, e["diff"]), "rb").read(), table)
        if sha256(out) != e["out_sha256"]:
            bad.append((e["target"], "result hash"))
            continue
        open(p, "wb").write(out)
        ok += 1
    mism = []
    for e in man["files"]:
        got = open(os.path.join(work, "USRDIR", *e["target"].split("/")), "rb").read()
        want = open(os.path.join(a.deployed, *e["target"].split("/")), "rb").read()
        if got != want:
            mism.append(e["target"])
    # no table / no long original runs in the output
    leak = []
    tbl = [table[i:i + 64] for i in range(0, TABLE_LEN, 64)]
    for d, ds, fs in os.walk(a.patch):
        for f in fs:
            b = open(os.path.join(d, f), "rb").read()
            if any(t in b for t in tbl):
                leak.append(f)
    flagged = sum(e["add_flagged_runs"] for e in man["files"])
    fb = [e["target"] for e in man["files"] if e.get("raw_fallback")]
    print(f"applied {ok}, failed {len(bad)}; compared with deployed: {len(man["files"])}, "
          f"mismatches {len(mism)}; table bytes found in {len(leak)} output files; flagged ADD runs {flagged}; "
          f"raw fallbacks {len(fb)} {fb[:5]}")
    for x in (bad + [(m, 'mismatch') for m in mism])[:20]:
        print("  ", x)
    sys.exit(1 if bad or mism or leak or flagged or fb else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("gen", "verify"))
    for o in ("--pristine", "--pristine-dlc", "--deployed", "--table", "--out", "--patch", "--work", "--exe-yml",
              "--disc-hashes", "--disc-offset", "--disc-yml", "--update-offset", "--update-yml"):
        ap.add_argument(o)
    ap.add_argument("--add-yml", action="append", default=[], metavar="EDITION=PATH",
                    help="extra RPCS3 patch yml merged under that edition's EBOOT key (psn/disc/disc_upd)")
    a = ap.parse_args()
    (gen if a.cmd == "gen" else verify)(a)


if __name__ == "__main__":
    main()
