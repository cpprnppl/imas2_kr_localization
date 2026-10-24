#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실행 파일 하드코딩 문구 한글 주입 — 360 PC 포트 패치 파일 + PS3 RPCS3 patch.yml (§41, KOR 승인 설계)

원천 (읽기만):
  exe_texts.json       문구 위치 (meta.offset = default_unpacked.xex 파일 오프셋, meta.eboot = PS3 EBOOT 위치)
  exe_translations.json (또는 --tr) 웹앱 exe 분류 회수본 {"exe:<grp>:<key>": {"jp","kr",...}} 또는 행 리스트
  360 이미지 Desktop\\unpack\\imas2\\default.exe (basefile, 파일 오프셋 == RVA)
  PS3 EBOOT 복호 사본 Desktop\\imas2_image_text\\_cache\\EBOOT.elf (정적 분석만)

360 (imas2pc src/core/kor_exe_strings.cpp가 _xstart 전에 적용, [kor] exe_strings):
  VA = 0x82000000 + offset - 0x2000.  참조 분석:
    데이터 포인터 = .text 밖 BE32 워드 == VA,  코드 = .text의 lis rA,hi + addi rX,rA,lo (48명령 창)
  리컴파일 C++에서는 lis/addi가 즉시값이다 → 코드 참조 문자열은 **제자리만**.
  제자리 용량 = 원문(+널)을 4바이트 정렬까지 늘린 칸(그 사이가 0일 때만).
  넘치고 데이터 참조만 있으면 → .reloc(RVA 0x6D0200, 277,096B: 고정 베이스라 로더·게임이 안 읽음)에 쓰고
  포인터 워드를 옮긴다. .reloc을 가리키는 우연 일치 데이터 워드의 목표 주소는 할당에서 피한다.
  넘치고 코드 참조가 있으면 → 일본어 유지 + 단축 요청 목록.
  파일 KXS1: u32 count, (u32 addr, u32 len, orig[len], new[len])* — 전부 일치할 때만 전부 적용.
  인코딩 = 직접 한글(UTF-16BE). 폰트(직접 등록 글자 집합 = font_mapping 키) 밖 한글이면 실패.

PS3 (RPCS3 patch.yml, PPU 해시 키, 시험 때만 활성화):
  EBOOT VA = 세그먼트 매핑. 데이터 포인터(TOC·표) 참조면 재배치 가능. 인코딩 = 직접 등록 한글(§25, 360과 동일).

  python exe_inject.py analyze                 # 참조 분석 보고 (번역 불필요)
  python exe_inject.py build360 [--tr F]       # out_exe\\kor_exe_strings.bin + 보고
  python exe_inject.py deploy360               # game_kor\\kor_exe_strings.bin (gpu_run.lock 없을 때만)
  python exe_inject.py build-ps3 [--tr F]      # out_exe\\imas2_kor_exe.yml
  python exe_inject.py install-ps3             # RPCS3 patches\\imported_patch.yml + config\\patch_config.yml (상시 적용)
  python exe_inject.py uninstall-ps3           # 위 두 파일 삭제 (이 도구가 쓴 것만)
  python exe_inject.py port-texts --code … [--out D]   # PS3 기능 이식 문구: 웹앱 행 → out_exe\\retry_text.bin·difficulty_text.bin (retry-text = 같은 명령)

번역 갱신 절차 (웹앱 exe 번역이 바뀌면):
  ui-image-extract가 exe_translations.json 회수 → build360 → deploy360 (gpu_run.lock 없을 때)
                                                → build-ps3 → install-ps3 (RPCS3 종료 상태)
