"""Korean exe strings applied statically to default.xex for RGH/JTAG hardware (user-approved 2026-10-25).

  python xex_patch.py <original default.xex> <basefile from xex2base> <kor_exe_strings.bin (KXS2)> <out.xex>

- KXS2 records (addr, len, sha256[:8], new) are checked against the basefile first; any mismatch -> nothing
  written (same rule as imas2pc kor_exe_strings.cpp).
- Output xex = original header with FILE_FORMAT_INFO set to encryption 0 / compression 1 (basic, one block
  covering the whole image) + the patched image. Same form as iM@S1's xextool `-e d -c u` step
  (github.com/rnrmfdlapdlf/xbox360-idolmaster-korean-patcher, MIT); hashes/signature are not updated, so it
  runs only on consoles that skip xex signature checks (RGH/JTAG).
"""
import hashlib
import struct
import sys

BASE = 0x82000000


def be32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def opt_header(x, key):
    for i in range(be32(x, 20)):
        h = 24 + i * 8
        if be32(x, h) == key:
            return be32(x, h + 4)
    return None


def apply_kxs2(base, kxs):
    if kxs[:4] != b"KXS2":
        raise ValueError("not a KXS2 file")
    n, p, recs = be32(kxs, 4), 8, []
    for _ in range(n):
        a, ln = struct.unpack_from(">II", kxs, p)
        recs.append((a - BASE, ln, kxs[p + 8:p + 16], kxs[p + 16:p + 16 + ln]))
        p += 16 + ln
    if p != len(kxs):
        raise ValueError("malformed KXS2")
    for i, (o, ln, h, _new) in enumerate(recs):
        if o < 0 or o + ln > len(base) or hashlib.sha256(base[o:o + ln]).digest()[:8] != h:
            raise ValueError(f"record {i + 1}/{n} does not match the image - nothing applied")
    out = bytearray(base)
    for o, ln, _h, new in recs:
        out[o:o + ln] = new
    return bytes(out), n


def write_xex(orig, image):
    hdr = bytearray(orig[:be32(orig, 8)])
    ffi = opt_header(orig, 0x000003FF)
    if ffi is None or be32(orig, ffi) < 16:
        raise ValueError("no room for FILE_FORMAT_INFO")
    struct.pack_into(">IHHII", hdr, ffi, 16, 0, 1, len(image), 0)   # size, enc none, comp basic, 1 block
    return bytes(hdr) + image


def main():
    xex, basef, kxsf, out = sys.argv[1:5]
    orig = open(xex, "rb").read()
    base = open(basef, "rb").read()
    image, n = apply_kxs2(base, open(kxsf, "rb").read())
    new = write_xex(orig, image)
    with open(out, "xb") as f:
        f.write(new)
    print(f"{out}: {n} records applied, image {len(image):,} B, xex {len(new):,} B, "
          f"image sha256 {hashlib.sha256(image).hexdigest()}")


if __name__ == "__main__":
    main()
