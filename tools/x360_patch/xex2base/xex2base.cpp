// xex2base: default.xex -> basefile (decrypted, decompressed, memory layout).
// Thin CLI over imas2pc src/core/xex_basefile.cpp (compiled in by build.bat).
//   xex2base <in.xex> <out.bin>     prints "load=0xXXXXXXXX size=N"
#include <cstdio>
#include <string>
#include <vector>
#include "xex_basefile.h"

int main(int argc, char** argv) {
    if (argc != 3) { fprintf(stderr, "usage: xex2base <in.xex> <out.bin>\n"); return 2; }
    std::vector<uint8_t> out;
    uint32_t load = 0;
    std::string err;
    if (!xex_file_to_basefile(argv[1], out, &load, &err)) { fprintf(stderr, "error: %s\n", err.c_str()); return 1; }
    FILE* f = fopen(argv[2], "wb");
    if (!f || fwrite(out.data(), 1, out.size(), f) != out.size()) { fprintf(stderr, "error: cannot write %s\n", argv[2]); return 1; }
    fclose(f);
    printf("load=0x%08X size=%zu\n", load, out.size());
    return 0;
}