"""
import os
import sys
import json
import time
import shutil
import struct
import argparse
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from extract_image_text import OUT_DEFAULT  # noqa: E402
from xmb_text import MAPPING_PATH, encode_with_mapping  # noqa: E402

EXE360 = r"C:\Users\jackfilm\Desktop\unpack\imas2\default.exe"
EBOOT = os.path.join(OUT_DEFAULT, "_cache", "EBOOT.elf")
TEXTS = os.path.join(HERE, "exe_texts.json")
TR_DEFAULT = os.path.join(HERE, "exe_translations.json")
OUT = os.path.join(OUT_DEFAULT, "out_exe")
GAME_KOR = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor"
LOCK = r"C:\Users\jackfilm\Desktop\imas2pc\gpu_run.lock"
BASE = 0x82000000
XEX_HDR = 0x2000
PS3_PPU_HASH = "PPU-f942422316f63af3d64dc940b35ec8fddade0f44"


# ---------------------------------------------------------------- 공통

def load_tr(path):
    d = json.load(open(path, encoding="utf-8"))
    rows = d["rows"] if isinstance(d, dict) and "rows" in d else d
    out = {}
    if isinstance(rows, dict):
        for k, v in rows.items():
            if v.get("kr"):
                out[k if k.startswith("exe:") else f"exe:{v['grp']}:{v['key']}"] = v
    else:
        for r in rows:
            if r.get("cat") == "exe" and r.get("kr"):
                out[r.get("id") or f"exe:{r['grp']}:{r['key']}"] = r
    return out


def u16z(s):
    return s.encode("utf-16-be") + b"\x00\x00"


FONT_SET_PATH = os.path.join(os.path.dirname(os.path.dirname(HERE)), "font_patcher", "output", "font_mapping_v2.json")


def font_set():
    """직접 등록 폰트의 한글 집합. 폰트 세션 기준 파일(repatch_fonts.py NEW_CHARS와 함께 갱신)을
    우선 쓰고, 없으면 게임 tools의 font_mapping.json(같은 2,359 키)."""
    p = FONT_SET_PATH if os.path.exists(FONT_SET_PATH) else MAPPING_PATH
    return set(json.load(open(p, encoding="utf-8")).keys())


# ---------------------------------------------------------------- 360 이미지 분석

class Image360:
    def __init__(self, path=EXE360):
        self.d = open(path, "rb").read()
        d = self.d
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.secs = {}
        for i in range(nsec):
            o = pe + 24 + opt + i * 40
            name = d[o:o + 8].rstrip(b"\0").decode()
            vsz, va = struct.unpack_from("<II", d, o + 8)
            self.secs[name] = (va, vsz)
        self.text = self.secs[".text"]
        r = self.secs[".reloc"]
        self.reloc = (r[0], r[0] + r[1])

    def refs(self, vas):
        """{va: (data_word_rvas, code_addi_rvas)}"""
        d = self.d
        tlo, thi = self.text[0], self.text[0] + self.text[1]
        want = set(vas)
        data = defaultdict(list)
        for o in range(0, len(d) - 3, 4):
            if tlo <= o < thi:
                continue
            w = struct.unpack_from(">I", d, o)[0]
            if w in want:
                data[w].append(o)
        lo_idx = defaultdict(list)
        for va in want:
            lo_idx[va & 0xFFFF].append((va, ((va + 0x8000) >> 16) & 0xFFFF))
        code = defaultdict(list)
        for o in range(tlo, thi, 4):
            ins = struct.unpack_from(">I", d, o)[0]
            if ins >> 26 != 14 or (ins & 0xFFFF) not in lo_idx:
                continue
            ra = (ins >> 16) & 31
            for va, hi in lo_idx[ins & 0xFFFF]:
                for back in range(1, 48):
                    p = o - back * 4
                    if p < tlo:
                        break
                    j = struct.unpack_from(">I", d, p)[0]
                    if j >> 26 == 15 and ((j >> 21) & 31) == ra and ((j >> 16) & 31) == 0:
                        if (j & 0xFFFF) == hi:
                            code[va].append(o)
                        break
        return {va: (data.get(va, []), code.get(va, [])) for va in want}

    def reloc_avoid(self):
        """.reloc 안을 가리키는 데이터 워드(우연 일치)의 목표 주소 — 할당에서 피한다."""
        lo, hi = BASE + self.reloc[0], BASE + self.reloc[1]
        tlo, thi = self.text[0], self.text[0] + self.text[1]
        hits = []
        for o in range(0, len(self.d) - 3, 4):
            if tlo <= o < thi:
                continue
            w = struct.unpack_from(">I", self.d, o)[0]
            if lo <= w < hi:
                hits.append((BASE + o, w))
        return hits

    def reloc_code_refs(self):
        """.text에서 lis rA,<.reloc 상위 반> 개수 (0이어야 함)."""
        lo, hi = BASE + self.reloc[0], BASE + self.reloc[1]
        his = {((v + 0x8000) >> 16) & 0xFFFF for v in range(lo, hi, 0x100)}
        tlo, thi = self.text[0], self.text[0] + self.text[1]
        n = 0
        for o in range(tlo, thi, 4):
            i = struct.unpack_from(">I", self.d, o)[0]
            if i >> 26 == 15 and ((i >> 16) & 31) == 0 and (i & 0xFFFF) in his:
                n += 1
        return n


def rows360():
    rows = json.load(open(TEXTS, encoding="utf-8"))
    return {k: v for k, v in rows.items() if v["grp"] == "xex360"}


def analyze(_a):
    img = Image360()
    rows = rows360()
    vas = {BASE + v["meta"]["offset"] - XEX_HDR: k for k, v in rows.items()}
    bad = [k for va, k in vas.items() if img.d[va - BASE:va - BASE + len(u16z(rows[k]["jp"]))] != u16z(rows[k]["jp"])]
    refs = img.refs(vas)
    st = Counter()
    for va, (dr, cr) in refs.items():
        st["데이터만" if dr and not cr else "코드만" if cr and not dr else "둘다" if dr else "없음"] += 1
    print(f"xex360 {len(rows)}행, 원문 위치 불일치 {len(bad)}")
    print("참조:", dict(st))
    print(f".reloc RVA 0x{img.reloc[0]:X}-0x{img.reloc[1]:X} ({img.reloc[1] - img.reloc[0]:,}B): "
          f".text lis(상위 반) {img.reloc_code_refs()}건, 데이터 워드 {len(img.reloc_avoid())}건")
    for at, w in img.reloc_avoid():
        print(f"   우연 일치 워드 @0x{at:08X} -> 0x{w:08X} (할당 회피)")


# ---------------------------------------------------------------- 360 빌드

def build360(a):
    img = Image360()
    rows = rows360()
    tr = load_tr(a.tr)
    fonts = font_set()
    vas = {BASE + v["meta"]["offset"] - XEX_HDR: k for k, v in rows.items()}
    refs = img.refs(vas)
    avoid = {w for _at, w in img.reloc_avoid()}
    rlo, rhi = BASE + img.reloc[0], BASE + img.reloc[1]
    cur = (rlo + 15) & ~15
    recs = []
    rep = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "inplace": [], "reloc": [], "overflow": [], "font": [],
           "no_kr": 0, "no_ref": []}
    used = []
    for va, k in sorted(vas.items()):
        r = rows[k]
        t = tr.get(k)
        if not t or not t.get("kr"):
            rep["no_kr"] += 1
            continue
        kr = t["kr"].replace("\r\n", "\n")
        if t.get("jp") and t["jp"].replace("\r\n", "\n") != r["jp"]:
            rep.setdefault("jp_mismatch", []).append(k)
            continue
        miss = sorted({c for c in kr if "가" <= c <= "힣" and c not in fonts})
        if miss:
            rep["font"].append({"key": k, "chars": "".join(miss)})
            continue
        orig = u16z(r["jp"])
        rva = va - BASE
        assert img.d[rva:rva + len(orig)] == orig, k
        cap = len(orig)
        while cap % 4 and img.d[rva + cap] == 0:
            cap += 1
        new = u16z(kr)
        dr, cr = refs[va]
        if len(new) <= cap:
            recs.append((va, img.d[rva:rva + cap], new + b"\x00" * (cap - len(new))))
            rep["inplace"].append({"key": k, "jp": r["jp"], "kr": kr, "bytes": f"{len(new)}/{cap}"})
            continue
        if cr or not dr:
            why = "코드 즉시값 참조" if cr else "참조 없음(계산 주소)"
            rep["overflow"].append({"key": k, "jp": r["jp"], "kr": kr, "kr_chars": len(kr),
                                    "max_chars": cap // 2 - 1, "why": why})
            if not dr and not cr:
                rep["no_ref"].append(k)
            continue
        # 재배치: 16 정렬, 회피 주소를 포함하지 않는 자리
        while any(cur <= w < cur + len(new) for w in avoid):
            cur = (cur + 16 + 15) & ~15
        if cur + len(new) > rhi:
            rep["overflow"].append({"key": k, "jp": r["jp"], "kr": kr, "why": ".reloc 공간 부족"})
            continue
        at = cur
        cur = (cur + len(new) + 15) & ~15
        recs.append((at, img.d[at - BASE:at - BASE + len(new)], new))
        used.append((at, at + len(new)))
        for w in dr:
            recs.append((BASE + w, struct.pack(">I", va), struct.pack(">I", at)))
        rep["reloc"].append({"key": k, "jp": r["jp"], "kr": kr, "at": f"0x{at:08X}", "ptrs": len(dr)})
    # 게이트
    spans = sorted((a_, a_ + len(o)) for a_, o, _n in recs)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2, f"레코드 겹침 0x{s1:08X}/0x{s2:08X}"
    for a_, o, n in recs:
        assert len(o) == len(n) and img.d[a_ - BASE:a_ - BASE + len(o)] == o
    for s, e in used:
        assert rlo <= s and e <= rhi and not any(s <= w < e for w in avoid)
    # 시뮬레이션: 적용 후 각 문자열을 참조 경로로 다시 읽어 kr인지
    sim = bytearray(img.d)
    for a_, o, n in recs:
        sim[a_ - BASE:a_ - BASE + len(n)] = n
    for it in rep["inplace"] + rep["reloc"]:
        va = BASE + rows[it["key"]]["meta"]["offset"] - XEX_HDR
        dr, cr = refs[va]
        targets = [struct.unpack_from(">I", sim, w)[0] for w in dr] + ([va] if cr or not dr else [])
        for tva in targets:
            o = tva - BASE
            e = o
            while sim[e:e + 2] != b"\x00\x00":
                e += 2
            assert sim[o:e].decode("utf-16-be") == it["kr"], f"시뮬 불일치 {it['key']}"
    os.makedirs(OUT, exist_ok=True)
    blob = b"KXS1" + struct.pack(">I", len(recs)) + b"".join(
        struct.pack(">II", a_, len(o)) + o + n for a_, o, n in recs)
    open(os.path.join(OUT, "kor_exe_strings.bin"), "wb").write(blob)
    json.dump(rep, open(os.path.join(OUT, "report_360.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"360: 번역 있음 {len(rows) - rep['no_kr']}/{len(rows)} → 제자리 {len(rep['inplace'])} · 재배치 {len(rep['reloc'])}"
          f" · 용량 초과(일본어 유지) {len(rep['overflow'])} · 폰트 밖 {len(rep['font'])}"
          f" | 레코드 {len(recs)}, {len(blob):,}B → {OUT}\\kor_exe_strings.bin")
    if rep["overflow"]:
        print("  용량 초과:", ", ".join(f"{o['jp'][:8]}→{o['kr'][:8]}({o.get('max_chars', '?')}자)" for o in rep["overflow"][:12]))
    return 0


def deploy360(_a):
    if os.path.exists(LOCK):
        sys.exit(f"[중단] {LOCK} 존재 — 게임 실행 중")
    for fn in ("kor_exe_strings.bin", *PORT_TEXTS):    # PORT_TEXTS: PS3 기능 이식 예/아니요 문구(<disc_root>에서 읽음)
        src = os.path.join(OUT, fn)
        if fn in PORT_TEXTS and not os.path.exists(src):
            continue
        dst = os.path.join(GAME_KOR, fn)
        if os.path.exists(dst):
            shutil.copy2(dst, dst + time.strftime(".bak_%Y%m%d_%H%M%S"))
        shutil.copy2(src, dst)
        print(f"배포: {dst} (실행: IMAS2PC_DISC_ROOT={GAME_KOR})")


# ---------------------------------------------------------------- PS3

class Eboot:
    def __init__(self, path=EBOOT):
        self.d = open(path, "rb").read()
        e = self.d
        phoff = struct.unpack_from(">Q", e, 0x20)[0]
        phnum, = struct.unpack_from(">H", e, 0x38)
        phes, = struct.unpack_from(">H", e, 0x36)
        self.segs = []
        for i in range(phnum):
            o = phoff + i * phes
            t, fl = struct.unpack_from(">II", e, o)
            off, va, _pa, fsz, msz = struct.unpack_from(">QQQQQ", e, o + 8)
            if t == 1 and fsz:
                self.segs.append((off, va, fsz, msz, fl))

    def f2v(self, fo):
        for off, va, fsz, _m, _f in self.segs:
            if off <= fo < off + fsz:
                return va + fo - off

    def v2f(self, v):
        for off, va, fsz, _m, _f in self.segs:
            if va <= v < va + fsz:
                return off + v - va


def build_ps3(a):
    eb = Eboot()
    tr = load_tr(a.tr)
    mapping = font_set()
    rows = json.load(open(TEXTS, encoding="utf-8"))
    items = []
    for k, v in rows.items():
        t = tr.get(k)
        if not t or not t.get("kr"):
            continue
        locs = v["meta"].get("eboot") or ([{"offset": v["meta"]["offset"], "enc": v["meta"].get("enc", "u16")}]
                                          if v["grp"] == "eboot_ps3" else [])
        for loc in locs:
            items.append((k, v, t, loc))
    vas = {}
    for k, v, t, loc in items:
        vas[eb.f2v(loc["offset"])] = (k, v, t, loc)
    words = defaultdict(list)
    e = eb.d
    for o in range(0, len(e) - 3, 4):
        w = struct.unpack_from(">I", e, o)[0]
        if w in vas:
            words[w].append(o)
    missing = set()
    patches, rep = [], {"inplace": 0, "reloc": 0, "overflow": [], "skip_enc": []}
    # 재배치 공간: EBOOT 안에는 안전한 빈 영역이 없어(데이터 세그먼트의 0 구간은 0 초기화 변수일 수 있음)
    # RPCS3 patch의 alloc으로 ELF·PRX가 쓰지 않는 메인 메모리 상단에 블록을 받는다(--alloc-at).
    free_lo, free_hi = a.alloc_at, a.alloc_at + a.alloc_size
    cur = free_lo
    for va, (k, v, t, loc) in sorted(vas.items()):
        if loc.get("enc", "u16") != "u16":
            rep["skip_enc"].append(k)
            continue
        jp = v["jp"]
        kr_src = t["kr"].replace("\r\n", "\n")
        fo = loc["offset"]
        orig = u16z(jp)
        if e[fo:fo + len(orig)] != orig:
            # xex와 EBOOT가 앞뒤 전각 공백(U+3000)만 다른 짝(ui 페어링 규칙): EBOOT 원문에 맞춰 kr에서도 뺀다
            jp2 = jp.strip("　")
            orig = u16z(jp2)
            if jp2 == jp or e[fo:fo + len(orig)] != orig:
                rep["overflow"].append({"key": k, "why": "EBOOT 원문 불일치"})
                continue
            jp, kr_src = jp2, kr_src.strip("　")
        # PS3 폰트도 직접 등록(§25: 한글 코드 2,359자, 매핑 한자 슬롯은 없음) → 원시 한글
        missing |= {c for c in kr_src if "가" <= c <= "힣" and c not in mapping}
        kr = kr_src
        new = u16z(kr)
        cap = len(orig)
        while cap % 4 and e[fo + cap] == 0:
            cap += 1
        if len(new) <= cap:
            patches.append((va, new + b"\x00" * (cap - len(new)), f"{k} 제자리"))
            rep["inplace"] += 1
            continue
        ptrs = words.get(va, [])
        if not ptrs or cur + len(new) > free_hi:
            rep["overflow"].append({"key": k, "jp": jp, "kr": t["kr"], "why": "포인터 없음" if not ptrs else "공간 부족"})
            continue
        at = cur
        cur = (cur + len(new) + 15) & ~15
        patches.append((at, new, f"{k} 재배치"))
        for w in ptrs:
            patches.append((eb.f2v(w), struct.pack(">I", at), f"{k} 포인터"))
        rep["reloc"] += 1
    os.makedirs(OUT, exist_ok=True)
    lines = ["Version: 1.2", "", f"{PS3_PPU_HASH}:", '  "iM@S2 KOR exe strings (imas2_kr_localization exe_inject.py)":',
             "    Games:", '      "THE iDOLM@STER 2":', "        NPJB00337: [ All ]",
             "    Author: \"imas2 KOR\"", "    Notes: \"실행 파일 하드코딩 문구 한글화 (직접 등록 한글)\"",
             "    Patch Version: 1.0", "    Patch:"]
    if cur > free_lo:
        lines.append(f"      - [ alloc, 0x{free_lo:08x}, 0x{a.alloc_size:x} ] # 재배치 문자열 블록")
    for va, b, note in patches:
        lines += ps3_words(va, b, note)
    open(os.path.join(OUT, "imas2_kor_exe.yml"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    rep["font_missing"] = "".join(sorted(missing))
    rep["free"] = [hex(free_lo), hex(free_hi), hex(cur)]
    json.dump(rep, open(os.path.join(OUT, "report_ps3.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"PS3: 패치 {len(patches)}줄 (제자리 {rep['inplace']} · 재배치 {rep['reloc']} · 초과 {len(rep['overflow'])}"
          f" · SJIS 생략 {len(rep['skip_enc'])}) 폰트 매핑 누락 {len(missing)} → {OUT}\\imas2_kor_exe.yml")
    return 0


def ps3_words(va, b, note):
    """RPCS3 patch 타입에 bytes가 없다 → be32(4정렬)·be16 조각으로 쓴다."""
    out, i = [], 0
    while i < len(b):
        if (va + i) % 4 == 0 and i + 4 <= len(b):
            out.append(f"      - [ be32, 0x{va + i:08x}, 0x{b[i:i + 4].hex()} ]")
            i += 4
        else:
            out.append(f"      - [ be16, 0x{va + i:08x}, 0x{b[i:i + 2].hex()} ]")
            i += 2
    out[0] += f" # {note}"
    return out


def find_zero_run(eb, need=0x4000):
    """쓰기 가능 데이터 세그먼트의 파일 영역 안에서 가장 긴 0 구간(재배치용 후보). 정적으로만 판단하므로
    보고서에 위치를 남기고 RPCS3 시험으로 확인한다."""
    best = (0, 0)
    for off, va, fsz, _m, fl in eb.segs:
        if not fl & 2:     # PF_W
            continue
        e = eb.d
        i = off
        end = off + fsz
        while i < end:
            if e[i] == 0:
                j = i
                while j < end and e[j] == 0:
                    j += 1
                if j - i > best[1] - best[0]:
                    best = (va + i - off, va + j - off)
                i = j
            else:
                i += 1
    lo, hi = best
    lo = (lo + 0x100 + 15) & ~15          # 앞뒤 여유
    hi = hi - 0x100
    if hi - lo < need:
        return lo, lo
    return lo, hi


# ---------------------------------------------------------------- PS3 상시 설치 (사용자 승인 2026-10-23)

RPCS3 = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc"
RP_PATCH = os.path.join(RPCS3, "patches", "imported_patch.yml")
RP_CONFIG = os.path.join(RPCS3, "config", "patch_config.yml")
PATCH_TITLE = "iM@S2 KOR exe strings (imas2_kr_localization exe_inject.py)"
CONFIG_BLOCK = (f"{PS3_PPU_HASH}:\n  \"{PATCH_TITLE}\":\n    \"THE iDOLM@STER 2\":\n      NPJB00337:\n"
                f"        All:\n          Enabled: true\n")


def _rpcs3_running():
    import subprocess
    out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout.lower()
    return "rpcs3.exe" in out


def install_ps3(_a):
    """out_exe\\imas2_kor_exe.yml → RPCS3 patches\\imported_patch.yml + config\\patch_config.yml(활성).
    두 파일은 이 도구 전용으로 쓴다(원래 없던 파일). 다른 내용이 있으면 백업 후 중단."""
    if _rpcs3_running():
        sys.exit("[중단] RPCS3 실행 중 — 종료 후 다시")
    src = os.path.join(OUT, "imas2_kor_exe.yml")
    for p in (RP_PATCH, RP_CONFIG):
        if os.path.exists(p) and PATCH_TITLE not in open(p, encoding="utf-8").read():
            shutil.copy2(p, p + time.strftime(".bak_%Y%m%d_%H%M%S"))
            sys.exit(f"[중단] {p}에 다른 패치가 있음(백업함) — 수동 병합 필요")
    shutil.copy2(src, RP_PATCH)
    open(RP_CONFIG, "w", encoding="utf-8").write(CONFIG_BLOCK)
    print(f"설치: {RP_PATCH}\n      {RP_CONFIG} (Enabled: true)\n되돌리기: python exe_inject.py uninstall-ps3")


def uninstall_ps3(_a):
    if _rpcs3_running():
        sys.exit("[중단] RPCS3 실행 중 — 종료 후 다시")
    for p in (RP_PATCH, RP_CONFIG):
        if os.path.exists(p):
            if PATCH_TITLE not in open(p, encoding="utf-8").read():
                print(f"[건너뜀] {p}: 이 도구가 쓴 파일이 아님")
                continue
            os.remove(p)
            print(f"삭제: {p}")


# ---------------------------------------------------------------- PS3 기능 이식: 리트라이 확인 문구 (ps3-360-pc 요청)
# PC 포트 전용 예/아니요 창 문구 (ps3-360-pc 요청, 원문 없는 행은 짝 PS3 행 원문을 jp로) — <disc_root>\\<파일>을 읽는다
PORT_TEXTS = {
    "retry_text.bin": "gamedata:system:initialFix#x3:retry_001_pc",        # 리트라이(스테이지 전 대화부터 재시작)
    "difficulty_text.bin": "gamedata:system:initialFix#x14:war_144_pc",   # 새 게임 난이도(예 = HYPER, 아니요 = NORMAL)
}


def port_texts(a):
    """웹앱 행 kr → UTF-16BE + 널 2바이트 파일(PORT_TEXTS 전부). 줄바꿈 0x000A, 3줄 이하.
    360 cSelectYesNo가 sub_82271558로 쓰는 문자열과 같은 형식(직접 등록 한글, 폰트 집합 밖 글자면 실패).
    out_exe\\<파일>(+--out 폴더)에 만들고 배포는 deploy360."""
    import urllib.request
    import urllib.parse
    cfg = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
    h = {"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}", "x-team-code": a.code}
    fs = font_set()
    for fn, rid in PORT_TEXTS.items():
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{cfg['url']}/rest/v1/rows?id=eq.{urllib.parse.quote(rid, safe='')}&select=kr,st,by", headers=h)))
        if not r or not r[0]["kr"]:
            sys.exit(f"❌ 웹앱 행 {rid} 없음/미번역")
        kr = r[0]["kr"].replace("\r\n", "\n")
        if kr.count("\n") > 2:
            sys.exit(f"❌ {rid}: {kr.count(chr(10)) + 1}줄 — 3줄 이하여야 함")
        miss = sorted({c for c in kr if "가" <= c <= "힣" and c not in fs})
        if miss:
            sys.exit(f"❌ {rid}: 폰트에 없는 한글 {''.join(miss)}")
        blob = u16z(kr)
        assert blob[:-2].decode("utf-16-be") == kr
        outs = [os.path.join(OUT, fn)] + ([os.path.join(a.out, fn)] if a.out else [])
        for o in outs:
            os.makedirs(os.path.dirname(o), exist_ok=True)
            open(o, "wb").write(blob)
        print(f"{fn} ← {rid} (by {r[0]['by']}, st {r[0]['st']}) {len(kr)}자 {kr.count(chr(10)) + 1}줄 → {len(blob)}B")
        for o in outs:
            print("  →", o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["analyze", "build360", "deploy360", "build-ps3", "install-ps3", "uninstall-ps3",
                                    "port-texts", "retry-text"])
    ap.add_argument("--code", help="port-texts: 팀 암호")
    ap.add_argument("--out", help="port-texts: 추가 출력 폴더")
    ap.add_argument("--tr", default=TR_DEFAULT)
    ap.add_argument("--alloc-at", type=lambda x: int(x, 0), default=0x0F000000,
                    help="build-ps3: RPCS3 alloc 블록 주소(64KB 정렬, 메인 메모리 미사용 영역)")
    ap.add_argument("--alloc-size", type=lambda x: int(x, 0), default=0x10000)
    a = ap.parse_args()
    return {"analyze": analyze, "build360": build360, "deploy360": deploy360, "build-ps3": build_ps3,
            "install-ps3": install_ps3, "uninstall-ps3": uninstall_ps3, "port-texts": port_texts, "retry-text": port_texts}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
