# Xbox 360 XCompress "LZX TD" file (magic 0x0FF512ED), as used by iM@S2 bg2d_*.s2d

This is the XCTD ("transparent decompression") format. XAPI's file open
(sub_823C78B8 -> sub_823C7850, NtQueryInformationFile class 27) wraps it in a
decompressing reader. The seekable reader is sub_823BDB30 / sub_823BDF58 / sub_823BE218
in recomp_out/ppc_recomp.42.cpp.

Tags: **[code]** read from the recompiled reader. **[data]** holds for all 323 bg2d
files (decode check below). **[guess]** not verified.

## Header (big-endian)

| off | size | field |
|-----|------|-------|
| 0x00 | u32 | magic 0x0FF512ED **[code]** (compared in sub_823BDF58 / sub_823C78B8) |
| 0x04 | u32 | 0x01000000 in every file. Probably u16 version 1 + u16 reserved **[guess]** |
| 0x08 | u32 | varies per file. It is not CRC32 or Adler32 of the output, the body or the header remainder. Probably a hash or checksum. Not needed to decode **[guess]** |
| 0x0C | u32 | W, bit fields, see below |
| 0x10 | ... | page-size table: n entries, bit-packed MSB-first in big-endian 32-bit words, padded to a 4-byte boundary **[code]** for the bit reader, **[data]** for the padding |

W bit fields (bit 0 = LSB):

- bits 0..3: LZX window = `1 << (15 + v)`. In sub_823BE218: `clrlwi r11,W,28; addi 15; slw`. All files have v=2, so the window is 128 KiB (window_bits 17). **[code]**
- bits 4..5: page size = `0x8000 << v`. In sub_823BDB30/BDF58/BE218: `rlwinm r,W,28,30,31; slw 0x8000`. All files have v=2, so pages are 128 KiB. **[code]**
- bits 6..21: page count n. In sub_823BDB30: `rlwinm. r6,W,26,16,31`, which is the loop bound of the table walk. n=0 takes a separate path with no table, which is not handled here. **[code]**
- bits 22..23: width index for the table entries, `width = table[idx]`. The table at 0x820226CC in default.exe `.rdata` is {20, 32, ...}. All files have idx=0, so entries are 20 bits wide. **[code]** Only 20-bit entries are seen in the data.
- bits 24..31: unknown. The value is 0 when n=1 and 0x40..0x80 otherwise. It does not match the last page's compressed or uncompressed size. The reader functions above do not use it. **[guess]**

Each table entry is the **uncompressed size of one page**. The seek routine subtracts the
entries from the target offset to find the page index. **[code]** The sum of the entries
is the output size (461,440 for single-texture packs). **[data]**

Header length = `16 + ceil(n*width/32)*4`, giving 20 / 24 / 24 / 28 bytes for n = 1 / 2 / 3 / 4. **[data]**

## Pages and frames

- The compressed data is split into pages at absolute file offsets `k * pagesize`. Page 0 starts right after the header. The last page ends at EOF. Page count = ceil(filesize / pagesize). **[data]**, plus **[code]** for the page-index math (`offset / pagesize`).
- Each page is an **independent LZX stream**: the decoder is fresh and the window is reset. Its first frame starts with the 1-bit E8 header. **[data]** All 323 files decode with a fresh lzxd per page, with no "match beyond stream" errors and exact input use.
- Inside a page, each 32 KiB output frame is stored as `[u16 BE compressed size][frame bits]`. The bits are standard LZX (libmspack lzxd), 16-bit LE words, realigned at each frame end. A size of **0** ends the page early. This padding is seen in bg2d_0139 and bg2d_1089, among others, where the page ends 2 bytes short of the boundary. Running out of page also ends it. **[data]**
- The last frame of every page is short (page size mod 32 KiB). It has no 0xFF marker, unlike the 0x0FF512EE "native" format. The frame length comes from the table entry. **[data]**
- Frames per page = ceil(entry / 32768), checked for every page of every file. **[data]**

Differences from 0x0FF512EE (native, see imas2pc/tools/ps3feat/xmem_store.py): this format has no
64-bit sizes and no u32 block sizes, it uses 128 KiB *compressed* pages that each restart LZX, and it
needs a page-size table for seeking.

## Why the earlier probe gave "294,912 bytes"

The earlier probe (lzxd from offset 26) decoded only frame 0 correctly. Offsets 24..25 are frame 0's size
field (0x5396). At frame 1 the decoder read the next size field (0x4B68) as LZX bits. That gave a bogus
UNCOMPRESSED block of length 0x425A00, so output frames 1..8 were raw compressed bytes.

## Validation (xcomp_ed_unpack.exe + validate.py)

- 323/323 bg2d `*.s2d` files decode with no warnings. For every page, the input used equals the bytes stored.
- Every output is a TSK. The section table (XMB + NTXR) is in bounds and ordered, with zero gaps. The NTXR size field equals the section size minus 0x10. The 32- or 48-byte zero tail ends exactly at the output size.
- bg2d_0003 compared with the decrypted PS3 bg2d_0003 (scratchpad/dectest): the total size (461,440), the TSK header and table, the whole XMB section and the tail are byte-identical. The texture section differs as expected: NTXR (360) vs NTP3 (PS3).
- No other file under resource/ has this magic.

## 레포 사용(2026-10-29, ui)

- 빌드(로컬, exe는 커밋하지 않음 — libmspack lzxd.c는 LGPL, XenonRecomp thirdparty에 있음):
  `clang-cl /O2 /D_CRT_SECURE_NO_WARNINGS xcomp_ed_unpack.c <XenonRecomp>\thirdparty\libmspack\libmspack\mspack\lzxd.c /I <같은 mspack 폴더> /Fe:xcomp_ed_unpack.exe`
  (Git Bash에선 `MSYS_NO_PATHCONV=1`)
- pcport_apply.decrypt_port가 머리 0x0FF512ED인 360 순정 파일을 이 exe로 풀어 _cache/pcport_x360에 평문(TSK)으로 둔다.
  결과 s2d는 평문으로 배포한다(360 XAPI는 이 머리가 아닌 파일을 그대로 읽음 — imas2pc stubs.cpp class 27).
