# -*- coding: utf-8 -*-
"""
patch_attract.py — scene/attract.mpc 내장 SCB 패치 (어트랙트 데모 대사)

구조 (2026-10-12 확인):
  attract.mpc = 평문 pac 컨테이너 (암호화 없음, AES 푸터 없음)
    0x000        헤더 ('pac\0', +0x08 = 서브파일 크기 합, +0x0C = 서브파일 수 2)
    0x040+i*0x20 서브파일 레코드 (+8 size, +12 ofs; ofs는 0x120 기준)
    0x080        MSG 매니페스트 (이름표: all_dem_01.scb, resource/gscript/all,
                 all_dem_02.scb — 크기 참조 없음, 수정 불필요)
    0x120        서브파일 0 = dec(all/all_dem_01.scb)와 바이트 동일한 내부 pac
    ...+16B pad  서브파일 1 = dec(all/all_dem_02.scb)와 바이트 동일한 내부 pac
    ...+16B pad  EOF
  외곽에서 갱신할 크기 참조는 +0x08, rec0.size(+0x48), rec1.size(+0x68),
  rec1.ofs(+0x6C) 4곳뿐 (0x00~0x140 전수 스캔으로 확인).

흐름:
  1. 순정 attract.mpc 확보 — 최초 실행 시 live 파일이 순정인지 검증 후
     attract.mpc.orig 백업 생성. 이후엔 항상 .orig에서 읽음 (재패치 오염 방지).
  2. 내장 SCB를 excel2scb와 동일한 코드 경로(translation_2 로드 → rewrap →
     테이블 리빌드 → 내부 pac 헤더 4필드 갱신)로 패치한 dec 생성.
  3. 외곽 pac 재조립 + 내장 게이트 검증 통과 시에만 tools/output_scene/에 저장.
  4. 배포는 `--deploy`로만 (백업 확인 + 복사 + 바이트 무결성 검사).

사용: python patch_attract.py           (패치 + 검증 → output_scene/attract.mpc)
      python patch_attract.py --deploy  (위 과정 후 scene/attract.mpc에 배포)
"""
import os, sys, struct, shutil, filecmp

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
sys.path.insert(0, GAME_TOOLS)
import scb_common as common
import excel2scb as e2s

USRDIR      = os.path.dirname(os.path.dirname(common.GSCRIPT_DIR))
ATTRACT     = os.path.join(USRDIR, "resource", "scene", "attract.mpc")
ATTRACT_BAK = ATTRACT + ".orig"          # 순정 백업 (최초 실행 시 생성, 이후 읽기 전용)
OUT_PATH    = os.path.join(GAME_TOOLS, "output_scene", "attract.mpc")

BASE = 0x120                              # 서브파일 데이터 시작 (rec ofs 기준점)
PAD  = 16                                 # 각 서브파일 뒤 0x00 패딩
EMBEDDED = ["all/all_dem_01.scb", "all/all_dem_02.scb"]   # rec 순서와 동일


def read_records(data: bytes):
    nsub = struct.unpack_from(">I", data, 0x0C)[0]
    recs = []
    for i in range(nsub):
        rec = 0x40 + i * 0x20
        sz = struct.unpack_from(">I", data, rec + 8)[0]
        of = struct.unpack_from(">I", data, rec + 12)[0]
        recs.append((sz, of))
    return recs


def ensure_pristine():
    """순정 attract.mpc 바이트 반환. .orig 백업이 없으면 live가 순정인지
    (내장 서브파일 == 순정 gscript dec) 검증한 뒤 백업을 만든다."""
    if os.path.exists(ATTRACT_BAK):
        return open(ATTRACT_BAK, "rb").read()

    data = open(ATTRACT, "rb").read()
    if data[:4] != b"pac\x00":
        raise ValueError("attract.mpc가 pac 컨테이너가 아닙니다")
    recs = read_records(data)
    if len(recs) != len(EMBEDDED):
        raise ValueError(f"서브파일 수가 예상(2)과 다름: {len(recs)}")
    for (sz, of), rel in zip(recs, EMBEDDED):
        scb = open(os.path.join(e2s.ORIG_DIR, rel.replace("/", os.sep)), "rb").read()
        dec = common.decrypt_scb(scb)
        if data[BASE + of:BASE + of + sz] != dec:
            raise ValueError(
                f"live attract.mpc의 내장 {rel}이 순정 dec와 다릅니다 — "
                f"이미 패치/오염된 파일. 순정 attract.mpc를 복원한 뒤 다시 실행하세요.")
    shutil.copy2(ATTRACT, ATTRACT_BAK)
    print(f"순정 백업 생성: {ATTRACT_BAK}")
    return data


