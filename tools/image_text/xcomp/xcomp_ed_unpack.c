/* xcomp_ed_unpack: decompress an Xbox 360 XCompress "LZX TD" file
 * (magic 0x0FF512ED, the XCTD format XAPI decompresses transparently;
 * iM@S2 bg2d_*.s2d). See FORMAT.md next to this file.
 *
 *   xcomp_ed_unpack in.s2d out.bin [-v]
 *
 * Layout (all big-endian):
 *   +0x00 u32 0x0FF512ED   +0x04 u32 0x01000000 (version)   +0x08 u32 hash/checksum (?)
 *   +0x0C u32 W: bits 0..3  window = 1 << (15 + v)        (iM@S2 files: 2 -> 128 KiB)
 *                bits 4..5  page size = 0x8000 << v       (2 -> 128 KiB)
 *                bits 6..21 page count n
 *                bits 22..23 size-entry width index: 0 -> 20 bits, 1 -> 32 bits
 *                bits 24..31 unknown (not needed to decode)
 *   +0x10 n uncompressed page sizes, MSB-first bit-packed, padded to 4 bytes
 *   then the compressed data, cut into pages at absolute file offsets
 *   k*pagesize (page 0 starts right after the header). Each page is an independent
 *   LZX stream (fresh state) whose 32 KiB output frames are stored as
 *   [u16 frame compressed size][frame bits]; a size of 0, or fewer than 2 bytes left
 *   in the page, ends the page. The last frame of a page is short (page size % 32 KiB).
 *
 * Build (clang-cl):
 *   clang-cl /O2 xcomp_ed_unpack.c <libmspack>/lzxd.c /I <libmspack> /Fe:xcomp_ed_unpack.exe
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mspack.h"
#include "lzx.h"

#define MAGIC 0x0FF512EDu

typedef struct { struct mspack_system sys; unsigned char* buf; size_t size, off; } MemFile;

static int mem_read(struct mspack_file* f, void* b, int n) {
    MemFile* m = (MemFile*)f;
    size_t t = (size_t)n < m->size - m->off ? (size_t)n : m->size - m->off;
    memcpy(b, m->buf + m->off, t); m->off += t; return (int)t;
}
static int mem_write(struct mspack_file* f, void* b, int n) {
    MemFile* m = (MemFile*)f;
    size_t t = (size_t)n < m->size - m->off ? (size_t)n : m->size - m->off;
    memcpy(m->buf + m->off, b, t); m->off += t; return (int)t;
}
static void* mem_alloc(struct mspack_system* s, size_t n) { (void)s; return calloc(n, 1); }
static void mem_free(void* p) { free(p); }
static void mem_copy(void* s, void* d, size_t n) { memmove(d, s, n); }
static void mem_msg(struct mspack_file* f, const char* fmt, ...) { (void)f; (void)fmt; }

static unsigned be32(const unsigned char* p) { return (unsigned)p[0] << 24 | (unsigned)p[1] << 16 | (unsigned)p[2] << 8 | p[3]; }
static unsigned be16(const unsigned char* p) { return (unsigned)p[0] << 8 | p[1]; }

static unsigned getbits(const unsigned char* p, unsigned bitpos, unsigned nbits) {
    unsigned v = 0;
    for (unsigned i = 0; i < nbits; i++, bitpos++)
        v = (v << 1) | ((p[bitpos >> 3] >> (7 - (bitpos & 7))) & 1);
    return v;
}

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: xcomp_ed_unpack in.s2d out.bin [-v]\n"); return 2; }
    int verbose = argc > 3 && !strcmp(argv[3], "-v");
    FILE* f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char* in = malloc(n ? n : 1);
    if (fread(in, 1, n, f) != (size_t)n) { fprintf(stderr, "read error\n"); return 1; }
    fclose(f);
    if (n < 20 || be32(in) != MAGIC) { fprintf(stderr, "%s: not a 0x0FF512ED XCompress file\n", argv[1]); return 1; }

    unsigned w = be32(in + 12);
    /* field layout from the game's XCTD reader (sub_823BDB30 / sub_823BE218) */
    unsigned window_bits = 15 + (w & 0xF);
    unsigned PAGE = 0x8000u << ((w >> 4) & 3);
    unsigned npages = (w >> 6) & 0xFFFF;
    unsigned widx = (w >> 22) & 3;
    unsigned width = widx == 0 ? 20 : widx == 1 ? 32 : 0;   /* table at 0x820226CC = {20, 32} */
    if (window_bits > 21 || !width) { fprintf(stderr, "unsupported header word 0x%08X\n", w); return 1; }
    if (npages == 0) { fprintf(stderr, "page count 0 (no size table) not supported, W=0x%08X\n", w); return 1; }
    unsigned hdr = 16 + (unsigned)(((unsigned long long)npages * width + 31) / 32) * 4;
    unsigned expect_pages = (unsigned)((n - 1) / PAGE + 1);
    if ((long)hdr > n) { fprintf(stderr, "header (%u bytes) larger than file\n", hdr); return 1; }
    if (npages != expect_pages)
        fprintf(stderr, "warning: header says %u pages, file size implies %u\n", npages, expect_pages);

    unsigned long long total = 0;
    unsigned* psize = calloc(npages, sizeof *psize);
    for (unsigned i = 0; i < npages; i++) { psize[i] = getbits(in + 16, i * width, width); total += psize[i]; }
    if (verbose) {
        printf("hash %08X  W %08X  window 2^%u  page 0x%X  pages %u  width %u  header %u bytes  total %llu\n",
               be32(in + 8), w, window_bits, PAGE, npages, width, hdr, total);
    }

    unsigned char* out = malloc(total ? total : 1);
    unsigned char* stream = malloc(PAGE);
    struct mspack_system sys; memset(&sys, 0, sizeof sys);
    sys.read = mem_read; sys.write = mem_write; sys.alloc = mem_alloc; sys.free = mem_free;
    sys.copy = mem_copy; sys.message = mem_msg;

    unsigned long long opos = 0;
    int bad = 0;
    for (unsigned pg = 0; pg < npages; pg++) {
        long pstart = pg == 0 ? hdr : (long)pg * PAGE;
        long pend = (long)(pg + 1) * PAGE; if (pend > n) pend = n;
        if (pstart >= n) { fprintf(stderr, "page %u starts past EOF\n", pg); bad = 1; break; }
        /* gather this page's frames into one LZX stream */
        size_t slen = 0; unsigned frames = 0; long p = pstart;
        while (p + 2 <= pend) {
            unsigned cs = be16(in + p);
            if (cs == 0) break;
            if (p + 2 + cs > pend) { fprintf(stderr, "page %u: frame at 0x%lX (size %u) overruns page\n", pg, p, cs); bad = 1; break; }
            memcpy(stream + slen, in + p + 2, cs); slen += cs; p += 2 + cs; frames++;
        }
        if (bad) break;
        unsigned expect_frames = (psize[pg] + 0x7FFF) / 0x8000;
        if (frames != expect_frames)
            fprintf(stderr, "page %u: %u frames stored, size %u implies %u\n", pg, frames, psize[pg], expect_frames);
        MemFile mi = { sys, stream, slen, 0 }, mo = { sys, out + opos, psize[pg], 0 };
        struct lzxd_stream* s = lzxd_init(&sys, (struct mspack_file*)&mi, (struct mspack_file*)&mo,
                                          (int)window_bits, 0, 4096, (off_t)psize[pg], 0);
        if (!s) { fprintf(stderr, "lzxd_init failed\n"); return 1; }
        int r = lzxd_decompress(s, (off_t)psize[pg]);
        lzxd_free(s);
        if (verbose)
            printf("page %u: file 0x%06lX..0x%06lX  frames %u  lzx %zu bytes (read %zu)  out %u  r=%d\n",
                   pg, pstart, p, frames, slen, mi.off, psize[pg], r);
        if (r || mo.off != psize[pg]) { fprintf(stderr, "page %u: lzxd error %d (out %zu of %u)\n", pg, r, mo.off, psize[pg]); bad = 1; break; }
        opos += psize[pg];
    }
    if (bad) return 1;
    f = fopen(argv[2], "wb");
    if (!f) { perror(argv[2]); return 1; }
    fwrite(out, 1, (size_t)total, f); fclose(f);
    printf("ok %llu bytes, %u page(s)\n", total, npages);
    return 0;
}