def build_patched_dec(rel: str, abs_to_tr: dict, font_map: dict):
    """excel2scb.patch_one_scb와 동일 경로로 패치된 dec 생성 (암호화 없이 반환).
    Returns (new_dec, expected_texts: dict[index] = 매핑 적용된 최종 문자열, warns)"""
    scb = open(os.path.join(e2s.ORIG_DIR, rel.replace("/", os.sep)), "rb").read()
    dec = common.decrypt_scb(scb)
    secs = common.parse_section_dir(dec)
    msg_abs, msg_size = secs["MSG"]
    parsed = e2s.parse_msg_table(dec, msg_abs)

    abs_to_index = {s["abs_offset"]: s["index"] for s in parsed["strings"]}
    text_to_indices = {}
    for s in parsed["strings"]:
        text_to_indices.setdefault(s["text"].strip(), []).append(s["index"])

    new_by_idx = {}
    warns = []
    misses = garbage = 0
    for abs_off, (orig, tr) in abs_to_tr.items():
        if e2s.is_garbage_translation(tr):
            garbage += 1
            continue
        idx = abs_to_index.get(abs_off)
        if idx is None:
            cand = [c for c in text_to_indices.get(orig.strip(), []) if c not in new_by_idx]
            if len(cand) == 1:
                idx = cand[0]
            else:
                misses += 1
                continue
        new_by_idx[idx] = e2s.rewrap(tr)
    if misses:
        warns.append(f"abs_offset 매칭 실패 {misses}개")
    if garbage:
        warns.append(f"LLM 쓰레기 번역 {garbage}개 스킵")

    new_msg = e2s.build_msg_block(parsed, new_by_idx, font_map, msg_size)
    new_dec, _ = e2s.replace_msg_section(dec, msg_abs, msg_size, new_msg)

    expected = {}
    for s in parsed["strings"]:
        t = new_by_idx.get(s["index"], s["text"])
        expected[s["index"]] = e2s.apply_font_mapping(t, font_map)
    return new_dec, expected, len(new_by_idx), warns


def assemble(pristine: bytes, patched_decs: list):
    """외곽 pac 재조립: 헤더/매니페스트는 순정 그대로, 서브파일 교체 + 크기 4필드 갱신."""
    out = bytearray(pristine[:BASE])
    sizes, offs = [], []
    pos = 0
    for dec in patched_decs:
        assert len(dec) % 16 == 0, "서브파일 크기가 16배수가 아님"
        offs.append(pos)
        sizes.append(len(dec))
        out += dec
        out += b"\x00" * PAD
        pos += len(dec) + PAD
    # +0x08 = 서브파일 크기 합 / rec 테이블 갱신
    struct.pack_into(">I", out, 0x08, sum(sizes))
    for i, (sz, of) in enumerate(zip(sizes, offs)):
        rec = 0x40 + i * 0x20
        struct.pack_into(">I", out, rec + 8, sz)
        struct.pack_into(">I", out, rec + 12, of)
    return bytes(out)


def validate(built: bytes, pristine: bytes, expected_texts: list):
    """내장 게이트: 외곽 구조 invariant + 내장 SCB 재파싱으로 번역 반영 확인."""
    errors = []
    if built[:4] != b"pac\x00":
        errors.append("외곽 pac magic 깨짐")
    recs = read_records(built)
    total = struct.unpack_from(">I", built, 0x08)[0]
    if total != sum(sz for sz, _ in recs):
        errors.append(f"+0x08({total:#x}) != 크기 합({sum(sz for sz, _ in recs):#x})")
    end = BASE
    for i, (sz, of) in enumerate(recs):
        if BASE + of != end:
            errors.append(f"rec{i} ofs 불일치: {BASE+of:#x} != {end:#x}")
        end = BASE + of + sz + PAD
    if end != len(built):
        errors.append(f"EOF 불일치: {end:#x} != {len(built):#x}")
    # 헤더·매니페스트가 순정과 동일한지 (갱신 4필드 제외)
    def mask(h):
        h = bytearray(h[:BASE])
        for o in (0x08, 0x48, 0x68, 0x6C):
            h[o:o+4] = b"\x00" * 4
        return bytes(h)
    if mask(built) != mask(pristine):
        errors.append("외곽 헤더가 크기 4필드 외의 위치에서 변경됨")

    p_recs = read_records(pristine)
    for i, ((sz, of), expected) in enumerate(zip(recs, expected_texts)):
        sub = built[BASE + of:BASE + of + sz]
        p_sz, p_of = p_recs[i]
        p_sub = pristine[BASE + p_of:BASE + p_of + p_sz]
        if sub[:4] != b"pac\x00":
            errors.append(f"sub{i}: 내부 pac magic 깨짐")
            continue
        try:
            secs = common.parse_section_dir(sub)
            msg_abs, msg_size = secs["MSG"]
            parsed = e2s.parse_msg_table(sub, msg_abs)
            p_secs = common.parse_section_dir(p_sub)
            p_msg_abs, p_msg_size = p_secs["MSG"]
        except Exception as ex:
            errors.append(f"sub{i}: 섹션 파싱 실패 {ex}")
            continue
        if parsed["count"] != len(expected):
            errors.append(f"sub{i}: MSG count {parsed['count']} != {len(expected)}")
            continue
        bad = [s["index"] for s in parsed["strings"] if s["text"] != expected[s["index"]]]
        if bad:
            errors.append(f"sub{i}: 문자열 불일치 {len(bad)}개 (예: index {bad[:5]})")
        # MSG 밖 영역(앞: pac/SCB 헤더 크기필드 제외, 뒤: 컷씬 pac 등)이 보존됐는지
        delta = msg_size - p_msg_size
        if sub[msg_abs + msg_size:] != p_sub[p_msg_abs + p_msg_size:]:
            errors.append(f"sub{i}: MSG 이후 데이터(컷씬 pac 등) 변형됨")
        if struct.unpack_from(">I", sub, 0x08)[0] != struct.unpack_from(">I", p_sub, 0x08)[0] + delta:
            errors.append(f"sub{i}: 내부 pac +0x08 갱신 오류")
    return errors


def main():
    deploy = "--deploy" in sys.argv
    print("=" * 60)
    print("  scene/attract.mpc 내장 SCB 패치")
    print("=" * 60)

    pristine = ensure_pristine()
    font_map = e2s.load_font_mapping()
    excel_path = e2s.choose_excel_path()
    print(f"번역 엑셀: {os.path.basename(excel_path)}")
    translations = e2s.load_translations(excel_path)

    patched_decs, expected_all = [], []
    for rel in EMBEDDED:
        abs_to_tr = translations.get(rel, {})
        new_dec, expected, n_applied, warns = build_patched_dec(rel, abs_to_tr, font_map)
        print(f"  {rel}: 번역 {n_applied}/{len(expected)}줄 적용"
              + (f" ({'; '.join(warns)})" if warns else ""))
        patched_decs.append(new_dec)
        expected_all.append(expected)

    built = assemble(pristine, patched_decs)
    errors = validate(built, pristine, expected_all)
    if errors:
        print("\n❌ 검증 실패 — 저장/배포하지 않음:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(built)
    print(f"\n✅ 검증 통과 → {OUT_PATH}")
    print(f"   크기: {len(pristine):,} → {len(built):,} 바이트")

    if deploy:
        if not os.path.exists(ATTRACT_BAK):
            print("❌ 순정 백업(.orig)이 없어 배포 중단")
            sys.exit(1)
        shutil.copy2(OUT_PATH, ATTRACT)
        if not filecmp.cmp(OUT_PATH, ATTRACT, shallow=False):
            print("❌ 배포 무결성 확인 실패")
            sys.exit(1)
        print(f"✅ 배포 완료: {ATTRACT}")
    else:
        print("   배포하려면: python patch_attract.py --deploy")


if __name__ == "__main__":
    main()
